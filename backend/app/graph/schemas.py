from typing import Literal

from pydantic import BaseModel, Field

IncidentCategory = Literal[
    "malware",
    "ransomware",
    "phishing",
    "unauthorized_access",
    "denial_of_service",
    "data_breach",
    "insider_threat",
    "other",
]

Severity = Literal["low", "medium", "high", "critical"]


class IncidentClassification(BaseModel):
    category: IncidentCategory
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    missing_info: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    source_id: str
    page: int


class DiagnosticStep(BaseModel):
    description: str
    rationale: str
    expected_evidence: str
    priority: int = Field(ge=1)
    citations: list[Citation] = Field(default_factory=list)


class DiagnosticPlan(BaseModel):
    steps: list[DiagnosticStep]
    caveats: list[str] = Field(default_factory=list)
