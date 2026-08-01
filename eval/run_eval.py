"""Runs every eval/scenarios.py scenario through the real graph against real Groq, and records
raw results to eval/results/{timestamp}/raw.jsonl for eval/metrics.py to turn into numbers.

Usage:
    uv run python -m eval.run_eval
    uv run python -m eval.run_eval --scenario-ids ransomware-fileserver,ambiguous-encryption-no-ransom-note
    uv run python -m eval.run_eval --classify-model llama-3.1-8b-instant --scenario-ids ...  # Part C
    uv run python -m eval.run_eval --resume eval/results/2026-08-02T10-00-00

Rate-limit aware: sleeps SLEEP_BETWEEN_SCENARIOS_SECONDS between scenarios regardless (spreads
usage out, rather than bursting), and on an actual 429 tells a short (TPM-style) limit apart from
a long one (TPD-style, hours) — the former is slept out and retried once, the latter aborts the
whole run rather than blocking for hours, since this project shares a 100k tokens/day quota with
everything else (see ZNALEZISKO #4, docs/odbior-etap7-notatki.md).
"""

import argparse
import json
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from groq import RateLimitError
from langchain_core.callbacks import BaseCallbackHandler
from langchain_groq import ChatGroq
from langgraph.types import Command

from app.config import Settings
from app.evidence import store_evidence
from app.graph.builder import build_graph
from app.graph.report import IncidentReport
from app.graph.schemas import ApprovalGateDecision, DiagnosticPlan, IncidentClassification
from app.rag.retriever import get_retriever
from eval.scenarios import FIXTURES_DIR, SCENARIOS, EvalScenario

GENERIC_UNCERTAIN_ANSWER = (
    "Nie wiemy / nie mamy pewności — nie mamy dodatkowych informacji poza opisem zgłoszenia."
)
"""Used to answer EVERY clarifying question in every scenario, deliberately. This is what makes
the faithfulness metric (ZNALEZISKO #5, computed later in eval/metrics.py) meaningful at scale:
any report that states something definite about a fact we explicitly marked unknown is a
faithfulness failure, by construction, for every scenario that needed clarification — not just
the one that happened to get a real "nie wiemy" answer during the Etap 7 acceptance session."""

SLEEP_BETWEEN_SCENARIOS_SECONDS = 5.0
MAX_AUTO_RETRY_SECONDS = 90.0
"""A 429 with a longer retry-after than this is treated as the daily (TPD) quota, not a
transient per-minute one — waiting it out would stall the run for potentially hours."""


class EvalBudgetExhausted(Exception):
    def __init__(self, retry_after_seconds: float | None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Groq quota exhausted; retry-after={retry_after_seconds}s")


class TokenProbe(BaseCallbackHandler):
    """Attached once per graph.invoke()/resume call. Records every LLM call's real token usage,
    in call order — see the module docstring in eval/scenarios.py... actually see the tutor
    explanation for this chunk for why this doesn't use tags or per-LLM callbacks: neither
    survives being wrapped by with_structured_output() or LangGraph's own node execution."""

    def __init__(self) -> None:
        self.hits: list[dict[str, int]] = []

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = (response.llm_output or {}).get("token_usage", {}) if response.llm_output else {}
        self.hits.append(
            {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
        )


def _attribute_hits(hits: list[dict[str, int]], *, after_approval: bool, ended_in: str) -> dict[str, list[dict]]:
    """Maps a phase's ordered token hits to node names, positionally, from the graph's known,
    fixed topology (backend/app/graph/builder.py): classify -> [clarify, back to classify] ->
    retrieve -> tools (0..5 LLM calls; 0 if no evidence was uploaded) -> plan -> propose_actions
    -> [approval_gate, no LLM call] -> [report]. `ended_in` is "clarify" | "approval" |
    "completed" — what this phase's graph.invoke() call actually stopped at.
    """
    if after_approval:
        # approval_gate makes no LLM call itself; only report runs after it.
        if len(hits) != 1:
            raise AssertionError(f"expected exactly 1 LLM call (report) after approval, got {len(hits)}")
        return {"report": hits}

    if ended_in == "clarify":
        if len(hits) != 1:
            raise AssertionError(f"expected exactly 1 LLM call (classify) before clarify, got {len(hits)}")
        return {"classify": hits}

    # classify -> tools (0..5) -> plan -> propose_actions [-> report if ended_in == "completed"]
    tail = 3 if ended_in == "approval" else 4  # classify+plan+propose_actions[+report], tools is the remainder
    n_tools = len(hits) - tail
    if n_tools < 0:
        raise AssertionError(f"fewer LLM calls ({len(hits)}) than the graph topology requires for ended_in={ended_in}")

    by_node: dict[str, list[dict]] = defaultdict(list)
    by_node["classify"].append(hits[0])
    by_node["tools"].extend(hits[1 : 1 + n_tools])
    by_node["plan"].append(hits[1 + n_tools])
    by_node["propose_actions"].append(hits[2 + n_tools])
    if ended_in == "completed":
        by_node["report"].append(hits[3 + n_tools])
    return dict(by_node)


def _merge_node_tokens(dest: dict[str, list[dict]], src: dict[str, list[dict]]) -> None:
    for node, hits in src.items():
        dest.setdefault(node, []).extend(hits)


def _sum_tokens(node_tokens: dict[str, list[dict]]) -> dict[str, int]:
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for hits in node_tokens.values():
        for hit in hits:
            for key in total:
                total[key] += hit.get(key, 0)
    return total


def _parse_retry_after(exc: RateLimitError) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _invoke_with_rate_limit_handling(
    fn: Callable[[], dict], *, allow_one_retry: bool = True
) -> dict:
    try:
        return fn()
    except RateLimitError as exc:
        retry_after = _parse_retry_after(exc)
        if retry_after is None or retry_after > MAX_AUTO_RETRY_SECONDS:
            raise EvalBudgetExhausted(retry_after) from exc
        if not allow_one_retry:
            raise
        time.sleep(retry_after + 1)
        return _invoke_with_rate_limit_handling(fn, allow_one_retry=False)


def _make_llms(settings: Settings, classify_model: str | None) -> dict[str, Any]:
    """Builds the five real LLM roles build_graph() needs. classify_model lets Part C swap just
    the classifier for a comparison run without touching plan/report/etc."""

    def structured(schema: type, model_name: str) -> Any:
        return ChatGroq(model=model_name, api_key=settings.groq_api_key, temperature=0).with_structured_output(schema)

    def chat(model_name: str) -> Any:
        return ChatGroq(model=model_name, api_key=settings.groq_api_key, temperature=0)

    default_model = settings.groq_model_name
    return {
        "classify_llm": structured(IncidentClassification, classify_model or default_model),
        "tools_llm": chat(default_model),
        "plan_llm": structured(DiagnosticPlan, default_model),
        "approval_llm": structured(ApprovalGateDecision, default_model),
        "report_llm": structured(IncidentReport, default_model),
    }


def _dump(obj: Any) -> Any:
    return obj.model_dump(mode="json") if obj is not None else None


def run_scenario(
    scenario: EvalScenario, settings: Settings, classify_model: str | None, retriever: Any
) -> dict[str, Any]:
    thread_id = f"eval-{scenario.id}"
    graph = build_graph(settings=settings, retriever=retriever, **_make_llms(settings, classify_model))
    config = {"configurable": {"thread_id": thread_id}}

    if scenario.evidence_file:
        evidence_dir = Path(settings.evidence_dir) / thread_id
        content = (FIXTURES_DIR / scenario.evidence_file).read_bytes()
        store_evidence(evidence_dir, scenario.evidence_file, content)

    node_tokens: dict[str, list[dict]] = {}
    clarifications_asked: list[str] = []
    proposed_actions_payload: list[dict] = []
    started_at = time.monotonic()
    error: str | None = None
    status = "completed"

    try:
        probe = TokenProbe()
        result = _invoke_with_rate_limit_handling(
            lambda: graph.invoke(
                {"incident_description": scenario.description},
                config={**config, "callbacks": [probe]},
            )
        )
        interrupts = result.get("__interrupt__", ())

        if interrupts and "questions" in interrupts[0].value:
            clarifications_asked = list(interrupts[0].value["questions"])
            _merge_node_tokens(node_tokens, _attribute_hits(probe.hits, after_approval=False, ended_in="clarify"))

            answers = {q: GENERIC_UNCERTAIN_ANSWER for q in clarifications_asked}
            probe = TokenProbe()
            result = _invoke_with_rate_limit_handling(
                lambda: graph.invoke(Command(resume=answers), config={**config, "callbacks": [probe]})
            )
            interrupts = result.get("__interrupt__", ())
            outcome = "approval" if interrupts else "completed"
            _merge_node_tokens(node_tokens, _attribute_hits(probe.hits, after_approval=False, ended_in=outcome))
        else:
            outcome = "approval" if interrupts else "completed"
            _merge_node_tokens(node_tokens, _attribute_hits(probe.hits, after_approval=False, ended_in=outcome))

        if interrupts and "proposed_actions" in interrupts[0].value:
            proposed_actions_payload = list(interrupts[0].value["proposed_actions"])
            approvals = [
                {
                    "action_id": action["id"],
                    "approved": False,
                    "decided_at": datetime.now(UTC).isoformat(),
                    "comment": "eval harness: auto-rejected, no infrastructure to execute against",
                }
                for action in proposed_actions_payload
            ]
            probe = TokenProbe()
            result = _invoke_with_rate_limit_handling(
                lambda: graph.invoke(Command(resume=approvals), config={**config, "callbacks": [probe]})
            )
            _merge_node_tokens(node_tokens, _attribute_hits(probe.hits, after_approval=True, ended_in="completed"))

    except EvalBudgetExhausted:
        raise
    except Exception as exc:  # noqa: BLE001 - a scenario failing must not abort the whole run
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        result = {}

    duration_seconds = time.monotonic() - started_at

    return {
        "scenario_id": scenario.id,
        "timestamp": datetime.now(UTC).isoformat(),
        "expected_category": scenario.expected_category,
        "expected_severity_range": list(scenario.expected_severity_range),
        "no_clear_target": scenario.no_clear_target,
        "ambiguous_with": scenario.ambiguous_with,
        "classify_model": classify_model,
        "status": status,
        "error": error,
        "classification": _dump(result.get("classification")),
        "plan": _dump(result.get("plan")),
        "retrieved_chunks": [_dump(c) for c in (result.get("retrieved_chunks") or [])],
        "tool_results": [_dump(t) for t in (result.get("tool_results") or [])],
        "proposed_actions": proposed_actions_payload,
        "audit_log": [_dump(a) for a in (result.get("audit_log") or [])],
        "report_markdown": result.get("report"),
        "report_warnings": result.get("report_warnings"),
        "clarifications_asked": clarifications_asked,
        "clarification_answer_used": GENERIC_UNCERTAIN_ANSWER if clarifications_asked else None,
        "tokens_by_node": node_tokens,
        "tokens_total": _sum_tokens(node_tokens),
        "duration_seconds": duration_seconds,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-ids", type=str, default=None, help="Comma-separated subset of scenario ids")
    parser.add_argument("--classify-model", type=str, default=None, help="Override model for classify_llm only")
    parser.add_argument("--output-dir", type=str, default=None, help="Defaults to eval/results/{timestamp}/")
    parser.add_argument(
        "--sleep-seconds", type=float, default=SLEEP_BETWEEN_SCENARIOS_SECONDS, help="Pause between scenarios"
    )
    parser.add_argument(
        "--resume", type=str, default=None, help="Existing results dir — skip scenario ids already in its raw.jsonl"
    )
    args = parser.parse_args()

    scenarios = SCENARIOS
    if args.scenario_ids:
        wanted = set(args.scenario_ids.split(","))
        scenarios = [s for s in SCENARIOS if s.id in wanted]
        missing = wanted - {s.id for s in scenarios}
        if missing:
            raise SystemExit(f"Unknown scenario id(s): {sorted(missing)}")

    if args.resume:
        output_dir = Path(args.resume)
        raw_path = output_dir / "raw.jsonl"
        already_done = set()
        if raw_path.exists():
            for line in raw_path.read_text().splitlines():
                already_done.add(json.loads(line)["scenario_id"])
        scenarios = [s for s in scenarios if s.id not in already_done]
        print(f"Resuming {output_dir}: {len(already_done)} already done, {len(scenarios)} remaining.")
    else:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent / "results" / timestamp
        raw_path = output_dir / "raw.jsonl"

    output_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(evidence_dir=str(output_dir / "evidence"))
    # Built once and reused: Qdrant's embedded (no-server) mode holds an exclusive file lock on
    # data/qdrant, so opening a fresh KnowledgeRetriever() per scenario is both wasteful and (if
    # anything else, e.g. a dev uvicorn, has it open at the same time) a hard failure.
    retriever = get_retriever()

    print(f"Running {len(scenarios)} scenario(s) -> {raw_path}")
    completed, skipped = 0, 0
    with raw_path.open("a") as f:
        for i, scenario in enumerate(scenarios):
            print(f"[{i + 1}/{len(scenarios)}] {scenario.id} ...", end=" ", flush=True)
            try:
                record = run_scenario(scenario, settings, args.classify_model, retriever)
            except EvalBudgetExhausted as exc:
                print(f"ABORTING RUN — Groq quota exhausted (retry-after={exc.retry_after_seconds}s)")
                skipped = len(scenarios) - i
                break
            f.write(json.dumps(record) + "\n")
            f.flush()
            completed += 1
            print(f"{record['status']} ({record['tokens_total']['total_tokens']} tokens, {record['duration_seconds']:.1f}s)")
            if i < len(scenarios) - 1:
                time.sleep(args.sleep_seconds)

    print(f"Done: {completed} completed, {skipped} skipped. Results: {raw_path}")


if __name__ == "__main__":
    main()
