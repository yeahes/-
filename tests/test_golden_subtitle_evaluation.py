import json
import tempfile
from pathlib import Path

from app.core.subtitle_processor.authoritative_parent_chinese import (
    bind_display_page_parent_records,
    build_authoritative_parent_chinese_artifact,
)
from app.core.subtitle_processor.stable_display_page_contract import (
    build_display_page_contract,
    validate_page_translation_response,
)
from scripts.evaluate_golden_subtitles import _resolve_artifact_dir, evaluate_golden_subtitles


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_run(root: Path, *, english: str = "We met Pop Mart in 2024.", chinese: str = "我们在2024年见到了泡泡玛特。", end_ms: int = 500) -> Path:
    artifacts = root / "sample-artifacts"
    artifacts.mkdir(parents=True)
    _write_json(
        artifacts / "subtitle-spans.json",
        [
            {
                "subtitle_id": "S0001",
                "word_start": 0,
                "word_end": 5,
                "original": english,
                "translated": chinese,
            },
            {
                "subtitle_id": "S0002",
                "word_start": 6,
                "word_end": 8,
                "original": "It grew quickly.",
                "translated": "它增长很快。",
            },
        ],
    )
    words = []
    for index, word in enumerate("We met Pop Mart in 2024 It grew quickly".split()):
        words.append(
            {
                "word_id": index,
                "surface": word,
                "start_ms": index * 100,
                "end_ms": end_ms if index == 5 else index * 100 + 90,
            }
        )
    _write_json(artifacts / "word-ledger.json", {"words": words, "source_segments": []})
    return artifacts


def _reference() -> dict:
    return {
        "schema_version": 1,
        "sample_id": "golden-smoke",
        "english_text": "We met Pop Mart in 2024. It grew quickly.",
        "entities": [{"canonical_name": "Pop Mart", "category": "brand"}],
        "boundaries_after_word_index": [5],
        "word_timings": [
            {"word_id": 0, "start_ms": 0, "end_ms": 90},
            {"word_id": 5, "start_ms": 500, "end_ms": 500},
        ],
        "chinese_anchors": [
            {
                "anchor_id": "brand-and-year",
                "subtitle_ids": ["S0001"],
                "must_contain_any": [["泡泡玛特"], ["2024"]],
                "must_not_contain": ["2025"],
            }
        ],
        "thresholds": {
            "max_word_error_rate": 0.03,
            "min_recall": 1.0,
            "min_f1": 1.0,
            "max_mean_absolute_error_ms": 1,
            "max_p90_absolute_error_ms": 1,
        },
    }


def _write_v2_run(
    root: Path,
    *,
    first_id: str = "S0001",
    second_id: str = "S0002",
    timeline_status: str = "PASS",
    include_authority: bool = True,
) -> Path:
    artifacts = root / "v2-artifacts"
    artifacts.mkdir(parents=True)
    english_rows = [
        (first_id, 0, 5, "We met Pop Mart in 2024."),
        (second_id, 6, 8, "It grew quickly."),
    ]
    chinese_by_id = {
        first_id: "我们在2024年见到了泡泡玛特。",
        second_id: "它发展得很快。",
    }
    _write_json(
        artifacts / "subtitle-spans.json",
        [
            {
                "subtitle_id": subtitle_id,
                "word_start": word_start,
                "word_end": word_end,
                "original": english,
                "translated": "错误的旧投影",
            }
            for subtitle_id, word_start, word_end, english in english_rows
        ],
    )
    words = [
        {
            "word_id": index,
            "surface": word,
            "start_ms": index * 100,
            "end_ms": index * 100 + 90,
        }
        for index, word in enumerate("We met Pop Mart in 2024 It grew quickly".split())
    ]
    _write_json(
        artifacts / "word-ledger.json",
        {
            "schema_version": 2,
            "hash_version": "canonical-word-ledger-v1",
            "hash": "golden-ledger-hash",
            "words": words,
            "source_segments": [],
        },
    )
    authority = build_authoritative_parent_chinese_artifact(
        [
            {
                "subtitle_id": subtitle_id,
                "english": english,
                "chinese": chinese_by_id[subtitle_id],
                "word_start": word_start,
                "word_end": word_end,
            }
            for subtitle_id, word_start, word_end, english in english_rows
        ],
        source_word_ledger_hash="golden-ledger-hash",
        producer="golden-test",
    )
    if include_authority:
        _write_json(artifacts / "authoritative-parent-chinese.json", authority)
        _write_json(
            artifacts / "translations.json",
            [
                {
                    "subtitle_id": record["subtitle_id"],
                    "text": record["english"],
                    "translated_text": record["chinese"],
                    "parent_source_hash": record["source_hash"],
                    "parent_record_hash": record["record_hash"],
                }
                for record in authority["records"]
            ],
        )
    _write_json(
        artifacts / "final-cue-timeline.json",
        {
            "schema_version": 2,
            "records": [
                {
                    "subtitle_id": subtitle_id,
                    "word_start": word_start,
                    "word_end": word_end,
                    "original": english,
                    "translated": chinese_by_id[subtitle_id],
                    "start_ms": word_start * 100,
                    "end_ms": word_end * 100 + 90,
                }
                for subtitle_id, word_start, word_end, english in english_rows
            ],
            "validation": {
                "status": timeline_status,
                "error_count": 0 if timeline_status == "PASS" else 1,
                "errors": [] if timeline_status == "PASS" else ["forced failure"],
            },
        },
    )
    _write_json(
        artifacts / "validation-report.json",
        {"status": "WARNING", "errors": [], "warnings": ["review only"], "info": []},
    )
    _write_json(
        artifacts / "english-boundary-audit.json",
        {"schema_version": 2, "summary": {"hard": 0, "review": 1, "allow": 1}, "records": []},
    )
    render_plans = []
    contract_parents = []
    authority_by_id = {
        record["subtitle_id"]: record for record in authority["records"]
    }
    for subtitle_id, word_start, word_end, english in english_rows:
        if subtitle_id == first_id:
            page_specs = [
                (word_start, word_start + 2, "We met Pop"),
                (word_start + 3, word_end, "Mart in 2024."),
            ]
        else:
            page_specs = [(word_start, word_end, english)]
        pages = [
            {
                "display_page_id": f"{subtitle_id}.P{page_index:02d}",
                "page_index": page_index,
                "word_start": page_start,
                "word_end": page_end,
                "english": page_english,
                "start_ms": page_start * 100,
                "end_ms": page_end * 100 + 90,
                "english_lines": [page_english],
                "english_font_size": 56,
                "english_width": 600,
            }
            for page_index, (page_start, page_end, page_english) in enumerate(
                page_specs,
                1,
            )
        ]
        render_plans.append(
            {
                "parent_subtitle_id": subtitle_id,
                "english": english,
                "chinese": chinese_by_id[subtitle_id],
                "word_start": word_start,
                "word_end": word_end,
                "english_font_size": 56,
                "font_fallback": {"used": False},
                "pages": pages,
            }
        )
        if len(pages) > 1:
            contract_parents.append(
                {
                    "parent_subtitle_id": subtitle_id,
                    "english": english,
                    "chinese": chinese_by_id[subtitle_id],
                    "word_start": word_start,
                    "word_end": word_end,
                    "pages": pages,
                }
            )
    contract = build_display_page_contract(
        contract_parents,
        layout_profile={"profile": "golden-test"},
        planner_version="golden-test-v1",
        render_plans=render_plans,
    )
    first_page_ids = [
        page["display_page_id"] for page in contract["parents"][0]["pages"]
    ]
    page_artifact = validate_page_translation_response(
        contract,
        {
            "pages": [
                {"display_page_id": first_page_ids[0], "zh": "我们在2024年"},
                {"display_page_id": first_page_ids[1], "zh": "见到了泡泡玛特。"},
            ]
        },
    )
    page_artifact = bind_display_page_parent_records(
        page_artifact,
        authority_by_id,
    )
    _write_json(
        artifacts / "display-page-translations.json",
        page_artifact,
    )
    return artifacts


def _v2_reference() -> dict:
    full_anchor = "We met Pop Mart in 2024 It grew quickly"
    return {
        "schema_version": 2,
        "sample_id": "golden-v2-smoke",
        "english_segmentation": {
            "windows": [
                {
                    "anchor_id": "two-sentences",
                    "english_anchor": full_anchor,
                    "expected_segments": ["We met Pop Mart in 2024", "It grew quickly"],
                }
            ]
        },
        "parent_translation": {
            "anchors": [
                {
                    "anchor_id": "brand-and-year",
                    "english_anchor": "We met Pop Mart in 2024",
                    "must_contain_any": [["泡泡玛特"], ["2024"]],
                    "must_not_contain": ["2025"],
                }
            ]
        },
        "fixed_id_allocation": {
            "anchors": [
                {
                    "anchor_id": "brand-owner",
                    "english_anchor": "Pop Mart",
                    "must_contain_any": [["泡泡玛特"]],
                    "must_not_appear_in_adjacent": True,
                }
            ]
        },
        "display_pages": {
            "windows": [
                {
                    "anchor_id": "two-pages",
                    "english_anchor": full_anchor,
                    "expected_segments": [
                        "We met Pop",
                        "Mart in 2024",
                        "It grew quickly",
                    ],
                    "max_words_per_page": 6,
                    "min_english_font_size": 52,
                    "max_english_lines": 2,
                }
            ]
        },
        "thresholds": {"min_overall_score": 0.90, "min_component_score": 0.85},
    }


def test_golden_evaluation_passes_for_matching_run():
    with tempfile.TemporaryDirectory() as temp_dir:
        report = evaluate_golden_subtitles(_reference(), _write_run(Path(temp_dir)))

    assert report["status"] == "PASS"
    assert report["scores"]["english"]["word_error_rate"] == 0.0
    assert report["scores"]["entities"]["recall"] == 1.0
    assert report["scores"]["boundaries"]["f1"] == 1.0
    assert report["scores"]["timing"]["mean_absolute_error_ms"] == 0.0
    assert report["scores"]["chinese_anchors"]["failures"] == []


def test_golden_evaluation_reports_word_entity_timing_and_chinese_failures():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_run(
            Path(temp_dir),
            english="We met Popmark in 2024.",
            chinese="我们在2025年见到了这个品牌。",
            end_ms=900,
        )
        report = evaluate_golden_subtitles(_reference(), artifacts)

    codes = {failure["code"] for failure in report["failures"]}
    assert report["status"] == "FAIL"
    assert "english_word_error_rate_too_high" in codes
    assert "entities_recall_too_low" in codes
    assert "timing_mean_absolute_error_ms_too_high" in codes
    assert "chinese_fact_anchor_failed" in codes


def test_v2_uses_authoritative_parent_chinese_and_is_independent_of_subtitle_ids():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir), first_id="PARENT-A", second_id="PARENT-B")
        report = evaluate_golden_subtitles(_v2_reference(), artifacts)

    assert report["status"] == "PASS"
    assert report["hard_gates"]["status"] == "PASS"
    assert report["quality"]["overall_score"] == 1.0
    assert report["sources"]["parent_chinese"] == "authoritative-parent-chinese.json"
    assert report["quality"]["components"]["fixed_id_allocation"]["items"][0]["resolved_subtitle_id"] == "PARENT-A"


def test_v2_falls_back_to_legacy_timeline_chinese_when_authority_is_absent():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir), include_authority=False)
        report = evaluate_golden_subtitles(_v2_reference(), artifacts)

    assert report["status"] == "PASS"
    assert report["sources"]["parent_chinese"] == "final-cue-timeline.json"


def test_v2_legacy_package_allows_absent_newer_audit_files_with_explicit_notes():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir), include_authority=False)
        (artifacts / "validation-report.json").unlink()
        (artifacts / "english-boundary-audit.json").unlink()
        report = evaluate_golden_subtitles(_v2_reference(), artifacts)

    assert report["status"] == "PASS"
    assert {item["code"] for item in report["compatibility"]["notes"]} == {
        "run_validation_report_missing",
        "run_english_boundary_audit_missing",
    }


def test_v2_modern_package_requires_validation_and_boundary_evidence():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir))
        (artifacts / "validation-report.json").unlink()
        (artifacts / "english-boundary-audit.json").unlink()
        report = evaluate_golden_subtitles(_v2_reference(), artifacts)

    codes = {item["code"] for item in report["hard_gates"]["failures"]}
    assert report["status"] == "FAIL"
    assert "run_validation_report_missing" in codes
    assert "run_english_boundary_audit_missing" in codes


def test_v2_legacy_timeline_chinese_must_match_frozen_english_identity():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir), include_authority=False)
        timeline_path = artifacts / "final-cue-timeline.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["records"][0]["original"] = "Different English text."
        _write_json(timeline_path, timeline)
        report = evaluate_golden_subtitles(_v2_reference(), artifacts)

    codes = {item["code"] for item in report["hard_gates"]["failures"]}
    assert report["status"] == "FAIL"
    assert "run_final_timeline_english_mismatch" in codes
    assert "run_parent_chinese_legacy_identity_mismatch" in codes


def test_v2_hard_gate_failure_cannot_be_hidden_by_perfect_quality_scores():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir), timeline_status="ERROR")
        report = evaluate_golden_subtitles(_v2_reference(), artifacts)

    codes = {failure["code"] for failure in report["failures"]}
    assert report["status"] == "FAIL"
    assert report["quality"]["overall_score"] == 1.0
    assert "run_final_timeline_invalid" in codes


def test_v2_rejects_one_component_below_85_even_when_overall_exceeds_90():
    reference = _v2_reference()
    reference["parent_translation"]["anchors"][0]["must_contain_any"] = [
        ["泡泡玛特"],
        ["2024"],
        ["见到"],
        ["不存在的事实"],
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        report = evaluate_golden_subtitles(reference, _write_v2_run(Path(temp_dir)))

    component_failures = [
        failure
        for failure in report["failures"]
        if failure["code"] == "quality_component_score_too_low"
    ]
    assert report["quality"]["overall_score"] > 0.90
    assert [failure["component"] for failure in component_failures] == ["parent_translation"]


def test_v2_rejects_ambiguous_english_anchor_without_occurrence():
    reference = _v2_reference()
    reference["fixed_id_allocation"]["anchors"][0]["english_anchor"] = "in"
    changed_full_anchor = "We met Pop Mart in 2024 It grew in"
    reference["english_segmentation"]["windows"][0]["english_anchor"] = changed_full_anchor
    reference["english_segmentation"]["windows"][0]["expected_segments"][-1] = "It grew in"
    reference["display_pages"]["windows"][0]["english_anchor"] = changed_full_anchor
    reference["display_pages"]["windows"][0]["expected_segments"][-1] = "It grew in"
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir), include_authority=False)
        ledger_path = artifacts / "word-ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["words"][-1]["surface"] = "in"
        _write_json(ledger_path, ledger)
        try:
            evaluate_golden_subtitles(reference, artifacts)
        except ValueError as exc:
            assert str(exc) == "golden_reference_anchor_ambiguous"
        else:
            raise AssertionError("ambiguous anchor was accepted")


def test_v2_allocation_adjacent_check_requires_all_fact_groups():
    reference = _v2_reference()
    reference["fixed_id_allocation"]["anchors"][0]["must_contain_any"] = [
        ["泡泡玛特"],
        ["2024"],
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir))
        timeline_path = artifacts / "final-cue-timeline.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["records"][1]["translated"] = "2024年它发展得很快。"
        _write_json(timeline_path, timeline)
        report = evaluate_golden_subtitles(reference, artifacts)

    allocation = report["quality"]["components"]["fixed_id_allocation"]
    assert allocation["score"] == 1.0
    assert allocation["items"][0]["adjacent_matches"] == []


def test_v2_rejects_display_pages_bound_to_stale_parent_authority():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir))
        page_path = artifacts / "display-page-translations.json"
        page_artifact = json.loads(page_path.read_text(encoding="utf-8"))
        page_artifact["parents"][0]["parent_record_hash"] = "stale-record"
        _write_json(page_path, page_artifact)
        report = evaluate_golden_subtitles(_v2_reference(), artifacts)

    codes = {item["code"] for item in report["hard_gates"]["failures"]}
    assert report["status"] == "FAIL"
    assert "run_display_page_parent_authority_mismatch" in codes


def test_curated_v2_reference_fixtures_are_loaded_by_offline_regression():
    fixture_dir = Path(__file__).parent / "fixtures" / "golden_subtitles"
    fixture_names = {"dreamcore-v2.json", "bad-animation-v2.json"}

    for fixture_name in fixture_names:
        reference = json.loads((fixture_dir / fixture_name).read_text(encoding="utf-8"))
        assert reference["schema_version"] == 2
        assert set(reference) >= {
            "english_segmentation",
            "parent_translation",
            "fixed_id_allocation",
            "display_pages",
            "thresholds",
        }
        for section, key in (
            ("english_segmentation", "windows"),
            ("parent_translation", "anchors"),
            ("fixed_id_allocation", "anchors"),
            ("display_pages", "windows"),
        ):
            assert reference[section][key]


def test_artifact_resolution_uses_stable_manifest_instead_of_ambiguous_old_runs():
    with tempfile.TemporaryDirectory() as temp_dir:
        subtitle_root = Path(temp_dir) / "subtitle"
        current = _write_run(subtitle_root / "stable-runs" / "current")
        _write_run(subtitle_root / "stable-runs" / "old")
        _write_json(
            subtitle_root / "stable-final-manifest.json",
            {"schema_version": 2, "stable_run_dir": str(current.parent)},
        )

        resolved = _resolve_artifact_dir(subtitle_root)

    assert resolved.name == "sample-artifacts"
    assert resolved.parent.name == "current"


def test_v2_page_pass_status_cannot_hide_missing_multipage_chinese():
    reference = _v2_reference()
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_v2_run(Path(temp_dir))
        page_path = artifacts / "display-page-translations.json"
        page_artifact = json.loads(page_path.read_text(encoding="utf-8"))
        first_plan = page_artifact["render_plans"][0]
        first_parent = page_artifact["parents"][0]
        original_page = first_plan["pages"][0]
        split_page = {
            **original_page,
            "display_page_id": "S0001.P01",
            "word_start": 0,
            "word_end": 2,
            "english": "We met Pop",
        }
        second_page = {
            **original_page,
            "display_page_id": "S0001.P02",
            "page_index": 2,
            "word_start": 3,
            "word_end": 5,
            "english": "Mart in 2024.",
        }
        first_plan["pages"] = [split_page, second_page]
        first_parent["pages"] = [
            {**split_page, "zh": "我们见到了"},
            {**second_page, "zh": ""},
        ]
        _write_json(page_path, page_artifact)
        report = evaluate_golden_subtitles(reference, artifacts)

    codes = {failure["code"] for failure in report["hard_gates"]["failures"]}
    assert report["status"] == "FAIL"
    assert "run_display_page_translation_missing" in codes


if __name__ == "__main__":
    test_golden_evaluation_passes_for_matching_run()
    test_golden_evaluation_reports_word_entity_timing_and_chinese_failures()
    test_v2_uses_authoritative_parent_chinese_and_is_independent_of_subtitle_ids()
    test_v2_falls_back_to_legacy_timeline_chinese_when_authority_is_absent()
    test_v2_legacy_package_allows_absent_newer_audit_files_with_explicit_notes()
    test_v2_modern_package_requires_validation_and_boundary_evidence()
    test_v2_legacy_timeline_chinese_must_match_frozen_english_identity()
    test_v2_hard_gate_failure_cannot_be_hidden_by_perfect_quality_scores()
    test_v2_rejects_one_component_below_85_even_when_overall_exceeds_90()
    test_v2_rejects_ambiguous_english_anchor_without_occurrence()
    test_v2_allocation_adjacent_check_requires_all_fact_groups()
    test_v2_rejects_display_pages_bound_to_stale_parent_authority()
    test_curated_v2_reference_fixtures_are_loaded_by_offline_regression()
    test_artifact_resolution_uses_stable_manifest_instead_of_ambiguous_old_runs()
    test_v2_page_pass_status_cannot_hide_missing_multipage_chinese()
    print("golden subtitle evaluation tests passed")
