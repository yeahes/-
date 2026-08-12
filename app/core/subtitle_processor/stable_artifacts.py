"""Path and JSON serialization helpers for stable subtitle artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Tuple


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


def manifest_generation_dir(
    manifest_path: Path,
    manifest: Mapping[str, Any],
) -> Path | None:
    """Resolve the immutable generation owned by a schema-v3 package."""
    generation = manifest.get("package_generation") or {}
    if not isinstance(generation, Mapping):
        return None
    generation_id = str(generation.get("id") or "").strip()
    relative_text = str(generation.get("relative_dir") or "").strip()
    if (
        not generation_id
        or not relative_text
        or not all(character.isalnum() or character in "-_." for character in generation_id)
    ):
        return None
    relative_dir = Path(relative_text)
    if relative_dir.is_absolute() or ".." in relative_dir.parts:
        return None
    try:
        package_root = Path(manifest_path).resolve().parent
        generation_dir = (package_root / relative_dir).resolve()
        generation_dir.relative_to(package_root)
    except (OSError, ValueError):
        return None
    if generation_dir.name != generation_id:
        return None
    return generation_dir


def resolve_manifest_owned_path(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    declared_path: str | Path,
    expected_sha256: str = "",
    *,
    expect_directory: bool = False,
) -> Path | None:
    """Resolve one package-owned path without escaping its committed generation.

    Schema-v1/v2 packages retain their historical absolute-path and moved-package
    fallback behavior. Schema-v3 generation packages accept only paths below the
    generation referenced by the root manifest.
    """
    text = str(declared_path or "").strip()
    if not text:
        return None
    manifest_file = Path(manifest_path).resolve()
    recorded = Path(text)
    schema_version = int(manifest.get("schema_version") or 1)
    generation_dir = manifest_generation_dir(manifest_file, manifest)
    candidates: list[Path] = []
    if schema_version >= 3:
        if generation_dir is None or ".." in recorded.parts:
            return None
        if recorded.is_absolute():
            candidates.append(recorded)
            lowered_parts = [part.casefold() for part in recorded.parts]
            try:
                generations_index = lowered_parts.index("generations")
            except ValueError:
                generations_index = -1
            if (
                generations_index >= 0
                and generations_index + 1 < len(recorded.parts)
                and recorded.parts[generations_index + 1].casefold()
                == generation_dir.name.casefold()
            ):
                suffix = recorded.parts[generations_index + 2 :]
                candidates.append(generation_dir.joinpath(*suffix))
        else:
            candidates.append(manifest_file.parent / recorded)
    else:
        candidates.append(recorded)
        if not recorded.is_absolute():
            candidates.append(manifest_file.parent / recorded)
        candidates.append(manifest_file.parent / recorded.name)
        if recorded.parent.name:
            candidates.append(
                manifest_file.parent / recorded.parent.name / recorded.name
            )

    expected_hash = str(expected_sha256 or "").strip().lower()
    seen: set[str] = set()
    for raw_candidate in candidates:
        try:
            candidate = Path(raw_candidate).resolve()
        except OSError:
            continue
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if generation_dir is not None:
            try:
                candidate.relative_to(generation_dir)
            except ValueError:
                continue
        if expect_directory:
            if not candidate.is_dir():
                continue
        elif not candidate.is_file() or candidate.stat().st_size <= 0:
            continue
        if expected_hash and not expect_directory:
            try:
                if not hmac.compare_digest(expected_hash, file_sha256(candidate).lower()):
                    continue
            except OSError:
                continue
        return candidate
    return None


def find_stable_manifest_for_artifact(artifact_path: str | Path) -> Path | None:
    """Find the nearest root manifest for a normal or generation-owned file."""
    path = Path(artifact_path)
    anchor = path if path.is_dir() else path.parent
    for parent in (anchor, *anchor.parents):
        candidate = parent / "stable-final-manifest.json"
        if candidate.is_file():
            return candidate.resolve()
        if len(parent.parts) + 4 < len(anchor.parts):
            break
    return None


def validate_manifest_artifact(
    manifest: dict,
    path_key: str,
    artifact_path: Path,
    *,
    manifest_path: Path | None = None,
) -> bool:
    """Validate a manifest-owned file without weakening schema-v1 compatibility."""
    declared = str((manifest.get("paths") or {}).get(path_key) or "")
    if not declared or not artifact_path.is_file() or artifact_path.stat().st_size <= 0:
        return False
    schema_version = int(manifest.get("schema_version") or 1)
    if schema_version >= 3:
        if manifest_path is None:
            return False
        resolved = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            declared,
            str((manifest.get("paths_sha256") or {}).get(path_key) or ""),
        )
        if resolved is None:
            return False
        try:
            return resolved == artifact_path.resolve()
        except OSError:
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
    if schema_version >= 2 and not expected:
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
