import sys
import json
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor, ScreenSubtitleItem
from app.core.subtitle_processor.stable_ts_alignment import (
    align_frozen_word_ledger_with_whisperx,
    _make_whisperx_word_segments,
)
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.entities import SynthesisConfig, SynthesisTask, SubtitleConfig, SubtitleTask
from app.core.task_factory import TaskFactory
from app.thread.subtitle_thread import SubtitleThread
from app.thread.video_synthesis_thread import VideoSynthesisThread, resolve_podcast_template_subtitle
from app.core.utils import podcast_learning_video
from tests.caption_audit.metrics import (
    CaptionCue,
    audit_srt,
    _chinese_semantic_group_issues,
    _syntax_boundary_reasons,
    split_bilingual_body,
    count_words,
)


def _editor(max_words=14):
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = max_words
    editor._syntax_protected_cuts = set()
    editor._syntax_hard_cut_issues = {}
    editor._syntax_nlp = None
    editor._active_word_entries = []
    editor.coverage_report_path = None
    editor.last_validation_summary = None
    editor._frozen_subtitle_ids = []
    editor._translation_structure_errors = []
    editor._last_llm_raw_returns = []
    editor._last_semantic_group_debug = []
    editor._last_allocation_inputs = []
    editor._last_allocation_raw_returns = []
    editor._last_allocation_validation = []
    editor._last_allocation_retry_log = []
    editor._last_allocation_final = []
    editor._last_allocation_unresolved = []
    editor._last_semantic_group_audit_contexts = {}
    editor._last_semantic_group_id_by_subtitle_id = {}
    editor._boundary_snapshots = []
    editor._boundary_snapshot_changes = []
    editor._boundary_snapshot_item_sets = {}
    editor._pre_id_boundary_repairs = []
    editor._qa_review_points_path = ""
    return editor


def _entries(text):
    entries = []
    current = 0
    for match in ScreenSubtitleEditor._word_token_matches(text):
        surface = match.group(0)
        tokens = ScreenSubtitleEditor._word_tokens(surface)
        token = tokens[0] if tokens else surface.lower()
        entries.append(
            {
                "token": token,
                "surface": surface,
                "start_time": current,
                "end_time": current + 180,
            }
        )
        current += 220
    return entries


def _split_text(text, max_words=14):
    editor = _editor(max_words=max_words)
    editor._active_word_entries = _entries(text)
    ranges = editor._stable_word_ranges_for_span((0, len(editor._active_word_entries) - 1))
    return [
        " ".join(entry["surface"] for entry in editor._active_word_entries[start : end + 1])
        for start, end in ranges
    ]


def test_final_time_alignment_reapplies_display_padding_to_loaded_short_subtitle():
    editor = _editor()
    segments = [
        ASRDataSeg("Previous line.", 0, 1000, "前一句。"),
        ASRDataSeg("over 20% of its real value.", 1200, 1320, "超过20%的实际价值。"),
        ASRDataSeg("Next line.", 2300, 3200, "下一句。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    repaired = editor._repair_final_short_subtitle_timings(segments)

    assert repaired[1].end_time - repaired[1].start_time >= 700
    assert repaired[0].end_time <= repaired[1].start_time - 40
    assert repaired[1].end_time <= repaired[2].start_time - 40
    assert repaired[1].text == segments[1].text
    assert repaired[1].translated_text == segments[1].translated_text
    assert getattr(repaired[1], "subtitle_id") == "S0002"


def test_final_time_alignment_shifts_next_when_loaded_short_has_no_gap():
    editor = _editor()
    segments = [
        ASRDataSeg("deliver the joke,", 302600, 305840, "讲出笑话，"),
        ASRDataSeg(
            "and react to the silence if it completely bombs.",
            305880,
            306140,
            "并且在它彻底冷场时应对沉默。",
        ),
        ASRDataSeg("Right. You're on the hook for the delivery.", 306180, 307740, "没错，你要负责实际的表达。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    repaired = editor._repair_final_short_subtitle_timings(segments)

    assert repaired[1].start_time == 305880
    assert repaired[1].end_time - repaired[1].start_time >= 700
    assert repaired[2].start_time >= repaired[1].end_time + 40
    assert repaired[2].end_time - repaired[2].start_time >= 700
    assert repaired[1].text == segments[1].text
    assert repaired[2].text == segments[2].text
    assert getattr(repaired[1], "subtitle_id") == "S0002"
    assert getattr(repaired[2], "subtitle_id") == "S0003"


def test_final_time_alignment_runs_chinese_speed_repair_without_touching_english():
    editor = _editor()
    asr_data = ASRData(
        [
            ASRDataSeg(
                "can't spell to save his life.",
                0,
                1560,
                "拼写烂到不行的人之手的文本所带来的恐怖谷效应说起。",
            )
        ]
    )
    asr_data.segments[0].subtitle_id = "S0001"
    editor._last_semantic_groups = [{"id": 1, "items": []}]
    editor._last_subtitle_items = []

    called = {}

    def fake_compress(segments, semantic_groups=None, subtitle_items=None):
        called["semantic_groups"] = semantic_groups
        return [
            editor._copy_segment(
                segments[0],
                translated_text="它来自一个平时拼写很差的人",
            )
        ]

    editor._compress_fast_chinese_segments = fake_compress
    editor._write_coverage_report = lambda *args, **kwargs: None

    repaired = editor.repair_after_final_time_alignment(asr_data)

    assert called["semantic_groups"] == editor._last_semantic_groups
    assert repaired.segments[0].text == "can't spell to save his life."
    assert getattr(repaired.segments[0], "subtitle_id") == "S0001"
    assert repaired.segments[0].translated_text == "它来自一个平时拼写很差的人"


def _words(text):
    return ScreenSubtitleEditor._word_tokens(text)


def _id_editor():
    editor = _editor()
    editor.model = "test-model"
    editor.timeout = 5
    editor.batch_num = 24
    editor.allocation_batch_size = 24
    editor.allocation_max_concurrency = 1
    editor.cache_manager = _NoCache()
    editor.client = None
    editor.max_cjk_chars = 18
    editor._translation_structure_errors = []
    editor._last_llm_raw_returns = []
    editor._last_semantic_group_debug = []
    editor._last_semantic_group_audit_contexts = {}
    editor._last_semantic_group_id_by_subtitle_id = {}
    editor.article_context_prompt = ""
    editor._frozen_subtitle_ids = []
    editor._llm_cache_used = False
    editor._llm_cache_stats = {}
    editor._allocation_runtime_stats = {}
    return editor


def test_screen_editor_uses_16_word_stable_hard_floor():
    with patch.object(ScreenSubtitleEditor, "_init_client", return_value=None):
        editor = ScreenSubtitleEditor(
            model="test-model",
            max_english_words=14,
        )

    assert editor.max_english_words == 16


def test_stable_screen_pipeline_requests_word_timestamps_without_legacy_split():
    assert TaskFactory._needs_word_timestamps_for_subtitle_pipeline(
        need_split=False,
        need_screen_subtitle_edit=True,
        screen_subtitle_stable_mode=True,
    )
    assert TaskFactory._needs_word_timestamps_for_subtitle_pipeline(
        need_split=True,
        need_screen_subtitle_edit=False,
        screen_subtitle_stable_mode=False,
    )
    assert not TaskFactory._needs_word_timestamps_for_subtitle_pipeline(
        need_split=False,
        need_screen_subtitle_edit=True,
        screen_subtitle_stable_mode=False,
    )


class _NoCache:
    def get_llm_result(self, *args, **kwargs):
        return None

    def set_llm_result(self, *args, **kwargs):
        return None


class _QueueCache:
    def __init__(self, results):
        self.results = list(results)
        self.set_calls = []

    def get_llm_result(self, *args, **kwargs):
        if self.results:
            return self.results.pop(0)
        return None

    def set_llm_result(self, *args, **kwargs):
        self.set_calls.append((args, kwargs))


def _id_items(count, translated=""):
    return [
        ScreenSubtitleItem(
            source_ids=[index],
            original=f"English {index}.",
            translated=translated.format(index=index) if translated else "",
            word_start=index * 2,
            word_end=index * 2 + 1,
        )
        for index in range(1, count + 1)
    ]


def _id_group(group_id, start_index, items):
    return {"id": group_id, "start_index": start_index, "items": items}


def _codes(editor):
    return {issue["code"] for issue in editor._translation_structure_errors}


def _semantic_context(group_id, subtitle_ids, full_english, full_translation):
    return {
        "semantic_group_id": f"G{group_id:04d}",
        "group_id": group_id,
        "full_english": full_english,
        "full_english_signature": ScreenSubtitleEditor._semantic_audit_signature(full_english),
        "expected_subtitle_ids": list(subtitle_ids),
        "full_translation": full_translation,
        "mapping_valid": True,
    }


def _id_segments(count, translated="这是原文"):
    segments = []
    for index in range(1, count + 1):
        segment = ASRDataSeg(
            f"English {index}.",
            (index - 1) * 1000,
            index * 1000,
            translated,
        )
        segment.subtitle_id = f"S{index:04d}"
        segments.append(segment)
    return segments


def _marker_editor(words, max_words=14):
    editor = _id_editor()
    editor.max_english_words = max_words
    editor._active_word_entries = [
        {
            "token": ScreenSubtitleEditor._word_tokens(word)[0],
            "surface": word,
            "start_time": index * 200,
            "end_time": index * 200 + 120,
        }
        for index, word in enumerate(words)
    ]
    editor._active_source_word_spans = {
        index + 1: (index, index)
        for index in range(len(words))
    }
    editor._active_source_segments_by_id = {
        index + 1: ASRDataSeg(word, index * 200, index * 200 + 120, "")
        for index, word in enumerate(words)
    }
    editor._discourse_marker_orphans = []
    return editor


def _word_item(editor, start, end, source_id=None):
    return ScreenSubtitleItem(
        source_ids=[source_id if source_id is not None else start + 1],
        original=editor._text_from_word_span(start, end),
        translated="",
        word_start=start,
        word_end=end,
    )


class _StaticCache:
    def __init__(self, value):
        self.value = value

    def get_llm_result(self, *args, **kwargs):
        return json.dumps(self.value, ensure_ascii=False)

    def set_llm_result(self, *args, **kwargs):
        raise AssertionError("cache-backed test must not write")


def _assert_stable_split(text, max_words=16):
    parts = _split_text(text, max_words=max_words)
    assert parts
    rebuilt = [word for part in parts for word in _words(part)]
    assert rebuilt == _words(text)
    for part in parts:
        assert len(_words(part)) <= max_words, part
        first = _words(part)[0]
        last = _words(part)[-1]
        assert first not in {"of", "for", "with", "by", "to"}, parts
        assert last not in {"a", "an", "the", "to", "of", "for", "with", "by"}, parts


def test_preposition_phrase_is_not_stranded():
    _assert_stable_split(
        "If the market starts seeing the Fed as just a piggy bank to seamlessly fund government deficits, they lose credibility."
    )


def test_number_and_policy_sentence_keeps_readable_boundaries():
    _assert_stable_split(
        "From 1980 to 2015, the cultural preference for sons in a deeply patriarchal society led to decades of aborted female fetuses."
    )


def test_long_finance_sentence_keeps_full_coverage():
    _assert_stable_split(
        "Although the central bank can reduce its footprint, it cannot drain these massive financial reservoirs without triggering a drought."
    )


def test_missing_translation_is_reported_but_not_blocking():
    editor = _editor()
    source = [ASRDataSeg("Hello world.", 0, 1000)]
    final = [ASRDataSeg("Hello world.", 0, 1000, translated_text="")]

    editor._report_subtitle_coverage_gaps(source, final)

    assert editor.last_validation_summary["status"] == "ERROR"
    assert not editor.has_blocking_validation_errors()
    assert editor.blocking_validation_message() == ""


def test_suspicious_cut_is_warning_not_blocking():
    editor = _editor()
    source = [
        ASRDataSeg("Like, why risk that?", 0, 1200, translated_text="为什么要冒这个险？"),
        ASRDataSeg("Well,", 1240, 1600, translated_text="嗯，"),
    ]

    editor._report_subtitle_coverage_gaps(source, source)

    assert editor.last_validation_summary["status"] == "WARNING"
    assert not editor.has_blocking_validation_errors()


def test_abnormal_timing_gap_is_repaired_for_compressed_cluster():
    editor = _editor()
    segments = [
        ASRDataSeg("and, you know, wants to drain it.", 20580, 22740, "并且想要把它抽干。"),
        ASRDataSeg(
            "Which sounds kind of crazy if the town is literally surviving on that water.",
            27960,
            28700,
            "如果这个城镇确实是靠这水生存的，听起来就有点疯狂了。",
        ),
        ASRDataSeg("Like, why take the risk?", 28700, 29200, "为什么要冒这个风险？"),
        ASRDataSeg(
            "Right. And that is the exact dilemma facing the new Fed chairman right now.",
            29200,
            31280,
            "这正是新任美联储主席目前面临的困境。",
        ),
        ASRDataSeg(
            "So today, we're taking a deep dive into the Federal Reserve's massive balance sheet.",
            32140,
            36640,
            "今天我们深入探讨美联储庞大的资产负债表。",
        ),
    ]

    repaired = editor._repair_abnormal_timing_gaps(segments)

    assert repaired[1].start_time < 24000
    assert repaired[1].start_time - repaired[0].end_time <= 100
    assert repaired[3].end_time <= segments[4].start_time


def test_coverage_gap_does_not_sum_natural_pauses():
    editor = _editor()
    source = [
        ASRDataSeg(
            "But here's where it gets really interesting. Because the sources show the other massive drop in our albedo is directly tied to, well, less pollution.",
            122640,
            132600,
        )
    ]
    final = [
        ASRDataSeg("But here's where it gets really interesting.", 122640, 123960, "ok"),
        ASRDataSeg(
            "Because the sources show the other massive drop in our albedo",
            124980,
            128880,
            "ok",
        ),
        ASRDataSeg("is directly tied to, well, less pollution.", 129360, 132600, "ok"),
    ]

    editor._report_subtitle_coverage_gaps(source, final)

    assert editor.last_validation_summary["status"] != "ERROR"
    assert not editor.has_blocking_validation_errors()


def test_coverage_gap_blocks_single_long_uncovered_span():
    editor = _editor()
    source = [ASRDataSeg("This should remain covered by subtitles.", 0, 5000)]
    final = [
        ASRDataSeg("This should", 0, 1000, "ok"),
        ASRDataSeg("remain covered by subtitles.", 2700, 5000, "ok"),
    ]

    editor._report_subtitle_coverage_gaps(source, final)

    assert editor.last_validation_summary["status"] == "WARNING"
    assert not editor.has_blocking_validation_errors()
    assert any(
        issue["code"] == "coverage_gap_unverified"
        for issue in editor.last_validation_summary["warnings"]
    )


def _coverage_segment(text, start, end, subtitle_id, word_start, word_end):
    segment = ASRDataSeg(text, start, end, "中文")
    segment.subtitle_id = subtitle_id
    segment.word_start = word_start
    segment.word_end = word_end
    segment.stable_word_start_ms = word_start
    segment.stable_word_end_ms = word_end
    return segment


def test_final_display_coverage_bridges_short_continuous_source_gap():
    editor = _editor()
    source = [
        ASRDataSeg("Continuous", 0, 1000),
        ASRDataSeg("source speech.", 1100, 3000),
    ]
    segments = [
        _coverage_segment("First subtitle.", 0, 1000, "S0001", 0, 1000),
        _coverage_segment("Second subtitle.", 1600, 3000, "S0002", 1100, 3000),
    ]

    repaired = editor._reconcile_final_display_coverage(segments, source)

    assert repaired[0].end_time == 1300
    assert repaired[1].start_time == 1300
    assert repaired[0].text == segments[0].text
    assert repaired[1].translated_text == segments[1].translated_text
    assert repaired[0].subtitle_id == "S0001"
    assert repaired[1].subtitle_id == "S0002"
    assert repaired[0].stable_word_end_ms == 1000
    assert repaired[1].stable_word_start_ms == 1100
    assert editor._display_coverage_repairs[0]["code"] == "continuous_source_coverage_bridge"


def test_final_display_coverage_does_not_bridge_long_gap():
    editor = _editor()
    source = [ASRDataSeg("Continuous source speech.", 0, 4000)]
    segments = [
        _coverage_segment("First subtitle.", 0, 1000, "S0001", 0, 1000),
        _coverage_segment("Second subtitle.", 2200, 4000, "S0002", 1050, 4000),
    ]

    repaired = editor._reconcile_final_display_coverage(segments, source)

    assert [(item.start_time, item.end_time) for item in repaired] == [(0, 1000), (2200, 4000)]
    assert editor._display_coverage_repairs == []
    assert editor._display_coverage_unresolved[0]["reason"] == "gap_exceeds_auto_repair_limit"


def test_final_display_coverage_preserves_real_word_pause():
    editor = _editor()
    source = [ASRDataSeg("Source segment with a pause.", 0, 3000)]
    segments = [
        _coverage_segment("First subtitle.", 0, 1000, "S0001", 0, 1000),
        _coverage_segment("Second subtitle.", 1500, 3000, "S0002", 1600, 3000),
    ]

    repaired = editor._reconcile_final_display_coverage(segments, source)

    assert [(item.start_time, item.end_time) for item in repaired] == [(0, 1000), (1500, 3000)]
    assert editor._display_coverage_repairs == []
    assert editor._display_coverage_unresolved[0]["reason"] == "frozen_word_pause_exceeds_limit"


def test_final_time_alignment_coverage_bridge_runs_with_preserved_alignment_timing():
    editor = _editor()
    source = ASRDataSeg("Continuous source speech.", 0, 3000)
    editor._active_source_segments_by_id = {1: source}
    editor._last_semantic_groups = []
    editor._last_subtitle_items = []
    editor._compress_fast_chinese_segments = lambda segments, **kwargs: list(segments)
    editor._align_segment_translation_punctuation = lambda segments: list(segments)
    editor._report_subtitle_coverage_gaps = lambda *args, **kwargs: None
    editor._write_stable_pipeline_artifacts = lambda **kwargs: None
    asr_data = ASRData(
        [
            _coverage_segment("First subtitle.", 0, 1000, "S0001", 0, 1000),
            _coverage_segment("Second subtitle.", 1600, 3000, "S0002", 1100, 3000),
        ]
    )

    repaired = editor.repair_after_final_time_alignment(asr_data, preserve_aligned_timing=True)

    assert [(item.start_time, item.end_time) for item in repaired.segments] == [(0, 1300), (1300, 3000)]
    assert [item.subtitle_id for item in repaired.segments] == ["S0001", "S0002"]


def test_chinese_reading_speed_error_is_reported_but_not_blocking():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "This is short.",
            0,
            1500,
            "这条中文字幕明显太长观众基本没有办法在一秒内读完",
        )
    ]

    editor._report_subtitle_coverage_gaps(segments, segments)

    assert editor.last_validation_summary["status"] == "ERROR"
    assert not editor.has_blocking_validation_errors()
    assert any(
        issue["code"] == "reading_speed_error"
        for issue in editor.last_validation_summary["errors"]
    )


def test_validation_report_adds_actionable_review_tiers_without_changing_status():
    editor = _editor()
    editor._translation_structure_errors = [
        {
            "code": "final_translation_id_mismatch",
            "message": "final id mismatch",
            "missing_subtitle_ids": ["S0002"],
        }
    ]
    health = {
        "overlong_english": [],
        "bad_cuts": [],
        "translationese": [],
        "reading_speed_errors": [
            {
                "subtitle_id": "S0001",
                "chars_per_second": 18.5,
                "text": "too fast",
            }
        ],
        "reading_speed_warnings": [],
        "duration_errors": [],
        "duration_warnings": [],
        "duplicate_chinese": [],
        "asr_suspicious": [],
        "discourse_marker_orphans": [],
        "syntax_boundary_audit": [],
        "chinese_semantic_group_warnings": [],
        "chinese_semantic_group_info": [],
    }

    summary = editor._validation_summary([], [], health, [ASRDataSeg("Hello.", 0, 1000, "Ni hao.")])
    review_items = summary["review"]["items"]

    assert summary["status"] == "ERROR"
    assert any(item["code"] == "final_translation_id_mismatch" for item in summary["errors"])
    assert any(
        item["code"] == "final_translation_id_mismatch"
        and item["severity"] == "BLOCKER"
        and item["affected_subtitle_ids"] == ["S0002"]
        for item in review_items
    )
    assert any(
        item["code"] == "reading_speed_error"
        and item["severity"] == "REVIEW"
        and item["affected_subtitle_ids"] == ["S0001"]
        for item in review_items
    )
    assert any(item["code"] == "subtitle_stats" and item["severity"] == "INFO" for item in review_items)
    assert summary["review"]["summary"]["blocker_count"] >= 1
    assert summary["review"]["summary"]["review_count"] >= 1


def test_validation_review_includes_allocation_unresolved_without_old_error_mutation():
    editor = _editor()
    editor._last_allocation_unresolved = [
        {
            "semantic_group_id": "G0007",
            "reason": "retry_quality_failed",
            "issue_codes": ["number_allocation_mismatch"],
            "allocation": {"S0010": "A", "S0011": "B"},
        }
    ]
    health = {
        "overlong_english": [],
        "bad_cuts": [],
        "translationese": [],
        "reading_speed_errors": [],
        "reading_speed_warnings": [],
        "duration_errors": [],
        "duration_warnings": [],
        "duplicate_chinese": [],
        "asr_suspicious": [],
        "discourse_marker_orphans": [],
        "syntax_boundary_audit": [],
        "chinese_semantic_group_warnings": [],
        "chinese_semantic_group_info": [],
    }

    summary = editor._validation_summary([], [], health, [ASRDataSeg("Hello.", 0, 1000, "Ni hao.")])

    assert summary["errors"] == []
    assert summary["status"] == "PASS"
    assert any(
        item["code"] == "allocation_quality_unresolved"
        and item["severity"] == "BLOCKER"
        and item["semantic_group_ids"] == ["G0007"]
        and item["affected_subtitle_ids"] == ["S0010", "S0011"]
        for item in summary["review"]["items"]
    )


def test_allocation_isolation_report_passes_when_only_chinese_changes():
    editor = _id_editor()
    editor._active_word_entries = [
        {"surface": "Alice", "token": "alice", "start_time": 0, "end_time": 500},
        {"surface": "arrived", "token": "arrived", "start_time": 500, "end_time": 1000},
    ]
    items = editor._assign_global_subtitle_ids(_id_items(1))
    items[0].original = "Alice arrived."
    items[0].translated = "old"
    items[0].word_start = 0
    items[0].word_end = 1
    groups = [_id_group(1, 0, items)]
    full_translations = {1: "Alice arrived."}
    source = [ASRDataSeg("Alice arrived.", 0, 1000)]

    before = editor._allocation_isolation_snapshot(
        stage="before_allocation",
        source_segments=source,
        items=items,
        semantic_groups=groups,
        full_translations=full_translations,
    )
    items[0].translated = "new"
    after = editor._allocation_isolation_snapshot(
        stage="before_export",
        source_segments=source,
        items=items,
        semantic_groups=groups,
        full_translations=full_translations,
        final_segments=[ASRDataSeg("Alice arrived.", 0, 1000, "new")],
    )
    report = editor._build_allocation_isolation_report(before, after)

    assert report["status"] == "passed"
    assert report["changed_keys"] == []


def test_allocation_isolation_report_fails_on_english_boundary_change():
    editor = _id_editor()
    editor._active_word_entries = [
        {"surface": "Alice", "token": "alice", "start_time": 0, "end_time": 500},
        {"surface": "arrived", "token": "arrived", "start_time": 500, "end_time": 1000},
    ]
    items = editor._assign_global_subtitle_ids(_id_items(1))
    items[0].original = "Alice arrived."
    items[0].word_start = 0
    items[0].word_end = 1
    groups = [_id_group(1, 0, items)]
    source = [ASRDataSeg("Alice arrived.", 0, 1000)]
    before = editor._allocation_isolation_snapshot(
        stage="before_allocation",
        source_segments=source,
        items=items,
        semantic_groups=groups,
        full_translations={1: "Alice arrived."},
    )

    changed_items = list(items)
    changed_items[0] = ScreenSubtitleItem(
        source_ids=items[0].source_ids,
        original="Alice arrived today.",
        translated=items[0].translated,
        word_start=items[0].word_start,
        word_end=items[0].word_end,
        subtitle_id=items[0].subtitle_id,
    )
    changed_groups = [_id_group(1, 0, changed_items)]
    after = editor._allocation_isolation_snapshot(
        stage="before_export",
        source_segments=source,
        items=changed_items,
        semantic_groups=changed_groups,
        full_translations={1: "Alice arrived."},
    )
    report = editor._build_allocation_isolation_report(before, after)

    assert report["status"] == "allocation_isolation_failed"
    assert "english_text_hash" in report["changed_keys"]
    assert report["first_differences"]["english_text_hash"]["index"] == 1


def test_duplicate_chinese_is_warning_not_blocking():
    editor = _editor()
    segments = [
        ASRDataSeg("This is one point.", 0, 2500, "这是同一个观点"),
        ASRDataSeg("This is another point.", 2600, 5100, "这是同一个观点"),
    ]

    editor._report_subtitle_coverage_gaps(segments, segments)

    assert editor.last_validation_summary["status"] == "WARNING"
    assert not editor.has_blocking_validation_errors()
    assert any(
        issue["code"] == "duplicate_chinese"
        for issue in editor.last_validation_summary["warnings"]
    )


def test_overlong_english_segment_is_locally_split_without_llm():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "Which explains why even graduates with degrees in IT services are struggling right now in many markets today.",
            0,
            4500,
            "这也解释了为什么即使是IT服务专业的毕业生现在也举步维艰。",
        )
    ]

    repaired = editor._repair_overlong_english_segments_local(segments)

    assert len(repaired) == 2
    assert " ".join(seg.text for seg in repaired) == segments[0].text
    assert all(editor._word_count(seg.text) <= 14 for seg in repaired)
    assert repaired[0].start_time == 0
    assert repaired[-1].end_time == 4500


def test_audit_parser_does_not_count_chinese_line_with_it_as_english():
    english, chinese = split_bilingual_body(
        [
            "Which explains why even graduates with degrees in IT services are struggling right now.",
            "这也解释了为什么即使是IT服务专业的毕业生现在也举步维艰。",
        ]
    )

    assert count_words(english) == 14
    assert chinese.startswith("这也解释了")


def test_888_chinese_speed_compression_rejects_dangling_fragment():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "And if we connect this to the bigger picture,",
            358620,
            360260,
            "\u800c\u5982\u679c\u6211\u4eec\u628a\u8fd9\u4e2a\u8bdd\u9898\u8054\u7cfb\u5230\u66f4\u5b8f\u89c2\u7684\u5c42\u9762\uff0c",
        ),
        ASRDataSeg(
            "it raises a huge existential question for the entire corporate world.",
            360260,
            364000,
            "\u5c31\u5f15\u51fa\u4e86\u4e00\u4e2a\u5173\u4e4e\u6574\u4e2a\u4f01\u4e1a\u754c\u7684\u5de8\u5927\u751f\u5b58\u6027\u8d28\u7591\u3002",
        ),
        ASRDataSeg("What question?", 364000, 365200, "\u4ec0\u4e48\u8d28\u7591\uff1f"),
    ]

    assert not editor._is_valid_chinese_compression(
        "\u800c\u82e5\u8054\u7cfb\u66f4\u5b8f\u89c2\u5c42\u9762\uff0c",
        segments[0],
        segments,
        0,
    )
    assert editor._is_valid_chinese_compression(
        "\u518d\u4ece\u5b8f\u89c2\u5c42\u9762\u6765\u770b\uff0c",
        segments[0],
        segments,
        0,
    )


def test_888_chinese_speed_compression_uses_semantic_group_context():
    editor = _editor()
    editor._last_semantic_full_translations = {
        1: "\u518d\u4ece\u5b8f\u89c2\u5c42\u9762\u6765\u770b\uff0c\u6574\u4e2a\u4f01\u4e1a\u754c\u90fd\u9762\u4e34\u4e00\u4e2a\u751f\u6b7b\u6538\u5173\u7684\u95ee\u9898\u3002"
    }
    items = [
        ScreenSubtitleItem([1], "And if we connect this to the bigger picture,", "\u800c\u5982\u679c\u6211\u4eec\u628a\u8fd9\u4e2a\u8bdd\u9898\u8054\u7cfb\u5230\u66f4\u5b8f\u89c2\u7684\u5c42\u9762\uff0c", 0, 8),
        ScreenSubtitleItem([1], "it raises a huge existential question for the entire corporate world.", "\u5c31\u5f15\u51fa\u4e86\u4e00\u4e2a\u5173\u4e4e\u6574\u4e2a\u4f01\u4e1a\u754c\u7684\u5de8\u5927\u751f\u5b58\u6027\u8d28\u7591\u3002", 9, 18),
        ScreenSubtitleItem([1], "What question?", "\u4ec0\u4e48\u8d28\u7591\uff1f", 19, 20),
    ]
    segments = [
        ASRDataSeg(items[0].original, 358620, 360260, items[0].translated),
        ASRDataSeg(items[1].original, 360260, 364000, items[1].translated),
        ASRDataSeg(items[2].original, 364000, 365200, items[2].translated),
    ]
    context = editor._semantic_context_for_segment_index(
        0,
        segments,
        semantic_groups=[{"id": 1, "start_index": 0, "items": items}],
        subtitle_items=items,
    )

    assert context["full_translation"] == "\u518d\u4ece\u5b8f\u89c2\u5c42\u9762\u6765\u770b\uff0c\u6574\u4e2a\u4f01\u4e1a\u754c\u90fd\u9762\u4e34\u4e00\u4e2a\u751f\u6b7b\u6538\u5173\u7684\u95ee\u9898\u3002"
    assert len(context["parts"]) == 3
    assert context["parts"][1]["english"].startswith("it raises")


def test_000_group_validation_rejects_lost_ponder_action():
    editor = _editor()
    editor._last_semantic_full_translations = {
        1: "\u8fd9\u662f\u4e2a\u503c\u5f97\u601d\u8003\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u8def\u8fc7\u7a7a\u7f6e\u653f\u5e9c\u5927\u697c\u65f6\uff0c\u4e0d\u59a8\u60f3\u60f3\u8fd9\u4e2a\u95ee\u9898\u3002"
    }
    items = [
        ScreenSubtitleItem([1], "It's a good question to ponder next time you", "\u8fd9\u662f\u4e00\u4e2a\u5f88\u597d\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u4f60", 0, 8),
        ScreenSubtitleItem([1], "pass an empty government building.", "\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c\u65f6\u53ef\u4ee5\u601d\u8003\u4e00\u4e0b\u3002", 9, 13),
    ]
    segments = [
        ASRDataSeg(items[0].original, 264000, 266420, items[0].translated),
        ASRDataSeg(items[1].original, 266420, 267880, items[1].translated),
    ]
    context = editor._semantic_context_for_segment_index(
        1,
        segments,
        semantic_groups=[{"id": 1, "start_index": 0, "items": items}],
        subtitle_items=items,
    )

    assert not editor._is_valid_group_chinese_allocation(
        {1: "\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c"},
        segments,
        context,
    )
    assert editor._is_valid_group_chinese_allocation(
        {
            0: "\u8fd9\u662f\u4e2a\u503c\u5f97\u601d\u8003\u7684\u95ee\u9898\u3002",
            1: "\u4e0b\u6b21\u8def\u8fc7\u7a7a\u7f6e\u653f\u5e9c\u5927\u697c\u65f6\u60f3\u60f3\u3002",
        },
        segments,
        context,
    )


def test_444_independent_syntax_boundary_audit_catches_bad_cuts():
    editor = _editor()
    bad_boundaries = [
        ("shows we're", "rapidly losing"),
        ("sulfur dioxide into", "the air"),
        ("forces", "a really uncomfortable look"),
        ("hunkering", "down"),
        ("the absolute", "extreme edge"),
        ("Stardust Solutions", "are trying"),
        ("we can alter", "the atmosphere"),
        ("be forced", "to put"),
    ]

    for left, right in bad_boundaries:
        assert editor._syntax_boundary_reasons(left, right), (left, right)


def test_syntax_boundary_audit_ignores_safe_short_dialogue():
    editor = _editor()

    assert not editor._syntax_boundary_reasons("What question?", "Exactly.")
    assert not editor._syntax_boundary_reasons("Right.", "Okay, let's unpack this.")
    assert not _syntax_boundary_reasons("pump water in.", "But the next part matters.")
    assert not _syntax_boundary_reasons("bringing in.", "Wow, that is a lot.")
    assert not _syntax_boundary_reasons("much further than that.", "What do you mean?")


def test_syntax_boundary_audit_keeps_confirmed_bad_cuts():
    confirmed = [
        ("cooling machinery's", "efficiency"),
        ("the Fed's", "massive footprint"),
        ("Rajan's", "rather provocative idea"),
        ("they took", "this low-lying"),
        ("state assets across", "the 10 most active provinces"),
        ("A 56 year-old man is weaving a loaded", "motorized scooter"),
        ("motorized scooter through the dense", "chaotic traffic"),
        ("we really have to look", "at the mechanics"),
    ]

    for left, right in confirmed:
        assert _syntax_boundary_reasons(left, right), (left, right)


def test_chinese_semantic_group_audit_warns_on_lost_core_action():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "That is a very good question to ponder next time you",
            263940,
            266420,
            "\u8fd9\u662f\u4e00\u4e2a\u5f88\u597d\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u4f60",
        ),
        ASRDataSeg(
            "pass an empty government building.",
            266420,
            267880,
            "\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c",
        ),
    ]
    english = " ".join(seg.text for seg in segments)
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(
            1,
            ["S0001", "S0002"],
            english,
            "\u8fd9\u662f\u4e00\u4e2a\u503c\u5f97\u601d\u8003\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u4f60\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c\u65f6\u53ef\u4ee5\u601d\u8003\u4e00\u4e0b\u3002",
        )
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0001": "G0001", "S0002": "G0001"}

    issues = editor._chinese_semantic_group_audit_issues(segments)

    assert issues
    assert "semantic_loss" in issues[0]["reason"]


def test_chinese_semantic_audit_skips_semantic_loss_when_mapping_invalid():
    editor = _editor()
    segments = [
        ASRDataSeg("Bouncing the sunlight away.", 1000, 2500, "\u628a\u9633\u5149\u53cd\u5c04\u56de\u53bb\u3002")
    ]
    editor._last_semantic_group_audit_contexts = {
        "G0002": _semantic_context(2, ["S0002"], "Yeah.", "\u662f\u7684\u3002"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0002": "G0002"}

    issues = editor._chinese_semantic_group_audit_issues(segments, "WARNING")

    assert not [issue for issue in issues if "semantic_loss" in issue.get("reason", "")]


def test_chinese_semantic_audit_ignores_normal_short_responses():
    editor = _editor()
    samples = [
        ("Good question.", "问得好。"),
        ("Oh, yeah.", "哦，是的。"),
        ("In a way, yeah.", "在某种程度上，是的。"),
    ]
    for index, (english, chinese) in enumerate(samples, 1):
        subtitle_id = f"S{index:04d}"
        group_id = f"G{index:04d}"
        editor._last_semantic_group_audit_contexts = {
            group_id: _semantic_context(index, [subtitle_id], english, chinese)
        }
        editor._last_semantic_group_id_by_subtitle_id = {subtitle_id: group_id}
        segment = ASRDataSeg(english, index * 1000, index * 1000 + 800, chinese)
        segment.subtitle_id = subtitle_id

        issues = editor._chinese_semantic_group_audit_issues([segment], "WARNING")

        assert not issues


def test_semantic_audit_context_requires_id_signature_and_expected_ids():
    editor = _editor()
    context = _semantic_context(24, ["S0101", "S0102"], "Meta, the American tech giant.", "甲")
    editor._last_semantic_group_audit_contexts = {"G0024": context}
    editor._last_semantic_group_id_by_subtitle_id = {
        "S0101": "G0024",
        "S0102": "G0024",
        "S9999": "G0099",
    }

    matched = editor._semantic_audit_context_for_group(
        "Meta, the American tech giant.",
        ["S0101", "S0102"],
    )
    assert matched["mapping_valid"] is True
    assert matched["semantic_group_id"] == "G0024"

    mismatch = editor._semantic_audit_context_for_group(
        "Meta, the American tech giant.",
        ["S0101", "S9999"],
    )
    assert mismatch["mapping_valid"] is False


def test_semantic_audit_mapping_does_not_shift_when_audit_groups_exceed_generation_count():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(1, ["S0001"], "Alpha one.", "甲一"),
        "G0002": _semantic_context(2, ["S0002"], "Bravo two.", "乙二"),
        "G0003": _semantic_context(3, ["S0003"], "Charlie three.", "丙三"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {
        "S0001": "G0001",
        "S0002": "G0002",
        "S0003": "G0003",
    }
    checks = [
        editor._semantic_audit_context_for_group("Alpha one.", ["S0001"]),
        editor._semantic_audit_context_for_group("Exactly.", ["S9998"]),
        editor._semantic_audit_context_for_group("Bravo two.", ["S0002"]),
        editor._semantic_audit_context_for_group("Charlie three.", ["S0003"]),
        editor._semantic_audit_context_for_group("Right.", ["S9999"]),
    ]

    assert [checks[index]["semantic_group_id"] for index in (0, 2, 3)] == ["G0001", "G0002", "G0003"]
    assert [checks[index]["mapping_valid"] for index in (0, 2, 3)] == [True, True, True]
    assert checks[1]["mapping_valid"] is False
    assert checks[4]["mapping_valid"] is False


def test_semantic_audit_mapping_does_not_shift_when_audit_groups_drop_generation_count():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(1, ["S0001"], "Alpha one.", "甲一"),
        "G0002": _semantic_context(2, ["S0002"], "Bravo two.", "乙二"),
        "G0003": _semantic_context(3, ["S0003"], "Charlie three.", "丙三"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {
        "S0001": "G0001",
        "S0002": "G0002",
        "S0003": "G0003",
    }
    checks = [
        editor._semantic_audit_context_for_group("Alpha one. Bravo two.", ["S0001", "S0002"]),
        editor._semantic_audit_context_for_group("Charlie three.", ["S0003"]),
    ]

    assert checks[0]["mapping_valid"] is False
    assert checks[1]["mapping_valid"] is True
    assert checks[1]["semantic_group_id"] == "G0003"


def test_repeated_short_dialogue_does_not_map_to_wrong_semantic_group():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0024": _semantic_context(24, ["S0247"], "Exactly.", "完全正确。"),
        "G0025": _semantic_context(25, ["S0248"], "Right.", "对。"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0247": "G0024", "S0248": "G0025"}
    context = editor._semantic_audit_context_for_group("Exactly.", ["S9999"])
    assert context["mapping_valid"] is False
    assert context.get("semantic_group_id", "") == ""


def test_missing_semantic_group_id_only_invalidates_that_group():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(1, ["S0001"], "Alpha one.", "甲一"),
        "G0003": _semantic_context(3, ["S0003"], "Charlie three.", "丙三"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {
        "S0001": "G0001",
        "S0003": "G0003",
    }
    groups = [("Alpha one.", ["S0001"]), ("Bravo two.", ["S0002"]), ("Charlie three.", ["S0003"])]
    results = [editor._semantic_audit_context_for_group(english, ids) for english, ids in groups]
    assert results[0]["mapping_valid"] is True
    assert results[1]["mapping_valid"] is False
    assert results[2]["mapping_valid"] is True
    assert results[2]["semantic_group_id"] == "G0003"


def test_identical_english_but_different_subtitle_ids_do_not_match():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0010": _semantic_context(10, ["S0101"], "Right.", "对。"),
        "G0011": _semantic_context(11, ["S0102"], "Right.", "没错。"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0101": "G0010", "S0102": "G0011"}
    matched = editor._semantic_audit_context_for_group("Right.", ["S0102"])
    assert matched["semantic_group_id"] == "G0011"
    mismatch = editor._semantic_audit_context_for_group("Right.", ["S0101", "S0102"])
    assert mismatch["mapping_valid"] is False


def test_g0248_full_translation_can_be_retraced_from_generated_context():
    editor = _editor()
    context = _semantic_context(
        248,
        ["S0391"],
        "All of it.",
        "所有的。"
    )
    editor._last_semantic_group_audit_contexts = {"G0248": context}
    editor._last_semantic_group_id_by_subtitle_id = {"S0391": "G0248"}
    matched = editor._semantic_audit_context_for_group("All of it.", ["S0391"])
    assert matched["semantic_group_id"] == "G0248"
    assert matched["full_translation"] == "所有的。"


def test_validation_report_full_translation_uses_single_stage_raw_records_for_all_valid_groups():
    editor = _id_editor()
    editor.model = "unit-test"
    editor.timeout = 1
    items = editor._assign_global_subtitle_ids(_id_items(5, translated="old-S{index:04d}"))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 6)]
    stale_full_translations = {
        index: f"stale-full-G{index:04d}"
        for index in range(1, 6)
    }
    editor._last_semantic_full_translations = dict(stale_full_translations)
    editor._last_semantic_group_audit_contexts = editor._semantic_group_audit_contexts(
        groups,
        stale_full_translations,
    )
    raw_groups = [
        {
            "id": index,
            "full_translation": f"raw-full-G{index:04d}",
            "part_translations": [
                {"subtitle_id": f"S{index:04d}", "zh": f"zh-S{index:04d}"}
            ],
        }
        for index in (3, 1, 5, 2, 4)
    ]
    editor.cache_manager = _StaticCache({"groups": raw_groups})

    applied = editor._translate_semantic_subtitle_groups_single_stage(items, groups)
    raw_by_semantic_group_id = {
        f"G{int(group['id']):04d}": group["full_translation"]
        for group in raw_groups
    }
    segments = []
    for index, item in enumerate(applied, 1):
        segment = ASRDataSeg(item.original, index * 1000, index * 1000 + 800, item.translated)
        segment.subtitle_id = item.subtitle_id
        segments.append(segment)

    def forced_findings(english, chinese, parts, full_translation="", mapping_valid=False):
        if not mapping_valid:
            return []
        return [
            {
                "code": "semantic_loss",
                "message": "forced semantic issue",
                "confidence_score": 0.9,
            }
        ]

    with patch.object(
        editor,
        "_semantic_segment_groups",
        return_value=[(0, 1), (0, 2), (1, 2), (2, 3), (3, 4), (4, 5)],
    ), patch.object(editor, "_chinese_group_quality_findings", side_effect=forced_findings):
        issues = editor._chinese_semantic_group_audit_issues(segments, "WARNING")

    valid_issues = [issue for issue in issues if issue.get("mapping_valid")]
    assert len(valid_issues) == 5
    for issue in valid_issues:
        semantic_group_id = issue["semantic_group_id"]
        assert issue["full_translation"] == raw_by_semantic_group_id[semantic_group_id]
        assert not issue["full_translation"].startswith("stale-full")
    assert any(not issue.get("mapping_valid") for issue in issues)


def test_mapping_failure_does_not_emit_full_translation_dependent_false_positive():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(1, ["S0001"], "Alpha one.", "甲一"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0001": "G0001"}
    issues = editor._chinese_semantic_group_audit_issues(
        [ASRDataSeg("Unmapped group.", 0, 1000, "孤立中文")],
        "WARNING",
    )
    assert all("semantic_loss" not in issue.get("reason", "") for issue in issues)


def test_command_chinese_audit_catches_confirmed_bad_groups():
    cues = [
        CaptionCue(106, 1, 2, "which leaves you,", "\u8fd9\u8ba9\u4f60\uff0c", ()),
        CaptionCue(
            107,
            2,
            3,
            "the listener, with a really unsettling thought to chew on long after",
            "\u542c\u4f17\uff0c\u7559\u4e0b\u4e86\u4e00\u4e2a\u975e\u5e38\u4ee4\u4eba\u4e0d\u5b89\u7684\u601d\u8003\uff0c\u4e45\u4e45",
            (),
        ),
        CaptionCue(108, 3, 4, "this deep dive is over.", "\u8fd9\u6b21\u6df1\u5ea6\u89e3\u6790\u7ed3\u675f\u540e\u3002", ()),
    ]

    issues = _chinese_semantic_group_issues(cues, "WARNING")

    assert issues
    assert "dangling_preposition" in issues[0]["rule_codes"]


def test_command_chinese_audit_ignores_normal_short_groups():
    cues = [
        CaptionCue(1, 1, 2, "Bouncing the sunlight away.", "\u628a\u9633\u5149\u53cd\u5c04\u56de\u53bb\u3002", ()),
        CaptionCue(2, 2, 3, "Oh, yeah.", "\u54e6\uff0c\u662f\u7684\u3002", ()),
    ]

    assert not _chinese_semantic_group_issues(cues, "WARNING")


def test_very_short_subtitle_has_dedicated_duration_error():
    editor = _editor()
    segments = [ASRDataSeg("Really?", 132200, 132300, "\u771f\u7684\u5417\uff1f")]

    issues = editor._subtitle_duration_issues(segments, "ERROR")

    assert issues
    assert issues[0]["code"] == "subtitle_duration_invalid"
    assert issues[0]["duration_ms"] == 100


def test_short_backchannel_duration_is_warning_not_error():
    editor = _editor()
    segments = [ASRDataSeg("Right.", 130140, 130360, "\u6ca1\u9519\u3002")]

    errors = editor._subtitle_duration_issues(segments, "ERROR")
    warnings = editor._subtitle_duration_issues(segments, "WARNING")

    assert not errors
    assert warnings
    assert warnings[0]["code"] == "subtitle_duration_too_short"
    assert warnings[0]["duration_ms"] == 220


def test_short_regular_sentence_duration_remains_error():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "This sentence is too long.",
            1000,
            1220,
            "\u8fd9\u53e5\u8bdd\u592a\u957f\u4e86\u3002",
        )
    ]

    issues = editor._subtitle_duration_issues(segments, "ERROR")

    assert issues
    assert issues[0]["code"] == "subtitle_duration_invalid"
    assert issues[0]["duration_ms"] == 220


def test_asr_suspicious_phrases_are_reported_without_fixing_text():
    editor = _editor()
    segments = [
        ASRDataSeg("That caught me total off guard.", 1000, 3000, "ok"),
        ASRDataSeg("Seeds away the mirror.", 4000, 6000, "ok"),
        ASRDataSeg("It is geographing arbitrage.", 7000, 9000, "ok"),
        ASRDataSeg("They need stronger safety nuts.", 10000, 12000, "ok"),
        ASRDataSeg("A state-of the-art system arrived.", 13000, 15000, "ok"),
    ]

    issues = editor._asr_suspicious_issues(segments)
    codes = {issue.get("rule_code") for issue in issues}

    assert "asr_ungrammatical_collocation" in codes
    assert "asr_semantic_nonsense" in codes
    assert "asr_hyphenation_suspicious" in codes


def test_asr_suspicious_article_context_misses_are_reported():
    editor = _editor()
    segments = [
        ASRDataSeg("And the invisible electric cess was still there?", 0, 1200, "ok"),
        ASRDataSeg("Only 10% of America respondents said yes.", 1300, 2600, "ok"),
        ASRDataSeg("Taylor Swift plans to legally adopt Kils surname.", 2700, 4200, "ok"),
    ]

    issues = editor._asr_suspicious_issues(segments)
    codes = {issue.get("rule_code") for issue in issues}

    assert "asr_semantic_nonsense" in codes
    assert "asr_adjective_form_suspicious" in codes
    assert "asr_name_suspicious" in codes


def test_abbreviation_name_boundary_is_syntax_warning():
    editor = _editor()

    assert "abbreviation_name_split" in editor._syntax_boundary_reasons("St.", "Gallen is a city.")
    assert "abbreviation_name_split" in _syntax_boundary_reasons("Dr.", "Smith explains it.")


def test_terminal_punctuation_wins_over_token_only_determiner_heuristic():
    words = "The team built a laboratory for this. They gathered 55 940 sentences.".split()
    editor = _marker_editor(words, max_words=16)
    this_index = words.index("this.")

    evaluation = editor._evaluate_stable_cut_boundary(this_index, this_index + 1)

    assert evaluation["legal"] is True
    assert evaluation["hard_issues"] == []
    assert evaluation["soft_issues"] == []
    assert not editor._is_unambiguous_sentence_terminal("Dr.", "Smith explains it.")


def test_caption_audit_uses_16_word_hard_limit():
    with tempfile.TemporaryDirectory() as temp_dir:
        srt = Path(temp_dir) / "soft-limit.srt"
        sixteen_words = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen."
        seventeen_words = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen."
        srt.write_text(
            "\n".join(
                [
                    "1",
                    "00:00:00,000 --> 00:00:04,000",
                    sixteen_words,
                    "十六词可以接受。",
                    "",
                    "2",
                    "00:00:04,000 --> 00:00:08,000",
                    seventeen_words,
                    "十七词超过硬上限。",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        report = audit_srt(srt)
    overlong = [issue for issue in report["errors"] if issue["code"] == "overlong_english"]

    assert len(overlong) == 1
    assert overlong[0]["index"] == 2
    assert overlong[0]["word_count"] == 17
    assert overlong[0]["hard_limit"] == 16


def test_caption_audit_accepts_allowed_plus_discourse_overflow():
    with tempfile.TemporaryDirectory() as temp_dir:
        srt = Path(temp_dir) / "plus-overflow.srt"
        srt.write_text(
            "\n".join(
                [
                    "1",
                    "00:00:00,000 --> 00:00:04,000",
                    "Plus, breaking away from corporate hubs kind of broke the social pressure to climb that traditional ladder.",
                    "此外，脱离企业中心也在一定程度上摆脱了传统晋升的社会压力。",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        report = audit_srt(srt)

    assert not [issue for issue in report["errors"] if issue["code"] == "overlong_english"]


def test_caption_audit_treats_borderline_chinese_speed_as_warning_not_blocker():
    with tempfile.TemporaryDirectory() as temp_dir:
        srt = Path(temp_dir) / "chinese-speed.srt"
        srt.write_text(
            "\n".join(
                [
                    "1",
                    "00:00:00,000 --> 00:00:01,340",
                    "I can see why you'd think that. I mean,",
                    "我理解你为什么这么想。我的意思是，",
                    "",
                    "2",
                    "00:00:02,000 --> 00:00:03,340",
                    "This is deliberately too dense.",
                    "这是一个故意设置得过于密集的中文字幕测试文本。",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        report = audit_srt(srt)

    speed_errors = [issue for issue in report["errors"] if issue["code"] == "chinese_speed_error"]
    speed_warnings = [issue for issue in report["warnings"] if issue["code"] == "chinese_speed_warning"]
    assert [issue["index"] for issue in speed_errors] == [2]
    assert [issue["index"] for issue in speed_warnings] == [1]


def test_caption_audit_keeps_numeric_percent_chinese_line():
    english, chinese = split_bilingual_body(["70%.", "70%。"])

    assert english == "70%."
    assert chinese == "70%。"


def test_large_number_anchor_variants_do_not_crash():
    variants = ScreenSubtitleEditor._chinese_number_anchor_variants("1000000000")

    assert variants


def test_concise_group_allocation_is_not_rejected_by_coverage_only():
    editor = _id_editor()
    entry = {
        "id": 96,
        "full_english": "So Beijing gets to look under the hood of Washington's best AI and vice versa.",
        "full_translation": "于是，北京可以了解华盛顿最优秀人工智能的内部情况，反之亦然。",
        "subtitle_parts": [
            {"subtitle_id": "S0152", "english": "So Beijing gets to look under the hood"},
            {"subtitle_id": "S0153", "english": "of Washington's best AI and vice versa."},
        ],
    }
    allocation = {
        "S0152": "于是，北京可窥华盛顿最优AI内部，",
        "S0153": "反之亦然。",
    }

    validation = editor._validate_group_chinese_allocation(entry, allocation)

    assert validation["valid"]
    assert "group_allocation_information_omission" not in validation["issue_codes"]

    stronger_compression = {
        "S0152": "于是，北京可窥探华盛顿顶尖AI内部",
        "S0153": "反之亦然。",
    }
    stronger_validation = editor._validate_group_chinese_allocation(
        entry, stronger_compression
    )

    assert stronger_validation["valid"]
    assert "group_allocation_information_omission" not in stronger_validation["issue_codes"]


def test_short_but_severe_chinese_speed_triggers_repair():
    editor = _id_editor()
    seg = ASRDataSeg(
        "simply can't patch?",
        0,
        1220,
        "无论如何也修补不了的漏洞，会发生什么？",
    )

    assert editor._is_severe_chinese_speed(seg)


def test_borderline_chinese_speed_does_not_trigger_render_blocker():
    editor = _id_editor()
    seg = ASRDataSeg(
        "I can see why you'd think that. I mean,",
        0,
        1340,
        "我理解你为什么这么想。我的意思是，",
    )

    # 15 Chinese characters / 1.34s = about 11.19 chars/s: review, not block.
    assert not editor._is_severe_chinese_speed(seg)


def test_short_subtitle_gets_minimum_display_duration_when_room_allows():
    segments = [
        ASRDataSeg("Exactly.", 18420, 18680, "ok"),
        ASRDataSeg("But what happens next?", 19560, 23280, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time - adjusted[0].start_time >= 800
    assert adjusted[0].end_time <= adjusted[1].start_time - 40


def test_short_backchannel_merges_with_following_segment():
    editor = _editor()
    segments = [
        ASRDataSeg("Exactly.", 37940, 38140, "ok"),
        ASRDataSeg("Okay, let's unpack this.", 38500, 40620, "ok"),
    ]

    merged = editor._merge_short_display_segments(segments)

    assert len(merged) == 1
    assert merged[0].text == "Exactly. Okay, let's unpack this."
    assert merged[0].start_time == 37940
    assert merged[0].end_time == 40620


def test_short_sentence_bridges_small_gap_before_next_subtitle():
    segments = [
        ASRDataSeg("It's wild.", 206140, 206660, "ok"),
        ASRDataSeg("Coming out for a second,", 208640, 212780, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time == adjusted[1].start_time - 40


def test_display_timing_bridges_regular_short_gap_before_next_subtitle():
    segments = [
        ASRDataSeg("That structural tightening is the key takeaway.", 1000, 4300, "ok"),
        ASRDataSeg("Better administration yields higher compliance.", 5020, 8200, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time == adjusted[1].start_time - 40
    assert adjusted[0].text == segments[0].text
    assert adjusted[1].start_time == segments[1].start_time


def test_display_timing_preserves_clear_long_pause():
    segments = [
        ASRDataSeg("That structural tightening is the key takeaway.", 1000, 4300, "ok"),
        ASRDataSeg("Better administration yields higher compliance.", 5600, 8200, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time == 4750
    assert adjusted[0].end_time < adjusted[1].start_time - 40
    assert adjusted[1].start_time == segments[1].start_time - 80


def test_standalone_discourse_marker_attaches_to_immediate_next_sentence():
    editor = _marker_editor(["I", "mean,", "this", "market", "changed."])
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 1
    assert merged[0].original == "I mean, this market changed."
    assert editor._discourse_marker_orphans == []


def test_plus_marker_keeps_a_complete_one_word_overflow_unit():
    words = "Plus, breaking away from corporate hubs kind of broke the social pressure to climb that traditional ladder.".split()
    editor = _marker_editor(words, max_words=16)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, len(words) - 1, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 1
    assert merged[0].original == " ".join(words)
    assert ScreenSubtitleEditor._word_count(merged[0].original) == 17
    assert editor._is_allowed_plus_discourse_overflow(merged[0].original, 17, 16)


def test_trailing_standalone_discourse_marker_attaches_to_previous_sentence():
    editor = _marker_editor(["this", "market", "changed,", "you", "know."])
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 1
    assert merged[0].original == "this market changed, you know."
    assert editor._discourse_marker_orphans == []


def test_standalone_discourse_marker_does_not_cross_long_pause():
    editor = _marker_editor(["You", "know,", "this", "market", "changed."])
    editor._active_word_entries[2]["start_time"] = 1500
    editor._active_word_entries[2]["end_time"] = 1620
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 2
    assert merged[0].original == "You know,"
    assert editor._discourse_marker_orphans
    assert editor._discourse_marker_orphans[0]["code"] == "discourse_marker_orphan"


def test_standalone_discourse_marker_does_not_cross_speaker_change():
    editor = _marker_editor(["I", "guess,", "this", "market", "changed."])
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 2
    assert merged[0].original == "I guess,"
    assert editor._discourse_marker_orphans


def test_overlong_discourse_marker_attachment_reselects_cutpoint():
    content_words = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
    ]
    words = ["Well,", "I", "mean,"] + content_words
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 18, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 2
    assert merged[0].original.startswith("Well, I mean, alpha")
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in merged)
    assert merged[1].original == "golf hotel india juliet kilo lima mike november oscar papa"
    assert all(editor._standalone_discourse_marker(item.original) == "" for item in merged)
    assert editor._discourse_marker_orphans == []


def test_discourse_marker_rebalance_does_not_leave_one_word_fragment():
    content_words = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "kilo",
        "lima",
        "mike",
    ]
    words = ["I", "mean,"] + content_words
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 14, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 2
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in merged)
    assert merged[0].original.startswith("I mean, alpha")
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_trailing_discourse_marker_is_not_left_at_subtitle_end():
    words = [
        "which",
        "is",
        "now,",
        "you",
        "know,",
        "a",
        "standard",
        "industry",
        "playbook.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 4, 1), _word_item(editor, 5, 8, 2)]

    rebalanced = editor._rebalance_edge_discourse_markers(items)

    assert len(rebalanced) == 2
    assert rebalanced[0].original == "which is now,"
    assert rebalanced[1].original == "you know, a standard industry playbook."
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in rebalanced)
    assert not editor._has_trailing_discourse_marker(rebalanced[0].original)


def test_discourse_marker_phrase_is_not_split_during_rebalance():
    words = [
        "which",
        "is",
        "now,",
        "you",
        "know,",
        "a",
        "standard",
        "industry",
        "playbook.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 4, 1), _word_item(editor, 5, 8, 2)]

    rebalanced = editor._rebalance_edge_discourse_markers(items)

    joined = " ".join(item.original for item in rebalanced)
    assert "you know" in joined.lower()
    assert all(not item.original.lower().endswith(" you") for item in rebalanced)
    assert all(not item.original.lower().startswith("know") for item in rebalanced)


def test_trailing_discourse_marker_rebalances_two_long_items_without_word_loss():
    words = [
        "this",
        "became",
        "the",
        "standard",
        "industry",
        "playbook,",
        "you",
        "know,",
        "because",
        "founders",
        "needed",
        "capital",
        "talent",
        "distribution",
        "and",
        "regulatory",
        "cover.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 7, 1), _word_item(editor, 8, 16, 2)]

    rebalanced = editor._rebalance_edge_discourse_markers(items)

    assert len(rebalanced) == 2
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in rebalanced)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in rebalanced)
    assert not editor._has_trailing_discourse_marker(rebalanced[0].original)
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in rebalanced)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_short_yeah_rebalances_with_long_following_sentence():
    words = [
        "Yeah,",
        "they",
        "were",
        "clawing",
        "their",
        "way",
        "out",
        "of",
        "extreme",
        "poverty",
        "during",
        "China's",
        "early",
        "economic",
        "transition.",
    ]
    editor = _marker_editor(words, max_words=14)
    editor._active_word_entries[0]["end_time"] = 140
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 14, 2)]

    merged = editor._merge_short_display_segments(items)

    assert len(merged) == 2
    assert merged[0].original.startswith("Yeah, they were clawing")
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in merged)
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_short_though_attaches_to_following_sentence():
    editor = _marker_editor(["Though,", "it", "was", "different."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 3, 2)]

    merged = editor._merge_short_display_segments(items)

    assert len(merged) == 1
    assert merged[0].original == "Though, it was different."


def test_short_though_rebalances_without_leaving_orphan():
    words = [
        "Though,",
        "this",
        "generation",
        "still",
        "built",
        "durable",
        "companies",
        "through",
        "exports",
        "software",
        "capital",
        "discipline",
        "and",
        "constant",
        "pressure.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 14, 2)]

    merged = editor._merge_short_display_segments(items)

    assert len(merged) == 2
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert all(item.original != "Though," for item in merged)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in merged)
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_discourse_marker_ids_are_assigned_after_all_english_boundaries_are_fixed():
    editor = _marker_editor(["I", "mean,", "this", "market", "changed."])
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]
    assert all(item.subtitle_id is None for item in items)

    merged = editor._merge_standalone_discourse_markers(items)
    merged = editor._merge_short_display_segments(merged)
    assigned = editor._assign_global_subtitle_ids(merged)

    assert len(assigned) == 1
    assert assigned[0].subtitle_id == "S0001"
    assert assigned[0].original == "I mean, this market changed."


def test_discourse_marker_pre_id_pipeline_keeps_400_plus_english_chinese_id_sets_equal():
    words = [f"word{i}" for i in range(1, 406)]
    editor = _marker_editor(words, max_words=14)
    items = [
        ScreenSubtitleItem(
            source_ids=[index],
            original=f"English {index}.",
            translated=f"zh-S{index:04d}",
            word_start=index - 1,
            word_end=index - 1,
        )
        for index in range(1, 406)
    ]

    merged = editor._merge_standalone_discourse_markers(items)
    merged = editor._merge_short_display_segments(merged)
    assigned = editor._assign_global_subtitle_ids(merged)
    editor._validate_final_item_translation_ids(assigned)

    english_ids = [item.subtitle_id for item in assigned]
    chinese_ids = [item.subtitle_id for item in assigned if item.translated]
    assert len(assigned) == 405
    assert english_ids == [f"S{index:04d}" for index in range(1, 406)]
    assert english_ids == chinese_ids
    assert editor._translation_structure_errors == []


def test_discourse_marker_pre_id_pipeline_keeps_421_item_structure_errors_zero():
    words = [f"word{index}" for index in range(1, 422)]
    editor = _marker_editor(words, max_words=14)
    items = [
        ScreenSubtitleItem(
            source_ids=[index],
            original=f"English {index}.",
            translated=f"zh-S{index:04d}",
            word_start=index - 1,
            word_end=index - 1,
        )
        for index in range(1, 422)
    ]

    items = editor._merge_standalone_discourse_markers(items)
    items = editor._merge_short_display_segments(items)
    items = editor._rebalance_edge_discourse_markers(items)
    assigned = editor._assign_global_subtitle_ids(items)
    editor._validate_final_item_translation_ids(assigned)

    assert len(assigned) == 421
    assert len({item.subtitle_id for item in assigned}) == 421
    assert editor._translation_structure_errors == []


def test_balanced_split_does_not_create_preposition_object_boundary():
    words = [
        "Yeah,",
        "so",
        "Todd",
        "is",
        "the",
        "founder",
        "of",
        "a",
        "non-profit",
        "and",
        "the",
        "author",
        "of",
        "a",
        "book,",
        "which",
        "changed",
        "the",
        "field.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 18, 2)]

    merged = editor._merge_short_display_segments(items)

    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )
    for left, right in zip(merged, merged[1:]):
        assert "preposition_object_split" not in editor._evaluate_item_boundary(left, right)["hard_issues"]


def test_determiner_numeric_noun_boundary_is_hard_illegal():
    editor = _marker_editor(["those", "200", "economists", "signed", "the", "letter."])

    first = editor._evaluate_stable_cut_boundary(0, 1)
    second = editor._evaluate_stable_cut_boundary(1, 2)

    assert "determiner_numeric_noun_split" in first["hard_issues"]
    assert "determiner_numeric_noun_split" in second["hard_issues"]
    assert not first["legal"]
    assert not second["legal"]


def test_quantifier_phrase_boundary_is_hard_illegal():
    editor = _marker_editor(["a", "few", "thousand", "people", "arrived."])

    first = editor._evaluate_stable_cut_boundary(0, 1)
    second = editor._evaluate_stable_cut_boundary(1, 2)

    assert "quantifier_phrase_split" in first["hard_issues"]
    assert "quantifier_phrase_split" in second["hard_issues"]
    assert not first["legal"]
    assert not second["legal"]


def test_adverb_adjective_boundary_is_hard_illegal_without_pause():
    editor = _marker_editor(["a", "highly", "valuable", "company", "emerged."])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "adverb_adjective_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_short_verb_complement_boundary_is_hard_when_syntax_marks_it():
    editor = _marker_editor(["they", "made", "it", "quickly."])
    editor._record_syntax_hard_issue_for_indices([1, 2], "short_verb_complement_split")

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "short_verb_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_short_verb_possessive_complement_boundary_is_hard_when_syntax_marks_it():
    editor = _marker_editor(["he", "navigated", "his", "way", "carefully."])
    editor._record_syntax_hard_issue_for_indices([1, 2, 3], "short_verb_complement_split")

    first = editor._evaluate_stable_cut_boundary(1, 2)
    second = editor._evaluate_stable_cut_boundary(2, 3)

    assert "short_verb_complement_split" in first["hard_issues"]
    assert "short_verb_complement_split" in second["hard_issues"]
    assert not first["legal"]
    assert not second["legal"]


def test_parser_blocks_direct_verb_particle_boundary():
    editor = _marker_editor(
        ["AI", "is", "stepping", "in", "and", "permanently", "filling", "the", "gap."]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(2, 3)

    assert "verb_particle_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_compact_coordinated_subject_boundary():
    editor = _marker_editor(
        ["why", "you", "and", "so", "many", "others", "support", "this", "change."]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "coordinated_subject_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_short_dative_object_start_boundary():
    editor = _marker_editor(
        ["the", "company", "gives", "you", "a", "completely", "different", "lens."]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(3, 4)

    assert "short_verb_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_numeric_range_boundaries():
    editor = _marker_editor(
        ["the", "stock", "plummeted", "from", "36%", "to", "under", "10%", "in", "June."]
    )
    editor._prepare_syntax_cut_hints()

    for cut_after in (2, 3, 4, 5, 6):
        evaluation = editor._evaluate_stable_cut_boundary(cut_after, cut_after + 1)
        assert "numeric_range_split" in evaluation["hard_issues"], evaluation
        assert not evaluation["legal"]


def test_pre_id_candidate_gate_rejects_new_hard_syntax_boundary():
    editor = _marker_editor(["they", "made", "it", "to", "the", "top."], max_words=6)
    editor._prepare_syntax_cut_hints()
    old_items = [_word_item(editor, 0, 5)]
    candidate = [_word_item(editor, 0, 1), _word_item(editor, 2, 5)]

    decision = editor._can_apply_pre_id_repair_candidate(old_items, candidate)

    assert decision["accepted"] is False
    assert "short_verb_complement_split" in decision["hard_issues"]
    assert decision["old_word_range"] == decision["new_word_range"] == [0, 5]


def test_long_object_still_allows_legal_boundary():
    editor = _marker_editor(
        [
            "they",
            "built",
            "a",
            "large",
            "durable",
            "export",
            "business",
            "with",
            "capital",
            "partners",
            "over",
            "many",
            "years.",
        ]
    )

    evaluation = editor._evaluate_stable_cut_boundary(6, 7)

    assert evaluation["hard_issues"] == []
    assert evaluation["legal"]


def test_final_pre_id_repair_removes_known_hard_boundary():
    words = [
        "Todd",
        "is",
        "the",
        "founder",
        "of",
        "a",
        "non-profit",
        "and",
        "the",
        "author",
        "of",
        "a",
        "book",
        "about",
        "risk.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 4, 1), _word_item(editor, 5, 14, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in repaired)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in repaired)
    assert all(
        editor._evaluate_item_boundary(left, right)["legal"]
        for left, right in zip(repaired, repaired[1:])
    )
    assert editor._pre_id_boundary_repairs


def test_final_pre_id_keeps_discourse_marker_with_following_sentence_after_terminal_over():
    words = [
        "But", "the", "thing", "I", "keep", "coming", "back", "to", "is", "how",
        "fast", "this", "is", "evolving.", "I", "mean,", "the", "Delve", "era", "is",
        "over.", "Why", "does", "its", "style", "change", "so", "rapidly?",
    ]
    editor = _marker_editor(words, max_words=16)
    items = [
        _word_item(editor, 0, 13, 1),
        _word_item(editor, 14, 20, 2),
        _word_item(editor, 21, 27, 3),
    ]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]
    assert repaired[1].original == "I mean, the Delve era is over."
    assert not any(item.original.endswith("I mean,") for item in repaired)
    assert "preposition_object_split" not in editor._evaluate_item_boundary(
        repaired[1], repaired[2]
    )["hard_issues"]


def test_final_pre_id_rebalances_leading_nonfinite_dependent_prefix():
    words = (
        "Exactly. Plus, it doesn't naturally quote human experts unless forced to, "
        "so it doesn't need all those attributive commas and quotation marks either."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    items = [_word_item(editor, 0, 7, 1), _word_item(editor, 8, len(words) - 1, 2)]
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [
        "Exactly. Plus, it doesn't naturally quote human experts unless forced to,",
        "so it doesn't need all those attributive commas and quotation marks either.",
    ]
    assert [item.word_start for item in repaired] == [0, 11]
    assert [item.word_end for item in repaired] == [10, len(words) - 1]
    assert editor._pre_id_boundary_repairs[0]["repair_reason"] == (
        "leading_nonfinite_dependent_prefix_rebalanced"
    )
    assert editor._pre_id_boundary_repairs[0]["word_order_preserved"] is True
    assert editor._pre_id_boundary_repairs[0]["word_coverage_preserved"] is True
    segments = []
    for item in repaired:
        segment = ASRDataSeg(item.original, 0, 1000, "中文")
        segment.word_start = item.word_start
        segment.word_end = item.word_end
        segments.append(segment)
    assert editor._bad_cut_issues(segments) == []
    assert editor._syntax_boundary_audit_issues(segments) == []
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before


def test_final_pre_id_keeps_finite_conditional_introduction_in_its_own_cue():
    words = (
        "The speaker sets up an example if I normally say, uh, "
        "I'm going to eat a sandwich for lunch."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    left = _word_item(editor, 0, 5, 1)
    right = _word_item(editor, 6, len(words) - 1, 2)

    assert editor._leading_nonfinite_dependent_prefix_end(right) is None
    assert editor._rebalance_leading_nonfinite_dependent_prefixes([left, right]) == [left, right]


def test_leading_nonfinite_dependent_prefix_rebalance_respects_long_pause():
    words = (
        "Exactly. Plus, it doesn't naturally quote human experts unless forced to, "
        "so it doesn't need all those attributive commas and quotation marks either."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    for entry in editor._active_word_entries[8:]:
        entry["start_time"] += 600
        entry["end_time"] += 600
    items = [_word_item(editor, 0, 7, 1), _word_item(editor, 8, len(words) - 1, 2)]

    assert editor._rebalance_leading_nonfinite_dependent_prefixes(items) == items
    assert editor._pre_id_boundary_repairs == []


def test_leading_nonfinite_dependent_prefix_rebalance_respects_speaker_change():
    words = (
        "Exactly. Plus, it doesn't naturally quote human experts unless forced to, "
        "so it doesn't need all those attributive commas and quotation marks either."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 7, 1), _word_item(editor, 8, len(words) - 1, 2)]

    assert editor._rebalance_leading_nonfinite_dependent_prefixes(items) == items
    assert editor._pre_id_boundary_repairs == []


def test_final_pre_id_repair_does_not_cross_speaker_change():
    words = ["founder", "of", "a", "non-profit", "built", "trust."]
    editor = _marker_editor(words, max_words=14)
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]
    assert editor._pre_id_boundary_repairs[-1]["unresolved_hard_issue"] is True


def test_final_pre_id_rejects_noop_repartition_without_iteration_loop():
    editor = _marker_editor(["founder", "of", "a", "non-profit"], max_words=14)
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 3, 2)]
    evaluation = editor._evaluate_item_pair_for_final_boundary(items[0], items[1])
    assert not evaluation["legal"]

    with patch.object(
        editor,
        "_repartition_pre_id_window",
        return_value=(list(items), [{"cuts": [[1, 2]]}]),
    ):
        repaired = editor._repair_pre_id_boundary_window(items, 0, evaluation)

    assert repaired is None


def test_verb_directional_adverb_preposition_boundary_is_hard_when_syntax_marks_it():
    editor = _marker_editor(
        [
            "But",
            "the",
            "thing",
            "I",
            "keep",
            "coming",
            "back",
            "to",
            "is",
            "how",
            "fast",
            "this",
            "is",
            "evolving.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    verb_adverb = editor._evaluate_stable_cut_boundary(5, 6)
    adverb_preposition = editor._evaluate_stable_cut_boundary(6, 7)

    assert "verb_adverb_preposition_split" in verb_adverb["hard_issues"]
    assert "verb_adverb_preposition_split" in adverb_preposition["hard_issues"]
    assert not verb_adverb["legal"]
    assert not adverb_preposition["legal"]


def test_short_display_merge_keeps_original_when_no_safe_boundary_exists():
    words = ["Yeah,", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]
    editor = _marker_editor(words, max_words=4)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 7, 2)]

    with patch.object(editor, "_should_merge_short_display_item", return_value=True), patch.object(
        editor, "_balanced_two_item_split", return_value=[]
    ), patch.object(editor, "_safe_direct_short_item_merge", return_value=None):
        merged = editor._merge_short_display_segments(items)

    assert [item.original for item in merged] == [item.original for item in items]
    assert editor._pre_id_boundary_repairs[-1]["repair_reason"] == "short_display_merge_no_legal_boundary"


def test_final_pre_id_preserves_word_order_coverage_and_timestamps():
    words = [
        "This",
        "became",
        "a",
        "highly",
        "valuable",
        "business",
        "for",
        "the",
        "market",
        "leaders.",
    ]
    editor = _marker_editor(words, max_words=8)
    before_times = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]
    items = [_word_item(editor, 0, 3, 1), _word_item(editor, 4, 9, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in repaired)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == before_times
    assert repaired[0].subtitle_id is None


def test_boundary_snapshot_payload_records_pre_id_repairs():
    editor = _marker_editor(["founder", "of", "a", "non-profit"])
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 3, 2)]

    editor._validate_and_repair_final_pre_id_boundaries(items)
    payload = editor._boundary_snapshot_payload()

    assert "pre_id_boundary_repairs" in payload
    assert payload["pre_id_boundary_repairs"]


def test_subject_finite_verb_we_tend_is_hard_boundary():
    editor = _marker_editor(["We", "tend", "to", "view", "AI"])
    editor._record_syntax_hard_issue_for_indices([0, 1], "subject_finite_verb_split")

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_subject_finite_verb_they_needed_is_hard_boundary():
    editor = _marker_editor(["they", "needed", "to", "hire", "more", "clerks"])
    editor._record_syntax_hard_issue_for_indices([0, 1], "subject_finite_verb_split")

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_subject_finite_verb_ai_is_upending_is_hard_boundary():
    editor = _marker_editor(["when", "AI", "is", "completely", "upending"])
    editor._record_syntax_hard_issue_for_indices([1, 2], "subject_finite_verb_split")

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_modifier_head_actually_good_is_hard_boundary():
    editor = _marker_editor(["actually", "good", "at", "this"])
    editor._record_syntax_hard_issue_for_indices([0, 1], "modifier_head_split")

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "modifier_head_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_relative_clause_subject_verb_you_can_is_hard_boundary():
    editor = _marker_editor(["the", "good", "you", "can", "do"])
    editor._record_syntax_hard_issue_for_indices([2, 3], "relative_clause_subject_verb_split")

    evaluation = editor._evaluate_stable_cut_boundary(2, 3)

    assert "relative_clause_subject_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_pre_id_repairs_yeah_so_todd_subject_fragment():
    words = [
        "Yeah,",
        "so",
        "Todd",
        "is",
        "the",
        "founder",
        "of",
        "a",
        "non-profit",
        "and",
        "the",
        "author",
        "of",
        "a",
        "book,",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 14, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original.startswith("Yeah, so Todd is the founder")
    assert all(editor._evaluate_item_pair_for_final_boundary(left, right)["legal"] for left, right in zip(repaired, repaired[1:]))
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in repaired)


def test_final_pre_id_repairs_pronoun_only_fragment():
    editor = _marker_editor(["We", "tend", "to", "view", "AI", "carefully."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original.startswith("We tend")
    assert all(item.original != "We" for item in repaired)


def test_final_pre_id_attaches_standalone_so_to_next_sentence():
    editor = _marker_editor(["So,", "this", "matters", "now."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 3, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original == "So, this matters now."


def test_final_pre_id_keeps_independent_short_answers():
    editor = _marker_editor(["No.", "Really?", "This", "changed."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 1, 2), _word_item(editor, 2, 3, 3)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired][:2] == ["No.", "Really?"]


def test_weak_fragment_repair_does_not_cross_speaker_change():
    editor = _marker_editor(["We", "tend", "to", "view", "AI"])
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]


def test_weak_fragment_repair_does_not_cross_long_pause():
    editor = _marker_editor(["We", "tend", "to", "view", "AI"])
    editor._active_word_entries[1]["start_time"] = editor._active_word_entries[0]["end_time"] + 800
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]


def test_internal_transition_attaches_to_following_sentence():
    words = [
        "having",
        "80",
        "000",
        "Alternatively,",
        "if",
        "you",
        "want",
        "to",
        "work",
        "directly",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 9, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original == "having 80 000"
    assert repaired[1].original.startswith("Alternatively, if you want")
    assert all("Alternatively" not in item.original or item.original.startswith("Alternatively") for item in repaired)


def test_final_pre_id_repair_does_not_create_new_hard_issue():
    editor = _marker_editor(["We", "tend", "to", "view", "AI", "as", "important."])
    editor._record_syntax_hard_issue_for_indices([0, 1], "subject_finite_verb_split")
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 6, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert all(
        editor._evaluate_item_pair_for_final_boundary(left, right)["legal"]
        for left, right in zip(repaired, repaired[1:])
    )


def test_unresolved_weak_fragment_is_recorded_when_no_safe_repair():
    editor = _marker_editor(["We", "tend", "to", "view", "AI"], max_words=2)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]
    assert editor._pre_id_boundary_repairs[-1]["unresolved_hard_issue"] is True


def test_final_pre_id_second_phase_preserves_word_order_and_timestamps():
    words = ["We", "tend", "to", "view", "AI", "as", "important."]
    editor = _marker_editor(words, max_words=14)
    before_times = [(entry["start_time"], entry["end_time"]) for entry in editor._active_word_entries]
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 6, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in repaired)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )
    assert [(entry["start_time"], entry["end_time"]) for entry in editor._active_word_entries] == before_times
    assert all(item.subtitle_id is None for item in repaired)


def test_boundary_snapshots_record_stage_changes_before_subtitle_ids():
    editor = _marker_editor(["I", "mean,", "this", "market", "changed."])
    items = [
        ScreenSubtitleItem([1], "I mean,", "", word_start=0, word_end=1),
        ScreenSubtitleItem([1], "this market changed.", "", word_start=2, word_end=4),
    ]
    editor._capture_boundary_snapshot(
        "_stable_cut_items",
        items,
        changed_by="_stable_cut_items",
        previous_items=None,
    )
    merged = editor._merge_standalone_discourse_markers(items)
    editor._capture_boundary_snapshot(
        "_merge_standalone_discourse_markers",
        merged,
        changed_by="_merge_standalone_discourse_markers",
        previous_items=editor._boundary_snapshot_items("_stable_cut_items"),
    )

    payload = editor._boundary_snapshot_payload()

    assert [stage["stage"] for stage in payload["stages"]] == [
        "_stable_cut_items",
        "_merge_standalone_discourse_markers",
    ]
    assert payload["changes"][0]["change_type"] == "initial_dp_boundaries"
    assert any(
        change["created_or_modified_by"] == "_merge_standalone_discourse_markers"
        for change in payload["changes"][1]["changes"]
    )
    assert all(item.subtitle_id is None for item in merged)
    assert isinstance(payload["stages"][0]["boundaries"][0]["pause_ms"], int)
    assert "boundary_score" in payload["stages"][0]["boundaries"][0]


def test_final_stable_english_boundaries_do_not_change_for_video_layout():
    editor = _marker_editor(
        ["This", "is", "a", "long", "but", "grammatical", "English", "subtitle", "sentence."]
    )

    items = editor._finalize_stable_english_boundaries([])

    assert " ".join(item.original for item in items) == (
        "This is a long but grammatical English subtitle sentence."
    )
    assert all(item.subtitle_id is None for item in items)
    assert [stage["stage"] for stage in editor._boundary_snapshots] == [
        "_stable_cut_items",
        "_merge_standalone_discourse_markers",
        "_merge_short_display_segments",
        "_rebalance_edge_discourse_markers",
        "_validate_and_repair_final_pre_id_boundaries",
        "_apply_visual_reading_budget",
    ]


def test_final_gate_blocks_particle_preposition_complement_split():
    editor = _marker_editor(["straight", "into", "the", "absolute", "tundra"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "particle_or_preposition_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_keeps_preposition_object_boundary_illegal_after_long_pause():
    editor = _marker_editor(["optimism", "about", "finding", "a", "good", "job."])
    editor._active_word_entries[2]["start_time"] = editor._active_word_entries[1]["end_time"] + 500

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert evaluation["pause_ms"] == 500
    assert "preposition_object_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_stable_cut_keeps_preposition_object_phrase_together_in_long_sentence():
    text = (
        "I mean Gallup data shows optimism among 15 to 34 year-olds "
        "about finding a good job plummeted from 75% to just 43% recently."
    )

    parts = _split_text(text, max_words=16)

    assert all(not part.rstrip().lower().endswith("about") for part in parts)
    assert all(not part.lstrip().lower().startswith("finding") for part in parts)
    assert "about finding a good job" in " ".join(parts).lower()


def test_parser_confirmed_verb_object_boundary_stays_illegal_after_long_pause():
    editor = _marker_editor(
        ["they", "are", "setting", "up", "large", "new", "facilities."]
    )
    editor._prepare_syntax_cut_hints()
    editor._active_word_entries[4]["start_time"] = editor._active_word_entries[3]["end_time"] + 650

    evaluation = editor._evaluate_stable_cut_boundary(3, 4)

    assert evaluation["pause_ms"] == 650
    assert "short_verb_object_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_clause_introducer_from_ending_a_cue():
    editor = _marker_editor(
        [
            "the", "question", "has", "to", "do", "with", "how", "these",
            "systems", "are", "funded.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(6, 7)

    assert "clause_introducer_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_verb_from_its_preposition_complement():
    editor = _marker_editor(
        ["investors", "got", "liquidated", "in", "that", "doom", "loop."]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(2, 3)

    assert "verb_preposition_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_verb_from_numeric_result_expression():
    editor = _marker_editor(
        [
            "the", "stock", "kept", "crashing", "52%", "from", "its",
            "June", "peak.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    verb_to_result = editor._evaluate_stable_cut_boundary(3, 4)
    result_to_qualifier = editor._evaluate_stable_cut_boundary(4, 5)

    assert "verb_numeric_result_split" in verb_to_result["hard_issues"]
    assert "numeric_result_qualifier_split" in editor._syntax_hard_cut_issues[(4, 5)]
    assert not verb_to_result["legal"]
    assert not result_to_qualifier["legal"]


def test_parser_mapping_keeps_numeric_result_after_hyphenated_ledger_word():
    editor = _marker_editor(
        [
            "even", "a", "six-fold", "profit", "jump", "wasn't", "enough",
            "to", "stop", "the", "stock", "from", "crashing", "52%",
            "from", "its", "June", "peak.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(12, 13)

    assert "verb_numeric_result_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_stable_cut_prefers_normal_limit_when_a_legal_boundary_exists():
    words = [
        "One", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen", "twenty.",
    ]
    editor = _marker_editor(words, max_words=16)

    ranges = editor._stable_word_ranges_for_span((0, len(words) - 1))

    assert [end - start + 1 for start, end in ranges] == [16, 4]


def test_final_gate_soft_flags_heuristic_short_verb_object_split():
    editor = _marker_editor(["issued", "this", "stark", "public", "warning"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "short_verb_object_split" in evaluation["soft_issues"]
    assert evaluation["legal"]


def test_final_gate_blocks_auxiliary_predicate_split():
    editor = _marker_editor(["work", "doesn't", "have", "to", "be", "a", "tradeoff"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "auxiliary_predicate_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_soft_flags_heuristic_catenative_verb_complement_split():
    editor = _marker_editor(["helped", "expose", "the", "crimes"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "verb_complement_split" in evaluation["soft_issues"]
    assert evaluation["legal"]


def test_final_gate_blocks_numeric_unit_or_noun_split():
    editor = _marker_editor(["80", "000", "hours"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "numeric_unit_or_noun_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_numeric_sentence_boundary_is_not_repaired_as_a_numeric_phrase():
    editor = _marker_editor(["2019.", "Right."])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert evaluation["legal"]
    assert "numeric_unit_or_noun_split" not in evaluation["hard_issues"]


def test_final_gate_soft_flags_heuristic_compound_noun_split():
    editor = _marker_editor(["large-scale", "job", "displacement"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "compound_noun_split" in evaluation["soft_issues"]
    assert evaluation["legal"]


def test_final_gate_soft_flags_heuristic_modifier_noun_head_split():
    editor = _marker_editor(["the", "vast", "majority", "of", "people"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "modifier_noun_head_split" in evaluation["soft_issues"]
    assert evaluation["legal"]


def test_final_gate_blocks_negation_emphasis_split():
    editor = _marker_editor(["never,", "ever", "be", "automated"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "negation_or_emphasis_fragment" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_stranded_leading_of_complement():
    editor = _marker_editor(["the", "mechanics", "of", "resilience"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "stranded_leading_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_stranded_leading_with_complement():
    editor = _marker_editor(["was", "met", "with", "hostility"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "stranded_leading_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_time_range_to_continuation():
    editor = _marker_editor(["working", "9", "a", "m.", "to", "9", "p", "m."])

    evaluation = editor._evaluate_stable_cut_boundary(3, 4)

    assert "time_range_continuation_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_coordinated_modifier_split():
    editor = _marker_editor(["a", "massive", "economic", "and", "social", "pressure", "cooker"])

    evaluation = editor._evaluate_stable_cut_boundary(2, 3)

    assert "coordinated_modifier_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_modifier_chain_split():
    editor = _marker_editor(["a", "massive", "economic", "and", "social", "pressure", "cooker"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "modifier_chain_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_high_confidence_phrasal_verb_particle_split():
    editor = _marker_editor(["we", "really", "have", "to", "look", "at", "the", "mechanics"])

    evaluation = editor._evaluate_stable_cut_boundary(4, 5)

    assert "protected_phrasal_boundary_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_number_anchor_accepts_billion_to_chinese_yi_conversion():
    editor = _id_editor()
    anchors = editor._build_group_allocation_anchors("They raised 57.9 billion yuan.")

    number_anchor = next(anchor for anchor in anchors if anchor["type"] == "number")

    assert number_anchor["value"] == "57900000000"
    assert editor._allocation_anchor_present(number_anchor["value"], "number", "他们募集了579亿人民币。")
    assert editor._allocation_anchor_present("8600000000", "number", "大约是86亿美元。")


def test_number_anchor_accepts_decade_and_century_chinese_equivalents():
    editor = _id_editor()

    assert editor._allocation_anchor_present("2000", "number", "他在21世纪初转向健美。")
    assert editor._allocation_anchor_present("1800", "number", "可以想象成19世纪铺设铁路。")


def test_negation_anchor_accepts_natural_chinese_question_tags_and_until_pattern():
    editor = _id_editor()

    assert editor._allocation_anchor_present("negation", "negation", "对吧？")
    assert editor._allocation_anchor_present("negation", "negation", "他直到62岁才创办那家公司。")


def test_legacy_sample_specific_fragment_rules_are_not_hardcoded():
    assert not ScreenSubtitleEditor._is_bad_chinese_fragment("而如果联系更宏观层面，")
    assert not ScreenSubtitleEditor._is_bad_chinese_fragment("经过一栋空置的政府大楼")


def test_final_fragment_gate_repairs_trailing_dependent_fragments():
    editor = _marker_editor(["It's", "a", "mind-bending", "number.", "And", "they", "aren't", "funding"], max_words=8)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2), _word_item(editor, 5, 7, 3)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    texts = [item.original for item in repaired]
    assert texts == ["It's a mind-bending number. And they aren't funding"]
    assert all(not editor._ends_with_dependent_boundary_token(text) for text in texts)
    assert all(item.subtitle_id is None for item in repaired)


def test_final_fragment_gate_repairs_possessive_and_quantifier_tails():
    editor = _marker_editor(
        ["all", "the", "capital", "committed", "to", "markets", "company's", "trajectory"],
        max_words=6,
    )
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 5, 2), _word_item(editor, 6, 6, 3), _word_item(editor, 7, 7, 4)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    texts = [item.original for item in repaired]
    assert texts == ["all the capital committed to markets", "company's trajectory"]
    assert all(item.subtitle_id is None for item in repaired)


def test_final_gate_allows_sentence_initial_to_me_after_punctuation():
    editor = _marker_editor(["brutal.", "To", "me", "that", "is", "clear"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "stranded_leading_complement_split" not in evaluation["hard_issues"]


def test_final_fragment_gate_repairs_incomplete_interrogative_fragment():
    editor = _marker_editor(["How", "on", "earth", "do", "you", "know", "this?"], max_words=14)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 6, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original.startswith("How on earth do")
    assert all(item.subtitle_id is None for item in repaired)


def test_final_repair_does_not_create_adjacent_subject_fragment():
    editor = _marker_editor(["what", "you", "are", "actually", "good", "at"], max_words=14)
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert all(
        editor._evaluate_item_pair_for_final_boundary(
            left,
            right,
            repaired[index - 1] if index > 0 else None,
        )["legal"]
        for index, (left, right) in enumerate(zip(repaired, repaired[1:]))
    )


def test_final_repair_does_not_create_ordinary_one_word_fragment():
    editor = _marker_editor(["a", "Pulitzer", "Prize-winning", "journalist", "reported", "it"], max_words=5)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert not any(editor._is_ordinary_one_word_fragment(item.original) for item in repaired)
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 5 for item in repaired)


def test_final_fragment_gate_repairs_connector_and_reflexive_fragments():
    words = [
        "And",
        "another",
        "Douban",
        "user",
        "made",
        "a",
        "sharp",
        "observation",
        "about",
        "the",
        "writing",
        "itself.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [
        _word_item(editor, 0, 0, 1),
        _word_item(editor, 1, 10, 2),
        _word_item(editor, 11, 11, 3),
    ]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert " ".join(item.original for item in repaired).replace(" .", ".") == " ".join(words)
    assert not any(item.original == "And" for item in repaired)
    assert not any(item.original == "itself." for item in repaired)
    assert all(
        editor._evaluate_item_pair_for_final_boundary(
            left,
            right,
            repaired[index - 1] if index > 0 else None,
        )["legal"]
        for index, (left, right) in enumerate(zip(repaired, repaired[1:]))
    )


def test_final_fragment_gate_records_unresolved_when_no_legal_solution():
    editor = _marker_editor(["How", "on", "earth", "do", "you"], max_words=2)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 4, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]
    assert any(
        repair["unresolved_hard_issue"]
        for repair in editor._pre_id_boundary_repairs
    )


def test_podcast_template_prefers_stable_manifest_subtitle():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        stale = root / "222-original-top.srt"
        stable = root / "stable-final-original-top.srt"
        manifest = root / "stable-final-manifest.json"
        ass = root / "output.ass"
        stale.write_text("stale", encoding="utf-8")
        stable.write_text("stable", encoding="utf-8")
        ass.write_text("", encoding="utf-8")
        manifest.write_text(
            json.dumps({"paths": {"original_top_srt": str(stable)}}),
            encoding="utf-8",
        )

        resolved = resolve_podcast_template_subtitle("C:/tmp/222.m4a", str(ass))

        assert Path(resolved) == stable


def test_podcast_template_blocks_failed_stable_manifest_subtitle():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        stable = root / "stable-final-original-top.srt"
        manifest = root / "stable-final-manifest.json"
        ass = root / "output.ass"
        stable.write_text("stable", encoding="utf-8")
        ass.write_text("", encoding="utf-8")
        manifest.write_text(
            json.dumps(
                {
                    "render_blocked": True,
                    "paths": {"original_top_srt": str(stable)},
                }
            ),
            encoding="utf-8",
        )

        try:
            resolve_podcast_template_subtitle("C:/tmp/222.m4a", str(ass))
            assert False, "blocked manifest must stop podcast-template synthesis"
        except RuntimeError as exc:
            assert "阻止" in str(exc)


def test_podcast_template_reuses_legacy_reading_speed_manifest_when_revalidated():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        stable = root / "stable-final-original-top.srt"
        manifest = root / "stable-final-manifest.json"
        ass = root / "output.ass"
        stable.write_text(
            "1\n00:00:00,000 --> 00:00:01,340\n"
            "I can see why you'd think that. I mean,\n"
            "我理解你为什么这么想。我的意思是，\n",
            encoding="utf-8-sig",
        )
        ass.write_text("", encoding="utf-8")
        manifest.write_text(
            json.dumps(
                {
                    "render_blocked": True,
                    "validation_summary": {
                        "errors": [{"code": "reading_speed_error"}]
                    },
                    "paths": {"original_top_srt": str(stable)},
                }
            ),
            encoding="utf-8",
        )

        resolved = resolve_podcast_template_subtitle("C:/tmp/222.m4a", str(ass))

        assert Path(resolved) == stable


def test_podcast_template_preserves_full_media_duration_when_subtitles_end_early():
    class _FakeStdin:
        def __init__(self):
            self.frames = []

        def write(self, payload):
            self.frames.append(payload)

        def close(self):
            pass

    class _FakeProcess:
        def __init__(self):
            self.stdin = _FakeStdin()

        def wait(self):
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("successful template process must not be killed")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        srt = root / "short.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:00,200\nHello.\n你好。\n",
            encoding="utf-8",
        )
        process = _FakeProcess()
        with patch.object(podcast_learning_video, "get_duration", return_value=3.0), \
             patch.object(podcast_learning_video, "FPS", 1), \
             patch.object(podcast_learning_video, "make_base", return_value=Image.new("RGBA", (2, 2))), \
             patch.object(podcast_learning_video, "make_avatars", return_value=(None, None)), \
             patch.object(podcast_learning_video, "draw_frame", return_value=Image.new("RGB", (2, 2))), \
             patch.object(podcast_learning_video.subprocess, "Popen", return_value=process):
            podcast_learning_video.render_podcast_learning_video(
                "source.m4a",
                str(srt),
                str(root / "output.mp4"),
            )

        assert len(process.stdin.frames) == 3


def test_podcast_template_uses_frozen_task_configuration():
    config = SynthesisConfig(
        podcast_learning_template=True,
        podcast_template_style="文章单词",
        podcast_template_ai_vocab=True,
        podcast_template_title="Frozen title",
        podcast_template_background="C:/images/background.png",
        podcast_template_cover="C:/images/cover.png",
        podcast_template_date="Jul 31st 2026",
    )
    task = SynthesisTask(
        video_path="C:/media/input.m4a",
        subtitle_path="C:/media/input.srt",
        output_path="C:/media/output.mp4",
        synthesis_config=config,
    )
    with patch("app.thread.video_synthesis_thread.render_podcast_learning_video") as render:
        VideoSynthesisThread(task).run()

    kwargs = render.call_args.kwargs
    assert kwargs["template_style"] == "文章单词"
    assert kwargs["show_ai_vocab"] is True
    assert kwargs["title_text"] == "Frozen title"
    assert kwargs["background_path"] == "C:/images/background.png"
    assert kwargs["cover_path"] == "C:/images/cover.png"
    assert kwargs["date_text"] == "Jul 31st 2026"


def test_article_cover_ignores_legacy_date_text():
    article_image = Image.new(
        "RGBA",
        (
            podcast_learning_video.acx(854),
            podcast_learning_video.acy(480),
        ),
        (18, 54, 86, 255),
    )
    date_area = podcast_learning_video.article_rect(673, 0, 854, 44)

    with_legacy_date = podcast_learning_video.decorate_article_cover(
        article_image,
        "Jul 31st 2026",
    )
    with_different_legacy_date = podcast_learning_video.decorate_article_cover(
        article_image,
        "December 1st 2030",
    )

    assert with_legacy_date.tobytes() == with_different_legacy_date.tobytes()
    assert with_legacy_date.crop(date_area).tobytes() == article_image.crop(date_area).tobytes()


def test_article_opening_title_shrinks_to_keep_a_normal_long_title_in_three_lines():
    title = "如何识别人工智能写作，以及它会怎样改变我们的学习方式"
    image = Image.new("RGBA", (1920, 1080))
    draw = ImageDraw.Draw(image)

    title_font, lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        title,
        500,
        3,
        52,
        24,
        lambda size: podcast_learning_video.article_cjk_font(size, 700),
        podcast_learning_video.wrap_article_mixed_text,
    )

    assert title_font.size >= podcast_learning_video.acx(24)
    assert "".join(lines) == title
    assert len(lines) <= 3
    assert all(
        podcast_learning_video.text_w(draw, line, title_font)
        <= podcast_learning_video.acx(500)
        for line in lines
    )


def test_article_template_uses_full_hd_canvas_and_balanced_subtitle_widths():
    article_image = Image.new(
        "RGB",
        (
            podcast_learning_video.acx(854),
            podcast_learning_video.acy(480),
        ),
    )
    cue = podcast_learning_video.Cue(
        1,
        0.0,
        2.0,
        "A compact English subtitle.",
        "这是一条应优先保持单行显示的中文字幕。",
        "male",
    )
    original_wrap_zh = podcast_learning_video.wrap_zh
    original_draw_text = podcast_learning_video.draw_stroked_text
    widths = []
    chinese_centers = []

    def capture_wrap_zh(draw, text, fnt, max_width):
        widths.append(max_width)
        return original_wrap_zh(draw, text, fnt, max_width)

    def capture_draw_text(draw, xy, text, *args, **kwargs):
        if any("\u4e00" <= char <= "\u9fff" for char in text):
            chinese_centers.append((xy, kwargs.get("anchor")))
        return original_draw_text(draw, xy, text, *args, **kwargs)

    with patch.object(podcast_learning_video, "wrap_zh", side_effect=capture_wrap_zh), \
         patch.object(podcast_learning_video, "draw_article_vocab_card") as draw_card, \
         patch.object(podcast_learning_video, "draw_stroked_text", side_effect=capture_draw_text):
        frame = podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            vocab_plan={},
            show_vocab=True,
        )

    assert frame.size == (1920, 1080)
    assert podcast_learning_video.acx(1455) in widths
    assert not draw_card.called
    assert any(xy[0] == 960 and anchor == "ma" for xy, anchor in chinese_centers)


def test_caption_wrapper_never_orphans_a_leading_connector_to_balance_two_lines():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "And the data certainly points to an isolationist trend."

    font = podcast_learning_video.fit_article_en_font(draw, text, 1455)
    lines = podcast_learning_video.wrap_en(draw, text, font, podcast_learning_video.acx(1455))

    assert lines[0] != "And"
    assert lines[0].startswith("And the ")
    assert all(len(line.split()) >= 3 for line in lines)


def test_caption_wrapper_preserves_preposition_and_infinitive_phrase_edges():
    chance_words = "It increases the chance of losing the thread of the sentence.".split()
    lead_words = "Okay, but how does token prediction lead to fewer commas?".split()

    assert podcast_learning_video._caption_line_break_penalty(chance_words, 4) > 0
    assert podcast_learning_video._caption_line_break_penalty(chance_words, 5) > 0
    assert podcast_learning_video._caption_line_break_penalty(chance_words, 6) < 1_000

    infinitive_start = lead_words.index("to")
    assert podcast_learning_video._caption_line_break_penalty(lead_words, infinitive_start) > 0
    assert podcast_learning_video._caption_line_break_penalty(lead_words, infinitive_start + 1) > 0


def test_caption_wrapper_scales_before_breaking_a_hyphenated_compound():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "Think of the AI as a stand-up comedian with no internal sense of humor."

    font = podcast_learning_video.fit_article_en_font(draw, text, 1455)
    lines = podcast_learning_video.wrap_article_en_subtitle(
        draw, text, font, podcast_learning_video.acx(1455)
    )

    assert all(not line.rstrip().endswith("stand-up") for line in lines)
    assert not podcast_learning_video._has_discouraged_caption_break(text, lines)


def test_article_template_does_not_truncate_a_long_english_subtitle():
    article_image = Image.new(
        "RGB",
        (
            podcast_learning_video.acx(854),
            podcast_learning_video.acy(480),
        ),
    )
    text = (
        "Yeah. Our report from the American Enterprise Institute details how massive "
        "corporations essentially bought out the American entrepreneurial spirit."
    )
    cue = podcast_learning_video.Cue(1, 0.0, 2.0, text, "中文译文。", "male")
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    en_font = podcast_learning_video.fit_article_en_font(draw, text, 1455)
    en_lines = podcast_learning_video.wrap_article_en_subtitle(
        draw, text, en_font, podcast_learning_video.acx(1455)
    )
    rendered_lines = []
    expected_lines = set(en_lines)
    original_draw_text = podcast_learning_video.draw_stroked_text

    def capture_draw_text(draw, xy, line, *args, **kwargs):
        if line in expected_lines:
            rendered_lines.append(line)
        return original_draw_text(draw, xy, line, *args, **kwargs)

    with patch.object(
        podcast_learning_video, "draw_stroked_text", side_effect=capture_draw_text
    ):
        podcast_learning_video.draw_article_frame(article_image, cue, vocab_plan={})

    assert en_font.size == podcast_learning_video.acx(
        podcast_learning_video.ARTICLE_SUBTITLE_EN_MIN_SIZE
    )
    assert len(en_lines) == 3
    assert en_lines[0].endswith("Institute")
    assert en_lines[1].endswith("out")
    assert en_lines[2].startswith("the ")
    assert len(en_lines[-1].split()) >= 3
    assert " ".join(en_lines) == text
    assert " ".join(rendered_lines) == text


def test_standard_chinese_subtitle_font_uses_48_then_46_before_two_lines():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    width = podcast_learning_video.scx(1459)

    short_font = podcast_learning_video.fit_standard_zh_font(draw, "这是一句简短的中文字幕。", width)
    reduced_font = podcast_learning_video.fit_standard_zh_font(draw, "甲" * 32, width)
    wrapped_font = podcast_learning_video.fit_standard_zh_font(draw, "甲" * 33, width)

    assert short_font.size == 48
    assert reduced_font.size == 46
    assert len(podcast_learning_video.wrap_zh(draw, "甲" * 32, reduced_font, width)) == 1
    assert wrapped_font.size == 46
    assert len(podcast_learning_video.wrap_zh(draw, "甲" * 33, wrapped_font, width)) == 2


def test_article_template_scaled_geometry_stays_on_integer_pixels():
    values = [16, 31, 68, 854, 900, 916, 1455, 1584]

    assert all(isinstance(podcast_learning_video.acx(value), int) for value in values)
    assert all(isinstance(podcast_learning_video.acy(value), int) for value in values)
    assert isinstance(podcast_learning_video.acx(16), int)
    assert isinstance(podcast_learning_video.acy(16), int)


def test_article_template_tip_font_and_wrapper_support_chinese_text():
    font = podcast_learning_video.article_mixed_font(24)
    assert Path(font.path).name.lower() == "msyh.ttc"

    draw = ImageDraw.Draw(Image.new("RGB", (800, 300)))
    lines = podcast_learning_video.wrap_article_mixed_text(
        draw,
        "playbook 不再是体育术语，常比喻一套现成的宣传策略。",
        font,
        300,
    )

    assert "".join(lines).replace(" ", "") == "playbook不再是体育术语，常比喻一套现成的宣传策略。"
    assert len(lines) >= 2
    assert not any(line in "，。！？；：、" for line in lines)


def test_article_opening_title_accent_matches_the_visible_title_height():
    image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    rect = podcast_learning_video.article_rect(916, 16, 1584, 530)
    title = "创业者的天堂"
    podcast_learning_video.draw_article_opening_topic_panel(image, rect, title)

    draw = ImageDraw.Draw(image, "RGBA")
    title_font, title_lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        title,
        500,
        3,
        52,
        24,
        lambda size: podcast_learning_video.article_cjk_font(size, 700),
        podcast_learning_video.wrap_article_mixed_text,
    )
    line_gap = int(title_font.size * 1.25)
    block_height = max(line_gap, len(title_lines) * line_gap)
    title_x = rect[0] + podcast_learning_video.acx(92)
    first_y = (rect[1] + rect[3] - block_height) // 2
    bounds = [
        draw.textbbox((title_x, first_y + index * line_gap), line, font=title_font)
        for index, line in enumerate(title_lines)
    ]
    expected_y0 = min(box[1] for box in bounds)
    expected_y1 = max(box[3] for box in bounds)
    accent_x = rect[0] + podcast_learning_video.acx(52)
    accent_pixels = [
        y
        for y in range(rect[1], rect[3] + 1)
        if image.getpixel((accent_x, y)) == podcast_learning_video.ARTICLE_BLUE
    ]

    assert (min(accent_pixels), max(accent_pixels)) == (expected_y0, expected_y1)


def test_article_mixed_wrapper_rebalances_a_short_chinese_tail_line():
    detail = "文中指年轻人通过自主创业来摆脱僵化职场困境的途径。"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    font, lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        detail,
        500,
        2,
        26,
        20,
        lambda size: podcast_learning_video.article_cjk_font(size, 400),
        podcast_learning_video.wrap_article_mixed_text,
    )

    assert lines == [
        "文中指年轻人通过自主创业来",
        "摆脱僵化职场困境的途径。",
    ]
    assert all(
        podcast_learning_video.text_w(draw, line, font) <= podcast_learning_video.acx(500)
        for line in lines
    )


def test_article_vocab_typography_uses_hanchan_tip_and_regular_definition():
    assert Path(podcast_learning_video.article_tip_font(24).path).name == "ChillYunmoGothicMedium.otf"
    assert Path(podcast_learning_video.article_en_font(24, 400).path).name == "ReadexPro-Regular.ttf"
    assert Path(podcast_learning_video.article_cjk_font(24, 400).path).name == "ChillYunmoGothicRegular.otf"


def test_vocab_highlight_keeps_attached_punctuation_but_not_whitespace():
    line = 'seriously entertain the accusation, "then reconsider it"'
    key = "seriously entertain the accusation"
    end = podcast_learning_video.extend_highlight_to_trailing_punctuation(
        line,
        line.lower().index(key) + len(key),
    )

    assert line[:end] == "seriously entertain the accusation,"
    assert line[end] == " "


def test_standard_subtitle_highlight_colors_attached_punctuation():
    line = "seriously entertain the accusation, before dismissing it"
    key = "seriously entertain the accusation"
    image = Image.new("RGBA", (1920, 1080))
    draw = ImageDraw.Draw(image)
    blue = podcast_learning_video.with_alpha(podcast_learning_video.BLUE, 255)

    with patch.object(podcast_learning_video, "draw_subtitle_shadowed_text") as draw_text:
        podcast_learning_video.draw_highlighted_line(
            image,
            draw,
            960,
            620,
            line,
            key,
            podcast_learning_video.font(podcast_learning_video.FONT_GANTARI, 32, 600),
        )

    highlighted_text = [
        call.args[3]
        for call in draw_text.call_args_list
        if call.args[5] == blue
    ]
    assert highlighted_text == ["seriously entertain the accusation,"]


def test_article_subtitle_highlight_colors_attached_punctuation():
    line = "seriously entertain the accusation,) before dismissing it"
    key = "seriously entertain the accusation"
    fill = (42, 63, 93, 255)
    highlight_fill = (47, 111, 237, 255)
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    with patch.object(podcast_learning_video, "draw_stroked_text") as draw_text:
        podcast_learning_video.draw_highlighted_article_line(
            draw,
            960,
            620,
            line,
            key,
            podcast_learning_video.article_en_font(40, 600),
            fill,
            highlight_fill,
        )

    highlighted_text = [
        call.args[2]
        for call in draw_text.call_args_list
        if call.args[4] == highlight_fill
    ]
    assert highlighted_text == ["seriously entertain the accusation,)"]


def test_article_subtitle_highlight_does_not_add_an_underline_for_the_matched_phrase():
    line = "Well, the government wound down those subsidies years ago."
    key = "wound down"
    fill = (42, 63, 93, 255)
    highlight_fill = (47, 111, 237, 255)
    image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    font = podcast_learning_video.article_en_font(48, 600)
    center_x, text_y = 960, 620

    podcast_learning_video.draw_highlighted_article_line(
        draw,
        center_x,
        text_y,
        line,
        key,
        font,
        fill,
        highlight_fill,
    )

    prefix = line[:line.lower().index(key)]
    total_width = podcast_learning_video.text_w(draw, line, font)
    highlighted_x = center_x - total_width // 2 + podcast_learning_video.text_w(draw, prefix, font)
    box = draw.textbbox((highlighted_x, text_y), key, font=font)
    underline_y = box[3] + podcast_learning_video.acy(6) + podcast_learning_video.acy(2)
    underline_x = (box[0] + box[2]) // 2

    assert image.getpixel((underline_x, underline_y)) == (0, 0, 0, 0)


def test_vocab_highlight_ranges_cover_a_phrase_split_between_subtitle_lines():
    lines = [
        "Well, the government wound",
        "down those subsidies years ago.",
    ]

    assert podcast_learning_video.highlight_ranges_for_lines(lines, "wound down") == [
        (21, 26),
        (0, 4),
    ]


def test_article_subtitle_keeps_the_active_phrase_on_one_line_when_possible():
    text = "Well, the government wound down those subsidies years ago."
    key = "wound down"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    font = podcast_learning_video.fit_article_en_font(draw, text, 1455)

    lines = podcast_learning_video.wrap_en_preserving_highlight(
        draw,
        text,
        font,
        podcast_learning_video.acx(1455),
        key,
    )

    assert " ".join(lines) == text
    assert any(key in line for line in lines)
    assert all(len(line.split()) >= 3 for line in lines)


def test_vocab_card_plan_keeps_the_latest_full_card_until_replacement():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 1.0, "A regulatory change.", "", "male"),
        podcast_learning_video.Cue(2, 1.5, 2.5, "A crackdown begins.", "", "male"),
        podcast_learning_video.Cue(3, 5.0, 6.0, "New compliance rules.", "", "male"),
        podcast_learning_video.Cue(4, 10.0, 16.0, "A quiet transition.", "", "male"),
        podcast_learning_video.Cue(5, 20.0, 21.0, "Algorithmic oversight.", "", "male"),
        podcast_learning_video.Cue(6, 25.0, 26.0, "More regulatory rules.", "", "male"),
    ]
    candidates = {
        1: {"key": "regulatory", "word": "Regulatory"},
        2: {"key": "crackdown", "word": "Crackdown"},
        3: {"key": "compliance", "word": "Compliance"},
        5: {"key": "algorithmic", "word": "Algorithmic"},
        6: {"key": "regulatory", "word": "Regulatory"},
    }

    plan = podcast_learning_video.schedule_vocab_card_plan(candidates, cues)

    assert list(plan) == [1, 5]
    assert podcast_learning_video.active_vocab_card(plan, cues[0], 0.5)["key"] == "regulatory"
    assert podcast_learning_video.vocab_card_display_state(plan, cues[2], 5.0)[1] == "full"
    assert podcast_learning_video.vocab_card_display_state(plan, cues[3], 13.0) == (plan[1], "full")
    assert podcast_learning_video.vocab_card_display_state(plan, cues[4], 20.0) == (plan[5], "full")
    assert podcast_learning_video.vocab_card_display_state(plan, None, 50.0) == (plan[5], "full")


def test_article_vocab_card_uses_only_expression_gloss_and_concept_note():
    image = Image.new(
        "RGBA",
        (podcast_learning_video.ARTICLE_WIDTH, podcast_learning_video.ARTICLE_HEIGHT),
        (255, 255, 255, 255),
    )
    item = {
        "word": "black-box algorithm",
        "phonetic": "/ˈreɡ.jə.lə.tɔːr.i/",
        "level": "TOEFL",
        "pos": "adj.",
        "meaning": "黑箱算法",
        "definition": "Related to official rules or controls.",
        "tip_en": "Often used before policy or approval.",
        "tip_zh": "常放在 policy 等名词前。",
        "card_type": "concept",
        "detail": "能给出结论，却无法说明判断过程。",
    }
    with patch.object(podcast_learning_video, "draw_stroked_text") as draw_text:
        podcast_learning_video.draw_article_vocab_card(
            image,
            item,
            podcast_learning_video.article_rect(916, 16, 1584, 530),
        )

    labels = [call.args[2] for call in draw_text.call_args_list]
    rendered_text = "".join(labels)
    assert "black-box algorithm" in labels
    assert "黑箱算法" in rendered_text
    assert "能给出结论，却无法说明判断过程。" in rendered_text
    assert "adj." not in rendered_text
    assert "TOEFL" not in rendered_text
    assert "IN CONTEXT" not in rendered_text
    assert "Related to official rules or controls." not in rendered_text


def test_vocab_prompt_requests_expression_card_fields_without_dictionary_metadata():
    group = podcast_learning_video.VocabSemanticGroup(
        "VG0001",
        (1,),
        0.0,
        2.0,
        "A hallmark of quality is consistency.",
    )

    prompt = podcast_learning_video.build_vocab_selection_prompt([group], 1)

    assert "phrase" in prompt
    assert "card_type" in prompt
    assert "detail" in prompt
    assert "音标" in prompt
    assert "词性" in prompt
    assert "tip_zh" not in prompt
    assert "语义组" in prompt


def test_vocab_plan_preserves_the_exact_phrase_from_its_subtitle():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "Long hours can take a toll on health.", "长时间工作会损害健康。", "male"),
    ]
    groups = podcast_learning_video.build_vocab_semantic_groups(cues)

    plan = podcast_learning_video.normalize_vocab_plan(
        [{
            "group_id": "VG0001",
            "cue_index": 1,
            "phrase": "take a toll on",
            "meaning": "对……造成损害",
            "card_type": "standard",
        }],
        cues,
        groups,
    )

    assert plan[1]["word"] == "take a toll on"
    assert plan[1]["key"] == "take a toll on"


def test_vocab_source_phrase_does_not_match_inside_a_larger_word():
    cue = "She continues to out-earn her husband."

    assert podcast_learning_video.find_vocab_source_phrase(cue, "earn") == ""
    assert podcast_learning_video.find_vocab_source_phrase(cue, "out-earn") == "out-earn"


def test_vocab_plan_limits_concept_cards_to_three_per_episode():
    cues = [
        podcast_learning_video.Cue(index, (index - 1) * 20.0, (index - 1) * 20.0 + 2.0, f"Concept {index} appears.", "", "male")
        for index in range(1, 5)
    ]
    candidates = {
        index: {
            "key": f"concept {index}",
            "word": f"Concept {index}",
            "meaning": f"概念{index}",
            "detail": "需要额外解释。",
            "card_type": "concept",
            "priority": 5,
        }
        for index in range(1, 5)
    }

    plan = podcast_learning_video.schedule_vocab_card_plan(candidates, cues)

    assert sum(item["card_type"] == "concept" for item in plan.values()) == 3
    assert plan[4]["card_type"] == "standard"
    assert plan[4]["detail"] == ""


def test_vocab_plan_keeps_each_llm_card_inside_its_frozen_group():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 1.0, "The policy is designed", "", "male"),
        podcast_learning_video.Cue(2, 1.0, 2.0, "to reduce regulatory risk.", "", "male"),
        podcast_learning_video.Cue(3, 2.2, 3.2, "That is important.", "", "male"),
    ]
    groups = podcast_learning_video.build_vocab_semantic_groups(cues)
    assert [group.cue_indices for group in groups] == [(1, 2), (3,)]
    candidates = podcast_learning_video.normalize_vocab_plan(
        [
            {
                "group_id": "VG0001",
                "cue_index": 2,
                "word": "regulatory",
                "meaning": "监管的",
            }
        ],
        cues,
        groups,
    )
    plan = podcast_learning_video.schedule_vocab_card_plan(candidates, cues)
    assert plan[2]["display_start"] == 1.0
    assert podcast_learning_video.active_vocab_card(plan, cues[0], 0.5) is None
    assert podcast_learning_video.active_vocab_card(plan, cues[1], 1.0)["key"] == "regulatory"
    assert podcast_learning_video.active_vocab_card(plan, cues[2], 2.2)["key"] == "regulatory"
    assert podcast_learning_video.active_vocab_card(plan, None, 2.2)["key"] == "regulatory"


def test_vocab_card_meaning_keeps_only_compact_primary_gloss():
    assert podcast_learning_video.compact_vocab_meaning(
        "n. 破绽；暴露真相的线索（此处指暴露 AI 的明显特征）"
    ) == "破绽；暴露真相的线索"
    assert podcast_learning_video.compact_vocab_meaning(
        "名词化（把动词或形容词变成名词的过程/结果）"
    ) == "名词化"


def test_vocab_plan_normalizes_verbose_model_meaning_before_rendering():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "A giveaway reveals the truth.", "", "male"),
    ]
    groups = podcast_learning_video.build_vocab_semantic_groups(cues)

    plan = podcast_learning_video.normalize_vocab_plan(
        [{
            "group_id": "VG0001",
            "cue_index": 1,
            "word": "giveaway",
            "meaning": "n. 破绽；暴露真相的线索（此处指暴露 AI 的明显特征）",
        }],
        cues,
        groups,
    )

    assert plan[1]["meaning"] == "破绽；暴露真相的线索"


def test_vocab_card_plan_skips_low_priority_model_candidates():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "A marginal word.", "", "male"),
        podcast_learning_video.Cue(2, 12.0, 14.0, "A central concept.", "", "male"),
    ]
    plan = podcast_learning_video.schedule_vocab_card_plan(
        {
            1: {"key": "marginal", "word": "Marginal", "priority": 2},
            2: {"key": "central", "word": "Central", "priority": 5},
        },
        cues,
    )

    assert list(plan) == [2]
    assert plan[2]["priority"] == 5


def test_vocabulary_card_target_is_20_for_a_sixteen_minute_episode():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "Opening.", "", "male"),
        podcast_learning_video.Cue(2, 958.0, 960.0, "Closing.", "", "female"),
    ]
    assert podcast_learning_video.vocabulary_card_target(cues) == 20


def test_article_template_does_not_fallback_to_per_subtitle_vocab_lookup():
    article_image = Image.new(
        "RGB",
        (podcast_learning_video.acx(854), podcast_learning_video.acy(480)),
    )
    cue = podcast_learning_video.Cue(
        1,
        0.0,
        2.0,
        "A regulatory change.",
        "一次监管变化。",
        "male",
    )
    with patch.object(podcast_learning_video, "find_vocab", return_value={"key": "regulatory"}) as fallback, \
         patch.object(podcast_learning_video, "draw_article_vocab_card") as draw_card:
        podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            vocab_plan={},
            show_vocab=True,
            display_time=0.5,
        )

    assert not fallback.called
    assert not draw_card.called


def test_vocab_generation_keeps_successful_batches_when_one_batch_fails():
    from types import SimpleNamespace

    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "An obscure signal appeared.", "出现了一个晦涩信号。", ""),
        podcast_learning_video.Cue(2, 2.1, 4.0, "The pattern is persistent.", "这种模式持续存在。", ""),
    ]
    groups = [
        podcast_learning_video.VocabSemanticGroup("VG0001", (1,), 0.0, 2.0, cues[0].en),
        podcast_learning_video.VocabSemanticGroup("VG0002", (2,), 2.1, 4.0, cues[1].en),
    ]

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                raise RuntimeError("temporary provider failure")
            payload = [{
                "group_id": "VG0002",
                "cue_index": 2,
                "word": "persistent",
                "phonetic": "/pəˈsɪstənt/",
                "level": "IELTS",
                "pos": "adj.",
                "meaning": "持续的",
                "definition": "Continuing for a long time.",
                "tip_en": "A persistent pattern continues over time.",
                "tip_zh": "表示持续存在。",
            }]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    messages = []
    with tempfile.TemporaryDirectory() as raw:
        subtitle_path = Path(raw) / "sample.srt"
        subtitle_path.write_text("", encoding="utf-8")
        with patch.object(podcast_learning_video, "build_vocab_semantic_groups", return_value=groups), patch.object(
            podcast_learning_video, "split_vocab_groups_for_requests", return_value=[[groups[0]], [groups[1]]]
        ), patch.object(podcast_learning_video, "vocabulary_card_target", return_value=2), patch.object(
            podcast_learning_video, "current_llm_config", return_value=("https://example.test/v1", "key", "test-model")
        ), patch.object(podcast_learning_video, "OpenAI", return_value=client), patch.object(
            podcast_learning_video, "CACHE_PATH", Path(raw) / "cache"
        ):
            plan = podcast_learning_video.load_or_generate_vocab_plan(
                subtitle_path,
                cues,
                True,
                progress_callback=lambda _, message: messages.append(message),
            )

    assert 2 in plan
    assert 1 not in plan
    assert any("部分生成完成" in message for message in messages)


def test_empty_vocab_cache_is_regenerated_instead_of_reused():
    from types import SimpleNamespace

    cue = podcast_learning_video.Cue(
        1, 0.0, 2.0, "An obscure signal appeared.", "出现了一个晦涩信号。", ""
    )
    group = podcast_learning_video.VocabSemanticGroup(
        "VG0001", (1,), 0.0, 2.0, cue.en
    )

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            payload = [{
                "group_id": "VG0001",
                "cue_index": 1,
                "word": "obscure",
                "phonetic": "/əbˈskjʊr/",
                "level": "IELTS",
                "pos": "adj.",
                "meaning": "晦涩的",
                "definition": "Not well known or difficult to understand.",
                "tip_en": "Obscure can describe an idea that is hard to grasp.",
                "tip_zh": "可形容概念晦涩难懂。",
            }]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    with tempfile.TemporaryDirectory() as raw:
        subtitle_path = Path(raw) / "sample.srt"
        subtitle_path.write_text("", encoding="utf-8")
        cache_root = Path(raw) / "cache"
        source_hash = podcast_learning_video.vocab_source_hash([cue])
        stale_cache = cache_root / "podcast_vocab_cards" / f"{source_hash}.json"
        stale_cache.parent.mkdir(parents=True)
        stale_cache.write_text(
            json.dumps({
                "source_hash": source_hash,
                "prompt_version": podcast_learning_video.VOCAB_PROMPT_VERSION,
                "model": "test-model",
                "cards": [],
            }),
            encoding="utf-8",
        )
        with patch.object(podcast_learning_video, "build_vocab_semantic_groups", return_value=[group]), patch.object(
            podcast_learning_video, "split_vocab_groups_for_requests", return_value=[[group]]
        ), patch.object(podcast_learning_video, "vocabulary_card_target", return_value=1), patch.object(
            podcast_learning_video, "current_llm_config", return_value=("https://example.test/v1", "key", "test-model")
        ), patch.object(podcast_learning_video, "OpenAI", return_value=client), patch.object(
            podcast_learning_video, "CACHE_PATH", cache_root
        ):
            plan = podcast_learning_video.load_or_generate_vocab_plan(subtitle_path, [cue], True)

    assert completions.calls == 1
    assert plan[1]["key"] == "obscure"


def test_article_template_shows_topic_panel_before_first_card():
    article_image = Image.new(
        "RGB",
        (podcast_learning_video.acx(854), podcast_learning_video.acy(480)),
    )
    cue = podcast_learning_video.Cue(1, 0.0, 8.0, "Welcome to the lesson.", "欢迎收看本期内容。", "male")
    plan = {
        2: {
            "key": "regulatory",
            "word": "Regulatory",
            "meaning": "监管的",
            "display_start": 4.0,
            "display_end": 7.0,
        }
    }
    with patch.object(podcast_learning_video, "draw_article_opening_topic_panel") as topic_panel, \
         patch.object(podcast_learning_video, "draw_article_vocab_card") as card:
        podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            plan,
            show_vocab=True,
            title_text="如何识别人工智能写作",
            display_time=0.0,
        )
        assert topic_panel.called
        assert topic_panel.call_args.args[2] == "如何识别人工智能写作"
        assert not card.called

        topic_panel.reset_mock()
        podcast_learning_video.draw_article_frame(article_image, cue, plan, show_vocab=True, display_time=5.0)
        assert card.called
        assert not topic_panel.called

        card.reset_mock()
        podcast_learning_video.draw_article_frame(article_image, cue, plan, show_vocab=True, display_time=8.0)
        assert card.called
        assert not topic_panel.called


def test_article_template_crossfades_only_from_topic_to_first_card():
    article_image = Image.new(
        "RGB",
        (podcast_learning_video.acx(854), podcast_learning_video.acy(480)),
    )
    cue = podcast_learning_video.Cue(1, 4.0, 6.0, "A key expression appears.", "出现一个重点表达。", "male")
    plan = {
        1: {"key": "key expression", "word": "key expression", "meaning": "重点表达", "display_start": 4.0, "display_end": 12.0},
        2: {"key": "next expression", "word": "next expression", "meaning": "下一个表达", "display_start": 24.0, "display_end": 32.0},
    }
    with patch.object(podcast_learning_video, "draw_article_opening_topic_panel") as topic_panel, \
         patch.object(podcast_learning_video, "draw_article_vocab_card") as card:
        podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            plan,
            show_vocab=True,
            display_time=4.1,
        )
        assert topic_panel.called
        assert card.called

        topic_panel.reset_mock()
        card.reset_mock()
        podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            plan,
            show_vocab=True,
            display_time=24.1,
        )
        assert not topic_panel.called
        assert card.called

    assert podcast_learning_video.opening_card_transition_progress(plan, plan[1], "full", 4.0) == 0.0
    assert podcast_learning_video.opening_card_transition_progress(plan, plan[1], "full", 4.125) == 0.5
    assert podcast_learning_video.opening_card_transition_progress(plan, plan[1], "full", 4.25) is None
    assert podcast_learning_video.opening_card_transition_progress(plan, plan[2], "full", 24.1) is None


def test_episode_vocab_overview_uses_editor_rank_instead_of_earliest_words():
    plan = {
        3: {"word": "Early", "display_start": 2.0},
        21: {"word": "Core", "display_start": 40.0, "episode_rank": 1},
        48: {"word": "Theme", "display_start": 90.0, "episode_rank": 2},
        77: {"word": "Mechanism", "display_start": 140.0, "episode_rank": 3},
    }

    assert [item["word"] for item in podcast_learning_video.episode_vocab_overview_items(plan)] == [
        "Core",
        "Theme",
        "Mechanism",
    ]


def test_template_frame_cache_keeps_the_full_vocab_card_stable():
    class _FakeStdin:
        def write(self, payload):
            pass

        def close(self):
            pass

    class _FakeProcess:
        def __init__(self):
            self.stdin = _FakeStdin()

        def wait(self):
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("successful template process must not be killed")

    plan = {
        1: {
            "key": "regulatory",
            "word": "Regulatory",
            "display_id": "1:regulatory",
            "display_start": 0.0,
        }
    }
    rendered_at = []

    def draw_frame(*args):
        rendered_at.append(args[-1])
        return Image.new("RGB", (2, 2))

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        srt = root / "long.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:10,000\nA regulatory change.\n一次监管变化。\n",
            encoding="utf-8",
        )
        with patch.object(podcast_learning_video, "load_or_generate_vocab_plan", return_value=plan), \
             patch.object(podcast_learning_video, "get_duration", return_value=10.0), \
             patch.object(podcast_learning_video, "FPS", 1), \
             patch.object(podcast_learning_video, "make_base", return_value=Image.new("RGBA", (2, 2))), \
             patch.object(podcast_learning_video, "make_avatars", return_value=(None, None)), \
             patch.object(podcast_learning_video, "draw_frame", side_effect=draw_frame), \
             patch.object(podcast_learning_video.subprocess, "Popen", return_value=_FakeProcess()):
            podcast_learning_video.render_podcast_learning_video(
                "source.m4a",
                str(srt),
                str(root / "output.mp4"),
                show_ai_vocab=True,
            )

    assert rendered_at
    assert all(timestamp < 8.0 for timestamp in rendered_at)


def test_stable_srt_writer_keeps_bilingual_original_top():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "stable-final-original-top.srt"
        data = ASRData([ASRDataSeg("Hello world.", 0, 1000, "你好，世界。")])

        SubtitleThread._write_stable_srt(data, path, "original_top")

        text = path.read_text(encoding="utf-8-sig")
        assert "Hello world.\n你好，世界。" in text


def test_id_bound_group_missing_one_id_does_not_shift_later_subtitles():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(4, translated="fallback-S{index:04d}"))
    group = _id_group(1, 0, items)
    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0002", "zh": "zh-S0002"},
            {"subtitle_id": "S0004", "zh": "zh-S0004"},
        ],
    )

    applied = editor._apply_semantic_group_translations(items, [group], {1: translations})

    assert [item.subtitle_id for item in applied] == ["S0001", "S0002", "S0003", "S0004"]
    assert [item.original for item in applied] == [item.original for item in items]
    assert [item.word_start for item in applied] == [item.word_start for item in items]
    assert applied[2].translated == "fallback-S0003"
    assert applied[3].translated == "zh-S0004"
    assert {"translation_id_missing", "translation_group_cardinality_mismatch"} <= _codes(editor)


def test_atomic_no_response_cannot_be_written_as_affirmative():
    editor = _editor()

    assert editor._repair_atomic_response_polarity("No.", "对。") == "不是。"
    assert editor._repair_atomic_response_polarity("No.", "不。") == "不。"
    assert editor._repair_atomic_response_polarity("No, not at all.", "完全不是。") == "完全不是。"


def test_id_bound_group_rejects_duplicate_id_without_compressing_chinese():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(3))
    group = _id_group(1, 0, items)

    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0002", "zh": "zh-S0002"},
            {"subtitle_id": "S0002", "zh": "duplicate"},
        ],
    )

    assert translations == {"S0001": "zh-S0001", "S0002": "zh-S0002"}
    assert {
        "translation_id_duplicate",
        "translation_id_missing",
        "translation_group_cardinality_mismatch",
    } <= _codes(editor)


def test_id_bound_group_rejects_unknown_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    group = _id_group(1, 0, items)

    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S9999", "zh": "unknown"},
        ],
    )

    assert translations == {"S0001": "zh-S0001"}
    assert {
        "translation_id_unknown",
        "translation_id_missing",
        "translation_group_cardinality_mismatch",
    } <= _codes(editor)


def test_id_bound_group_allows_different_return_order():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(4))
    group = _id_group(1, 0, items)

    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0004", "zh": "zh-S0004"},
            {"subtitle_id": "S0002", "zh": "zh-S0002"},
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0003", "zh": "zh-S0003"},
        ],
    )
    applied = editor._apply_semantic_group_translations(items, [group], {1: translations})

    assert [item.translated for item in applied] == [
        "zh-S0001",
        "zh-S0002",
        "zh-S0003",
        "zh-S0004",
    ]
    assert editor._translation_structure_errors == []


def test_allocation_parser_recovers_orphan_subtitle_rows_by_global_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(4))
    groups = [_id_group(1, 0, items[:2]), _id_group(2, 2, items[2:])]
    groups_data = [
        {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [{"subtitle_id": "S0001", "zh": "zh-S0001"}],
                },
                {"subtitle_id": "S0002", "zh": "zh-S0002"},
            ]
        },
        {
            "id": 2,
            "part_translations": [{"subtitle_id": "S0003", "zh": "zh-S0003"}],
        },
        {"subtitle_id": "S0004", "zh": "zh-S0004"},
    ]

    normalized = editor._normalize_allocation_groups_data(groups, groups_data)
    translations = {}
    for group in normalized:
        expected_group = groups[int(group["id"]) - 1]
        translations[int(group["id"])] = editor._parse_id_bound_translations(
            expected_group,
            editor._group_expected_subtitle_ids(expected_group),
            group.get("part_translations", []),
        )
    applied = editor._apply_semantic_group_translations(items, groups, translations)

    assert [item.subtitle_id for item in applied] == ["S0001", "S0002", "S0003", "S0004"]
    assert [item.translated for item in applied] == [
        "zh-S0001",
        "zh-S0002",
        "zh-S0003",
        "zh-S0004",
    ]
    assert editor._translation_structure_errors == []


def test_allocation_requests_large_payload_in_small_id_bound_chunks():
    editor = _id_editor()
    editor.batch_num = 50
    editor.allocation_batch_size = 24
    items = editor._assign_global_subtitle_ids(_id_items(50))
    groups = [
        _id_group(index, (index - 1) * 2, items[(index - 1) * 2 : index * 2])
        for index in range(1, 26)
    ]
    full_translations = {index: f"full-{index}" for index in range(1, 26)}
    requested_group_ids = []

    def request(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        requested_group_ids.append([entry["id"] for entry in payload])
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": part["subtitle_id"],
                            "zh": f"zh-{part['subtitle_id']}",
                        }
                        for part in entry["subtitle_parts"]
                    ],
                }
                for entry in reversed(payload)
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert requested_group_ids == [
        list(range(1, 25)),
        [25],
    ]
    assert allocated[1] == {"S0001": "zh-S0001", "S0002": "zh-S0002"}
    assert allocated[25] == {"S0049": "zh-S0049", "S0050": "zh-S0050"}
    assert editor._translation_structure_errors == []


def test_single_cue_group_uses_authoritative_full_translation_without_allocation_request():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Hello."
    items[1].original = "Thanks."
    groups = [_id_group(1, 0, [items[0]]), _id_group(2, 1, [items[1]])]

    with patch.object(
        editor,
        "_request_semantic_translation_allocation",
        side_effect=AssertionError("single-cue group must not make an allocation request"),
    ):
        allocated = editor._allocate_semantic_group_translations(
            groups,
            {1: "你好。", 2: "谢谢。"},
        )

    assert allocated == {1: {"S0001": "你好。"}, 2: {"S0002": "谢谢。"}}
    assert [entry["source"] for entry in editor._last_allocation_final] == [
        "authoritative_full_translation",
        "authoritative_full_translation",
    ]
    assert editor._last_allocation_retry_log == []
    assert [entry["id"] for entry in editor._last_allocation_inputs] == [1, 2]


def test_full_translation_number_error_is_not_misclassified_as_allocation_error():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "下降了8个百分点。",
        "subtitle_parts": [{"subtitle_id": "S0001", "english": "An 8% drop."}],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "下降了8个百分点。"},
    )

    assert validation["valid"]
    assert "full_translation_quality_issue" in validation["issue_codes"]
    assert "number_allocation_mismatch" not in validation["issue_codes"]


def test_full_translation_requests_are_chunked_and_retry_missing_groups():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 2
    items = editor._assign_global_subtitle_ids(_id_items(3))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 4)]
    calls = []

    def request(prompt, payload, cache_task):
        ids = [entry["id"] for entry in payload]
        calls.append((cache_task, ids))
        if ids == [1, 2]:
            return {"groups": [{"id": 1, "full_translation": "full-1"}]}
        return {
            "groups": [
                {"id": entry["id"], "full_translation": f"full-{entry['id']}"}
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_full_translation_chunk", side_effect=request):
        full_translations = editor._translate_semantic_group_full_translations(groups)

    assert calls == [
        ("screen_subtitle_semantic_full_translation_v4", [1, 2]),
        ("screen_subtitle_semantic_full_translation_v4", [3]),
        ("screen_subtitle_semantic_full_translation_v4_retry", [2]),
    ]
    assert full_translations == {1: "full-1", 2: "full-2", 3: "full-3"}
    assert editor._translation_structure_errors == []


def test_full_translation_prompt_restrains_ordinary_chinese_em_dashes():
    from app.core.subtitle_processor.screen_editor import SEMANTIC_FULL_TRANSLATION_PROMPT

    assert "Do not use em dashes for ordinary explanations" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "Never leave an em dash at the beginning or end" in SEMANTIC_FULL_TRANSLATION_PROMPT


def test_full_translation_em_dash_style_detector_ignores_lexical_hyphen():
    assert ScreenSubtitleEditor._full_translation_em_dash_findings("盎格鲁-撒克逊传统") == []
    assert ScreenSubtitleEditor._full_translation_em_dash_findings("——研究结论")
    assert ScreenSubtitleEditor._full_translation_em_dash_findings("研究结论——")
    assert ScreenSubtitleEditor._full_translation_em_dash_findings("甲——乙——丙")


def test_full_translation_style_retry_only_retries_flagged_group_and_accepts_improvement():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "An ordinary statement."
    items[1].original = "The study found a clear result."
    groups = [_id_group(1, 0, [items[0]]), _id_group(2, 1, [items[1]])]
    calls = []

    def request(prompt, payload, cache_task):
        calls.append((cache_task, [entry["id"] for entry in payload]))
        if cache_task == "screen_subtitle_semantic_full_translation_v4":
            return {
                "groups": [
                    {"id": 1, "full_translation": "这是一句普通陈述。"},
                    {"id": 2, "full_translation": "这项研究得出了明确结论——"},
                ]
            }
        assert cache_task == "screen_subtitle_semantic_full_translation_style_retry_v1"
        assert payload[0]["current_translation"] == "这项研究得出了明确结论——"
        return {"groups": [{"id": 2, "full_translation": "这项研究得出了明确结论。"}]}

    with patch.object(editor, "_request_semantic_full_translation_chunk", side_effect=request):
        full_translations = editor._translate_semantic_group_full_translations(groups)

    assert calls == [
        ("screen_subtitle_semantic_full_translation_v4", [1, 2]),
        ("screen_subtitle_semantic_full_translation_style_retry_v1", [2]),
    ]
    assert full_translations == {1: "这是一句普通陈述。", 2: "这项研究得出了明确结论。"}
    assert editor._last_full_translation_style_retry_log == [
        {
            "semantic_group_id": "G0002",
            "cache_task": "screen_subtitle_semantic_full_translation_style_retry_v1",
            "original_translation": "这项研究得出了明确结论——",
            "candidate_translation": "这项研究得出了明确结论。",
            "original_style_findings": [{"code": "em_dash_at_translation_boundary", "em_dash_runs": 1}],
            "candidate_style_findings": [],
            "original_style_score": 3,
            "candidate_style_score": 0,
            "accepted": True,
            "decision": "accept_style_retry",
            "rejection_reasons": [],
        }
    ]
    assert [item.original for item in items] == ["An ordinary statement.", "The study found a clear result."]
    assert [item.subtitle_id for item in items] == ["S0001", "S0002"]


def test_full_translation_style_retry_keeps_original_when_candidate_loses_number_or_negation():
    editor = _id_editor()
    original = "该公司没有批准42份提案——"
    with patch.object(
        editor,
        "_request_semantic_full_translation_chunk",
        return_value={"groups": [{"id": 1, "full_translation": "该公司批准了这些提案。"}]},
    ):
        result = editor._retry_full_translations_for_em_dash_style(
            payload_by_id={
                1: {
                    "id": 1,
                    "full_english": "The company did not approve 42 proposals.",
                    "current_translation": original,
                }
            },
            full_translations={1: original},
        )

    assert result == {1: original}
    assert editor._last_full_translation_style_retry_log[-1]["decision"] == "keep_original"
    assert set(editor._last_full_translation_style_retry_log[-1]["rejection_reasons"]) == {
        "lost_number_anchor:42",
        "lost_negation_anchor:negation",
    }


def test_two_stage_translation_failure_does_not_fallback_to_single_stage():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2, translated="old-{index}"))

    with patch.object(editor, "_translate_semantic_group_full_translations", return_value={}), patch.object(
        editor,
        "_translate_semantic_subtitle_groups_single_stage",
        side_effect=AssertionError("single-stage fallback must not run"),
    ):
        result = editor._translate_semantic_subtitle_groups(items)

    assert [item.subtitle_id for item in result] == ["S0001", "S0002"]
    assert [item.translated for item in result] == ["old-1", "old-2"]


def test_allocation_retries_incomplete_chunk_by_single_group_without_lingering_errors():
    editor = _id_editor()
    editor.batch_num = 24
    editor.allocation_batch_size = 24
    items = editor._assign_global_subtitle_ids(_id_items(3))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 4)]
    full_translations = {index: f"full-{index}" for index in range(1, 4)}
    calls = []

    def request(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        calls.append((cache_task, [entry["id"] for entry in payload]))
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "zh-S0001"},
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": entry["subtitle_parts"][0]["subtitle_id"],
                            "zh": f"zh-{entry['subtitle_parts'][0]['subtitle_id']}",
                        }
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert calls == [
        ("screen_subtitle_semantic_translation_allocation_v3", [1, 2, 3]),
        ("screen_subtitle_semantic_translation_allocation_retry_v3", [1]),
        ("screen_subtitle_semantic_translation_allocation_retry_v3", [2]),
        ("screen_subtitle_semantic_translation_allocation_retry_v3", [3]),
    ]
    assert allocated == {
        1: {"S0001": "zh-S0001"},
        2: {"S0002": "zh-S0002"},
        3: {"S0003": "zh-S0003"},
    }
    assert editor._translation_structure_errors == []


def test_allocation_concurrency_merges_out_of_order_batches_by_id():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 2
    editor.allocation_max_concurrency = 2
    items = editor._assign_global_subtitle_ids(_id_items(4))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 5)]
    full_translations = {index: f"full-{index}" for index in range(1, 5)}
    completions = []

    def request_api(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        ids = [entry["id"] for entry in payload]
        if ids == [1, 2]:
            time.sleep(0.05)
        completions.append(ids)
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {
                                "subtitle_id": entry["subtitle_parts"][0]["subtitle_id"],
                                "zh": f"zh-{entry['subtitle_parts'][0]['subtitle_id']}",
                            }
                        ],
                    }
                    for entry in reversed(payload)
                ]
            },
            "",
        )

    with patch.object(editor, "_request_semantic_translation_allocation_api_only", side_effect=request_api):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert completions[0] == [3, 4]
    assert allocated == {
        1: {"S0001": "zh-S0001"},
        2: {"S0002": "zh-S0002"},
        3: {"S0003": "zh-S0003"},
        4: {"S0004": "zh-S0004"},
    }
    assert [entry["batch_id"] for entry in editor._last_llm_raw_returns] == [1, 2]
    assert editor._translation_structure_errors == []


def test_allocation_concurrency_retries_one_failed_batch_without_dropping_completed_batches():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 2
    editor.allocation_max_concurrency = 2
    items = editor._assign_global_subtitle_ids(_id_items(4))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 5)]
    full_translations = {index: f"full-{index}" for index in range(1, 5)}
    retried = []

    def request_api(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        ids = [entry["id"] for entry in payload]
        if ids == [1, 2]:
            return None, "timeout"
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {"subtitle_id": entry["subtitle_parts"][0]["subtitle_id"], "zh": f"zh-{entry['id']}"}
                        ],
                    }
                    for entry in payload
                ]
            },
            "",
        )

    def retry_request(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation_retry"):
        retried.append([entry["id"] for entry in payload])
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {"subtitle_id": entry["subtitle_parts"][0]["subtitle_id"], "zh": f"retry-{entry['id']}"}
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation_api_only", side_effect=request_api), patch.object(
        editor, "_request_semantic_translation_allocation", side_effect=retry_request
    ):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert retried == [[1], [2]]
    assert allocated == {
        1: {"S0001": "retry-1"},
        2: {"S0002": "retry-2"},
        3: {"S0003": "zh-3"},
        4: {"S0004": "zh-4"},
    }
    assert editor._translation_structure_errors == []


def test_allocation_concurrency_records_duplicate_and_unknown_ids_after_retry_failure():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 2
    editor.allocation_max_concurrency = 2
    items = editor._assign_global_subtitle_ids(_id_items(2))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 3)]
    full_translations = {1: "full-1", 2: "full-2"}

    def bad_response(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "one"},
                        {"subtitle_id": "S0001", "zh": "duplicate"},
                        {"subtitle_id": "S9999", "zh": "unknown"},
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation_api_only", return_value=(bad_response("", []), "")), patch.object(
        editor, "_request_semantic_translation_allocation", side_effect=bad_response
    ):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert allocated[1] == {"S0001": "one"}
    codes = _codes(editor)
    assert "translation_id_duplicate" in codes
    assert "translation_id_unknown" in codes
    assert "translation_group_cardinality_mismatch" in codes


def test_allocation_concurrency_uses_mixed_cache_hits_without_worker_cache_writes():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 2
    editor.allocation_max_concurrency = 2
    cached_payload = {
        "groups": [
            {"id": 1, "part_translations": [{"subtitle_id": "S0001", "zh": "cached-1"}]},
            {"id": 2, "part_translations": [{"subtitle_id": "S0002", "zh": "cached-2"}]},
        ]
    }
    editor.cache_manager = _QueueCache([json.dumps(cached_payload, ensure_ascii=False), None])
    items = editor._assign_global_subtitle_ids(_id_items(4))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 5)]
    full_translations = {index: f"full-{index}" for index in range(1, 5)}

    def request_api(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {"subtitle_id": entry["subtitle_parts"][0]["subtitle_id"], "zh": f"api-{entry['id']}"}
                        ],
                    }
                    for entry in payload
                ]
            },
            "",
        )

    with patch.object(editor, "_request_semantic_translation_allocation_api_only", side_effect=request_api):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert allocated == {
        1: {"S0001": "cached-1"},
        2: {"S0002": "cached-2"},
        3: {"S0003": "api-3"},
        4: {"S0004": "api-4"},
    }
    assert editor._llm_cache_used is True
    assert len(editor.cache_manager.set_calls) == 1
    assert editor._llm_cache_stats["screen_subtitle_semantic_translation_allocation_v3"] == {"hit": 1, "miss": 1}
    assert editor._allocation_runtime_stats["batch_size"] == 2
    assert editor._allocation_runtime_stats["batch_count"] == 2
    assert editor._allocation_runtime_stats["cached_batch_count"] == 1
    assert editor._allocation_runtime_stats["pending_batch_count"] == 1
    assert editor._allocation_runtime_stats["actual_max_workers"] == 1
    assert editor._translation_structure_errors == []


def test_chinese_polish_rewrites_only_fixed_group_chinese_by_id():
    editor = _id_editor()
    editor.enable_chinese_polish = True
    item = editor._assign_global_subtitle_ids(_id_items(1))[0]
    item.original = "The system adapts to feedback."
    groups = [_id_group(1, 0, [item])]
    full_translations = {1: "系统会根据人类反馈不断调整。"}
    allocations = {1: {"S0001": "系统将"}}

    def request(prompt, payload, cache_task):
        assert cache_task == "screen_subtitle_semantic_chinese_polish_v3"
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": entry["subtitle_parts"][0]["subtitle_id"],
                            "zh": "系统会根据人类反馈不断调整。",
                        }
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        polished = editor._polish_semantic_group_translations(
            groups, full_translations, allocations
        )

    assert polished == {1: {"S0001": "系统会根据人类反馈不断调整。"}}
    assert item.original == "The system adapts to feedback."
    assert editor._chinese_polish_log[-1]["decision"] == "applied"


def test_chinese_polish_skips_natural_groups_without_a_model_request():
    editor = _id_editor()
    editor.enable_chinese_polish = True
    item = editor._assign_global_subtitle_ids(_id_items(1))[0]
    item.original = "The system adapts to feedback."
    groups = [_id_group(1, 0, [item])]
    full_translations = {1: "系统会根据人类反馈不断调整。"}
    allocations = {1: {"S0001": "系统会根据人类反馈不断调整。"}}

    with patch.object(editor, "_request_semantic_translation_allocation") as request:
        polished = editor._polish_semantic_group_translations(
            groups, full_translations, allocations
        )

    assert polished == allocations
    assert not request.called


def test_chinese_polish_selects_complex_comparison_group_by_fixed_ids():
    editor = _id_editor()
    editor.enable_chinese_polish = True
    items = editor._assign_global_subtitle_ids(_id_items(4))
    items[0].original = "They compared leading models"
    items[1].original = "against writing from The Economist,"
    items[2].original = "CNN, The New York Times,"
    items[3].original = "and novels published from 1950 to 2022."
    groups = [_id_group(1, 0, items)]
    full_translations = {
        1: "他们将顶尖模型的输出，与《经济学人》、CNN、《纽约时报》以及1950年至2022年的畅销小说进行比较。"
    }
    allocations = {
        1: {
            "S0001": "他们比较了顶尖模型——",
            "S0002": "与《经济学人》的写作，",
            "S0003": "CNN和《纽约时报》，",
            "S0004": "以及1950至2022年的畅销小说。",
        }
    }

    def request(prompt, payload, cache_task):
        assert cache_task == "screen_subtitle_semantic_chinese_polish_v3"
        assert payload[0]["subtitle_parts"][0]["target_zh_chars"] >= 4
        return {
            "groups": [{
                "id": 1,
                "part_translations": [
                    {"subtitle_id": "S0001", "zh": "他们将顶尖模型的输出，"},
                    {"subtitle_id": "S0002", "zh": "与《经济学人》的写作进行比较，"},
                    {"subtitle_id": "S0003", "zh": "对象还包括CNN和《纽约时报》，"},
                    {"subtitle_id": "S0004", "zh": "以及1950至2022年的畅销小说。"},
                ],
            }]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request) as call:
        polished = editor._polish_semantic_group_translations(
            groups, full_translations, allocations
        )

    assert call.called
    assert polished[1]["S0002"] == "与《经济学人》的写作进行比较，"
    assert any(
        "complex_enumeration_or_comparison_allocation" in item.get("issue_codes", [])
        for item in editor._chinese_polish_log
        if item.get("decision") == "selected"
    )
    applied = [item for item in editor._chinese_polish_log if item.get("decision") == "applied"]
    assert applied[-1]["quality_comparison"]["require_high_confidence_fix"] is False


def test_cross_subtitle_predicate_break_triggers_group_polish_by_fixed_ids():
    editor = _id_editor()
    editor.enable_chinese_polish = True
    items = [
        ScreenSubtitleItem([1], "A recent study found that the AI models", "", 0, 1),
        ScreenSubtitleItem([2], "currently drafting over a third of new websites", "", 2, 3),
        ScreenSubtitleItem([3], "have stopped using those words.", "", 4, 5),
    ]
    items = editor._assign_global_subtitle_ids(items)
    groups = [_id_group(1, 0, items)]
    full_translations = {
        1: "一项分析了120万个词的最新研究发现，如今超过三分之一的新网站由AI模型撰写，而这些模型已不再使用那些词。"
    }
    allocations = {
        1: {
            "S0001": "最近一项分析120万单词的研究发现",
            "S0002": "目前正在撰写超过三分之一新网站的AI模型",
            "S0003": "突然不再使用那些词了。",
        }
    }
    frozen_before = [
        (item.original, item.subtitle_id, item.word_start, item.word_end)
        for item in items
    ]

    entry = {
        "id": 1,
        "full_english": " ".join(item.original for item in items),
        "full_translation": full_translations[1],
        "subtitle_parts": [
            {"subtitle_id": item.subtitle_id, "english": item.original}
            for item in items
        ],
    }
    validation = editor._validate_group_chinese_allocation(entry, allocations[1])
    assert "cross_subtitle_predicate_break" in validation["issue_codes"]

    def request(prompt, payload, cache_task):
        assert cache_task == "screen_subtitle_semantic_chinese_polish_v3"
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "一项分析了120万个词的最新研究发现，"},
                        {"subtitle_id": "S0002", "zh": "如今超过三分之一的新网站由AI模型撰写，"},
                        {"subtitle_id": "S0003", "zh": "而这些模型已不再使用那些词。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request) as call:
        polished = editor._polish_semantic_group_translations(
            groups, full_translations, allocations
        )

    assert call.called
    assert polished[1]["S0002"] == "如今超过三分之一的新网站由AI模型撰写，"
    assert [
        (item.original, item.subtitle_id, item.word_start, item.word_end)
        for item in items
    ] == frozen_before
    assert editor._chinese_polish_log[-1]["decision"] == "applied"


def test_cross_subtitle_predicate_break_does_not_flag_normal_chinese_continuation():
    issues = ScreenSubtitleEditor._detect_cross_subtitle_predicate_breaks(
        ["S0001", "S0002", "S0003"],
        [
            "一项最新研究发现，",
            "如今超过三分之一的新网站由AI模型撰写，",
            "而这些模型已不再使用那些词。",
        ],
    )

    assert issues == []


def test_semantic_loss_recognizes_bingfei_as_negation():
    assert not ScreenSubtitleEditor._has_core_semantic_loss(
        "再看最新的人口普查数据和美联储研究，他并非个例。",
        "再看最新的人口普查数据和美联储研究，他并非个例。",
        "And looking at the latest census data and Federal Reserve research, he is not an outlier.",
    )


def test_sentence_final_shide_is_not_a_dangling_chinese_fragment():
    assert not ScreenSubtitleEditor._is_bad_chinese_fragment(
        "但到2025年，全职自雇人数创下百年新高。是的。"
    )


def test_allocation_concurrency_preserves_400_plus_subtitle_ids_without_drift():
    editor = _id_editor()
    editor.batch_num = 24
    editor.allocation_batch_size = 24
    editor.allocation_max_concurrency = 2
    items = editor._assign_global_subtitle_ids(_id_items(432))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 433)]
    full_translations = {index: f"full-{index}" for index in range(1, 433)}

    def request_api(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {
                                "subtitle_id": entry["subtitle_parts"][0]["subtitle_id"],
                                "zh": f"zh-{entry['subtitle_parts'][0]['subtitle_id']}",
                            }
                        ],
                    }
                    for entry in reversed(payload)
                ]
            },
            "",
        )

    with patch.object(editor, "_request_semantic_translation_allocation_api_only", side_effect=request_api):
        translations = editor._allocate_semantic_group_translations(groups, full_translations)
    applied = editor._apply_semantic_group_translations(items, groups, translations)

    assert [item.subtitle_id for item in applied] == [f"S{index:04d}" for index in range(1, 433)]
    assert [item.translated for item in applied] == [f"zh-S{index:04d}" for index in range(1, 433)]
    assert editor._translation_structure_errors == []


def test_allocation_quality_retries_information_leaked_to_previous_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Alice arrived."
    items[1].original = "Bob signed 42 contracts."
    groups = [_id_group(1, 0, items)]
    full_translations = {1: "爱丽丝到了。鲍勃签了42份合同。"}
    calls = []

    def request(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation_v3"):
        calls.append(cache_task)
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "鲍勃签了42份合同。"},
                            {"subtitle_id": "S0002", "zh": "爱丽丝到了。"},
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "爱丽丝到了。"},
                        {"subtitle_id": "S0002", "zh": "鲍勃签了42份合同。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert allocated[1] == {"S0001": "爱丽丝到了。", "S0002": "鲍勃签了42份合同。"}
    assert calls == [
        "screen_subtitle_semantic_translation_allocation_v3",
        "screen_subtitle_semantic_translation_allocation_retry_v3",
    ]
    assert any("number_allocation_mismatch" in item["issue_codes"] for item in editor._last_allocation_validation)
    assert editor._last_allocation_retry_log[-1]["success"] is True
    assert editor._translation_structure_errors == []


def test_allocation_quality_rejects_adjacent_core_duplication():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Alice arrived."
    items[1].original = "Bob left."
    entry = {
        "id": 1,
        "full_translation": "爱丽丝到了。鲍勃离开了。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": items[0].original},
            {"subtitle_id": "S0002", "english": items[1].original},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "鲍勃离开了。", "S0002": "鲍勃离开了。"},
    )

    assert not validation["valid"]
    assert "adjacent_chinese_semantic_duplication" in validation["issue_codes"]


def test_allocation_quality_rejects_adjacent_long_common_phrase_duplication():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "身边的人究竟是爱真实的我们，还是只是爱上了我们雇来替我们说话的算法？",
        "subtitle_parts": [
            {
                "subtitle_id": "S0001",
                "english": "if the people in our lives actually love us for who we are, or if they're",
            },
            {
                "subtitle_id": "S0002",
                "english": "just in love with the algorithm we hired to speak for us?",
            },
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "身边的人究竟是爱真实的我们，还是只是爱上了那个我们雇来替我们说话的算法呢",
            "S0002": "只是爱上了我们雇来替我们说话的算法吗？",
        },
    )

    assert not validation["valid"]
    assert "adjacent_chinese_semantic_duplication" in validation["issue_codes"]
    assert any(
        issue.get("reason") == "adjacent_long_common_phrase"
        for issue in validation["issues"]
    )


def test_allocation_quality_detects_negation_misplacement():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "方案可行。但它不能扩展。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "The plan works."},
            {"subtitle_id": "S0002", "english": "But it does not scale."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "它不能扩展。", "S0002": "方案可行。"},
    )

    assert not validation["valid"]
    assert "negation_allocation_mismatch" in validation["issue_codes"]


def test_allocation_quality_allows_negation_with_adjacent_predicate_completion():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "把工作当作巨大方程，难道不会剥夺我们的人性吗？",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "doesn't treating your life's work like"},
            {"subtitle_id": "S0002", "english": "a giant equation strip away our humanity?"},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "把工作当作",
            "S0002": "巨大方程，难道不会剥夺我们的人性吗？",
        },
    )

    assert validation["valid"]
    assert "negation_allocation_mismatch" not in validation["issue_codes"]


def test_allocation_quality_accepts_common_chinese_negation_equivalents():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "你无需担心。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "You do not need to worry."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "你无需担心。"},
    )

    assert validation["valid"]
    assert "negation_allocation_mismatch" not in validation["issue_codes"]


def test_allocation_quality_accepts_entity_spacing_equivalent():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "OpenAI released the model.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Open AI released the model."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "OpenAI released the model."},
    )

    assert validation["valid"]
    assert "entity_allocation_mismatch" not in validation["issue_codes"]
    assert "cross_id_semantic_leakage" not in validation["issue_codes"]


def test_allocation_quality_accepts_chinese_number_equivalents():
    editor = _id_editor()
    percent_entry = {
        "id": 1,
        "full_translation": "哦，百分之百。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Oh, 100%."},
        ],
    }
    percent_validation = editor._validate_group_chinese_allocation(
        percent_entry,
        {"S0001": "哦，百分之百。"},
    )

    hours_entry = {
        "id": 2,
        "full_translation": "这本书叫《八万小时》。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "The book is called 80 000 Hours."},
        ],
    }
    hours_validation = editor._validate_group_chinese_allocation(
        hours_entry,
        {"S0001": "这本书叫《八万小时》。"},
    )
    million_entry = {
        "id": 3,
        "full_translation": "拥有一千万并不会让你更快乐。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Having 10 million does not make you happier."},
        ],
    }
    million_validation = editor._validate_group_chinese_allocation(
        million_entry,
        {"S0001": "拥有一千万并不会让你更快乐。"},
    )
    blue_collar_entry = {
        "id": 5,
        "full_translation": "中国经济中蓝领工人的数量达到了4亿人。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "China has 400 million blue-collar workers."},
        ],
    }
    blue_collar_validation = editor._validate_group_chinese_allocation(
        blue_collar_entry,
        {"S0001": "中国经济中蓝领工人的数量达到了4亿人。"},
    )
    raised_entry = {
        "id": 6,
        "full_translation": "他们募集了579亿人民币。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "They raised 57.9 billion yuan."},
        ],
    }
    raised_validation = editor._validate_group_chinese_allocation(
        raised_entry,
        {"S0001": "他们募集了579亿人民币。"},
    )
    usd_entry = {
        "id": 7,
        "full_translation": "大约是86亿美元。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "That's about 8.6 billion U S."},
        ],
    }
    usd_validation = editor._validate_group_chinese_allocation(
        usd_entry,
        {"S0001": "大约是86亿美元。"},
    )
    decade_entry = {
        "id": 8,
        "full_translation": "他在21世纪初转向健美。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "He pivoted to bodybuilding in the early 2000 s."},
        ],
    }
    decade_validation = editor._validate_group_chinese_allocation(
        decade_entry,
        {"S0001": "他在21世纪初转向健美。"},
    )
    economists_entry = {
        "id": 4,
        "full_translation": "那两百位经济学家发出了警告。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Those 200 economists issued a warning."},
        ],
    }
    economists_validation = editor._validate_group_chinese_allocation(
        economists_entry,
        {"S0001": "那两百位经济学家发出了警告。"},
    )

    assert percent_validation["valid"]
    assert "number_allocation_mismatch" not in percent_validation["issue_codes"]
    assert hours_validation["valid"]
    assert "number_allocation_mismatch" not in hours_validation["issue_codes"]
    assert million_validation["valid"]
    assert "number_allocation_mismatch" not in million_validation["issue_codes"]
    assert blue_collar_validation["valid"]
    assert "number_allocation_mismatch" not in blue_collar_validation["issue_codes"]
    assert raised_validation["valid"]
    assert "number_allocation_mismatch" not in raised_validation["issue_codes"]
    assert usd_validation["valid"]
    assert "number_allocation_mismatch" not in usd_validation["issue_codes"]
    assert decade_validation["valid"]
    assert "number_allocation_mismatch" not in decade_validation["issue_codes"]
    assert economists_validation["valid"]
    assert "number_allocation_mismatch" not in economists_validation["issue_codes"]


def test_allocation_quality_accepts_decimal_wan_number_equivalent():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "salary is about 7.7万美元。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "salary is about 77 000 dollars."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "salary is about 7.7万美元。"},
    )

    assert validation["valid"]
    assert "number_allocation_mismatch" not in validation["issue_codes"]


def test_allocation_quality_allows_adjacent_number_when_target_line_is_not_degraded():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "You save lives, about 20 times more.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "you save about 20 times more lives"},
            {"subtitle_id": "S0002", "english": "than the baseline."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "you save lives,",
            "S0002": "about 20 times more than the baseline.",
        },
    )

    assert validation["valid"]
    assert "number_allocation_mismatch" not in validation["issue_codes"]


def test_allocation_quality_rejects_adjacent_number_when_target_line_is_empty():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "You save lives, about 20 times more.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "you save about 20 times more lives"},
            {"subtitle_id": "S0002", "english": "than the baseline."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "",
            "S0002": "you save lives, about 20 times more than the baseline.",
        },
    )

    assert not validation["valid"]
    assert "number_allocation_mismatch" in validation["issue_codes"]


def test_allocation_quality_accepts_natural_subtitle_half_sentence():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "她指出，做好事和追随热情并不意味着你必须发誓过贫穷的生活。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "She points out that doing good and following your passion doesn't mean"},
            {"subtitle_id": "S0002", "english": "you have to take a vow of poverty."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "她指出，做好事和追随热情并不意味着",
            "S0002": "你必须发誓过贫穷的生活。",
        },
    )

    assert validation["valid"]
    assert "unnatural_chinese_fragment" not in validation["issue_codes"]


def test_allocation_retry_rejects_quality_regression_before_writeback():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(3))
    items[0].original = "Alice arrived."
    items[1].original = "Bob signed 42 contracts."
    items[2].original = "Carol approved the long budget plan."
    groups = [_id_group(1, 0, items)]
    full_translations = {
        1: "爱丽丝到了。鲍勃签了42份合同。卡罗尔批准了这份长期预算计划。",
    }

    def request(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation_v3"):
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "爱丽丝到了。鲍勃签了42份合同。"},
                            {"subtitle_id": "S0002", "zh": "鲍勃签了合同。"},
                            {"subtitle_id": "S0003", "zh": "卡罗尔批准了这份长期预算计划。"},
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "爱丽丝到了。"},
                        {"subtitle_id": "S0002", "zh": "鲍勃签了42份合同。"},
                        {"subtitle_id": "S0003", "zh": "卡罗尔批准预算。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert allocated[1]["S0003"] == "卡罗尔批准了这份长期预算计划。"
    assert editor._last_allocation_retry_log[-1]["success"] is False
    assert editor._last_allocation_unresolved[-1]["reason"] == "retry_rejected_due_to_quality_regression"
    assert editor._last_allocation_retry_log[-1]["original_allocation"]
    assert editor._last_allocation_retry_log[-1]["retry_allocation"]
    assert editor._last_allocation_retry_log[-1]["quality_comparison"]["decision"] == "keep_original"


def test_compare_allocation_candidates_accepts_strict_improvement_only():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "Alice arrived. Bob signed 42 contracts.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Alice arrived."},
            {"subtitle_id": "S0002", "english": "Bob signed 42 contracts."},
        ],
    }
    original = {"S0001": "Bob signed 42 contracts.", "S0002": "Alice arrived."}
    retry = {"S0001": "Alice arrived.", "S0002": "Bob signed 42 contracts."}
    original_validation = editor._validate_group_chinese_allocation(entry, original)
    retry_validation = editor._validate_group_chinese_allocation(entry, retry)

    comparison = editor._compare_allocation_candidates(
        original_allocation=original,
        retry_allocation=retry,
        group_context=entry,
        original_validation=original_validation,
        retry_validation=retry_validation,
    )

    assert comparison["accepted"]
    assert comparison["decision"] == "accept_retry"
    assert "number_allocation_mismatch" in comparison["fixed_issue_codes"]
    assert comparison["new_issue_codes"] == []


def test_compare_allocation_candidates_rejects_new_high_confidence_issue():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "Alice arrived. Bob signed 42 contracts.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Alice arrived."},
            {"subtitle_id": "S0002", "english": "Bob signed 42 contracts."},
        ],
    }
    original = {"S0001": "Alice arrived.", "S0002": "Bob signed 42 contracts."}
    retry = {"S0001": "Bob signed 42 contracts.", "S0002": "Alice arrived."}
    original_validation = editor._validate_group_chinese_allocation(entry, original)
    retry_validation = editor._validate_group_chinese_allocation(entry, retry)

    comparison = editor._compare_allocation_candidates(
        original_allocation=original,
        retry_allocation=retry,
        group_context=entry,
        original_validation=original_validation,
        retry_validation=retry_validation,
    )

    assert not comparison["accepted"]
    assert comparison["decision"] == "keep_original"
    assert "new_high_confidence_issue" in comparison["reasons"]
    assert "number_allocation_mismatch" in comparison["new_issue_codes"]


def test_cross_id_leakage_requires_target_id_to_be_degraded():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "爱丽丝说明了背景。接着引用了Alice的原话。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Alice explained the context."},
            {"subtitle_id": "S0002", "english": "Then they quoted her exact words."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "她说明了背景。",
            "S0002": "接着引用了Alice的原话。",
        },
    )

    assert validation["valid"]
    assert "cross_id_semantic_leakage" not in validation["issue_codes"]


def test_cross_id_leakage_flags_when_target_id_is_consumed_and_empty():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "Alice说明了背景。下一句继续展开。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Alice explained the context."},
            {"subtitle_id": "S0002", "english": "The next sentence continued."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "",
            "S0002": "Alice说明了背景。下一句继续展开。",
        },
    )

    assert not validation["valid"]
    assert "cross_id_semantic_leakage" in validation["issue_codes"]


def test_allocation_quality_keeps_out_of_order_return_by_subtitle_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "The plan works."
    items[1].original = "It scales."
    groups = [_id_group(1, 0, items)]
    full_translations = {1: "方案可行。它可以扩展。"}

    def request(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation_v3"):
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0002", "zh": "它可以扩展。"},
                        {"subtitle_id": "S0001", "zh": "方案可行。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    applied = editor._apply_semantic_group_translations(items, groups, allocated)
    assert [item.translated for item in applied] == ["方案可行。", "它可以扩展。"]
    assert editor._translation_structure_errors == []


def test_allocation_quality_failed_group_does_not_shift_following_100_ids():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(101))
    items[0].original = "It does not work."
    items[1].original = "It is still broken."
    groups = [
        _id_group(1, 0, items[:2]),
        *[_id_group(index, index, [items[index]]) for index in range(2, 101)],
    ]
    full_translations = {1: "它不能工作，问题仍未解决。", **{index: f"中文{index}" for index in range(2, 101)}}

    def request(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation_v3"):
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": part["subtitle_id"],
                            "zh": "" if entry["id"] == 1 else f"中文{entry['id']}",
                        }
                        for part in entry["subtitle_parts"]
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    applied = editor._apply_semantic_group_translations(items, groups, allocated)
    assert [item.subtitle_id for item in applied] == [f"S{index:04d}" for index in range(1, 102)]
    assert applied[100].translated == "中文100"
    assert editor._last_allocation_unresolved


def test_compression_quality_regression_restores_previous_group_allocation():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Alice arrived."
    items[1].original = "Bob left."
    group = _id_group(1, 0, items)
    editor._last_semantic_full_translations = {1: "爱丽丝到了。鲍勃离开了。"}
    before = [
        ASRDataSeg("Alice arrived.", 0, 1000, "爱丽丝到了。"),
        ASRDataSeg("Bob left.", 1000, 2000, "鲍勃离开了。"),
    ]
    after = [
        ASRDataSeg("Alice arrived.", 0, 1000, "鲍勃离开了。"),
        ASRDataSeg("Bob left.", 1000, 2000, "鲍勃离开了。"),
    ]
    for index, seg in enumerate(before + after):
        seg.subtitle_id = f"S{index % 2 + 1:04d}"

    restored = editor._restore_invalid_postprocess_allocations(
        before_segments=before,
        after_segments=after,
        semantic_groups=[group],
        subtitle_items=items,
    )

    assert [seg.translated_text for seg in restored] == ["爱丽丝到了。", "鲍勃离开了。"]
    assert editor._last_allocation_unresolved[-1]["reason"] == "postprocess_allocation_quality_regression_restored"


def test_speed_compression_cannot_accept_number_omission_for_shorter_chinese():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(1))
    items[0].original = "Alice successfully reached the annual sales target in 2024."
    group = _id_group(1, 0, items)
    full_translation = "爱丽丝在2024年成功达成了年度销售目标。"
    editor._last_semantic_full_translations = {1: full_translation}
    before = [
        ASRDataSeg(items[0].original, 0, 1000, full_translation),
    ]
    after = [
        ASRDataSeg(items[0].original, 0, 1000, "爱丽丝达成销售目标。"),
    ]
    before[0].subtitle_id = "S0001"
    after[0].subtitle_id = "S0001"

    restored = editor._restore_invalid_postprocess_allocations(
        before_segments=before,
        after_segments=after,
        semantic_groups=[group],
        subtitle_items=items,
    )

    assert restored[0].translated_text == full_translation
    comparison = editor._last_allocation_unresolved[-1]["candidate_comparison"]
    assert comparison["speed_improved"] is True
    assert "new_high_confidence_issue" in comparison["reasons"]


def test_id_bound_candidate_decision_never_accepts_invalid_candidate():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "爱丽丝到了。",
        "subtitle_parts": [{"subtitle_id": "S0001", "english": "Alice arrived."}],
    }
    allocation = {"S0001": "爱丽丝到了。"}
    decision = editor._decide_id_bound_allocation_candidate(
        original_allocation=allocation,
        candidate_allocation=allocation,
        group_context=entry,
        original_validation={"valid": True, "issue_codes": []},
        candidate_validation={
            "valid": False,
            "issue_codes": ["translation_group_cardinality_mismatch"],
        },
        candidate_source="test",
        require_high_confidence_fix=False,
    )

    assert not decision["accepted"]
    assert decision["decision"] == "keep_original"
    assert decision["candidate_source"] == "test"


def test_editor_review_points_only_include_long_split_allocation_mismatch():
    editor = _id_editor()
    segments = []
    for index in range(1, 5):
        seg = ASRDataSeg(
            text=f"English {index}",
            start_time=index * 1000,
            end_time=index * 1000 + 800,
            translated_text=f"中文{index}",
        )
        seg.subtitle_id = f"S{index:04d}"
        segments.append(seg)

    editor._last_allocation_unresolved = [
        {
            "semantic_group_id": "G0001",
            "reason": "retry_quality_failed",
            "issue_codes": ["number_allocation_mismatch"],
            "full_english": "Then in the 2000 s they joined the World Trade Organisation.",
            "full_translation": "然后，在21世纪初，中国加入了世界贸易组织。",
            "allocation": {"S0001": "然后，在21世纪初，", "S0002": "中国加入了世界贸易组织。"},
        },
        {
            "semantic_group_id": "G0002",
            "reason": "retry_quality_failed",
            "issue_codes": ["unnatural_chinese_fragment"],
            "full_english": "Short answer.",
            "full_translation": "短回答。",
            "allocation": {"S0003": "短回答。"},
        },
    ]

    points = editor._editor_review_points(segments)
    assert len(points) == 1
    assert points[0]["subtitle_ids"] == ["S0001", "S0002"]
    assert points[0]["end_ms"] == segments[1].end_time
    srt = editor._review_points_to_srt(points)
    assert "[QA] S0001-S0002" in srt
    assert "G0001" in srt
    assert "S0001 EN" in srt
    assert "S0002 EN" in srt
    assert "S0003" not in srt


def test_empty_middle_translation_keeps_its_own_id_slot():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(3))
    group = _id_group(1, 0, items)

    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0002", "zh": ""},
            {"subtitle_id": "S0003", "zh": "zh-S0003"},
        ],
    )
    applied = editor._apply_semantic_group_translations(items, [group], {1: translations})
    editor._validate_final_item_translation_ids(applied)

    assert [item.subtitle_id for item in applied] == ["S0001", "S0002", "S0003"]
    assert applied[1].translated == ""
    assert applied[2].translated == "zh-S0003"
    final_errors = [
        issue for issue in editor._translation_structure_errors
        if issue["code"] == "final_translation_id_mismatch"
    ]
    assert final_errors and final_errors[0]["missing_subtitle_ids"] == ["S0002"]


def test_numeric_only_subtitle_keeps_semantic_group_id_slot():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(
        [
            ScreenSubtitleItem(
                original="Imports rose sharply.",
                translated="",
                start_ms=0,
                end_ms=1000,
                source_ids=[1],
                word_start=0,
                word_end=2,
            ),
            ScreenSubtitleItem(
                original="70%.",
                translated="",
                start_ms=1000,
                end_ms=1600,
                source_ids=[2],
                word_start=3,
                word_end=3,
            ),
            ScreenSubtitleItem(
                original="That is a wild jump.",
                translated="",
                start_ms=1600,
                end_ms=2600,
                source_ids=[3],
                word_start=4,
                word_end=8,
            ),
        ]
    )

    groups = editor._semantic_translation_groups(items)
    grouped_ids = [
        subtitle_id
        for group in groups
        for subtitle_id in editor._group_expected_subtitle_ids(group)
    ]

    assert grouped_ids == ["S0001", "S0002", "S0003"]
    assert any(group["items"][0].original == "70%." for group in groups)


def test_failed_group_does_not_shift_following_100_subtitles():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(104))
    first = _id_group(1, 0, items[:4])
    tail = _id_group(2, 4, items[4:])
    first_translations = editor._parse_id_bound_translations(
        first,
        editor._group_expected_subtitle_ids(first),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0002", "zh": "zh-S0002"},
            {"subtitle_id": "S0004", "zh": "zh-S0004"},
        ],
    )
    tail_translations = editor._parse_id_bound_translations(
        tail,
        editor._group_expected_subtitle_ids(tail),
        [
            {"subtitle_id": item.subtitle_id, "zh": f"zh-{item.subtitle_id}"}
            for item in items[4:]
        ],
    )

    applied = editor._apply_semantic_group_translations(
        items,
        [first, tail],
        {1: first_translations, 2: tail_translations},
    )

    assert applied[2].subtitle_id == "S0003"
    assert applied[2].translated == ""
    assert all(item.translated == f"zh-{item.subtitle_id}" for item in applied[4:])


def test_whisperx_time_only_preserves_text_and_translation_while_retiming():
    source = ASRData([
        ASRDataSeg("Welcome to today's Deep Dive. We are unpacking the story.", 1000, 4300),
    ])
    ledger = ASRData([
        ASRDataSeg("Welcome", 1000, 1100),
        ASRDataSeg("to", 1100, 1200),
        ASRDataSeg("today's", 1200, 1400),
        ASRDataSeg("Deep", 1400, 1600),
        ASRDataSeg("Dive.", 1600, 1800),
        ASRDataSeg("We", 2600, 2700),
        ASRDataSeg("are", 2700, 2800),
        ASRDataSeg("unpacking", 2800, 3200),
        ASRDataSeg("the", 3200, 3300),
        ASRDataSeg("story.", 3300, 3600),
    ])
    aligned_words = [
        {"text": "Welcome", "start": 1.22, "end": 1.45},
        {"text": "to", "start": 1.46, "end": 1.56},
        {"text": "today's", "start": 1.57, "end": 1.82},
        {"text": "Deep", "start": 1.83, "end": 2.03},
        {"text": "Dive", "start": 2.04, "end": 2.25},
        {"text": "We", "start": 2.92, "end": 3.05},
        {"text": "are", "start": 3.06, "end": 3.18},
        {"text": "unpacking", "start": 3.19, "end": 3.55},
        {"text": "the", "start": 3.56, "end": 3.66},
        {"text": "story", "start": 3.67, "end": 3.96},
    ]

    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        remapped = align_frozen_word_ledger_with_whisperx("unused.m4a", source, ledger)

    assert remapped is not None
    by_word_id = {segment.word_id: segment for segment in remapped.segments}
    assert [by_word_id[index].text for index in range(10)] == [
        segment.text for segment in ledger.segments
    ]
    assert by_word_id[0].start_time == 1220
    assert by_word_id[9].end_time == 3960
    assert all(by_word_id[index].alignment_source == "whisperx" for index in range(10))


def test_whisperx_frozen_ledger_keeps_only_unmatched_word_on_stable_ts_time():
    source = ASRData([ASRDataSeg("One two three.", 1000, 1600)])
    ledger = ASRData(
        [
            ASRDataSeg("One", 1000, 1100),
            ASRDataSeg("two", 1110, 1220),
            ASRDataSeg("three", 1230, 1400),
        ]
    )
    aligned_words = [
        {"text": "One", "start": 1.01, "end": 1.09},
        {"text": "three", "start": 1.30, "end": 1.52},
    ]

    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        remapped = align_frozen_word_ledger_with_whisperx("unused.m4a", source, ledger)

    assert remapped is not None
    by_word_id = {segment.word_id: segment for segment in remapped.segments}
    assert (by_word_id[0].start_time, by_word_id[0].end_time) == (1010, 1090)
    assert (by_word_id[1].start_time, by_word_id[1].end_time) == (1110, 1220)
    assert (by_word_id[2].start_time, by_word_id[2].end_time) == (1300, 1520)
    assert by_word_id[1].alignment_source == "stable-ts-fallback"
    assert remapped.whisperx_matched_word_count == 2
    assert remapped.whisperx_fallback_word_count == 1


def test_whisperx_frozen_ledger_reverts_a_candidate_that_inverts_fallback_word_order():
    source = ASRData([ASRDataSeg("and 15 000", 592140, 593020)])
    ledger = ASRData(
        [
            ASRDataSeg("and", 592140, 592260),
            ASRDataSeg("15", 592260, 592640),
            ASRDataSeg("000", 592640, 593020),
        ]
    )
    aligned_words = [{"text": "and", "start": 592.917, "end": 593.017}]

    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        remapped = align_frozen_word_ledger_with_whisperx("unused.m4a", source, ledger)

    assert remapped is not None
    by_word_id = {segment.word_id: segment for segment in remapped.segments}
    assert (by_word_id[0].start_time, by_word_id[0].end_time) == (592140, 592260)
    assert by_word_id[0].alignment_source == "stable-ts-fallback"
    assert [(segment.word_id, segment.text) for segment in remapped.segments] == [
        (0, "and"),
        (1, "15"),
        (2, "000"),
    ]
    assert remapped.whisperx_monotonicity_fallbacks == [
        {
            "code": "whisperx_monotonicity_fallback",
            "word_id": 0,
            "word": "and",
            "baseline_range_ms": [592140, 592260],
            "rejected_whisperx_range_ms": [592917, 593017],
            "conflicting_word_ids": [0, 1],
        }
    ]


def test_whisperx_frozen_ledger_keeps_monotonic_candidate_updates():
    source = ASRData([ASRDataSeg("One two", 1000, 1300)])
    ledger = ASRData([ASRDataSeg("One", 1000, 1100), ASRDataSeg("two", 1120, 1300)])
    aligned_words = [
        {"text": "One", "start": 1.20, "end": 1.30},
        {"text": "two", "start": 1.31, "end": 1.46},
    ]

    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        remapped = align_frozen_word_ledger_with_whisperx("unused.m4a", source, ledger)

    assert remapped is not None
    by_word_id = {segment.word_id: segment for segment in remapped.segments}
    assert (by_word_id[0].start_time, by_word_id[1].end_time) == (1200, 1460)
    assert all(by_word_id[index].alignment_source == "whisperx" for index in range(2))
    assert remapped.whisperx_monotonicity_fallbacks == []


def test_whisperx_time_only_falls_back_to_stable_ledger_without_changing_cues():
    class _Progress:
        def __init__(self):
            self.events = []

        def emit(self, *args):
            self.events.append(args)

    class _FallbackEditor:
        def __init__(self):
            self.alignment = None
            self.rebuild_backend = None

        def record_final_timeline_alignment(self, **kwargs):
            self.alignment = kwargs

        def rebuild_final_cue_timeline(self, asr_data, word_ledger, *, alignment_backend):
            self.rebuild_backend = alignment_backend
            return asr_data

    thread = SubtitleThread.__new__(SubtitleThread)
    thread.task = type("Task", (), {"video_path": __file__})()
    thread.progress = _Progress()
    thread.tr = lambda value: value
    thread._record_stage_duration = lambda *args: None
    source = ASRData([ASRDataSeg("A stable cue.", 1000, 1600, "稳定字幕。")])
    source.segments[0].subtitle_id = "S0001"
    ledger = ASRData([ASRDataSeg("A", 1000, 1100), ASRDataSeg("stable", 1110, 1350)])
    editor = _FallbackEditor()

    with patch.object(SubtitleThread, "_timeline_alignment_backend", return_value="whisperx-time-only"), patch(
        "app.thread.subtitle_thread.align_frozen_word_ledger_with_whisperx",
        return_value=None,
    ):
        rebuilt = thread._apply_whisperx_time_only_if_enabled(
            source,
            alignment_source=source,
            word_ledger=ledger,
            screen_editor=editor,
        )

    assert rebuilt is source
    assert editor.rebuild_backend == "stable-ts-fallback"
    assert editor.alignment == {
        "requested_backend": "whisperx-time-only",
        "applied_backend": "stable-ts-fallback",
        "fallback_reason": "incomplete_frozen_word_ledger",
    }
    assert any("稳定词级时间轴" in event[1] for event in thread.progress.events)


def test_whisperx_time_only_uses_expanded_frozen_ledger_not_source_segment_count():
    """Final alignment must consume display words, not the coarser ASR spans.

    Stable cutting can expand a single ASR word span such as ``twenty-one``
    into several frozen display words.  The final alignment contract is the
    frozen ledger, even when it has more entries than the original ASR input.
    """
    class _Progress:
        def emit(self, *args):
            pass

    class _LedgerEditor:
        def __init__(self):
            self.alignment = None
            self.rebuilt_word_ids = []

        def record_final_timeline_alignment(self, **kwargs):
            self.alignment = kwargs

        def rebuild_final_cue_timeline(self, asr_data, word_ledger, *, alignment_backend):
            self.rebuilt_word_ids = [segment.word_id for segment in word_ledger.segments]
            assert alignment_backend == "whisperx-time-only"
            return asr_data

    thread = SubtitleThread.__new__(SubtitleThread)
    thread.task = type("Task", (), {"video_path": __file__})()
    thread.progress = _Progress()
    thread.tr = lambda value: value
    thread._record_stage_duration = lambda *args: None

    # Three original ASR spans expand into five frozen display words.
    alignment_source = ASRData(
        [
            ASRDataSeg("twenty-one", 0, 320),
            ASRDataSeg("founders", 330, 640),
            ASRDataSeg("arrived.", 650, 900),
        ]
    )
    final_cues = ASRData([ASRDataSeg("Twenty one founders arrived.", 0, 900, "二十一位创始人到了。")])
    final_cues.segments[0].subtitle_id = "S0001"
    ledger = ASRData(
        [
            ASRDataSeg("Twenty", 0, 120),
            ASRDataSeg("one", 120, 320),
            ASRDataSeg("founders", 330, 640),
            ASRDataSeg("arrived", 650, 820),
            ASRDataSeg(".", 820, 900),
        ]
    )
    for word_id, segment in enumerate(ledger.segments):
        segment.word_id = word_id
        segment.alignment_source = "whisperx"
    editor = _LedgerEditor()

    with patch.object(SubtitleThread, "_timeline_alignment_backend", return_value="whisperx-time-only"), patch(
        "app.thread.subtitle_thread.align_frozen_word_ledger_with_whisperx",
        return_value=ledger,
    ) as align:
        rebuilt = thread._apply_whisperx_time_only_if_enabled(
            final_cues,
            alignment_source=alignment_source,
            word_ledger=ledger,
            screen_editor=editor,
        )

    assert rebuilt is final_cues
    assert len(alignment_source.segments) == 3
    assert len(ledger.segments) == 5
    assert align.call_args.args[2] is ledger
    assert editor.rebuilt_word_ids == [0, 1, 2, 3, 4]
    assert editor.alignment["applied_backend"] == "whisperx-time-only"


def test_short_nonindependent_backchannel_attaches_to_previous_display_item():
    previous_words = "This explanation has fourteen ordinary words and ends as a complete thought clearly today".split()
    words = previous_words + ["Yeah.", "The", "next", "sentence", "continues."]
    editor = _marker_editor(words, max_words=16)
    items = [
        _word_item(editor, 0, len(previous_words) - 1, 1),
        _word_item(editor, len(previous_words), len(previous_words), 2),
        _word_item(editor, len(previous_words) + 1, len(words) - 1, 3),
    ]

    merged = editor._merge_short_display_items(items)

    assert len(merged) == 2
    assert merged[0].original.endswith("Yeah.")
    assert ScreenSubtitleEditor._word_count(merged[0].original) == 15
    assert merged[1].original == "The next sentence continues."
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_complete_unsplittable_overflow_is_warning_not_overlong_error():
    text = "A precise compact sentence keeps every protected grammatical relation intact through this final complete clause cleanly today."
    editor = _marker_editor(text.split(), max_words=16)
    segment = ASRDataSeg(text, 0, 3200, "完整中文。")
    segment.subtitle_id = "S0001"
    segment.word_start = 0
    segment.word_end = len(editor._active_word_entries) - 1
    editor._safe_overlong_item_split = lambda item: ([], [])

    structural = editor._structural_english_overflow_issues([segment])
    overlong = editor._overlong_english_issues([segment])

    assert len(structural) == 1
    assert overlong == []
    health = {
        "overlong_english": overlong,
        "structural_english_overflow": structural,
        "bad_cuts": [],
        "translationese": [],
        "reading_speed_errors": [],
        "reading_speed_warnings": [],
        "duration_errors": [],
        "duration_warnings": [],
        "duplicate_chinese": [],
        "asr_suspicious": [],
        "discourse_marker_orphans": [],
        "syntax_boundary_audit": [],
        "chinese_semantic_group_warnings": [],
        "chinese_semantic_group_info": [],
    }
    summary = editor._validation_summary([], [], health, [segment])

    assert summary["errors"] == []
    assert [issue["code"] for issue in summary["warnings"]] == ["structural_english_overflow"]


def test_comma_terminated_parser_confirmed_subordinate_overflow_is_warning_not_error():
    text = "Yeah. And now that mobile coffee cart is bringing in between 10 000 and 15 000 every single month,"
    editor = _marker_editor(text.split(), max_words=16)
    segment = ASRDataSeg(text, 0, 6000, "完整中文。")
    segment.subtitle_id = "S0001"
    segment.word_start = 0
    segment.word_end = len(editor._active_word_entries) - 1
    editor._safe_overlong_item_split = lambda item: ([], [])

    assert editor._word_count(text) == 19
    assert editor._is_allowed_structural_english_overflow(segment, text, 19, 16)
    assert editor._overlong_english_issues([segment]) == []
    assert len(editor._structural_english_overflow_issues([segment])) == 1


def test_comma_overflow_requires_parser_proof_and_no_safe_split():
    text = "Yeah. And now that mobile coffee cart is bringing in between 10 000 and 15 000 every single month,"
    editor = _marker_editor(text.split(), max_words=16)
    segment = ASRDataSeg(text, 0, 6000, "完整中文。")
    segment.word_start = 0
    segment.word_end = len(editor._active_word_entries) - 1
    editor._safe_overlong_item_split = lambda item: ([], [])

    with patch.object(editor, "_load_syntax_nlp", return_value=None):
        assert not editor._is_allowed_structural_english_overflow(segment, text, 19, 16)

    editor._safe_overlong_item_split = lambda item: ([item], [])
    assert not editor._is_allowed_structural_english_overflow(segment, text, 19, 16)


def test_visual_reading_budget_keeps_complete_13_word_cue_for_renderer_wrapping():
    words = "The market changed quickly after years of steady growth, and investors are responding.".split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_keeps_character_heavy_cue_for_renderer_wrapping():
    words = "Internationalization creates a comprehensive institutional transformation across decentralized communities today.".split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)

    assert ScreenSubtitleEditor._word_count(original.original) <= 12
    assert editor._visible_english_character_count(original.original) > 68

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_never_selects_preposition_object_cut():
    words = "She is the founder of a non-profit organization that helps young people find careers.".split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_does_not_create_a_review_for_renderer_wrapping():
    words = "The market changed quickly after years of steady growth, and investors took notice.".split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)
    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_keeps_short_open_phrase_with_its_sentence():
    words = (
        "It turns out that the most famous giveaway of AI-generated text, "
        "the word delve, signals a formulaic style."
    ).split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)

    repaired = editor._apply_visual_reading_budget([original])

    assert all(item.original != "the word delve," for item in repaired)
    phrase = _word_item(editor, 11, 13, 1)
    issues = editor._visual_split_display_unit_issues(phrase, None, None)
    assert "visual_open_phrase_fragment" in issues


def test_visual_reading_budget_keeps_a_single_clause_for_renderer_wrapping():
    words = (
        "But the thing I keep coming back to is how fast this is evolving."
    ).split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_rejects_short_preposition_led_display_tail():
    words = "Our editors write clear explanations with punchy statements.".split()
    editor = _marker_editor(words, max_words=16)
    tail = _word_item(editor, 5, len(words) - 1, 1)

    issues = editor._visual_split_display_unit_issues(tail, _word_item(editor, 0, 4, 1), None)

    assert "visual_preposition_led_fragment" in issues


def test_visual_reading_budget_never_creates_parser_confirmed_example_preposition_cut():
    words = (
        "Researchers still look for outdated clues like excessive em dashes "
        "in generated prose today."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)

    evaluation = editor._evaluate_stable_cut_boundary(6, 7)
    repaired = editor._apply_visual_reading_budget([original])

    assert "preposition_object_split" in evaluation["hard_issues"]
    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_stable_cut_keeps_comma_bracketed_adverb_with_preceding_list_item():
    words = (
        "I mean, the stakes here are massive for you, for me, really, "
        "for anyone reading anything on the screen right now."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(10, 11)
    ranges = editor._stable_word_ranges_for_span((0, len(words) - 1))

    assert "comma_bracketed_adverb_split" in evaluation["hard_issues"]
    assert ranges == [(0, 11), (12, len(words) - 1)]
    assert [
        " ".join(words[start:end + 1])
        for start, end in ranges
    ] == [
        "I mean, the stakes here are massive for you, for me, really,",
        "for anyone reading anything on the screen right now.",
    ]


def test_visual_budget_keeps_subject_with_delayed_finite_predicate():
    words = "Yeah. Well, the judges specifically praised its, quote, quiet authority.".split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)

    evaluation = editor._evaluate_stable_cut_boundary(3, 4)
    repaired = editor._apply_visual_reading_budget([original])

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert repaired == [original]


def test_visual_budget_keeps_short_gerundial_manner_phrase_with_main_question():
    words = "How can you actually spot the ghost in the machine using your own eyes?".split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    evaluation = editor._evaluate_stable_cut_boundary(9, 10)
    repaired = editor._apply_visual_reading_budget([original])
    preposition_tail = _word_item(editor, 7, len(words) - 1, 1)

    assert "short_gerundial_modifier_split" in evaluation["hard_issues"]
    assert repaired == [original]
    assert "visual_preposition_led_fragment" in editor._visual_split_display_unit_issues(
        preposition_tail,
        _word_item(editor, 0, 6, 1),
        None,
    )
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before


def _add_visual_pause(editor, cut_after, pause_ms):
    original_pause = (
        editor._active_word_entries[cut_after + 1]["start_time"]
        - editor._active_word_entries[cut_after]["end_time"]
    )
    delta = pause_ms - original_pause
    for entry in editor._active_word_entries[cut_after + 1:]:
        entry["start_time"] += delta
        entry["end_time"] += delta


def test_visual_temporal_budget_splits_punctuated_fronted_introduction():
    words = (
        "Reading about these polysyllables and nominalizations, "
        "it immediately brings George Orwell to mind."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 5, 420)
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    repaired = editor._apply_visual_reading_budget([original])

    assert [item.original for item in repaired] == [
        "Reading about these polysyllables and nominalizations,",
        "it immediately brings George Orwell to mind.",
    ]
    assert [item.word_start for item in repaired] == [0, 6]
    assert [item.word_end for item in repaired] == [5, 12]
    assert editor._pre_id_boundary_repairs[0]["visual_temporal_category"] == (
        "fronted_introduction_boundary"
    )
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before


def test_visual_temporal_budget_splits_complete_punctuated_clauses():
    words = (
        "Humans might say things are connected, but the AI talks about "
        "their interdependence."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 5, 420)

    repaired = editor._apply_visual_reading_budget([original])

    assert [item.original for item in repaired] == [
        "Humans might say things are connected,",
        "but the AI talks about their interdependence.",
    ]
    assert editor._pre_id_boundary_repairs[0]["visual_temporal_category"] == (
        "complete_clause_boundary"
    )


def test_visual_temporal_budget_splits_complete_sentence_terminal():
    words = (
        "The first report confirms a meaningful trend. The next report explains "
        "the remaining uncertainty."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 6, 180)

    repaired = editor._apply_visual_reading_budget([original])

    assert [item.original for item in repaired] == [
        "The first report confirms a meaningful trend.",
        "The next report explains the remaining uncertainty.",
    ]
    assert editor._pre_id_boundary_repairs[0]["visual_temporal_category"] == (
        "sentence_terminal"
    )


def test_visual_temporal_budget_keeps_subject_with_delayed_predicate_despite_pause():
    words = (
        "You know, this robotic vocabulary actually connects to a very human "
        "critique from way back."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 4, 280)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []
    evaluation = editor._evaluate_stable_cut_boundary(4, 5)
    assert "subject_finite_verb_split" in evaluation["hard_issues"]


def test_visual_temporal_budget_rejects_punctuated_conditional_intro():
    words = "If I normally say, uh, I'm going to eat a sandwich for lunch.".split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 4, 320)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_final_timeline_rebuild_preserves_id_text_chinese_and_word_ownership():
    editor = _editor()
    editor._active_word_entries = [
        {"token": "i", "surface": "I", "start_time": 553220, "end_time": 553340},
        {"token": "mean", "surface": "mean", "start_time": 553350, "end_time": 553500},
        {"token": "the", "surface": "the", "start_time": 553510, "end_time": 553620},
        {"token": "delve", "surface": "Delve", "start_time": 553630, "end_time": 553900},
        {"token": "era", "surface": "era", "start_time": 553910, "end_time": 554100},
        {"token": "is", "surface": "is", "start_time": 554110, "end_time": 554220},
        {"token": "over", "surface": "over.", "start_time": 554230, "end_time": 555720},
        {"token": "why", "surface": "Why", "start_time": 555730, "end_time": 555960},
    ]
    editor._frozen_subtitle_ids = ["S0187", "S0188"]
    final_data = ASRData(
        [
            ASRDataSeg("I mean, the Delve era is over.", 553180, 555284, "我的意思是，Delve时代结束了。"),
            ASRDataSeg("Why does its style change so rapidly?", 555324, 557100, "为什么它的风格变化这么快？"),
        ]
    )
    for index, segment in enumerate(final_data.segments):
        segment.subtitle_id = editor._frozen_subtitle_ids[index]
        segment.word_start = 0 if index == 0 else 7
        segment.word_end = 6 if index == 0 else 7
    final_data.segments.reverse()

    ledger = ASRData([])
    for word_id, entry in enumerate(editor._active_word_entries):
        word = ASRDataSeg(entry["surface"], entry["start_time"], entry["end_time"])
        word.word_id = word_id
        word.alignment_source = "whisperx"
        ledger.segments.append(word)

    before = {
        segment.subtitle_id: (
            segment.text,
            segment.translated_text,
            segment.word_start,
            segment.word_end,
        )
        for segment in final_data.segments
    }
    rebuilt = editor.rebuild_final_cue_timeline(
        final_data,
        ledger,
        alignment_backend="whisperx-time-only",
    )
    after = {
        segment.subtitle_id: (
            segment.text,
            segment.translated_text,
            segment.word_start,
            segment.word_end,
        )
        for segment in rebuilt.segments
    }

    assert after == before
    assert [segment.subtitle_id for segment in rebuilt.segments] == ["S0187", "S0188"]
    assert rebuilt.segments[0].end_time >= 555720
    assert editor._final_cue_timeline["validation"]["status"] == "PASS"
    assert editor._final_cue_timeline["expected_subtitle_ids"] == ["S0187", "S0188"]
    assert [record["subtitle_id"] for record in editor._final_cue_timeline["records"]] == [
        "S0187",
        "S0188",
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "final.srt"
        rebuilt.to_srt(save_path=str(output), layout="原文在上")
        rendered = output.read_text(encoding="utf-8-sig")
    assert "I mean, the Delve era is over." in rendered
    assert "我的意思是，Delve时代结束了。" in rendered


def test_forced_alignment_finalization_never_moves_timing():
    editor = _editor()
    asr_data = ASRData([
        ASRDataSeg("A short line.", 1000, 1220, "一条很短的字幕。"),
        ASRDataSeg("The next line.", 1260, 2200, "下一条字幕。"),
    ])
    for index, seg in enumerate(asr_data.segments, 1):
        seg.subtitle_id = f"S{index:04d}"
    before = [(seg.start_time, seg.end_time) for seg in asr_data.segments]
    editor._last_semantic_groups = []
    editor._last_subtitle_items = []
    editor._write_coverage_report = lambda *args, **kwargs: None

    repaired = editor.repair_after_final_time_alignment(
        asr_data,
        preserve_aligned_timing=True,
    )

    assert [(seg.start_time, seg.end_time) for seg in repaired.segments] == before


def test_failed_validation_does_not_write_final_output_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        task = SubtitleTask(
            subtitle_path=str(root / "source.srt"),
            output_path=str(root / "output.ass"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )
        summary = {
            "status": "ERROR",
            "errors": [{"code": "final_translation_id_mismatch"}],
            "warnings": [],
            "info": [],
        }

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English 1.", 0, 1000, "")]),
            config,
            coverage_report_path=str(root / "coverage-report.txt"),
            validation_status="failed",
            validation_summary=summary,
        )

        manifest = json.loads((root / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert manifest["render_blocked"] is True
        assert not (root / "output.ass").exists()
        assert Path(manifest["paths"]["original_top_srt"]).exists()


def test_non_structural_validation_errors_do_not_block_render_gate():
    editor = _id_editor()
    editor._translation_structure_errors = []
    editor.last_validation_summary = {
        "status": "ERROR",
        "errors": [{"code": "subtitle_duration_invalid"}],
        "warnings": [],
        "info": [],
    }

    assert editor.has_blocking_validation_errors() is False
    assert editor.blocking_validation_message() == ""


def test_final_segment_count_mismatch_is_structural_error():
    editor = _id_editor()
    editor._assign_global_subtitle_ids(_id_items(4))

    segments = [
        ASRDataSeg("English 1.", 0, 1000, "zh-S0001"),
        ASRDataSeg("English 2.", 1000, 2000, "zh-S0002"),
        ASRDataSeg("English 4.", 3000, 4000, "zh-S0004"),
    ]
    for segment, subtitle_id in zip(segments, ["S0001", "S0002", "S0004"]):
        segment.subtitle_id = subtitle_id
    editor._validate_final_segment_translation_ids(segments)

    assert "final_translation_id_mismatch" in _codes(editor)
    assert editor._translation_structure_errors[-1]["missing_subtitle_ids"] == ["S0003"]


def test_merge_preserves_ids_when_order_changes_before_final_write():
    editor = _id_editor()
    segments = _id_segments(4)
    editor._frozen_subtitle_ids = ["S0001", "S0002", "S0003", "S0004"]

    shuffled = [segments[2], segments[0], segments[3], segments[1]]
    ordered = editor._order_segments_by_frozen_subtitle_ids(shuffled)

    assert [seg.subtitle_id for seg in ordered] == editor._frozen_subtitle_ids
    assert [seg.text for seg in ordered] == [seg.text for seg in segments]


def test_repair_only_modifies_the_target_subtitle_id():
    editor = _id_editor()
    segments = _id_segments(3)
    segments[1].translated_text = "LONG_TARGET"

    def severe(seg):
        return seg.translated_text == "LONG_TARGET"

    def request(prompt, payload, task, temperature):
        return {"items": [{"index": 1, "chinese": "这是修复文本"}]}

    with patch.object(editor, "_is_severe_chinese_speed", side_effect=severe), patch.object(
        editor, "_request_chinese_compression", side_effect=request
    ):
        repaired = editor._compress_fast_chinese_segments(segments)

    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002", "S0003"]
    assert repaired[0].translated_text == "这是原文"
    assert repaired[1].translated_text == "这是修复文本"
    assert repaired[2].translated_text == "这是原文"


def test_compression_accepts_new_subtitle_id_protocol_without_position_shift():
    editor = _id_editor()
    segments = _id_segments(3)
    segments[1].translated_text = "LONG_TARGET"

    def severe(seg):
        return seg.translated_text == "LONG_TARGET"

    def request(prompt, payload, task, temperature):
        assert payload[0]["subtitle_id"] == "S0002"
        return {"items": [{"subtitle_id": "S0002", "chinese": "这是修复文本"}]}

    with patch.object(editor, "_is_severe_chinese_speed", side_effect=severe), patch.object(
        editor, "_request_chinese_compression", side_effect=request
    ):
        repaired = editor._compress_fast_chinese_segments(segments)

    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002", "S0003"]
    assert repaired[0].translated_text == "这是原文"
    assert repaired[1].translated_text == "这是修复文本"
    assert repaired[2].translated_text == "这是原文"


def test_redistribution_parses_out_of_order_returns_by_subtitle_id():
    editor = _id_editor()
    segments = _id_segments(4)
    data = {
        "groups": [
            {
                "target_index": 2,
                "segments": [
                    {"index": 3, "zh": "这是第四条"},
                    {"index": 1, "zh": "这是第二条"},
                ],
            }
        ]
    }

    parsed = editor._parse_chinese_group_allocations(data, segments)

    assert parsed == {"S0003": {"S0004": "这是第四条", "S0002": "这是第二条"}}


def test_redistribution_parses_new_id_only_protocol_without_position_shift():
    editor = _id_editor()
    segments = _id_segments(4)
    data = {
        "groups": [
            {
                "target_subtitle_id": "S0003",
                "segments": [
                    {"subtitle_id": "S0004", "zh": "这是第四条"},
                    {"subtitle_id": "S0002", "zh": "这是第二条"},
                ],
            }
        ]
    }

    parsed = editor._parse_chinese_group_allocations(data, segments)

    assert parsed == {"S0003": {"S0004": "这是第四条", "S0002": "这是第二条"}}


def test_compression_keeps_subtitle_ids_and_count():
    editor = _id_editor()
    segments = _id_segments(3)
    segments[1].translated_text = "LONG_TARGET"

    def severe(seg):
        return seg.translated_text == "LONG_TARGET"

    def request(prompt, payload, task, temperature):
        return {"items": [{"index": 1, "chinese": "这是压缩文本"}]}

    with patch.object(editor, "_is_severe_chinese_speed", side_effect=severe), patch.object(
        editor, "_request_chinese_compression", side_effect=request
    ):
        compressed = editor._compress_fast_chinese_segments(segments)

    assert len(compressed) == len(segments)
    assert [seg.subtitle_id for seg in compressed] == [seg.subtitle_id for seg in segments]
    assert compressed[1].translated_text == "这是压缩文本"


def test_fallback_translation_fills_only_one_missing_subtitle_id():
    editor = _id_editor()
    segments = _id_segments(3)
    segments[1].translated_text = ""

    with patch.object(editor, "_translate_split_parts", return_value=["这是补译"]):
        repaired = editor._translate_missing_segments(segments)

    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002", "S0003"]
    assert repaired[0].translated_text == "这是原文"
    assert repaired[1].translated_text == "这是补译"
    assert repaired[2].translated_text == "这是原文"


def test_multiple_semantic_groups_apply_by_id_without_drift():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(6))
    groups = [_id_group(1, 0, items[:3]), _id_group(2, 3, items[3:])]
    translations = {
        1: {"S0003": "zh-S0003", "S0001": "zh-S0001", "S0002": "zh-S0002"},
        2: {"S0006": "zh-S0006", "S0005": "zh-S0005", "S0004": "zh-S0004"},
    }

    applied = editor._apply_semantic_group_translations(items, groups, translations)

    assert [item.subtitle_id for item in applied] == [f"S{index:04d}" for index in range(1, 7)]
    assert [item.translated for item in applied] == [f"zh-S{index:04d}" for index in range(1, 7)]


def test_full_merge_repair_chain_keeps_400_plus_ids_without_drift():
    editor = _id_editor()
    editor.max_english_words = 14
    segments = _id_segments(405)
    editor._frozen_subtitle_ids = [seg.subtitle_id for seg in segments]

    repaired = editor._repair_blocking_subtitle_issues(segments)
    repaired = editor._merge_short_display_segments(repaired)
    repaired = editor._repair_abnormal_timing_gaps(repaired)
    repaired = editor._apply_display_timing_padding(repaired)
    repaired = editor._order_segments_by_frozen_subtitle_ids(repaired)
    editor._validate_final_segment_translation_ids(repaired)

    assert editor._translation_structure_errors == []
    assert [seg.subtitle_id for seg in repaired] == editor._frozen_subtitle_ids
    assert [seg.text for seg in repaired] == [seg.text for seg in segments]


def test_safe_auto_repair_is_noop_when_disabled():
    editor = _id_editor()
    editor.enable_safe_auto_repair = False
    segments = [
        ASRDataSeg("First different sentence.", 0, 1500, "这是明显重复的中文。"),
        ASRDataSeg("Second different sentence.", 1500, 3000, "这是明显重复的中文。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    repaired = editor._safe_auto_repair_segments(segments, stage="test")

    assert [seg.text for seg in repaired] == [seg.text for seg in segments]
    assert [seg.translated_text for seg in repaired] == [seg.translated_text for seg in segments]


def test_safe_auto_repair_retranslates_exact_duplicate_chinese_by_id():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg("First different sentence.", 0, 1800, "这是明显重复的中文。"),
        ASRDataSeg("Second different sentence.", 1800, 3600, "这是明显重复的中文。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    with patch.object(editor, "_translate_split_parts", return_value=["第二句正确中文。"]):
        repaired = editor._safe_auto_repair_segments(segments, stage="test")

    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002"]
    assert [seg.text for seg in repaired] == [seg.text for seg in segments]
    assert [(seg.start_time, seg.end_time) for seg in repaired] == [
        (seg.start_time, seg.end_time) for seg in segments
    ]
    assert repaired[0].translated_text == "这是明显重复的中文。"
    assert repaired[1].translated_text == "第二句正确中文。"
    assert editor._safe_auto_repair_log
    assert editor._safe_auto_repair_log[-1]["subtitle_id"] == "S0002"


def test_safe_auto_repair_extends_high_load_short_subtitle_when_neighbor_has_room():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg(
            "He is trying to prevent the natural price discovery of the market.",
            1000,
            1700,
            "他试图阻止市场自然的价格发现机制。",
        ),
        ASRDataSeg("And the next sentence has enough room.", 1740, 5200, "下一句有足够空间。"),
    ]

    repaired = editor._repair_final_short_subtitle_timings(segments)

    assert repaired[0].end_time - repaired[0].start_time > 700
    assert repaired[0].end_time <= repaired[1].start_time - 40
    assert repaired[0].text == segments[0].text
    assert repaired[0].translated_text == segments[0].translated_text
    assert any(item["code"] == "high_load_short_timing_repaired" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_does_not_extend_high_load_short_subtitle_when_disabled():
    editor = _id_editor()
    editor.enable_safe_auto_repair = False
    segments = [
        ASRDataSeg(
            "He is trying to prevent the natural price discovery of the market.",
            1000,
            1700,
            "他试图阻止市场自然的价格发现机制。",
        ),
        ASRDataSeg("And the next sentence has enough room.", 1740, 5200, "下一句有足够空间。"),
    ]

    repaired = editor._repair_final_short_subtitle_timings(segments)

    assert repaired[0].end_time - repaired[0].start_time < editor._target_high_load_duration_ms(segments[0])
    assert repaired[0].text == segments[0].text


def test_duration_audit_reports_high_load_short_subtitle_as_warning():
    editor = _id_editor()
    segments = [
        ASRDataSeg(
            "He is trying to prevent the natural price discovery of the market.",
            1000,
            1700,
            "他试图阻止市场自然的价格发现机制。",
        )
    ]

    issues = editor._subtitle_duration_issues(segments, "WARNING")

    assert issues
    assert issues[0]["code"] == "subtitle_high_load_too_short"


def test_safe_auto_repair_records_review_candidates_without_rewriting_fragments():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_candidates = []
    segments = [
        ASRDataSeg("Yes, this is the key part.", 0, 1200, "是的，这是关键部分。因为"),
        ASRDataSeg("The next idea is separate.", 1240, 2600, "下一点是分开的。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    repaired = editor._safe_auto_repair_segments(segments, stage="test")

    assert [seg.translated_text for seg in repaired] == [seg.translated_text for seg in segments]
    assert any(
        item["code"] == "candidate_chinese_fragment_review_only"
        and item["decision"] == "not_auto_repaired_due_to_false_positive_risk"
        for item in editor._safe_auto_repair_candidates
    )
    assert not editor._is_high_confidence_chinese_fragment_candidate("哦，绝对是历史性的。")
    assert not editor._is_high_confidence_chinese_fragment_candidate("因为这两家公司主导了内存芯片市场。")


def test_safe_auto_repair_guard_rejects_repairs_that_create_new_hard_problem():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg("First different sentence.", 0, 1800, "第一句中文。"),
        ASRDataSeg("Second different sentence.", 1800, 3600, "第二句中文。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"
    damaged = [editor._copy_segment(seg) for seg in segments]
    damaged[1] = editor._copy_segment(damaged[1], translated_text="第一句中文。")

    with patch.object(editor, "_repair_exact_duplicate_chinese_segments", return_value=damaged):
        repaired = editor._safe_auto_repair_segments(segments, stage="test")

    assert [seg.translated_text for seg in repaired] == [seg.translated_text for seg in segments]
    assert any(item["code"] == "safe_repair_guard_rejected" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_llm_repairs_high_confidence_chinese_candidate_after_final_alignment():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [ASRDataSeg("Yeah, he is out there.", 0, 1800, "是啊，他正在")]
    segments[0].subtitle_id = "S0001"
    item = ScreenSubtitleItem(
        source_ids=[1],
        original=segments[0].text,
        translated=segments[0].translated_text,
        subtitle_id="S0001",
    )
    semantic_groups = [{"id": 1, "start_index": 0, "items": [item]}]
    editor._last_semantic_full_translations = {1: "是啊，他正在外面积极行动。"}

    with patch.object(
        editor,
        "_request_chinese_compression",
        return_value={
            "groups": [
                {
                    "target_index": 0,
                    "segments": [{"index": 0, "zh": "是啊，他正在外面积极行动。"}],
                }
            ]
        },
    ) as request:
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=[item],
            stage="after_final_time_alignment",
        )

    assert request.called
    assert repaired[0].text == segments[0].text
    assert repaired[0].subtitle_id == "S0001"
    assert repaired[0].translated_text == "是啊，他正在外面积极行动。"
    assert any(item["code"] == "llm_chinese_candidate_repaired" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_llm_does_not_run_candidate_repair_before_final_alignment():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    segments = [ASRDataSeg("Yeah, he is out there.", 0, 1800, "是啊，他正在")]
    segments[0].subtitle_id = "S0001"
    item = ScreenSubtitleItem(
        source_ids=[1],
        original=segments[0].text,
        translated=segments[0].translated_text,
        subtitle_id="S0001",
    )
    semantic_groups = [{"id": 1, "start_index": 0, "items": [item]}]
    editor._last_semantic_full_translations = {1: "是啊，他正在外面积极行动。"}

    with patch.object(editor, "_request_chinese_compression") as request:
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=[item],
            stage="before_export",
        )

    assert not request.called
    assert repaired[0].translated_text == segments[0].translated_text


def test_safe_auto_repair_llm_rejects_invalid_candidate_repair():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [ASRDataSeg("Yeah, he is out there.", 0, 1800, "是啊，他正在")]
    segments[0].subtitle_id = "S0001"
    item = ScreenSubtitleItem(
        source_ids=[1],
        original=segments[0].text,
        translated=segments[0].translated_text,
        subtitle_id="S0001",
    )
    semantic_groups = [{"id": 1, "start_index": 0, "items": [item]}]
    editor._last_semantic_full_translations = {1: "是啊，他正在外面积极行动。"}

    with patch.object(
        editor,
        "_request_chinese_compression",
        return_value={
            "groups": [
                {
                    "target_index": 0,
                    "segments": [{"index": 0, "zh": "因为"}],
                }
            ]
        },
    ):
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=[item],
            stage="after_final_time_alignment",
        )

    assert repaired[0].translated_text == segments[0].translated_text
    assert any(item["code"] == "llm_chinese_candidate_repair_rejected" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_llm_retries_invalid_candidate_with_same_group_context():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg("when you look at internet native humor and culture.", 0, 2600, "当你在看网络原生幽默和文化时。"),
        ASRDataSeg("Zachary Dunn is a fascinating example.", 2600, 5200, "Zachary Dunn就是一个很有意思的例子。"),
    ]
    for index, segment in enumerate(segments, 1):
        segment.subtitle_id = f"S{index:04d}"
    items = [
        ScreenSubtitleItem(
            source_ids=[index],
            original=segment.text,
            translated=segment.translated_text,
            subtitle_id=segment.subtitle_id,
        )
        for index, segment in enumerate(segments, 1)
    ]
    semantic_groups = [{"id": 1, "start_index": 0, "items": items}]
    editor._last_semantic_full_translations = {
        1: "从网络原生幽默和文化来看，Zachary Dunn就是一个很有意思的例子。"
    }

    responses = [
        {
            "groups": [
                {
                    "target_index": 0,
                    "segments": [{"index": 0, "zh": "因为"}],
                }
            ]
        },
        {
            "groups": [
                {
                    "target_index": 0,
                    "segments": [
                        {"index": 0, "zh": "从网络原生幽默和文化来看，"},
                        {"index": 1, "zh": "Zachary Dunn就是一个很有意思的例子。"},
                    ],
                }
            ]
        },
    ]

    def fake_request(*args, **kwargs):
        return responses.pop(0)

    with patch.object(editor, "_request_chinese_compression", side_effect=fake_request) as request:
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=items,
            stage="after_final_time_alignment",
        )

    assert request.call_count == 2
    assert [seg.text for seg in repaired] == [seg.text for seg in segments]
    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002"]
    assert repaired[0].translated_text == "从网络原生幽默和文化来看，"
    assert repaired[1].translated_text == segments[1].translated_text
    assert any(item["code"] == "llm_chinese_candidate_repaired" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_llm_rejects_new_adjacent_chinese_boundary_break():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg(
            "You validate a radically new disruptive movement by anchoring it",
            466020,
            469660,
            "你将一个全新的颠覆性运动，直接锚定在",
        ),
        ASRDataSeg(
            "directly to an ancient, established, and highly respected text.",
            469700,
            473600,
            "一部古老、权威且备受尊崇的文本上，从而为其提供合法性。",
        ),
    ]
    for index, segment in enumerate(segments, 1):
        segment.subtitle_id = f"S{index:04d}"
    items = [
        ScreenSubtitleItem(
            source_ids=[index],
            original=segment.text,
            translated=segment.translated_text,
            subtitle_id=segment.subtitle_id,
        )
        for index, segment in enumerate(segments, 1)
    ]
    semantic_groups = [{"id": 1, "start_index": 0, "items": items}]
    editor._last_semantic_full_translations = {
        1: "你将一个全新的颠覆性运动，直接锚定在一部古老、权威且备受尊崇的文本上，从而为其提供合法性。"
    }

    with patch.object(
        editor,
        "_request_chinese_compression",
        return_value={
            "groups": [
                {
                    "target_index": 0,
                    "segments": [
                        {"index": 0, "zh": "你将一个全新的颠覆性运动，直接锚定它"},
                        {"index": 1, "zh": "到一部古老、权威且备受尊崇的文本上，从而为其提供合法性。"},
                    ],
                }
            ]
        },
    ):
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=items,
            stage="after_final_time_alignment",
        )

    assert [seg.translated_text for seg in repaired] == [seg.translated_text for seg in segments]
    assert any(item["code"] == "llm_chinese_candidate_repair_rejected" for item in editor._safe_auto_repair_log)


def test_final_gate_blocks_protected_named_phrase_split():
    editor = _marker_editor(["Wall", "Street", "is", "watching"], max_words=8)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 3, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == ["Wall Street is watching"]
    assert "protected_named_phrase_split" in editor._syntax_boundary_reasons("Wall", "Street is watching")


def test_final_gate_blocks_protected_phrasal_boundary_split():
    editor = _marker_editor(["They", "are", "pricing", "in", "the", "belief"], max_words=8)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == ["They are pricing in the belief"]
    assert "protected_phrasal_boundary_split" in editor._syntax_boundary_reasons("They are pricing", "in the belief")


def test_final_gate_blocks_look_at_boundary_split():
    editor = _marker_editor(["We", "need", "to", "look", "at", "why", "this", "changed"], max_words=8)
    items = [_word_item(editor, 0, 3, 1), _word_item(editor, 4, 7, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == ["We need to look at why this changed"]
    assert "protected_phrasal_boundary_split" in editor._syntax_boundary_reasons("We need to look", "at why this changed")


def test_passed_validation_writes_final_output_and_manifest_metadata():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        output_dir = root / "work" / "subtitle"
        source_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        audio_path = source_dir / "sample.m4a"
        audio_path.write_bytes(b"audio")
        task = SubtitleTask(
            subtitle_path=str(output_dir / "source.srt"),
            video_path=str(audio_path),
            output_path=str(output_dir / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English 1.", 0, 1000, "这是译文")]),
            config,
            coverage_report_path=str(root / "coverage-report.txt"),
            validation_status="passed",
            manifest_meta={
                "translation_model": "deepseek-v4-flash",
                "code_commit": "abc123",
                "cache_used": False,
                "prompt_version": "global-subtitle-id-v2",
            },
        )

        manifest = json.loads((output_dir / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert manifest["render_blocked"] is False
        assert manifest["translation_model"] == "deepseek-v4-flash"
        assert manifest["code_commit"] == "abc123"
        assert manifest["cache_used"] is False
        assert manifest["prompt_version"] == "global-subtitle-id-v2"
        assert (output_dir / "output.srt").exists()
        assert not (output_dir / "字幕处理结果摘要.txt").exists()
        summary_path = source_dir / "字幕处理结果摘要.txt"
        assert summary_path.exists()
        summary = summary_path.read_text(encoding="utf-8-sig")
        assert "结论：通过" in summary
        assert "字幕数量：1" in summary


def test_stable_result_summary_records_safe_repair_details():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        output_dir = root / "work" / "subtitle"
        source_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        audio_path = source_dir / "sample.m4a"
        audio_path.write_bytes(b"audio")
        task = SubtitleTask(
            subtitle_path=str(output_dir / "source.srt"),
            video_path=str(audio_path),
            output_path=str(output_dir / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English 1.", 0, 1000, "这是译文")]),
            config,
            coverage_report_path=str(root / "coverage-report.txt"),
            validation_status="passed",
            validation_summary={"status": "WARNING", "errors": [], "warnings": [{"code": "x", "message": "待检查"}], "info": []},
            manifest_meta={
                "safe_auto_repair_enabled": True,
                "safe_auto_repair_log": [
                    {
                        "code": "llm_chinese_candidate_repaired",
                        "subtitle_id": "S0001",
                        "start": "00:00:00.000",
                        "end": "00:00:01.000",
                        "before_chinese": "旧中文",
                        "after_chinese": "新中文",
                    }
                ],
                "safe_auto_repair_candidates": [{"code": "candidate"}],
            },
        )

        manifest = json.loads((output_dir / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert "work_summary_txt" not in manifest["result_summary_paths"]
        summary_path = Path(manifest["result_summary_paths"]["source_summary_txt"])
        summary = summary_path.read_text(encoding="utf-8-sig")
        assert "结论：可用" in summary
        assert "实际修复：1" in summary
        assert "旧中文" in summary
        assert "新中文" in summary


def test_qa_review_srt_is_not_mirrored_to_source_audio_folder():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        output_dir = root / "work" / "subtitle"
        source_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        audio_path = source_dir / "sample.m4a"
        audio_path.write_bytes(b"audio")
        coverage_path = output_dir / "output-coverage-report.txt"
        coverage_path.write_text("coverage", encoding="utf-8")
        qa_path = output_dir / "qa-review-points.srt"
        qa_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nQA\n", encoding="utf-8")

        task = SubtitleTask(
            subtitle_path=str(output_dir / "source.srt"),
            video_path=str(audio_path),
            output_path=str(output_dir / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English 1.", 0, 1000, "译文")]),
            config,
            coverage_report_path=str(coverage_path),
            validation_status="passed",
            manifest_meta={"qa_review_points_srt": str(qa_path)},
        )

        assert qa_path.exists()
        assert not (source_dir / "qa-review-points.srt").exists()
        assert not (source_dir / "coverage-report.txt").exists()
        assert not (source_dir / "stable-final-manifest.json").exists()

        work_manifest = json.loads((output_dir / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert work_manifest["qa_review_points_srt"] == str(qa_path)
        assert "source_report_paths" not in work_manifest


def test_user_subtitle_exports_are_saved_to_source_audio_folder():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        output_dir = root / "work" / "subtitle"
        source_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        audio_path = source_dir / "sample-audio.m4a"
        audio_path.write_bytes(b"audio")

        task = SubtitleTask(
            subtitle_path=str(output_dir / "source.srt"),
            video_path=str(audio_path),
            output_path=str(output_dir / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="translation_top",
        )

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English line.", 0, 1000, "中文行。")]),
            config,
            validation_status="passed",
        )

        bilingual = source_dir / "双语字幕.srt"
        chinese = source_dir / "中文字幕.srt"
        english = source_dir / "英文字幕.srt"
        assert bilingual.exists()
        assert chinese.exists()
        assert english.exists()
        bilingual_text = bilingual.read_text(encoding="utf-8-sig")
        assert "English line.\n中文行。" in bilingual_text
        assert "中文行。" in chinese.read_text(encoding="utf-8-sig")
        assert "English line." not in chinese.read_text(encoding="utf-8-sig")
        assert "English line." in english.read_text(encoding="utf-8-sig")
        assert "中文行。" not in english.read_text(encoding="utf-8-sig")

        manifest = json.loads((output_dir / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert manifest["source_subtitle_paths"] == {
            "bilingual_original_top_srt": str(bilingual),
            "only_translation_srt": str(chinese),
            "only_original_srt": str(english),
        }


def test_screen_manifest_metadata_includes_stage_timings():
    class FakeScreenEditor:
        @staticmethod
        def manifest_metadata():
            return {"translation_model": "deepseek-v4-flash"}

    thread = SubtitleThread.__new__(SubtitleThread)
    thread._stage_timings_seconds = {"screen_subtitle_edit": 12.345, "final_subtitle_save": 0.5}

    metadata = thread._screen_manifest_metadata(FakeScreenEditor())

    assert metadata["translation_model"] == "deepseek-v4-flash"
    assert metadata["stage_timings_seconds"]["screen_subtitle_edit"] == 12.345
    assert metadata["stage_timings_total_seconds"] == 12.845


def test_id_bound_mapping_has_no_drift_over_400_subtitles():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(405))
    group = _id_group(1, 0, items)
    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": item.subtitle_id, "zh": f"zh-{item.subtitle_id}"}
            for item in reversed(items)
        ],
    )
    applied = editor._apply_semantic_group_translations(items, [group], {1: translations})
    editor._validate_final_item_translation_ids(applied)

    assert editor._translation_structure_errors == []
    assert [item.subtitle_id for item in applied] == [item.subtitle_id for item in items]
    assert [item.original for item in applied] == [item.original for item in items]
    assert [item.word_start for item in applied] == [item.word_start for item in items]
    assert applied[-1].translated == "zh-S0405"


def test_validation_summary_error_marks_stable_manifest_failed():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        task = SubtitleTask(
            subtitle_path=str(root / "source.srt"),
            output_path=str(root / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )
        data = ASRData([ASRDataSeg("Really?", 0, 100, "ok")])
        summary = {
            "status": "ERROR",
            "errors": [{"code": "subtitle_duration_invalid"}],
            "warnings": [],
            "info": [],
        }

        thread._save_stable_subtitle_outputs(
            data,
            config,
            coverage_report_path=str(root / "coverage-report.txt"),
            validation_status="passed",
            validation_summary=summary,
        )

        manifest = json.loads((root / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert manifest["validation_status"] == "failed"
        assert manifest["render_blocked"] is True
        assert manifest["validation_error_codes"] == ["subtitle_duration_invalid"]
        assert Path(manifest["paths"]["original_top_srt"]).exists()
        assert not (root / "output.srt").exists()


def test_runtime_module_import_path_is_available():
    result = subprocess.run(
        [str(ROOT / "runtime" / "python.exe"), "-m", "tests.caption_audit.run_all", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0
    assert "Audit stable bilingual subtitle outputs" in result.stdout


def test_whisperx_alignment_mapping_preserves_source_tokens_and_local_fallback():
    source = [
        ASRDataSeg("A", 100, 200),
        ASRDataSeg("56-year-old", 200, 400),
        ASRDataSeg("speaker,", 400, 600),
        ASRDataSeg("continues.", 600, 800),
    ]
    aligned_words = [
        {"text": "A", "start": 0.12, "end": 0.22},
        {"text": "speaker", "start": 0.42, "end": 0.62},
        {"text": "continues", "start": 0.64, "end": 0.88},
    ]

    mapped = _make_whisperx_word_segments(source, aligned_words)

    assert [seg.text for seg in mapped.segments] == [seg.text for seg in source]
    assert [seg.start_time for seg in mapped.segments] == [120, 200, 420, 640]
    assert [seg.end_time for seg in mapped.segments] == [220, 400, 620, 880]


if __name__ == "__main__":
    test_final_time_alignment_reapplies_display_padding_to_loaded_short_subtitle()
    test_final_time_alignment_shifts_next_when_loaded_short_has_no_gap()
    test_final_time_alignment_runs_chinese_speed_repair_without_touching_english()
    test_screen_editor_uses_16_word_stable_hard_floor()
    test_stable_screen_pipeline_requests_word_timestamps_without_legacy_split()
    test_preposition_phrase_is_not_stranded()
    test_number_and_policy_sentence_keeps_readable_boundaries()
    test_long_finance_sentence_keeps_full_coverage()
    test_missing_translation_is_reported_but_not_blocking()
    test_suspicious_cut_is_warning_not_blocking()
    test_abnormal_timing_gap_is_repaired_for_compressed_cluster()
    test_coverage_gap_does_not_sum_natural_pauses()
    test_coverage_gap_blocks_single_long_uncovered_span()
    test_final_display_coverage_bridges_short_continuous_source_gap()
    test_final_display_coverage_does_not_bridge_long_gap()
    test_final_display_coverage_preserves_real_word_pause()
    test_final_time_alignment_coverage_bridge_runs_with_preserved_alignment_timing()
    test_chinese_reading_speed_error_is_reported_but_not_blocking()
    test_validation_report_adds_actionable_review_tiers_without_changing_status()
    test_validation_review_includes_allocation_unresolved_without_old_error_mutation()
    test_allocation_isolation_report_passes_when_only_chinese_changes()
    test_allocation_isolation_report_fails_on_english_boundary_change()
    test_duplicate_chinese_is_warning_not_blocking()
    test_overlong_english_segment_is_locally_split_without_llm()
    test_audit_parser_does_not_count_chinese_line_with_it_as_english()
    test_888_chinese_speed_compression_rejects_dangling_fragment()
    test_888_chinese_speed_compression_uses_semantic_group_context()
    test_000_group_validation_rejects_lost_ponder_action()
    test_444_independent_syntax_boundary_audit_catches_bad_cuts()
    test_syntax_boundary_audit_ignores_safe_short_dialogue()
    test_syntax_boundary_audit_keeps_confirmed_bad_cuts()
    test_chinese_semantic_group_audit_warns_on_lost_core_action()
    test_chinese_semantic_audit_skips_semantic_loss_when_mapping_invalid()
    test_chinese_semantic_audit_ignores_normal_short_responses()
    test_semantic_audit_context_requires_id_signature_and_expected_ids()
    test_semantic_audit_mapping_does_not_shift_when_audit_groups_exceed_generation_count()
    test_semantic_audit_mapping_does_not_shift_when_audit_groups_drop_generation_count()
    test_repeated_short_dialogue_does_not_map_to_wrong_semantic_group()
    test_missing_semantic_group_id_only_invalidates_that_group()
    test_identical_english_but_different_subtitle_ids_do_not_match()
    test_g0248_full_translation_can_be_retraced_from_generated_context()
    test_validation_report_full_translation_uses_single_stage_raw_records_for_all_valid_groups()
    test_mapping_failure_does_not_emit_full_translation_dependent_false_positive()
    test_command_chinese_audit_catches_confirmed_bad_groups()
    test_command_chinese_audit_ignores_normal_short_groups()
    test_very_short_subtitle_has_dedicated_duration_error()
    test_short_backchannel_duration_is_warning_not_error()
    test_short_regular_sentence_duration_remains_error()
    test_asr_suspicious_phrases_are_reported_without_fixing_text()
    test_asr_suspicious_article_context_misses_are_reported()
    test_abbreviation_name_boundary_is_syntax_warning()
    test_terminal_punctuation_wins_over_token_only_determiner_heuristic()
    test_caption_audit_uses_16_word_hard_limit()
    test_caption_audit_accepts_allowed_plus_discourse_overflow()
    test_caption_audit_treats_borderline_chinese_speed_as_warning_not_blocker()
    test_caption_audit_keeps_numeric_percent_chinese_line()
    test_large_number_anchor_variants_do_not_crash()
    test_concise_group_allocation_is_not_rejected_by_coverage_only()
    test_short_but_severe_chinese_speed_triggers_repair()
    test_borderline_chinese_speed_does_not_trigger_render_blocker()
    test_short_subtitle_gets_minimum_display_duration_when_room_allows()
    test_short_backchannel_merges_with_following_segment()
    test_short_sentence_bridges_small_gap_before_next_subtitle()
    test_standalone_discourse_marker_attaches_to_immediate_next_sentence()
    test_plus_marker_keeps_a_complete_one_word_overflow_unit()
    test_trailing_standalone_discourse_marker_attaches_to_previous_sentence()
    test_standalone_discourse_marker_does_not_cross_long_pause()
    test_standalone_discourse_marker_does_not_cross_speaker_change()
    test_overlong_discourse_marker_attachment_reselects_cutpoint()
    test_discourse_marker_rebalance_does_not_leave_one_word_fragment()
    test_trailing_discourse_marker_is_not_left_at_subtitle_end()
    test_discourse_marker_phrase_is_not_split_during_rebalance()
    test_trailing_discourse_marker_rebalances_two_long_items_without_word_loss()
    test_short_yeah_rebalances_with_long_following_sentence()
    test_short_though_attaches_to_following_sentence()
    test_short_though_rebalances_without_leaving_orphan()
    test_discourse_marker_ids_are_assigned_after_all_english_boundaries_are_fixed()
    test_discourse_marker_pre_id_pipeline_keeps_400_plus_english_chinese_id_sets_equal()
    test_discourse_marker_pre_id_pipeline_keeps_421_item_structure_errors_zero()
    test_balanced_split_does_not_create_preposition_object_boundary()
    test_determiner_numeric_noun_boundary_is_hard_illegal()
    test_quantifier_phrase_boundary_is_hard_illegal()
    test_adverb_adjective_boundary_is_hard_illegal_without_pause()
    test_short_verb_complement_boundary_is_hard_when_syntax_marks_it()
    test_short_verb_possessive_complement_boundary_is_hard_when_syntax_marks_it()
    test_parser_blocks_direct_verb_particle_boundary()
    test_parser_blocks_compact_coordinated_subject_boundary()
    test_parser_blocks_short_dative_object_start_boundary()
    test_parser_blocks_numeric_range_boundaries()
    test_pre_id_candidate_gate_rejects_new_hard_syntax_boundary()
    test_long_object_still_allows_legal_boundary()
    test_final_pre_id_repair_removes_known_hard_boundary()
    test_final_pre_id_keeps_discourse_marker_with_following_sentence_after_terminal_over()
    test_final_pre_id_rebalances_leading_nonfinite_dependent_prefix()
    test_final_pre_id_keeps_finite_conditional_introduction_in_its_own_cue()
    test_leading_nonfinite_dependent_prefix_rebalance_respects_long_pause()
    test_leading_nonfinite_dependent_prefix_rebalance_respects_speaker_change()
    test_final_pre_id_repair_does_not_cross_speaker_change()
    test_final_pre_id_rejects_noop_repartition_without_iteration_loop()
    test_verb_directional_adverb_preposition_boundary_is_hard_when_syntax_marks_it()
    test_short_display_merge_keeps_original_when_no_safe_boundary_exists()
    test_final_pre_id_preserves_word_order_coverage_and_timestamps()
    test_boundary_snapshot_payload_records_pre_id_repairs()
    test_subject_finite_verb_we_tend_is_hard_boundary()
    test_subject_finite_verb_they_needed_is_hard_boundary()
    test_subject_finite_verb_ai_is_upending_is_hard_boundary()
    test_modifier_head_actually_good_is_hard_boundary()
    test_relative_clause_subject_verb_you_can_is_hard_boundary()
    test_final_pre_id_repairs_yeah_so_todd_subject_fragment()
    test_final_pre_id_repairs_pronoun_only_fragment()
    test_final_pre_id_attaches_standalone_so_to_next_sentence()
    test_final_pre_id_keeps_independent_short_answers()
    test_weak_fragment_repair_does_not_cross_speaker_change()
    test_weak_fragment_repair_does_not_cross_long_pause()
    test_internal_transition_attaches_to_following_sentence()
    test_final_pre_id_repair_does_not_create_new_hard_issue()
    test_unresolved_weak_fragment_is_recorded_when_no_safe_repair()
    test_final_pre_id_second_phase_preserves_word_order_and_timestamps()
    test_boundary_snapshots_record_stage_changes_before_subtitle_ids()
    test_final_stable_english_boundaries_do_not_change_for_video_layout()
    test_final_gate_blocks_particle_preposition_complement_split()
    test_final_gate_keeps_preposition_object_boundary_illegal_after_long_pause()
    test_stable_cut_keeps_preposition_object_phrase_together_in_long_sentence()
    test_parser_confirmed_verb_object_boundary_stays_illegal_after_long_pause()
    test_parser_blocks_clause_introducer_from_ending_a_cue()
    test_parser_blocks_verb_from_its_preposition_complement()
    test_parser_blocks_verb_from_numeric_result_expression()
    test_parser_mapping_keeps_numeric_result_after_hyphenated_ledger_word()
    test_stable_cut_prefers_normal_limit_when_a_legal_boundary_exists()
    test_final_gate_soft_flags_heuristic_short_verb_object_split()
    test_final_gate_blocks_auxiliary_predicate_split()
    test_final_gate_soft_flags_heuristic_catenative_verb_complement_split()
    test_final_gate_blocks_numeric_unit_or_noun_split()
    test_numeric_sentence_boundary_is_not_repaired_as_a_numeric_phrase()
    test_final_gate_soft_flags_heuristic_compound_noun_split()
    test_final_gate_soft_flags_heuristic_modifier_noun_head_split()
    test_final_gate_blocks_negation_emphasis_split()
    test_final_gate_blocks_stranded_leading_of_complement()
    test_final_gate_blocks_stranded_leading_with_complement()
    test_final_gate_blocks_time_range_to_continuation()
    test_final_gate_blocks_coordinated_modifier_split()
    test_final_gate_blocks_modifier_chain_split()
    test_final_gate_blocks_high_confidence_phrasal_verb_particle_split()
    test_final_fragment_gate_repairs_trailing_dependent_fragments()
    test_final_fragment_gate_repairs_possessive_and_quantifier_tails()
    test_final_gate_allows_sentence_initial_to_me_after_punctuation()
    test_final_fragment_gate_repairs_incomplete_interrogative_fragment()
    test_final_repair_does_not_create_adjacent_subject_fragment()
    test_final_repair_does_not_create_ordinary_one_word_fragment()
    test_final_fragment_gate_repairs_connector_and_reflexive_fragments()
    test_final_fragment_gate_records_unresolved_when_no_legal_solution()
    test_podcast_template_prefers_stable_manifest_subtitle()
    test_podcast_template_blocks_failed_stable_manifest_subtitle()
    test_podcast_template_reuses_legacy_reading_speed_manifest_when_revalidated()
    test_podcast_template_preserves_full_media_duration_when_subtitles_end_early()
    test_podcast_template_uses_frozen_task_configuration()
    test_article_template_uses_full_hd_canvas_and_balanced_subtitle_widths()
    test_caption_wrapper_never_orphans_a_leading_connector_to_balance_two_lines()
    test_caption_wrapper_preserves_preposition_and_infinitive_phrase_edges()
    test_caption_wrapper_scales_before_breaking_a_hyphenated_compound()
    test_article_template_does_not_truncate_a_long_english_subtitle()
    test_standard_chinese_subtitle_font_uses_48_then_46_before_two_lines()
    test_article_template_scaled_geometry_stays_on_integer_pixels()
    test_article_template_tip_font_and_wrapper_support_chinese_text()
    test_article_vocab_typography_uses_hanchan_tip_and_regular_definition()
    test_vocab_highlight_keeps_attached_punctuation_but_not_whitespace()
    test_standard_subtitle_highlight_colors_attached_punctuation()
    test_article_subtitle_highlight_colors_attached_punctuation()
    test_vocab_generation_keeps_successful_batches_when_one_batch_fails()
    test_empty_vocab_cache_is_regenerated_instead_of_reused()
    test_vocab_card_plan_keeps_the_latest_full_card_until_replacement()
    test_article_vocab_card_uses_only_expression_gloss_and_concept_note()
    test_vocab_prompt_requests_expression_card_fields_without_dictionary_metadata()
    test_vocab_plan_preserves_the_exact_phrase_from_its_subtitle()
    test_vocab_source_phrase_does_not_match_inside_a_larger_word()
    test_vocab_plan_limits_concept_cards_to_three_per_episode()
    test_vocab_plan_keeps_each_llm_card_inside_its_frozen_group()
    test_vocab_card_meaning_keeps_only_compact_primary_gloss()
    test_vocab_plan_normalizes_verbose_model_meaning_before_rendering()
    test_vocab_card_plan_skips_low_priority_model_candidates()
    test_vocabulary_card_target_is_20_for_a_sixteen_minute_episode()
    test_article_template_does_not_fallback_to_per_subtitle_vocab_lookup()
    test_article_template_shows_topic_panel_before_first_card()
    test_article_template_crossfades_only_from_topic_to_first_card()
    test_episode_vocab_overview_uses_editor_rank_instead_of_earliest_words()
    test_template_frame_cache_keeps_the_full_vocab_card_stable()
    test_stable_srt_writer_keeps_bilingual_original_top()
    test_id_bound_group_missing_one_id_does_not_shift_later_subtitles()
    test_atomic_no_response_cannot_be_written_as_affirmative()
    test_id_bound_group_rejects_duplicate_id_without_compressing_chinese()
    test_id_bound_group_rejects_unknown_id()
    test_id_bound_group_allows_different_return_order()
    test_single_cue_group_uses_authoritative_full_translation_without_allocation_request()
    test_full_translation_number_error_is_not_misclassified_as_allocation_error()
    test_full_translation_requests_are_chunked_and_retry_missing_groups()
    test_full_translation_prompt_restrains_ordinary_chinese_em_dashes()
    test_full_translation_em_dash_style_detector_ignores_lexical_hyphen()
    test_full_translation_style_retry_only_retries_flagged_group_and_accepts_improvement()
    test_full_translation_style_retry_keeps_original_when_candidate_loses_number_or_negation()
    test_allocation_quality_retries_information_leaked_to_previous_id()
    test_allocation_quality_rejects_adjacent_core_duplication()
    test_allocation_quality_rejects_adjacent_long_common_phrase_duplication()
    test_allocation_quality_detects_negation_misplacement()
    test_allocation_quality_allows_negation_with_adjacent_predicate_completion()
    test_allocation_quality_accepts_common_chinese_negation_equivalents()
    test_allocation_quality_accepts_entity_spacing_equivalent()
    test_allocation_quality_accepts_chinese_number_equivalents()
    test_allocation_quality_accepts_decimal_wan_number_equivalent()
    test_number_anchor_accepts_billion_to_chinese_yi_conversion()
    test_number_anchor_accepts_decade_and_century_chinese_equivalents()
    test_negation_anchor_accepts_natural_chinese_question_tags_and_until_pattern()
    test_legacy_sample_specific_fragment_rules_are_not_hardcoded()
    test_allocation_quality_allows_adjacent_number_when_target_line_is_not_degraded()
    test_allocation_quality_rejects_adjacent_number_when_target_line_is_empty()
    test_allocation_quality_accepts_natural_subtitle_half_sentence()
    test_chinese_polish_rewrites_only_fixed_group_chinese_by_id()
    test_chinese_polish_skips_natural_groups_without_a_model_request()
    test_chinese_polish_selects_complex_comparison_group_by_fixed_ids()
    test_cross_subtitle_predicate_break_triggers_group_polish_by_fixed_ids()
    test_cross_subtitle_predicate_break_does_not_flag_normal_chinese_continuation()
    test_semantic_loss_recognizes_bingfei_as_negation()
    test_sentence_final_shide_is_not_a_dangling_chinese_fragment()
    test_allocation_retry_rejects_quality_regression_before_writeback()
    test_compare_allocation_candidates_accepts_strict_improvement_only()
    test_compare_allocation_candidates_rejects_new_high_confidence_issue()
    test_id_bound_candidate_decision_never_accepts_invalid_candidate()
    test_cross_id_leakage_requires_target_id_to_be_degraded()
    test_cross_id_leakage_flags_when_target_id_is_consumed_and_empty()
    test_allocation_quality_keeps_out_of_order_return_by_subtitle_id()
    test_allocation_quality_failed_group_does_not_shift_following_100_ids()
    test_compression_quality_regression_restores_previous_group_allocation()
    test_speed_compression_cannot_accept_number_omission_for_shorter_chinese()
    test_empty_middle_translation_keeps_its_own_id_slot()
    test_failed_group_does_not_shift_following_100_subtitles()
    test_failed_validation_does_not_write_final_output_file()
    test_non_structural_validation_errors_do_not_block_render_gate()
    test_final_segment_count_mismatch_is_structural_error()
    test_merge_preserves_ids_when_order_changes_before_final_write()
    test_repair_only_modifies_the_target_subtitle_id()
    test_compression_accepts_new_subtitle_id_protocol_without_position_shift()
    test_redistribution_parses_out_of_order_returns_by_subtitle_id()
    test_redistribution_parses_new_id_only_protocol_without_position_shift()
    test_compression_keeps_subtitle_ids_and_count()
    test_fallback_translation_fills_only_one_missing_subtitle_id()
    test_multiple_semantic_groups_apply_by_id_without_drift()
    test_full_merge_repair_chain_keeps_400_plus_ids_without_drift()
    test_passed_validation_writes_final_output_and_manifest_metadata()
    test_user_subtitle_exports_are_saved_to_source_audio_folder()
    test_id_bound_mapping_has_no_drift_over_400_subtitles()
    test_validation_summary_error_marks_stable_manifest_failed()
    test_runtime_module_import_path_is_available()
    test_whisperx_alignment_mapping_preserves_source_tokens_and_local_fallback()
    test_whisperx_time_only_preserves_text_and_translation_while_retiming()
    test_whisperx_frozen_ledger_keeps_only_unmatched_word_on_stable_ts_time()
    test_whisperx_frozen_ledger_reverts_a_candidate_that_inverts_fallback_word_order()
    test_whisperx_frozen_ledger_keeps_monotonic_candidate_updates()
    test_whisperx_time_only_falls_back_to_stable_ledger_without_changing_cues()
    test_whisperx_time_only_uses_expanded_frozen_ledger_not_source_segment_count()
    test_short_nonindependent_backchannel_attaches_to_previous_display_item()
    test_complete_unsplittable_overflow_is_warning_not_overlong_error()
    test_comma_terminated_parser_confirmed_subordinate_overflow_is_warning_not_error()
    test_comma_overflow_requires_parser_proof_and_no_safe_split()
    test_visual_reading_budget_keeps_complete_13_word_cue_for_renderer_wrapping()
    test_visual_reading_budget_keeps_character_heavy_cue_for_renderer_wrapping()
    test_visual_reading_budget_never_selects_preposition_object_cut()
    test_visual_reading_budget_does_not_create_a_review_for_renderer_wrapping()
    test_visual_reading_budget_keeps_short_open_phrase_with_its_sentence()
    test_visual_reading_budget_keeps_a_single_clause_for_renderer_wrapping()
    test_visual_reading_budget_rejects_short_preposition_led_display_tail()
    test_visual_reading_budget_never_creates_parser_confirmed_example_preposition_cut()
    test_stable_cut_keeps_comma_bracketed_adverb_with_preceding_list_item()
    test_visual_budget_keeps_subject_with_delayed_finite_predicate()
    test_visual_budget_keeps_short_gerundial_manner_phrase_with_main_question()
    test_visual_temporal_budget_splits_punctuated_fronted_introduction()
    test_visual_temporal_budget_splits_complete_punctuated_clauses()
    test_visual_temporal_budget_splits_complete_sentence_terminal()
    test_visual_temporal_budget_keeps_subject_with_delayed_predicate_despite_pause()
    test_visual_temporal_budget_rejects_punctuated_conditional_intro()
    test_final_timeline_rebuild_preserves_id_text_chinese_and_word_ownership()
    test_forced_alignment_finalization_never_moves_timing()
    test_duration_audit_reports_high_load_short_subtitle_as_warning()
    test_final_gate_blocks_protected_named_phrase_split()
    test_final_gate_blocks_protected_phrasal_boundary_split()
    test_final_gate_blocks_look_at_boundary_split()
    print("stable caption rule smoke tests passed")
