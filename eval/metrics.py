"""Computes every Etap 8 Part B metric from a raw.jsonl produced by eval/run_eval.py, and
renders eval/report.md. Each metric traces back to a specific finding from the Etap 7
acceptance session (docs/odbior-etap7-notatki.md) — see the docstring on each function.

Usage:
    uv run python -m eval.metrics --raw-jsonl eval/results/<timestamp>/raw.jsonl
    uv run python -m eval.metrics --raw-jsonl eval/results/<timestamp>/raw.jsonl \\
        --classify-comparison eval/results/<timestamp>/classify_comparison.jsonl \\
        --output eval/report.md
"""

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel

from app.config import Settings
from app.graph.retry import with_retry
from eval.scenarios import SCENARIOS, SEVERITY_ORDER

# Categories treated as a "reasonable neighbor" of the expected one — a wrong-but-defensible
# call (e.g. an in-progress ransomware attack classified as malware before encryption is
# confirmed) rather than a genuine miss. Judgment calls, documented here rather than hidden
# inside a threshold: revisit if a category is added or these stop feeling right.
NEIGHBOR_CATEGORIES: dict[str, set[str]] = {
    "malware": {"ransomware"},
    "ransomware": {"malware"},
    "unauthorized_access": {"insider_threat", "data_breach"},
    "data_breach": {"unauthorized_access", "insider_threat"},
    "insider_threat": {"unauthorized_access", "data_breach"},
    "phishing": {"unauthorized_access"},
    "denial_of_service": set(),
    "other": set(),
}

CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")
REFERENCES_HEADING_RE = re.compile(r"^##\s*References", re.MULTILINE)

# A small, manual Polish (+ a few English) stopword list — no NLP dependency was added for this
# (see CLAUDE.md: don't add dependencies without asking). Good enough for a heuristic proxy, not
# meant to be linguistically rigorous.
_STOPWORDS = {
    "i", "w", "na", "z", "do", "się", "że", "który", "która", "które", "których", "jest", "są",
    "oraz", "lub", "nie", "to", "dla", "po", "od", "przez", "może", "być", "ten", "ta", "te",
    "tego", "tej", "tych", "jako", "czy", "ze", "za", "o", "a", "ale", "co", "jak", "też",
    "the", "an", "of", "and", "or", "in", "on", "for", "with", "is", "are",
}


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-ząćęłńóśźż]+", text.lower())
    return {w for w in words if len(w) >= 4 and w not in _STOPWORDS}


def load_records(raw_jsonl: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw_jsonl.read_text().splitlines() if line.strip()]


# --- Classification accuracy ------------------------------------------------------------------


def classification_accuracy(records: list[dict]) -> dict[str, Any]:
    """Exact category match, plus a looser 'reasonable neighbor' match (NEIGHBOR_CATEGORIES) —
    a classifier that confuses ransomware and malware mid-attack is behaving more reasonably
    than one that lands on denial_of_service, and treating both misses identically would hide
    that."""
    scored = [r for r in records if r.get("classification")]
    exact = [r for r in scored if r["classification"]["category"] == r["expected_category"]]
    neighbor = [
        r
        for r in scored
        if r["classification"]["category"] == r["expected_category"]
        or r["classification"]["category"] in NEIGHBOR_CATEGORIES.get(r["expected_category"], set())
    ]
    severity_ok = []
    for r in scored:
        lo, hi = r["expected_severity_range"]
        actual = r["classification"]["severity"]
        if SEVERITY_ORDER.index(lo) <= SEVERITY_ORDER.index(actual) <= SEVERITY_ORDER.index(hi):
            severity_ok.append(r)

    ambiguous = [r for r in scored if r.get("ambiguous_with")]
    unambiguous_confidences = [r["classification"]["confidence"] for r in scored if not r.get("ambiguous_with")]

    return {
        "n_scored": len(scored),
        "exact_match_rate": len(exact) / len(scored) if scored else None,
        "neighbor_match_rate": len(neighbor) / len(scored) if scored else None,
        "severity_in_range_rate": len(severity_ok) / len(scored) if scored else None,
        "misses": [
            {"scenario_id": r["scenario_id"], "expected": r["expected_category"], "actual": r["classification"]["category"]}
            for r in scored
            if r not in exact
        ],
        "ambiguous_scenario_confidence": (ambiguous[0]["classification"]["confidence"] if ambiguous else None),
        "mean_unambiguous_confidence": (
            statistics.mean(unambiguous_confidences) if unambiguous_confidences else None
        ),
    }


# --- Citations: recall (report vs. plan) and precision ----------------------------------------


def citation_recall_report(records: list[dict]) -> dict[str, Any]:
    """ZNALEZISKO #7: what fraction of generated reports use at least one [n] marker at all.
    Measured on report_markdown as returned by the graph — i.e. *after* report.py's own
    whitelist-and-strip pass already removed anything invalid, so this can only undercount
    genuine attempts, never overcount them."""
    completed = [r for r in records if r.get("report_markdown")]
    with_citation = [r for r in completed if CITATION_MARKER_RE.search(r["report_markdown"])]
    with_references = [r for r in completed if REFERENCES_HEADING_RE.search(r["report_markdown"])]
    return {
        "n_reports": len(completed),
        "recall": len(with_citation) / len(completed) if completed else None,
        "n_with_references_section": len(with_references),
        "scenarios_with_citation": [r["scenario_id"] for r in with_citation],
    }


def citation_recall_plan(records: list[dict]) -> dict[str, Any]:
    """The contrasting, already-known-to-work case: what fraction of plans have at least one
    step with a non-empty citations list. Measured for contrast with citation_recall_report,
    per the Etap 8 brief — this is the mechanism that DiagnosticPlanView renders as [1]/[2] in
    the UI, confirmed working live during the Etap 7 acceptance session."""
    plans = [r for r in records if r.get("plan")]
    with_citation = [r for r in plans if any(step.get("citations") for step in r["plan"]["steps"])]
    return {
        "n_plans": len(plans),
        "recall": len(with_citation) / len(plans) if plans else None,
    }


def citation_precision(records: list[dict]) -> dict[str, Any]:
    """For every [n] marker actually present in a report, does (source_id, page) exist in that
    thread's retrieved_chunks? Expected to be ~100% almost by construction: report.py's
    whitelist already strips any marker that fails this exact check before the report ever
    reaches this function. A value below 100% here would mean the whitelist itself has a bug;
    a value AT 100% is not a discovery, it's confirmation the mechanism works on live data —
    the real open question is citation_recall_report (does the model cite at all), not this."""
    total_markers = 0
    valid_markers = 0
    for r in records:
        markdown = r.get("report_markdown")
        if not markdown:
            continue
        # Reconstructs the exact same whitelist app/graph/report.py:_build_allowed_citations()
        # builds — every (source_id, page) from retrieved_chunks plus every plan step citation,
        # deduplicated and numbered in sorted order — so [n] can be checked precisely rather
        # than approximately.
        keys: set[tuple[str, int]] = set()
        for chunk in r.get("retrieved_chunks") or []:
            keys.add((chunk["source_id"], chunk["page"]))
        for step in (r.get("plan") or {}).get("steps", []):
            for citation in step.get("citations", []):
                keys.add((citation["source_id"], citation["page"]))
        n_allowed = len(keys)
        for match in CITATION_MARKER_RE.finditer(markdown):
            total_markers += 1
            if 1 <= int(match.group(1)) <= n_allowed:
                valid_markers += 1
    return {
        "total_markers_found": total_markers,
        "precision": (valid_markers / total_markers) if total_markers else None,
        "note": "Expected ~100% by construction — see docstring. Low total_markers_found is the real signal.",
    }


# --- Groundless action rate (ZNALEZISKO #11) ---------------------------------------------------

_TOOL_CALL_CRASH_MARKERS = ("positional argument", "block_ip")
"""Both must appear (not just one) for an error to be classified as a tool-call-argument crash
— requiring both instead of either avoids miscategorizing some unrelated future error that
happens to mention "block_ip" in passing as if it were this specific failure mode."""


def _classify_groundless_failure(record: dict) -> str | None:
    """Categorizes exactly how a groundless proposal manifested — these are genuinely different
    problems, not one, and averaging them into a single rate without saying which is which
    hides that: a Python crash before anything is even captured, a placeholder string caught by
    plain format validation (ip_address() rejects it), and — the most concerning case, since
    it's the one ZNALEZISKO #11 actually warned about — a syntactically valid-looking IP that
    was only caught because it happened to land in a reserved/test range (RFC 5737 etc.), not
    because anything detected it was fabricated. Returns None if this scenario shows no
    groundless-action evidence at all."""
    if record["status"] == "error" and record.get("error") and all(m in record["error"] for m in _TOOL_CALL_CRASH_MARKERS):
        return "crash"
    for action in record.get("proposed_actions") or []:
        preview = action.get("preview") or {}
        summary = preview.get("summary", "")
        if "Invalid IP address" in summary:
            return "invalid_format"
        if "Refused to propose blocking" in summary:
            return "looked_valid_but_reserved_range"
    return None


def groundless_action_rate(records: list[dict]) -> dict[str, Any]:
    """ZNALEZISKO #11: among scenarios with no legitimate active-tool target, what fraction
    still got a proposed action anyway. Broken down by _classify_groundless_failure's three
    distinct failure modes rather than reported as one blended rate — see that function's
    docstring for why "looked_valid_but_reserved_range" is the one that actually matters most."""
    no_target = [r for r in records if r.get("no_clear_target")]
    hits = []
    for r in no_target:
        failure_mode = _classify_groundless_failure(r)
        if failure_mode is not None:
            hits.append(
                {
                    "scenario_id": r["scenario_id"],
                    "status": r["status"],
                    "failure_mode": failure_mode,
                    "proposed_actions": r.get("proposed_actions"),
                    "error": r.get("error"),
                }
            )
    by_mode = Counter(h["failure_mode"] for h in hits)
    return {
        "n_no_clear_target": len(no_target),
        "rate": len(hits) / len(no_target) if no_target else None,
        "by_failure_mode": dict(by_mode),
        "scenarios": hits,
    }


# --- Padding score (ZNALEZISKO #9) --------------------------------------------------------------


def padding_score(records: list[dict]) -> dict[str, Any]:
    """ZNALEZISKO #9: for plans with 5+ steps, how many of the steps from position 5 onward
    have an expected_evidence field sharing NO non-trivial content word with the original
    incident description. Confirmed by hand against real data before implementing this exact
    direction: generic "padding" steps (e.g. "Informacje o potencjalnych słabościach systemu")
    reference no specific entity from the case at all, while concrete steps reuse actual names
    from the description (server names, filenames) in their expected_evidence — so LOW overlap
    is the padding signal, not high overlap."""
    scenarios_by_id = {s.id: s for s in SCENARIOS}
    plans_5plus = [r for r in records if r.get("plan") and len(r["plan"]["steps"]) >= 5]
    per_scenario = []
    for r in plans_5plus:
        # raw.jsonl doesn't store the incident description itself (only what the graph
        # produced from it) — looked up from eval/scenarios.py by id instead of duplicating it.
        description_words = _content_words(scenarios_by_id[r["scenario_id"]].description)
        steps = r["plan"]["steps"][4:]  # positions 5+ (0-indexed slice)
        generic_steps = [
            step for step in steps if not (description_words & _content_words(step.get("expected_evidence", "")))
        ]
        per_scenario.append(
            {
                "scenario_id": r["scenario_id"],
                "n_tail_steps": len(steps),
                "n_generic": len(generic_steps),
                "fraction_generic": len(generic_steps) / len(steps) if steps else None,
            }
        )
    fractions = [s["fraction_generic"] for s in per_scenario if s["fraction_generic"] is not None]
    return {
        "n_plans_with_5plus_steps": len(plans_5plus),
        "mean_fraction_generic_in_tail": statistics.mean(fractions) if fractions else None,
        "per_scenario": per_scenario,
    }


# --- Faithfulness of the Executive summary (ZNALEZISKO #5) --------------------------------------

FAITHFULNESS_MODEL = "llama-3.1-8b-instant"

FAITHFULNESS_SYSTEM_PROMPT = """You are a fact-checking assistant. You will be given a list of \
clarifying questions that were asked about a security incident, the (deliberately uncertain) \
answer given to ALL of them, and the "Executive summary" section of a report about that \
incident. List any sentences in the summary that state something as a definite fact when the \
underlying information was explicitly marked as unknown/uncertain in the answers (e.g. claiming \
an attack "is no longer active" when the true answer was "we don't know"). Return ONLY a JSON \
list of the suspicious sentences (in the summary's own language), or an empty list if none. Do \
not explain, do not judge severity — just list them."""


class SuspiciousSentences(BaseModel):
    sentences: list[str]


def _extract_executive_summary(markdown: str) -> str | None:
    match = re.search(r"##\s*Executive summary\s*\n(.*?)(?=\n##|\Z)", markdown, re.DOTALL)
    return match.group(1).strip() if match else None


def faithfulness_check(records: list[dict], settings: Settings) -> list[dict[str, Any]]:
    """Makes one cheap (8B) call per scenario that both (a) had clarifying questions and (b)
    produced a report — asks the model to flag sentences in the Executive summary contradicting
    the fact that those questions were answered with uncertainty. Returns a *list of suspicious
    sentences per scenario*, not a pass/fail verdict, per the Etap 8 brief: a human should read
    these, not trust an automatic judgment on something this subjective."""
    llm = ChatGroq(model=FAITHFULNESS_MODEL, api_key=settings.groq_api_key, temperature=0).with_structured_output(
        SuspiciousSentences
    )
    results = []
    for r in records:
        summary = _extract_executive_summary(r.get("report_markdown") or "")
        if not r.get("clarifications_asked") or not summary:
            continue
        user_message = (
            "Clarifying questions asked:\n"
            + "\n".join(f"- {q}" for q in r["clarifications_asked"])
            + f"\n\nAnswer given to all of them: {r.get('clarification_answer_used')}"
            + f"\n\nExecutive summary to check:\n{summary}"
        )
        try:
            result: SuspiciousSentences = with_retry(llm.invoke)(
                [SystemMessage(content=FAITHFULNESS_SYSTEM_PROMPT), HumanMessage(content=user_message)]
            )
            # 8B repeats itself sometimes (same sentence flagged twice) — de-dup, keep order.
            suspicious = list(dict.fromkeys(result.sentences))
            check_failed = False
        except Exception:  # noqa: BLE001 - a failed faithfulness check must not abort the report
            # Observed live: 8B sometimes emits its tool call as literal text instead of a
            # parseable structured response, deterministically for a given input (retrying the
            # identical prompt 3x still failed) — not a transient flake. Itself a small data
            # point on 8B's structured-output reliability, relevant to the Part C discussion.
            suspicious = []
            check_failed = True
        results.append({"scenario_id": r["scenario_id"], "suspicious_sentences": suspicious, "check_failed": check_failed})
    return results


# --- Token cost --------------------------------------------------------------------------------


def token_cost_stats(records: list[dict]) -> dict[str, Any]:
    completed = [r for r in records if r["status"] == "completed"]
    totals = [r["tokens_total"]["total_tokens"] for r in completed]
    by_node: dict[str, list[int]] = {}
    for r in completed:
        for node, hits in r["tokens_by_node"].items():
            by_node.setdefault(node, []).extend(h["total_tokens"] for h in hits)
    median = statistics.median(totals) if totals else None
    p90 = statistics.quantiles(totals, n=10)[8] if len(totals) >= 2 else (totals[0] if totals else None)
    return {
        "n_completed": len(completed),
        "median_tokens_per_scenario": median,
        "p90_tokens_per_scenario": p90,
        "runs_per_100k_tpd_budget": int(100_000 / median) if median else None,
        "mean_tokens_by_node": {node: statistics.mean(vals) for node, vals in by_node.items() if vals},
    }


# --- Report rendering ----------------------------------------------------------------------------


def render_report(
    records: list[dict],
    classify_comparison: list[dict] | None,
    faithfulness: list[dict],
    output_path: Path,
) -> None:
    acc = classification_accuracy(records)
    recall_report = citation_recall_report(records)
    recall_plan = citation_recall_plan(records)
    precision = citation_precision(records)
    groundless = groundless_action_rate(records)
    padding = padding_score(records)
    tokens = token_cost_stats(records)
    n_errors = sum(1 for r in records if r["status"] == "error")

    def pct(x: float | None) -> str:
        return f"{x * 100:.0f}%" if x is not None else "n/a"

    n_planned = len(SCENARIOS)
    completeness_note = (
        f"**Partial dataset: {len(records)} of {n_planned} planned scenarios.** "
        "The remaining ones were blocked by Groq's daily token quota (ZNALEZISKO #4) and are "
        "meant to be added with `eval.run_eval --resume`, after which this report should be "
        "regenerated — treat the numbers below as directional, not final."
        if len(records) < n_planned
        else f"All {n_planned} planned scenarios collected."
    )

    lines: list[str] = []
    lines.append("# Etap 8 — Evaluation report")
    lines.append("")
    lines.append(f"Scenarios: {len(records)} run, {n_errors} ended in an uncaught error. {completeness_note}")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value | Recommendation |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| Classification accuracy (exact) | {pct(acc['exact_match_rate'])} | "
        + ("known limitation" if (acc["exact_match_rate"] or 1) < 1 else "no action") + " |"
    )
    lines.append(f"| Classification accuracy (incl. reasonable neighbor) | {pct(acc['neighbor_match_rate'])} | informational |")
    lines.append(f"| Severity in expected range | {pct(acc['severity_in_range_rate'])} | informational |")
    lines.append(
        f"| Citation recall — final report (ZNALEZISKO #7) | {pct(recall_report['recall'])} | "
        + ("Etap 9 (prompt fix candidate)" if (recall_report["recall"] or 0) < 0.5 else "monitor") + " |"
    )
    lines.append(f"| Citation recall — plan (contrast) | {pct(recall_plan['recall'])} | no action, already works |")
    lines.append(f"| Citation precision | {pct(precision['precision'])} | expected ~100%, see note below |")
    lines.append(
        f"| Groundless action rate (ZNALEZISKO #11) | {pct(groundless['rate'])} | "
        + ("fix now (Part D)" if (groundless["rate"] or 0) > 0 else "no action") + " |"
    )
    lines.append(f"| Plan padding (mean fraction generic in steps 5+) | {pct(padding['mean_fraction_generic_in_tail'])} | Etap 9 |")
    token_cost_cell = (
        f"{tokens['median_tokens_per_scenario']:.0f} / {tokens['p90_tokens_per_scenario']:.0f}"
        if tokens["median_tokens_per_scenario"]
        else "n/a"
    )
    lines.append(f"| Token cost per scenario (median / p90) | {token_cost_cell} | capacity planning |")
    lines.append(f"| Full runs fitting in 100k tokens/day | {tokens['runs_per_100k_tpd_budget']} | capacity planning |")
    lines.append("")

    lines.append("## Interpretation")
    lines.append("")
    lines.append("### Classification accuracy")
    lines.append(
        f"{acc['n_scored']} scenarios scored. Exact-category accuracy {pct(acc['exact_match_rate'])}, "
        f"rising to {pct(acc['neighbor_match_rate'])} when a defensible neighbor category "
        "(e.g. ransomware/malware) counts as correct. "
        f"Severity landed in the expected range {pct(acc['severity_in_range_rate'])} of the time. "
        + (
            f"The deliberately ambiguous scenario got confidence {acc['ambiguous_scenario_confidence']:.2f} "
            f"vs. a mean of {acc['mean_unambiguous_confidence']:.2f} for unambiguous ones — "
            + ("confidence did drop for genuine uncertainty, as hoped." if acc["ambiguous_scenario_confidence"] and acc["mean_unambiguous_confidence"] and acc["ambiguous_scenario_confidence"] < acc["mean_unambiguous_confidence"] else "confidence did NOT drop for genuine uncertainty — worth a closer look.")
            if acc["ambiguous_scenario_confidence"] is not None and acc["mean_unambiguous_confidence"] is not None
            else "The ambiguous scenario hasn't been run yet in this dataset."
        )
    )
    lines.append("")
    lines.append("### Citations — report vs. plan (ZNALEZISKO #7, narrowed)")
    lines.append(
        f"The final report cited at least once in {pct(recall_report['recall'])} of scenarios, "
        f"vs. {pct(recall_plan['recall'])} for the plan panel's own citations. This gap is the "
        "actual finding: the same citation *data* (plan.steps[].citations, retrieved_chunks) is "
        "available to both, but report_llm doesn't reliably use [n] markers while the plan "
        "mechanism (rendered by the frontend, not an LLM decision) does. "
        + (
            f"Citation precision measured at {pct(precision['precision'])} on "
            f"{precision['total_markers_found']} marker(s) found"
            if precision["total_markers_found"]
            else "No [n] markers were found anywhere, so precision isn't measurable this round"
        )
        + " — expected to be ~100% by "
        "construction (report.py's whitelist already strips anything invalid before this "
        "measurement ever sees it), so this confirms the mechanism works rather than revealing "
        "something new; the low marker COUNT is the real signal, not the precision percentage."
    )
    lines.append("")
    lines.append("### Groundless action rate (ZNALEZISKO #11)")
    lines.append(
        f"{pct(groundless['rate'])} of the {groundless['n_no_clear_target']} no-clear-target "
        "scenarios still got a proposed action — but this is three genuinely different failure "
        "modes, not one, and blending them into a single rate would hide which ones actually "
        "matter:"
    )
    lines.append("")
    mode_labels = {
        "crash": "**Uncaught crash** — propose_actions raises before anything is even captured",
        "invalid_format": "**Placeholder string** — caught by plain IP format validation",
        "looked_valid_but_reserved_range": (
            "**Looked like a real IP** — caught only because it happened to land in a "
            "reserved/test range, not because anything detected it was fabricated"
        ),
    }
    for mode, label in mode_labels.items():
        hits = [h for h in groundless["scenarios"] if h["failure_mode"] == mode]
        if not hits:
            continue
        lines.append(f"- {label} — {len(hits)}:")
        for h in hits:
            detail = h["error"] if h["status"] == "error" else h["proposed_actions"][0]["args"]
            lines.append(f"  - `{h['scenario_id']}` ({h['status']}): `{detail}`")
    lines.append("")
    n_reserved_range = groundless["by_failure_mode"].get("looked_valid_but_reserved_range", 0)
    lines.append(
        
            f"The **looked_valid_but_reserved_range** case ({n_reserved_range}) is the one that "
            "actually matters most: it's the closest real occurrence to what ZNALEZISKO #11 "
            "originally warned about — 'model mógłby podstawić syntaktycznie poprawny, ale "
            "merytorycznie zmyślony adres IP' — a fabricated-looking IP that isn't an obvious "
            "placeholder like 'nie dotyczy'. It was only caught because it happened to fall in "
            "a reserved range (RFC 5737); a fabricated *public-looking* IP would sail straight "
            "through every existing check and reach the approval panel looking legitimate."
            if n_reserved_range
            else "No occurrence of the most concerning sub-case (a fabricated but public-"
            "looking IP) in this dataset yet — worth watching as more scenarios are collected."
        
    )
    lines.append("")
    lines.append("### Plan padding (ZNALEZISKO #9)")
    lines.append(
        f"Across {padding['n_plans_with_5plus_steps']} plans with 5+ steps, a mean of "
        f"{pct(padding['mean_fraction_generic_in_tail'])} of steps from position 5 onward share "
        "no specific content word with the original incident description — i.e. they don't "
        "reference anything concrete from the case (no server name, filename, IP), unlike the "
        "earlier, concrete steps. Consistent with the acceptance-session observation."
    )
    lines.append("")
    lines.append("### Faithfulness of the Executive summary (ZNALEZISKO #5)")
    n_checked = [f for f in faithfulness if not f["check_failed"]]
    n_check_failed = [f for f in faithfulness if f["check_failed"]]
    n_flagged = sum(1 for f in n_checked if f["suspicious_sentences"])
    lines.append(
        f"Checked {len(n_checked)} of {len(faithfulness)} eligible scenario(s) successfully "
        + (f"({len(n_check_failed)} check(s) failed — see note below); " if n_check_failed else "; ")
        + f"{n_flagged} flagged at least one sentence stating something as certain that the "
        "clarification answers explicitly marked unknown. This is a list for human review, not "
        "an automatic verdict:"
    )
    lines.append("")
    for f in n_checked:
        if f["suspicious_sentences"]:
            lines.append(f"- **{f['scenario_id']}**:")
            for s in f["suspicious_sentences"]:
                lines.append(f"  - \"{s}\"")
    lines.append("")
    if n_check_failed:
        lines.append(
            f"**Note**: {len(n_check_failed)} check(s) failed deterministically (3 identical "
            f"retries all failed the same way) for "
            + ", ".join(f"**{f['scenario_id']}**" for f in n_check_failed)
            + " — llama-3.1-8b-instant emitted its tool call as literal text instead of a "
            "parseable response for these specific inputs. A data point on 8B's structured-"
            "output reliability, relevant to the Part C discussion below."
        )
        lines.append("")

    if classify_comparison:
        lines.append("### Part C — classify-only 8B vs 70B comparison")
        n = len(classify_comparison)
        matches_70b = sum(1 for c in classify_comparison if c["match_70b"])
        matches_8b = sum(1 for c in classify_comparison if c["match_8b"])
        lines.append(
            f"On {n} scenarios: 70B matched the expected category {matches_70b}/{n}, "
            f"8B matched {matches_8b}/{n}. "
        )
        lines.append("")
        lines.append("| Scenario | Expected | 70B (conf.) | 8B (conf.) |")
        lines.append("| --- | --- | --- | --- |")
        for c in classify_comparison:
            lines.append(
                f"| {c['scenario_id']} | {c['expected_category']} | "
                f"{c['classification_70b']['category']} ({c['classification_70b']['confidence']:.2f}) | "
                f"{c['classification_8b']['category']} ({c['classification_8b']['confidence']:.2f}) |"
            )
        lines.append("")
        lines.append(
            f"{'Matches the accuracy of 70B on this small sample' if matches_8b >= matches_70b else 'Slightly behind 70B on this small sample'} "
            "— a candidate for moving classification to the cheaper/faster model specifically, "
            "which would help both token budget and rate-limit resilience (ZNALEZISKO #4). "
            f"Sample size ({n}) is too small to be conclusive on its own; treat as a promising "
            "signal to expand in Etap 9, not a final answer."
        )
        lines.append("")

    lines.append("## Scope decisions (this stage measures and decides — it does not fix everything)")
    lines.append("")
    lines.append(
        "Per the Etap 8 brief, each finding below is either fixed now (Part D, gated on the "
        "numbers above — see the project's commit history for exactly what changed and why) or "
        "deliberately deferred. Deferring is a scope decision, not an oversight:"
    )
    lines.append("")
    lines.append(
        "- **Candidates for Part D, gated on the numbers above**: ZNALEZISKO #9 (plan padding), "
        "#10 (frontend stepper), #11 (groundless action rate), #12 (raw repr() in the report's "
        "Podjęte działania section), and the citation-recall prompt experiment for #7."
    )
    lines.append(
        "- **Deferred to Etap 9 (evaluation-driven backlog, not abandoned)**: report faithfulness "
        "(ZNALEZISKO #5/#6) beyond the flagging done above, "
        "language consistency across nodes (ZNALEZISKO #8), and expanding Part C's sample size "
        "before committing to a model change."
    )
    lines.append(
        "- **Deferred to Etap 10 (observability)**: resuming a `failed` thread (ZNALEZISKO #1), "
        "structured token/cost tracking in production (this eval harness is a one-off script, "
        "not a standing observability pipeline — that's Langfuse's job)."
    )
    lines.append("")

    output_path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-jsonl", required=True)
    parser.add_argument("--classify-comparison", default=None)
    parser.add_argument("--output", default="eval/report.md")
    parser.add_argument("--skip-faithfulness", action="store_true", help="Skip the 8B faithfulness LLM calls")
    args = parser.parse_args()

    records = load_records(Path(args.raw_jsonl))
    classify_comparison = (
        load_records(Path(args.classify_comparison)) if args.classify_comparison else None
    )
    faithfulness = [] if args.skip_faithfulness else faithfulness_check(records, Settings())

    output_path = Path(args.output)
    render_report(records, classify_comparison, faithfulness, output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
