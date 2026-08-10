import datetime
import os
import tempfile
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from app.core.bk_asr import transcribe
from app.core.bk_asr.asr_data import ASRData
from app.core.entities import TranscribeTask, TranscribeModelEnum
from app.core.subtitle_processor.stable_ts_alignment import align_to_word_timestamps
from app.core.utils.logger import setup_logger
from app.core.utils.video_utils import video2audio
from app.core.storage.cache_manager import ServiceUsageManager
from app.core.storage.database import DatabaseManager
from app.config import CACHE_PATH

logger = setup_logger("transcript_thread")


_DOWNLOADED_SUBTITLE_PREFIX = "【下载字幕】"
_SUPPORTED_DOWNLOADED_SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass", ".json"}
_LANGUAGE_ALIASES = {
    "english": "en",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "cantonese": "yue",
}


def _normalize_language_code(language: str) -> str:
    normalized = str(language or "").strip().lower().replace("_", "-")
    normalized = _LANGUAGE_ALIASES.get(normalized, normalized)
    base = normalized.split("-", 1)[0]
    return _LANGUAGE_ALIASES.get(base, base)


def _downloaded_subtitle_language(path: Path) -> str:
    stem = path.stem
    if not stem.startswith(_DOWNLOADED_SUBTITLE_PREFIX):
        return ""
    label = stem[len(_DOWNLOADED_SUBTITLE_PREFIX) :].strip(" ._-")
    if not label:
        return ""
    return _normalize_language_code(label)


def select_downloaded_subtitle(
    subtitle_dir: Path, requested_language: str
) -> Path | None:
    """Return the newest parseable downloaded subtitle for an exact language."""
    language = _normalize_language_code(requested_language)
    if not language or not subtitle_dir.exists():
        return None
    candidates = [
        path
        for path in subtitle_dir.glob(f"{_DOWNLOADED_SUBTITLE_PREFIX}*")
        if path.is_file()
        and path.suffix.lower() in _SUPPORTED_DOWNLOADED_SUBTITLE_SUFFIXES
        and _downloaded_subtitle_language(path) == language
    ]
    candidates.sort(
        key=lambda path: (path.stat().st_mtime_ns, path.name.casefold()),
        reverse=True,
    )
    if not candidates:
        return None

    newest = candidates[0]
    try:
        subtitle_data = ASRData.from_subtitle_file(str(newest))
    except Exception as exc:
        logger.warning("Downloaded subtitle is unreadable: %s (%s)", newest, exc)
        return None
    if not subtitle_data.has_data():
        logger.warning("Downloaded subtitle is empty: %s", newest)
        return None
    return newest


def can_reuse_downloaded_subtitle(*, need_word_time_stamp: bool) -> bool:
    # A downloaded cue timeline has no acoustic word-alignment evidence.
    return not need_word_time_stamp


def _require_valid_asr_data(asr_data: ASRData) -> None:
    if not asr_data or not asr_data.has_data():
        raise RuntimeError("ASR returned empty transcription data")
    for index, segment in enumerate(asr_data.segments):
        if segment.start_time < 0 or segment.end_time <= segment.start_time:
            raise RuntimeError(f"ASR segment {index} has invalid timing")


def _has_trusted_word_timing(asr_data: ASRData) -> bool:
    return bool(
        asr_data
        and getattr(asr_data, "word_timing_trusted", False)
        and asr_data.is_word_timestamp()
    )


def _mark_word_timing(asr_data: ASRData, *, source: str, trusted: bool) -> None:
    asr_data.timing_source = source
    asr_data.word_timing_trusted = bool(trusted)
    for segment in asr_data.segments:
        segment.timing_source = source
        segment.word_timing_trusted = bool(trusted)


def _write_srt_atomically(asr_data: ASRData, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.stem}.",
            suffix=output_path.suffix or ".srt",
            dir=output_path.parent,
            delete=False,
        ) as temp_output:
            temp_path = Path(temp_output.name)
        srt_text = asr_data.to_srt(save_path=str(temp_path))
        if not srt_text.strip():
            raise RuntimeError("ASR produced an empty subtitle file")
        os.replace(temp_path, output_path)
        temp_path = None
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


class TranscriptThread(QThread):
    finished = pyqtSignal(TranscribeTask)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)
    MAX_DAILY_ASR_CALLS = 40

    def __init__(self, task: TranscribeTask):
        super().__init__()
        self.task = task
        # 初始化服务管理器
        db_manager = DatabaseManager(CACHE_PATH)
        self.service_manager = ServiceUsageManager(db_manager)

    def run(self):
        temp_file = None
        try:
            logger.info(f"\n===========转录任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")

            # 检查是否已经存在字幕文件
            # if Path(self.task.output_path).exists():
            #     logger.info("字幕文件已存在，跳过转录")
            #     self.progress.emit(100, self.tr("字幕已存在"))
            #     self.finished.emit(self.task)
            #     return

            # 检查视频文件是否存在
            video_path = Path(self.task.file_path)
            if not video_path.exists():
                logger.error(f"视频文件不存在：{video_path}")
                raise ValueError(self.tr("视频文件不存在"))

            # 对于BIJIAN和JIANYING模型，检查服务使用限制
            if self.task.transcribe_config.transcribe_model in [
                TranscribeModelEnum.BIJIAN,
                TranscribeModelEnum.JIANYING,
            ]:
                if not self.service_manager.check_service_available(
                    "asr", self.MAX_DAILY_ASR_CALLS
                ):
                    raise Exception(
                        self.tr("公益ASR服务已达到每日使用限制，建议使用本地转录")
                    )

            # 检查是否存在下载的字幕文件（对于视频url的任务，前面可能已下载字幕文件）
            if self.task.need_next_task and can_reuse_downloaded_subtitle(
                need_word_time_stamp=self.task.transcribe_config.need_word_time_stamp
            ):
                subtitle_dir = Path(self.task.file_path).parent / "subtitle"
                subtitle_file = select_downloaded_subtitle(
                    subtitle_dir,
                    self.task.transcribe_config.transcribe_language,
                )
                if subtitle_file:
                    self.task.output_path = str(subtitle_file)
                    logger.info(
                        f"字幕文件已下载，跳过转录。找到下载的字幕文件：{subtitle_file}"
                    )
                    self.progress.emit(100, self.tr("字幕已下载"))
                    self.finished.emit(self.task)
                    return
            elif self.task.need_next_task:
                logger.info(
                    "Downloaded subtitle bypass disabled: trusted acoustic word timing is required"
                )

            self.progress.emit(5, self.tr("转换音频中"))
            logger.info(f"开始转换音频")

            # 转换音频文件
            temp_dir = tempfile.gettempdir()
            temp_file = tempfile.NamedTemporaryFile(
                suffix=".wav", dir=temp_dir, delete=False
            )
            temp_file.close()
            is_success = video2audio(str(video_path), output=temp_file.name)
            if not is_success:
                logger.error("音频转换失败")
                raise RuntimeError(self.tr("音频转换失败"))

            self.progress.emit(20, self.tr("语音转录中"))
            logger.info("开始语音转录")

            # 进行转录，并回调进度。 （传入 transcribe_config）
            asr_data = transcribe(
                temp_file.name,
                self.task.transcribe_config,
                callback=self.progress_callback,
            )
            _require_valid_asr_data(asr_data)
            if (
                self.task.need_next_task
                and self.task.transcribe_config.need_word_time_stamp
                and _normalize_language_code(
                    self.task.transcribe_config.transcribe_language
                )
                == "en"
            ):
                if self._should_skip_stable_ts_alignment(asr_data):
                    logger.info(
                        "stable-ts词级时间轴跳过：Qwen3-ASR已使用ForcedAligner生成词级时间轴"
                    )
                else:
                    aligned_data = align_to_word_timestamps(
                        temp_file.name,
                        asr_data,
                        language=self.task.transcribe_config.transcribe_language,
                        callback=self.progress_callback,
                    )
                    if aligned_data and aligned_data.has_data():
                        original_timing_trusted = _has_trusted_word_timing(asr_data)
                        fallback_word_count = int(
                            getattr(aligned_data, "whisperx_fallback_word_count", 0)
                            or 0
                        )
                        alignment_source = (
                            "whisperx"
                            if hasattr(aligned_data, "whisperx_matched_word_count")
                            else "stable-ts"
                        )
                        aligned_timing_trusted = bool(
                            original_timing_trusted or fallback_word_count == 0
                        )
                        _mark_word_timing(
                            aligned_data,
                            source=alignment_source,
                            trusted=aligned_timing_trusted,
                        )
                        _require_valid_asr_data(aligned_data)
                        asr_data = aligned_data
                        logger.info("词级时间轴对齐已应用到转录结果")
                    else:
                        logger.info("词级时间轴对齐未应用，原转录时间轴将接受可信性检查")

            if (
                self.task.need_next_task
                and self.task.transcribe_config.need_word_time_stamp
                and not _has_trusted_word_timing(asr_data)
            ):
                raise RuntimeError(
                    "Trusted acoustic word timing is required for the stable subtitle pipeline"
                )

            # 如果是BIJIAN或JIANYING模型，增加使用次数
            if self.task.transcribe_config.transcribe_model in [
                TranscribeModelEnum.BIJIAN,
                TranscribeModelEnum.JIANYING,
            ]:
                self.service_manager.increment_usage("asr", self.MAX_DAILY_ASR_CALLS)

            # 保存字幕文件
            output_path = Path(self.task.output_path)
            _write_srt_atomically(asr_data, output_path)
            logger.info("字幕文件已保存到: %s", str(output_path))

            self.progress.emit(100, self.tr("转录完成"))
            self.finished.emit(self.task)
        except Exception as e:
            logger.exception("转录过程中发生错误: %s", str(e))
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("转录失败"))
        finally:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")

    def progress_callback(self, value, message):
        progress = min(20 + (value * 0.8), 100)
        self.progress.emit(int(progress), message)

    def _should_skip_stable_ts_alignment(self, asr_data: ASRData) -> bool:
        config = self.task.transcribe_config
        if config.transcribe_model != TranscribeModelEnum.QWEN3_ASR:
            return False
        return bool(
            config.qwen3_aligner_model
            and getattr(asr_data, "timing_source", "") == "qwen3_forced_aligner"
            and _has_trusted_word_timing(asr_data)
        )
