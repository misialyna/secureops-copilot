"""Evidence file storage and lookup, shared by the FastAPI upload/list endpoints and the
`tools` graph node.

Uploaded evidence is stored under a random name (uuid + validated extension) — never the
client-supplied filename — recording the original filename only as a display string in a
per-thread manifest. This means the client-supplied name is never used to build a filesystem
path (no path traversal, no collisions between uploads), and callers that need to open a
specific file must go through resolve_evidence_path(), which looks the real path up via the
manifest instead of joining the untrusted name onto a directory.
"""

import json
from pathlib import Path
from uuid import uuid4

ALLOWED_EVIDENCE_EXTENSIONS = {".log", ".txt", ".pcap", ".pcapng"}
_MANIFEST_FILENAME = "manifest.json"


class UnsupportedEvidenceExtension(ValueError):
    pass


def validate_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EVIDENCE_EXTENSIONS:
        raise UnsupportedEvidenceExtension(
            f"Unsupported or missing file extension '{extension}'. "
            f"Allowed: {sorted(ALLOWED_EVIDENCE_EXTENSIONS)}"
        )
    return extension


def _manifest_path(evidence_dir: Path) -> Path:
    return evidence_dir / _MANIFEST_FILENAME


def _load_manifest(evidence_dir: Path) -> dict[str, str]:
    manifest_file = _manifest_path(evidence_dir)
    if not manifest_file.exists():
        return {}
    return json.loads(manifest_file.read_text())


def _save_manifest(evidence_dir: Path, manifest: dict[str, str]) -> None:
    _manifest_path(evidence_dir).write_text(json.dumps(manifest))


def store_evidence(evidence_dir: Path, original_filename: str, contents: bytes) -> tuple[str, str]:
    """Validate the extension, then persist `contents` under a random filename.

    Returns (stored_name, display_name). Raises UnsupportedEvidenceExtension if the
    original filename's extension isn't in ALLOWED_EVIDENCE_EXTENSIONS.
    """
    extension = validate_extension(original_filename)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid4().hex}{extension}"
    (evidence_dir / stored_name).write_bytes(contents)

    # .name strips any directory components for display purposes; this value is never used
    # to build a filesystem path, only shown to the user/LLM and used as a manifest key.
    display_name = Path(original_filename).name or stored_name
    manifest = _load_manifest(evidence_dir)
    manifest[stored_name] = display_name
    _save_manifest(evidence_dir, manifest)
    return stored_name, display_name


def list_evidence(evidence_dir: Path) -> list[str]:
    """Display (original) filenames for this thread's evidence, not the on-disk stored names."""
    if not evidence_dir.exists():
        return []
    return sorted(_load_manifest(evidence_dir).values())


def resolve_evidence_path(evidence_dir: Path, display_name: str) -> Path | None:
    """Map a display filename (e.g. one an LLM echoed back) to its real on-disk path.

    Looked up via the manifest rather than joining `display_name` onto `evidence_dir` — so
    an attacker-influenced display name (a crafted original filename) can never point
    anywhere outside evidence_dir, no matter what it contains.
    """
    manifest = _load_manifest(evidence_dir)
    for stored_name, name in manifest.items():
        if name == display_name:
            return evidence_dir / stored_name
    return None
