from pydantic import BaseModel, Field

from app.graph.schemas import DiagnosticPlan, IncidentClassification
from app.rag.retriever import RetrievedChunk
from app.tools.registry import ToolResult


class ClarificationPair(BaseModel):
    question: str
    answer: str


class AgentState(BaseModel):
    incident_description: str
    classification: IncidentClassification | None = None
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    clarifications: list[ClarificationPair] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    plan: DiagnosticPlan | None = None
