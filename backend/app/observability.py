"""Langfuse observability wiring (Etap 9): traces every LangGraph node as a span, grouped by
incident thread_id. Optional — the app must start and run with no Langfuse credentials configured
at all, exactly like the Postgres checkpointer (see app/graph/checkpointer.py): observability is
never a hard requirement to run the agent.
"""

import logging
from typing import Any

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.config import Settings

logger = logging.getLogger(__name__)


def init_langfuse(settings: Settings) -> bool:
    """Registers the global Langfuse client once, at app startup (see lifespan() in main.py).
    Every CallbackHandler() created afterwards picks up this client automatically — the handler
    itself carries no credentials. Returns False (no-op) if credentials aren't configured or the
    client fails to initialize — either way, this must never stop the app from starting."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning("Langfuse disabled: LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set.")
        return False
    try:
        Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_base_url,
        )
    except Exception as exc:  # noqa: BLE001 - observability must never block app startup
        logger.warning("Langfuse disabled: client initialization failed: %s", exc)
        return False
    logger.info("Langfuse observability enabled (host=%s).", settings.langfuse_base_url)
    return True


def get_langfuse_config(thread_id: str, langfuse_enabled: bool) -> dict[str, Any]:
    """Config fragment to merge into a graph.ainvoke(..., config=...) call: a callback handler
    that traces every graph node as a span, plus the session_id metadata that groups every trace
    from this incident's thread_id together in the Langfuse UI (LangGraph node names become span
    names automatically — no per-node wiring needed). Empty dict — safe to merge unconditionally,
    changes nothing — when Langfuse isn't configured.
    """
    if not langfuse_enabled:
        return {}
    return {
        "callbacks": [CallbackHandler()],
        "metadata": {"langfuse_session_id": thread_id},
    }
