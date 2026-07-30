from pathlib import Path

from langchain_core.messages import AIMessage

from app.config import Settings
from app.graph.nodes import MAX_TOOL_CALLS, build_tools_node
from app.graph.state import AgentState

_AUTH_LOG_LINES = [
    "Jan 12 03:14:01 web01 sshd[1001]: Failed password for invalid user admin from 203.0.113.5 port 51001 ssh2",
    "Jan 12 03:14:10 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51002 ssh2",
    "Jan 12 03:14:20 web01 sshd[1001]: Failed password for admin from 203.0.113.5 port 51003 ssh2",
    "Jan 12 03:14:30 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51004 ssh2",
    "Jan 12 03:14:40 web01 sshd[1001]: Failed password for test from 203.0.113.5 port 51005 ssh2",
    "Jan 12 03:14:50 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51006 ssh2",
    "Jan 12 03:15:00 web01 sshd[1001]: Failed password for admin from 203.0.113.5 port 51007 ssh2",
    "Jan 12 03:15:10 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51008 ssh2",
    "Jan 12 03:15:20 web01 sshd[1001]: Failed password for guest from 203.0.113.5 port 51009 ssh2",
    "Jan 12 03:15:30 web01 sshd[1001]: Failed password for root from 203.0.113.5 port 51010 ssh2",
]


class FakeToolCallingLLM:
    """Fakes only the LLM's tool-selection decision; execute_tool() below still runs
    the real, registered tool implementation against the fixture evidence file."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.bound_tools: list[dict] | None = None

    def bind_tools(self, tools: list[dict]) -> "FakeToolCallingLLM":
        self.bound_tools = tools
        return self

    def invoke(self, messages: list[object]) -> AIMessage:
        return self._responses.pop(0)


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_tools_node_executes_real_tool_chosen_by_fake_llm(tmp_path: Path) -> None:
    thread_id = "thread-abc"
    evidence_dir = tmp_path / "evidence" / thread_id
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "auth.log").write_text("\n".join(_AUTH_LOG_LINES) + "\n")
    settings = Settings(evidence_dir=str(tmp_path / "evidence"))

    fake_llm = FakeToolCallingLLM(
        [
            AIMessage(
                content="", tool_calls=[_tool_call("log_analyzer", {"file_path": "auth.log"}, "call_1")]
            ),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    node = build_tools_node(fake_llm, settings=settings)
    state = AgentState(incident_description="Possible SSH brute force")
    config = {"configurable": {"thread_id": thread_id}}

    result = node(state, config)

    assert fake_llm.bound_tools is not None
    assert {tool["function"]["name"] for tool in fake_llm.bound_tools} >= {
        "log_analyzer",
        "pcap_analyzer",
        "attack_lookup",
    }

    tool_results = result["tool_results"]
    assert len(tool_results) == 1
    assert tool_results[0].tool_name == "log_analyzer"
    assert any(finding.get("failed_count") == 10 for finding in tool_results[0].findings)


def test_tools_node_skips_when_no_evidence_uploaded(tmp_path: Path) -> None:
    settings = Settings(evidence_dir=str(tmp_path / "evidence"))
    fake_llm = FakeToolCallingLLM([])  # must never be called

    node = build_tools_node(fake_llm, settings=settings)
    result = node(
        AgentState(incident_description="no evidence here"),
        {"configurable": {"thread_id": "no-evidence-thread"}},
    )

    assert result == {"tool_results": []}
    assert fake_llm.bound_tools is None


def test_tools_node_stops_after_max_tool_calls(tmp_path: Path) -> None:
    thread_id = "loop-thread"
    evidence_dir = tmp_path / "evidence" / thread_id
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "auth.log").write_text("harmless log line\n")
    settings = Settings(evidence_dir=str(tmp_path / "evidence"))

    # An LLM that always wants to call another tool and never stops on its own.
    responses = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("log_analyzer", {"file_path": "auth.log"}, f"call_{i}")],
        )
        for i in range(10)
    ]
    fake_llm = FakeToolCallingLLM(responses)
    node = build_tools_node(fake_llm, settings=settings)

    result = node(
        AgentState(incident_description="x"), {"configurable": {"thread_id": thread_id}}
    )

    assert len(result["tool_results"]) == MAX_TOOL_CALLS


def test_tools_node_handles_unknown_tool_call_gracefully(tmp_path: Path) -> None:
    thread_id = "bad-call-thread"
    evidence_dir = tmp_path / "evidence" / thread_id
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "auth.log").write_text("harmless\n")
    settings = Settings(evidence_dir=str(tmp_path / "evidence"))

    fake_llm = FakeToolCallingLLM(
        [
            AIMessage(content="", tool_calls=[_tool_call("nonexistent_tool", {}, "call_1")]),
            AIMessage(content="done", tool_calls=[]),
        ]
    )
    node = build_tools_node(fake_llm, settings=settings)

    result = node(
        AgentState(incident_description="x"), {"configurable": {"thread_id": thread_id}}
    )

    assert len(result["tool_results"]) == 1
    assert result["tool_results"][0].warnings
