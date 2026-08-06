import datetime
import copy
import json
import os
import time
from pathlib import Path
from typing import Dict

from PyQt5.QtCore import QSettings, QThread, pyqtSignal

from app.common.config import cfg
from app.core.bk_asr.asr_data import ASRData
from app.core.entities import SubtitleConfig, SubtitleTask, TranslatorServiceEnum
from app.core.article_context import (
    ArticleLLMConfig,
    analyze_article_text,
    apply_article_asr_corrections,
    build_article_glossary,
    build_translation_context_prompt,
    clean_article_text,
    empty_article_context,
    normalize_article_context,
    save_article_artifacts,
)
from app.core.subtitle_processor.stable_pipeline_contracts import stable_payload_hash
from app.core.subtitle_processor.stable_run_state import (
    ResumePlan,
    StableRunStateStore,
    build_stable_run_fingerprint,
    format_stage_progress,
)
from app.core.subtitle_processor.split import SubtitleSplitter
from app.core.subtitle_processor.summarization import SubtitleSummarizer
from app.core.subtitle_processor.optimize import SubtitleOptimizer
from app.core.subtitle_processor.stable_ts_alignment import (
    align_frozen_word_ledger_with_whisperx,
)
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.subtitle_processor.translate import TranslatorFactory, TranslatorType
from app.core.utils.logger import setup_logger
from app.core.utils.test_opanai import test_openai
from app.core.storage.cache_manager import ServiceUsageManager
from app.core.storage.database import DatabaseManager
from app.config import CACHE_PATH

# 配置日志
logger = setup_logger("subtitle_optimization_thread")


class SubtitleThread(QThread):
    finished = pyqtSignal(str, str)
    progress = pyqtSignal(int, str)
    update = pyqtSignal(dict)
    update_all = pyqtSignal(dict)
    error = pyqtSignal(str)
    MAX_DAILY_LLM_CALLS = 30
    _STAGE_PROGRESS_RANGES = {
        "load_subtitle": (0, 4),
        "article_context": (4, 10),
        "article_asr_correction": (10, 16),
        "word_timestamp_prepare": (16, 22),
        "api_setup": (22, 28),
        "split_subtitle": (28, 36),
        "optimize_subtitle": (36, 50),
        "translate_subtitle": (50, 64),
        "screen_subtitle_edit": (28, 92),
        "whisperx_time_only_alignment": (92, 96),
        "final_subtitle_save": (96, 100),
    }

    def __init__(self, task: SubtitleTask):
        super().__init__()
        self.task: SubtitleTask = task
        self.subtitle_length = 0
        self.finished_subtitle_length = 0
        self.custom_prompt_text = ""
        self._stage_timings_seconds: Dict[str, float] = {}
        self._article_run_metadata: Dict = self._empty_article_run_metadata()
        self._run_state_store: StableRunStateStore | None = None
        self._resume_plan = ResumePlan(False, "missing", (), "not_initialized")
        self._resume_stage_records: Dict[str, Dict] = {}
        self._active_stage = ""
        self._active_stage_started_at = 0.0
        self._screen_editor_phase_started_at: Dict[str, float] = {}
        self._last_progress_value = 0
        # 初始化数据库和服务使用管理器
        self.db_manager = DatabaseManager(CACHE_PATH)
        self.service_manager = ServiceUsageManager(self.db_manager)

    def set_custom_prompt_text(self, text: str):
        self.custom_prompt_text = text

    @staticmethod
    def _should_run_legacy_subtitle_optimization(
        *,
        need_optimize: bool,
        stable_screen_mode: bool,
    ) -> bool:
        """Keep LLM English rewriting out of the stable word-ledger path."""
        return bool(need_optimize and not stable_screen_mode)

    def _record_stage_duration(self, stage: str, started_at: float) -> None:
        self._stage_timings_seconds[stage] = round(max(0.0, time.perf_counter() - started_at), 3)

    def _initialize_run_state(
        self,
        subtitle_config: SubtitleConfig,
        output_dir: Path,
    ) -> None:
        """Create one durable run record before subtitle data is transformed."""
        store = StableRunStateStore(output_dir)
        fingerprint = build_stable_run_fingerprint(
            subtitle_path=self.task.subtitle_path,
            subtitle_config=subtitle_config,
            article_reference_text=str(getattr(self.task, "article_reference_text", "") or ""),
            article_context_data=getattr(self.task, "article_context_data", None),
            use_article_reference_assist=bool(
                getattr(self.task, "use_article_reference_assist", False)
            ),
            use_article_translation_terms=bool(
                getattr(self.task, "use_article_translation_terms", False)
            ),
            alignment_backend=self._timeline_alignment_backend(),
            custom_prompt_text=self.custom_prompt_text,
        )
        prior = store.load() or {}
        self._resume_plan = store.plan_resume(fingerprint)
        self._resume_stage_records = dict(prior.get("stages") or {})
        self._run_state_store = store
        store.start(fingerprint, self._resume_plan)
        logger.info(
            "Stable run state initialized: resume=%s prior_status=%s stages=%s reason=%s",
            self._resume_plan.compatible,
            self._resume_plan.previous_status,
            list(self._resume_plan.reusable_stages),
            self._resume_plan.reason,
        )

    def _begin_stage(
        self,
        stage: str,
        label: str,
        *,
        details: Dict | None = None,
    ) -> float:
        self._active_stage = stage
        self._active_stage_started_at = time.perf_counter()
        if stage == "screen_subtitle_edit":
            self._screen_editor_phase_started_at = {}
        if self._run_state_store is not None:
            self._run_state_store.begin_stage(stage, details=details)
        self._emit_stage_progress(stage, label, details=details)
        return self._active_stage_started_at

    def _complete_stage(
        self,
        stage: str,
        label: str,
        started_at: float,
        *,
        artifact_paths: tuple[Path, ...] = (),
        details: Dict | None = None,
    ) -> None:
        elapsed = max(0.0, time.perf_counter() - started_at)
        self._stage_timings_seconds[stage] = round(elapsed, 3)
        if self._run_state_store is not None:
            self._run_state_store.complete_stage(
                stage,
                elapsed_seconds=elapsed,
                artifact_paths=artifact_paths,
                details=details,
            )
        self._emit_stage_progress(stage, label, fraction=1.0, details=details)

    def _fail_active_stage(self, error: str, *, cancelled: bool = False) -> None:
        if self._run_state_store is None or not self._active_stage:
            return
        self._run_state_store.fail_stage(self._active_stage, error, cancelled=cancelled)

    def _emit_stage_progress(
        self,
        stage: str,
        label: str,
        *,
        fraction: float | None = None,
        completed: int | None = None,
        total: int | None = None,
        cache_hits: int = 0,
        retries: int = 0,
        details: Dict | None = None,
        elapsed_started_at: float | None = None,
    ) -> None:
        # Several focused tests exercise a single timing helper through
        # ``SubtitleThread.__new__`` without constructing its QThread base.
        # Their fake signal still receives the same two-argument event.
        instance_state = self.__dict__
        try:
            progress_signal = self.progress
        except RuntimeError:
            return
        if "_last_progress_value" not in instance_state:
            instance_state["_last_progress_value"] = 0
            instance_state.setdefault("_active_stage", "")
            instance_state.setdefault("_active_stage_started_at", 0.0)
        start, end = self._STAGE_PROGRESS_RANGES.get(stage, (0, 100))
        if fraction is None:
            fraction = (completed / total) if total else 0.0
        fraction = max(0.0, min(1.0, float(fraction)))
        value = max(instance_state["_last_progress_value"], int(round(start + (end - start) * fraction)))
        self._last_progress_value = min(100, value)
        progress_started_at = elapsed_started_at or instance_state["_active_stage_started_at"]
        elapsed = (
            max(0.0, time.perf_counter() - progress_started_at)
            if instance_state["_active_stage"] == stage and progress_started_at
            else 0.0
        )
        eta_seconds = None
        if completed is not None and total and completed > 0:
            eta_seconds = max(0.0, elapsed * max(0, total - completed) / completed)
        message = format_stage_progress(
            label,
            completed=completed,
            total=total,
            cache_hits=cache_hits,
            retries=retries,
            elapsed_seconds=elapsed,
            eta_seconds=eta_seconds,
        )
        progress_details = {
            "completed": completed,
            "total": total,
            "cache_hits": cache_hits,
            "retries": retries,
            **(details or {}),
        }
        run_state_store = instance_state.get("_run_state_store")
        if run_state_store is not None:
            run_state_store.update_stage(stage, details=progress_details)
            run_state_store.update_progress(
                percent=self._last_progress_value,
                stage=stage,
                message=message,
                details=progress_details,
            )
        progress_signal.emit(self._last_progress_value, self.tr(message))

    def _resume_stage_details(self, stage: str) -> Dict:
        record = self._resume_stage_records.get(stage) or {}
        return dict(record.get("details") or {}) if isinstance(record, dict) else {}

    def _load_resume_article_context(self, output_dir: Path) -> Dict | None:
        if not self._resume_plan.can_reuse("article_context"):
            return None
        try:
            payload = json.loads((output_dir / "article_context.json").read_text(encoding="utf-8"))
            return normalize_article_context(payload)
        except Exception as exc:
            logger.warning("Resume article context unavailable; recomputing: %s", exc)
            return None

    def _load_resume_asr_correction(self, output_dir: Path) -> ASRData | None:
        if not self._resume_plan.can_reuse("article_asr_correction"):
            return None
        try:
            payload = json.loads((output_dir / "asr_corrected.json").read_text(encoding="utf-8"))
            return ASRData.from_json(payload)
        except Exception as exc:
            logger.warning("Resume ASR correction unavailable; recalculating: %s", exc)
            return None

    def _handle_screen_editor_progress(self, event: Dict) -> None:
        """Translate editor events into the existing two-argument GUI signal."""
        if not isinstance(event, dict):
            return
        phase = str(event.get("phase") or "")
        phase_timers = self.__dict__.setdefault("_screen_editor_phase_started_at", {})
        phase_started_at = phase_timers.setdefault(phase, time.perf_counter()) if phase else None
        completed = event.get("completed")
        total = event.get("total")
        cache_hits = int(event.get("cache_hits") or 0)
        retries = int(event.get("retries") or 0)
        if phase == "english_boundaries":
            fraction = 0.08 * (float(completed or 0) / max(1, int(total or 1)))
            label = "英文边界冻结"
        elif phase == "full_translation":
            fraction = 0.08 + 0.34 * (float(completed or 0) / max(1, int(total or 1)))
            label = "完整中文翻译"
        elif phase == "allocation":
            fraction = 0.42 + 0.46 * (float(completed or 0) / max(1, int(total or 1)))
            label = "中文分配"
        elif phase == "allocation_retry":
            fraction = 0.88
            label = "中文分配复核"
        else:
            fraction = 0.90 if phase == "finalization" else 0.0
            label = "上屏短字幕校正"
        self._emit_stage_progress(
            "screen_subtitle_edit",
            label,
            fraction=fraction,
            completed=int(completed) if completed is not None else None,
            total=int(total) if total is not None else None,
            cache_hits=cache_hits,
            retries=retries,
            details={"phase": phase, **{key: value for key, value in event.items() if key != "phase"}},
            elapsed_started_at=phase_started_at,
        )

    @staticmethod
    def _empty_article_run_metadata() -> Dict:
        return {
            "schema_version": 1,
            "reference_text_present": False,
            "reference_text_hash": "",
            "normalized_context_hash": "",
            "glossary_hash": "",
            "use_article_reference_assist": False,
            "use_article_translation_terms": False,
            "article_reference_enabled": False,
            "correction_requested": False,
            "correction_ran": False,
            "correction_applied": False,
            "translation_terms_applied": False,
        }

    def _set_article_run_metadata(
        self,
        article_context: Dict,
        *,
        correction_ran: bool = False,
        correction_applied: bool = False,
        translation_terms_applied: bool = False,
    ) -> None:
        """Persist actual task state, never infer it from stale output files."""
        article_text = clean_article_text(
            str(getattr(self.task, "article_reference_text", "") or "")
        )
        normalized_context = normalize_article_context(article_context)
        context_payload = {
            key: value
            for key, value in normalized_context.items()
            if not key.startswith("_")
        }
        glossary = build_article_glossary(normalized_context)
        use_assist = bool(getattr(self.task, "use_article_reference_assist", False))
        use_terms = bool(getattr(self.task, "use_article_translation_terms", False))
        self._article_run_metadata = {
            "schema_version": 1,
            "reference_text_present": bool(article_text),
            "reference_text_hash": stable_payload_hash(article_text) if article_text else "",
            "normalized_context_hash": stable_payload_hash(context_payload),
            "glossary_hash": stable_payload_hash(glossary),
            "use_article_reference_assist": use_assist,
            "use_article_translation_terms": use_terms,
            "article_reference_enabled": bool(article_text) and (use_assist or use_terms),
            "correction_requested": bool(article_text) and use_assist,
            "correction_ran": bool(correction_ran),
            "correction_applied": bool(correction_applied),
            "translation_terms_applied": bool(translation_terms_applied),
        }

    def _screen_manifest_metadata(self, screen_editor: ScreenSubtitleEditor) -> dict:
        metadata = screen_editor.manifest_metadata()
        try:
            from app.common.config import cfg

            metadata["timeline_alignment_backend"] = os.getenv(
                "VIDEOCAPTIONER_ALIGNMENT_BACKEND",
                str(cfg.timeline_alignment_backend.value or "stable-ts"),
            )
        except Exception:
            metadata["timeline_alignment_backend"] = os.getenv(
                "VIDEOCAPTIONER_ALIGNMENT_BACKEND", "stable-ts"
            )
        metadata["stage_timings_seconds"] = dict(self._stage_timings_seconds)
        metadata["stage_timings_total_seconds"] = round(sum(self._stage_timings_seconds.values()), 3)
        metadata["run_comparison"] = {
            "schema_version": 1,
            "article_reference": dict(
                getattr(self, "_article_run_metadata", self._empty_article_run_metadata())
            ),
            "translation_runtime_config": {
                "translation_model": str(getattr(screen_editor, "model", "") or ""),
                "prompt_version": str(metadata.get("prompt_version", "") or ""),
                "target_language": str(getattr(screen_editor, "target_language", "") or ""),
                "max_cjk_chars": int(getattr(screen_editor, "max_cjk_chars", 0) or 0),
                "max_english_words": int(getattr(screen_editor, "max_english_words", 0) or 0),
                "allocation_batch_size": int(
                    getattr(screen_editor, "allocation_batch_size", 0) or 0
                ),
                "allocation_max_concurrency": int(
                    getattr(screen_editor, "allocation_max_concurrency", 0) or 0
                ),
                "chinese_polish_enabled": bool(
                    getattr(screen_editor, "enable_chinese_polish", False)
                ),
            },
        }
        return metadata

    @staticmethod
    def _timeline_alignment_backend() -> str:
        try:
            return os.getenv(
                "VIDEOCAPTIONER_ALIGNMENT_BACKEND",
                str(cfg.timeline_alignment_backend.value or "stable-ts"),
            ).strip().lower()
        except Exception:
            return os.getenv("VIDEOCAPTIONER_ALIGNMENT_BACKEND", "stable-ts").strip().lower()

    def _apply_whisperx_time_only_if_enabled(
        self,
        asr_data: ASRData,
        *,
        alignment_source: ASRData,
        word_ledger: ASRData,
        screen_editor: ScreenSubtitleEditor,
    ) -> ASRData:
        if self._timeline_alignment_backend() != "whisperx-time-only":
            return asr_data

        def cue_text_by_id(data: ASRData) -> Dict[str, tuple[str, str]]:
            return {
                str(getattr(segment, "subtitle_id", "") or ""): (
                    segment.text,
                    segment.translated_text,
                )
                for segment in data.segments
            }

        def use_stable_ledger_fallback(reason: str) -> ASRData:
            logger.warning(
                "WhisperX time-only unavailable; rebuilding final cues from stable word ledger: %s",
                reason,
            )
            self._emit_stage_progress(
                "whisperx_time_only_alignment",
                "WhisperX不可用，使用稳定词级时间轴",
                fraction=0.5,
                details={"fallback_reason": reason},
            )
            screen_editor.record_final_timeline_alignment(
                requested_backend="whisperx-time-only",
                applied_backend="stable-ts-fallback",
                fallback_reason=reason,
            )
            rebuilt = screen_editor.rebuild_final_cue_timeline(
                asr_data,
                word_ledger,
                alignment_backend="stable-ts-fallback",
            )
            if cue_text_by_id(asr_data) != cue_text_by_id(rebuilt):
                raise RuntimeError(
                    self.tr("最终时间轴降级失败：稳定词账本重建改变了字幕文本。")
                )
            return rebuilt

        # ``video_path`` historically served both as the report-output anchor
        # and alignment input.  Prefer the explicit source path so isolated
        # E2E runs can keep all writes out of the original audio directory.
        audio_path = (
            getattr(self.task, "source_audio_path", None)
            or getattr(self.task, "video_path", None)
            or ""
        )
        if not audio_path or not Path(audio_path).exists():
            return use_stable_ledger_fallback("source_audio_missing")
        try:
            stage_started = time.perf_counter()
            self._emit_stage_progress(
                "whisperx_time_only_alignment",
                "WhisperX最终时间轴对齐",
                fraction=0.2,
            )
            aligned_word_ledger = align_frozen_word_ledger_with_whisperx(
                audio_path,
                alignment_source,
                word_ledger,
                language="en",
                callback=None,
            )
            self._record_stage_duration("whisperx_time_only_alignment", stage_started)
            if (
                not aligned_word_ledger
                or not aligned_word_ledger.has_data()
                or len(aligned_word_ledger.segments) != len(word_ledger.segments)
            ):
                return use_stable_ledger_fallback("incomplete_frozen_word_ledger")
            screen_editor.record_final_timeline_alignment(
                requested_backend="whisperx-time-only",
                applied_backend="whisperx-time-only",
                local_timing_fallbacks=list(
                    getattr(aligned_word_ledger, "whisperx_monotonicity_fallbacks", []) or []
                ),
            )
            rebuilt = screen_editor.rebuild_final_cue_timeline(
                asr_data,
                aligned_word_ledger,
                alignment_backend="whisperx-time-only",
            )
            if cue_text_by_id(asr_data) != cue_text_by_id(rebuilt):
                logger.warning("WhisperX time-only rejected: final cue text changed during ledger rebuild")
                return use_stable_ledger_fallback("cue_text_changed_during_rebuild")
            logger.info("WhisperX time-only rebuilt final cue timings from the frozen word ledger")
            return rebuilt
        except Exception as exc:
            logger.warning("WhisperX time-only failed: %s", exc)
            return use_stable_ledger_fallback(f"alignment_exception:{type(exc).__name__}")

    @staticmethod
    def _subtitle_layout_names() -> Dict[str, str]:
        return {
            "original_top": "\u539f\u6587\u5728\u4e0a",
            "translation_top": "\u8bd1\u6587\u5728\u4e0a",
            "only_original": "\u4ec5\u539f\u6587",
            "only_translation": "\u4ec5\u8bd1\u6587",
        }

    def _article_reference_enabled(self) -> bool:
        article_text = str(getattr(self.task, "article_reference_text", "") or "").strip()
        return bool(article_text) and (
            bool(getattr(self.task, "use_article_reference_assist", False))
            or bool(getattr(self.task, "use_article_translation_terms", False))
        )

    def _article_output_dir(self) -> Path:
        output_path = getattr(self.task, "output_path", None) or getattr(
            self.task, "subtitle_path", ""
        )
        return Path(output_path).parent if output_path else Path(CACHE_PATH)

    @staticmethod
    def _compose_prompt(base_prompt: str, extra_prompt: str) -> str:
        parts = [part.strip() for part in (base_prompt, extra_prompt) if part and part.strip()]
        return "\n\n".join(parts)

    def _article_llm_config(self, subtitle_config: SubtitleConfig) -> ArticleLLMConfig | None:
        if not (
            subtitle_config.base_url
            and subtitle_config.api_key
            and subtitle_config.llm_model
        ):
            return None
        return ArticleLLMConfig(
            base_url=subtitle_config.base_url,
            api_key=subtitle_config.api_key,
            model=subtitle_config.llm_model,
        )

    @staticmethod
    def _has_article_context(context: Dict) -> bool:
        normalized = normalize_article_context(context)
        if normalized.get("title") or normalized.get("summary"):
            return True
        for key in (
            "people",
            "companies",
            "brands",
            "organisations",
            "places",
            "technical_terms",
            "numbers_and_dates",
        ):
            if normalized.get(key):
                return True
        return False

    def _resolve_article_context(
        self, subtitle_config: SubtitleConfig, output_dir: Path
    ) -> Dict:
        if not self._article_reference_enabled():
            return empty_article_context()

        article_text = str(getattr(self.task, "article_reference_text", "") or "").strip()
        context = normalize_article_context(
            getattr(self.task, "article_context_data", None)
        )
        if not self._has_article_context(context):
            llm_config = self._article_llm_config(subtitle_config)
            if llm_config is not None:
                try:
                    context = analyze_article_text(
                        article_text,
                        llm_config,
                        timeout=60,
                    )
                except Exception as exc:
                    logger.warning("Article context analysis failed, fallback to empty context: %s", exc)
                    context = empty_article_context()

        try:
            save_article_artifacts(output_dir, article_text, context)
        except Exception as exc:
            logger.warning("Saving article artifacts failed: %s", exc)
        return context

    @staticmethod
    def _save_stage_json(output_dir: Path, name: str, asr_data: ASRData) -> None:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / name).write_text(
                json.dumps(asr_data.to_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Saving %s failed: %s", name, exc)

    @staticmethod
    def _srt_timestamp(ms: int) -> str:
        ms = max(0, int(ms))
        hours = ms // 3_600_000
        minutes = (ms % 3_600_000) // 60_000
        seconds = (ms % 60_000) // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    @classmethod
    def _write_stable_srt(cls, asr_data: ASRData, save_path: Path, mode: str) -> None:
        lines = []
        for index, segment in enumerate(asr_data.segments, 1):
            original = (segment.text or "").strip()
            translated = (segment.translated_text or "").strip()
            if mode == "original_top":
                body = [original] + ([translated] if translated else [])
            elif mode == "translation_top":
                body = ([translated] if translated else []) + [original]
            elif mode == "only_original":
                body = [original]
            elif mode == "only_translation":
                body = [translated or original]
            else:
                body = [original] + ([translated] if translated else [])
            lines.append(str(index))
            lines.append(
                f"{cls._srt_timestamp(segment.start_time)} --> "
                f"{cls._srt_timestamp(segment.end_time)}"
            )
            lines.extend(line for line in body if line)
            lines.append("")
        save_path.write_text("\n".join(lines), encoding="utf-8-sig")

    def _save_stable_subtitle_outputs(
        self,
        asr_data: ASRData,
        subtitle_config: SubtitleConfig,
        coverage_report_path: str | None = None,
        validation_status: str = "passed",
        validation_summary: dict | None = None,
        manifest_meta: dict | None = None,
    ) -> None:
        """Write deterministic subtitle outputs used by video synthesis.

        These files are intentionally ASCII-named so the synthesis step can
        resolve the newest stable subtitle without relying on localized names.
        """
        if not subtitle_config.need_screen_subtitle_edit:
            return

        output_path = Path(self.task.output_path)
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        stable_paths = {
            "original_top_srt": output_dir / "stable-final-original-top.srt",
            "translation_top_srt": output_dir / "stable-final-translation-top.srt",
            "only_original_srt": output_dir / "stable-final-only-original.srt",
            "only_translation_srt": output_dir / "stable-final-only-translation.srt",
        }
        self._write_stable_srt(asr_data, stable_paths["original_top_srt"], "original_top")
        self._write_stable_srt(
            asr_data, stable_paths["translation_top_srt"], "translation_top"
        )
        self._write_stable_srt(
            asr_data, stable_paths["only_original_srt"], "only_original"
        )
        self._write_stable_srt(
            asr_data, stable_paths["only_translation_srt"], "only_translation"
        )

        if validation_summary and validation_summary.get("status") == "ERROR":
            validation_status = "failed"
        render_blocked = validation_status == "failed"
        if not render_blocked:
            if output_path.suffix.lower() == ".ass":
                asr_data.to_ass(
                    save_path=str(output_path),
                    style_str=subtitle_config.subtitle_style,
                    layout=subtitle_config.subtitle_layout,
                )
            elif output_path.suffix.lower() == ".srt":
                asr_data.to_srt(
                    save_path=str(output_path),
                    layout=subtitle_config.subtitle_layout,
                )

        manifest = {
            "schema_version": 1,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "source_subtitle": self.task.subtitle_path,
            "output_path": str(output_path),
            "coverage_report": coverage_report_path,
            "validation_status": validation_status,
            "render_blocked": render_blocked,
            "validation_error_codes": [
                str(issue.get("code"))
                for issue in (validation_summary or {}).get("errors", [])
                if issue.get("code")
            ],
            "validation_summary": validation_summary or {},
            "layout": subtitle_config.subtitle_layout,
            "stable_mode": subtitle_config.screen_subtitle_stable_mode,
            "subtitle_count": len(asr_data.segments),
            "paths": {key: str(path) for key, path in stable_paths.items()},
        }
        if manifest_meta:
            manifest.update(manifest_meta)
        source_subtitle_paths = self._write_source_audio_subtitle_exports(asr_data)
        if source_subtitle_paths:
            manifest["source_subtitle_dir"] = str(self._source_audio_report_dir())
            manifest["source_subtitle_paths"] = source_subtitle_paths
        qa_review_paths = self._write_source_audio_qc_queue(coverage_report_path)
        if qa_review_paths:
            manifest["qa_review_queue"] = qa_review_paths
        summary_paths = self._write_stable_result_summary(manifest)
        if summary_paths:
            manifest["result_summary_paths"] = summary_paths
        manifest_path = output_dir / "stable-final-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Stable subtitle manifest saved: %s", manifest_path)

    def _write_source_audio_qc_queue(self, coverage_report_path: str | None) -> dict:
        """Create one concise, time-addressable review SRT beside the source audio."""
        source_dir = self._source_audio_report_dir()
        if source_dir is None or not coverage_report_path:
            return {}
        report_path = Path(coverage_report_path)
        artifact_dir = report_path.with_name(
            f"{report_path.stem.removesuffix('-coverage-report')}-artifacts"
        )
        if not artifact_dir.exists():
            return {}
        try:
            from scripts.build_qa_summary import write_qa_review_artifacts

            result = write_qa_review_artifacts(
                artifact_dir,
                source_audio_dir=source_dir,
            )
            logger.info(
                "Source audio QA review queue saved: %s",
                result.get("source_audio_qa_review_queue_srt", ""),
            )
            return result
        except Exception as exc:
            logger.warning("Saving source audio QA review queue failed: %s", exc)
            return {}

    def _write_stable_result_summary(self, manifest: dict) -> dict:
        summary = self._build_stable_result_summary(manifest)
        if not summary:
            return {}
        source_dir = self._source_audio_report_dir()
        if source_dir is None:
            return {}
        paths = {"source_summary_txt": str(source_dir / "字幕处理结果摘要.txt")}
        for path_text in paths.values():
            try:
                Path(path_text).write_text(summary, encoding="utf-8-sig")
            except Exception as exc:
                logger.warning("Writing stable result summary failed: %s", exc)
        return paths

    def _build_stable_result_summary(self, manifest: dict) -> str:
        validation = manifest.get("validation_summary") or {}
        errors = list(validation.get("errors") or [])
        warnings = list(validation.get("warnings") or [])
        info = list(validation.get("info") or [])
        polish_log = list(manifest.get("chinese_polish_log") or [])
        applied_polish = [item for item in polish_log if item.get("decision") == "applied"]
        rejected_polish = [
            item for item in polish_log
            if item.get("decision") in {"rejected", "skipped", "batch_skipped"}
        ]

        status = str(manifest.get("validation_status") or "unknown")
        blocked = bool(manifest.get("render_blocked"))
        if blocked:
            conclusion = "失败：存在硬错误，已阻止后续合成。"
        elif errors:
            conclusion = "异常：报告存在 ERROR，需要人工确认。"
        elif warnings:
            conclusion = "可用：没有硬错误，但仍有需要抽查的问题。"
        else:
            conclusion = "通过：未发现需要阻断的问题。"

        lines = [
            "字幕处理结果摘要",
            "",
            f"结论：{conclusion}",
            f"生成时间：{manifest.get('created_at', '')}",
            f"字幕数量：{manifest.get('subtitle_count', 0)}",
            f"稳定模式：{'开' if manifest.get('stable_mode') else '关'}",
            f"中文字幕润色：{'开' if manifest.get('chinese_polish_enabled') else '关'}",
            f"状态：{status}",
            f"是否阻止合成：{'是' if blocked else '否'}",
            "",
            "问题统计：",
            f"- ERROR：{len(errors)}",
            f"- WARNING：{len(warnings)}",
            f"- INFO：{len(info)}",
            f"- 润色成功：{len(applied_polish)}",
            f"- 润色跳过/拒绝：{len(rejected_polish)}",
        ]

        if errors:
            lines.extend(["", "需要优先处理的 ERROR："])
            lines.extend(self._summary_issue_lines(errors, limit=8))

        if warnings:
            lines.extend(["", "主要 WARNING："])
            lines.extend(self._summary_issue_lines(warnings, limit=8))

        if applied_polish:
            lines.extend(["", "本次中文润色："])
            for item in applied_polish[:12]:
                lines.append(
                    f"- {item.get('semantic_group_id', '')}：{', '.join(item.get('subtitle_ids') or [])}"
                )

        if rejected_polish:
            lines.extend(["", "已跳过或拒绝的中文润色："])
            for item in rejected_polish[:12]:
                lines.append(
                    f"- {item.get('semantic_group_id', '')}：{item.get('reason', '')}"
                )

        paths = manifest.get("paths") or {}
        source_paths = manifest.get("source_subtitle_paths") or {}
        lines.extend(["", "输出文件："])
        if paths.get("original_top_srt"):
            lines.append(f"- 工作目录双语字幕：{paths.get('original_top_srt')}")
        if source_paths.get("bilingual_original_top_srt"):
            lines.append(f"- 音频目录双语字幕：{source_paths.get('bilingual_original_top_srt')}")
        if source_paths.get("only_translation_srt"):
            lines.append(f"- 音频目录中文字幕：{source_paths.get('only_translation_srt')}")
        if source_paths.get("only_original_srt"):
            lines.append(f"- 音频目录英文字幕：{source_paths.get('only_original_srt')}")
        if manifest.get("coverage_report"):
            lines.append(f"- 详细报告：{manifest.get('coverage_report')}")
        qa_review_queue = manifest.get("qa_review_queue") or {}
        if qa_review_queue.get("source_audio_qa_review_queue_srt"):
            lines.append(
                f"- 剪映质检队列：{qa_review_queue.get('source_audio_qa_review_queue_srt')}"
            )

        if blocked or errors:
            recommendation = "建议：先处理 ERROR，不建议直接合成。"
        elif applied_polish:
            recommendation = "建议：可以导入视频抽查已润色语义组和 WARNING 位置。"
        elif warnings:
            recommendation = "建议：可以合成，但优先抽查 WARNING 中的英文切分和阅读速度。"
        else:
            recommendation = "建议：可以直接合成或导入剪辑软件。"
        lines.extend(["", recommendation, ""])
        return "\n".join(lines)

    @staticmethod
    def _summary_issue_lines(issues: list, limit: int) -> list:
        lines = []
        for issue in issues[:limit]:
            code = issue.get("code", "")
            message = str(issue.get("message") or "").strip()
            item_count = len(issue.get("items") or []) if isinstance(issue.get("items"), list) else 0
            suffix = f"（{item_count}项）" if item_count else ""
            lines.append(f"- {code}：{message}{suffix}")
        return lines

    @staticmethod
    def _summary_time_range(item: dict) -> str:
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or "").strip()
        if start and end:
            return f"{start} --> {end}"
        return ""

    @staticmethod
    def _unique_summary_repairs(items: list) -> list:
        unique = []
        seen = set()
        for item in items:
            key = (
                item.get("subtitle_id"),
                item.get("before_chinese"),
                item.get("after_chinese"),
                item.get("before_start_ms"),
                item.get("before_end_ms"),
                item.get("after_start_ms"),
                item.get("after_end_ms"),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _source_audio_subtitle_paths(self) -> dict:
        source_dir = self._source_audio_report_dir()
        if source_dir is None:
            return {}
        return {
            "bilingual_original_top_srt": str(source_dir / "双语字幕.srt"),
            "only_translation_srt": str(source_dir / "中文字幕.srt"),
            "only_original_srt": str(source_dir / "英文字幕.srt"),
        }

    def _write_source_audio_subtitle_exports(self, asr_data: ASRData) -> dict:
        paths = self._source_audio_subtitle_paths()
        if not paths:
            return {}
        try:
            self._write_stable_srt(
                asr_data,
                Path(paths["bilingual_original_top_srt"]),
                "original_top",
            )
            self._write_stable_srt(
                asr_data,
                Path(paths["only_translation_srt"]),
                "only_translation",
            )
            self._write_stable_srt(
                asr_data,
                Path(paths["only_original_srt"]),
                "only_original",
            )
            logger.info("Source audio subtitle exports saved: %s", paths)
        except Exception as exc:
            logger.warning("Saving source audio subtitle exports failed: %s", exc)
            return {}
        return paths

    def _source_audio_report_dir(self) -> Path | None:
        source_path = getattr(self.task, "video_path", None) or ""
        if not source_path:
            return None
        source_dir = Path(source_path).parent
        if not source_dir.exists():
            return None
        return source_dir

    def _setup_api_config(self) -> SubtitleConfig:
        """设置API配置，返回SubtitleConfig"""
        public_base_url = "https://ddg.bkfeng.top/v1"
        if self.task.subtitle_config.base_url == public_base_url:
            # 检查是否可以使用服务

            if not self.service_manager.check_service_available(
                "llm", self.MAX_DAILY_LLM_CALLS
            ):
                raise Exception(
                    self.tr(
                        f"公益LLM服务已达到每日使用限制 {self.MAX_DAILY_LLM_CALLS} 次，建议使用自己的API"
                    )
                )
            self.task.subtitle_config.thread_num = 5
            self.task.subtitle_config.batch_size = 10
            return self.task.subtitle_config

        if self.task.subtitle_config.base_url and self.task.subtitle_config.api_key:
            if not test_openai(
                self.task.subtitle_config.base_url,
                self.task.subtitle_config.api_key,
                self.task.subtitle_config.llm_model,
            )[0]:
                raise Exception(
                    self.tr(
                        "（字幕断句或字幕修正需要大模型）\nOpenAI API 测试失败, 请检查LLM配置"
                    )
                )
            # 增加服务使用次数
            if self.task.subtitle_config.base_url == public_base_url:
                self.service_manager.increment_usage("llm", self.MAX_DAILY_LLM_CALLS)
            return self.task.subtitle_config
        else:
            raise Exception(
                self.tr(
                    "（字幕断句或字幕修正需要大模型）\nOpenAI API 未配置, 请检查LLM配置"
                )
            )

    def run(self):
        try:
            logger.info(f"\n===========字幕处理任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")

            # 字幕文件路径检查、对断句字幕路径进行定义
            subtitle_path = self.task.subtitle_path
            output_name = (
                Path(subtitle_path)
                .stem.replace("【原始字幕】", "")
                .replace("【下载字幕】", "")
            )
            split_path = str(
                Path(subtitle_path).parent / f"【断句字幕】{output_name}.srt"
            )
            assert subtitle_path is not None, self.tr("字幕文件路径为空")

            subtitle_config = self.task.subtitle_config
            article_output_dir = self._article_output_dir()
            self._initialize_run_state(subtitle_config, article_output_dir)

            stage_started = self._begin_stage("load_subtitle", "加载原始字幕")
            asr_raw = ASRData.from_subtitle_file(subtitle_path)
            asr_data = asr_raw
            word_time_asr_data = None
            self._save_stage_json(article_output_dir, "asr_raw.json", asr_raw)
            self._complete_stage(
                "load_subtitle",
                "加载原始字幕",
                stage_started,
                artifact_paths=(article_output_dir / "asr_raw.json",),
                details={"subtitle_count": len(asr_raw.segments)},
            )

            stage_started = self._begin_stage("article_context", "分析参考原文")
            article_context = self._load_resume_article_context(article_output_dir)
            article_context_resumed = article_context is not None
            if article_context is None:
                article_context = self._resolve_article_context(subtitle_config, article_output_dir)
            self._complete_stage(
                "article_context",
                "分析参考原文",
                stage_started,
                artifact_paths=(article_output_dir / "article_context.json",),
                details={"resumed": article_context_resumed},
            )
            article_translation_prompt = ""
            if (
                str(getattr(self.task, "article_reference_text", "") or "").strip()
                and bool(getattr(self.task, "use_article_translation_terms", False))
            ):
                try:
                    article_translation_prompt = build_translation_context_prompt(article_context)
                except Exception as exc:
                    logger.warning("Building article translation prompt failed: %s", exc)
                    article_translation_prompt = ""
            article_correction_ran = False
            article_correction_applied = False
            if (
                str(getattr(self.task, "article_reference_text", "") or "").strip()
                and bool(getattr(self.task, "use_article_reference_assist", False))
            ):
                stage_started = self._begin_stage("article_asr_correction", "参考原文实体校正")
                try:
                    asr_corrected = self._load_resume_asr_correction(article_output_dir)
                    article_correction_resumed = asr_corrected is not None
                    if asr_corrected is None:
                        asr_corrected = apply_article_asr_corrections(
                            asr_raw,
                            article_context,
                            output_dir=article_output_dir,
                        )
                    asr_data = asr_corrected
                    prior_correction_details = self._resume_stage_details(
                        "article_asr_correction"
                    )
                    article_correction_ran = bool(
                        prior_correction_details.get("correction_ran", True)
                    )
                    article_correction_applied = [
                        segment.text for segment in asr_raw.segments
                    ] != [segment.text for segment in asr_corrected.segments]
                    self._save_stage_json(article_output_dir, "asr_corrected.json", asr_data)
                    self.update_all.emit(asr_data.to_json())
                except Exception as exc:
                    logger.warning("Article ASR correction failed, using original ASR: %s", exc)
                    article_correction_resumed = False
                    self._save_stage_json(article_output_dir, "asr_corrected.json", asr_data)
                self._complete_stage(
                    "article_asr_correction",
                    "参考原文实体校正",
                    stage_started,
                    artifact_paths=(article_output_dir / "asr_corrected.json",),
                    details={
                        "resumed": article_correction_resumed,
                        "correction_ran": article_correction_ran,
                        "correction_applied": article_correction_applied,
                    },
                )
            else:
                stage_started = self._begin_stage("article_asr_correction", "跳过参考原文实体校正")
                self._save_stage_json(article_output_dir, "asr_corrected.json", asr_data)
                self._complete_stage(
                    "article_asr_correction",
                    "跳过参考原文实体校正",
                    stage_started,
                    artifact_paths=(article_output_dir / "asr_corrected.json",),
                    details={"skipped": True, "correction_ran": False, "correction_applied": False},
                )
            self._set_article_run_metadata(
                article_context,
                correction_ran=article_correction_ran,
                correction_applied=article_correction_applied,
                translation_terms_applied=bool(article_translation_prompt),
            )

            # WhisperX time-only aligns these natural ASR phrases, then maps
            # word times back to the frozen ledger.  Do not use final cue text
            # as alignment input after English boundaries are frozen.
            alignment_source_asr_data = copy.deepcopy(asr_data)

            # 1. 稳定模式必须先建立词级账本；不能再依赖旧的“字幕分割”开关。
            stage_started = self._begin_stage("word_timestamp_prepare", "准备词级时间轴")
            stable_screen_mode = bool(
                subtitle_config.need_screen_subtitle_edit
                and subtitle_config.screen_subtitle_stable_mode
            )
            if (subtitle_config.need_split or stable_screen_mode) and not asr_data.is_word_timestamp():
                asr_data.split_to_word_segments()
            if asr_data.is_word_timestamp():
                word_time_asr_data = copy.deepcopy(asr_data)
            elif stable_screen_mode:
                raise RuntimeError(
                    "上屏稳定模式需要词级时间戳，但当前转录结果无法建立词级账本。"
                    "请切换支持词级时间戳的转录模型，或关闭上屏稳定模式。"
                )
            self._complete_stage(
                "word_timestamp_prepare",
                "准备词级时间轴",
                stage_started,
                details={"word_timestamp_count": len(word_time_asr_data.segments) if word_time_asr_data else 0},
            )

            # 获取API配置，会先检查可用性（优先使用设置的API，其次使用自带的公益API）
            if (
                subtitle_config.need_optimize
                or subtitle_config.need_screen_subtitle_edit
                or asr_data.is_word_timestamp()
                or (
                    (
                        subtitle_config.need_translate
                        and subtitle_config.translator_service
                        not in [
                            TranslatorServiceEnum.DEEPLX,
                            TranslatorServiceEnum.BING,
                            TranslatorServiceEnum.GOOGLE,
                        ]
                    )
                )
            ):
                stage_started = self._begin_stage("api_setup", "验证翻译服务")
                subtitle_config = self._setup_api_config()
                os.environ["OPENAI_BASE_URL"] = subtitle_config.base_url
                os.environ["OPENAI_API_KEY"] = subtitle_config.api_key
                self._complete_stage("api_setup", "验证翻译服务", stage_started)

            # 2. 重新断句（对于字词级字幕）
            if asr_data.is_word_timestamp() and not stable_screen_mode:
                stage_started = self._begin_stage("split_subtitle", "英文语义粗切")
                logger.info("正在字幕断句...")
                screen_edit_mode = subtitle_config.need_screen_subtitle_edit
                coarse_english_limit = max(
                    subtitle_config.max_word_count_english,
                    subtitle_config.screen_subtitle_max_english * 2,
                    28,
                )
                splitter = SubtitleSplitter(
                    thread_num=subtitle_config.thread_num,
                    model=subtitle_config.llm_model,
                    temperature=0.3,
                    timeout=60,
                    retry_times=1,
                    split_type=subtitle_config.split_type,
                    max_word_count_cjk=subtitle_config.max_word_count_cjk,
                    max_word_count_english=(
                        coarse_english_limit
                        if screen_edit_mode
                        else subtitle_config.max_word_count_english
                    ),
                    screen_mode=False,
                )
                if screen_edit_mode:
                    logger.info(
                        "上屏短字幕模式：字幕分割仅做语义粗切，英文粗切上限=%s，最终上屏长度由上屏校正控制",
                        coarse_english_limit,
                    )
                asr_data = splitter.split_subtitle(asr_data)
                asr_data.save(save_path=split_path)
                self.update_all.emit(asr_data.to_json())
                self._complete_stage(
                    "split_subtitle",
                    "英文语义粗切",
                    stage_started,
                    artifact_paths=(Path(split_path),),
                    details={"subtitle_count": len(asr_data.segments)},
                )
            self._save_stage_json(article_output_dir, "segmented_english.json", asr_data)

            # 3. 优化字幕
            custom_prompt = self._compose_prompt(
                subtitle_config.custom_prompt_text,
                article_translation_prompt,
            )
            self.subtitle_length = len(asr_data.segments)

            if self._should_run_legacy_subtitle_optimization(
                need_optimize=subtitle_config.need_optimize,
                stable_screen_mode=stable_screen_mode,
            ):
                stage_started = self._begin_stage("optimize_subtitle", "优化字幕")
                logger.info("正在优化字幕...")
                self.finished_subtitle_length = 0  # 重置计数器
                optimizer = SubtitleOptimizer(
                    custom_prompt=custom_prompt,
                    model=subtitle_config.llm_model,
                    batch_num=subtitle_config.batch_size,
                    thread_num=subtitle_config.thread_num,
                    update_callback=self.callback,
                )
                asr_data = optimizer.optimize_subtitle(asr_data)
                self.update_all.emit(asr_data.to_json())
                self._complete_stage("optimize_subtitle", "优化字幕", stage_started)
            elif subtitle_config.need_optimize:
                logger.info("稳定上屏模式跳过旧 LLM 英文优化；最终边界由本地词级规则决定")

            # 4. 翻译字幕
            translator_map = {
                TranslatorServiceEnum.OPENAI: TranslatorType.OPENAI,
                TranslatorServiceEnum.DEEPLX: TranslatorType.DEEPLX,
                TranslatorServiceEnum.BING: TranslatorType.BING,
                TranslatorServiceEnum.GOOGLE: TranslatorType.GOOGLE,
            }
            should_translate_before_screen_edit = (
                subtitle_config.need_translate
                and not subtitle_config.need_screen_subtitle_edit
            )
            if subtitle_config.need_translate and subtitle_config.need_screen_subtitle_edit:
                logger.info(
                    "跳过普通翻译：上屏短字幕校正将基于语义粗切字幕直接完成翻译和细切"
            )
            if should_translate_before_screen_edit:
                stage_started = self._begin_stage("translate_subtitle", "翻译字幕")
                logger.info("正在翻译字幕...")
                self.finished_subtitle_length = 0  # 重置计数器
                os.environ["DEEPLX_ENDPOINT"] = subtitle_config.deeplx_endpoint
                translator = TranslatorFactory.create_translator(
                    translator_type=translator_map[subtitle_config.translator_service],
                    thread_num=subtitle_config.thread_num,
                    batch_num=subtitle_config.batch_size,
                    target_language=subtitle_config.target_language,
                    model=subtitle_config.llm_model,
                    custom_prompt=custom_prompt,
                    is_reflect=subtitle_config.need_reflect,
                    update_callback=self.callback,
                )
                asr_data = translator.translate_subtitle(asr_data)
                # 移除末尾标点符号
                if (
                    subtitle_config.need_remove_punctuation
                    and not subtitle_config.need_screen_subtitle_edit
                ):
                    asr_data.remove_punctuation()
                self.update_all.emit(asr_data.to_json())
                self._complete_stage("translate_subtitle", "翻译字幕", stage_started)
            self._save_stage_json(article_output_dir, "translated_subtitles.json", asr_data)

            # 5. 上屏短字幕校正
            coverage_report_path = None
            if subtitle_config.need_screen_subtitle_edit:
                stage_started = self._begin_stage("screen_subtitle_edit", "上屏短字幕校正")
                if any(seg.translated_text for seg in asr_data.segments):
                    logger.info("正在进行上屏短字幕校正...")
                else:
                    logger.info("正在进行上屏短字幕翻译与校正...")
                self.subtitle_length = len(asr_data.segments)
                self.finished_subtitle_length = 0
                coverage_report_path = str(
                    Path(self.task.output_path).with_name(
                        f"{Path(self.task.output_path).stem}-coverage-report.txt"
                    )
                )
                screen_editor = ScreenSubtitleEditor(
                    model=subtitle_config.llm_model,
                    target_language=subtitle_config.target_language,
                    batch_num=max(20, subtitle_config.batch_size),
                    thread_num=min(4, max(1, subtitle_config.thread_num)),
                    max_cjk_chars=subtitle_config.screen_subtitle_max_cjk,
                    max_english_words=subtitle_config.screen_subtitle_max_english,
                    enable_stable_mode=subtitle_config.screen_subtitle_stable_mode,
                    enable_chinese_polish=subtitle_config.screen_subtitle_chinese_polish,
                    preserve_aligned_timing=(
                        self._timeline_alignment_backend()
                        in {"whisperx", "whisperx-time-only"}
                    ),
                    allocation_max_concurrency=subtitle_config.screen_subtitle_allocation_max_concurrency,
                    allocation_batch_size=subtitle_config.screen_subtitle_allocation_batch_size,
                    article_context_prompt=article_translation_prompt,
                    coverage_report_path=coverage_report_path,
                    update_callback=self.callback,
                    progress_callback=self._handle_screen_editor_progress,
                )
                asr_data = screen_editor.edit(asr_data, word_time_asr_data=word_time_asr_data)
                if screen_editor.has_blocking_validation_errors():
                    message = screen_editor.blocking_validation_message()
                    self._save_stable_subtitle_outputs(
                        asr_data,
                        subtitle_config,
                        coverage_report_path=coverage_report_path,
                        validation_status="failed",
                        validation_summary=screen_editor.last_validation_summary,
                        manifest_meta=self._screen_manifest_metadata(screen_editor),
                    )
                    raise RuntimeError(
                        self.tr(
                            "字幕体检发现严重问题，已停止后续合成。\n报告路径："
                        )
                        + coverage_report_path
                        + "\n"
                        + message
                    )
                frozen_word_ledger = screen_editor.export_frozen_word_ledger()
                if not frozen_word_ledger.has_data():
                    raise RuntimeError(self.tr("最终时间轴构建失败：缺少冻结词级账本。"))
                try:
                    timeline_stage_started = self._begin_stage(
                        "whisperx_time_only_alignment",
                        "最终词级时间轴对齐",
                    )
                    asr_data = self._apply_whisperx_time_only_if_enabled(
                        asr_data,
                        alignment_source=alignment_source_asr_data,
                        word_ledger=frozen_word_ledger,
                        screen_editor=screen_editor,
                    )
                    self._complete_stage(
                        "whisperx_time_only_alignment",
                        "最终词级时间轴对齐",
                        timeline_stage_started,
                    )
                    # The alignment backend has finished.  Any remaining
                    # validation belongs to the still-running screen stage.
                    self._active_stage = "screen_subtitle_edit"
                    self._active_stage_started_at = stage_started
                except RuntimeError as exc:
                    validation_summary = {
                        "status": "ERROR",
                        "errors": [
                            {
                                "code": "whisperx_time_mapping_incomplete",
                                "message": str(exc),
                            }
                        ],
                        "warnings": [],
                        "info": [],
                    }
                    self._save_stable_subtitle_outputs(
                        asr_data,
                        subtitle_config,
                        coverage_report_path=coverage_report_path,
                        validation_status="failed",
                        validation_summary=validation_summary,
                        manifest_meta=self._screen_manifest_metadata(screen_editor),
                    )
                    raise
                if self._timeline_alignment_backend() != "whisperx-time-only":
                    asr_data = screen_editor.rebuild_final_cue_timeline(
                        asr_data,
                        frozen_word_ledger,
                        alignment_backend=self._timeline_alignment_backend(),
                    )
                asr_data = screen_editor.repair_after_final_time_alignment(
                    asr_data,
                    # Every backend now reaches the same frozen-ledger final
                    # timeline.  Later passes may alter Chinese only; they
                    # must not write a second cue timing authority.
                    preserve_aligned_timing=True,
                )
                try:
                    page_stage_started = self._begin_stage(
                        "display_page_translation",
                        "双语分页语义分配",
                    )
                    asr_data = screen_editor.apply_display_page_translations_after_final_timing(
                        asr_data
                    )
                    self._complete_stage(
                        "display_page_translation",
                        "双语分页语义分配",
                        page_stage_started,
                    )
                    self._active_stage = "screen_subtitle_edit"
                    self._active_stage_started_at = stage_started
                except RuntimeError as exc:
                    validation_summary = {
                        "status": "ERROR",
                        "errors": [
                            {
                                "code": "display_page_translation_invalid",
                                "message": str(exc),
                            }
                        ],
                        "warnings": [],
                        "info": [],
                    }
                    self._save_stable_subtitle_outputs(
                        asr_data,
                        subtitle_config,
                        coverage_report_path=coverage_report_path,
                        validation_status="failed",
                        validation_summary=validation_summary,
                        manifest_meta=self._screen_manifest_metadata(screen_editor),
                    )
                    raise
                final_duration_errors = screen_editor._subtitle_duration_issues(
                    asr_data.segments,
                    "ERROR",
                )
                if final_duration_errors:
                    validation_summary = {
                        "errors": [
                            {
                                "code": "subtitle_duration_invalid",
                                "message": self.tr("最终时间轴存在严重短字幕。"),
                                "items": final_duration_errors,
                            }
                        ],
                        "warnings": [],
                        "info": [],
                    }
                    self._save_stable_subtitle_outputs(
                        asr_data,
                        subtitle_config,
                        coverage_report_path=coverage_report_path,
                        validation_status="failed",
                        validation_summary=validation_summary,
                        manifest_meta=self._screen_manifest_metadata(screen_editor),
                    )
                    raise RuntimeError(
                        self.tr("最终时间轴存在严重短字幕，已停止后续合成。")
                    )
                if (
                    screen_editor.last_validation_summary
                    and screen_editor.last_validation_summary.get("status") == "ERROR"
                ):
                    self._save_stable_subtitle_outputs(
                        asr_data,
                        subtitle_config,
                        coverage_report_path=coverage_report_path,
                        validation_status="failed",
                        validation_summary=screen_editor.last_validation_summary,
                        manifest_meta=self._screen_manifest_metadata(screen_editor),
                    )
                    raise RuntimeError(
                        self.tr("字幕体检发现 ERROR，已停止后续合成。报告路径：")
                        + coverage_report_path
                    )
                self._complete_stage(
                    "screen_subtitle_edit",
                    "上屏短字幕校正",
                    stage_started,
                    details={"subtitle_count": len(asr_data.segments)},
                )
                self.update_all.emit(asr_data.to_json())
                self._save_stage_json(article_output_dir, "translated_subtitles.json", asr_data)

            # 保存翻译结果(单语、双语)
            if (
                (subtitle_config.need_translate or subtitle_config.need_screen_subtitle_edit)
                and self.task.need_next_task
                and self.task.video_path
            ):
                for subtitle_layout in ["原文在上", "译文在上", "仅原文", "仅译文"]:
                    save_path = str(
                        Path(self.task.subtitle_path).parent
                        / f"{Path(self.task.video_path).stem}-{subtitle_layout}.srt"
                    )
                    asr_data.save(
                        save_path=save_path,
                        ass_style=subtitle_config.subtitle_style,
                        layout=subtitle_layout,
                    )
                    logger.info(f"字幕保存到 {save_path}")

            # 6. 保存字幕
            stage_started = self._begin_stage("final_subtitle_save", "写入稳定终稿")
            asr_data.save(
                save_path=self.task.output_path,
                ass_style=subtitle_config.subtitle_style,
                layout=subtitle_config.subtitle_layout,
            )
            self._save_stage_json(article_output_dir, "final_subtitles.json", asr_data)
            self._save_stable_subtitle_outputs(
                asr_data,
                subtitle_config,
                coverage_report_path=coverage_report_path,
                validation_status="passed",
                validation_summary=(
                    screen_editor.last_validation_summary
                    if subtitle_config.need_screen_subtitle_edit
                    else None
                ),
                manifest_meta=self._screen_manifest_metadata(screen_editor),
            )
            self._complete_stage(
                "final_subtitle_save",
                "写入稳定终稿",
                stage_started,
                artifact_paths=(
                    article_output_dir / "final_subtitles.json",
                    article_output_dir / "stable-final-manifest.json",
                ),
                details={"subtitle_count": len(asr_data.segments)},
            )
            logger.info(f"字幕保存到 {self.task.output_path}")

            # 7. 文件移动与清理
            if self.task.need_next_task and self.task.video_path:
                # 保存srt/ass文件到视频目录（对于全流程任务）
                save_srt_path = (
                    Path(self.task.video_path).parent
                    / f"{Path(self.task.video_path).stem}.srt"
                )
                asr_data.to_srt(
                    save_path=str(save_srt_path), layout=subtitle_config.subtitle_layout
                )
                # save_ass_path = (
                #     Path(self.task.video_path).parent
                #     / f"{Path(self.task.video_path).stem}.ass"
                # )
                # asr_data.to_ass(
                #     save_path=str(save_ass_path),
                #     layout=subtitle_config.subtitle_layout,
                #     style_str=subtitle_config.subtitle_style,
                # )
            else:
                # 删除断句文件（对于仅字幕任务）
                split_path = str(
                    Path(self.task.subtitle_path).parent
                    / f"【智能断句】{Path(self.task.subtitle_path).stem}.srt"
                )
                if os.path.exists(split_path):
                    os.remove(split_path)

            if self._run_state_store is not None:
                self._run_state_store.complete_run()
            self._last_progress_value = 100
            self.progress.emit(100, self.tr("优化完成"))
            logger.info("优化完成")
            self.finished.emit(self.task.video_path, self.task.output_path)
        except Exception as e:
            logger.exception(f"优化失败: {str(e)}")
            self._fail_active_stage(str(e))
            self.error.emit(str(e))
            self.progress.emit(self._last_progress_value, self.tr("优化失败"))

    def callback(self, result: Dict):
        self.finished_subtitle_length += len(result)
        stage = self._active_stage or "translate_subtitle"
        labels = {
            "optimize_subtitle": "优化字幕",
            "translate_subtitle": "翻译字幕",
            "screen_subtitle_edit": "上屏短字幕校正",
        }
        self._emit_stage_progress(
            stage,
            labels.get(stage, "处理字幕"),
            completed=min(self.finished_subtitle_length, max(1, self.subtitle_length)),
            total=max(1, self.subtitle_length),
        )
        self.update.emit(result)

    def stop(self):
        """停止所有处理"""
        try:
            self._fail_active_stage("user_cancelled", cancelled=True)
            # 先停止优化器
            if hasattr(self, "optimizer"):
                try:
                    self.optimizer.stop()
                except Exception as e:
                    logger.error(f"停止优化器时出错：{str(e)}")

            # 终止线程
            self.terminate()
            # 等待最多3秒
            if not self.wait(3000):
                logger.warning("线程未能在3秒内正常停止")

            # 发送进度信号
            self.progress.emit(self._last_progress_value, self.tr("已终止"))

        except Exception as e:
            logger.error(f"停止线程时出错：{str(e)}")
            self.progress.emit(self._last_progress_value, self.tr("终止时发生错误"))
