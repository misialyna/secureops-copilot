from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile
from langgraph.types import Command, Interrupt
from pydantic import BaseModel

from app.config import Settings
from app.evidence import UnsupportedEvidenceExtension, list_evidence, store_evidence
from app.graph.builder import build_graph
from app.graph.checkpointer import get_checkpointer
from app.graph.schemas import DiagnosticPlan, IncidentClassification
from app.rag.retriever import RetrievedChunk, get_retriever
from app.tools.approval import ApprovalDecision, AuditEntry, ProposedAction
from app.tools.registry import ToolResult


class IncidentRequest(BaseModel):
    description: str


class ResumeRequest(BaseModel):
    """Resumes a paused thread with exactly one of the two payload shapes, matching
    whichever `status` the previous response reported:
    - answers: for status="awaiting_clarification" (clarify node).
    - approvals: for status="awaiting_approval" (approval_gate node).
    Both fields exist on one model rather than two endpoints because they drive the exact
    same underlying operation (resume a paused LangGraph thread with a value) — the only
    difference is which shape the currently-paused node expects.
    """

    answers: dict[str, str] | None = None
    approvals: list[ApprovalDecision] | None = None


class IncidentResponse(BaseModel):
    thread_id: str
    status: Literal["awaiting_clarification", "awaiting_approval", "completed"]
    pending_questions: list[str] | None = None
    proposed_actions: list[ProposedAction] | None = None
    classification: IncidentClassification | None = None
    plan: DiagnosticPlan | None = None
    sources: list[RetrievedChunk] | None = None
    tool_results: list[ToolResult] | None = None
    audit_log: list[AuditEntry] | None = None
    report: str | None = None
    report_warnings: list[str] | None = None


class ReportResponse(BaseModel):
    markdown: str
    generated_at: datetime
    warnings: list[str]


class EvidenceUploadResponse(BaseModel):
    thread_id: str
    filename: str
    size_bytes: int


class EvidenceListResponse(BaseModel):
    thread_id: str
    files: list[str]


def _build_response(
    thread_id: str, values: dict[str, Any], interrupts: Sequence[Interrupt]
) -> IncidentResponse:
    if interrupts:
        payload = interrupts[0].value
        if "proposed_actions" in payload:
            return IncidentResponse(
                thread_id=thread_id,
                status="awaiting_approval",
                proposed_actions=payload["proposed_actions"],
            )
        questions = payload.get("questions", [])
        return IncidentResponse(
            thread_id=thread_id, status="awaiting_clarification", pending_questions=questions
        )
    return IncidentResponse(
        thread_id=thread_id,
        status="completed",
        classification=values.get("classification"),
        plan=values.get("plan"),
        sources=values.get("retrieved_chunks"),
        tool_results=values.get("tool_results"),
        audit_log=values.get("audit_log"),
        report=values.get("report"),
        report_warnings=values.get("report_warnings"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    async with get_checkpointer(settings) as checkpointer:
        app.state.graph = build_graph(checkpointer=checkpointer, settings=settings)
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    settings = settings or Settings()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    @app.get("/search")
    async def search(q: str, top_k: int = 5) -> list[RetrievedChunk]:
        return get_retriever().search(q, top_k=top_k)

    @app.post("/incidents")
    async def create_incident(payload: IncidentRequest) -> IncidentResponse:
        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        result = await app.state.graph.ainvoke(
            {"incident_description": payload.description}, config=config
        )
        return _build_response(thread_id, result, result.get("__interrupt__", ()))

    @app.post("/incidents/{thread_id}/resume")
    async def resume_incident(thread_id: str, payload: ResumeRequest) -> IncidentResponse:
        if payload.answers is not None and payload.approvals is not None:
            raise HTTPException(
                status_code=400, detail="Provide either 'answers' or 'approvals', not both."
            )
        if payload.approvals is not None:
            resume_value: Any = [a.model_dump(mode="json") for a in payload.approvals]
        elif payload.answers is not None:
            resume_value = payload.answers
        else:
            raise HTTPException(
                status_code=400, detail="Provide either 'answers' or 'approvals'."
            )

        config = {"configurable": {"thread_id": thread_id}}
        result = await app.state.graph.ainvoke(Command(resume=resume_value), config=config)
        return _build_response(thread_id, result, result.get("__interrupt__", ()))

    @app.get("/incidents/{thread_id}")
    async def get_incident(thread_id: str) -> IncidentResponse:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await app.state.graph.aget_state(config)
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="Unknown thread_id")
        return _build_response(thread_id, snapshot.values, snapshot.interrupts)

    @app.get("/incidents/{thread_id}/report")
    async def get_incident_report(thread_id: str) -> ReportResponse:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await app.state.graph.aget_state(config)
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="Unknown thread_id")
        markdown = snapshot.values.get("report")
        if markdown is None:
            raise HTTPException(
                status_code=404, detail="Report not generated yet for this thread_id"
            )
        return ReportResponse(
            markdown=markdown,
            generated_at=snapshot.values["report_generated_at"],
            warnings=snapshot.values.get("report_warnings") or [],
        )

    @app.post("/incidents/{thread_id}/evidence")
    async def upload_evidence(thread_id: str, file: UploadFile) -> EvidenceUploadResponse:
        max_bytes = settings.max_evidence_file_size_mb * 1024 * 1024
        contents = await file.read(max_bytes + 1)
        if len(contents) > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File exceeds the {settings.max_evidence_file_size_mb} MB limit.",
            )

        evidence_dir = Path(settings.evidence_dir) / thread_id
        try:
            _, display_name = store_evidence(evidence_dir, file.filename or "", contents)
        except UnsupportedEvidenceExtension as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return EvidenceUploadResponse(
            thread_id=thread_id, filename=display_name, size_bytes=len(contents)
        )

    @app.get("/incidents/{thread_id}/evidence")
    async def get_incident_evidence(thread_id: str) -> EvidenceListResponse:
        evidence_dir = Path(settings.evidence_dir) / thread_id
        return EvidenceListResponse(thread_id=thread_id, files=list_evidence(evidence_dir))

    return app


app = create_app()
