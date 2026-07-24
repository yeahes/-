import sys
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor, ScreenSubtitleItem
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.entities import SubtitleConfig, SubtitleTask
from app.thread.subtitle_thread import SubtitleThread
from app.thread.video_synthesis_thread import resolve_podcast_template_subtitle
from tests.caption_audit.metrics import (
    CaptionCue,
    _chinese_semantic_group_issues,
    _syntax_boundary_reasons,
    split_bilingual_body,
    count_words,
)


def _editor(max_words=14):
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = max_words
    editor._syntax_protected_cuts = set()
    editor._active_word_entries = []
    editor.coverage_report_path = None
    editor.last_validation_summary = None
    editor._frozen_subtitle_ids = []
    editor._translation_structure_errors = []
    editor._last_llm_raw_returns = []
    editor._last_semantic_group_debug = []
    editor._last_semantic_group_audit_contexts = {}
    editor._last_semantic_group_id_by_subtitle_id = {}
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


def _words(text):
    return ScreenSubtitleEditor._word_tokens(text)


def _id_editor():
    editor = _editor()
    editor.max_cjk_chars = 18
    editor._translation_structure_errors = []
    editor._last_llm_raw_returns = []
    editor._last_semantic_group_debug = []
    editor._last_semantic_group_audit_contexts = {}
    editor._last_semantic_group_id_by_subtitle_id = {}
    editor.article_context_prompt = ""
    editor._frozen_subtitle_ids = []
    editor._llm_cache_used = False
    return editor


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


def _assert_stable_split(text):
    parts = _split_text(text)
    assert parts
    rebuilt = [word for part in parts for word in _words(part)]
    assert rebuilt == _words(text)
    for part in parts:
        assert len(_words(part)) <= 14, part
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
    ]

    issues = editor._asr_suspicious_issues(segments)
    codes = {issue.get("rule_code") for issue in issues}

    assert "asr_ungrammatical_collocation" in codes
    assert "asr_semantic_nonsense" in codes


def test_short_subtitle_gets_minimum_display_duration_when_room_allows():
    segments = [
        ASRDataSeg("Exactly.", 18420, 18680, "ok"),
        ASRDataSeg("But what happens next?", 19560, 23280, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time - adjusted[0].start_time >= 900
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


def test_standalone_discourse_marker_attaches_to_immediate_next_sentence():
    editor = _marker_editor(["I", "mean,", "this", "market", "changed."])
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 1
    assert merged[0].original == "I mean, this market changed."
    assert editor._discourse_marker_orphans == []


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
    items = editor._assign_global_subtitle_ids(_id_items(25))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 26)]
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
                            "subtitle_id": entry["subtitle_parts"][0]["subtitle_id"],
                            "zh": f"zh-{entry['subtitle_parts'][0]['subtitle_id']}",
                        }
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
    assert allocated[1] == {"S0001": "zh-S0001"}
    assert allocated[25] == {"S0025": "zh-S0025"}
    assert editor._translation_structure_errors == []


def test_allocation_retries_incomplete_chunk_by_single_group_without_lingering_errors():
    editor = _id_editor()
    editor.batch_num = 24
    items = editor._assign_global_subtitle_ids(_id_items(3))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 4)]
    full_translations = {index: f"full-{index}" for index in range(1, 4)}
    calls = []

    def request(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        calls.append((cache_task, [entry["id"] for entry in payload]))
        if cache_task == "screen_subtitle_semantic_translation_allocation":
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
        ("screen_subtitle_semantic_translation_allocation", [1, 2, 3]),
        ("screen_subtitle_semantic_translation_allocation_retry", [1]),
        ("screen_subtitle_semantic_translation_allocation_retry", [2]),
        ("screen_subtitle_semantic_translation_allocation_retry", [3]),
    ]
    assert allocated == {
        1: {"S0001": "zh-S0001"},
        2: {"S0002": "zh-S0002"},
        3: {"S0003": "zh-S0003"},
    }
    assert editor._translation_structure_errors == []


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


def test_passed_validation_writes_final_output_and_manifest_metadata():
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

        manifest = json.loads((root / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert manifest["render_blocked"] is False
        assert manifest["translation_model"] == "deepseek-v4-flash"
        assert manifest["code_commit"] == "abc123"
        assert manifest["cache_used"] is False
        assert manifest["prompt_version"] == "global-subtitle-id-v2"
        assert (root / "output.srt").exists()


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


def test_non_structural_validation_errors_still_write_stable_artifacts():
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
        assert manifest["validation_status"] == "passed"
        assert manifest["render_blocked"] is False
        assert manifest["validation_error_codes"] == ["subtitle_duration_invalid"]
        assert Path(manifest["paths"]["original_top_srt"]).exists()
        assert (root / "output.srt").exists()


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


if __name__ == "__main__":
    test_preposition_phrase_is_not_stranded()
    test_number_and_policy_sentence_keeps_readable_boundaries()
    test_long_finance_sentence_keeps_full_coverage()
    test_missing_translation_is_reported_but_not_blocking()
    test_suspicious_cut_is_warning_not_blocking()
    test_abnormal_timing_gap_is_repaired_for_compressed_cluster()
    test_coverage_gap_does_not_sum_natural_pauses()
    test_coverage_gap_blocks_single_long_uncovered_span()
    test_chinese_reading_speed_error_is_reported_but_not_blocking()
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
    test_short_subtitle_gets_minimum_display_duration_when_room_allows()
    test_short_backchannel_merges_with_following_segment()
    test_short_sentence_bridges_small_gap_before_next_subtitle()
    test_standalone_discourse_marker_attaches_to_immediate_next_sentence()
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
    test_podcast_template_prefers_stable_manifest_subtitle()
    test_stable_srt_writer_keeps_bilingual_original_top()
    test_id_bound_group_missing_one_id_does_not_shift_later_subtitles()
    test_id_bound_group_rejects_duplicate_id_without_compressing_chinese()
    test_id_bound_group_rejects_unknown_id()
    test_id_bound_group_allows_different_return_order()
    test_empty_middle_translation_keeps_its_own_id_slot()
    test_failed_group_does_not_shift_following_100_subtitles()
    test_failed_validation_does_not_write_final_output_file()
    test_non_structural_validation_errors_do_not_block_render_gate()
    test_final_segment_count_mismatch_is_structural_error()
    test_merge_preserves_ids_when_order_changes_before_final_write()
    test_repair_only_modifies_the_target_subtitle_id()
    test_redistribution_parses_out_of_order_returns_by_subtitle_id()
    test_compression_keeps_subtitle_ids_and_count()
    test_fallback_translation_fills_only_one_missing_subtitle_id()
    test_multiple_semantic_groups_apply_by_id_without_drift()
    test_full_merge_repair_chain_keeps_400_plus_ids_without_drift()
    test_passed_validation_writes_final_output_and_manifest_metadata()
    test_id_bound_mapping_has_no_drift_over_400_subtitles()
    test_non_structural_validation_errors_still_write_stable_artifacts()
    test_runtime_module_import_path_is_available()
    print("stable caption rule smoke tests passed")
