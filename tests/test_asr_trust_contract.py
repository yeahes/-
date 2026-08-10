import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.bk_asr.base import BaseASR
from app.core.bk_asr.faster_whisper import FasterWhisperASR
from app.core.bk_asr.qwen3_asr_runner import proportional_word_segments
from app.core.bk_asr.whisper_api import WhisperAPI
from app.core.bk_asr.whisper_cpp import WhisperCppASR
from app.core.entities import TranscribeModelEnum
from app.thread.transcript_thread import (
    _write_srt_atomically,
    TranscriptThread,
    can_reuse_downloaded_subtitle,
    select_downloaded_subtitle,
)


SRT_TEXT = "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n"


class _MemoryCache:
    def __init__(self, cached=None):
        self.cached = cached
        self.writes = []

    def get_asr_result(self, key, asr_type):
        return self.cached

    def set_asr_result(self, key, asr_type, result):
        self.writes.append((key, asr_type, result))


class _FakeASR(BaseASR):
    def __init__(self, response, cached=None, need_word_time_stamp=False):
        self.response = response
        self.backend_calls = 0
        self.use_cache = True
        self.need_word_time_stamp = need_word_time_stamp
        self.cache_manager = _MemoryCache(cached)

    def _get_key(self):
        return "test-key"

    def _run(self, callback=None, **kwargs):
        self.backend_calls += 1
        return self.response

    def _make_segments(self, response):
        return [
            ASRDataSeg(
                text=item["text"],
                start_time=item["start_time"],
                end_time=item["end_time"],
            )
            for item in response.get("segments", [])
        ]


class Qwen3ASR(_FakeASR):
    pass


class _LineStream:
    def __init__(self, lines):
        self.lines = list(lines)
        self.read_count = 0

    def readline(self):
        self.read_count += 1
        if self.lines:
            return self.lines.pop(0)
        return ""


class ASRTrustContractTests(unittest.TestCase):
    def test_empty_backend_result_is_not_cached(self):
        asr = _FakeASR({"segments": []})

        with self.assertRaisesRegex(RuntimeError, "empty"):
            asr.run()

        self.assertEqual(asr.cache_manager.writes, [])

    def test_invalid_cached_result_is_ignored_and_replaced_after_validation(self):
        response = {
            "segments": [
                {"text": "hello", "start_time": 0, "end_time": 500},
            ]
        }
        asr = _FakeASR(response, cached={"segments": []})

        result = asr.run()

        self.assertTrue(result.has_data())
        self.assertEqual(asr.backend_calls, 1)
        self.assertEqual(len(asr.cache_manager.writes), 1)

    def test_legacy_qwen_cache_without_provenance_is_not_trusted(self):
        response = {
            "segments": [
                {"text": "hello", "start_time": 0, "end_time": 500},
            ]
        }
        asr = Qwen3ASR(response, need_word_time_stamp=True)

        result = asr.run()

        self.assertFalse(result.word_timing_trusted)
        self.assertEqual(result.timing_source, "legacy_qwen3_unknown")

    def test_explicit_word_timing_provenance_reaches_returned_data(self):
        response = {
            "segments": [
                {"text": "hello", "start_time": 0, "end_time": 500},
            ],
            "timing_source": "qwen3_forced_aligner",
            "word_timing_trusted": True,
        }
        asr = Qwen3ASR(response, need_word_time_stamp=True)

        result = asr.run()

        self.assertTrue(result.word_timing_trusted)
        self.assertEqual(result.segments[0].timing_source, "qwen3_forced_aligner")

    def test_downloaded_subtitle_selection_matches_language_and_uses_newest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle_dir = Path(temp_dir)
            old_en = subtitle_dir / "【下载字幕】en.srt"
            new_en = subtitle_dir / "【下载字幕】en-US.srt"
            newer_zh = subtitle_dir / "【下载字幕】zh.srt"
            for path in (old_en, new_en, newer_zh):
                path.write_text(SRT_TEXT, encoding="utf-8")
            os.utime(old_en, (100, 100))
            os.utime(new_en, (200, 200))
            os.utime(newer_zh, (300, 300))

            selected = select_downloaded_subtitle(subtitle_dir, "english")

            self.assertEqual(selected, new_en)

    def test_downloaded_subtitle_requires_language_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle_dir = Path(temp_dir)
            unknown = subtitle_dir / "【下载字幕】.srt"
            unknown.write_text(SRT_TEXT, encoding="utf-8")

            self.assertIsNone(select_downloaded_subtitle(subtitle_dir, "en"))

    def test_word_timing_pipeline_never_reuses_downloaded_subtitle(self):
        self.assertFalse(can_reuse_downloaded_subtitle(need_word_time_stamp=True))
        self.assertTrue(can_reuse_downloaded_subtitle(need_word_time_stamp=False))

    def test_atomic_srt_write_preserves_existing_output_on_empty_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output.srt"
            output.write_text("existing", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "empty subtitle"):
                _write_srt_atomically(ASRData([]), output)

            self.assertEqual(output.read_text(encoding="utf-8"), "existing")

    def test_qwen_proportional_timing_is_explicitly_untrusted_and_non_overlapping(self):
        segments = proportional_word_segments("one two three", 900)

        self.assertTrue(segments)
        self.assertTrue(all(not item["word_timing_trusted"] for item in segments))
        self.assertTrue(
            all(item["timing_source"] == "proportional_text_fallback" for item in segments)
        )
        self.assertTrue(
            all(left["end_time"] <= right["start_time"] for left, right in zip(segments, segments[1:]))
        )

    def test_qwen_proportional_timing_rejects_impossible_duration(self):
        with self.assertRaisesRegex(ValueError, "duration"):
            proportional_word_segments("one two three", 1)

    def test_qwen_aligner_configuration_only_skips_realign_when_result_is_trusted(self):
        thread = SimpleNamespace(
            task=SimpleNamespace(
                transcribe_config=SimpleNamespace(
                    transcribe_model=TranscribeModelEnum.QWEN3_ASR,
                    qwen3_aligner_model="aligner",
                )
            )
        )
        asr_data = ASRData([ASRDataSeg("hello", 0, 500)])
        asr_data.timing_source = "proportional_text_fallback"
        asr_data.word_timing_trusted = False

        self.assertFalse(
            TranscriptThread._should_skip_stable_ts_alignment(thread, asr_data)
        )

        asr_data.timing_source = "qwen3_forced_aligner"
        asr_data.word_timing_trusted = True
        self.assertTrue(
            TranscriptThread._should_skip_stable_ts_alignment(thread, asr_data)
        )

    def test_whisper_api_passes_configured_language(self):
        captured = {}

        class _Completion:
            def to_dict(self):
                return {"segments": []}

        class _Transcriptions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return _Completion()

        api = object.__new__(WhisperAPI)
        api.language = "en"
        api.prompt = ""
        api.need_word_time_stamp = False
        api.base_url = "https://example.invalid/v1"
        api.model = "whisper-test"
        api.file_binary = b"audio"
        api.client = type(
            "Client",
            (),
            {"audio": type("Audio", (), {"transcriptions": _Transcriptions()})()},
        )()

        api._submit()

        self.assertEqual(captured["language"], "en")

    def test_whisper_api_cache_key_separates_endpoints_without_exposing_query(self):
        first = object.__new__(WhisperAPI)
        second = object.__new__(WhisperAPI)
        for api in (first, second):
            api.crc32_hex = "deadbeef"
            api.model = "same-model"
            api.language = "en"
            api.prompt = "same-prompt"
            api.need_word_time_stamp = True
        first.base_url = "https://one.invalid/v1?api_key=secret"
        second.base_url = "https://two.invalid/v1?api_key=secret"

        first_key = first._get_key()
        second_key = second._get_key()

        self.assertNotEqual(first_key, second_key)
        self.assertNotIn("secret", first_key)
        self.assertNotIn("one.invalid", first_key)

    def test_whisper_cpp_eof_reaches_nonzero_exit_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            audio_path.write_bytes(b"wav")
            stream = _LineStream([])

            class _Process:
                def __init__(self):
                    self.stdout = stream
                    self.returncode = None

                def communicate(self):
                    self.returncode = 1
                    return ("fatal", None)

            asr = object.__new__(WhisperCppASR)
            asr.audio_path = str(audio_path)
            asr.process = None
            asr._build_command = lambda *_args: ["whisper-cpp"]
            asr.get_audio_duration = lambda *_args: 1

            with patch(
                "app.core.bk_asr.whisper_cpp.subprocess.Popen",
                return_value=_Process(),
            ):
                with self.assertRaisesRegex(RuntimeError, "WhisperCPP"):
                    asr._run()

            self.assertEqual(stream.read_count, 1)

    def test_faster_whisper_rejects_nonzero_exit_after_100_percent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            audio_path.write_bytes(b"wav")

            class _Process:
                def __init__(self, output_path):
                    self.stdout = _LineStream(["100%\n"])
                    self.returncode = None
                    self.output_path = output_path
                    self.poll_count = 0

                def poll(self):
                    self.poll_count += 1
                    return None if self.poll_count == 1 else 1

                def communicate(self):
                    self.returncode = 1
                    self.output_path.write_text(SRT_TEXT, encoding="utf-8")
                    return ("", None)

            def _popen(cmd, **_kwargs):
                return _Process(Path(cmd[1]).with_suffix(".srt"))

            asr = object.__new__(FasterWhisperASR)
            asr.audio_path = str(audio_path)
            asr.process = None
            asr._build_command = lambda wav_path: ["faster-whisper", str(wav_path)]

            with patch(
                "app.core.bk_asr.faster_whisper.subprocess.Popen",
                side_effect=_popen,
            ):
                with self.assertRaisesRegex(RuntimeError, "return code"):
                    asr._run()

    def test_faster_whisper_repairs_only_srt_quantized_zero_duration_words(self):
        source = (
            "1\n00:04:06,100 --> 00:04:06,100\nfirst\n\n"
            "2\n00:04:06,100 --> 00:04:06,100\nsecond\n\n"
            "3\n00:04:06,105 --> 00:04:06,200\nthird\n"
        )
        asr = object.__new__(FasterWhisperASR)

        segments = asr._make_segments(source)

        self.assertEqual([segment.text for segment in segments], ["first", "second", "third"])
        self.assertEqual(
            [(segment.start_time, segment.end_time) for segment in segments],
            [(246100, 246101), (246101, 246102), (246105, 246200)],
        )
        self.assertEqual(
            getattr(segments[0], "timing_repair", ""),
            "millisecond_quantization_zero_width",
        )


if __name__ == "__main__":
    unittest.main()
