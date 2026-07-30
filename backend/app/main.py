from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import aiosqlite
from fastapi import FastAPI, HTTPException, UploadFile
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command, Interrupt
from pydantic import BaseModel

from app.config import Settings
from app.evidence import UnsupportedEvidenceExtension, list_evidence, store_evidence
from app.graph.builder import CHECKPOINT_SERDE, build_graph
from app.graph.schemas import DiagnosticPlan, IncidentClassification
from app.rag.retriever import RetrievedChunk, get_retriever
from app.tools.registry import ToolResult


class IncidentRequest(BaseModel):
    description: str


class ResumeRequest(BaseModel):
    answers: dict[str, str]


class IncidentResponse(BaseModel):
    thread_id: str
    status: Literal["awaiting_clarification", "completed"]
    pending_questions: list[str] | None = None
    classification: IncidentClassification | None = None
    plan: DiagnosticPlan | None = None
    sources: list[RetrievedChunk] | None = None
    tool_results: list[ToolResult] | None = None


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
        questions = interrupts[0].value.get("questions", [])
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
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    checkpoint_path = Path(settings.checkpoint_db_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(checkpoint_path)) as conn:
        checkpointer = AsyncSqliteSaver(conn, serde=CHECKPOINT_SERDE)
        await checkpointer.setup()
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
        config = {"configurable": {"thread_id": thread_id}}
        result = await app.state.graph.ainvoke(Command(resume=payload.answers), config=config)
        return _build_response(thread_id, result, result.get("__interrupt__", ()))

    @app.get("/incidents/{thread_id}")
    async def get_incident(thread_id: str) -> IncidentResponse:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await app.state.graph.aget_state(config)
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="Unknown thread_id")
        return _build_response(thread_id, snapshot.values, snapshot.interrupts)

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
