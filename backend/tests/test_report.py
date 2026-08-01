from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.config import Settings
from app.graph.builder import build_graph
from app.graph.report import (
    AllowedCitation,
    IncidentReport,
    _build_allowed_citations,
    _build_references_section,
    _format_audit_log,
    _validate_and_strip_citations,
)
from app.graph.schemas import (
    ApprovalGateDecision,
    Citation,
    DiagnosticPlan,
    DiagnosticStep,
    IncidentClassification,
)
from app.graph.state import AgentState
from app.main import _build_response, create_app
from app.rag.retriever import RetrievedChunk
from app.tools.approval import ApprovalDecision, AuditEntry, ProposedAction


class FakeRetriever:
    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                text="x", source_id="nist-sp-800-61r3", title="NIST Title", page=40, score=0.9
            )
        ]


def _classify_llm() -> RunnableLambda:
    return RunnableLambda(
        lambda messages: IncidentClassification(
            category="phishing",
            severity="low",
            confidence=0.8,
            reasoning="Isolated phishing click",
            missing_info=[],
        )
    )


def _tools_llm() -> RunnableLambda:
    return RunnableLambda(lambda messages: AIMessage(content="", tool_calls=[]))


def _plan_llm() -> RunnableLambda:
    return RunnableLambda(
        lambda messages: DiagnosticPlan(
            steps=[
                DiagnosticStep(
                    description="Review NIST guidance",
                    rationale="r",
                    expected_evidence="e",
                    priority=1,
                    citations=[Citation(source_id="nist-sp-800-61r3", page=40)],
                )
            ]
        )
    )


def _no_proposals_approval_llm() -> RunnableLambda:
    return RunnableLambda(lambda messages: ApprovalGateDecision(proposed_actions=[]))


def _build(report_llm: RunnableLambda) -> object:
    return build_graph(
        classify_llm=_classify_llm(),
        tools_llm=_tools_llm(),
        plan_llm=_plan_llm(),
        approval_llm=_no_proposals_approval_llm(),
        report_llm=report_llm,
        retriever=FakeRetriever(),
    )


# --- unit tests for the citation-whitelist helpers ---------------------------------------


def test_build_allowed_citations_combines_plan_and_retrieved_chunks() -> None:
    state = AgentState(
        incident_description="x",
        retrieved_chunks=[
            RetrievedChunk(
                text="a", source_id="nist-sp-800-61r3", title="NIST", page=40, score=0.9
            )
        ],
        plan=DiagnosticPlan(
            steps=[
                DiagnosticStep(
                    description="d",
                    rationale="r",
                    expected_evidence="e",
                    priority=1,
                    citations=[Citation(source_id="cisa-ir-vr-playbooks", page=14)],
                )
            ]
        ),
    )

    allowed = _build_allowed_citations(state)

    assert [(c.source_id, c.page) for c in allowed] == [
        ("cisa-ir-vr-playbooks", 14),
        ("nist-sp-800-61r3", 40),
    ]
    assert [c.n for c in allowed] == [1, 2]


def test_validate_and_strip_citations_removes_invalid_marker_and_counts_warning() -> None:
    allowed_by_n = {1: AllowedCitation(n=1, source_id="s", page=1, title="T")}

    cleaned, warnings = _validate_and_strip_citations(
        "See [1] and [2] and [2] again.", allowed_by_n
    )

    assert "[2]" not in cleaned
    assert "[1]" in cleaned
    assert len(warnings) == 1
    assert "[2]" in warnings[0]
    assert "2 time" in warnings[0]


def test_validate_and_strip_citations_keeps_all_valid_markers() -> None:
    allowed_by_n = {
        1: AllowedCitation(n=1, source_id="s", page=1, title="T"),
        2: AllowedCitation(n=2, source_id="s2", page=2, title="T2"),
    }

    cleaned, warnings = _validate_and_strip_citations("[1] then [2].", allowed_by_n)

    assert cleaned == "[1] then [2]."
    assert warnings == []


def test_build_references_section_contains_exactly_the_used_citations() -> None:
    allowed_by_n = {
        1: AllowedCitation(n=1, source_id="s1", page=1, title="Title One"),
        2: AllowedCitation(n=2, source_id="s2", page=2, title="Title Two"),
        3: AllowedCitation(n=3, source_id="s3", page=3, title="Title Three"),
    }

    section = _build_references_section({1, 3}, allowed_by_n)

    assert "## References" in section
    assert "Title One" in section
    assert "Title Three" in section
    assert "Title Two" not in section


def test_build_references_section_empty_when_nothing_cited() -> None:
    assert _build_references_section(set(), {}) == ""


def _audit_entry(tool_args: dict, justification: str) -> AuditEntry:
    action = ProposedAction(
        id="a1", tool_name="block_ip", args=tool_args, justification=justification, risk_note="r"
    )
    decision = ApprovalDecision(action_id="a1", approved=True, decided_at=datetime.now(UTC))
    return AuditEntry(
        action=action,
        decision=decision,
        executed=True,
        result_summary="Invalid IP address: 'nie dotyczy'",
        timestamp=datetime.now(UTC),
    )


def test_format_audit_log_never_leaks_python_dict_repr() -> None:
    """ZNALEZISKO #12 (observed live during Etap 8 evaluation): report_llm sometimes copies its
    input too literally, and Python's dict repr (`{'ip': 'nie dotyczy'}`) leaking into a report
    reads like broken output. _format_audit_log's input text must never contain that syntax,
    regardless of what report_llm then does with it."""
    state = AgentState(
        incident_description="x",
        audit_log=[_audit_entry({"ip": "nie dotyczy"}, "Brak konkretnego adresu IP.")],
    )
    formatted = _format_audit_log(state)
    assert "{'ip'" not in formatted
    assert "ip=nie dotyczy" in formatted


def test_format_audit_log_does_not_double_the_justification_period() -> None:
    state = AgentState(
        incident_description="x",
        audit_log=[_audit_entry({"ip": "45.83.65.12"}, "Confirmed brute-force source.")],
    )
    formatted = _format_audit_log(state)
    assert ".." not in formatted


# --- graph-level tests ---------------------------------------------------------------------


def test_report_strips_invalid_marker_and_records_warning() -> None:
    report_llm = RunnableLambda(
        lambda messages: IncidentReport(
            markdown="## Executive summary\nFound brute force [1] and also [99] which is bogus."
        )
    )
    graph = _build(report_llm)

    result = graph.invoke(
        {"incident_description": "x"}, config={"configurable": {"thread_id": "report-invalid"}}
    )

    assert "[99]" not in result["report"]
    assert "[1]" in result["report"]
    assert "## References" in result["report"]
    assert "nist-sp-800-61r3" in result["report"]
    assert len(result["report_warnings"]) == 1
    assert "[99]" in result["report_warnings"][0]


def test_report_with_only_valid_markers_has_no_warnings() -> None:
    report_llm = RunnableLambda(
        lambda messages: IncidentReport(markdown="## Executive summary\nFound brute force [1].")
    )
    graph = _build(report_llm)

    result = graph.invoke(
        {"incident_description": "x"}, config={"configurable": {"thread_id": "report-valid"}}
    )

    assert result["report_warnings"] == []
    assert "[1]" in result["report"]
    assert "## References" in result["report"]


def test_report_generated_without_any_active_actions() -> None:
    """The no-proposed-actions path skips approval_gate entirely but must still reach report."""
    report_llm = RunnableLambda(
        lambda messages: IncidentReport(markdown="## Executive summary\nNothing alarming found.")
    )
    graph = _build(report_llm)

    result = graph.invoke(
        {"incident_description": "x"}, config={"configurable": {"thread_id": "report-no-action"}}
    )

    assert "__interrupt__" not in result
    assert result.get("report") is not None
    assert "Nothing alarming found" in result["report"]


def test_report_reaches_incident_response() -> None:
    report_llm = RunnableLambda(
        lambda messages: IncidentReport(markdown="## Executive summary\nSummary text.")
    )
    graph = _build(report_llm)

    result = graph.invoke(
        {"incident_description": "x"}, config={"configurable": {"thread_id": "report-api"}}
    )
    response = _build_response("report-api", result, ())

    assert response.status == "completed"
    assert response.report is not None
    assert "Summary text" in response.report
    assert response.report_warnings == []


@pytest.mark.asyncio
async def test_report_endpoint_returns_markdown_and_warnings(tmp_path: Path) -> None:
    report_llm = RunnableLambda(
        lambda messages: IncidentReport(
            markdown="## Executive summary\nBody with [1] and bogus [42]."
        )
    )
    app = create_app(settings=Settings(drafts_dir=str(tmp_path / "drafts")))
    app.state.graph = _build(report_llm)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/incidents", json={"description": "test incident"})
        assert create_response.json()["status"] == "draft"
        thread_id = create_response.json()["thread_id"]

        start_response = await client.post(f"/incidents/{thread_id}/start")
        assert start_response.json()["status"] == "completed"

        report_response = await client.get(f"/incidents/{thread_id}/report")
        missing_response = await client.get("/incidents/unknown-thread/report")

    assert report_response.status_code == 200
    body = report_response.json()
    assert "[1]" in body["markdown"]
    assert "[42]" not in body["markdown"]
    assert body["generated_at"]
    assert len(body["warnings"]) == 1

    assert missing_response.status_code == 404
