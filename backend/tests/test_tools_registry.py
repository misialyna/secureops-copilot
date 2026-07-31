from datetime import UTC, datetime

import pytest

import app.tools.registry as registry_module
from app.tools.approval import ApprovalDecision
from app.tools.registry import (
    ToolResult,
    ToolSpec,
    execute_tool,
    get_spec,
    list_tools,
    preview_tool,
    register_tool,
)


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    """register_tool() mutates a module-level global dict shared with the real tools
    (log_analyzer, attack_lookup, pcap_analyzer) — restore it after each test so the
    dummy tools registered here never leak into other test modules."""
    original = dict(registry_module._REGISTRY)
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(original)


def _dummy_read_only(**kwargs: object) -> ToolResult:
    return ToolResult(tool_name="dummy_read_only", summary="ran fine")


def _dummy_active(**kwargs: object) -> ToolResult:
    return ToolResult(tool_name="dummy_active", summary="should never run")


def test_registered_read_only_tool_appears_in_list_tools() -> None:
    register_tool(
        ToolSpec(
            name="dummy_read_only",
            description="A dummy read-only tool for tests.",
            risk_level="read_only",
            input_schema={"type": "object", "properties": {}},
        ),
        _dummy_read_only,
    )

    names = {spec.name for spec in list_tools()}
    assert "dummy_read_only" in names
    assert get_spec("dummy_read_only").risk_level == "read_only"


def test_execute_tool_runs_read_only_tool() -> None:
    register_tool(
        ToolSpec(
            name="dummy_read_only",
            description="A dummy read-only tool for tests.",
            risk_level="read_only",
            input_schema={"type": "object", "properties": {}},
        ),
        _dummy_read_only,
    )

    result = execute_tool("dummy_read_only")

    assert result.summary == "ran fine"


def test_execute_tool_blocks_active_tools_without_approval() -> None:
    register_tool(
        ToolSpec(
            name="dummy_active",
            description="A dummy active tool for tests.",
            risk_level="active",
            input_schema={"type": "object", "properties": {}},
        ),
        _dummy_active,
    )

    with pytest.raises(PermissionError, match="approv"):
        execute_tool("dummy_active")


def test_execute_tool_blocks_active_tools_with_unapproved_decision() -> None:
    register_tool(
        ToolSpec(
            name="dummy_active",
            description="A dummy active tool for tests.",
            risk_level="active",
            input_schema={"type": "object", "properties": {}},
        ),
        _dummy_active,
    )
    decision = ApprovalDecision(
        action_id="a1", approved=False, decided_at=datetime.now(UTC), comment="no"
    )

    with pytest.raises(PermissionError, match="approv"):
        execute_tool("dummy_active", approval=decision)


def test_execute_tool_runs_active_tool_with_approved_decision() -> None:
    register_tool(
        ToolSpec(
            name="dummy_active",
            description="A dummy active tool for tests.",
            risk_level="active",
            input_schema={"type": "object", "properties": {}},
        ),
        _dummy_active,
    )
    decision = ApprovalDecision(
        action_id="a1", approved=True, decided_at=datetime.now(UTC), comment="go ahead"
    )

    result = execute_tool("dummy_active", approval=decision)

    assert result.summary == "should never run"


def test_preview_tool_returns_none_when_the_tool_has_no_preview_fn() -> None:
    register_tool(
        ToolSpec(
            name="dummy_active",
            description="A dummy active tool for tests.",
            risk_level="active",
            input_schema={"type": "object", "properties": {}},
        ),
        _dummy_active,
    )

    assert preview_tool("dummy_active") is None


def test_preview_tool_calls_preview_fn_with_no_approval_required() -> None:
    def _preview(**kwargs: object) -> ToolResult:
        return ToolResult(tool_name="dummy_active", summary=f"preview of {kwargs}")

    register_tool(
        ToolSpec(
            name="dummy_active",
            description="A dummy active tool for tests.",
            risk_level="active",
            input_schema={"type": "object", "properties": {}},
            preview_fn=_preview,
        ),
        _dummy_active,
    )

    result = preview_tool("dummy_active", {"ip": "1.2.3.4"})

    assert result is not None
    assert "1.2.3.4" in result.summary
