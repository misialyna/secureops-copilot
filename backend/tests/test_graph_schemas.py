import pytest
from pydantic import ValidationError

from app.graph.schemas import DiagnosticPlan, DiagnosticStep, IncidentClassification


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
            )
        ]
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].description == "Review authentication logs"
