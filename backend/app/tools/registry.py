from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    # Only needed for the `approval` type hint below, never constructed here — kept out of
    # the runtime import graph so app.tools.approval can import ToolResult from this module
    # (preview_fn's return type) without the two modules importing each other at runtime.
    from app.tools.approval import ApprovalDecision

ToolFunction = Callable[..., "ToolResult"]


class PreviewDriftError(RuntimeError):
    """Raised when a tool's preview_fn, re-run right before execution, no longer matches the
    preview an analyst already reviewed and approved — see approval_gate in app/graph/nodes.py,
    which catches this instead of executing and records it as a failed, unexecuted audit entry
    rather than letting one drifted action take down the rest of the batch."""

    def __init__(self, action_id: str, tool_name: str) -> None:
        self.action_id = action_id
        self.tool_name = tool_name
        super().__init__(
            f"Preview for action {action_id!r} (tool {tool_name!r}) no longer matches what "
            "preview_tool computes for the same args — refusing to execute something that has "
            "drifted from what the analyst approved."
        )


class ToolResult(BaseModel):
    tool_name: str
    summary: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    risk_level: Literal["read_only", "active"]
    input_schema: dict[str, Any]
    preview_fn: ToolFunction | None = None
    """Side-effect-free by contract: called before an action is approved, to show an analyst
    what an 'active' tool would do. Only meaningful for risk_level="active" tools — read_only
    tools already run immediately, so there's nothing to preview. A tool that has no preview_fn
    simply produces no preview (see preview_tool below)."""


_REGISTRY: dict[str, tuple[ToolSpec, ToolFunction]] = {}


def register_tool(spec: ToolSpec, fn: ToolFunction) -> None:
    _REGISTRY[spec.name] = (spec, fn)


def list_tools() -> list[ToolSpec]:
    return [spec for spec, _ in _REGISTRY.values()]


def get_spec(name: str) -> ToolSpec:
    spec, _ = _REGISTRY[name]
    return spec


def preview_tool(name: str, args: dict[str, Any] | None = None) -> ToolResult | None:
    """Runs a tool's preview_fn, if it has one — the only path besides execute_tool() into a
    tool's logic, and the only one that requires no approval, since preview_fn is side-effect-
    free by contract. Returns None for tools with no preview_fn (e.g. read_only tools, or any
    active tool that hasn't defined one)."""
    spec = get_spec(name)
    if spec.preview_fn is None:
        return None
    return spec.preview_fn(**(args or {}))


def execute_tool(
    name: str, args: dict[str, Any] | None = None, approval: "ApprovalDecision | None" = None
) -> ToolResult:
    spec, fn = _REGISTRY[name]
    if spec.risk_level == "active" and not (approval is not None and approval.approved):
        raise PermissionError(
            f"Tool '{name}' is risk_level='active' and requires an approved ApprovalDecision "
            "before it can run — none was provided, or it was not approved. This check is "
            "enforced here regardless of what any LLM decides."
        )
    return fn(**(args or {}))
