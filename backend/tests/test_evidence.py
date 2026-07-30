from pathlib import Path

import pytest

from app.evidence import (
    UnsupportedEvidenceExtension,
    list_evidence,
    resolve_evidence_path,
    store_evidence,
)


def test_store_evidence_uses_a_random_stored_name(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "thread-1"

    stored_name, display_name = store_evidence(evidence_dir, "auth.log", b"hello")

    assert display_name == "auth.log"
    assert stored_name != "auth.log"
    assert stored_name.endswith(".log")
    assert (evidence_dir / stored_name).read_bytes() == b"hello"
    assert not (evidence_dir / "auth.log").exists()


def test_store_evidence_rejects_disallowed_extension(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "thread-1"

    with pytest.raises(UnsupportedEvidenceExtension):
        store_evidence(evidence_dir, "payload.exe", b"hello")

    assert not evidence_dir.exists() or list(evidence_dir.iterdir()) == []


def test_store_evidence_path_traversal_name_stays_inside_evidence_dir(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_dir = evidence_root / "thread-1"

    stored_name, display_name = store_evidence(evidence_dir, "../../evil.log", b"payload")

    # the malicious name must never escape evidence_dir...
    assert not (tmp_path / "evil.log").exists()
    assert not (tmp_path.parent / "evil.log").exists()
    # ...the file must exist inside it under a safe, random name...
    assert (evidence_dir / stored_name).read_bytes() == b"payload"
    # ...and the traversal prefix must not survive into the display name either
    assert display_name == "evil.log"
    assert ".." not in display_name


def test_store_evidence_handles_filename_collisions(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "thread-1"

    first_stored, _ = store_evidence(evidence_dir, "auth.log", b"first upload")
    second_stored, _ = store_evidence(evidence_dir, "auth.log", b"second upload")

    assert first_stored != second_stored
    assert (evidence_dir / first_stored).read_bytes() == b"first upload"
    assert (evidence_dir / second_stored).read_bytes() == b"second upload"
    assert list_evidence(evidence_dir) == ["auth.log", "auth.log"]


def test_list_evidence_returns_display_names(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "thread-1"
    store_evidence(evidence_dir, "auth.log", b"a")
    store_evidence(evidence_dir, "capture.pcap", b"b")

    assert list_evidence(evidence_dir) == ["auth.log", "capture.pcap"]


def test_list_evidence_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    assert list_evidence(tmp_path / "evidence" / "no-such-thread") == []


def test_resolve_evidence_path_finds_the_real_file(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "thread-1"
    stored_name, display_name = store_evidence(evidence_dir, "auth.log", b"hello")

    resolved = resolve_evidence_path(evidence_dir, display_name)

    assert resolved == evidence_dir / stored_name
    assert resolved.read_bytes() == b"hello"


def test_resolve_evidence_path_returns_none_for_unknown_name(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "thread-1"
    store_evidence(evidence_dir, "auth.log", b"hello")

    assert resolve_evidence_path(evidence_dir, "../../../etc/passwd") is None
    assert resolve_evidence_path(evidence_dir, "nonexistent.log") is None
