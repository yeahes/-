"""Durable state and progress contracts for stable subtitle processing.

This module deliberately owns no subtitle transformation.  It records which
inputs produced a stage artifact and exposes a narrow resume planner that only
reuses artifacts whose input contract and file digest still match.  That keeps
progress/resume features from becoming a second writer of English, IDs, or
timings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence
from uuid import uuid4

from app.core.subtitle_processor.stable_pipeline_contracts import stable_payload_hash


RUN_STATE_SCHEMA_VERSION = 1
RUN_STATE_FILE_NAME = "run-state.json"

# These stages produce self-contained inputs that can be reloaded without
# re-creating frozen English boundaries or final timing state.
SAFE_RESUMABLE_STAGES = (
    "article_context",
    "article_asr_correction",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_value(value: Any) -> Any:
    """Return a stable, secret-free representation of a config value."""
    if hasattr(value, "value"):
        return _config_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_stable_run_fingerprint(
    *,
    subtitle_path: str | Path,
    subtitle_config: Any,
    article_reference_text: str = "",
    article_context_data: Optional[Mapping[str, Any]] = None,
    use_article_reference_assist: bool = False,
    use_article_translation_terms: bool = False,
    alignment_backend: str = "stable-ts",
    custom_prompt_text: str = "",
) -> Dict[str, Any]:
    """Build the explicit input contract used by the resume planner.

    API keys are intentionally excluded.  A model, prompt, article state,
    allocation setting, or alignment backend change invalidates reuse.
    """
    source = Path(subtitle_path)
    if not source.exists():
        raise FileNotFoundError(f"Subtitle input does not exist: {source}")
    config_keys = (
        "llm_model",
        "translator_service",
        "need_translate",
        "need_optimize",
        "need_reflect",
        "thread_num",
        "batch_size",
        "split_type",
        "subtitle_layout",
        "max_word_count_cjk",
        "max_word_count_english",
        "need_split",
        "target_language",
        "need_remove_punctuation",
        "need_screen_subtitle_edit",
        "screen_subtitle_stable_mode",
        "screen_subtitle_chinese_polish",
        "screen_subtitle_max_cjk",
        "screen_subtitle_max_english",
        "screen_subtitle_allocation_max_concurrency",
        "screen_subtitle_allocation_batch_size",
        "custom_prompt_text",
    )
    config_payload = {
        key: _config_value(getattr(subtitle_config, key, None))
        for key in config_keys
    }
    article_payload = dict(article_context_data or {})
    return {
        "schema_version": RUN_STATE_SCHEMA_VERSION,
        "input_subtitle_path": str(source.resolve()),
        "input_subtitle_sha256": _file_sha256(source),
        "article_reference_sha256": stable_payload_hash((article_reference_text or "").strip()),
        "article_context_input_sha256": stable_payload_hash(article_payload),
        "use_article_reference_assist": bool(use_article_reference_assist),
        "use_article_translation_terms": bool(use_article_translation_terms),
        "timeline_alignment_backend": str(alignment_backend or "stable-ts").strip().lower(),
        "subtitle_config": config_payload,
        "custom_prompt_sha256": stable_payload_hash((custom_prompt_text or "").strip()),
    }


@dataclass(frozen=True)
class ResumePlan:
    compatible: bool
    previous_status: str
    reusable_stages: tuple[str, ...]
    reason: str = ""

    def can_reuse(self, stage: str) -> bool:
        return self.compatible and stage in self.reusable_stages


def format_elapsed(seconds: float | int | None) -> str:
    total = max(0, int(round(float(seconds or 0))))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_stage_progress(
    label: str,
    *,
    completed: Optional[int] = None,
    total: Optional[int] = None,
    cache_hits: int = 0,
    retries: int = 0,
    elapsed_seconds: float = 0.0,
    eta_seconds: Optional[float] = None,
    detail: str = "",
) -> str:
    """Build the status-label text without coupling progress to a GUI class."""
    parts = [label]
    if completed is not None and total:
        parts.append(f"第 {completed}/{total} 批")
    if cache_hits:
        parts.append(f"缓存命中 {cache_hits}")
    if retries:
        parts.append(f"重试 {retries}")
    parts.append(f"已用时 {format_elapsed(elapsed_seconds)}")
    if eta_seconds is not None and eta_seconds >= 0:
        parts.append(f"预计剩余 {format_elapsed(eta_seconds)}")
    if detail:
        parts.append(detail)
    return "，".join(parts)


class StableRunStateStore:
    """Atomic JSON state store for one subtitle output directory."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.path = self.output_dir / RUN_STATE_FILE_NAME
        self.state: Dict[str, Any] = {}

    def load(self) -> Optional[Dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(payload, dict) or payload.get("schema_version") != RUN_STATE_SCHEMA_VERSION:
            return None
        return payload

    @staticmethod
    def _artifact_record(path: Path) -> Dict[str, Any]:
        return {
            "path": str(path),
            "sha256": _file_sha256(path),
            "size": path.stat().st_size,
        }

    @staticmethod
    def _artifacts_valid(artifacts: Mapping[str, Any]) -> bool:
        if not artifacts:
            return False
        for artifact in artifacts.values():
            if not isinstance(artifact, Mapping):
                return False
            path = Path(str(artifact.get("path") or ""))
            expected_hash = str(artifact.get("sha256") or "")
            if not path.is_file() or not expected_hash:
                return False
            try:
                if _file_sha256(path) != expected_hash:
                    return False
            except OSError:
                return False
        return True

    def plan_resume(self, fingerprint: Mapping[str, Any]) -> ResumePlan:
        prior = self.load()
        if prior is None:
            return ResumePlan(False, "missing", (), "no_prior_state")
        if prior.get("fingerprint") != dict(fingerprint):
            return ResumePlan(False, str(prior.get("status") or "unknown"), (), "input_contract_changed")
        prior_status = str(prior.get("status") or "unknown")
        if prior_status == "completed":
            return ResumePlan(False, prior_status, (), "prior_run_completed")
        stages = prior.get("stages") if isinstance(prior.get("stages"), Mapping) else {}
        reusable = []
        for stage in SAFE_RESUMABLE_STAGES:
            record = stages.get(stage)
            if not isinstance(record, Mapping) or record.get("status") != "completed":
                continue
            artifacts = record.get("artifacts")
            if isinstance(artifacts, Mapping) and self._artifacts_valid(artifacts):
                reusable.append(stage)
        return ResumePlan(True, prior_status, tuple(reusable), "compatible_interrupted_run")

    def start(self, fingerprint: Mapping[str, Any], plan: ResumePlan) -> Dict[str, Any]:
        self.state = {
            "schema_version": RUN_STATE_SCHEMA_VERSION,
            "run_id": uuid4().hex,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "status": "running",
            "fingerprint": dict(fingerprint),
            "resume": {
                "compatible": plan.compatible,
                "previous_status": plan.previous_status,
                "reusable_stages": list(plan.reusable_stages),
                "reason": plan.reason,
            },
            "progress": {"percent": 0, "stage": "", "message": "", "details": {}},
            "stages": {},
        }
        self._write()
        return self.state

    def begin_stage(self, stage: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        self._stage(stage).update(
            {
                "status": "running",
                "started_at": _utc_now(),
                "completed_at": "",
                "elapsed_seconds": 0.0,
                "error": "",
            }
        )
        if details:
            self._stage(stage).setdefault("details", {}).update(dict(details))
        self._write()

    def update_stage(self, stage: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        record = self._stage(stage)
        if details:
            record.setdefault("details", {}).update(dict(details))
        self._write()

    def complete_stage(
        self,
        stage: str,
        *,
        elapsed_seconds: float,
        artifact_paths: Iterable[str | Path] = (),
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        record = self._stage(stage)
        artifacts = {}
        for artifact_path in artifact_paths:
            path = Path(artifact_path)
            if path.is_file():
                artifacts[path.name] = self._artifact_record(path)
        record.update(
            {
                "status": "completed",
                "completed_at": _utc_now(),
                "elapsed_seconds": round(max(0.0, float(elapsed_seconds)), 3),
                "error": "",
                "artifacts": artifacts,
            }
        )
        if details:
            record.setdefault("details", {}).update(dict(details))
        self._write()

    def fail_stage(self, stage: str, error: str, *, cancelled: bool = False) -> None:
        record = self._stage(stage)
        record.update(
            {
                "status": "cancelled" if cancelled else "failed",
                "completed_at": _utc_now(),
                "error": str(error),
            }
        )
        self.state["status"] = "cancelled" if cancelled else "failed"
        self._write()

    def complete_run(self) -> None:
        self.state["status"] = "completed"
        self._write()

    def update_progress(
        self,
        *,
        percent: int,
        stage: str,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        prior = int((self.state.get("progress") or {}).get("percent") or 0)
        self.state["progress"] = {
            "percent": max(prior, min(100, int(percent))),
            "stage": stage,
            "message": message,
            "details": dict(details or {}),
        }
        self._write()

    def _stage(self, stage: str) -> Dict[str, Any]:
        return self.state.setdefault("stages", {}).setdefault(stage, {"details": {}})

    def _write(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state["updated_at"] = _utc_now()
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
