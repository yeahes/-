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


def test_tail_cut_caps_only_final_display_padding_after_word_envelope():
    words = _words((1000, 1200), (1210, 1400))
    timeline = derive_final_cue_timeline(
        [{"subtitle_id": "S0001", "word_start": 0, "word_end": 1}],
        words,
        expected_subtitle_ids=["S0001"],
        lead_in_ms=40,
        tail_padding_ms=260,
        display_end_cap_ms=1450,
    )

    record = timeline["records"][0]
    assert record["word_envelope_end_ms"] == 1400
    assert record["end_ms"] == 1450
    assert timeline["validation"]["status"] == "PASS"


def test_short_parent_gap_is_chained_at_the_original_three_quarter_boundary():
    words = _words((1000, 2000), (2740, 3500))
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

    left, right = timeline["records"]
    assert left["end_ms"] == right["start_ms"] == 2555
    assert right["word_envelope_start_ms"] - right["start_ms"] == 185
    assert timeline["validation"]["status"] == "PASS"
    assert any(
        item["code"] == "final_timeline_short_gap_chained"
        and item["word_gap_ms"] == 740
        and item["old_display_gap_ms"] == 440
        for item in timeline["boundary_reconciliations"]
    )


def test_short_parent_gap_caps_the_next_cue_lead_in():
    words = _words((1000, 2000), (2960, 3800))
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

    left, right = timeline["records"]
    assert left["end_ms"] == right["start_ms"] == 2760
    assert right["word_envelope_start_ms"] - right["start_ms"] == 200
    assert timeline["validation"]["status"] == "PASS"


def test_one_second_parent_pause_is_not_chained():
    words = _words((1000, 2000), (3000, 3800))
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

    left, right = timeline["records"]
    assert left["end_ms"] == 2260
    assert right["start_ms"] == 2960
    assert right["start_ms"] - left["end_ms"] == 700
    assert timeline["validation"]["status"] == "PASS"
    assert not any(
        item["code"] == "final_timeline_short_gap_chained"
        for item in timeline["boundary_reconciliations"]
    )


def test_existing_timeline_artifact_preserves_boundary_reconciliation_evidence():
    words = _words((1000, 2000), (2740, 3500))
    evidence = [
        {
            "code": "final_timeline_short_gap_chained",
            "left_subtitle_id": "S0001",
            "right_subtitle_id": "S0002",
            "new_boundary_ms": 2555,
        }
    ]
    artifact = final_cue_timeline_artifact(
        [
            {
                "subtitle_id": "S0001",
                "word_start": 0,
                "word_end": 0,
                "word_envelope_start_ms": 1000,
                "word_envelope_end_ms": 2000,
                "start_ms": 960,
                "end_ms": 2555,
            },
            {
                "subtitle_id": "S0002",
                "word_start": 1,
                "word_end": 1,
                "word_envelope_start_ms": 2740,
                "word_envelope_end_ms": 3500,
                "start_ms": 2555,
                "end_ms": 3760,
            },
        ],
        words,
        expected_subtitle_ids=["S0001", "S0002"],
        boundary_reconciliations=evidence,
    )

    assert artifact["validation"]["status"] == "PASS"
    assert artifact["boundary_reconciliations"] == evidence
    assert artifact["boundary_reconciliations"] is not evidence


def test_short_response_uses_available_silence_for_target_display_duration():
    words = _words(
        (400000, 405430),
        (405580, 405700),
        (406240, 408000),
    )
    timeline = derive_final_cue_timeline(
        [
            {"subtitle_id": "S0001", "word_start": 0, "word_end": 0},
            {"subtitle_id": "S0002", "word_start": 1, "word_end": 1},
            {"subtitle_id": "S0003", "word_start": 2, "word_end": 2},
        ],
        words,
        expected_subtitle_ids=["S0001", "S0002", "S0003"],
        lead_in_ms=40,
        tail_padding_ms=260,
    )

    short = timeline["records"][1]
    assert short["end_ms"] - short["start_ms"] >= 700
    assert short["start_ms"] <= 405580
    assert short["end_ms"] >= 405700
    assert timeline["validation"]["status"] == "PASS"
    assert [(word["start_ms"], word["end_ms"]) for word in words] == [
        (400000, 405430),
        (405580, 405700),
        (406240, 408000),
    ]


def test_short_response_keeps_best_safe_duration_when_target_is_impossible():
    words = _words(
        (800000, 802380),
        (802380, 802500),
        (802380, 802500),
        (802740, 805000),
    )
    timeline = derive_final_cue_timeline(
        [
            {"subtitle_id": "S0001", "word_start": 0, "word_end": 0},
            {"subtitle_id": "S0002", "word_start": 1, "word_end": 2},
            {"subtitle_id": "S0003", "word_start": 3, "word_end": 3},
        ],
        words,
        expected_subtitle_ids=["S0001", "S0002", "S0003"],
        lead_in_ms=40,
        tail_padding_ms=260,
    )

    short = timeline["records"][1]
    assert 150 <= short["end_ms"] - short["start_ms"] < 700
    assert short["start_ms"] <= 802380
    assert short["end_ms"] <= 802740
    assert timeline["validation"]["status"] == "PASS"


def test_short_response_without_hard_minimum_room_blocks_final_timeline():
    words = _words((0, 1000), (1000, 1100), (1100, 2000))
    timeline = derive_final_cue_timeline(
        [
            {"subtitle_id": "S0001", "word_start": 0, "word_end": 0},
            {"subtitle_id": "S0002", "word_start": 1, "word_end": 1},
            {"subtitle_id": "S0003", "word_start": 2, "word_end": 2},
        ],
        words,
        expected_subtitle_ids=["S0001", "S0002", "S0003"],
        lead_in_ms=40,
        tail_padding_ms=260,
    )

    codes = {item["code"] for item in timeline["validation"]["errors"]}
    assert "final_timeline_display_duration_invalid" in codes
    assert timeline["validation"]["status"] == "ERROR"


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


def test_artifact_rejects_ledger_words_outside_the_first_and_last_cue():
    words = _words((1000, 1200), (1210, 1400), (1410, 1600), (1610, 1800))
    artifact = final_cue_timeline_artifact(
        [
            {
                "subtitle_id": "S0001",
                "word_start": 1,
                "word_end": 2,
                "word_envelope_start_ms": 1210,
                "word_envelope_end_ms": 1600,
                "start_ms": 1200,
                "end_ms": 1610,
            }
        ],
        words,
        expected_subtitle_ids=["S0001"],
    )

    coverage_errors = [
        item
        for item in artifact["validation"]["errors"]
        if item["code"] == "final_timeline_word_coverage_incomplete"
    ]
    assert artifact["validation"]["status"] == "ERROR"
    assert coverage_errors == [
        {
            "code": "final_timeline_word_coverage_incomplete",
            "missing_word_ids": [0, 3],
            "duplicate_word_ids": [],
            "expected_word_range": [0, 3],
            "covered_word_range": [1, 2],
        }
    ]


def test_reconcile_rejects_compressed_multiword_cluster_before_boundary_repair():
    words = _words(
        (1077980, 1078100),
        (1077980, 1078100),
        (1077980, 1078100),
        (1077980, 1078100),
        (1077980, 1078100),
        (1077980, 1078100),
    )

    result = reconcile_frozen_word_ledger(words)

    assert result["words"] == []
    assert result["reconciliations"] == []
    assert result["errors"][0]["code"] == "final_timeline_word_timing_density_invalid"


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
    test_reconcile_rejects_compressed_multiword_cluster_before_boundary_repair()
    test_final_timeline_cue_covers_its_last_frozen_word()
    test_final_timeline_cue_covers_its_first_frozen_word()
    test_padding_overlap_is_reconciled_without_cutting_either_word_envelope()
    test_short_parent_gap_is_chained_at_the_original_three_quarter_boundary()
    test_short_parent_gap_caps_the_next_cue_lead_in()
    test_one_second_parent_pause_is_not_chained()
    test_existing_timeline_artifact_preserves_boundary_reconciliation_evidence()
    test_short_response_uses_available_silence_for_target_display_duration()
    test_short_response_keeps_best_safe_duration_when_target_is_impossible()
    test_short_response_without_hard_minimum_room_blocks_final_timeline()
    test_overlapping_word_envelopes_fail_instead_of_truncating_a_cue()
    test_adjacent_word_overlap_is_reconciled_in_the_ledger_before_cue_building()
    test_missing_or_synthetic_subtitle_id_blocks_final_timeline()
    test_artifact_rejects_final_cue_that_ends_before_its_word_envelope()
    test_artifact_rejects_cues_reordered_from_frozen_subtitle_ids()
    print("final cue timeline tests passed")
