from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import aiosqlite
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command, Interrupt
from pydantic import BaseModel

from app.config import Settings
from app.graph.builder import CHECKPOINT_SERDE, build_graph
from app.graph.schemas import DiagnosticPlan, IncidentClassification
from app.rag.retriever import RetrievedChunk, get_retriever


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


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    settings = Settings()

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

    return app


app = create_app()
