import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command

from app.graph.builder import build_graph
from app.graph.schemas import DiagnosticPlan, DiagnosticStep, IncidentClassification
from app.graph.state import ClarificationPair
from app.rag.retriever import RetrievedChunk


class FakeRetriever:
    """Stands in for KnowledgeRetriever: same `search` signature, no Qdrant/model involved."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        self.queries.append(query)
        return [
            RetrievedChunk(
                text="Isolate the affected host from the network.",
                source_id="cisa-ir-vr-playbooks",
                title="CISA Playbooks",
                page=14,
                score=0.9,
            )
        ]


def _plan_llm(steps: list[DiagnosticStep] | None = None) -> RunnableLambda:
    steps = steps or [
        DiagnosticStep(
            description="Collect endpoint logs",
            rationale="Confirm the infection vector",
            expected_evidence="Relevant log entries",
            priority=1,
        )
    ]
    return RunnableLambda(lambda messages: DiagnosticPlan(steps=steps))


@pytest.fixture
def fake_retriever() -> FakeRetriever:
    return FakeRetriever()


def test_graph_completes_without_clarification(fake_retriever: FakeRetriever) -> None:
    classify_llm = RunnableLambda(
        lambda messages: IncidentClassification(
            category="phishing",
            severity="medium",
            confidence=0.9,
            reasoning="Clear phishing indicators",
            missing_info=[],
        )
    )
    graph = build_graph(classify_llm=classify_llm, plan_llm=_plan_llm(), retriever=fake_retriever)

    config = {"configurable": {"thread_id": "no-clarification"}}
    result = graph.invoke(
        {"incident_description": "Employee received a fake invoice email with a login link"},
        config=config,
    )

    assert "__interrupt__" not in result
    assert result["classification"].category == "phishing"
    # clarify never ran in this path, so the "clarifications" channel was never written to and
    # is simply absent from the result (LangGraph only returns channels a node wrote), not "[]"
    assert result.get("clarifications", []) == []
    assert result["plan"].steps
    assert fake_retriever.queries  # retrieve node ran and queried the retriever


def test_graph_interrupt_then_resume(fake_retriever: FakeRetriever) -> None:
    call_count = {"n": 0}

    def fake_classify(messages: object) -> IncidentClassification:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return IncidentClassification(
                category="ransomware",
                severity="high",
                confidence=0.6,
                reasoning="Possible ransomware, missing scope",
                missing_info=["Which systems are affected?"],
            )
        return IncidentClassification(
            category="ransomware",
            severity="critical",
            confidence=0.95,
            reasoning="Confirmed ransomware on the file server",
            missing_info=[],
        )

    graph = build_graph(
        classify_llm=RunnableLambda(fake_classify),
        plan_llm=_plan_llm(),
        retriever=fake_retriever,
    )

    config = {"configurable": {"thread_id": "with-clarification"}}
    first_result = graph.invoke(
        {"incident_description": "Found a ransom note on a shared drive"}, config=config
    )

    assert "__interrupt__" in first_result
    interrupt = first_result["__interrupt__"][0]
    assert interrupt.value["questions"] == ["Which systems are affected?"]
    # graph paused before retrieve/plan ran
    assert "plan" not in first_result or first_result.get("plan") is None

    resumed_result = graph.invoke(
        Command(resume={"Which systems are affected?": "file-server-01"}), config=config
    )

    assert "__interrupt__" not in resumed_result
    assert resumed_result["clarifications"] == [
        ClarificationPair(question="Which systems are affected?", answer="file-server-01")
    ]
    assert resumed_result["classification"].severity == "critical"
    assert resumed_result["plan"].steps
    # only one clarification round happened, even though call_count reflects two classify calls
    assert call_count["n"] == 2


def test_graph_asks_only_one_round_of_clarification(fake_retriever: FakeRetriever) -> None:
    """Even if the second classification still reports missing_info, we proceed anyway."""

    def always_incomplete(messages: object) -> IncidentClassification:
        return IncidentClassification(
            category="other",
            severity="low",
            confidence=0.3,
            reasoning="Still unclear",
            missing_info=["What system is involved?"],
        )

    graph = build_graph(
        classify_llm=RunnableLambda(always_incomplete),
        plan_llm=_plan_llm(),
        retriever=fake_retriever,
    )

    config = {"configurable": {"thread_id": "always-incomplete"}}
    graph.invoke({"incident_description": "Something happened"}, config=config)
    resumed_result = graph.invoke(Command(resume={"What system is involved?": "unknown"}), config=config)

    assert "__interrupt__" not in resumed_result
    assert resumed_result["plan"].steps
    assert len(resumed_result["clarifications"]) == 1


def test_retrieve_query_includes_category(fake_retriever: FakeRetriever) -> None:
    classify_llm = RunnableLambda(
        lambda messages: IncidentClassification(
            category="denial_of_service",
            severity="high",
            confidence=0.8,
            reasoning="Traffic spike consistent with DoS",
            missing_info=[],
        )
    )
    graph = build_graph(classify_llm=classify_llm, plan_llm=_plan_llm(), retriever=fake_retriever)

    graph.invoke(
        {"incident_description": "Website is unreachable, huge traffic spike"},
        config={"configurable": {"thread_id": "dos-query"}},
    )

    assert any("denial_of_service" in query for query in fake_retriever.queries)
