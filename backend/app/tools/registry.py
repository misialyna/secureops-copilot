from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field


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


def execute_tool(name: str, **kwargs: Any) -> ToolResult:
    spec, fn = _REGISTRY[name]
    if spec.risk_level == "active":
        raise NotImplementedError(
            f"Tool '{name}' is risk_level='active' and requires human approval before "
            "it can run. The approval gate is not implemented yet (planned for a later stage) "
            "— this is a placeholder to make the gap explicit rather than silently executing."
        )
    return fn(**kwargs)
