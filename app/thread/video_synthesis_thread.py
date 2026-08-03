import datetime
import json
import logging
import re
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from app.common.config import cfg
from app.core.bk_asr.asr_data import ASRData
from app.core.entities import SynthesisTask
from app.core.subtitle_processor.screen_editor import (
    CHINESE_CPS_ERROR,
    SUBTITLE_DURATION_INVALID_MS,
)
from app.core.utils.logger import setup_logger
from app.core.utils.podcast_learning_video import render_podcast_learning_video
from app.core.utils.video_utils import add_subtitles

logger = setup_logger("video_synthesis_thread")


def _blocked_manifest_reading_speed_is_now_safe(manifest: dict) -> bool:
    """Allow an old manifest only when its sole retired blocker is revalidated.

    This is deliberately narrow: it never clears missing translations, timing,
    English-length, ID, or any other structural validation failure.
    """
    errors = list((manifest.get("validation_summary") or {}).get("errors") or [])
    if not errors or {str(item.get("code") or "") for item in errors} != {
        "reading_speed_error"
    }:
        return False

    stable_path = Path(
        (manifest.get("paths") or {}).get("original_top_srt") or ""
    )
    if not stable_path.exists() or stable_path.stat().st_size <= 0:
        return False

    try:
        subtitle_data = ASRData.from_srt(stable_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        logger.warning("Cannot revalidate blocked stable subtitle: %s", exc)
        return False

    for segment in subtitle_data.segments:
        duration_ms = max(1, int(segment.end_time) - int(segment.start_time))
        if duration_ms < SUBTITLE_DURATION_INVALID_MS:
            continue
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", segment.translated_text or ""))
        if (
            chinese_chars >= 12
            and duration_ms >= 1200
            and chinese_chars / (duration_ms / 1000.0) > CHINESE_CPS_ERROR
        ):
            return False
    return True


def resolve_podcast_template_subtitle(video_file: str, subtitle_file: str) -> str:
    """Prefer bilingual original-on-top SRT for the podcast learning template."""
    subtitle_path = Path(subtitle_file)
    search_dir = subtitle_path.parent
    video_stem = Path(video_file).stem

    manifest_path = search_dir / "stable-final-manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("render_blocked"):
                if _blocked_manifest_reading_speed_is_now_safe(manifest):
                    stable_path = Path(
                        manifest.get("paths", {}).get("original_top_srt", "")
                    )
                    logger.info(
                        "Revalidated legacy reading-speed manifest under current threshold: %s",
                        manifest_path,
                    )
                    return str(stable_path)
                logger.warning("Stable subtitle manifest is blocked by validation: %s", manifest_path)
                raise RuntimeError(
                    "字幕体检未通过，已阻止使用该稳定字幕合成视频。"
                )
            manual_override = manifest.get("manual_final_override") or {}
            manual_path_text = str(manual_override.get("subtitle_path") or "")
            manual_path = Path(manual_path_text) if manual_path_text else None
            if manual_path is not None and manual_path.exists() and manual_path.stat().st_size > 0:
                logger.info(
                    "Resolved podcast subtitle from manual final override: %s", manual_path
                )
                return str(manual_path)
            stable_path = Path(
                manifest.get("paths", {}).get("original_top_srt", "")
            )
            if stable_path.exists() and stable_path.stat().st_size > 0:
                logger.info("Resolved podcast subtitle from stable manifest: %s", stable_path)
                return str(stable_path)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("Stable subtitle manifest ignored: %s", exc)

    candidates = [
        search_dir / "stable-final-original-top.srt",
        search_dir / f"{video_stem}-原文在上.srt",
        search_dir / f"{video_stem}-译文在上.srt",
    ]
    candidates.extend(sorted(search_dir.glob("stable-final-*-top.srt")))
    candidates.extend(sorted(search_dir.glob("*-原文在上.srt")))
    candidates.extend(sorted(search_dir.glob("*-译文在上.srt")))
    if subtitle_path.suffix.lower() == ".srt":
        candidates.append(subtitle_path)

    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            return str(candidate)
    return subtitle_file


class VideoSynthesisThread(QThread):
    finished = pyqtSignal(SynthesisTask)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, task: SynthesisTask):
        super().__init__()
        self.task = task
        logger.debug(f"初始化 VideoSynthesisThread，任务: {self.task}")

    def run(self):
        try:
            logger.info(f"\n===========视频合成任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")
            video_file = self.task.video_path
            subtitle_file = self.task.subtitle_path
            output_path = self.task.output_path
            soft_subtitle = self.task.synthesis_config.soft_subtitle
            need_video = self.task.synthesis_config.need_video
            podcast_learning_template = (
                self.task.synthesis_config.podcast_learning_template
            )
            render_mode = self.task.synthesis_config.subtitle_render_mode
            subtitle_layout = self.task.synthesis_config.subtitle_layout
            rounded_style = self.task.synthesis_config.rounded_style

            if not need_video:
                logger.info(f"不需要合成视频，跳过")
                self.progress.emit(100, self.tr("合成完成"))
                self.finished.emit(self.task)
                return

            logger.info(f"开始合成视频: {video_file}")
            self.progress.emit(5, self.tr("正在合成"))

            if podcast_learning_template:
                subtitle_file = resolve_podcast_template_subtitle(
                    video_file, subtitle_file
                )
                logger.info(f"Podcast learning template subtitle: {subtitle_file}")
                render_podcast_learning_video(
                    video_file,
                    subtitle_file,
                    output_path,
                    template_style=self.task.synthesis_config.podcast_template_style,
                    show_ai_vocab=self.task.synthesis_config.podcast_template_ai_vocab,
                    title_text=self.task.synthesis_config.podcast_template_title,
                    background_path=self.task.synthesis_config.podcast_template_background,
                    cover_path=self.task.synthesis_config.podcast_template_cover,
                    date_text=self.task.synthesis_config.podcast_template_date,
                    progress_callback=self.progress_callback,
                )
                self.progress.emit(100, self.tr("合成完成"))
                logger.info(f"Podcast learning template video saved: {output_path}")
                self.finished.emit(self.task)
                return

            add_subtitles(
                video_file,
                subtitle_file,
                output_path,
                soft_subtitle=soft_subtitle,
                render_mode=render_mode,
                subtitle_layout=subtitle_layout,
                rounded_style=rounded_style,
                progress_callback=self.progress_callback,
            )

            self.progress.emit(100, self.tr("合成完成"))
            logger.info(f"视频合成完成，保存路径: {output_path}")

            self.finished.emit(self.task)
        except Exception as e:
            logger.exception(f"视频合成失败: {e}")
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("视频合成失败"))

    def progress_callback(self, value, message):
        progress = int(5 + int(value) / 100 * 95)
        logger.debug(f"合成进度: {progress}% - {message}")
        self.progress.emit(progress, str(progress) + "% " + message)
