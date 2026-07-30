from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


def _client_for(tmp_path: Path) -> tuple[AsyncClient, Path]:
    evidence_root = tmp_path / "evidence"
    settings = Settings(evidence_dir=str(evidence_root))
    app = create_app(settings=settings)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), evidence_root


@pytest.mark.asyncio
async def test_upload_with_path_traversal_filename_stays_inside_evidence_dir(
    tmp_path: Path,
) -> None:
    client, evidence_root = _client_for(tmp_path)
    thread_id = "traversal-thread"

    async with client:
        response = await client.post(
            f"/incidents/{thread_id}/evidence",
            files={"file": ("../../evil.log", b"malicious content", "text/plain")},
        )

    assert response.status_code == 200
    assert response.json()["filename"] == "evil.log"

    # nothing was ever created outside this thread's own evidence directory
    assert not (tmp_path / "evil.log").exists()
    assert not (evidence_root / "evil.log").exists()
    assert not (evidence_root.parent / "evil.log").exists()

    evidence_dir = evidence_root / thread_id
    stored_files = [p for p in evidence_dir.iterdir() if p.name != "manifest.json"]
    assert len(stored_files) == 1
    assert stored_files[0].name != "../../evil.log"
    assert stored_files[0].read_bytes() == b"malicious content"


@pytest.mark.asyncio
async def test_upload_then_list_shows_sanitized_display_name(tmp_path: Path) -> None:
    client, _ = _client_for(tmp_path)
    thread_id = "list-thread"

    async with client:
        await client.post(
            f"/incidents/{thread_id}/evidence",
            files={"file": ("../../evil.log", b"x", "text/plain")},
        )
        response = await client.get(f"/incidents/{thread_id}/evidence")

    assert response.status_code == 200
    assert response.json()["files"] == ["evil.log"]


@pytest.mark.asyncio
async def test_upload_rejects_disallowed_extension(tmp_path: Path) -> None:
    client, evidence_root = _client_for(tmp_path)
    thread_id = "bad-ext-thread"

    async with client:
        response = await client.post(
            f"/incidents/{thread_id}/evidence",
            files={"file": ("payload.exe", b"x", "application/octet-stream")},
        )

    assert response.status_code == 400
    evidence_dir = evidence_root / thread_id
    assert not evidence_dir.exists() or list(evidence_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_twice_with_same_name_does_not_collide(tmp_path: Path) -> None:
    client, evidence_root = _client_for(tmp_path)
    thread_id = "collision-thread"

    async with client:
        await client.post(
            f"/incidents/{thread_id}/evidence",
            files={"file": ("auth.log", b"first", "text/plain")},
        )
        await client.post(
            f"/incidents/{thread_id}/evidence",
            files={"file": ("auth.log", b"second", "text/plain")},
        )
        response = await client.get(f"/incidents/{thread_id}/evidence")

    assert response.json()["files"] == ["auth.log", "auth.log"]
    evidence_dir = evidence_root / thread_id
    contents = {p.read_bytes() for p in evidence_dir.iterdir() if p.name != "manifest.json"}
    assert contents == {b"first", b"second"}
