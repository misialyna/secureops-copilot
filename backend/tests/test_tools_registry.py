import pytest

import app.tools.registry as registry_module
from app.tools.registry import (
    ToolResult,
    ToolSpec,
    execute_tool,
    get_spec,
    list_tools,
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


def test_execute_tool_blocks_active_tools_pending_approval_gate() -> None:
    register_tool(
        ToolSpec(
            name="dummy_active",
            description="A dummy active tool for tests.",
            risk_level="active",
            input_schema={"type": "object", "properties": {}},
        ),
        _dummy_active,
    )

    with pytest.raises(NotImplementedError, match="approval"):
        execute_tool("dummy_active")
