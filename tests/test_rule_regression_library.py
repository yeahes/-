import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bk_asr.asr_data import ASRDataSeg
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor, ScreenSubtitleItem


CASES_PATH = ROOT / "tests" / "fixtures" / "rule_regression_cases.json"


def _load_cases():
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _editor(max_words=16):
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = max_words
    editor.max_cjk_chars = 18
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


def test_rule_regression_fixture_has_unique_case_ids():
    data = _load_cases()
    seen = set()
    for category, cases in data.items():
        if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
            continue
        for case in cases:
            case_id = f"{category}:{case.get('id')}"
            assert case.get("id"), f"{category} has a case without id"
            assert case_id not in seen, f"duplicate case id: {case_id}"
            seen.add(case_id)


def test_rule_regression_english_syntax_boundaries():
    editor = _editor()
    for case in _load_cases()["english_syntax_boundaries"]:
        reasons = set(editor._syntax_boundary_reasons(case["left"], case["right"]))
        if case["expected"] == "warning":
            assert reasons, case["id"]
            for code in case.get("expected_codes", []):
                assert code in reasons, (case["id"], reasons)
        else:
            for code in case.get("forbidden_codes", []):
                assert code not in reasons, (case["id"], reasons)


def test_rule_regression_chinese_allocation_quality():
    editor = _editor()
    for case in _load_cases()["chinese_allocation_quality"]:
        if case.get("validator") == "semantic_group_context":
            subtitle_parts = case["entry"]["subtitle_parts"]
            segments = [
                ASRDataSeg(
                    text=part["english"],
                    translated_text=case["allocation"].get(part["subtitle_id"], ""),
                    start_time=index * 2000,
                    end_time=index * 2000 + 1600,
                )
                for index, part in enumerate(subtitle_parts)
            ]
            context = {
                "full_english": case["entry"]["full_english"],
                "full_translation": case["entry"]["full_translation"],
                "parts": [
                    {"index": index, "subtitle_id": part["subtitle_id"]}
                    for index, part in enumerate(subtitle_parts)
                ],
            }
            indexed_allocation = {
                index: case["allocation"].get(part["subtitle_id"], "")
                for index, part in enumerate(subtitle_parts)
            }
            valid = editor._is_valid_group_chinese_allocation(
                indexed_allocation,
                segments,
                context,
            )
            assert valid is case["valid"], case["id"]
            continue
        validation = editor._validate_group_chinese_allocation(
            case["entry"],
            case["allocation"],
        )
        assert validation["valid"] is case["valid"], (case["id"], validation)
        for code in case.get("expected_issue_codes", []):
            assert code in validation["issue_codes"], (case["id"], validation)


def test_rule_regression_timing_repairs_keep_text_and_ids():
    editor = _editor()
    for case in _load_cases()["timing_repairs"]:
        segments = [
            ASRDataSeg(
                text=segment["english"],
                start_time=segment["start_ms"],
                end_time=segment["end_ms"],
                translated_text=segment["chinese"],
            )
            for segment in case["segments"]
        ]
        for segment, source in zip(segments, case["segments"]):
            segment.subtitle_id = source["subtitle_id"]

        before = {
            segment.subtitle_id: (segment.text, segment.translated_text)
            for segment in segments
        }
        repaired = editor._repair_final_short_subtitle_timings(segments)
        by_id = {segment.subtitle_id: segment for segment in repaired}
        target = by_id[case["target_subtitle_id"]]

        assert target.end_time - target.start_time >= case["min_duration_ms"], case["id"]
        if case.get("expect_text_unchanged"):
            after = {
                segment.subtitle_id: (segment.text, segment.translated_text)
                for segment in repaired
            }
            assert after == before, case["id"]


def test_rule_regression_local_chinese_speed_fallbacks():
    editor = _editor()
    for case in _load_cases()["local_chinese_speed_fallback"]:
        seg = ASRDataSeg(
            text=case["english"],
            translated_text=case["chinese"],
            start_time=case["start_ms"],
            end_time=case["end_ms"],
        )
        fallback = editor._local_chinese_speed_fallback(seg)
        assert fallback == case["expected_chinese"], case["id"]
        assert editor._is_valid_chinese_compression(
            fallback,
            seg,
            [seg],
            0,
        ), case["id"]


def test_rule_regression_local_fallback_is_applied_when_llm_compression_misses():
    editor = _editor()
    editor._request_chinese_compression = lambda *args, **kwargs: {"items": []}
    cases = _load_cases()["local_chinese_speed_fallback"]
    segments = [
        ASRDataSeg(
            text=case["english"],
            translated_text=case["chinese"],
            start_time=case["start_ms"],
            end_time=case["end_ms"],
        )
        for case in cases
    ]
    for index, segment in enumerate(segments, 1):
        segment.subtitle_id = f"S{index:04d}"

    repaired = editor._compress_fast_chinese_segments(segments)

    assert [segment.text for segment in repaired] == [segment.text for segment in segments]
    assert [segment.subtitle_id for segment in repaired] == [segment.subtitle_id for segment in segments]
    assert [segment.translated_text for segment in repaired] == [
        case["expected_chinese"] for case in cases
    ]
    assert not editor._subtitle_health_issues(repaired)["reading_speed_errors"]


def test_rule_regression_speed_fallback_is_not_restored_as_soft_omission():
    editor = _editor()
    before = ASRDataSeg(
        text="But they have a much bigger test coming.",
        translated_text="但他们即将进行一次规模远大得多且影响深远的测试。",
        start_time=470400,
        end_time=471920,
    )
    before.subtitle_id = "S0154"
    after = ASRDataSeg(
        text=before.text,
        translated_text="更大的测试要来了。",
        start_time=before.start_time,
        end_time=before.end_time,
    )
    after.subtitle_id = before.subtitle_id

    keep = editor._should_keep_speed_repair_despite_soft_omission(
        [before],
        [after],
        {"issue_codes": ["group_allocation_information_omission"]},
    )

    assert keep is True


def test_rule_regression_translation_writeback_is_id_driven():
    editor = _editor()
    for case in _load_cases()["id_writeback"]:
        items_by_id = {}
        items = []
        for index, raw in enumerate(case["items"], 1):
            item = ScreenSubtitleItem(
                source_ids=[index],
                original=raw["english"],
                translated=raw["chinese"],
                word_start=index * 2,
                word_end=index * 2 + 1,
                subtitle_id=raw["subtitle_id"],
            )
            items.append(item)
            items_by_id[item.subtitle_id] = item

        groups = []
        for raw_group in case["groups"]:
            groups.append(
                {
                    "id": raw_group["id"],
                    "start_index": raw_group["start_index"],
                    "items": [items_by_id[subtitle_id] for subtitle_id in raw_group["subtitle_ids"]],
                }
            )

        translations_by_group = {
            int(group_id): translations
            for group_id, translations in case["translations_by_group"].items()
        }
        applied = editor._apply_semantic_group_translations(
            items,
            groups,
            translations_by_group,
        )

        assert [item.subtitle_id for item in applied] == [item.subtitle_id for item in items], case["id"]
        assert [item.translated for item in applied] == case["expected_chinese"], case["id"]


if __name__ == "__main__":
    test_rule_regression_fixture_has_unique_case_ids()
    test_rule_regression_english_syntax_boundaries()
    test_rule_regression_chinese_allocation_quality()
    test_rule_regression_timing_repairs_keep_text_and_ids()
    test_rule_regression_local_chinese_speed_fallbacks()
    test_rule_regression_local_fallback_is_applied_when_llm_compression_misses()
    test_rule_regression_speed_fallback_is_not_restored_as_soft_omission()
    test_rule_regression_translation_writeback_is_id_driven()
    print("rule regression library tests passed")
