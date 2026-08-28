from __future__ import annotations

import json
from pathlib import Path

from scripts.measure_g6_manual_diff import measure


def test_g6_uses_current_actions_unique_queue_parents_and_single_word_diff(tmp_path: Path) -> None:
    source_dir = tmp_path / "artifacts"
    source_dir.mkdir()
    (source_dir / "subtitle-spans.json").write_text(
        json.dumps(
            [
                {"subtitle_id": "S0001", "original": "alpha beta"},
                {"subtitle_id": "S0002", "original": "gamma delta"},
                {"subtitle_id": "S0003", "original": "tail"},
                {"subtitle_id": "S0004", "original": "one wrong word"},
                {"subtitle_id": "S0005", "original": "old two word phrase"},
            ]
        ),
        encoding="utf-8",
    )
    manual_path = tmp_path / "manual-edits.json"
    manual_path.write_text(
        json.dumps(
            {
                "source_artifact_dir": str(source_dir),
                "source_word_ledger_hash": "same",
                "cues": [
                    {"cue_id": "S0001", "original_subtitle": "alpha beta"},
                    {"cue_id": "S0002", "original_subtitle": "gamma delta"},
                    {"cue_id": "S0003", "original_subtitle": "tail"},
                    {"cue_id": "S0004", "original_subtitle": "one right word"},
                    {"cue_id": "S0005", "original_subtitle": "new phrase"},
                ],
                "history": [
                    {"operation": "edit_display_page_chinese", "parent_subtitle_id": "S0001"},
                    {"operation": "confirm_display_page_boundary", "parent_subtitle_id": "S0002"},
                    {
                        "operation": "trim_tail_from_cue",
                        "first_removed_display_page_id": "S0003.P01",
                    },
                    {"operation": "edit_english_surface", "affected_parent_ids": ["S0004"]},
                    {"operation": "edit_english_surface", "affected_parent_ids": ["S0005"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    queue_path = tmp_path / "queue.srt"
    queue_path.write_text(
        "\n\n".join(
            [
                "1\n00:00:00,000 --> 00:00:01,000\nID: S0001",
                "2\n00:00:01,000 --> 00:00:02,000\nID: S0002, S0009",
                "3\n00:00:02,000 --> 00:00:03,000\nID: S0004",
                "4\n00:00:03,000 --> 00:00:04,000\nID: S0010",
            ]
        ),
        encoding="utf-8",
    )

    result = measure(manual_path, queue_path)

    assert result["manual_change_parent_count"] == 5
    assert result["queue_unique_parent_count"] == 5
    assert result["queue_hit_parent_count"] == 3
    assert result["recall_percent"] == 60.0
    assert result["precision_percent"] == 60.0
    assert result["word_hit_fraction"] == "1/1"
