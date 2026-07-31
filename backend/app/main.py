from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from groq import APIStatusError, GroqError
from langgraph.types import Command, Interrupt
from pydantic import BaseModel

from app.config import Settings
from app.drafts import delete_draft, load_draft, save_draft
from app.evidence import UnsupportedEvidenceExtension, list_evidence, store_evidence
from app.graph.builder import build_graph
from app.graph.checkpointer import get_checkpointer
from app.graph.schemas import DiagnosticPlan, IncidentClassification
from app.rag.retriever import RetrievedChunk, get_retriever
from app.tools.approval import ApprovalDecision, AuditEntry, ProposedAction
from app.tools.registry import ToolResult

DEV_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


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
    status: Literal["draft", "awaiting_clarification", "awaiting_approval", "completed", "failed"]
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
    # No pending interrupt does *not* mean the run finished successfully — a thread can also
    # land here because report generation raised (e.g. Groq's rate limit, which with_retry
    # doesn't retry — see app/graph/retry.py) after approval_gate already ran and cleared the
    # last interrupt. Without this check, that half-finished state was indistinguishable from
    # a real "completed" response: same shape, just a null `report`.
    status = "completed" if values.get("report") is not None else "failed"
    return IncidentResponse(
        thread_id=thread_id,
        status=status,
        classification=values.get("classification"),
        plan=values.get("plan"),
        sources=values.get("retrieved_chunks"),
        tool_results=values.get("tool_results"),
        audit_log=values.get("audit_log"),
        report=values.get("report"),
        report_warnings=values.get("report_warnings"),
    )


async def _current_status(
    app: FastAPI, settings: Settings, thread_id: str
) -> tuple[dict[str, Any], Sequence[Interrupt], str]:
    """(values, interrupts, status) for a thread — the draft store if the incident hasn't
    been started yet, otherwise graph state. Checking the draft store first means a draft
    thread never touches `app.state.graph` at all — important because `app.state.graph` is
    only set up by the lifespan context manager, which tests that only exercise evidence
    upload/draft creation don't (and shouldn't have to) trigger. Raises 404 if thread_id is
    unknown to both — i.e. it was never created via POST /incidents."""
    if load_draft(Path(settings.drafts_dir), thread_id) is not None:
        return {}, (), "draft"

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await app.state.graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Unknown thread_id")
    status = _build_response(thread_id, snapshot.values, snapshot.interrupts).status
    return snapshot.values, snapshot.interrupts, status


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    async with get_checkpointer(settings) as checkpointer:
        app.state.graph = build_graph(checkpointer=checkpointer, settings=settings)
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    settings = settings or Settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(GroqError)
    async def groq_error_handler(request: Request, exc: GroqError) -> JSONResponse:
        if isinstance(exc, APIStatusError):
            status_code = exc.status_code
            if status_code == 429:
                detail = "The AI model's rate limit was reached — please try again in a few minutes."
            else:
                detail = f"The AI model returned an error ({status_code})."
        else:
            status_code = 503
            detail = "Could not reach the AI model — please try again."
        return JSONResponse(status_code=status_code, content={"detail": detail})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    @app.get("/search")
    async def search(q: str, top_k: int = 5) -> list[RetrievedChunk]:
        return get_retriever().search(q, top_k=top_k)

    @app.post("/incidents")
    async def create_incident(payload: IncidentRequest) -> IncidentResponse:
        thread_id = str(uuid4())
        save_draft(Path(settings.drafts_dir), thread_id, payload.description)
        return IncidentResponse(thread_id=thread_id, status="draft")

    @app.post("/incidents/{thread_id}/start")
    async def start_incident(thread_id: str) -> IncidentResponse:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await app.state.graph.aget_state(config)
        if snapshot.values:
            raise HTTPException(
                status_code=409, detail="This incident has already been started."
            )
        description = load_draft(Path(settings.drafts_dir), thread_id)
        if description is None:
            raise HTTPException(status_code=404, detail="Unknown thread_id")

        # Deleted before invoking, not after: once we're about to hand the description to the
        # graph, the draft's job is done regardless of whether this invocation succeeds. If it
        # raised (e.g. Groq's rate limit in a later node — see the "failed" status above) and
        # the draft file were still here, subsequent GETs would keep reporting "draft" even
        # though the graph already has real (partial) state for this thread_id.
        delete_draft(Path(settings.drafts_dir), thread_id)
        result = await app.state.graph.ainvoke(
            {"incident_description": description}, config=config
        )
        return _build_response(thread_id, result, result.get("__interrupt__", ()))

    @app.post("/incidents/{thread_id}/resume")
    async def resume_incident(thread_id: str, payload: ResumeRequest) -> IncidentResponse:
        if payload.answers is not None and payload.approvals is not None:
            raise HTTPException(
                status_code=400, detail="Provide either 'answers' or 'approvals', not both."
            )
        if payload.approvals is not None:
            expected_status = "awaiting_approval"
            resume_value: Any = [a.model_dump(mode="json") for a in payload.approvals]
        elif payload.answers is not None:
            expected_status = "awaiting_clarification"
            resume_value = payload.answers
        else:
            raise HTTPException(
                status_code=400, detail="Provide either 'answers' or 'approvals'."
            )

        # Guards against resuming a thread that isn't paused the way this payload assumes —
        # e.g. a duplicate/retried request arriving after an earlier resume already moved the
        # thread past this interrupt. Without this, the second call would feed a stale resume
        # value into whatever *other* interrupt() the thread is now sitting at (a different
        # node, expecting a different shape), which fails deep inside that node instead of
        # here. This is a known, accepted TOCTOU window — the status check and the actual
        # ainvoke() below are not atomic, so two requests racing closely enough could still
        # both pass this check before either resumes the graph. Closing that fully would need
        # a per-thread lock; not worth it for the actual traffic this endpoint sees, but this
        # check still turns the common case (a stale/duplicate request arriving after an
        # earlier one already completed) into a clean 409 instead of a raw 500.
        _, _, current_status = await _current_status(app, settings, thread_id)
        if current_status != expected_status:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot resume with {'approvals' if payload.approvals is not None else 'answers'} "
                    f"while the incident is '{current_status}' (expected '{expected_status}')."
                ),
            )

        config = {"configurable": {"thread_id": thread_id}}
        result = await app.state.graph.ainvoke(Command(resume=resume_value), config=config)
        return _build_response(thread_id, result, result.get("__interrupt__", ()))

    @app.get("/incidents/{thread_id}")
    async def get_incident(thread_id: str) -> IncidentResponse:
        values, interrupts, status = await _current_status(app, settings, thread_id)
        if status == "draft":
            return IncidentResponse(thread_id=thread_id, status="draft")
        return _build_response(thread_id, values, interrupts)

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
        _, _, status = await _current_status(app, settings, thread_id)
        if status not in ("draft", "awaiting_clarification"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot upload evidence while the incident is '{status}'.",
            )

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
