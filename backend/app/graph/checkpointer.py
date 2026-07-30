"""Picks and initializes the LangGraph checkpointer.

If `settings.database_url` is set, use Postgres (AsyncPostgresSaver) — this covers both
production (HF Spaces + Neon) and local development against the docker-compose Postgres.
Otherwise fall back to the local SQLite file used since Etap 3, so tests and CI never need a
running Postgres.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import Settings
from app.graph.builder import CHECKPOINT_SERDE

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _ensure_sslmode(database_url: str) -> str:
    """Managed Postgres (e.g. Neon) requires sslmode=require; local docker-compose Postgres
    has no TLS configured, so only add it for a non-local host, and only when the connection
    string doesn't already specify a mode explicitly."""
    parts = urlsplit(database_url)
    query_pairs = parse_qsl(parts.query)
    if any(key == "sslmode" for key, _ in query_pairs):
        return database_url
    if (parts.hostname or "") in _LOCAL_HOSTS:
        return database_url
    query_pairs.append(("sslmode", "require"))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query_pairs), parts.fragment)
    )


@asynccontextmanager
async def get_checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver]:
    if settings.database_url:
        dsn = _ensure_sslmode(settings.database_url)
        async with AsyncPostgresSaver.from_conn_string(dsn, serde=CHECKPOINT_SERDE) as checkpointer:
            await checkpointer.setup()
            yield checkpointer
        return

    checkpoint_path = Path(settings.checkpoint_db_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(checkpoint_path)) as conn:
        checkpointer = AsyncSqliteSaver(conn, serde=CHECKPOINT_SERDE)
        await checkpointer.setup()
        yield checkpointer
