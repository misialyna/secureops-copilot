import json
from pathlib import Path

from app.config import Settings
from app.tools.attack_lookup import AttackLookup, attack_lookup_tool

_STIX_FIXTURE = {
    "type": "bundle",
    "id": "bundle--test",
    "objects": [
        {
            "type": "attack-pattern",
            "id": "attack-pattern--brute-force",
            "name": "Brute Force",
            "description": "Adversaries may use brute force techniques to gain access to "
            "accounts.(Citation: Some Source)\n\nSecond paragraph should be dropped.",
            "kill_chain_phases": [
                {"kill_chain_name": "mitre-attack", "phase_name": "credential-access"}
            ],
            "external_references": [
                {
                    "source_name": "mitre-attack",
                    "external_id": "T1110",
                    "url": "https://attack.mitre.org/techniques/T1110",
                }
            ],
            "revoked": False,
        },
        {
            "type": "attack-pattern",
            "id": "attack-pattern--valid-accounts",
            "name": "Valid Accounts",
            "description": "Adversaries may obtain and abuse credentials of existing accounts.",
            "kill_chain_phases": [
                {"kill_chain_name": "mitre-attack", "phase_name": "defense-evasion"},
                {"kill_chain_name": "mitre-attack", "phase_name": "persistence"},
            ],
            "external_references": [{"source_name": "mitre-attack", "external_id": "T1078"}],
            "revoked": False,
        },
        {
            "type": "attack-pattern",
            "id": "attack-pattern--revoked-one",
            "name": "Some Revoked Technique",
            "description": "This one should never show up.",
            "external_references": [{"source_name": "mitre-attack", "external_id": "T9999"}],
            "revoked": True,
        },
        {
            "type": "x-mitre-detection-strategy",
            "id": "x-mitre-detection-strategy--brute-force",
            "name": "Brute Force Detection",
            "x_mitre_analytic_refs": ["x-mitre-analytic--brute-force-1"],
        },
        {
            "type": "x-mitre-analytic",
            "id": "x-mitre-analytic--brute-force-1",
            "name": "Analytic 1",
            "x_mitre_log_source_references": [
                {"x_mitre_data_component_ref": "x-mitre-data-component--auth", "name": "auditd:USER_LOGIN"}
            ],
        },
        {
            "type": "relationship",
            "id": "relationship--detects-brute-force",
            "relationship_type": "detects",
            "source_ref": "x-mitre-detection-strategy--brute-force",
            "target_ref": "attack-pattern--brute-force",
        },
    ],
}


def _write_fixture(tmp_path: Path) -> str:
    path = tmp_path / "enterprise-attack.json"
    path.write_text(json.dumps(_STIX_FIXTURE))
    return str(path)


def test_lookup_by_id_resolves_data_sources_and_tactics(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path)
    lookup = AttackLookup(path=path)

    technique = lookup.lookup_by_id("t1110")

    assert technique is not None
    assert technique.name == "Brute Force"
    assert technique.tactics == ["credential-access"]
    assert "Second paragraph" not in technique.description
    assert "(Citation:" not in technique.description
    assert technique.data_sources == ["auditd:USER_LOGIN"]


def test_lookup_by_id_unknown_returns_none(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path)
    lookup = AttackLookup(path=path)

    assert lookup.lookup_by_id("T0000") is None


def test_lookup_excludes_revoked_techniques(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path)
    lookup = AttackLookup(path=path)

    assert lookup.lookup_by_id("T9999") is None


def test_lookup_by_keyword_matches_name_and_description(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path)
    lookup = AttackLookup(path=path)

    matches = lookup.lookup_by_keyword("credentials of existing accounts")

    assert [m.id for m in matches] == ["T1078"]


def test_attack_lookup_tool_returns_tool_result_for_id(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path)
    settings = Settings(attack_stix_path=path)

    result = attack_lookup_tool(technique_id="T1110", settings=settings)

    assert result.tool_name == "attack_lookup"
    assert len(result.findings) == 1
    assert result.findings[0]["id"] == "T1110"
    assert not result.warnings


def test_attack_lookup_tool_reports_no_match(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path)
    settings = Settings(attack_stix_path=path)

    result = attack_lookup_tool(technique_id="T0000", settings=settings)

    assert result.findings == []
    assert result.warnings
