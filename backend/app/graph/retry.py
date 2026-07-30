import functools
import logging
import time
from collections.abc import Callable

from groq import BadRequestError
from pydantic import ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)


def _is_tool_use_failure(exc: Exception) -> bool:
    """Groq's structured-output/tool-calling path occasionally returns malformed JSON
    (e.g. a trailing comma) for complex schemas and rejects it server-side as a 400
    with code "tool_use_failed". This is non-deterministic — retrying the same
    request often succeeds on the next generation."""
    if isinstance(exc, ValidationError):
        return True
    if isinstance(exc, BadRequestError):
        body = exc.body if isinstance(exc.body, dict) else {}
        return body.get("error", {}).get("code") == "tool_use_failed"
    return False


def with_retry[T](fn: Callable[..., T], *, settings: Settings | None = None) -> Callable[..., T]:
    """Wrap a structured-output LLM call with a few retries on transient failures.

    Only retries tool_use_failed / structured-output validation errors — anything
    else (auth errors, rate limits, etc.) is raised immediately since retrying
    wouldn't help.
    """
    settings = settings or Settings()
    max_attempts = max(1, settings.groq_max_retries)
    base_delay = settings.groq_retry_backoff_seconds

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> T:
        for attempt in range(1, max_attempts + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                if not _is_tool_use_failure(exc) or attempt == max_attempts:
                    raise
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Structured LLM call failed on attempt %d/%d (%s: %s); retrying in %.1fs",
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                time.sleep(delay)
        raise AssertionError("unreachable")  # loop always returns or raises

    return wrapper
