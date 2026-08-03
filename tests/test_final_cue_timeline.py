"""Regression tests for the frozen-ledger final subtitle timeline."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.subtitle_processor.final_cue_timeline import (
    derive_final_cue_timeline,
    final_cue_timeline_artifact,
    reconcile_frozen_word_ledger,
)


def _words(*times):
    return [
        {
            "word_id": index,
            "surface": f"word-{index}",
            "start_ms": start,
            "end_ms": end,
            "alignment_source": "whisperx" if index != 2 else "stable-ts-fallback",
        }
        for index, (start, end) in enumerate(times)
    ]


def _cues():
    return [
        {"subtitle_id": "S0001", "word_start": 0, "word_end": 1},
        {"subtitle_id": "S0002", "word_start": 2, "word_end": 3},
    ]


def test_final_timeline_cue_covers_its_last_frozen_word():
    words = _words((553180, 553360), (553370, 555720))
    timeline = derive_final_cue_timeline(
        [{"subtitle_id": "S0001", "word_start": 0, "word_end": 1}],
        words,
        expected_subtitle_ids=["S0001"],
        lead_in_ms=40,
        tail_padding_ms=260,
    )

    record = timeline["records"][0]
    assert record["end_ms"] >= 555720
    assert record["end_ms"] == 555980
    assert timeline["validation"]["status"] == "PASS"


def test_final_timeline_cue_covers_its_first_frozen_word():
    words = _words((189080, 189220), (189230, 189580))
    timeline = derive_final_cue_timeline(
        [{"subtitle_id": "S0001", "word_start": 0, "word_end": 1}],
        words,
        expected_subtitle_ids=["S0001"],
        lead_in_ms=40,
        tail_padding_ms=260,
    )

    record = timeline["records"][0]
    assert record["start_ms"] <= 189080
    assert record["start_ms"] == 189040
    assert timeline["validation"]["status"] == "PASS"


def test_padding_overlap_is_reconciled_without_cutting_either_word_envelope():
    words = _words((1000, 1200), (1210, 1400), (1410, 1600), (1610, 1800))
    timeline = derive_final_cue_timeline(
        _cues(),
        words,
        expected_subtitle_ids=["S0001", "S0002"],
        lead_in_ms=80,
        tail_padding_ms=260,
    )

    left, right = timeline["records"]
    assert left["end_ms"] == right["start_ms"]
    assert left["end_ms"] >= left["word_envelope_end_ms"]
    assert right["start_ms"] <= right["word_envelope_start_ms"]
    assert timeline["validation"]["status"] == "PASS"


def test_overlapping_word_envelopes_fail_instead_of_truncating_a_cue():
    words = _words((1000, 1500), (1400, 1800))
    timeline = derive_final_cue_timeline(
        [
            {"subtitle_id": "S0001", "word_start": 0, "word_end": 0},
            {"subtitle_id": "S0002", "word_start": 1, "word_end": 1},
        ],
        words,
        expected_subtitle_ids=["S0001", "S0002"],
        lead_in_ms=40,
        tail_padding_ms=260,
    )

    codes = {item["code"] for item in timeline["validation"]["errors"]}
    assert "final_timeline_word_envelope_overlap" in codes
    assert timeline["validation"]["status"] == "ERROR"


def test_adjacent_word_overlap_is_reconciled_in_the_ledger_before_cue_building():
    reconciliation = reconcile_frozen_word_ledger(
        _words((553220, 555720), (555600, 556100))
    )

    assert reconciliation["errors"] == []
    assert reconciliation["reconciliations"][0]["new_boundary_ms"] == 555660
    normalized_words = reconciliation["words"]
    assert normalized_words[0]["end_ms"] == 555660
    assert normalized_words[1]["start_ms"] == 555660

    timeline = derive_final_cue_timeline(
        [
            {"subtitle_id": "S0001", "word_start": 0, "word_end": 0},
            {"subtitle_id": "S0002", "word_start": 1, "word_end": 1},
        ],
        normalized_words,
        expected_subtitle_ids=["S0001", "S0002"],
        lead_in_ms=40,
        tail_padding_ms=260,
    )
    assert timeline["validation"]["status"] == "PASS"


def test_missing_or_synthetic_subtitle_id_blocks_final_timeline():
    words = _words((1000, 1200), (1300, 1500))
    artifact = final_cue_timeline_artifact(
        [
            {
                "subtitle_id": "S0000",
                "word_start": 0,
                "word_end": 1,
                "word_envelope_start_ms": 1000,
                "word_envelope_end_ms": 1500,
                "start_ms": 960,
                "end_ms": 1760,
            }
        ],
        words,
        expected_subtitle_ids=["S0001"],
    )

    codes = {item["code"] for item in artifact["validation"]["errors"]}
    assert "final_timeline_subtitle_id_invalid" in codes
    assert "final_timeline_subtitle_id_missing" in codes
    assert "final_timeline_subtitle_id_unknown" in codes


def test_artifact_rejects_final_cue_that_ends_before_its_word_envelope():
    words = _words((1000, 1200), (1210, 1600))
    artifact = final_cue_timeline_artifact(
        [
            {
                "subtitle_id": "S0001",
                "word_start": 0,
                "word_end": 1,
                "word_envelope_start_ms": 1000,
                "word_envelope_end_ms": 1600,
                "start_ms": 960,
                "end_ms": 1480,
            }
        ],
        words,
        expected_subtitle_ids=["S0001"],
    )

    codes = {item["code"] for item in artifact["validation"]["errors"]}
    assert "final_timeline_word_envelope_uncovered" in codes


def test_artifact_rejects_cues_reordered_from_frozen_subtitle_ids():
    words = _words((1000, 1200), (1210, 1400), (1410, 1600), (1610, 1800))
    artifact = final_cue_timeline_artifact(
        [
            {
                "subtitle_id": "S0002",
                "word_start": 0,
                "word_end": 1,
                "word_envelope_start_ms": 1000,
                "word_envelope_end_ms": 1400,
                "start_ms": 960,
                "end_ms": 1500,
            },
            {
                "subtitle_id": "S0001",
                "word_start": 2,
                "word_end": 3,
                "word_envelope_start_ms": 1410,
                "word_envelope_end_ms": 1800,
                "start_ms": 1410,
                "end_ms": 2060,
            },
        ],
        words,
        expected_subtitle_ids=["S0001", "S0002"],
    )

    codes = {item["code"] for item in artifact["validation"]["errors"]}
    assert "final_timeline_subtitle_order_mismatch" in codes
    assert artifact["validation"]["status"] == "ERROR"


if __name__ == "__main__":
    test_final_timeline_cue_covers_its_last_frozen_word()
    test_final_timeline_cue_covers_its_first_frozen_word()
    test_padding_overlap_is_reconciled_without_cutting_either_word_envelope()
    test_overlapping_word_envelopes_fail_instead_of_truncating_a_cue()
    test_adjacent_word_overlap_is_reconciled_in_the_ledger_before_cue_building()
    test_missing_or_synthetic_subtitle_id_blocks_final_timeline()
    test_artifact_rejects_final_cue_that_ends_before_its_word_envelope()
    test_artifact_rejects_cues_reordered_from_frozen_subtitle_ids()
    print("final cue timeline tests passed")
