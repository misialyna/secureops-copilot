from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.tools.approval import ApprovalDecision


class ToolSpec(BaseModel):
    name: str
    description: str
    risk_level: Literal["read_only", "active"]
    input_schema: dict[str, Any]


class ToolResult(BaseModel):
    tool_name: str
    summary: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


ToolFunction = Callable[..., ToolResult]

_REGISTRY: dict[str, tuple[ToolSpec, ToolFunction]] = {}


def register_tool(spec: ToolSpec, fn: ToolFunction) -> None:
    _REGISTRY[spec.name] = (spec, fn)


def list_tools() -> list[ToolSpec]:
    return [spec for spec, _ in _REGISTRY.values()]


def get_spec(name: str) -> ToolSpec:
    spec, _ = _REGISTRY[name]
    return spec


def execute_tool(
    name: str, args: dict[str, Any] | None = None, approval: ApprovalDecision | None = None
) -> ToolResult:
    spec, fn = _REGISTRY[name]
    if spec.risk_level == "active" and not (approval is not None and approval.approved):
        raise PermissionError(
            f"Tool '{name}' is risk_level='active' and requires an approved ApprovalDecision "
            "before it can run — none was provided, or it was not approved. This check is "
            "enforced here regardless of what any LLM decides."
        )
    return fn(**(args or {}))
