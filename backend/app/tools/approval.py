"""Shared vocabulary for the human-in-the-loop approval flow.

Lives alongside registry.py (not in app/graph/) because ApprovalDecision is a tools-domain
concept that registry.execute_tool() itself needs to enforce the approval gate — putting it
in app/graph/schemas.py would create a reverse dependency (app/tools importing app/graph).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProposedActionDraft(BaseModel):
    """What an LLM proposes, before a stable id is assigned by the approval_gate node.

    LLMs are unreliable at producing globally-unique ids, so the id is never something we
    ask the model for — the node assigns it server-side once the draft is accepted.
    """

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    justification: str
    risk_note: str


class ProposedAction(ProposedActionDraft):
    id: str


class ApprovalDecision(BaseModel):
    action_id: str
    approved: bool
    decided_at: datetime
    comment: str | None = None


class AuditEntry(BaseModel):
    action: ProposedAction
    decision: ApprovalDecision
    executed: bool
    result_summary: str
    timestamp: datetime
