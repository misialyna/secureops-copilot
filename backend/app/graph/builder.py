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
    build_approval_gate_node,
    build_clarify_node,
    build_classify_node,
    build_plan_node,
    build_propose_actions_node,
    build_retrieve_node,
    build_tools_node,
    route_after_classify,
    route_after_propose_actions,
)
from app.graph.schemas import (
    ApprovalGateDecision,
    Citation,
    DiagnosticPlan,
    DiagnosticStep,
    IncidentClassification,
)
from app.graph.state import AgentState, ClarificationPair
from app.rag.retriever import KnowledgeRetriever, RetrievedChunk, get_retriever
from app.tools.approval import ApprovalDecision, AuditEntry, ProposedAction
from app.tools.registry import ToolResult

# Our own Pydantic models aren't in langgraph's built-in msgpack allowlist, so without this the
# checkpointer falls back to a deprecated "allow unregistered types with a warning" mode that a
# future langgraph release will turn into a hard failure — this keeps checkpoint (de)serialization
# working, e.g. across a real process restart, without depending on that fallback.
CHECKPOINT_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[
        IncidentClassification,
        DiagnosticPlan,
        DiagnosticStep,
        Citation,
        ClarificationPair,
        RetrievedChunk,
        ToolResult,
        ProposedAction,
        ApprovalDecision,
        AuditEntry,
    ]
)


def _default_structured_llm(settings: Settings, schema: type) -> Runnable[Any, Any]:
    llm = ChatGroq(model=settings.groq_model_name, api_key=settings.groq_api_key, temperature=0)
    return llm.with_structured_output(schema)


def _default_chat_llm(settings: Settings) -> Runnable[Any, Any]:
    return ChatGroq(model=settings.groq_model_name, api_key=settings.groq_api_key, temperature=0)


def build_graph(
    *,
    classify_llm: Runnable[Any, IncidentClassification] | None = None,
    tools_llm: Runnable[Any, Any] | None = None,
    plan_llm: Runnable[Any, DiagnosticPlan] | None = None,
    approval_llm: Runnable[Any, ApprovalGateDecision] | None = None,
    retriever: KnowledgeRetriever | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    settings: Settings | None = None,
) -> CompiledStateGraph:
    settings = settings or Settings()
    classify_llm = classify_llm or _default_structured_llm(settings, IncidentClassification)
    tools_llm = tools_llm or _default_chat_llm(settings)
    plan_llm = plan_llm or _default_structured_llm(settings, DiagnosticPlan)
    approval_llm = approval_llm or _default_structured_llm(settings, ApprovalGateDecision)
    retriever = retriever or get_retriever()
    checkpointer = checkpointer or MemorySaver(serde=CHECKPOINT_SERDE)

    graph = StateGraph(AgentState)
    graph.add_node("classify", build_classify_node(classify_llm))
    graph.add_node("clarify", build_clarify_node())
    graph.add_node("retrieve", build_retrieve_node(retriever))
    graph.add_node("tools", build_tools_node(tools_llm, settings=settings))
    graph.add_node("plan", build_plan_node(plan_llm))
    graph.add_node("propose_actions", build_propose_actions_node(approval_llm))
    graph.add_node("approval_gate", build_approval_gate_node())

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify", route_after_classify, {"clarify": "clarify", "retrieve": "retrieve"}
    )
    graph.add_edge("clarify", "classify")
    graph.add_edge("retrieve", "tools")
    graph.add_edge("tools", "plan")
    graph.add_edge("plan", "propose_actions")
    graph.add_conditional_edges(
        "propose_actions", route_after_propose_actions, {"approval_gate": "approval_gate", "skip": END}
    )
    graph.add_edge("approval_gate", END)

    return graph.compile(checkpointer=checkpointer)
