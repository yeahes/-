import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.subtitle_processor.subtitle_review_marks import (
    SubtitleReviewMark,
    _load_syntax_nlp,
    load_subtitle_review_marks,
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
                                "confidence_score": 0.72,
                                "reason": "group_allocation_information_omission",
                                "rule_codes": ["group_allocation_information_omission"],
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
        if _load_syntax_nlp() is not None:
            assert (
                "REVIEW",
                "english_cut",
                "english",
                "verified_cross_boundary_dependency",
            ) in _marks_for(marks, "S0002")
            assert (
                "REVIEW",
                "english_cut",
                "english",
                "verified_cross_boundary_dependency",
            ) in _marks_for(marks, "S0003")
        assert "S0006" not in marks
        assert "S0099" not in marks
        assert "S0009" not in marks
        assert "S0004" not in marks
        assert "S0005" not in marks
        assert "S0007" not in marks
        assert "S0008" not in marks


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
    assert "subject_finite_verb_split" in model.data(english, Qt.ToolTipRole)


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
                        "word_alignment_sources": ["whisperx"],
                    },
                    {
                        "subtitle_id": "S0002",
                        "word_alignment_sources": [
                            "stable-ts-fallback+final-ledger-boundary-reconciled",
                            "whisperx",
                        ],
                    },
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
    test_table_marks_only_the_relevant_english_or_chinese_column()
    test_review_marks_include_final_timeline_fallback_for_matching_subtitle_id()
    test_table_model_reset_reloads_imported_bilingual_rows()
    test_review_mark_payload_round_trip_preserves_global_subtitle_ids()
    test_manual_english_boundary_edit_marks_only_its_chinese_cell()
    print("subtitle review mark tests passed")
