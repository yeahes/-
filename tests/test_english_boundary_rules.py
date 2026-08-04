"""Fixture-backed contracts for local stable English boundary legality."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bk_asr.asr_data import ASRDataSeg
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor


CASES_PATH = ROOT / "tests" / "fixtures" / "stable_boundaries" / "syntax_boundary_contract.json"
AUDIT_CASES_PATH = ROOT / "tests" / "fixtures" / "stable_boundaries" / "boundary_audit_contract.json"


def _boundary_editor(words):
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = 16
    editor._syntax_protected_cuts = set()
    editor._syntax_hard_cut_issues = {}
    editor._syntax_nlp = None
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
        index + 1: (index, index) for index in range(len(words))
    }
    editor._active_source_segments_by_id = {
        index + 1: ASRDataSeg(word, index * 200, index * 200 + 120, "")
        for index, word in enumerate(words)
    }
    return editor


def test_fixture_backed_stable_boundary_contracts():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        editor = _boundary_editor(case["words"])
        if case.get("manual_syntax_issue"):
            editor._record_syntax_hard_issue_for_indices(
                case["manual_syntax_indices"],
                case["manual_syntax_issue"],
            )
        for cut_after in case["cut_after_indices"]:
            evaluation = editor._evaluate_stable_cut_boundary(cut_after, cut_after + 1)
            assert evaluation["legal"] is case["expected_legal"], (case["id"], evaluation)
            if case["expected_issue"]:
                assert case["expected_issue"] in evaluation["hard_issues"], (
                    case["id"],
                    evaluation,
                )
            else:
                assert evaluation["hard_issues"] == [], (case["id"], evaluation)


def _boundary_audit_segments(editor, cut_after: int):
    left = editor._item_from_word_span(0, cut_after)
    right = editor._item_from_word_span(cut_after + 1, len(editor._active_word_entries) - 1)
    assert left is not None and right is not None
    left.subtitle_id = "S0001"
    right.subtitle_id = "S0002"
    editor._last_subtitle_items = [left, right]
    segments = []
    for item in (left, right):
        start_ms, end_ms = editor._item_word_timing(item)
        segment = ASRDataSeg(item.original, start_ms, end_ms, "")
        segment.subtitle_id = item.subtitle_id
        segments.append(segment)
    return segments


def test_fixture_backed_whole_file_boundary_audit_contracts():
    cases = json.loads(AUDIT_CASES_PATH.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        editor = _boundary_editor(case["words"])
        pause_ms = case.get("pause_ms")
        if pause_ms is not None:
            cut_after = int(case["cut_after"])
            current_pause = (
                editor._active_word_entries[cut_after + 1]["start_time"]
                - editor._active_word_entries[cut_after]["end_time"]
            )
            for entry in editor._active_word_entries[cut_after + 1:]:
                entry["start_time"] += int(pause_ms) - current_pause
                entry["end_time"] += int(pause_ms) - current_pause

        records = editor._scan_final_english_boundaries(
            _boundary_audit_segments(editor, int(case["cut_after"]))
        )

        assert len(records) == 1
        record = records[0]
        assert record["classification"] == case["expected_classification"], (case["id"], record)
        if case["expected_issue"]:
            assert case["expected_issue"] in record["rule_codes"], (case["id"], record)
        else:
            assert record["rule_codes"] == [], (case["id"], record)


def test_residual_hard_boundary_blocks_export():
    editor = _boundary_editor(
        ["The", "fund", "raised", "one", "hundred", "million", "dollars."]
    )
    editor._translation_structure_errors = []
    editor._final_cue_timeline = {}
    segments = _boundary_audit_segments(editor, 4)
    audit = editor._scan_final_english_boundaries(segments)
    health = {
        "overlong_english": [],
        "structural_english_overflow": [],
        "bad_cuts": [],
        "translationese": [],
        "reading_speed_errors": [],
        "reading_speed_warnings": [],
        "duration_errors": [],
        "duration_warnings": [],
        "duplicate_chinese": [],
        "asr_suspicious": [],
        "discourse_marker_orphans": [],
        "syntax_boundary_audit": audit,
        "chinese_semantic_group_warnings": [],
        "chinese_semantic_group_info": [],
    }

    editor.last_validation_summary = editor._validation_summary([], [], health, segments)

    assert any(
        group["code"] == "hard_english_boundary"
        for group in editor.last_validation_summary["errors"]
    )
    assert editor.has_blocking_validation_errors()


if __name__ == "__main__":
    test_fixture_backed_stable_boundary_contracts()
    test_fixture_backed_whole_file_boundary_audit_contracts()
    test_residual_hard_boundary_blocks_export()
    print("English boundary rule tests passed.")
