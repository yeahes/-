import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.probe_alignment_emission import (
    audit_rows,
    project_chinese_to_pages,
    validate_emission,
)


def _row():
    return {
        "run_id": "synthetic",
        "source_kind": "pass",
        "parent_subtitle_id": "S9001",
        "english": "The core argument is clear.",
        "parent_chinese": "核心论点很清楚。",
        "word_start": 10,
        "word_end": 14,
        "english_words": ["The", "core", "argument", "is", "clear."],
        "pages": [
            {
                "display_page_id": "S9001.P01",
                "word_start": 10,
                "word_end": 12,
                "english": "The core argument",
                "zh": "核心论点",
            },
            {
                "display_page_id": "S9001.P02",
                "word_start": 13,
                "word_end": 14,
                "english": "is clear.",
                "zh": "很清楚。",
            },
        ],
    }


def test_validate_emission_requires_exact_concat_and_legal_ranges():
    row = _row()
    good = {
        "phrases": [
            {"chinese": "核心论点", "word_start": 0, "word_end": 2},
            {"chinese": "很清楚。", "word_start": 3, "word_end": 4},
        ]
    }
    assert validate_emission(good, row)["ok"] is True

    wrong_text = {
        "phrases": [
            {"chinese": "核心论点", "word_start": 0, "word_end": 2},
            {"chinese": "清楚。", "word_start": 3, "word_end": 4},
        ]
    }
    assert validate_emission(wrong_text, row)["failure_mode"] == "chinese_concat_mismatch"

    wrong_range = {
        "phrases": [{"chinese": "核心论点很清楚。", "word_start": 0, "word_end": 9}]
    }
    assert validate_emission(wrong_range, row)["failure_mode"] == "range_out_of_bounds"


def test_projection_uses_existing_page_ranges_without_rewriting_chinese():
    row = _row()
    validation = validate_emission(
        {
            "phrases": [
                {"chinese": "核心论点", "word_start": 0, "word_end": 2},
                {"chinese": "很清楚。", "word_start": 3, "word_end": 4},
            ]
        },
        row,
    )
    projected = project_chinese_to_pages(row, validation)
    assert [page["chinese"] for page in projected["pages"]] == ["核心论点", "很清楚。"]


def test_audit_retries_one_failed_response_and_keeps_failure_classification():
    row = _row()
    calls = {"count": 0}

    def completion(_request):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary provider failure")
        return {
            "phrases": [
                {"chinese": "核心论点", "word_start": 0, "word_end": 2},
                {"chinese": "很清楚。", "word_start": 3, "word_end": 4},
            ]
        }

    result = audit_rows([row], completion, max_retries=1)
    assert calls["count"] == 2
    assert result["retry_count"] == 1
    assert result["raw_compliant_count"] == 0
    assert result["compliant_after_retry_count"] == 1
    assert result["failures"] == []


def test_audit_rejects_permanent_invalid_alignment_after_retry():
    row = _row()

    def completion(_request):
        return {"phrases": [{"chinese": "核心论点", "word_start": 0, "word_end": 99}]}

    result = audit_rows([row], completion, max_retries=1)
    assert result["retry_count"] == 1
    assert result["compliant_after_retry_count"] == 0
    assert result["failure_modes"] == {"range_out_of_bounds": 1}
