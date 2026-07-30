from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langgraph.types import interrupt

from app.graph.schemas import DiagnosticPlan, IncidentClassification
from app.graph.state import AgentState, ClarificationPair
from app.rag.retriever import KnowledgeRetriever

CLASSIFY_SYSTEM_PROMPT = """You are a security incident triage assistant for a Security \
Operations Center (SOC).

You will receive an incident report, which may be written in any language, and optionally a \
transcript of clarifying questions already asked and the reporter's answers.

Classify the incident and respond with the required structured fields:
- category: exactly one of malware, ransomware, phishing, unauthorized_access, \
denial_of_service, data_breach, insider_threat, other.
- severity: one of low, medium, high, critical.
- confidence: your confidence in this classification, between 0 and 1.
- reasoning: a short explanation of your classification.
- missing_info: a list of specific questions about information missing from the report that is \
needed to handle the incident (e.g. which systems are affected, when it started, whether it is \
ongoing, what data or credentials may be involved). Return an empty list if the report already \
has enough information to proceed with diagnostics.

Write the `reasoning` text and every question in `missing_info` in the SAME language as the \
original incident report (e.g. if the report is in Polish, write them in Polish).
"""

PLAN_SYSTEM_PROMPT = """You are a security incident response planning assistant.

Given an incident's classification, any clarifying answers, and relevant excerpts from \
incident-response procedures (NIST SP 800-61 and CISA playbooks), produce a diagnostic plan: a \
short, ordered list of concrete diagnostic steps an analyst should take next.

For each step provide:
- description: what to do.
- rationale: why this step matters for this specific incident, referencing the classification \
and/or the provided procedure excerpts where relevant.
- expected_evidence: what evidence or outcome this step should produce.

Only include diagnostic/investigative steps. Do not include remediation, containment, or \
eradication actions, since those require human approval and are out of scope here. Write every \
field in the SAME language as the original incident report.
"""


def _format_clarifications(state: AgentState) -> str | None:
    if not state.clarifications:
        return None
    qa = "\n".join(f"Q: {pair.question}\nA: {pair.answer}" for pair in state.clarifications)
    return f"Clarifying questions already answered:\n{qa}"


def _build_classify_prompt(state: AgentState) -> str:
    parts = [f"Incident report:\n{state.incident_description}"]
    clarifications = _format_clarifications(state)
    if clarifications:
        parts.append(clarifications)
    return "\n\n".join(parts)


def _build_plan_prompt(state: AgentState) -> str:
    parts = [f"Incident report:\n{state.incident_description}"]

    if state.classification is not None:
        c = state.classification
        parts.append(
            f"Classification: category={c.category}, severity={c.severity}, "
            f"confidence={c.confidence:.2f}\nReasoning: {c.reasoning}"
        )

    clarifications = _format_clarifications(state)
    if clarifications:
        parts.append(clarifications)

    if state.retrieved_chunks:
        excerpts = "\n\n".join(
            f"[{chunk.source_id} p.{chunk.page}] {chunk.title}\n{chunk.text}"
            for chunk in state.retrieved_chunks
        )
        parts.append(f"Relevant procedure excerpts:\n{excerpts}")

    return "\n\n".join(parts)


def build_classify_node(
    classify_llm: Runnable[Any, IncidentClassification],
) -> Callable[[AgentState], dict]:
    def classify(state: AgentState) -> dict:
        messages = [
            SystemMessage(content=CLASSIFY_SYSTEM_PROMPT),
            HumanMessage(content=_build_classify_prompt(state)),
        ]
        result: IncidentClassification = classify_llm.invoke(messages)
        return {"classification": result}

    return classify


def build_retrieve_node(retriever: KnowledgeRetriever) -> Callable[[AgentState], dict]:
    def retrieve(state: AgentState) -> dict:
        category = state.classification.category if state.classification else ""
        query = f"{state.incident_description} {category}".strip()
        chunks = retriever.search(query, top_k=5)
        return {"retrieved_chunks": chunks}

    return retrieve


def build_clarify_node() -> Callable[[AgentState], dict]:
    def clarify(state: AgentState) -> dict:
        questions = state.classification.missing_info if state.classification else []
        answers: dict[str, str] = interrupt({"questions": questions})
        new_pairs = [
            ClarificationPair(question=question, answer=answers.get(question, ""))
            for question in questions
        ]
        return {"clarifications": [*state.clarifications, *new_pairs]}

    return clarify


def build_plan_node(plan_llm: Runnable[Any, DiagnosticPlan]) -> Callable[[AgentState], dict]:
    def plan(state: AgentState) -> dict:
        messages = [
            SystemMessage(content=PLAN_SYSTEM_PROMPT),
            HumanMessage(content=_build_plan_prompt(state)),
        ]
        result: DiagnosticPlan = plan_llm.invoke(messages)
        return {"plan": result}

    return plan


def route_after_classify(state: AgentState) -> str:
    if state.classification and state.classification.missing_info and not state.clarifications:
        return "clarify"
    return "retrieve"
