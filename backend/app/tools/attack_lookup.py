import json
import re
from collections import defaultdict
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from app.config import Settings
from app.tools.registry import ToolResult, ToolSpec, register_tool

_CITATION_MARKER = re.compile(r"\(Citation: [^)]+\)")
MAX_DESCRIPTION_LENGTH = 400


class AttackTechnique(BaseModel):
    id: str
    name: str
    tactics: list[str]
    description: str
    data_sources: list[str]


def _short_description(description: str) -> str:
    text = description.strip().split("\n")[0]
    text = _CITATION_MARKER.sub("", text).strip()
    if len(text) > MAX_DESCRIPTION_LENGTH:
        text = text[: MAX_DESCRIPTION_LENGTH - 1].rstrip() + "…"
    return text


@lru_cache(maxsize=4)
def _load_techniques(path: str) -> dict[str, AttackTechnique]:
    """Parse the enterprise-attack STIX bundle into a technique_id -> AttackTechnique map.

    Cached in memory per path (the bundle is ~50MB, parsing it is not free), and keyed
    by path rather than a bare @lru_cache() so production and test fixture paths never
    collide in the cache.
    """
    with open(path, encoding="utf-8") as f:
        bundle = json.load(f)
    objects: list[dict[str, Any]] = bundle.get("objects", [])
    by_id = {obj["id"]: obj for obj in objects if "id" in obj}

    # Detection data sources are three hops away in the current ATT&CK STIX schema:
    # attack-pattern <-[detects]- x-mitre-detection-strategy -> x-mitre-analytic ->
    # log source name. We only need the final log-source names, not the intermediate
    # objects, so we resolve the chain once here rather than exposing it to callers.
    detects_by_target: dict[str, list[str]] = defaultdict(list)
    for obj in objects:
        if obj.get("type") == "relationship" and obj.get("relationship_type") == "detects":
            detects_by_target[obj["target_ref"]].append(obj["source_ref"])

    techniques: dict[str, AttackTechnique] = {}
    for obj in objects:
        if obj.get("type") != "attack-pattern":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue

        technique_id = next(
            (
                ref.get("external_id")
                for ref in obj.get("external_references", [])
                if ref.get("source_name") == "mitre-attack"
            ),
            None,
        )
        if not technique_id:
            continue

        tactics = [
            phase["phase_name"]
            for phase in obj.get("kill_chain_phases", [])
            if phase.get("kill_chain_name") == "mitre-attack"
        ]

        data_sources: set[str] = set()
        for strategy_ref in detects_by_target.get(obj["id"], []):
            strategy = by_id.get(strategy_ref, {})
            for analytic_ref in strategy.get("x_mitre_analytic_refs", []):
                analytic = by_id.get(analytic_ref, {})
                for log_source in analytic.get("x_mitre_log_source_references", []):
                    if name := log_source.get("name"):
                        data_sources.add(name)

        techniques[technique_id] = AttackTechnique(
            id=technique_id,
            name=obj.get("name", ""),
            tactics=tactics,
            description=_short_description(obj.get("description", "")),
            data_sources=sorted(data_sources),
        )

    return techniques


class AttackLookup:
    def __init__(self, settings: Settings | None = None, path: str | None = None) -> None:
        self._path = path or (settings or Settings()).attack_stix_path

    def lookup_by_id(self, technique_id: str) -> AttackTechnique | None:
        return _load_techniques(self._path).get(technique_id.strip().upper())

    def lookup_by_keyword(self, keyword: str, limit: int = 5) -> list[AttackTechnique]:
        keyword_lower = keyword.lower()
        matches = [
            technique
            for technique in _load_techniques(self._path).values()
            if keyword_lower in technique.name.lower()
            or keyword_lower in technique.description.lower()
        ]
        return matches[:limit]


def attack_lookup_tool(
    technique_id: str | None = None,
    keyword: str | None = None,
    settings: Settings | None = None,
) -> ToolResult:
    lookup = AttackLookup(settings=settings)

    if technique_id:
        technique = lookup.lookup_by_id(technique_id)
        findings = [technique.model_dump()] if technique else []
        if technique:
            summary = f"Found ATT&CK technique {technique.id} ({technique.name})"
        else:
            summary = f"No ATT&CK technique found for id '{technique_id}'"
    elif keyword:
        matches = lookup.lookup_by_keyword(keyword)
        findings = [match.model_dump() for match in matches]
        summary = f"Found {len(matches)} ATT&CK technique(s) matching '{keyword}'"
    else:
        findings = []
        summary = "No technique_id or keyword provided"

    warnings = [] if findings else [f"{summary} — no results to report."]
    return ToolResult(
        tool_name="attack_lookup", summary=summary, findings=findings, warnings=warnings
    )


register_tool(
    ToolSpec(
        name="attack_lookup",
        description=(
            "Looks up a MITRE ATT&CK technique by its ID (e.g. 'T1110') or by a free-text "
            "keyword, returning its name, tactic(s), a short description, and known log/data "
            "sources useful for detecting it."
        ),
        risk_level="read_only",
        input_schema={
            "type": "object",
            "properties": {
                "technique_id": {
                    "type": "string",
                    "description": "MITRE ATT&CK technique ID, e.g. 'T1110'.",
                },
                "keyword": {
                    "type": "string",
                    "description": "Free-text keyword to search technique names/descriptions.",
                },
            },
        },
    ),
    attack_lookup_tool,
)
