from typing import Any

from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings
from app.graph.nodes import (
    build_clarify_node,
    build_classify_node,
    build_plan_node,
    build_retrieve_node,
    route_after_classify,
)
from app.graph.schemas import DiagnosticPlan, DiagnosticStep, IncidentClassification
from app.graph.state import AgentState, ClarificationPair
from app.rag.retriever import KnowledgeRetriever, RetrievedChunk, get_retriever

# Our own Pydantic models aren't in langgraph's built-in msgpack allowlist, so without this the
# checkpointer falls back to a deprecated "allow unregistered types with a warning" mode that a
# future langgraph release will turn into a hard failure — this keeps checkpoint (de)serialization
# working, e.g. across a real process restart, without depending on that fallback.
CHECKPOINT_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[
        IncidentClassification,
        DiagnosticPlan,
        DiagnosticStep,
        ClarificationPair,
        RetrievedChunk,
    ]
)


def _default_structured_llm(settings: Settings, schema: type) -> Runnable[Any, Any]:
    llm = ChatGroq(model=settings.groq_model_name, api_key=settings.groq_api_key, temperature=0)
    return llm.with_structured_output(schema)


def build_graph(
    *,
    classify_llm: Runnable[Any, IncidentClassification] | None = None,
    plan_llm: Runnable[Any, DiagnosticPlan] | None = None,
    retriever: KnowledgeRetriever | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    settings: Settings | None = None,
) -> CompiledStateGraph:
    settings = settings or Settings()
    classify_llm = classify_llm or _default_structured_llm(settings, IncidentClassification)
    plan_llm = plan_llm or _default_structured_llm(settings, DiagnosticPlan)
    retriever = retriever or get_retriever()
    checkpointer = checkpointer or MemorySaver(serde=CHECKPOINT_SERDE)

    graph = StateGraph(AgentState)
    graph.add_node("classify", build_classify_node(classify_llm))
    graph.add_node("clarify", build_clarify_node())
    graph.add_node("retrieve", build_retrieve_node(retriever))
    graph.add_node("plan", build_plan_node(plan_llm))

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify", route_after_classify, {"clarify": "clarify", "retrieve": "retrieve"}
    )
    graph.add_edge("clarify", "classify")
    graph.add_edge("retrieve", "plan")
    graph.add_edge("plan", END)

    return graph.compile(checkpointer=checkpointer)
