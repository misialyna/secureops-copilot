"""Lightweight file-based store for incident drafts: a thread_id + description that exists
before the graph has ever run (POST /incidents creates a draft; POST /incidents/{id}/start
actually invokes the graph for the first time). Kept entirely outside the LangGraph
checkpointer — "draft" is a pure pre-graph bookkeeping concept, so no graph/node changes are
needed to support an upload window before analysis begins.
"""

import json
from pathlib import Path


def _draft_path(drafts_dir: Path, thread_id: str) -> Path:
    return drafts_dir / f"{thread_id}.json"


def save_draft(drafts_dir: Path, thread_id: str, description: str) -> None:
    drafts_dir.mkdir(parents=True, exist_ok=True)
    _draft_path(drafts_dir, thread_id).write_text(json.dumps({"description": description}))


def load_draft(drafts_dir: Path, thread_id: str) -> str | None:
    path = _draft_path(drafts_dir, thread_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())["description"]


def delete_draft(drafts_dir: Path, thread_id: str) -> None:
    _draft_path(drafts_dir, thread_id).unlink(missing_ok=True)
