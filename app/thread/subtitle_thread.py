import datetime
import copy
import json
import os
import shutil
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
    build_translation_context_prompt,
    empty_article_context,
    normalize_article_context,
    save_article_artifacts,
)
from app.core.subtitle_processor.split import SubtitleSplitter
from app.core.subtitle_processor.summarization import SubtitleSummarizer
from app.core.subtitle_processor.optimize import SubtitleOptimizer
from app.core.subtitle_processor.stable_ts_alignment import (
    align_subtitle_segments_with_whisperx_time_only,
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

    def __init__(self, task: SubtitleTask):
        super().__init__()
        self.task: SubtitleTask = task
        self.subtitle_length = 0
        self.finished_subtitle_length = 0
        self.custom_prompt_text = ""
        self._stage_timings_seconds: Dict[str, float] = {}
        # 初始化数据库和服务使用管理器
        self.db_manager = DatabaseManager(CACHE_PATH)
        self.service_manager = ServiceUsageManager(self.db_manager)

    def set_custom_prompt_text(self, text: str):
        self.custom_prompt_text = text

    def _record_stage_duration(self, stage: str, started_at: float) -> None:
        self._stage_timings_seconds[stage] = round(max(0.0, time.perf_counter() - started_at), 3)

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

    def _apply_whisperx_time_only_if_enabled(self, asr_data: ASRData) -> ASRData:
        if self._timeline_alignment_backend() != "whisperx-time-only":
            return asr_data
        audio_path = getattr(self.task, "video_path", None) or ""
        if not audio_path or not Path(audio_path).exists():
            logger.warning("WhisperX time-only skipped: source audio is missing: %s", audio_path)
            return asr_data
        try:
            stage_started = time.perf_counter()
            self.progress.emit(92, self.tr("WhisperX最终时间轴对齐..."))
            aligned = align_subtitle_segments_with_whisperx_time_only(
                audio_path,
                asr_data,
                language="en",
                callback=None,
            )
            self._record_stage_duration("whisperx_time_only_alignment", stage_started)
            if not aligned or not aligned.has_data() or len(aligned.segments) != len(asr_data.segments):
                logger.warning("WhisperX time-only did not produce a complete subtitle timeline")
                return asr_data
            for old, new in zip(asr_data.segments, aligned.segments):
                if old.text != new.text or old.translated_text != new.translated_text:
                    logger.warning("WhisperX time-only rejected: subtitle text changed during mapping")
                    return asr_data
            logger.info("WhisperX time-only applied to final subtitle timings")
            return aligned
        except Exception as exc:
            logger.warning("WhisperX time-only failed, keeping original timings: %s", exc)
            return asr_data

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
        source_report_paths = self._source_audio_report_paths(
            qa_review_points_path=str(manifest.get("qa_review_points_srt") or ""),
        )
        source_subtitle_paths = self._write_source_audio_subtitle_exports(asr_data)
        if source_report_paths:
            manifest["source_report_dir"] = str(self._source_audio_report_dir())
            manifest["source_report_paths"] = source_report_paths
        if source_subtitle_paths:
            manifest["source_subtitle_dir"] = str(self._source_audio_report_dir())
            manifest["source_subtitle_paths"] = source_subtitle_paths
        manifest_path = output_dir / "stable-final-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._mirror_stable_reports_to_source_dir(
            qa_review_points_path=str(manifest.get("qa_review_points_srt") or ""),
        )
        logger.info("Stable subtitle manifest saved: %s", manifest_path)

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

    def _source_audio_report_paths(
        self,
        qa_review_points_path: str,
    ) -> dict:
        source_dir = self._source_audio_report_dir()
        if source_dir is None:
            return {}
        paths = {}
        if qa_review_points_path:
            paths["qa_review_points_srt"] = source_dir / "qa-review-points.srt"
        return {key: str(path) for key, path in paths.items()}

    def _mirror_stable_reports_to_source_dir(
        self,
        qa_review_points_path: str,
    ) -> None:
        source_dir = self._source_audio_report_dir()
        if source_dir is None:
            return
        try:
            report_sources = []
            if qa_review_points_path:
                report_sources.append((Path(qa_review_points_path), source_dir / "qa-review-points.srt"))
            for source, destination in report_sources:
                if source.exists() and source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
        except Exception as exc:
            logger.warning("Mirroring subtitle reports to source audio folder failed: %s", exc)

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

            stage_started = time.perf_counter()
            asr_raw = ASRData.from_subtitle_file(subtitle_path)
            asr_data = asr_raw
            word_time_asr_data = None
            article_output_dir = self._article_output_dir()
            self._save_stage_json(article_output_dir, "asr_raw.json", asr_raw)
            self._record_stage_duration("load_subtitle", stage_started)

            stage_started = time.perf_counter()
            article_context = self._resolve_article_context(subtitle_config, article_output_dir)
            self._record_stage_duration("article_context", stage_started)
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
            if (
                str(getattr(self.task, "article_reference_text", "") or "").strip()
                and bool(getattr(self.task, "use_article_reference_assist", False))
            ):
                stage_started = time.perf_counter()
                try:
                    asr_corrected = apply_article_asr_corrections(
                        asr_raw,
                        article_context,
                        output_dir=article_output_dir,
                    )
                    asr_data = asr_corrected
                    self._save_stage_json(article_output_dir, "asr_corrected.json", asr_data)
                    self.update_all.emit(asr_data.to_json())
                except Exception as exc:
                    logger.warning("Article ASR correction failed, using original ASR: %s", exc)
                    self._save_stage_json(article_output_dir, "asr_corrected.json", asr_data)
                self._record_stage_duration("article_asr_correction", stage_started)
            else:
                self._save_stage_json(article_output_dir, "asr_corrected.json", asr_data)

            # 1. 分割成字词级时间戳（对于非断句字幕且开启分割选项）
            stage_started = time.perf_counter()
            if subtitle_config.need_split and not asr_data.is_word_timestamp():
                asr_data.split_to_word_segments()
            if asr_data.is_word_timestamp():
                word_time_asr_data = copy.deepcopy(asr_data)
            self._record_stage_duration("word_timestamp_prepare", stage_started)

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
                stage_started = time.perf_counter()
                self.progress.emit(2, self.tr("开始验证API配置..."))
                subtitle_config = self._setup_api_config()
                os.environ["OPENAI_BASE_URL"] = subtitle_config.base_url
                os.environ["OPENAI_API_KEY"] = subtitle_config.api_key
                self._record_stage_duration("api_setup", stage_started)

            # 2. 重新断句（对于字词级字幕）
            stable_screen_mode = (
                subtitle_config.need_screen_subtitle_edit
                and subtitle_config.screen_subtitle_stable_mode
            )
            if asr_data.is_word_timestamp() and not stable_screen_mode:
                stage_started = time.perf_counter()
                self.progress.emit(5, self.tr("字幕断句..."))
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
                self._record_stage_duration("split_subtitle", stage_started)
            self._save_stage_json(article_output_dir, "segmented_english.json", asr_data)

            # 3. 优化字幕
            custom_prompt = self._compose_prompt(
                subtitle_config.custom_prompt_text,
                article_translation_prompt,
            )
            self.subtitle_length = len(asr_data.segments)

            if subtitle_config.need_optimize:
                stage_started = time.perf_counter()
                self.progress.emit(0, self.tr("优化字幕..."))
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
                self._record_stage_duration("optimize_subtitle", stage_started)

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
                stage_started = time.perf_counter()
                self.progress.emit(0, self.tr("翻译字幕..."))
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
                self._record_stage_duration("translate_subtitle", stage_started)
            self._save_stage_json(article_output_dir, "translated_subtitles.json", asr_data)

            # 5. 上屏短字幕校正
            coverage_report_path = None
            if subtitle_config.need_screen_subtitle_edit:
                stage_started = time.perf_counter()
                self.progress.emit(0, self.tr("上屏短字幕校正..."))
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
                    enable_quality_check=(
                        subtitle_config.need_screen_subtitle_quality_check
                        and not subtitle_config.screen_subtitle_stable_mode
                    ),
                    allocation_max_concurrency=subtitle_config.screen_subtitle_allocation_max_concurrency,
                    allocation_batch_size=subtitle_config.screen_subtitle_allocation_batch_size,
                    article_context_prompt=article_translation_prompt,
                    coverage_report_path=coverage_report_path,
                    update_callback=self.callback,
                )
                asr_data = screen_editor.edit(asr_data, word_time_asr_data=word_time_asr_data)
                self._record_stage_duration("screen_subtitle_edit", stage_started)
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
                asr_data = self._apply_whisperx_time_only_if_enabled(asr_data)
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
            stage_started = time.perf_counter()
            asr_data.save(
                save_path=self.task.output_path,
                ass_style=subtitle_config.subtitle_style,
                layout=subtitle_config.subtitle_layout,
            )
            self._save_stage_json(article_output_dir, "final_subtitles.json", asr_data)
            self._record_stage_duration("final_subtitle_save", stage_started)
            self._save_stable_subtitle_outputs(
                asr_data,
                subtitle_config,
                coverage_report_path=coverage_report_path,
                validation_status="passed",
                manifest_meta=self._screen_manifest_metadata(screen_editor),
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

            self.progress.emit(100, self.tr("优化完成"))
            logger.info("优化完成")
            self.finished.emit(self.task.video_path, self.task.output_path)
        except Exception as e:
            logger.exception(f"优化失败: {str(e)}")
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("优化失败"))

    def callback(self, result: Dict):
        self.finished_subtitle_length += len(result)
        # 简单计算当前进度（0-100%）
        progress = min(
            int((self.finished_subtitle_length / self.subtitle_length) * 100), 100
        )
        self.progress.emit(progress, self.tr("{0}% 处理字幕").format(progress))
        self.update.emit(result)

    def stop(self):
        """停止所有处理"""
        try:
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
            self.progress.emit(100, self.tr("已终止"))

        except Exception as e:
            logger.error(f"停止线程时出错：{str(e)}")
            self.progress.emit(100, self.tr("终止时发生错误"))
