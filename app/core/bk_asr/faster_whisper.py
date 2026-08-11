import hashlib
from difflib import SequenceMatcher
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Union

from ..utils.logger import setup_logger
from ..subtitle_processor.word_timing_trust import describe_word_timing_issue
from .asr_data import ASRDataSeg, ASRData
from .base import BaseASR

logger = setup_logger("faster_whisper")


class FasterWhisperASR(BaseASR):
    INTERNAL_GAP_MIN_MS = 1800
    INTERNAL_GAP_MAX_MS = 15000
    INTERNAL_GAP_CONTEXT_WORDS = 8
    INTERNAL_GAP_WINDOW_PADDING_MS = 2500
    INTERNAL_GAP_MIN_INSERTED_WORDS = 3
    INTERNAL_GAP_ACTIVITY_DB = -42.0
    INTERNAL_GAP_MAX_REPAIRS = 8
    TAIL_HALLUCINATION_MIN_WORDS = 6
    TAIL_HALLUCINATION_MAX_WORDS = 24
    TAIL_HALLUCINATION_MIN_WPS = 12.0
    TAIL_HALLUCINATION_MAX_DURATION_MS = 1500
    TAIL_HALLUCINATION_MIN_OVERLAP_RATIO = 0.30
    TAIL_HALLUCINATION_MIN_REPEAT_WORDS = 5
    TAIL_HALLUCINATION_MIN_REPEAT_RATIO = 0.60
    TAIL_HALLUCINATION_SILENCE_DB = -45.0

    def __init__(
        self,
        audio_path: str,
        faster_whisper_program: str,
        whisper_model: str,
        model_dir: str,
        language: str = "zh",
        device: str = "cpu",
        output_dir: str = None,
        output_format: str = "srt",
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
        # VAD 相关参数
        vad_filter: bool = True,
        vad_threshold: float = 0.4,
        vad_method: str = "",  # https://github.com/Purfview/whisper-standalone-win/discussions/231
        # 音频处理
        ff_mdx_kim2: bool = False,
        # 文本处理参数
        one_word: int = 0,
        sentence: bool = False,
        max_line_width: int = 100,
        max_line_count: int = 1,
        max_comma: int = 20,
        max_comma_cent: int = 50,
        prompt: str = None,
    ):
        super().__init__(audio_path, use_cache, need_word_time_stamp)

        # 基本参数
        self.model_path = whisper_model
        self.model_dir = model_dir
        self.faster_whisper_program = faster_whisper_program
        self.need_word_time_stamp = need_word_time_stamp
        self.language = language
        self.device = device
        self.output_dir = output_dir
        self.output_format = output_format

        # VAD 参数
        self.vad_filter = vad_filter
        self.vad_threshold = vad_threshold
        self.vad_method = vad_method

        # 音频处理参数
        self.ff_mdx_kim2 = ff_mdx_kim2

        # 文本处理参数
        self.one_word = one_word
        self.sentence = sentence
        self.max_line_width = max_line_width
        self.max_line_count = max_line_count
        self.max_comma = max_comma
        self.max_comma_cent = max_comma_cent
        self.prompt = prompt

        self.process = None

        # 断句宽度
        if self.language in ["zh", "ja", "ko"]:
            self.max_line_width = 30
        else:
            self.max_line_width = 90

        # 断句选项
        if self.need_word_time_stamp:
            self.one_word = 1
        else:
            self.one_word = 0
            self.sentence = True

        # 根据设备选择程序
        if self.device == "cpu":
            if shutil.which("faster-whisper-xxl"):
                self.faster_whisper_program = "faster-whisper-xxl"
            else:
                if not shutil.which("faster-whisper"):
                    raise EnvironmentError("faster-whisper程序未找到，请确保已经下载。")
                self.faster_whisper_program = "faster-whisper"
                self.vad_method = None
        elif self.device == "cuda":
            if not shutil.which("faster-whisper-xxl"):
                raise EnvironmentError(
                    "faster-whisper-xxl 程序未找到，请确保已经下载。"
                )
            self.faster_whisper_program = "faster-whisper-xxl"

    def run(self, callback=None, **kwargs) -> ASRData:
        asr_data = super().run(callback, **kwargs)
        repaired = bool(
            getattr(self, "last_internal_gap_repairs", [])
            or getattr(self, "last_tail_hallucination_repair", {})
        )
        if repaired and getattr(self, "use_cache", False):
            self.cache_manager.set_asr_result(
                self._get_key(),
                self.__class__.__name__,
                asr_data.to_srt("仅原文"),
            )
        return asr_data

    def _build_command(self, audio_path: str) -> List[str]:
        """构建命令行参数"""

        cmd = [
            str(self.faster_whisper_program),
            "-m",
            str(self.model_path),
            # "--verbose", "true",
            "--print_progress",
        ]

        # 添加模型目录参数
        if self.model_dir:
            cmd.extend(["--model_dir", str(self.model_dir)])

        # 基本参数
        cmd.extend(
            [
                str(audio_path),
                "-l",
                self.language,
                "-d",
                self.device,
                "--output_format",
                self.output_format,
            ]
        )

        # 输出目录
        if self.output_dir:
            cmd.extend(["-o", str(self.output_dir)])
        else:
            cmd.extend(["-o", "source"])

        # VAD 相关参数
        if self.vad_filter:
            cmd.extend(
                [
                    "--vad_filter",
                    "true",
                    "--vad_threshold",
                    f"{self.vad_threshold:.2f}",
                ]
            )
            if self.vad_method:
                cmd.extend(["--vad_method", self.vad_method])
        else:
            cmd.extend(["--vad_filter", "false"])

        # 人声分离
        if self.ff_mdx_kim2 and self.faster_whisper_program.startswith(
            "faster-whisper-xxl"
        ):
            cmd.append("--ff_mdx_kim2")

        # 文本处理参数
        if self.one_word:
            self.one_word = 1
        else:
            self.one_word = 0
        if self.one_word in [0, 1, 2]:
            cmd.extend(["--one_word", str(self.one_word)])

        if self.sentence:
            cmd.extend(
                [
                    "--sentence",
                    "--max_line_width",
                    str(self.max_line_width),
                    "--max_line_count",
                    str(self.max_line_count),
                    "--max_comma",
                    str(self.max_comma),
                    "--max_comma_cent",
                    str(self.max_comma_cent),
                ]
            )

        # 提示词
        if self.prompt:
            cmd.extend(["--prompt", self.prompt])

        # 完成的提示音
        cmd.extend(["--beep_off"])

        return cmd

    @staticmethod
    def _repair_quantized_zero_duration_segments(
        segments: list[ASRDataSeg],
    ) -> list[ASRDataSeg]:
        """Repair only sub-millisecond words collapsed by SRT serialization."""
        repair_count = 0
        for index, segment in enumerate(segments):
            start = int(segment.start_time)
            end = int(segment.end_time)
            if end != start:
                continue

            repaired_start = start
            if index > 0:
                repaired_start = max(
                    repaired_start,
                    int(segments[index - 1].end_time),
                )
            next_distinct_start = next(
                (
                    int(candidate.start_time)
                    for candidate in segments[index + 1 :]
                    if int(candidate.start_time) > start
                ),
                None,
            )
            repaired_end = repaired_start + 1
            if (
                next_distinct_start is not None
                and repaired_end > next_distinct_start
            ):
                raise RuntimeError(
                    "Faster Whisper zero-duration timing cannot be repaired "
                    f"without crossing the next word at segment {index}"
                )
            segment.start_time = repaired_start
            segment.end_time = repaired_end
            segment.timing_repair = "millisecond_quantization_zero_width"
            repair_count += 1

        if repair_count:
            logger.warning(
                "Repaired %s zero-duration Faster Whisper word timestamp(s) "
                "after millisecond SRT quantization",
                repair_count,
            )
        return segments

    def _make_segments(self, resp_data: str) -> list[ASRDataSeg]:
        asr_data = ASRData.from_srt(resp_data)
        self._repair_quantized_zero_duration_segments(asr_data.segments)
        # 过滤掉纯音乐标记
        filtered_segments = []
        for seg in asr_data.segments:
            text = seg.text.strip()
            if not (
                text.startswith("【")
                or text.startswith("[")
                or text.startswith("(")
                or text.startswith("（")
            ):
                filtered_segments.append(seg)
        filtered_segments = self._remove_high_confidence_silent_tail_duplicate(
            filtered_segments
        )
        if (
            getattr(self, "need_word_time_stamp", False)
            and not getattr(self, "_skip_internal_gap_repair", False)
        ):
            filtered_segments = self._repair_suspicious_internal_gaps(
                filtered_segments
            )
        return filtered_segments

    @classmethod
    def _internal_gap_candidates(
        cls,
        segments: list[ASRDataSeg],
    ) -> list[dict]:
        candidates = []
        for left_index, (left, right) in enumerate(zip(segments, segments[1:])):
            gap_start_ms = int(left.end_time)
            gap_end_ms = int(right.start_time)
            duration_ms = gap_end_ms - gap_start_ms
            if not cls.INTERNAL_GAP_MIN_MS <= duration_ms <= cls.INTERNAL_GAP_MAX_MS:
                continue
            candidates.append(
                {
                    "code": "asr_internal_word_gap",
                    "left_index": left_index,
                    "right_index": left_index + 1,
                    "start_ms": gap_start_ms,
                    "end_ms": gap_end_ms,
                    "duration_ms": duration_ms,
                }
            )
        return candidates

    @staticmethod
    def _normalized_words(segments: list[ASRDataSeg]) -> list[str]:
        return [
            FasterWhisperASR._normalize_tail_word(segment.text)
            for segment in segments
        ]

    @classmethod
    def _merge_anchored_gap_repair(
        cls,
        segments: list[ASRDataSeg],
        *,
        left_index: int,
        local_segments: list[ASRDataSeg],
    ) -> Optional[tuple[list[ASRDataSeg], dict]]:
        if left_index < 0 or left_index + 1 >= len(segments):
            return None
        source_words = cls._normalized_words(segments)
        local_words = cls._normalized_words(local_segments)
        if any(not word for word in local_words):
            return None

        anchor_pairs = []
        for left_edge_skip in range(2):
            left_anchor_end = left_index - left_edge_skip
            if left_anchor_end < 1:
                continue
            max_left_anchor = min(4, left_anchor_end + 1)
            for left_count in range(max_left_anchor, 1, -1):
                left_anchor = source_words[
                    left_anchor_end - left_count + 1 : left_anchor_end + 1
                ]
                left_matches = cls._subsequence_starts(local_words, left_anchor)
                for right_edge_skip in range(2):
                    right_anchor_start = left_index + 1 + right_edge_skip
                    max_right_anchor = min(4, len(segments) - right_anchor_start)
                    for right_count in range(max_right_anchor, 1, -1):
                        right_anchor = source_words[
                            right_anchor_start : right_anchor_start + right_count
                        ]
                        right_matches = cls._subsequence_starts(local_words, right_anchor)
                        for left_start in left_matches:
                            insert_start = left_start + left_count
                            for right_start in right_matches:
                                if right_start <= insert_start:
                                    continue
                                inserted_count = right_start - insert_start
                                if inserted_count < cls.INTERNAL_GAP_MIN_INSERTED_WORDS:
                                    continue
                                expected_left_ms = int(segments[left_index].end_time)
                                expected_right_ms = int(segments[left_index + 1].start_time)
                                acoustic_distance = abs(
                                    int(local_segments[insert_start].start_time)
                                    - expected_left_ms
                                ) + abs(
                                    int(local_segments[right_start - 1].end_time)
                                    - expected_right_ms
                                )
                                anchor_pairs.append(
                                    (
                                        left_edge_skip + right_edge_skip,
                                        -left_count - right_count,
                                        acoustic_distance,
                                        insert_start,
                                        right_start,
                                        left_edge_skip,
                                        right_edge_skip,
                                    )
                                )
        if not anchor_pairs:
            return None

        (
            _,
            _,
            _,
            insert_start,
            insert_end,
            left_edge_skip,
            right_edge_skip,
        ) = sorted(anchor_pairs)[0]
        inserted = [
            ASRDataSeg(
                text=segment.text,
                start_time=int(segment.start_time),
                end_time=int(segment.end_time),
            )
            for segment in local_segments[insert_start:insert_end]
        ]
        gap_start_ms = int(segments[left_index].end_time)
        gap_end_ms = int(segments[left_index + 1].start_time)
        if (
            not inserted
            or int(inserted[0].start_time) < gap_start_ms - 250
            or int(inserted[-1].end_time) > gap_end_ms + 250
        ):
            return None
        if any(int(segment.end_time) <= int(segment.start_time) for segment in inserted):
            return None
        if any(
            int(current.start_time) < int(previous.start_time)
            for previous, current in zip(inserted, inserted[1:])
        ):
            return None

        merged = list(segments[: left_index + 1]) + inserted + list(
            segments[left_index + 1 :]
        )
        return merged, {
            "code": "asr_internal_speech_gap_repaired",
            "start_ms": gap_start_ms,
            "end_ms": gap_end_ms,
            "inserted_word_count": len(inserted),
            "inserted_text": " ".join(segment.text.strip() for segment in inserted),
            "left_anchor_skipped_words": left_edge_skip,
            "right_anchor_skipped_words": right_edge_skip,
        }

    @staticmethod
    def _subsequence_starts(words: list[str], needle: list[str]) -> list[int]:
        if not needle or len(needle) > len(words):
            return []
        return [
            index
            for index in range(len(words) - len(needle) + 1)
            if words[index : index + len(needle)] == needle
        ]

    def _repair_suspicious_internal_gaps(
        self,
        segments: list[ASRDataSeg],
    ) -> list[ASRDataSeg]:
        self.last_internal_gap_repairs = []
        self.last_unresolved_internal_gap_candidates = []
        if not segments or not self._can_run_local_gap_repair():
            return segments

        repaired = list(segments)
        attempts = 0
        while attempts < self.INTERNAL_GAP_MAX_REPAIRS:
            candidates = self._internal_gap_candidates(repaired)
            if not candidates:
                break
            applied = False
            for candidate in candidates:
                if attempts >= self.INTERNAL_GAP_MAX_REPAIRS:
                    break
                if not self._audio_range_has_activity(
                    candidate["start_ms"], candidate["end_ms"]
                ):
                    continue
                attempts += 1
                left_index = int(candidate["left_index"])
                context_start = max(
                    0,
                    left_index - self.INTERNAL_GAP_CONTEXT_WORDS + 1,
                )
                context_end = min(
                    len(repaired) - 1,
                    left_index + self.INTERNAL_GAP_CONTEXT_WORDS,
                )
                window_start_ms = max(
                    0,
                    int(repaired[context_start].start_time)
                    - self.INTERNAL_GAP_WINDOW_PADDING_MS,
                )
                window_end_ms = (
                    int(repaired[context_end].end_time)
                    + self.INTERNAL_GAP_WINDOW_PADDING_MS
                )
                local_segments = self._transcribe_local_window(
                    window_start_ms,
                    window_end_ms,
                )
                merged = self._merge_anchored_gap_repair(
                    repaired,
                    left_index=left_index,
                    local_segments=local_segments,
                )
                if merged is not None:
                    repaired, report = merged
                    self.last_internal_gap_repairs.append(report)
                    logger.warning("Repaired Faster Whisper internal speech gap: %s", report)
                    applied = True
                    break

                words_inside_gap = [
                    segment
                    for segment in local_segments
                    if int(segment.start_time) >= int(candidate["start_ms"])
                    and int(segment.end_time) <= int(candidate["end_ms"])
                ]
                if len(words_inside_gap) >= self.INTERNAL_GAP_MIN_INSERTED_WORDS:
                    unresolved = {
                        **candidate,
                        "word_count": len(words_inside_gap),
                        "local_text": " ".join(
                            segment.text.strip() for segment in words_inside_gap
                        ),
                    }
                    self.last_unresolved_internal_gap_candidates.append(unresolved)
                    logger.warning(
                        "Skipped unanchored Faster Whisper gap candidate: %s",
                        describe_word_timing_issue(unresolved),
                    )
            if not applied:
                break
        return repaired

    def _can_run_local_gap_repair(self) -> bool:
        audio_path = getattr(self, "audio_path", None)
        return bool(
            isinstance(audio_path, str)
            and Path(audio_path).is_file()
            and self._find_ffmpeg() is not None
            and getattr(self, "faster_whisper_program", None)
        )

    def _audio_range_has_activity(self, start_ms: int, end_ms: int) -> bool:
        max_volume_db = self._probe_max_volume_db(start_ms, end_ms)
        return max_volume_db is not None and max_volume_db > self.INTERNAL_GAP_ACTIVITY_DB

    def _transcribe_local_window(
        self,
        start_ms: int,
        end_ms: int,
    ) -> list[ASRDataSeg]:
        ffmpeg = self._find_ffmpeg()
        if ffmpeg is None:
            return []
        duration_ms = max(1, int(end_ms) - int(start_ms))
        temp_root = Path(tempfile.gettempdir()) / "bk_asr"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, prefix="gap_repair_") as temp_path:
            repair_dir = Path(temp_path)
            clip_path = repair_dir / "repair.wav"
            extract_command = [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{max(0, int(start_ms)) / 1000.0:.3f}",
                "-i",
                str(self.audio_path),
                "-t",
                f"{duration_ms / 1000.0:.3f}",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-y",
                str(clip_path),
            ]
            extracted = subprocess.run(
                extract_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                check=False,
            )
            if extracted.returncode != 0 or not clip_path.is_file():
                logger.warning("Faster Whisper gap audio extraction failed: %s", extracted.stdout[-1000:])
                return []

            command = self._build_command(str(clip_path))
            try:
                output_index = command.index("-o") + 1
                command[output_index] = str(repair_dir)
            except (ValueError, IndexError):
                return []
            command.extend(["--condition_on_previous_text", "False"])
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                check=False,
            )
            output_path = repair_dir / "repair.srt"
            if not output_path.is_file():
                logger.warning("Faster Whisper gap repair produced no SRT: %s", result.stdout[-1000:])
                return []
            if result.returncode != 0 and not (
                "Subtitles are written to" in result.stdout
                and "Operation finished in:" in result.stdout
            ):
                logger.warning("Faster Whisper gap repair failed: %s", result.stdout[-1000:])
                return []

            local_data = ASRData.from_srt(output_path.read_text(encoding="utf-8"))
            self._repair_quantized_zero_duration_segments(local_data.segments)
            for segment in local_data.segments:
                segment.start_time = int(segment.start_time) + int(start_ms)
                segment.end_time = int(segment.end_time) + int(start_ms)
            return local_data.segments

    @staticmethod
    def _normalize_tail_word(text: str) -> str:
        return re.sub(r"[^a-z0-9']+", "", str(text or "").lower())

    @classmethod
    def _tail_duplicate_start_index(
        cls,
        segments: list[ASRDataSeg],
    ) -> Optional[int]:
        if len(segments) < cls.TAIL_HALLUCINATION_MIN_WORDS * 2:
            return None
        if not re.search(r"[.!?][\"')\]]*$", segments[-1].text.strip()):
            return None

        earliest = max(1, len(segments) - 48)
        candidate_starts = [
            index
            for index in range(earliest, len(segments))
            if re.search(r"[.!?][\"')\]]*$", segments[index - 1].text.strip())
        ]
        for start_index in reversed(candidate_starts):
            candidate = segments[start_index:]
            word_count = len(candidate)
            if not (
                cls.TAIL_HALLUCINATION_MIN_WORDS
                <= word_count
                <= cls.TAIL_HALLUCINATION_MAX_WORDS
            ):
                continue
            duration_ms = int(candidate[-1].end_time) - int(candidate[0].start_time)
            if duration_ms <= 0 or duration_ms > cls.TAIL_HALLUCINATION_MAX_DURATION_MS:
                continue
            words_per_second = word_count * 1000.0 / duration_ms
            if words_per_second < cls.TAIL_HALLUCINATION_MIN_WPS:
                continue
            overlap_count = sum(
                int(current.start_time) < int(previous.end_time)
                for previous, current in zip(candidate, candidate[1:])
            )
            if overlap_count / max(1, word_count - 1) < cls.TAIL_HALLUCINATION_MIN_OVERLAP_RATIO:
                continue

            candidate_words = [
                cls._normalize_tail_word(segment.text) for segment in candidate
            ]
            if any(not word for word in candidate_words):
                continue
            previous_words = [
                cls._normalize_tail_word(segment.text)
                for segment in segments[max(0, start_index - 80) : start_index]
            ]
            previous_words = [word for word in previous_words if word]
            repeated = SequenceMatcher(
                None,
                previous_words,
                candidate_words,
                autojunk=False,
            ).find_longest_match()
            if repeated.size < cls.TAIL_HALLUCINATION_MIN_REPEAT_WORDS:
                continue
            if repeated.size / word_count < cls.TAIL_HALLUCINATION_MIN_REPEAT_RATIO:
                continue
            return start_index
        return None

    @staticmethod
    def _find_ffmpeg() -> Optional[Path]:
        project_root = Path(__file__).resolve().parents[3]
        candidates = [
            project_root / "resource" / "bin" / "ffmpeg.exe",
            project_root
            / "resource"
            / "bin"
            / "Faster-Whisper-XXL"
            / "ffmpeg.exe",
        ]
        configured = shutil.which("ffmpeg")
        if configured:
            candidates.append(Path(configured))
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _tail_audio_is_silent(self, start_ms: int, end_ms: int) -> bool:
        max_volume_db = self._probe_max_volume_db(start_ms, end_ms)
        return (
            max_volume_db is not None
            and max_volume_db <= self.TAIL_HALLUCINATION_SILENCE_DB
        )

    def _probe_max_volume_db(
        self,
        start_ms: int,
        end_ms: int,
    ) -> Optional[float]:
        audio_path = getattr(self, "audio_path", None)
        if not isinstance(audio_path, str) or not Path(audio_path).is_file():
            return None
        ffmpeg = self._find_ffmpeg()
        if ffmpeg is None:
            return None
        duration_ms = max(1, int(end_ms) - int(start_ms))
        command = [
            str(ffmpeg),
            "-hide_banner",
            "-nostats",
            "-ss",
            f"{max(0, int(start_ms)) / 1000.0:.3f}",
            "-i",
            audio_path,
            "-t",
            f"{duration_ms / 1000.0:.3f}",
            "-af",
            "volumedetect",
            "-f",
            "null",
            os.devnull,
        ]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Faster Whisper tail audio probe failed: %s", exc)
            return None
        if result.returncode != 0:
            return None
        match = re.search(
            r"max_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB",
            result.stdout or "",
            re.IGNORECASE,
        )
        if not match:
            return None
        raw_volume = match.group(1).lower()
        max_volume_db = float("-inf") if raw_volume == "-inf" else float(raw_volume)
        return max_volume_db

    def _remove_high_confidence_silent_tail_duplicate(
        self,
        segments: list[ASRDataSeg],
    ) -> list[ASRDataSeg]:
        self.last_tail_hallucination_repair = {}
        if not getattr(self, "need_word_time_stamp", False):
            return segments
        start_index = self._tail_duplicate_start_index(segments)
        if start_index is None:
            return segments
        candidate = segments[start_index:]
        start_ms = int(candidate[0].start_time)
        end_ms = int(candidate[-1].end_time)
        if not self._tail_audio_is_silent(start_ms, end_ms):
            return segments
        self.last_tail_hallucination_repair = {
            "code": "high_confidence_silent_tail_duplicate",
            "start_ms": start_ms,
            "end_ms": end_ms,
            "removed_word_count": len(candidate),
            "removed_text": " ".join(segment.text.strip() for segment in candidate),
        }
        logger.warning(
            "Removed high-confidence silent Faster Whisper tail duplicate: %s",
            self.last_tail_hallucination_repair,
        )
        return segments[:start_index]

    def _read_validated_completed_output(self, output_path: Path) -> Optional[str]:
        previous_skip = getattr(self, "_skip_internal_gap_repair", False)
        self._skip_internal_gap_repair = True
        try:
            response_text = output_path.read_text(encoding="utf-8")
            self._make_validated_data(response_text)
        except Exception as exc:
            logger.warning(
                "Faster Whisper completed output failed validation: %s",
                exc,
            )
            return None
        finally:
            self._skip_internal_gap_repair = previous_skip
        return response_text

    def _run(self, callback=None) -> str:
        if callback is None:
            callback = lambda x, y: None

        temp_dir = Path(tempfile.gettempdir()) / "bk_asr"
        temp_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=temp_dir) as temp_path:
            temp_dir = Path(temp_path)
            wav_path = temp_dir / "audio.wav"
            output_path = wav_path.with_suffix(".srt")

            shutil.copy2(self.audio_path, wav_path)

            cmd = self._build_command(wav_path)

            logger.info("Faster Whisper 执行命令: %s", " ".join(cmd))
            callback(5, "Whisper识别")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            is_finish = False
            reported_output_written = False
            reported_operation_finished = False
            error_msg = ""

            # 实时打印日志和错误输出
            while True:
                output = self.process.stdout.readline()
                output = output.strip()
                if not output:
                    if self.process.poll() is not None:
                        break
                    continue
                # 解析进度百分比
                if match := re.search(r"(\d+)%", output):
                    progress = int(match.group(1))
                    if progress == 100:
                        is_finish = True
                    mapped_progress = int(5 + (progress * 0.9))
                    callback(mapped_progress, f"{mapped_progress} %")
                if "Subtitles are written to" in output:
                    is_finish = True
                    reported_output_written = True
                    callback(100, "识别完成")
                if "Operation finished in:" in output:
                    reported_operation_finished = True
                if "error" in output:
                    error_msg += output
                    logger.error(output)
                else:
                    logger.info(output)

            # 获取所有输出和错误信息
            self.process.communicate()

            logger.info("Faster Whisper 返回值: %s", self.process.returncode)
            recovered_output = None
            if (
                reported_output_written
                and reported_operation_finished
                and output_path.exists()
            ):
                recovered_output = self._read_validated_completed_output(output_path)
            if self.process.returncode != 0:
                if recovered_output is None:
                    logger.error(
                        "Faster Whisper exited with return code %s: %s",
                        self.process.returncode,
                        error_msg,
                    )
                    raise RuntimeError(
                        f"Faster Whisper return code {self.process.returncode}: {error_msg}"
                    )
                logger.warning(
                    "Faster Whisper exited after reporting completion; "
                    "using validated subtitle output: return_code=%s",
                    self.process.returncode,
                )
            if not is_finish:
                logger.error("Faster Whisper 错误: %s", error_msg)
                raise RuntimeError(error_msg)

            # 判断是否识别成功
            if not output_path.exists():
                raise RuntimeError(f"Faster Whisper 输出文件不存在: {output_path}")

            logger.info("Faster Whisper 识别完成")

            callback(100, "识别完成")

            return recovered_output or output_path.read_text(encoding="utf-8")

    def _get_key(self):
        """获取缓存key"""
        cmd = self._build_command("")
        cmd_hash = hashlib.md5(str(cmd).encode()).hexdigest()
        return f"{self.crc32_hex}-{cmd_hash}"
