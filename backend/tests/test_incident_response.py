from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.graph.builder import build_graph
from app.graph.schemas import Citation, DiagnosticPlan, DiagnosticStep, IncidentClassification
from app.main import _build_response
from app.rag.retriever import RetrievedChunk


class FakeRetriever:
    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                text="Isolate the affected host from the network.",
                source_id="cisa-ir-vr-playbooks",
                title="CISA Playbooks",
                page=14,
                score=0.9,
            )
        ]


def test_citations_survive_graph_to_api_response() -> None:
    classify_llm = RunnableLambda(
        lambda messages: IncidentClassification(
            category="ransomware",
            severity="critical",
            confidence=0.95,
            reasoning="Confirmed ransomware on the file server",
            missing_info=[],
        )
    )
    plan_llm = RunnableLambda(
        lambda messages: DiagnosticPlan(
            steps=[
                DiagnosticStep(
                    description="Review EDR process-creation logs on file-server-01",
                    rationale="Identify the initial execution vector",
                    expected_evidence="Suspicious parent/child process chain around infection time",
                    priority=1,
                    citations=[Citation(source_id="cisa-ir-vr-playbooks", page=14)],
                ),
                DiagnosticStep(
                    description="Check for common persistence mechanisms",
                    rationale="Rule out well-known persistence techniques",
                    expected_evidence="Presence/absence of unfamiliar scheduled tasks or run keys",
                    priority=2,
                    citations=[],
                ),
            ],
            caveats=["Balance urgent containment against preserving forensic evidence."],
        )
    )
    # this incident has no uploaded evidence, so the tools node returns before ever calling
    # tools_llm — it only needs to exist so build_graph() doesn't construct a real ChatGroq
    tools_llm = RunnableLambda(lambda messages: AIMessage(content="", tool_calls=[]))
    graph = build_graph(
        classify_llm=classify_llm,
        tools_llm=tools_llm,
        plan_llm=plan_llm,
        retriever=FakeRetriever(),
    )

    config = {"configurable": {"thread_id": "citation-passthrough"}}
    result = graph.invoke(
        {"incident_description": "Ransom note found on the shared drive"}, config=config
    )

    response = _build_response(
        "citation-passthrough", result, result.get("__interrupt__", ())
    )

    assert response.status == "completed"
    assert response.plan is not None
    assert response.plan.steps[0].citations == [
        Citation(source_id="cisa-ir-vr-playbooks", page=14)
    ]
    assert response.plan.steps[1].citations == []
    assert response.plan.caveats
