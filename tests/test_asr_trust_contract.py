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
from app.core.subtitle_processor.word_timing_trust import (
    find_implausible_word_timing_runs,
)
from app.thread.transcript_thread import (
    _require_plausible_word_timing,
    _require_resolved_acoustic_gaps,
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
    def test_word_timing_trust_rejects_multiword_compression_cluster(self):
        segments = [
            ASRDataSeg(word, 100000 + index * 15, 100120)
            for index, word in enumerate(
                "does this all mean for you we're stuck".split()
            )
        ]

        issues = find_implausible_word_timing_runs(segments)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "implausible_word_timing_density")
        self.assertEqual(issues[0]["word_count"], 4)

    def test_word_timing_trust_accepts_fast_but_plausible_words(self):
        segments = [
            ASRDataSeg(word, index * 180, index * 180 + 150)
            for index, word in enumerate("this remains a fairly quick spoken sentence".split())
        ]

        self.assertEqual(find_implausible_word_timing_runs(segments), [])

    def test_word_timing_trust_reports_the_minimal_extreme_core(self):
        segments = [
            ASRDataSeg(word, 99000 + index * 220, 99180 + index * 220)
            for index, word in enumerate(
                "So what does this all mean for you we're completely stuck now".split()
            )
        ]
        for index in range(2, 8):
            segments[index].start_time = 100000
            segments[index].end_time = 100120

        issues = find_implausible_word_timing_runs(segments)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["start_index"], 2)
        self.assertEqual(issues[0]["end_index"], 5)
        self.assertEqual(issues[0]["word_count"], 4)

    def test_word_timing_trust_does_not_chain_dense_windows(self):
        segments = [
            ASRDataSeg(f"w{index}", index * 70, index * 70 + 80)
            for index in range(40)
        ]

        issues = find_implausible_word_timing_runs(segments)

        self.assertEqual(len(issues), 1)
        self.assertLessEqual(issues[0]["word_count"], 8)

    def test_word_timing_trust_keeps_conservative_border_cases(self):
        eight_words_741ms = [
            ASRDataSeg(f"w{index}", index * 95, index * 95 + 76)
            for index in range(8)
        ]
        eight_words_800ms = [
            ASRDataSeg(f"w{index}", index * 100, index * 100 + 100)
            for index in range(8)
        ]
        seven_words_600ms = [
            ASRDataSeg(f"w{index}", index * 86, index * 86 + 84)
            for index in range(7)
        ]

        issues = find_implausible_word_timing_runs(eight_words_741ms)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["word_count"], 8)
        self.assertEqual(issues[0]["duration_ms"], 741)
        self.assertEqual(find_implausible_word_timing_runs(eight_words_800ms), [])
        self.assertEqual(find_implausible_word_timing_runs(seven_words_600ms), [])

    def test_transcript_pipeline_blocks_implausibly_compressed_word_timing(self):
        data = ASRData(
            [
                ASRDataSeg(word, 1077980 + index * 10, 1078100)
                for index, word in enumerate(
                    "does this all mean for you we're stuck".split()
                )
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "implausibly compressed"):
            _require_plausible_word_timing(data)

    def test_transcript_pipeline_blocks_unresolved_acoustic_gap(self):
        data = ASRData([ASRDataSeg("quoted", 1000, 1200)])
        data.unresolved_internal_gap_candidates = [
            {
                "start_ms": 1200,
                "end_ms": 8200,
                "reason": "local_retry_not_anchored",
            }
        ]

        with self.assertRaisesRegex(RuntimeError, "unresolved internal gap"):
            _require_resolved_acoustic_gaps(data)

    def test_transcript_pipeline_accepts_asr_without_gap_diagnostics(self):
        data = ASRData([ASRDataSeg("quoted", 1000, 1200)])

        _require_resolved_acoustic_gaps(data)

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
            asr.need_word_time_stamp = False
            asr._build_command = lambda wav_path: ["faster-whisper", str(wav_path)]

            with patch(
                "app.core.bk_asr.faster_whisper.subprocess.Popen",
                side_effect=_popen,
            ):
                with self.assertRaisesRegex(RuntimeError, "return code"):
                    asr._run()

    def test_faster_whisper_accepts_valid_output_after_completed_shutdown_crash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            audio_path.write_bytes(b"wav")

            class _Process:
                def __init__(self, output_path):
                    self.stdout = _LineStream(
                        [
                            "100%\n",
                            "Subtitles are written to 'output' directory.\n",
                            "Operation finished in: 0:00:01.000\n",
                        ]
                    )
                    self.returncode = None
                    self.output_path = output_path

                def poll(self):
                    return None if self.stdout.lines else 0xC0000409

                def communicate(self):
                    self.returncode = 0xC0000409
                    self.output_path.write_text(SRT_TEXT, encoding="utf-8")
                    return ("", None)

            def _popen(cmd, **_kwargs):
                return _Process(Path(cmd[1]).with_suffix(".srt"))

            asr = object.__new__(FasterWhisperASR)
            asr.audio_path = str(audio_path)
            asr.process = None
            asr.need_word_time_stamp = False
            asr._build_command = lambda wav_path: ["faster-whisper", str(wav_path)]

            with patch(
                "app.core.bk_asr.faster_whisper.subprocess.Popen",
                side_effect=_popen,
            ):
                result = asr._run()

            self.assertEqual(result, SRT_TEXT)

    def test_faster_whisper_rejects_nonzero_exit_without_operation_finished(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            audio_path.write_bytes(b"wav")

            class _Process:
                def __init__(self, output_path):
                    self.stdout = _LineStream(
                        ["Subtitles are written to 'output' directory.\n"]
                    )
                    self.returncode = None
                    self.output_path = output_path

                def poll(self):
                    return None if self.stdout.lines else 0xC0000409

                def communicate(self):
                    self.returncode = 0xC0000409
                    self.output_path.write_text(SRT_TEXT, encoding="utf-8")
                    return ("", None)

            def _popen(cmd, **_kwargs):
                return _Process(Path(cmd[1]).with_suffix(".srt"))

            asr = object.__new__(FasterWhisperASR)
            asr.audio_path = str(audio_path)
            asr.process = None
            asr.need_word_time_stamp = False
            asr._build_command = lambda wav_path: ["faster-whisper", str(wav_path)]

            with patch(
                "app.core.bk_asr.faster_whisper.subprocess.Popen",
                side_effect=_popen,
            ):
                with self.assertRaisesRegex(RuntimeError, "return code"):
                    asr._run()

    def test_faster_whisper_rejects_completed_shutdown_crash_with_invalid_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            audio_path.write_bytes(b"wav")

            class _Process:
                def __init__(self, output_path):
                    self.stdout = _LineStream(
                        [
                            "Subtitles are written to 'output' directory.\n",
                            "Operation finished in: 0:00:01.000\n",
                        ]
                    )
                    self.returncode = None
                    self.output_path = output_path

                def poll(self):
                    return None if self.stdout.lines else 0xC0000409

                def communicate(self):
                    self.returncode = 0xC0000409
                    self.output_path.write_text("not an srt", encoding="utf-8")
                    return ("", None)

            def _popen(cmd, **_kwargs):
                return _Process(Path(cmd[1]).with_suffix(".srt"))

            asr = object.__new__(FasterWhisperASR)
            asr.audio_path = str(audio_path)
            asr.process = None
            asr.need_word_time_stamp = False
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

    def test_faster_whisper_zero_duration_repair_preserves_emitted_word_order(self):
        source = (
            "1\n00:14:34,160 --> 00:14:34,280\nShe\n\n"
            "2\n00:14:34,280 --> 00:14:34,280\n realizes\n\n"
            "3\n00:14:34,280 --> 00:14:34,280\n that\n\n"
            "4\n00:14:34,280 --> 00:14:34,400\n the\n\n"
            "5\n00:14:34,400 --> 00:14:34,600\n sex\n"
        )
        asr = object.__new__(FasterWhisperASR)
        asr.need_word_time_stamp = True
        asr._skip_internal_gap_repair = True

        result = asr._make_validated_data(source)

        self.assertEqual(
            [segment.text.strip() for segment in result.segments],
            ["She", "realizes", "that", "the", "sex"],
        )
        self.assertTrue(
            all(segment.end_time > segment.start_time for segment in result.segments)
        )

    @staticmethod
    def _missing_speech_gap_fixture():
        source_words = [
            "focus",
            "on",
            "your",
            "work.",
            "Wow.",
            "You",
            "are",
            "borrowing",
            "energy",
        ]
        source_times = [
            (528900, 529100),
            (529100, 529300),
            (529300, 529500),
            (529500, 530300),
            (530520, 530780),
            (538120, 538300),
            (538300, 538500),
            (538500, 538920),
            (538920, 539300),
        ]
        source = [
            ASRDataSeg(word, start, end)
            for word, (start, end) in zip(source_words, source_times)
        ]
        local_words = (
            "focus on your work Wow Which means you procrastinate more fall "
            "further behind feel worse and then stay up late again to numb the "
            "anxiety with more scrolling You are borrowing energy"
        ).split()
        local = []
        cursor = 528900
        for word in local_words:
            duration = 260
            local.append(ASRDataSeg(word, cursor, cursor + duration))
            cursor += duration
        return source, local

    def test_faster_whisper_merges_only_double_anchored_gap_words(self):
        source, local = self._missing_speech_gap_fixture()
        # Keep the fixture inside the original acoustic gap while retaining
        # exact text anchors on both sides.
        missing = local[5:-4]
        step = (538000 - 531000) // len(missing)
        for index, segment in enumerate(missing):
            segment.start_time = 531000 + index * step
            segment.end_time = 531000 + (index + 1) * step - 10
        for index, segment in enumerate(local[:5]):
            segment.start_time = source[index].start_time
            segment.end_time = source[index].end_time
        for index, segment in enumerate(local[-4:]):
            segment.start_time = source[5 + index].start_time
            segment.end_time = source[5 + index].end_time

        result = FasterWhisperASR._merge_anchored_gap_repair(
            source,
            left_index=4,
            local_segments=local,
        )

        self.assertIsNotNone(result)
        merged, report = result
        self.assertIn("Which means you procrastinate more", " ".join(item.text for item in merged))
        self.assertEqual(report["code"], "asr_internal_speech_gap_repaired")
        self.assertEqual(report["inserted_word_count"], len(missing))

    def test_faster_whisper_persists_repaired_word_srt_into_asr_cache(self):
        asr = object.__new__(FasterWhisperASR)
        asr.use_cache = True
        asr.last_internal_gap_repairs = [{"code": "asr_internal_speech_gap_repaired"}]
        asr.last_compressed_timing_repairs = []
        asr.last_tail_hallucination_repair = {}
        asr.cache_manager = _MemoryCache()
        asr._get_key = lambda: "repaired-key"
        repaired = ASRData(
            [
                ASRDataSeg("Which", 1000, 1200),
                ASRDataSeg("means", 1200, 1400),
            ]
        )

        with patch.object(BaseASR, "run", return_value=repaired):
            result = asr.run()

        self.assertIs(result, repaired)
        self.assertEqual(len(asr.cache_manager.writes), 1)
        self.assertIn("Which", asr.cache_manager.writes[0][2])

    def test_faster_whisper_exports_unresolved_gap_diagnostics_on_asr_data(self):
        asr = object.__new__(FasterWhisperASR)
        asr.use_cache = False
        asr.last_internal_gap_repairs = []
        asr.last_unresolved_internal_gap_candidates = [
            {"start_ms": 1200, "end_ms": 8200, "reason": "local_retry_empty"}
        ]
        asr.last_compressed_timing_repairs = []
        asr.last_unresolved_compressed_timing_candidates = []
        asr.last_tail_hallucination_repair = {}
        repaired = ASRData([ASRDataSeg("quoted", 1000, 1200)])

        with patch.object(BaseASR, "run", return_value=repaired):
            result = asr.run()

        self.assertEqual(
            result.unresolved_internal_gap_candidates[0]["reason"],
            "local_retry_empty",
        )

    @staticmethod
    def _compressed_timing_fixture():
        words = (
            "hits her like a ton of bricks She realizes that the sex itself "
            "wasn't actually the point"
        ).split()
        local_times = [
            (871800, 872000),
            (872000, 872220),
            (872220, 872440),
            (872440, 872540),
            (872540, 872940),
            (872940, 873080),
            (873080, 873400),
            (873560, 873700),
            (873700, 874020),
            (874020, 874280),
            (874280, 874400),
            (874400, 874600),
            (874600, 874860),
            (874860, 875160),
            (875160, 875340),
            (875340, 875480),
            (875480, 875680),
        ]
        local = [
            ASRDataSeg(word, start, end)
            for word, (start, end) in zip(words, local_times)
        ]
        source = [
            ASRDataSeg(segment.text, segment.start_time, segment.end_time)
            for segment in local
        ]
        issue_start = words.index("She")
        compressed_times = [
            (874160, 874280),
            (874280, 874281),
            (874280, 874281),
            (874280, 874400),
        ]
        for offset, (start, end) in enumerate(compressed_times):
            source[issue_start + offset].start_time = start
            source[issue_start + offset].end_time = end

        return source, local, issue_start

    def test_faster_whisper_repairs_compressed_native_timing_from_exact_local_text(self):
        source, local, issue_start = self._compressed_timing_fixture()
        untouched_right = [
            (segment.text, segment.start_time, segment.end_time)
            for segment in source[issue_start + 4 :]
        ]
        asr = object.__new__(FasterWhisperASR)
        asr._can_run_local_gap_repair = lambda: True
        asr._transcribe_local_window = lambda *_args: local

        repaired = asr._repair_suspicious_compressed_timing(source)

        self.assertEqual(
            [segment.text for segment in repaired],
            [segment.text for segment in source],
        )
        self.assertEqual(
            [
                (segment.start_time, segment.end_time)
                for segment in repaired[issue_start : issue_start + 4]
            ],
            [
                (segment.start_time, segment.end_time)
                for segment in local[issue_start : issue_start + 4]
            ],
        )
        self.assertEqual(
            [
                (segment.text, segment.start_time, segment.end_time)
                for segment in repaired[issue_start + 4 :]
            ],
            untouched_right,
        )
        self.assertEqual(find_implausible_word_timing_runs(repaired), [])
        self.assertEqual(len(asr.last_compressed_timing_repairs), 1)

    def test_faster_whisper_does_not_repair_compression_without_exact_anchors(self):
        source, local, issue_start = self._compressed_timing_fixture()
        local[issue_start + 4 : issue_start + 8] = [
            ASRDataSeg("different", 874400, 874600),
            ASRDataSeg("right", 874600, 874800),
            ASRDataSeg("anchor", 874800, 875000),
            ASRDataSeg("ending", 875000, 875200),
        ]
        asr = object.__new__(FasterWhisperASR)
        asr._can_run_local_gap_repair = lambda: True
        asr._transcribe_local_window = lambda *_args: local
        before = [
            (segment.text, segment.start_time, segment.end_time) for segment in source
        ]

        repaired = asr._repair_suspicious_compressed_timing(source)

        self.assertEqual(
            [(segment.text, segment.start_time, segment.end_time) for segment in repaired],
            before,
        )
        self.assertEqual(asr.last_compressed_timing_repairs, [])
        self.assertEqual(len(asr.last_unresolved_compressed_timing_candidates), 1)

    @staticmethod
    def _terminal_compressed_hallucination_fixture():
        valid_words = "corporations hide the true origins of their products.".split()
        source = [
            ASRDataSeg(word, 1000 + index * 240, 1240 + index * 240)
            for index, word in enumerate(valid_words)
        ]
        tail_words = (
            "there are some other liters to look first and see that inside the "
            "never of nonsense in a free mole and an octavia character is nothing "
            "that low here is a simple fact for these imaginary insurance companies"
        ).split()
        tail_start_ms = source[-1].end_time
        source.extend(
            ASRDataSeg(
                word,
                tail_start_ms + index * 4,
                tail_start_ms + index * 4 + 4,
            )
            for index, word in enumerate(tail_words)
        )
        local = [
            ASRDataSeg(segment.text, segment.start_time, segment.end_time)
            for segment in source[: len(valid_words)]
        ]
        return source, local, len(valid_words)

    def test_faster_whisper_removes_impossible_terminal_tail_omitted_by_local_asr(self):
        source, local, tail_start = self._terminal_compressed_hallucination_fixture()
        asr = object.__new__(FasterWhisperASR)
        asr._can_run_local_gap_repair = lambda: True
        asr._transcribe_local_window = lambda *_args: local
        asr.last_tail_hallucination_repair = {}

        repaired = asr._repair_suspicious_compressed_timing(source)

        self.assertEqual(
            [segment.text for segment in repaired],
            [segment.text for segment in source[:tail_start]],
        )
        self.assertEqual(
            asr.last_tail_hallucination_repair["code"],
            "locally_unconfirmed_impossible_terminal_tail",
        )
        self.assertEqual(
            asr.last_tail_hallucination_repair["removed_word_count"],
            len(source) - tail_start,
        )
        self.assertEqual(find_implausible_word_timing_runs(repaired), [])

    def test_faster_whisper_keeps_terminal_tail_when_local_asr_hears_more_words(self):
        source, local, tail_start = self._terminal_compressed_hallucination_fixture()
        local.append(
            ASRDataSeg(
                source[tail_start].text,
                source[tail_start - 1].end_time,
                source[tail_start - 1].end_time + 220,
            )
        )
        asr = object.__new__(FasterWhisperASR)
        asr._can_run_local_gap_repair = lambda: True
        asr._transcribe_local_window = lambda *_args: local
        asr.last_tail_hallucination_repair = {}

        repaired = asr._repair_suspicious_compressed_timing(source)

        self.assertEqual(
            [segment.text for segment in repaired],
            [segment.text for segment in source],
        )
        self.assertFalse(asr.last_tail_hallucination_repair)

    def test_faster_whisper_restores_cached_order_only_for_the_same_word_multiset(self):
        source, local, issue_start = self._compressed_timing_fixture()
        source[issue_start + 2], source[issue_start + 3] = (
            source[issue_start + 3],
            source[issue_start + 2],
        )
        asr = object.__new__(FasterWhisperASR)
        asr._can_run_local_gap_repair = lambda: True
        asr._transcribe_local_window = lambda *_args: local

        repaired = asr._repair_suspicious_compressed_timing(source)

        self.assertEqual(
            [segment.text for segment in repaired[issue_start : issue_start + 4]],
            ["She", "realizes", "that", "the"],
        )
        self.assertTrue(
            asr.last_compressed_timing_repairs[0]["word_order_restored"]
        )

        changed_local = [
            ASRDataSeg(segment.text, segment.start_time, segment.end_time)
            for segment in local
        ]
        changed_local[issue_start + 1].text = "discovers"
        rejected_asr = object.__new__(FasterWhisperASR)
        rejected_asr._can_run_local_gap_repair = lambda: True
        rejected_asr._transcribe_local_window = lambda *_args: changed_local

        rejected = rejected_asr._repair_suspicious_compressed_timing(source)

        self.assertEqual(
            [segment.text for segment in rejected[issue_start : issue_start + 4]],
            ["She", "realizes", "the", "that"],
        )
        self.assertEqual(rejected_asr.last_compressed_timing_repairs, [])

    def test_faster_whisper_persists_compressed_timing_repair_into_asr_cache(self):
        asr = object.__new__(FasterWhisperASR)
        asr.use_cache = True
        asr.last_internal_gap_repairs = []
        asr.last_compressed_timing_repairs = [
            {"code": "asr_compressed_word_timing_repaired"}
        ]
        asr.last_tail_hallucination_repair = {}
        asr.cache_manager = _MemoryCache()
        asr._get_key = lambda: "compressed-repair-key"
        repaired = ASRData(
            [
                ASRDataSeg("She", 1000, 1200),
                ASRDataSeg("realizes", 1200, 1500),
            ]
        )

        with patch.object(BaseASR, "run", return_value=repaired):
            result = asr.run()

        self.assertIs(result, repaired)
        self.assertEqual(len(asr.cache_manager.writes), 1)
        self.assertIn("realizes", asr.cache_manager.writes[0][2])

    def test_faster_whisper_does_not_merge_gap_without_right_anchor(self):
        source, local = self._missing_speech_gap_fixture()
        local[-4:] = [ASRDataSeg("different", 538100, 538300)]

        self.assertIsNone(
            FasterWhisperASR._merge_anchored_gap_repair(
                source,
                left_index=4,
                local_segments=local,
            )
        )

    def test_faster_whisper_unanchored_active_gap_is_recorded_without_mutation(self):
        source, local = self._missing_speech_gap_fixture()
        local = [
            ASRDataSeg("unrelated", 531000, 531300),
            ASRDataSeg("background", 531300, 531700),
            ASRDataSeg("speech", 531700, 532100),
        ]
        asr = object.__new__(FasterWhisperASR)
        asr._can_run_local_gap_repair = lambda: True
        asr._audio_range_has_activity = lambda *_args: True
        asr._transcribe_local_window = lambda *_args: local

        repaired = asr._repair_suspicious_internal_gaps(source)

        self.assertEqual(
            [(segment.text, segment.start_time, segment.end_time) for segment in repaired],
            [(segment.text, segment.start_time, segment.end_time) for segment in source],
        )
        self.assertEqual(asr.last_internal_gap_repairs, [])
        self.assertEqual(len(asr.last_unresolved_internal_gap_candidates), 1)

    def test_faster_whisper_anchor_merge_tolerates_one_missing_edge_interjection(self):
        source, local = self._missing_speech_gap_fixture()
        local = [segment for segment in local if segment.text != "Wow"]
        missing = local[4:-4]
        step = (538000 - 530900) // len(missing)
        for index, segment in enumerate(missing):
            segment.start_time = 530900 + index * step
            segment.end_time = 530900 + (index + 1) * step - 10
        for index, segment in enumerate(local[:4]):
            segment.start_time = source[index].start_time
            segment.end_time = source[index].end_time
        for index, segment in enumerate(local[-4:]):
            segment.start_time = source[5 + index].start_time
            segment.end_time = source[5 + index].end_time

        result = FasterWhisperASR._merge_anchored_gap_repair(
            source,
            left_index=4,
            local_segments=local,
        )

        self.assertIsNotNone(result)
        _, report = result
        self.assertEqual(report["left_anchor_skipped_words"], 1)
        self.assertEqual(report["right_anchor_skipped_words"], 0)

    def test_faster_whisper_anchor_merge_fits_small_local_edge_overrun(self):
        source, local = self._missing_speech_gap_fixture()
        missing = local[5:-4]
        step = (538420 - 530780) // len(missing)
        for index, segment in enumerate(missing):
            segment.start_time = 530780 + index * step
            segment.end_time = 530780 + (index + 1) * step - 10
        for index, segment in enumerate(local[:5]):
            segment.start_time = source[index].start_time
            segment.end_time = source[index].end_time
        for index, segment in enumerate(local[-4:]):
            segment.start_time = source[5 + index].start_time
            segment.end_time = source[5 + index].end_time + 300

        result = FasterWhisperASR._merge_anchored_gap_repair(
            source,
            left_index=4,
            local_segments=local,
        )

        self.assertIsNotNone(result)
        merged, report = result
        inserted = merged[5:-4]
        self.assertTrue(report["timing_fitted_to_gap"])
        self.assertEqual(inserted[-1].end_time, source[5].start_time)
        self.assertTrue(
            all(item.end_time > item.start_time for item in inserted)
        )
        self.assertTrue(
            all(
                left.end_time <= right.start_time
                for left, right in zip(merged, merged[1:])
            )
        )

    def test_faster_whisper_anchor_merge_rejects_large_local_edge_overrun(self):
        source, local = self._missing_speech_gap_fixture()
        missing = local[5:-4]
        step = (540000 - 530780) // len(missing)
        for index, segment in enumerate(missing):
            segment.start_time = 530780 + index * step
            segment.end_time = 530780 + (index + 1) * step - 10
        for index, segment in enumerate(local[:5]):
            segment.start_time = source[index].start_time
            segment.end_time = source[index].end_time
        for index, segment in enumerate(local[-4:]):
            segment.start_time = source[5 + index].start_time
            segment.end_time = 540000 + index * 300

        self.assertIsNone(
            FasterWhisperASR._merge_anchored_gap_repair(
                source,
                left_index=4,
                local_segments=local,
            )
        )

    @staticmethod
    def _tail_duplicate_word_srt(candidate_words):
        previous_words = (
            "The real trick is designing a daily environment that requires less "
            "raw willpower to begin with."
        ).split()
        segments = [
            ASRDataSeg(word, index * 300, (index + 1) * 300)
            for index, word in enumerate(previous_words)
        ]
        tail_start = 5000
        segments.extend(
            ASRDataSeg(
                word,
                tail_start + (index // 4) * 50,
                tail_start + (index // 4) * 50 + 60,
            )
            for index, word in enumerate(candidate_words)
        )
        return ASRData(segments).to_srt("仅原文")

    def test_faster_whisper_removes_high_confidence_silent_tail_duplicate(self):
        candidate = "We're looking at a daily environment that requires less raw willpower to begin with.".split()
        asr = object.__new__(FasterWhisperASR)
        asr.need_word_time_stamp = True
        asr._tail_audio_is_silent = lambda *_args: True

        segments = asr._make_segments(self._tail_duplicate_word_srt(candidate))

        self.assertEqual(
            " ".join(segment.text for segment in segments),
            "The real trick is designing a daily environment that requires less raw willpower to begin with.",
        )
        self.assertEqual(asr.last_tail_hallucination_repair["removed_word_count"], 14)

    def test_faster_whisper_keeps_audible_tail_even_when_text_repeats(self):
        candidate = "We're looking at a daily environment that requires less raw willpower to begin with.".split()
        asr = object.__new__(FasterWhisperASR)
        asr.need_word_time_stamp = True
        asr._tail_audio_is_silent = lambda *_args: False

        segments = asr._make_segments(self._tail_duplicate_word_srt(candidate))

        self.assertEqual(len(segments), 30)
        self.assertFalse(getattr(asr, "last_tail_hallucination_repair", {}))

    def test_faster_whisper_keeps_silent_tail_without_repeated_phrase_evidence(self):
        candidate = "This closing thought introduces a completely different and useful final idea for listeners.".split()
        asr = object.__new__(FasterWhisperASR)
        asr.need_word_time_stamp = True
        asr._tail_audio_is_silent = lambda *_args: True

        segments = asr._make_segments(self._tail_duplicate_word_srt(candidate))

        self.assertEqual(len(segments), 16 + len(candidate))
        self.assertFalse(getattr(asr, "last_tail_hallucination_repair", {}))


if __name__ == "__main__":
    unittest.main()
