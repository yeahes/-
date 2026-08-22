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
    write_subtitle_review_ledger,
)
from app.core.subtitle_processor.review_evidence_identity import (
    build_review_source_identity,
)
from app.view.subtitle_interface import SubtitleTableModel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush
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
                    },
                    {
                        "left_subtitle_id": "S0012",
                        "right_subtitle_id": "S0013",
                        "classification": "review",
                        "confidence": "medium",
                        "reason": "leading_prepositional_fragment",
                        "boundary": "24 million | in revenue",
                    },
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
                    },
                    {
                        "parent_subtitle_id": "S0014",
                        "pages": [
                            {"english": "the motor, the housing,"},
                            {
                                "english": "and the shipping container",
                                "boundary_before": {
                                    "classification": "review",
                                    "confidence": "medium",
                                    "issue_codes": ["coordinated_constituent_split"],
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
        assert (
            "REVIEW",
            "english_cut",
            "english",
            "english_boundary_audit",
        ) in _marks_for(marks, "S0013")
        assert (
            "REVIEW",
            "visual_page",
            "both",
            "visual_page_boundary_review",
        ) in _marks_for(marks, "S0014")
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


def test_english_boundary_marks_drop_complete_sentence_false_positive():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "english-boundary-audit.json",
            {
                "records": [
                    {
                        "scope": "parent_cue",
                        "left_subtitle_id": "S0001",
                        "right_subtitle_id": "S0002",
                        "classification": "review",
                        "confidence": "high",
                        "reason": "right_orphaned_finite_predicate",
                        "rule_codes": ["right_orphaned_finite_predicate"],
                        "previous_english": "The point is clear.",
                        "current_english": "Think about a classroom.",
                    },
                    {
                        "scope": "parent_cue",
                        "left_subtitle_id": "S0003",
                        "right_subtitle_id": "S0004",
                        "classification": "review",
                        "confidence": "high",
                        "reason": "right_orphaned_finite_predicate",
                        "rule_codes": ["right_orphaned_finite_predicate"],
                        "previous_english": "If the main dial",
                        "current_english": "that everyone watches is fixed,",
                    },
                ]
            },
        )

        marks = load_subtitle_review_marks(artifact_dir)

        assert "S0002" not in marks
        assert (
            "REVIEW",
            "english_cut",
            "english",
            "english_boundary_audit",
        ) in _marks_for(marks, "S0004")


def test_semantic_review_queue_is_loaded_as_id_bound_read_only_marks():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        word_ledger = {"hash": "current-ledger", "words": []}
        subtitle_spans = [
            {
                "subtitle_id": "S0002",
                "original": "The current English sentence.",
                "word_start": 4,
                "word_end": 7,
            }
        ]
        _write_json(artifact_dir / "word-ledger.json", word_ledger)
        _write_json(artifact_dir / "subtitle-spans.json", subtitle_spans)
        _write_json(artifact_dir / "english-boundary-audit.json", {"records": []})
        _write_json(
            artifact_dir / "semantic-review-queue.json",
            {
                "schema_version": 2,
                "source_run": build_review_source_identity(
                    word_ledger,
                    subtitle_spans,
                ),
                "items": [
                    {
                        "code": "translation_fluency_review",
                        "title": "中文翻译腔复核",
                        "reason": "语义表达不自然",
                        "subtitle_ids": ["S0002"],
                        "context": [
                            {
                                "subtitle_id": "S0002",
                                "english": "The current English sentence.",
                                "word_start": 4,
                                "word_end": 7,
                            }
                        ],
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


def test_semantic_review_queue_rejects_same_id_from_different_frozen_run():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        current_ledger = {"hash": "current-ledger", "words": []}
        current_spans = [
            {
                "subtitle_id": "S0002",
                "original": "The current English sentence.",
                "word_start": 4,
                "word_end": 7,
            }
        ]
        stale_spans = [
            {
                "subtitle_id": "S0002",
                "original": "A stale English sentence.",
                "word_start": 10,
                "word_end": 14,
            }
        ]
        _write_json(artifact_dir / "word-ledger.json", current_ledger)
        _write_json(artifact_dir / "subtitle-spans.json", current_spans)
        _write_json(artifact_dir / "english-boundary-audit.json", {"records": []})
        _write_json(
            artifact_dir / "semantic-review-queue.json",
            {
                "schema_version": 2,
                "source_run": build_review_source_identity(
                    {"hash": "stale-ledger", "words": []},
                    stale_spans,
                ),
                "items": [
                    {
                        "code": "translation_fluency_review",
                        "subtitle_ids": ["S0002"],
                        "context": [
                            {
                                "subtitle_id": "S0002",
                                "english": "A stale English sentence.",
                                "word_start": 10,
                                "word_end": 14,
                            }
                        ],
                    }
                ],
            },
        )

        assert load_subtitle_review_marks(artifact_dir) == {}


def test_semantic_review_queue_rejects_unbound_legacy_payload():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "word-ledger.json",
            {"hash": "current-ledger", "words": []},
        )
        _write_json(
            artifact_dir / "subtitle-spans.json",
            [
                {
                    "subtitle_id": "S0002",
                    "original": "The current English sentence.",
                    "word_start": 4,
                    "word_end": 7,
                }
            ],
        )
        _write_json(artifact_dir / "english-boundary-audit.json", {"records": []})
        _write_json(
            artifact_dir / "semantic-review-queue.json",
            {
                "schema_version": 1,
                "items": [
                    {
                        "code": "translation_fluency_review",
                        "subtitle_ids": ["S0002"],
                    }
                ],
            },
        )

        assert load_subtitle_review_marks(artifact_dir) == {}


def test_article_asr_review_marks_require_matching_frozen_ledger_hash():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "word-ledger.json",
            {"hash": "current-ledger", "words": []},
        )
        _write_json(artifact_dir / "english-boundary-audit.json", {"records": []})
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


def test_mixed_display_failures_keep_layout_and_missing_chinese_separate():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "translation-structure-errors.json",
            [
                {
                    "code": "display_page_blueprint_invalid",
                    "message": "One or more parents require manual display pagination.",
                    "items": [
                        {
                            "subtitle_id": "S0201",
                            "reason": "no_complete_normal_font_page_partition",
                        },
                        {
                            "subtitle_id": "S0202",
                            "display_page_id": "S0202.P01",
                            "reason": "page_translation_id_missing",
                        },
                    ],
                    "subtitle_ids": ["S0201", "S0202"],
                }
            ],
        )

        marks = load_subtitle_review_marks(artifact_dir)

        assert (
            "BLOCKER",
            "visual_page",
            "english",
            "display_page_blueprint_invalid",
        ) in _marks_for(marks, "S0201")
        assert (
            "BLOCKER",
            "chinese_allocation",
            "chinese",
            "page_translation_id_missing",
        ) in _marks_for(marks, "S0202")
        assert "display_page_blueprint_invalid" not in {
            mark.code for mark in marks["S0202"]
        }


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


def test_table_marks_use_one_fixed_width_band_and_keep_target_in_tooltip():
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
    expected_english_color = "#3a3420" if isDarkTheme() else "#fff4cc"
    assert model.data(english, Qt.BackgroundRole).color().name() == expected_english_color
    assert model.data(chinese, Qt.BackgroundRole).color().name() == expected_english_color
    assert "主语和谓语被切开" in model.data(english, Qt.ToolTipRole)
    assert "英文 / 英文切分复查" in model.data(chinese, Qt.ToolTipRole)
    assert "subject_finite_verb_split" not in model.data(english, Qt.ToolTipRole)


def test_table_review_colors_encode_severity_instead_of_issue_category():
    model = SubtitleTableModel(
        {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "Review me.",
                "translated_subtitle": "请复核。",
                "source_subtitle_ids": ["S0001"],
            },
            "2": {
                "start_time": 1000,
                "end_time": 2000,
                "original_subtitle": "Blocked.",
                "translated_subtitle": "已阻断。",
                "source_subtitle_ids": ["S0002"],
            },
        }
    )
    model.set_review_marks(
        {
            "S0001": [
                SubtitleReviewMark(
                    subtitle_id="S0001",
                    severity="REVIEW",
                    category="chinese_fluency",
                    target="chinese",
                    code="model_fluency",
                    reason="中文不够通顺。",
                )
            ],
            "S0002": [
                SubtitleReviewMark(
                    subtitle_id="S0002",
                    severity="BLOCKER",
                    category="visual_page",
                    target="english",
                    code="display_page_unavailable",
                    reason="没有可用分页。",
                )
            ],
        }
    )

    review_color = "#3a3420" if isDarkTheme() else "#fff4cc"
    blocker_color = "#3d2424" if isDarkTheme() else "#ffe2e2"
    review_brush = model.data(model.index(0, 3), Qt.BackgroundRole)
    blocker_brush = model.data(model.index(1, 2), Qt.BackgroundRole)
    assert isinstance(review_brush, QBrush)
    assert isinstance(blocker_brush, QBrush)
    assert review_brush.color().name() == review_color
    assert blocker_brush.color().name() == blocker_color


def test_unallocated_page_chinese_uses_display_only_placeholder():
    model = SubtitleTableModel(
        {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "A page awaiting Chinese.",
                "translated_subtitle": "",
                "manual_cue_id": "S0001",
                "display_page_id": "S0001.P02",
                "display_page_view": True,
                "display_page_chinese_pending": True,
                "display_page_chinese_confirmed": False,
                "chinese_review_required": True,
            }
        }
    )

    chinese = model.index(0, 3)
    assert model.data(chinese, Qt.DisplayRole) == "待分配"
    assert model.data(chinese, Qt.EditRole) == ""
    foreground = model.data(chinese, Qt.ForegroundRole)
    assert isinstance(foreground, QBrush)
    assert foreground.color().isValid()
    assert "没有丢失" in model.data(chinese, Qt.ToolTipRole)
    assert model._data["1"]["translated_subtitle"] == ""


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
                    {"alignment_source": "whisperx", "start_ms": 0, "end_ms": 100},
                    {"alignment_source": "stable-ts-fallback", "start_ms": 100, "end_ms": 200},
                    {"alignment_source": "whisperx", "start_ms": 200, "end_ms": 300},
                    {"alignment_source": "whisperx", "start_ms": 300, "end_ms": 400},
                    {"alignment_source": "stable-ts-fallback", "start_ms": 400, "end_ms": 401},
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


def test_review_ledger_freezes_high_value_tasks_and_merges_shared_subtitle_ids():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(
            artifact_dir / "word-ledger.json",
            {"hash": "frozen-word-ledger", "words": []},
        )
        _write_json(
            artifact_dir / "validation-report.json",
            {
                "warnings": [
                    {
                        "code": "reading_speed_warning",
                        "items": [
                            {
                                "subtitle_id": "S0001",
                                "zh_chars": 18,
                                "reason": "中文字幕阅读速度 10.0 字/秒",
                            }
                        ],
                    },
                    {
                        "code": "translationese",
                        "items": [
                            {
                                "subtitle_id": "S0002",
                                "reason": "中文表达疑似直译",
                            }
                        ],
                    },
                    {
                        "code": "duplicate_chinese",
                        "items": [
                            {
                                "subtitle_ids": ["S0003", "S0004"],
                                "reason": "相邻中文字幕高度相似",
                            }
                        ],
                    },
                    {
                        "code": "asr_suspicious",
                        "items": [
                            {
                                "subtitle_id": "S0005",
                                "confidence": "high",
                                "rule_code": "asr_semantic_nonsense",
                                "reason": "英文语义不成立",
                            },
                            {
                                "subtitle_id": "S0006",
                                "confidence": "medium",
                                "rule_code": "asr_capitalized_variant",
                                "reason": "Vietnam 与 Vietnamese 可能相关",
                            },
                        ],
                    },
                ]
            },
        )
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "english-boundary-audit.json", {"records": []})

        ledger = write_subtitle_review_ledger(artifact_dir)

        assert ledger["schema_version"] == 2
        assert ledger["source_word_ledger_hash"] == "frozen-word-ledger"
        assert ledger["source_frozen_span_hash"]
        assert ledger["summary"] == {
            "task_count": 4,
            "blocker_count": 0,
            "review_count": 4,
            "subtitle_count": 5,
        }
        duplicate_task = next(
            item
            for item in ledger["items"]
            if item["code"] == "adjacent_chinese_duplicate_review"
        )
        assert duplicate_task["subtitle_ids"] == ["S0003", "S0004"]
        assert len(duplicate_task["task_id"]) == 13
        assert "S0006" not in load_subtitle_review_marks(artifact_dir)


def test_legacy_text_review_detects_format_anomalies_by_frozen_id():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "english-boundary-audit.json", {"records": []})
        _write_json(
            artifact_dir / "subtitle-spans.json",
            [
                {"subtitle_id": "S0007", "original": "It began in the 2000 s."},
                {"subtitle_id": "S0008", "original": "The 21 st Century changed it."},
                {"subtitle_id": "S0009", "original": "G K. G. K. Chesterton wrote it."},
            ],
        )

        marks = load_subtitle_review_marks(artifact_dir)

        assert "asr_split_decade_suffix" in {mark.code for mark in marks["S0007"]}
        assert "asr_split_ordinal_suffix" in {mark.code for mark in marks["S0008"]}
        assert "asr_repeated_initials" in {mark.code for mark in marks["S0009"]}


def test_table_deduplicates_one_shared_review_task_across_parent_ids():
    model = SubtitleTableModel(
        {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "First.",
                "translated_subtitle": "重复中文。",
                "source_subtitle_ids": ["S0001", "S0002"],
            }
        }
    )
    shared = {
        subtitle_id: [
            SubtitleReviewMark(
                subtitle_id=subtitle_id,
                severity="REVIEW",
                category="chinese_coherence",
                target="chinese",
                code="adjacent_chinese_duplicate_review",
                reason="相邻中文字幕高度相似。",
                task_id="Rshared-task",
            )
        ]
        for subtitle_id in ("S0001", "S0002")
    }

    model.set_review_marks(shared)

    marks = model._marks_for_segment(model._data["1"])
    assert len(marks) == 1
    assert marks[0].task_id == "Rshared-task"


def test_model_translation_audit_projects_only_fixed_id_review_marks():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "english-boundary-audit.json", {"records": []})
        _write_json(
            artifact_dir / "translation-quality-audit.json",
            {
                "status": "PASS",
                "items": [
                    {
                        "subtitle_ids": ["S0074", "S0075"],
                        "code": "adjacent_coherence",
                        "reason": "中文跨条语序不自然。",
                    },
                    {
                        "subtitle_ids": ["bad-id"],
                        "code": "semantic_loss",
                        "reason": "must be ignored",
                    },
                ],
            },
        )

        marks = load_subtitle_review_marks(artifact_dir)

        assert set(marks) == {"S0074", "S0075"}
        assert {mark.task_id for mark in marks["S0074"]} == {
            marks["S0075"][0].task_id
        }
        assert marks["S0074"][0].category == "chinese_coherence"
        assert marks["S0074"][0].code == "model_adjacent_coherence"


def test_complete_model_audit_supersedes_noisy_local_chinese_heuristics():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "english-boundary-audit.json", {"records": []})
        _write_json(
            artifact_dir / "validation-report.json",
            {
                "warnings": [
                    {
                        "code": "chinese_semantic_group_warning",
                        "items": [
                            {
                                "subtitle_ids": ["S0001"],
                                "mapping_valid": True,
                                "confidence": "high",
                                "reason": "heuristic false positive",
                            }
                        ],
                    }
                ]
            },
        )
        _write_json(
            artifact_dir / "translation-quality-audit.json",
            {
                "status": "PASS",
                "source_subtitle_count": 1,
                "audited_subtitle_count": 1,
                "items": [],
            },
        )

        assert load_subtitle_review_marks(artifact_dir) == {}


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
    assert model.data(english, Qt.BackgroundRole) is not None
    assert model.data(chinese, Qt.BackgroundRole) is not None
    assert "英文边界已人工调整" in model.data(chinese, Qt.ToolTipRole)


if __name__ == "__main__":
    test_review_marks_ignore_noisy_audits_and_keep_verified_id_markers_only()
    test_semantic_review_queue_is_loaded_as_id_bound_read_only_marks()
    test_display_page_blueprint_failure_marks_exact_frozen_subtitle_id()
    test_corrupt_structure_error_artifact_is_not_silently_treated_as_no_marks()
    test_table_marks_use_one_fixed_width_band_and_keep_target_in_tooltip()
    test_table_review_colors_encode_severity_instead_of_issue_category()
    test_unallocated_page_chinese_uses_display_only_placeholder()
    test_review_marks_include_final_timeline_fallback_for_matching_subtitle_id()
    test_table_model_reset_reloads_imported_bilingual_rows()
    test_table_model_incremental_update_changes_only_the_affected_rows()
    test_reapplying_identical_review_marks_does_not_repaint_the_table()
    test_review_mark_payload_round_trip_preserves_global_subtitle_ids()
    test_review_ledger_freezes_high_value_tasks_and_merges_shared_subtitle_ids()
    test_legacy_text_review_detects_format_anomalies_by_frozen_id()
    test_table_deduplicates_one_shared_review_task_across_parent_ids()
    test_model_translation_audit_projects_only_fixed_id_review_marks()
    test_complete_model_audit_supersedes_noisy_local_chinese_heuristics()
    test_manual_english_boundary_edit_marks_only_its_chinese_cell()
    print("subtitle review mark tests passed")
