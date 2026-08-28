import json
import logging
import math
import os
import tempfile
import threading
import zlib
from typing import Optional, Union

from app.config import CACHE_PATH
from app.core.storage.cache_manager import CacheManager

from .asr_data import ASRData, ASRDataSeg


logger = logging.getLogger(__name__)


class BaseASR:
    SUPPORTED_SOUND_FORMAT = ["flac", "m4a", "mp3", "wav"]
    _lock = threading.Lock()

    def __init__(
        self,
        audio_path: Optional[Union[str, bytes]] = None,
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
    ):
        self.audio_path = audio_path
        self.file_binary = None
        self.use_cache = use_cache
        self.need_word_time_stamp = need_word_time_stamp
        self._set_data()
        self.cache_manager = CacheManager(str(CACHE_PATH))

    def _set_data(self):
        if isinstance(self.audio_path, bytes):
            self.file_binary = self.audio_path
        else:
            ext = self.audio_path.split(".")[-1].lower()
            assert (
                ext in self.SUPPORTED_SOUND_FORMAT
            ), f"Unsupported sound format: {ext}"
            assert os.path.exists(self.audio_path), f"File not found: {self.audio_path}"
            with open(self.audio_path, "rb") as f:
                self.file_binary = f.read()
        crc32_value = zlib.crc32(self.file_binary) & 0xFFFFFFFF
        self.crc32_hex = format(crc32_value, "08x")

    def run(self, callback=None, **kwargs) -> ASRData:
        if self.use_cache:
            cached_result = self.cache_manager.get_asr_result(
                self._get_key(), self.__class__.__name__
            )
            if cached_result:
                try:
                    return self._make_validated_data(cached_result)
                except Exception as exc:
                    logger.warning(
                        "Ignoring invalid %s ASR cache entry: %s",
                        self.__class__.__name__,
                        exc,
                    )

        resp_data = self._run(callback, **kwargs)
        asr_data = self._make_validated_data(resp_data)

        if self.use_cache:
            self.cache_manager.set_asr_result(
                self._get_key(), self.__class__.__name__, resp_data
            )

        return asr_data

    def _make_validated_data(self, resp_data) -> ASRData:
        segments = self._make_segments(resp_data)
        asr_data = ASRData(segments)
        if not asr_data.has_data():
            raise RuntimeError("ASR returned empty transcription data")

        for index, segment in enumerate(asr_data.segments):
            try:
                start = float(segment.start_time)
                end = float(segment.end_time)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"ASR segment {index} has invalid timing values"
                ) from exc
            if not math.isfinite(start) or not math.isfinite(end):
                raise RuntimeError(f"ASR segment {index} has non-finite timing")
            if start < 0 or end <= start:
                raise RuntimeError(
                    f"ASR segment {index} has invalid timing range: {start}-{end}"
                )

        source = ""
        explicit_trust = None
        if isinstance(resp_data, dict):
            source = str(resp_data.get("timing_source") or "").strip()
            if "word_timing_trusted" in resp_data:
                explicit_trust = resp_data["word_timing_trusted"]
                if not isinstance(explicit_trust, bool) or not source:
                    raise RuntimeError("ASR returned invalid word-timing provenance")

        if explicit_trust is None:
            # Legacy Qwen cache entries do not reveal whether the forced
            # aligner ran, so they must be treated as untrusted.
            if self.__class__.__name__ == "Qwen3ASR":
                word_timing_trusted = False
                source = source or "legacy_qwen3_unknown"
            else:
                word_timing_trusted = bool(
                    self.need_word_time_stamp and asr_data.is_word_timestamp()
                )
                source = source or (
                    "native_word_timestamps"
                    if word_timing_trusted
                    else "segment_timestamps"
                )
        else:
            word_timing_trusted = explicit_trust
            source = source or "unspecified"

        if (
            word_timing_trusted
            and self.need_word_time_stamp
            and not asr_data.is_word_timestamp()
        ):
            raise RuntimeError(
                "ASR marked word timing as trusted but returned non-word segments"
            )

        asr_data.timing_source = source
        asr_data.word_timing_trusted = word_timing_trusted
        for segment in asr_data.segments:
            segment.timing_source = source
            segment.word_timing_trusted = word_timing_trusted
        return asr_data

    def _get_key(self):
        """获取缓存key"""
        return self.crc32_hex

    def _make_segments(self, resp_data: dict) -> list[ASRDataSeg]:
        """将响应数据转换为ASRDataSeg列表"""
        raise NotImplementedError(
            "_make_segments method must be implemented in subclass"
        )

    def _run(self, callback=None, **kwargs) -> dict:
        """运行ASR服务并返回响应数据"""
        raise NotImplementedError("_run method must be implemented in subclass")
