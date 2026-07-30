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
incident-response procedures (NIST SP 800-61 and CISA playbooks, each tagged with its \
[source_id, page]), produce a diagnostic plan of 4 to 7 concrete diagnostic steps, ordered by \
priority (1 = most urgent).

Every step must be immediately actionable by an analyst WITHOUT asking further questions: name \
specific artifacts, log sources, event/field identifiers, and tools (e.g. "Windows Security Event \
ID 4688", "EDR process-creation logs", "firewall NAT/connection logs", specific ATT&CK technique \
IDs). Prefer such specifics when the provided procedure excerpts contain them (e.g. the CISA \
tactics/techniques/log-source table). When the excerpts do not cover a step you still need \
(e.g. a step specific to this incident's systems), write it just as concretely from your own \
general incident-response knowledge instead of leaving it vague.

For each step provide:
- description: the concrete action to take.
- rationale: why this step matters for this specific incident.
- expected_evidence: the specific artifact or observation that would confirm or rule out a \
hypothesis (e.g. "presence of scheduled task X on host Y") — do not just restate the description.
- priority: 1 (most urgent) upward; no ties needed, but order the list by priority.
- citations: a list of {source_id, page} pairs.

STRICT citation rule: only add a citation to a step if that step's content is actually drawn \
from one of the provided excerpts for that exact source_id and page. Never invent or guess a \
citation, and never attach a citation just because a source was provided somewhere in context —
if a step comes from your own general knowledge rather than a specific excerpt, leave its \
citations list empty.

Also produce `caveats`: a list of important warnings or trade-offs the analyst should keep in \
mind (e.g. tension between fast containment and preserving forensic evidence, risk of tipping \
off an attacker, legal/regulatory notification obligations). If the classification or the \
incident report indicates the incident is still ongoing/active, caveats MUST include the \
trade-off between urgent containment and preserving evidence for later analysis.

Only include diagnostic/investigative steps. Do not include remediation, containment, or \
eradication actions themselves, since those require human approval and are out of scope here — \
mention containment only as a caveat, not as a step. Write every field in the SAME language as \
the original incident report.
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
            f"[source_id: {chunk.source_id}, page: {chunk.page}] {chunk.title}\n{chunk.text}"
            for chunk in state.retrieved_chunks
        )
        parts.append(
            "Relevant procedure excerpts (only cite a step to one of these exact "
            f"[source_id, page] pairs if the step's content actually comes from it):\n{excerpts}"
        )

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
