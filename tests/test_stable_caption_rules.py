import sys
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor, ScreenSubtitleItem
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
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


def test_missing_translation_is_blocking_error():
    editor = _editor()
    source = [ASRDataSeg("Hello world.", 0, 1000)]
    final = [ASRDataSeg("Hello world.", 0, 1000, translated_text="")]

    editor._report_subtitle_coverage_gaps(source, final)

    assert editor.last_validation_summary["status"] == "ERROR"
    assert editor.has_blocking_validation_errors()
    assert "缺少中文字幕" in editor.blocking_validation_message()


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


def test_chinese_reading_speed_error_blocks_synthesis():
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
    assert editor.has_blocking_validation_errors()
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
        editor._semantic_audit_signature(english): {
            "semantic_group_id": "G0001",
            "group_id": 1,
            "full_english": english,
            "full_translation": "\u8fd9\u662f\u4e00\u4e2a\u503c\u5f97\u601d\u8003\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u4f60\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c\u65f6\u53ef\u4ee5\u601d\u8003\u4e00\u4e0b\u3002",
            "mapping_valid": True,
        }
    }

    issues = editor._chinese_semantic_group_audit_issues(segments)

    assert issues
    assert "semantic_loss" in issues[0]["reason"]


def test_chinese_semantic_audit_skips_semantic_loss_when_mapping_invalid():
    editor = _editor()
    segments = [
        ASRDataSeg("Bouncing the sunlight away.", 1000, 2500, "\u628a\u9633\u5149\u53cd\u5c04\u56de\u53bb\u3002")
    ]
    editor._last_semantic_group_audit_contexts = {
        "oh yeah": {
            "semantic_group_id": "G0002",
            "full_translation": "\u662f\u7684\u3002",
            "mapping_valid": True,
        }
    }

    issues = editor._chinese_semantic_group_audit_issues(segments, "WARNING")

    assert not [issue for issue in issues if "semantic_loss" in issue.get("reason", "")]


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
    test_missing_translation_is_blocking_error()
    test_suspicious_cut_is_warning_not_blocking()
    test_abnormal_timing_gap_is_repaired_for_compressed_cluster()
    test_coverage_gap_does_not_sum_natural_pauses()
    test_coverage_gap_blocks_single_long_uncovered_span()
    test_chinese_reading_speed_error_blocks_synthesis()
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
    test_command_chinese_audit_catches_confirmed_bad_groups()
    test_command_chinese_audit_ignores_normal_short_groups()
    test_very_short_subtitle_has_dedicated_duration_error()
    test_short_backchannel_duration_is_warning_not_error()
    test_short_regular_sentence_duration_remains_error()
    test_asr_suspicious_phrases_are_reported_without_fixing_text()
    test_short_subtitle_gets_minimum_display_duration_when_room_allows()
    test_short_backchannel_merges_with_following_segment()
    test_short_sentence_bridges_small_gap_before_next_subtitle()
    test_podcast_template_prefers_stable_manifest_subtitle()
    test_stable_srt_writer_keeps_bilingual_original_top()
    test_runtime_module_import_path_is_available()
    print("stable caption rule smoke tests passed")
