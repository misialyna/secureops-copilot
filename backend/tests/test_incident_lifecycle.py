from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.config import Settings
from app.graph.builder import build_graph
from app.graph.report import IncidentReport
from app.graph.schemas import (
    ApprovalGateDecision,
    DiagnosticPlan,
    DiagnosticStep,
    IncidentClassification,
)
from app.main import create_app
from app.rag.retriever import RetrievedChunk


class FakeRetriever:
    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        return []


def _build_fake_graph() -> object:
    classify_llm = RunnableLambda(
        lambda messages: IncidentClassification(
            category="phishing",
            severity="low",
            confidence=0.8,
            reasoning="Isolated phishing click",
            missing_info=[],
        )
    )
    tools_llm = RunnableLambda(lambda messages: AIMessage(content="", tool_calls=[]))
    plan_llm = RunnableLambda(
        lambda messages: DiagnosticPlan(
            steps=[
                DiagnosticStep(
                    description="d", rationale="r", expected_evidence="e", priority=1
                )
            ]
        )
    )
    approval_llm = RunnableLambda(lambda messages: ApprovalGateDecision(proposed_actions=[]))
    report_llm = RunnableLambda(
        lambda messages: IncidentReport(markdown="## Executive summary\nAll good.")
    )
    return build_graph(
        classify_llm=classify_llm,
        tools_llm=tools_llm,
        plan_llm=plan_llm,
        approval_llm=approval_llm,
        report_llm=report_llm,
        retriever=FakeRetriever(),
    )


def _app_for(tmp_path: Path) -> object:
    settings = Settings(
        evidence_dir=str(tmp_path / "evidence"), drafts_dir=str(tmp_path / "drafts")
    )
    app = create_app(settings=settings)
    app.state.graph = _build_fake_graph()
    return app


@pytest.mark.asyncio
async def test_draft_upload_start_completes_full_cycle(tmp_path: Path) -> None:
    app = _app_for(tmp_path)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/incidents", json={"description": "phishing click"})
        assert create_response.status_code == 200
        assert create_response.json()["status"] == "draft"
        thread_id = create_response.json()["thread_id"]

        get_draft_response = await client.get(f"/incidents/{thread_id}")
        assert get_draft_response.json()["status"] == "draft"

        upload_response = await client.post(
            f"/incidents/{thread_id}/evidence",
            files={"file": ("note.txt", b"suspicious email", "text/plain")},
        )
        assert upload_response.status_code == 200

        start_response = await client.post(f"/incidents/{thread_id}/start")

    assert start_response.status_code == 200
    body = start_response.json()
    assert body["status"] == "completed"
    assert body["classification"]["category"] == "phishing"
    assert body["report"] is not None


@pytest.mark.asyncio
async def test_upload_after_start_is_rejected(tmp_path: Path) -> None:
    app = _app_for(tmp_path)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/incidents", json={"description": "phishing click"})
        thread_id = create_response.json()["thread_id"]
        await client.post(f"/incidents/{thread_id}/start")

        late_upload_response = await client.post(
            f"/incidents/{thread_id}/evidence",
            files={"file": ("note.txt", b"too late", "text/plain")},
        )

    assert late_upload_response.status_code == 409


@pytest.mark.asyncio
async def test_starting_twice_is_rejected(tmp_path: Path) -> None:
    app = _app_for(tmp_path)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/incidents", json={"description": "phishing click"})
        thread_id = create_response.json()["thread_id"]
        first_start = await client.post(f"/incidents/{thread_id}/start")
        second_start = await client.post(f"/incidents/{thread_id}/start")

    assert first_start.status_code == 200
    assert second_start.status_code == 409


@pytest.mark.asyncio
async def test_starting_unknown_thread_id_returns_404(tmp_path: Path) -> None:
    app = _app_for(tmp_path)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/incidents/never-created/start")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_evidence_upload_allowed_while_awaiting_clarification(tmp_path: Path) -> None:
    """A report that still needs clarification stays uploadable — only later stages
    (awaiting_approval / completed) close the upload window."""
    classify_llm = RunnableLambda(
        lambda messages: IncidentClassification(
            category="other",
            severity="low",
            confidence=0.3,
            reasoning="unclear",
            missing_info=["What system is affected?"],
        )
    )
    settings = Settings(
        evidence_dir=str(tmp_path / "evidence"), drafts_dir=str(tmp_path / "drafts")
    )
    app = create_app(settings=settings)
    app.state.graph = build_graph(
        classify_llm=classify_llm,
        tools_llm=RunnableLambda(lambda m: AIMessage(content="", tool_calls=[])),
        plan_llm=RunnableLambda(
            lambda m: DiagnosticPlan(
                steps=[DiagnosticStep(description="d", rationale="r", expected_evidence="e", priority=1)]
            )
        ),
        approval_llm=RunnableLambda(lambda m: ApprovalGateDecision(proposed_actions=[])),
        report_llm=RunnableLambda(lambda m: IncidentReport(markdown="# r")),
        retriever=FakeRetriever(),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/incidents", json={"description": "something odd"})
        thread_id = create_response.json()["thread_id"]
        start_response = await client.post(f"/incidents/{thread_id}/start")
        assert start_response.json()["status"] == "awaiting_clarification"

        upload_response = await client.post(
            f"/incidents/{thread_id}/evidence",
            files={"file": ("note.txt", b"more context", "text/plain")},
        )

    assert upload_response.status_code == 200
