"""Shared vocabulary for the human-in-the-loop approval flow.

Lives alongside registry.py (not in app/graph/) because ApprovalDecision is a tools-domain
concept that registry.execute_tool() itself needs to enforce the approval gate — putting it
in app/graph/schemas.py would create a reverse dependency (app/tools importing app/graph).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.tools.registry import ToolResult


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
    preview: ToolResult | None = None
    """Populated server-side (propose_actions node, via registry.preview_tool) from the same
    preview_fn that would eventually run the tool for real — never asked of the LLM, so it
    can't drift from what execution would actually do. None if the tool has no preview_fn."""


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
