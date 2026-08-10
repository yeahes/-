"""Path and JSON serialization helpers for stable subtitle artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Tuple


def stable_artifact_dir(report_path: Path) -> Path:
    """Return the stable artifact directory paired with one coverage report."""
    stem = report_path.stem
    if stem.endswith("-coverage-report"):
        stem = stem[: -len("-coverage-report")]
    return report_path.with_name(f"{stem}-artifacts")


def _json_default(value: Any) -> Any:
    """Serialize enum-backed configuration values without weakening JSON checks."""
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json_artifact(path: Path, payload: Any) -> None:
    """Atomically write one UTF-8 JSON artifact in the established format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def write_text_artifact(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically publish one text artifact on the destination filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding=encoding, newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest_artifact(
    manifest: dict,
    path_key: str,
    artifact_path: Path,
) -> bool:
    """Validate a manifest-owned file without weakening schema-v1 compatibility."""
    declared = str((manifest.get("paths") or {}).get(path_key) or "")
    if not declared or not artifact_path.is_file() or artifact_path.stat().st_size <= 0:
        return False
    try:
        if Path(declared).resolve() != artifact_path.resolve():
            return False
        run_dir_text = str(manifest.get("stable_run_dir") or "")
        if run_dir_text and artifact_path.resolve().parent != Path(run_dir_text).resolve():
            return False
    except OSError:
        return False

    expected = str((manifest.get("paths_sha256") or {}).get(path_key) or "")
    if int(manifest.get("schema_version") or 1) >= 2 and not expected:
        return False
    if expected and not hmac.compare_digest(expected, file_sha256(artifact_path)):
        return False
    return True


def write_json_artifact_set(
    artifact_dir: Path,
    named_payloads: Iterable[Tuple[str, Any]],
) -> None:
    """Write a stable artifact set in the caller-provided order.

    The editor remains responsible for assembling each payload. Keeping the
    filesystem loop here makes the artifact boundary explicit without coupling
    serialization to subtitle objects or pipeline state.
    """
    for filename, payload in named_payloads:
        write_json_artifact(artifact_dir / filename, payload)
