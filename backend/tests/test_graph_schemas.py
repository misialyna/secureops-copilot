import pytest
from pydantic import ValidationError

from app.graph.schemas import Citation, DiagnosticPlan, DiagnosticStep, IncidentClassification


def test_incident_classification_valid() -> None:
    classification = IncidentClassification(
        category="phishing",
        severity="medium",
        confidence=0.75,
        reasoning="Email contains a credential-harvesting link",
        missing_info=[],
    )
    assert classification.category == "phishing"
    assert classification.missing_info == []


def test_incident_classification_missing_info_defaults_to_empty() -> None:
    classification = IncidentClassification(
        category="other",
        severity="low",
        confidence=0.5,
        reasoning="not enough detail",
    )
    assert classification.missing_info == []


def test_incident_classification_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        IncidentClassification(
            category="not_a_real_category",
            severity="low",
            confidence=0.5,
            reasoning="x",
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_incident_classification_rejects_confidence_out_of_range(confidence: float) -> None:
    with pytest.raises(ValidationError):
        IncidentClassification(
            category="other",
            severity="low",
            confidence=confidence,
            reasoning="x",
        )


def test_diagnostic_plan_valid() -> None:
    plan = DiagnosticPlan(
        steps=[
            DiagnosticStep(
                description="Review authentication logs",
                rationale="Confirm scope of unauthorized access",
                expected_evidence="List of anomalous login events",
                priority=1,
                citations=[Citation(source_id="nist-sp-800-61r3", page=12)],
            )
        ],
        caveats=["Rotating credentials mid-investigation may tip off the attacker."],
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].description == "Review authentication logs"
    assert plan.steps[0].citations == [Citation(source_id="nist-sp-800-61r3", page=12)]
    assert plan.caveats


def test_diagnostic_step_citations_and_caveats_default_to_empty() -> None:
    step = DiagnosticStep(
        description="Check for known persistence mechanisms",
        rationale="General best practice for this incident type",
        expected_evidence="Presence/absence of unfamiliar scheduled tasks",
        priority=2,
    )
    assert step.citations == []

    plan = DiagnosticPlan(steps=[step])
    assert plan.caveats == []


def test_diagnostic_step_requires_priority() -> None:
    with pytest.raises(ValidationError):
        DiagnosticStep(
            description="x",
            rationale="y",
            expected_evidence="z",
        )


def test_diagnostic_step_rejects_non_positive_priority() -> None:
    with pytest.raises(ValidationError):
        DiagnosticStep(
            description="x",
            rationale="y",
            expected_evidence="z",
            priority=0,
        )


def test_citation_requires_source_id_and_page() -> None:
    citation = Citation(source_id="cisa-ir-vr-playbooks", page=14)
    assert citation.source_id == "cisa-ir-vr-playbooks"
    assert citation.page == 14
