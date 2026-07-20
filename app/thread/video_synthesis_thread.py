import datetime
import logging
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from app.common.config import cfg
from app.core.entities import SynthesisTask
from app.core.utils.logger import setup_logger
from app.core.utils.podcast_learning_video import render_podcast_learning_video
from app.core.utils.video_utils import add_subtitles

logger = setup_logger("video_synthesis_thread")


def resolve_podcast_template_subtitle(video_file: str, subtitle_file: str) -> str:
    """Prefer bilingual original-on-top SRT for the podcast learning template."""
    subtitle_path = Path(subtitle_file)
    search_dir = subtitle_path.parent
    video_stem = Path(video_file).stem

    candidates = [
        search_dir / f"{video_stem}-原文在上.srt",
        search_dir / f"{video_stem}-译文在上.srt",
    ]
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
                    progress_callback=self.progress_callback,
                )
                self.progress.emit(100, self.tr("鍚堟垚瀹屾垚"))
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
