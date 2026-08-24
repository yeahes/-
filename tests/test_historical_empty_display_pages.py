"""Guard the v28-v32 non-renderable page recovery shape."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.utils.podcast_learning_video import (
    Cue,
    _article_editable_page_seed_plan,
)


ROOT = Path(__file__).resolve().parents[1]
PLANNER_VERSIONS = {
    "article-fixed-font-pages-v28",
    "article-fixed-font-pages-v29",
    "article-fixed-font-pages-v32",
}


def _project_seed_lines_and_snapshot() -> tuple[int, int, list[tuple]]:
    empty_before = 0
    nonempty_after = 0
    snapshots: list[tuple] = []

    for artifact_dir in sorted((ROOT / "work-dir").glob("*/subtitle/*artifacts")):
        display_path = artifact_dir / "display-page-translations.json"
        ledger_path = artifact_dir / "word-ledger.json"
        if not display_path.is_file() or not ledger_path.is_file():
            continue
        display = json.loads(display_path.read_text(encoding="utf-8-sig"))
        if display.get("planner_version") not in PLANNER_VERSIONS:
            continue
        ledger = json.loads(ledger_path.read_text(encoding="utf-8-sig"))
        words = {
            int(word["word_id"]): word
            for word in ledger.get("words") or []
            if isinstance(word, dict) and "word_id" in word
        }

        for plan in display.get("render_plans") or []:
            for page in plan.get("pages") or []:
                if page.get("english_lines"):
                    continue
                empty_before += 1
                word_start = int(page["word_start"])
                word_end = int(page["word_end"])
                timing = tuple(
                    {
                        "word_id": word_id,
                        "word_end": word_id,
                        "surface": str(words[word_id].get("surface") or ""),
                        "start": words[word_id].get("start"),
                        "end": words[word_id].get("end"),
                    }
                    for word_id in range(word_start, word_end + 1)
                    if word_id in words
                )
                cue = Cue(
                    index=0,
                    start=float(page.get("start_ms") or 0) / 1000,
                    end=float(page.get("end_ms") or 0) / 1000,
                    en=str(plan.get("english") or ""),
                    zh=str(plan.get("chinese") or ""),
                    speaker="",
                    subtitle_id=str(plan.get("parent_subtitle_id") or ""),
                    word_timing=timing,
                )
                seed = _article_editable_page_seed_plan(
                    cue,
                    [
                        {
                            "cue_index": 0,
                            "reason": str(
                                (plan.get("failure_reasons") or [
                                    "render_structural_overflow"
                                ])[0]
                            ),
                        }
                    ],
                )
                assert seed is not None
                seed_page = seed["pages"][0]
                assert seed_page["english_lines"]
                assert seed_page["display_page_id"] == page.get("display_page_id")
                assert seed_page["word_start"] == word_start
                assert seed_page["word_end"] == word_end
                assert seed_page["english"] == page.get("english")
                assert seed["chinese"] == plan.get("chinese")
                nonempty_after += 1

                # D may replace only the empty preview line. All publication
                # identity and page-content fields must remain unchanged.
                snapshots.append(
                    (
                        page.get("display_page_id"),
                        page.get("word_start"),
                        page.get("word_end"),
                        page.get("english"),
                        plan.get("chinese"),
                    )
                )
    return empty_before, nonempty_after, snapshots


def test_historical_empty_pages_recover_preview_lines_without_repartitioning():
    empty_before, nonempty_after, snapshots = _project_seed_lines_and_snapshot()

    assert empty_before == 15
    assert nonempty_after == 15
    assert len(snapshots) == empty_before
    assert all(all(value is not None for value in snapshot) for snapshot in snapshots)


if __name__ == "__main__":
    before, after, _snapshots = _project_seed_lines_and_snapshot()
    assert before == 15
    assert after == 15
    print(f"Historical empty-page recovery passed: {before} -> {before - after}.")
