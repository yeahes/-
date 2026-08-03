"""Path and JSON serialization helpers for stable subtitle artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Tuple


def stable_artifact_dir(report_path: Path) -> Path:
    """Return the stable artifact directory paired with one coverage report."""
    stem = report_path.stem
    if stem.endswith("-coverage-report"):
        stem = stem[: -len("-coverage-report")]
    return report_path.with_name(f"{stem}-artifacts")


def write_json_artifact(path: Path, payload: Any) -> None:
    """Write one artifact with the established UTF-8, readable JSON format."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
