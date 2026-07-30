import httpx
import pytest
from groq import BadRequestError
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.graph.retry import with_retry


def _tool_use_failed_error() -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "http://groq.test"))
    return BadRequestError(
        "tool call failed", response=response, body={"error": {"code": "tool_use_failed"}}
    )


def test_with_retry_succeeds_after_transient_failures() -> None:
    calls = {"n": 0}

    def flaky(x: str) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _tool_use_failed_error()
        return f"ok:{x}"

    settings = Settings(groq_max_retries=3, groq_retry_backoff_seconds=0.0)
    result = with_retry(flaky, settings=settings)("hi")

    assert result == "ok:hi"
    assert calls["n"] == 3


def test_with_retry_gives_up_after_max_attempts() -> None:
    calls = {"n": 0}

    def always_fails(x: str) -> str:
        calls["n"] += 1
        raise _tool_use_failed_error()

    settings = Settings(groq_max_retries=3, groq_retry_backoff_seconds=0.0)

    with pytest.raises(BadRequestError):
        with_retry(always_fails, settings=settings)("hi")

    assert calls["n"] == 3


def test_with_retry_does_not_retry_unrelated_errors() -> None:
    calls = {"n": 0}

    def broken(x: str) -> str:
        calls["n"] += 1
        raise ValueError("not a structured-output problem")

    settings = Settings(groq_max_retries=3, groq_retry_backoff_seconds=0.0)

    with pytest.raises(ValueError, match="not a structured-output problem"):
        with_retry(broken, settings=settings)("hi")

    assert calls["n"] == 1


def test_with_retry_retries_on_pydantic_validation_error() -> None:
    class Model(BaseModel):
        value: int

    calls = {"n": 0}

    def sometimes_invalid(x: str) -> Model:
        calls["n"] += 1
        if calls["n"] < 2:
            return Model.model_validate({"value": "not-an-int-but-unparsable"})
        return Model(value=1)

    settings = Settings(groq_max_retries=3, groq_retry_backoff_seconds=0.0)

    with pytest.raises(ValidationError):
        sometimes_invalid("x")  # sanity check the fixture itself raises without retry

    calls["n"] = 0
    result = with_retry(sometimes_invalid, settings=settings)("x")
    assert result == Model(value=1)
    assert calls["n"] == 2
