"""Offline A/B probe for competitor-inspired long-caption pagination.

The probe reads an immutable stable run, rebuilds page candidates in memory,
and optionally writes a report outside the run directory.  It never calls an
LLM, changes subtitle artifacts, or changes the production page planner.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from app.core.utils import podcast_learning_video as planner  # noqa: E402
from scripts.audit_pre_id_joint_page_feasibility import (  # noqa: E402
    _cue_for_range,
    _load_run,
)


DRAW = ImageDraw.Draw(
    Image.new("RGB", (planner.ARTICLE_WIDTH, planner.ARTICLE_HEIGHT))
)

TERMINAL_RE = re.compile(r"[.!?\u3002\uff01\uff1f\u2026][\"')\]]*$")
CLAUSE_RE = re.compile(r"[,;:][\"')\]]*$")


def _load_parent_chinese(artifact_dir: Path) -> dict[str, str]:
    payload = json.loads(
        (artifact_dir / "authoritative-parent-chinese.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        str(record.get("subtitle_id") or ""): str(record.get("chinese") or "")
        for record in payload.get("records") or ()
        if isinstance(record, Mapping)
    }


def _saved_pages(run: Any) -> dict[str, list[dict[str, Any]]]:
    return {
        str(parent_id): [dict(page) for page in plan.get("pages") or ()]
        for parent_id, plan in run.saved_plans.items()
    }


def _cue_for_parent(run: Any, parent: Mapping[str, Any], chinese: str):
    subtitle_id = str(parent["subtitle_id"])
    timeline = run.timeline[subtitle_id]
    return _cue_for_range(
        run,
        int(parent["word_start"]),
        int(parent["word_end"]),
        subtitle_id,
        chinese=chinese,
        display_start_ms=int(timeline.get("start_ms") or 0),
        display_end_ms=int(timeline.get("end_ms") or 0),
    )


def _page_global_range(page: Mapping[str, Any]) -> tuple[int, int]:
    start = page.get("global_word_start", page.get("word_start"))
    end = page.get("global_word_end", page.get("word_end"))
    return int(start), int(end)


def _page_boundary_kind(words: Sequence[Mapping[str, Any]], page: Mapping[str, Any]) -> str:
    _, end = _page_global_range(page)
    if end < 0 or end >= len(words):
        return "unknown"
    surface = str(words[end].get("surface") or "").strip()
    if TERMINAL_RE.search(surface):
        return "terminal_punctuation"
    if CLAUSE_RE.search(surface):
        return "clause_punctuation"
    return "non_punctuation"


def _page_metrics(
    run: Any,
    parent_id: str,
    pages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    word_counts = []
    durations = []
    fonts = []
    boundary_kinds = []
    for index, page in enumerate(pages):
        start, end = _page_global_range(page)
        word_counts.append(max(0, end - start + 1))
        start_ms = page.get("start_ms")
        end_ms = page.get("end_ms")
        if start_ms is None:
            start_ms = round(float(page.get("start") or 0.0) * 1000)
        if end_ms is None:
            end_ms = round(float(page.get("end") or 0.0) * 1000)
        durations.append(max(0, int(end_ms) - int(start_ms)))
        fonts.append(int(page.get("english_font_size") or planner.ARTICLE_SUBTITLE_EN_FONT_SIZE))
        if index < len(pages) - 1:
            boundary_kinds.append(_page_boundary_kind(run.words, page))
    punctuation_boundaries = sum(
        kind in {"terminal_punctuation", "clause_punctuation"}
        for kind in boundary_kinds
    )
    return {
        "parent_subtitle_id": parent_id,
        "page_count": len(pages),
        "internal_boundary_count": max(0, len(pages) - 1),
        "terminal_punctuation_boundaries": boundary_kinds.count("terminal_punctuation"),
        "clause_punctuation_boundaries": boundary_kinds.count("clause_punctuation"),
        "punctuation_boundaries": punctuation_boundaries,
        "non_punctuation_boundaries": boundary_kinds.count("non_punctuation"),
        "boundary_kinds": boundary_kinds,
        "min_page_duration_ms": min(durations, default=0),
        "max_page_duration_ms": max(durations, default=0),
        "min_page_words": min(word_counts, default=0),
        "max_page_words": max(word_counts, default=0),
        "word_count_imbalance": max(word_counts, default=0) - min(word_counts, default=0),
        "pages_below_56px": sum(font < 56 for font in fonts),
        "fonts": fonts,
    }


def _run_metrics(run: Any, plans: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    per_parent = [
        _page_metrics(run, parent_id, pages)
        for parent_id, pages in plans.items()
    ]
    multipage = [item for item in per_parent if item["page_count"] > 1]
    return {
        "parent_count": len(per_parent),
        "multipage_parent_count": len(multipage),
        "page_count": sum(int(item["page_count"]) for item in per_parent),
        "internal_boundary_count": sum(int(item["internal_boundary_count"]) for item in per_parent),
        "terminal_punctuation_boundaries": sum(
            int(item["terminal_punctuation_boundaries"]) for item in per_parent
        ),
        "clause_punctuation_boundaries": sum(
            int(item["clause_punctuation_boundaries"]) for item in per_parent
        ),
        "punctuation_boundaries": sum(int(item["punctuation_boundaries"]) for item in per_parent),
        "non_punctuation_boundaries": sum(
            int(item["non_punctuation_boundaries"]) for item in per_parent
        ),
        "pages_below_56px": sum(int(item["pages_below_56px"]) for item in per_parent),
        "min_page_duration_ms": min(
            (int(item["min_page_duration_ms"]) for item in per_parent if item["page_count"]),
            default=0,
        ),
        "min_page_words": min(
            (int(item["min_page_words"]) for item in per_parent if item["page_count"]),
            default=0,
        ),
        "max_page_words": max(
            (int(item["max_page_words"]) for item in per_parent if item["page_count"]),
            default=0,
        ),
        "per_parent": per_parent,
    }


def _competitor_bonus(
    cue: Any,
    words: Sequence[str],
    split: int,
    word_timing: Sequence[Mapping[str, Any]],
) -> int:
    """Bounded presentation preference used only by this offline probe."""
    if split <= 0 or split >= len(words):
        return 0
    previous_surface = str(words[split - 1]).strip()
    bonus = 0
    if TERMINAL_RE.search(previous_surface):
        bonus += 1000
    elif CLAUSE_RE.search(previous_surface):
        bonus += 500
    if len(word_timing) == len(words):
        try:
            pause_ms = max(
                0,
                round(
                    (
                        float(word_timing[split]["start"])
                        - float(word_timing[split - 1]["end"])
                    )
                    * 1000
                ),
            )
        except (KeyError, TypeError, ValueError):
            pause_ms = 0
        if pause_ms >= 450:
            bonus += min(350, pause_ms - 450)
    return bonus


def _candidate_plans(run: Any, parent_chinese: Mapping[str, str]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    plans: dict[str, list[dict[str, Any]]] = {}
    failures: list[dict[str, Any]] = []
    for parent in run.spans:
        parent_id = str(parent["subtitle_id"])
        cue = _cue_for_parent(run, parent, parent_chinese.get(parent_id, ""))
        plan = planner._build_article_english_page_plan(cue, DRAW)
        if str(plan.get("status") or "") != "ok":
            failures.append(
                {
                    "parent_subtitle_id": parent_id,
                    "status": str(plan.get("status") or ""),
                    "errors": list(plan.get("errors") or ()),
                }
            )
            continue
        plans[parent_id] = [copy.deepcopy(page) for page in plan.get("pages") or ()]
    return plans, failures


def _run_probe(
    run_path: Path,
    *,
    target_words: int | None = None,
    preferred_words: int | None = None,
) -> dict[str, Any]:
    run = _load_run(run_path)
    parent_chinese = _load_parent_chinese(run.artifact_dir)
    frozen_baseline = _saved_pages(run)
    frozen_baseline_metrics = _run_metrics(run, frozen_baseline)

    old_target_words = planner.ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS
    old_preferred_words = planner.ARTICLE_VISUAL_PAGE_PREFERRED_WORDS
    if target_words is not None:
        planner.ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS = int(target_words)
    if preferred_words is not None:
        planner.ARTICLE_VISUAL_PAGE_PREFERRED_WORDS = int(preferred_words)

    original_score = planner._article_page_break_score

    try:
        rebuilt_baseline, baseline_failures = _candidate_plans(run, parent_chinese)
        rebuilt_baseline_metrics = _run_metrics(run, rebuilt_baseline)

        def competitor_score(*args: Any, **kwargs: Any):
            score = original_score(*args, **kwargs)
            if score is None:
                return None
            cue, words, split, _target_words, word_timing = args[:5]
            return int(score) - _competitor_bonus(cue, words, split, word_timing)

        planner._article_page_break_score = competitor_score
        candidate, failures = _candidate_plans(run, parent_chinese)
    finally:
        planner._article_page_break_score = original_score
        planner.ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS = old_target_words
        planner.ARTICLE_VISUAL_PAGE_PREFERRED_WORDS = old_preferred_words

    candidate_metrics = _run_metrics(run, candidate)
    frozen_by_id = {str(key): value for key, value in frozen_baseline.items()}
    rebuilt_by_id = {str(key): value for key, value in rebuilt_baseline.items()}
    candidate_by_id = {str(key): value for key, value in candidate.items()}
    changed_vs_rebuilt: list[dict[str, Any]] = []
    frozen_rebuild_mismatches: list[dict[str, Any]] = []
    for parent_id in sorted(set(frozen_by_id) | set(rebuilt_by_id) | set(candidate_by_id)):
        frozen_pages = frozen_by_id.get(parent_id, [])
        rebuilt_pages = rebuilt_by_id.get(parent_id, [])
        new_pages = candidate_by_id.get(parent_id, [])
        frozen_ranges = [_page_global_range(page) for page in frozen_pages]
        rebuilt_ranges = [_page_global_range(page) for page in rebuilt_pages]
        new_ranges = [_page_global_range(page) for page in new_pages]
        if frozen_ranges != rebuilt_ranges:
            frozen_rebuild_mismatches.append(
                {
                    "parent_subtitle_id": parent_id,
                    "frozen_ranges": frozen_ranges,
                    "rebuilt_ranges": rebuilt_ranges,
                    "frozen": _page_metrics(run, parent_id, frozen_pages),
                    "rebuilt": _page_metrics(run, parent_id, rebuilt_pages),
                }
            )
        if rebuilt_ranges != new_ranges:
            changed_vs_rebuilt.append(
                {
                    "parent_subtitle_id": parent_id,
                    "baseline_ranges": rebuilt_ranges,
                    "candidate_ranges": new_ranges,
                    "baseline": _page_metrics(run, parent_id, rebuilt_pages),
                    "candidate": _page_metrics(run, parent_id, new_pages),
                }
            )

    return {
        "experiment": "competitor-inspired-long-caption-pagination-ab-v1",
        "status": "complete" if not failures else "candidate_build_incomplete",
        "artifact_dir": str(run.artifact_dir),
        "word_ledger_hash": run.ledger_hash,
        "same_word_ledger": True,
        "target_words_override": target_words,
        "preferred_words_override": preferred_words,
        "api_calls": 0,
        "production_files_modified": False,
        "artifact_files_modified": False,
        "translation_evaluated": False,
        "frozen_baseline": frozen_baseline_metrics,
        "rebuilt_baseline": rebuilt_baseline_metrics,
        "candidate": candidate_metrics,
        "frozen_rebuild_mismatch_count": len(frozen_rebuild_mismatches),
        "frozen_rebuild_mismatches": frozen_rebuild_mismatches,
        "changed_parent_count": len(changed_vs_rebuilt),
        "changed_parents": changed_vs_rebuilt,
        "rebuilt_baseline_failures": baseline_failures,
        "candidate_failures": failures,
        "limits": [
            "B changes only the in-memory English page-break score; production code is not changed.",
            "Existing page-Chinese is bound to the frozen page ranges, so candidate page-Chinese quality is not scored.",
            "Punctuation is measured on English word surfaces as a proxy for the competitor's visible Chinese punctuation behavior.",
            "This is a targeted long-caption planner probe, not a full-film quality score.",
        ],
    }


def _ensure_report_outside_artifact(report_path: Path, artifact_dir: Path) -> None:
    try:
        report_path.resolve().relative_to(artifact_dir.resolve())
    except ValueError:
        return
    raise ValueError("report output must be outside the immutable artifact directory")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--target-words", type=int)
    parser.add_argument("--preferred-words", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = _run_probe(
        args.run,
        target_words=args.target_words,
        preferred_words=args.preferred_words,
    )
    if args.output:
        _ensure_report_outside_artifact(args.output, Path(report["artifact_dir"]))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "same_word_ledger": report["same_word_ledger"],
                "target_words_override": report["target_words_override"],
                "preferred_words_override": report["preferred_words_override"],
                "frozen_baseline": {
                    key: value
                    for key, value in report["frozen_baseline"].items()
                    if key != "per_parent"
                },
                "rebuilt_baseline": {
                    key: value
                    for key, value in report["rebuilt_baseline"].items()
                    if key != "per_parent"
                },
                "candidate": {
                    key: value
                    for key, value in report["candidate"].items()
                    if key != "per_parent"
                },
                "changed_parent_count": report["changed_parent_count"],
                "frozen_rebuild_mismatch_count": report["frozen_rebuild_mismatch_count"],
                "rebuilt_baseline_failures": report["rebuilt_baseline_failures"],
                "candidate_failures": report["candidate_failures"],
                "output": str(args.output.resolve()) if args.output else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
