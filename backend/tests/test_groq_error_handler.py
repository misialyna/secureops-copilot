import logging
from pathlib import Path

import httpx
import pytest
from groq import RateLimitError
from httpx import ASGITransport, AsyncClient
from langchain_core.runnables import RunnableLambda

from app.config import Settings
from app.graph.builder import build_graph
from app.main import _rate_limit_detail, create_app
from app.rag.retriever import RetrievedChunk


class FakeRetriever:
    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        return []


def _unused_llm() -> RunnableLambda:
    """A fake for the four LLM roles these tests never actually reach (classify raises first).

    build_graph() constructs a real ChatGroq for every role not explicitly overridden — eagerly,
    at construction time, before any node runs. A real ChatGroq's __init__ needs a real API key
    (see the "critical Groq gotcha" in this project's history); without one it raises immediately,
    which is exactly what broke CI here even though classify_llm alone was overridden. This
    raises AssertionError instead of quietly succeeding, so if that assumption ever stops
    holding, the test fails loudly rather than silently doing the wrong thing."""

    def _fail(messages: object) -> None:
        raise AssertionError("this LLM role should never be invoked in this test")

    return RunnableLambda(_fail)


def _make_rate_limit_error(*, daily: bool) -> RateLimitError:
    """Builds a real groq.RateLimitError with the same shape Groq actually returns (confirmed
    by hand during the Etap 7 acceptance session), without any network call."""
    limit_kind = "tokens per day (TPD)" if daily else "tokens per minute (TPM)"
    error_message = (
        f"Rate limit reached for model `llama-3.3-70b-versatile` on {limit_kind}: "
        "Limit 100000, Used 99809, Requested 6510. Please try again in 1h30m59.616s."
    )
    body = {"error": {"message": error_message, "type": "tokens", "code": "rate_limit_exceeded"}}
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(
        status_code=429,
        headers={
            "x-ratelimit-limit-tokens": "12000",
            "x-ratelimit-remaining-tokens": "12000",
            "retry-after": "5460",
        },
        request=request,
    )
    return RateLimitError(message=f"Error code: 429 - {body}", response=response, body=body)


# --- unit tests for the pure daily/per-minute distinction -----------------------------------


def test_rate_limit_detail_recognizes_daily_limit() -> None:
    detail = _rate_limit_detail("Rate limit reached ... on tokens per day (TPD): Limit 100000")
    assert "jutro" in detail


def test_rate_limit_detail_recognizes_per_minute_limit() -> None:
    detail = _rate_limit_detail("Rate limit reached ... on tokens per minute (TPM): Limit 12000")
    assert "minutę" in detail


def test_rate_limit_detail_falls_back_when_ambiguous() -> None:
    detail = _rate_limit_detail("Rate limit reached, please slow down.")
    assert "jutro" not in detail
    assert "minutę" not in detail


# --- handler-level tests: logging + response detail -----------------------------------------


@pytest.mark.asyncio
async def test_daily_rate_limit_logs_warning_and_returns_daily_detail(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def _raise(messages: object) -> None:
        raise _make_rate_limit_error(daily=True)

    settings = Settings(
        evidence_dir=str(tmp_path / "evidence"), drafts_dir=str(tmp_path / "drafts")
    )
    app = create_app(settings=settings)
    app.state.graph = build_graph(
        classify_llm=RunnableLambda(_raise),
        tools_llm=_unused_llm(),
        plan_llm=_unused_llm(),
        approval_llm=_unused_llm(),
        report_llm=_unused_llm(),
        retriever=FakeRetriever(),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/incidents", json={"description": "x"})
        thread_id = create_response.json()["thread_id"]

        with caplog.at_level(logging.WARNING, logger="app.main"):
            response = await client.post(f"/incidents/{thread_id}/start")

    assert response.status_code == 429
    assert "jutro" in response.json()["detail"]

    assert len(caplog.records) == 1
    logged = caplog.records[0].getMessage()
    assert "tokens per day" in logged
    assert "Used 99809" in logged
    assert "x-ratelimit-remaining-tokens" in logged


@pytest.mark.asyncio
async def test_per_minute_rate_limit_returns_per_minute_detail(tmp_path: Path) -> None:
    def _raise(messages: object) -> None:
        raise _make_rate_limit_error(daily=False)

    settings = Settings(
        evidence_dir=str(tmp_path / "evidence"), drafts_dir=str(tmp_path / "drafts")
    )
    app = create_app(settings=settings)
    app.state.graph = build_graph(
        classify_llm=RunnableLambda(_raise),
        tools_llm=_unused_llm(),
        plan_llm=_unused_llm(),
        approval_llm=_unused_llm(),
        report_llm=_unused_llm(),
        retriever=FakeRetriever(),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/incidents", json={"description": "x"})
        thread_id = create_response.json()["thread_id"]
        response = await client.post(f"/incidents/{thread_id}/start")

    assert response.status_code == 429
    assert "minutę" in response.json()["detail"]
