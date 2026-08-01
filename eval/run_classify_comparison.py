"""Part C: a narrow, classify-only comparison between llama-3.3-70b-versatile (already collected
via eval/run_eval.py's main scenario run) and llama-3.1-8b-instant, on the same 5 scenarios —
answers whether classification specifically could safely move to a cheaper/faster model, which
would help with both token budget and rate-limit resilience (ZNALEZISKO #4).

Deliberately classify-only, not a full graph run: comparing classification accuracy/confidence
doesn't need plan/tools/report at all, and running the full graph would spend the (often tight,
sometimes exhausted — see ZNALEZISKO #4) 70b daily budget on nodes irrelevant to this question.
Reuses the 70b classification already sitting in an existing raw.jsonl instead of re-spending
that budget, and only spends fresh tokens on the 8b side.

Usage:
    uv run python -m eval.run_classify_comparison --raw-jsonl eval/results/<timestamp>/raw.jsonl
"""

import argparse
import json
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.config import Settings
from app.graph.nodes import CLASSIFY_SYSTEM_PROMPT, _build_classify_prompt
from app.graph.schemas import IncidentClassification
from app.graph.state import AgentState
from eval.scenarios import SCENARIOS

COMPARISON_SCENARIO_IDS = [
    "phishing-single-user",
    "malware-worm-smb",
    "ransomware-fileserver",
    "ransomware-ssh-bruteforce",
    "phishing-mass-campaign",
]

COMPARISON_MODEL = "llama-3.1-8b-instant"


def _classify_with_model(description: str, model_name: str, settings: Settings) -> tuple[IncidentClassification, dict]:
    llm = ChatGroq(model=model_name, api_key=settings.groq_api_key, temperature=0).with_structured_output(
        IncidentClassification, include_raw=True
    )
    state = AgentState(incident_description=description)
    messages = [SystemMessage(content=CLASSIFY_SYSTEM_PROMPT), HumanMessage(content=_build_classify_prompt(state))]
    result = llm.invoke(messages)
    usage = result["raw"].usage_metadata or {}
    return result["parsed"], usage


def _load_existing_classifications(raw_jsonl: Path) -> dict[str, dict]:
    by_id = {}
    for line in raw_jsonl.read_text().splitlines():
        record = json.loads(line)
        if record.get("classification") is not None:
            by_id[record["scenario_id"]] = record["classification"]
    return by_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-jsonl", required=True, help="Existing raw.jsonl with 70b classifications to reuse")
    parser.add_argument("--output", default=None, help="Defaults to classify_comparison.jsonl next to --raw-jsonl")
    args = parser.parse_args()

    raw_jsonl = Path(args.raw_jsonl)
    output_path = Path(args.output) if args.output else raw_jsonl.parent / "classify_comparison.jsonl"

    existing_70b = _load_existing_classifications(raw_jsonl)
    missing = [sid for sid in COMPARISON_SCENARIO_IDS if sid not in existing_70b]
    if missing:
        raise SystemExit(
            f"{raw_jsonl} has no 70b classification for: {missing} — run eval.run_eval for these first."
        )

    scenarios_by_id = {s.id: s for s in SCENARIOS}
    settings = Settings()

    records = []
    for scenario_id in COMPARISON_SCENARIO_IDS:
        scenario = scenarios_by_id[scenario_id]
        classification_8b, usage_8b = _classify_with_model(scenario.description, COMPARISON_MODEL, settings)
        classification_70b = existing_70b[scenario_id]
        record = {
            "scenario_id": scenario_id,
            "expected_category": scenario.expected_category,
            "classification_70b": classification_70b,
            "classification_8b": classification_8b.model_dump(mode="json"),
            "match_70b": classification_70b["category"] == scenario.expected_category,
            "match_8b": classification_8b.category == scenario.expected_category,
            "tokens_8b": usage_8b,
        }
        records.append(record)
        print(
            f"{scenario_id}: expected={scenario.expected_category} "
            f"70b={classification_70b['category']}({classification_70b['confidence']:.2f}) "
            f"8b={classification_8b.category}({classification_8b.confidence:.2f})"
        )

    with output_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    print(f"Wrote {len(records)} comparison(s) -> {output_path}")


if __name__ == "__main__":
    main()
