from __future__ import annotations

import json
from pathlib import Path

from scripts import experiment_fixed_parent_bilingual_pages as experiment


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_changed_contract_preserves_parent_and_page_word_coverage(tmp_path: Path):
    artifact = tmp_path / "episode-artifacts"
    artifact.mkdir()
    _write_json(
        artifact / "subtitle-spans.json",
        [
            {
                "subtitle_id": "S0001",
                "word_start": 10,
                "word_end": 19,
                "original": "one two three four five six seven eight nine ten",
            }
        ],
    )
    _write_json(
        artifact / "authoritative-parent-chinese.json",
        {"records": [{"subtitle_id": "S0001", "chinese": "一二三四五六七八九十"}]},
    )
    _write_json(
        artifact / "display-page-translations.json",
        {"layout_profile": {"chinese_font_size": 50, "max_lines": 2}},
    )
    changed = [
        {
            "subtitle_id": "S0001",
            "material": {
                "pages": [
                    {
                        "english": "one two three four five",
                        "word_start": 10,
                        "word_end": 14,
                        "start_ms": 0,
                        "end_ms": 1200,
                    },
                    {
                        "english": "six seven eight nine ten",
                        "word_start": 15,
                        "word_end": 19,
                        "start_ms": 1200,
                        "end_ms": 2500,
                    },
                ]
            },
        }
    ]

    contract = experiment.build_changed_page_contract(artifact, changed)

    assert contract is not None
    parent = contract["parents"][0]
    assert parent["parent_subtitle_id"] == "S0001"
    assert parent["source_chinese"] == "一二三四五六七八九十"
    assert [page["display_page_id"] for page in parent["pages"]] == [
        "S0001.P01",
        "S0001.P02",
    ]
    assert [(page["word_start"], page["word_end"]) for page in parent["pages"]] == [
        (10, 14),
        (15, 19),
    ]


def test_empty_change_set_does_not_build_translation_contract(tmp_path: Path):
    assert experiment.build_changed_page_contract(tmp_path, []) is None
