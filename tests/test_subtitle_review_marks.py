import copy
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.subtitle_processor.subtitle_review_marks import (
    SubtitleReviewMark,
    load_subtitle_review_marks,
    review_marks_require_syntax_parser,
    review_marks_from_payload,
    review_marks_to_payload,
)
from app.view.subtitle_interface import SubtitleTableModel
from PyQt5.QtCore import Qt
from qfluentwidgets import isDarkTheme


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _marks_for(marks, subtitle_id: str):
    return {(mark.severity, mark.category, mark.target, mark.code) for mark in marks.get(subtitle_id, [])}


def test_review_marks_ignore_noisy_audits_and_keep_verified_id_markers_only():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "translation-structure-errors.json",
            [{"code": "translation_id_missing", "subtitle_ids": ["S0001"]}],
        )
        _write_json(
            artifact_dir / "validation-report.json",
            {
                "errors": [],
                "warnings": [
                    {
                        "code": "syntax_boundary_audit",
                        "items": [
                            {
                                "left_subtitle_id": "S0002",
                                "right_subtitle_id": "S0003",
                                "confidence": "high",
                                "reason": "subject_finite_verb_split",
                            }
                        ],
                    },
                    {
                        "code": "chinese_semantic_group_warning",
                        "items": [
                            {
                                "subtitle_ids": ["S0004", "S0005"],
                                "mapping_valid": True,
                                "confidence": "high",
                                "confidence_score": 0.9,
                                "reason": "semantic_loss",
                                "rule_codes": ["semantic_loss"],
                            },
                            {
                                "subtitle_ids": ["S0009"],
                                "mapping_valid": True,
                                "confidence": "high",
                                "reason": "dangling_preposition",
                                "rule_codes": ["dangling_preposition"],
                            },
                            {
                                "subtitle_ids": ["S0006"],
                                "mapping_valid": False,
                                "confidence": "high",
                                "reason": "audit_mapping_invalid",
                            },
                            {
                                "index": 99,
                                "mapping_valid": True,
                                "confidence": "high",
                                "reason": "must_not_use_list_position",
                            },
                        ],
                    },
                ],
            },
        )
        _write_json(
            artifact_dir / "allocation-unresolved.json",
            [
                {
                    "allocation": {"S0007": "甲", "S0008": "乙"},
                    "issue_codes": ["number_allocation_mismatch"],
                    "reason": "number lost",
                }
            ],
        )
        _write_json(
            artifact_dir / "english-boundary-audit.json",
            {
                "records": [
                    {
                        "left_subtitle_id": "S0002",
                        "right_subtitle_id": "S0003",
                        "classification": "review",
                        "confidence": "high",
                        "reason": "subject_finite_verb_split",
                        "boundary": "analysis | confirms",
                    }
                ]
            },
        )
        _write_json(
            artifact_dir / "display-page-translations.json",
            {
                "status": "PASS",
                "render_plans": [
                    {
                        "parent_subtitle_id": "S0010",
                        "pages": [
                            {"english": "investors"},
                            {
                                "english": "blanching at the news",
                                "boundary_before": {
                                    "classification": "review",
                                    "confidence": "medium",
                                    "issue_codes": [
                                        "post_noun_participial_modifier_split"
                                    ],
                                },
                            },
                        ],
                    },
                    {
                        "parent_subtitle_id": "S0011",
                        "pages": [
                            {"english": "being cut off from advanced gear"},
                            {
                                "english": "is forcing better engineering",
                                "boundary_before": {
                                    "classification": "review",
                                    "confidence": "high",
                                    "pause_ms": 800,
                                    "issue_codes": ["subject_predicate_split"],
                                },
                            },
                        ],
                    }
                ],
            },
        )
        _write_json(
            artifact_dir / "subtitle-spans.json",
            [
                {
                    "subtitle_id": "S0002",
                    "word_start": 0,
                    "word_end": 4,
                    "original": "Exactly. And the expert analysis",
                },
                {
                    "subtitle_id": "S0003",
                    "word_start": 5,
                    "word_end": 8,
                    "original": "in the study confirms.",
                },
            ],
        )
        _write_json(
            artifact_dir / "word-ledger.json",
            {
                "words": [
                    {"surface": word, "start_ms": index * 100, "end_ms": (index + 1) * 100}
                    for index, word in enumerate(
                        ["Exactly.", "And", "the", "expert", "analysis", "in", "the", "study", "confirms."]
                    )
                ]
            },
        )

        marks = load_subtitle_review_marks(artifact_dir)

        assert ("BLOCKER", "structure", "both", "translation_id_missing") in _marks_for(marks, "S0001")
        assert (
            "REVIEW",
            "english_cut",
            "english",
            "english_boundary_audit",
        ) in _marks_for(marks, "S0003")
        assert (
            "REVIEW",
            "chinese_allocation",
            "chinese",
            "high_confidence_chinese_semantic_issue",
        ) in _marks_for(marks, "S0004")
        assert (
            "REVIEW",
            "chinese_allocation",
            "chinese",
            "allocation_unresolved",
        ) in _marks_for(marks, "S0007")
        assert (
            "REVIEW",
            "visual_page",
            "both",
            "high_confidence_visual_page_boundary",
        ) in _marks_for(marks, "S0010")
        assert (
            "REVIEW",
            "visual_page",
            "both",
            "high_confidence_visual_page_boundary",
        ) in _marks_for(marks, "S0011")
        assert review_marks_require_syntax_parser(artifact_dir) is False
        assert "S0002" not in marks
        assert "S0006" not in marks
        assert "S0099" not in marks
        assert (
            "REVIEW",
            "chinese_allocation",
            "chinese",
            "high_confidence_chinese_semantic_issue",
        ) in _marks_for(marks, "S0009")
        assert (
            "REVIEW",
            "chinese_allocation",
            "chinese",
            "high_confidence_chinese_semantic_issue",
        ) in _marks_for(marks, "S0005")
        assert (
            "REVIEW",
            "chinese_allocation",
            "chinese",
            "allocation_unresolved",
        ) in _marks_for(marks, "S0008")


def test_semantic_review_queue_is_loaded_as_id_bound_read_only_marks():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "semantic-review-queue.json",
            {
                "items": [
                    {
                        "code": "translation_fluency_review",
                        "title": "中文翻译腔复核",
                        "reason": "语义表达不自然",
                        "subtitle_ids": ["S0002"],
                    },
                    {"code": "bad", "subtitle_ids": ["not-an-id"]},
                ]
            },
        )
        marks = load_subtitle_review_marks(artifact_dir)
        assert _marks_for(marks, "S0002") == {
            (
                "REVIEW",
                "chinese_allocation",
                "chinese",
                "translation_fluency_review",
            )
        }
        assert "not-an-id" not in marks


def test_article_asr_review_marks_require_matching_frozen_ledger_hash():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "word-ledger.json",
            {"hash": "current-ledger", "words": []},
        )
        _write_json(
            artifact_dir / "article-asr-correction-review.json",
            {
                "word_ledger_hash": "current-ledger",
                "items": [
                    {
                        "candidate_id": "candidate-1",
                        "subtitle_ids": ["S0012"],
                        "original_text": "Felugia",
                        "suggested_text": "Fulujia",
                        "action": "review_only",
                    }
                ],
            },
        )

        marks = load_subtitle_review_marks(artifact_dir)

        assert (
            "REVIEW",
            "asr_correction",
            "english",
            "article_asr_correction_review",
        ) in _marks_for(marks, "S0012")
        assert "Felugia" in marks["S0012"][0].reason
        assert "Fulujia" in marks["S0012"][0].reason

        _write_json(
            artifact_dir / "word-ledger.json",
            {"hash": "different-ledger", "words": []},
        )
        assert "S0012" not in load_subtitle_review_marks(artifact_dir)


def test_display_page_blueprint_failure_marks_exact_frozen_subtitle_id():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "translation-structure-errors.json",
            [
                {
                    "code": "display_page_blueprint_invalid",
                    "message": "render_structural_overflow: hard_page_boundary",
                    "parent_subtitle_id": "S0201",
                    "display_page_id": "S0201.P01",
                    "items": [
                        {
                            "subtitle_id": "S0201",
                            "cue_index": 201,
                            "reason": "hard_page_boundary",
                        }
                    ],
                }
            ],
        )

        marks = load_subtitle_review_marks(artifact_dir)

        assert set(marks) == {"S0201"}
        assert (
            "BLOCKER",
            "visual_page",
            "english",
            "display_page_blueprint_invalid",
        ) in _marks_for(marks, "S0201")


def test_corrupt_structure_error_artifact_is_not_silently_treated_as_no_marks():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        (artifact_dir / "translation-structure-errors.json").write_text(
            "{not-json",
            encoding="utf-8",
        )

        try:
            load_subtitle_review_marks(artifact_dir)
        except ValueError as exc:
            assert "translation-structure-errors.json" in str(exc)
        else:
            raise AssertionError("corrupt blocker evidence must fail closed")


def test_table_marks_only_the_relevant_english_or_chinese_column():
    model = SubtitleTableModel(
        {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "English text.",
                "translated_subtitle": "中文文本。",
                "source_subtitle_ids": ["S0001"],
            }
        }
    )
    model.set_review_marks(
        {
            "S0001": [
                SubtitleReviewMark(
                    subtitle_id="S0001",
                    severity="REVIEW",
                    category="english_cut",
                    target="english",
                    code="syntax_boundary_audit",
                    reason="subject_finite_verb_split",
                )
            ]
        }
    )

    english = model.index(0, 2)
    chinese = model.index(0, 3)
    expected_english_color = "#24364a" if isDarkTheme() else "#eaf4ff"
    assert model.data(english, Qt.BackgroundRole).name() == expected_english_color
    assert model.data(chinese, Qt.BackgroundRole) is None
    assert "主语和谓语被切开" in model.data(english, Qt.ToolTipRole)
    assert "subject_finite_verb_split" not in model.data(english, Qt.ToolTipRole)


def test_parent_chinese_fallback_is_explicitly_marked_as_unconfirmed_preview():
    model = SubtitleTableModel(
        {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "A failed page plan.",
                "translated_subtitle": "父字幕中文",
                "manual_cue_id": "S0001",
                "display_page_id": "S0001.P01",
                "display_page_chinese_stale": True,
                "display_page_chinese_draft_kind": "parent_chinese_fallback",
                "display_page_chinese_confirmed": False,
            }
        }
    )

    model_index = model.index(0, 3)
    marks = model._marks_for_segment(model._data["1"])
    assert {
        (mark.severity, mark.category, mark.target, mark.code)
        for mark in marks
    } == {
        ("REVIEW", "manual_chinese_review", "chinese", "parent_chinese_fallback")
    }
    assert "不是逐页中文" in model.data(model_index, Qt.ToolTipRole)


def test_review_marks_include_final_timeline_fallback_for_matching_subtitle_id():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "validation-report.json", {"errors": []})
        _write_json(
            artifact_dir / "final-cue-timeline.json",
            {
                "records": [
                    {
                        "subtitle_id": "S0001",
                        "word_start": 0,
                        "word_end": 2,
                    },
                    {
                        "subtitle_id": "S0002",
                        "word_start": 3,
                        "word_end": 4,
                    },
                ]
            },
        )
        _write_json(
            artifact_dir / "word-ledger.json",
            {
                "words": [
                    {"alignment_source": "whisperx"},
                    {"alignment_source": "stable-ts-fallback"},
                    {"alignment_source": "whisperx"},
                    {"alignment_source": "whisperx"},
                    {"alignment_source": "stable-ts-fallback"},
                ]
            },
        )

        marks = load_subtitle_review_marks(artifact_dir)

        assert "S0001" not in marks
        assert (
            "REVIEW",
            "timeline_alignment",
            "both",
            "timeline_alignment_fallback",
        ) in _marks_for(marks, "S0002")


def test_table_model_reset_reloads_imported_bilingual_rows():
    model = SubtitleTableModel()
    resets = []
    model.modelReset.connect(lambda: resets.append(True))

    model.update_all(
        {
            "1": {
                "start_time": 120,
                "end_time": 5384,
                "original_subtitle": "English source.",
                "translated_subtitle": "中文译文。",
            }
        }
    )

    assert resets == [True]
    assert model.rowCount() == 1
    assert model.data(model.index(0, 2), Qt.DisplayRole) == "English source."
    assert model.data(model.index(0, 3), Qt.DisplayRole) == "中文译文。"


def test_table_model_incremental_update_changes_only_the_affected_rows():
    def row(parent_id: str, page_id: str, english: str):
        return {
            "start_time": 0,
            "end_time": 1000,
            "original_subtitle": english,
            "translated_subtitle": "中文",
            "manual_cue_id": parent_id,
            "display_page_id": page_id,
            "display_page_view": True,
            "word_start": 0,
            "word_end": 1,
        }

    model = SubtitleTableModel(
        {
            "1": row("S0001", "S0001.P01", "One."),
            "2": row("S0002", "S0002.P01", "Two."),
            "3": row("S0003", "S0003.P01", "Three."),
        }
    )
    resets = []
    changed = []
    inserted = []
    removed = []
    model.modelReset.connect(lambda: resets.append(True))
    model.dataChanged.connect(
        lambda top, bottom, _roles: changed.append((top.row(), bottom.row()))
    )
    model.rowsInserted.connect(
        lambda _parent, first, last: inserted.append((first, last))
    )
    model.rowsRemoved.connect(
        lambda _parent, first, last: removed.append((first, last))
    )

    same_count = copy.deepcopy(model._data)
    same_count["2"]["translated_subtitle"] = "第二条已修改"
    model.update_incremental(same_count)

    assert resets == []
    assert changed == [(1, 1)]
    assert model.data(model.index(1, 3), Qt.DisplayRole) == "第二条已修改"

    split = {
        "1": copy.deepcopy(same_count["1"]),
        "2": row("S0002", "S0002.P01", "Two first."),
        "3": row("S0002", "S0002.P02", "Two second."),
        "4": copy.deepcopy(same_count["3"]),
    }
    model.update_incremental(split)

    assert resets == []
    assert removed == [(1, 1)]
    assert inserted == [(1, 2)]
    assert model.rowCount() == 4
    assert model.data(model.index(3, 2), Qt.DisplayRole) == "Three."


def test_reapplying_identical_review_marks_does_not_repaint_the_table():
    model = SubtitleTableModel(
        {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "English.",
                "translated_subtitle": "中文。",
                "manual_cue_id": "S0001",
            }
        }
    )
    marks = {
        "S0001": [
            SubtitleReviewMark(
                subtitle_id="S0001",
                severity="REVIEW",
                category="english_cut",
                target="english",
                code="syntax_boundary_audit",
                reason="subject_finite_verb_split",
            )
        ]
    }
    changed = []
    model.dataChanged.connect(lambda *_args: changed.append(True))

    model.set_review_marks(marks)
    assert changed == [True]
    model.set_review_marks(marks)
    assert changed == [True]


def test_review_mark_payload_round_trip_preserves_global_subtitle_ids():
    original = {
        "S0118": [
            SubtitleReviewMark(
                subtitle_id="S0118",
                severity="REVIEW",
                category="english_cut",
                target="english",
                code="verified_cross_boundary_dependency",
                reason="跨边界依存断裂。",
            )
        ]
    }

    restored = review_marks_from_payload(review_marks_to_payload(original))

    assert restored == original


def test_manual_english_boundary_edit_marks_only_its_chinese_cell():
    model = SubtitleTableModel(
        {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "Edited English text.",
                "translated_subtitle": "待检查中文。",
                "manual_cue_id": "S0001",
                "chinese_review_required": True,
            }
        }
    )

    english = model.index(0, 2)
    chinese = model.index(0, 3)
    assert model.data(english, Qt.BackgroundRole) is None
    assert model.data(chinese, Qt.BackgroundRole) is not None
    assert "英文边界已人工调整" in model.data(chinese, Qt.ToolTipRole)


if __name__ == "__main__":
    test_review_marks_ignore_noisy_audits_and_keep_verified_id_markers_only()
    test_semantic_review_queue_is_loaded_as_id_bound_read_only_marks()
    test_display_page_blueprint_failure_marks_exact_frozen_subtitle_id()
    test_corrupt_structure_error_artifact_is_not_silently_treated_as_no_marks()
    test_table_marks_only_the_relevant_english_or_chinese_column()
    test_review_marks_include_final_timeline_fallback_for_matching_subtitle_id()
    test_table_model_reset_reloads_imported_bilingual_rows()
    test_table_model_incremental_update_changes_only_the_affected_rows()
    test_reapplying_identical_review_marks_does_not_repaint_the_table()
    test_review_mark_payload_round_trip_preserves_global_subtitle_ids()
    test_manual_english_boundary_edit_marks_only_its_chinese_cell()
    print("subtitle review mark tests passed")
