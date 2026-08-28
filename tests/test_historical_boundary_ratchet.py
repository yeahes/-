"""Prevent stable boundary legality from regressing on published runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT_DIR = (
    ROOT / "docs" / "audits" / "2026-08-24" / "external-claude-measurement"
)
if str(MEASUREMENT_DIR) not in sys.path:
    sys.path.insert(0, str(MEASUREMENT_DIR))

# The measurement module loads spaCy before importing the application modules.
# Keep that order so the bundled parser is initialized consistently on Windows.
import measure_stage2  # noqa: E402


def _historical_boundary_counts() -> tuple[int, int]:
    accepted = 0
    illegal = 0
    baseline = json.loads(
        (MEASUREMENT_DIR / "boundary_flip_measurement.json").read_text(
            encoding="utf-8"
        )
    )
    # The measurement is a frozen corpus snapshot.  Ignore newer work-dir
    # runs so a user's fresh sample cannot silently change this regression's
    # denominator.
    baseline_episode_names = set((baseline.get("per_episode") or {}).keys())
    for _episode_name, artifact_dir in measure_stage2.find_episodes():
        if _episode_name not in baseline_episode_names:
            continue
        word_ledger = json.loads(
            (artifact_dir / "word-ledger.json").read_text(encoding="utf-8")
        )
        timeline = json.loads(
            (artifact_dir / "final-cue-timeline.json").read_text(encoding="utf-8")
        )
        words = word_ledger.get("words") or []
        records = timeline.get("records") or []
        if not words or not records:
            continue

        editor = measure_stage2.build_editor(
            words,
            word_ledger.get("source_segments") or [],
        )
        for left_record, right_record in zip(records, records[1:]):
            if int(right_record["word_start"]) != int(left_record["word_end"]) + 1:
                continue
            left = editor._item_from_word_span(
                int(left_record["word_start"]), int(left_record["word_end"])
            )
            right = editor._item_from_word_span(
                int(right_record["word_start"]), int(right_record["word_end"])
            )
            if not left or not right:
                continue
            accepted += 1
            if editor._evaluate_item_pair_for_final_boundary(left, right).get(
                "hard_issues"
            ):
                illegal += 1
    return accepted, illegal


def test_published_boundary_illegality_is_a_non_increasing_ratchet():
    accepted, illegal = _historical_boundary_counts()

    assert accepted == 5_180
    assert illegal <= 452


if __name__ == "__main__":
    accepted, illegal = _historical_boundary_counts()
    assert accepted == 5_180
    assert illegal <= 452
    print(f"Historical boundary ratchet passed: {illegal}/{accepted}.")
