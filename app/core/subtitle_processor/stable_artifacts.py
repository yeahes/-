"""Path and JSON serialization helpers for stable subtitle artifacts."""

from __future__ import annotations

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
