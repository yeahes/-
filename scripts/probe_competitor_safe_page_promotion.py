"""Find safe, already-enumerated extra-page candidates for long captions.

This is a read-only probe.  It does not relax hard boundaries, call an LLM,
or write any page artifact.  A candidate is only proposed when the existing
planner has already enumerated it and the promotion reduces display pressure
without introducing a severe boundary or an under-sized page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
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
from scripts.probe_competitor_long_caption_pagination import (  # noqa: E402
    _load_parent_chinese,
    _page_global_range,
)


DRAW = ImageDraw.Draw(
    Image.new("RGB", (planner.ARTICLE_WIDTH, planner.ARTICLE_HEIGHT))
)


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


def _ranges(plan: Mapping[str, Any]) -> list[tuple[int, int]]:
    return [_page_global_range(page) for page in plan.get("pages") or ()]


def _page_counts(plan: Mapping[str, Any]) -> list[int]:
    return [end - start + 1 for start, end in _ranges(plan)]


def _page_durations(plan: Mapping[str, Any]) -> list[int]:
    durations = []
    for page in plan.get("pages") or ():
        start_ms = page.get("start_ms")
        end_ms = page.get("end_ms")
        if start_ms is None:
            start_ms = round(float(page.get("start") or 0.0) * 1000)
        if end_ms is None:
            end_ms = round(float(page.get("end") or 0.0) * 1000)
        durations.append(max(0, int(end_ms) - int(start_ms)))
    return durations


def _pressure(plan: Mapping[str, Any]) -> float:
    return max(
        (float(planner._article_display_page_pressure(page)) for page in plan.get("pages") or ()),
        default=0.0,
    )


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    plan = candidate.get("plan") or {}
    return {
        "page_count": int(candidate.get("page_count") or 0),
        "ranges": _ranges(plan),
        "page_word_counts": _page_counts(plan),
        "page_durations_ms": _page_durations(plan),
        "fonts": [
            int(page.get("english_font_size") or planner.ARTICLE_SUBTITLE_EN_FONT_SIZE)
            for page in plan.get("pages") or ()
        ],
        "max_pressure": round(_pressure(plan), 6),
        "risk_score": int(candidate.get("risk_score") or 0),
        "severe_risk_count": int(candidate.get("severe_risk_count") or 0),
        "relaxed_raw_hard_count": int(candidate.get("relaxed_raw_hard_count") or 0),
        "review_count": int(candidate.get("review_count") or 0),
        "forced_continuation": bool(candidate.get("forced_continuation")),
        "review_boundary_candidate": bool(candidate.get("review_boundary_candidate")),
        "quality_cost": round(float(candidate.get("quality_cost") or 0.0)),
        "english": [str(page.get("en") or "") for page in plan.get("pages") or ()],
    }


def _matches_selected(candidate: Mapping[str, Any], selected: Mapping[str, Any]) -> bool:
    return _ranges(candidate.get("plan") or {}) == _ranges(selected)


def _eligible_extra_page(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    plan = candidate.get("plan") or {}
    base_plan = baseline.get("plan") or {}
    if int(candidate.get("page_count") or 0) <= len(base_plan.get("pages") or ()):
        reasons.append("not_more_pages")
    if int(candidate.get("severe_risk_count") or 0):
        reasons.append("severe_risk")
    if int(candidate.get("relaxed_raw_hard_count") or 0):
        reasons.append("relaxed_raw_hard_boundary")
    if any(
        int(page.get("english_font_size") or planner.ARTICLE_SUBTITLE_EN_FONT_SIZE) < 56
        for page in plan.get("pages") or ()
    ):
        reasons.append("font_below_56px")
    if any(count < 6 for count in _page_counts(plan)):
        reasons.append("page_below_6_words")
    if any(duration < 900 for duration in _page_durations(plan)):
        reasons.append("page_below_900ms")
    if int(candidate.get("risk_score") or 0) > int(baseline.get("risk_score") or 0):
        reasons.append("risk_increased")
    if _pressure(plan) >= _pressure(base_plan):
        reasons.append("maximum_pressure_not_reduced")
    return not reasons, reasons


def _probe(run_path: Path) -> dict[str, Any]:
    run = _load_run(run_path)
    parent_chinese = _load_parent_chinese(run.artifact_dir)
    rows: list[dict[str, Any]] = []
    candidate_count = 0
    eligible_count = 0
    rejection_reasons: Counter[str] = Counter()
    rejection_samples: list[dict[str, Any]] = []
    near_miss_candidates: list[dict[str, Any]] = []
    for parent in run.spans:
        parent_id = str(parent["subtitle_id"])
        cue = _cue_for_parent(run, parent, parent_chinese.get(parent_id, ""))
        selected_plan = planner._build_article_english_page_plan(cue, DRAW)
        bundle = planner._build_article_english_page_plan(
            cue,
            DRAW,
            _return_candidates=True,
            max_page_count=planner.ARTICLE_VISUAL_PAGE_MAX_PAGES,
        )
        if str(selected_plan.get("status") or "") != "ok":
            continue
        selected_candidate = next(
            (
                candidate
                for candidate in bundle.get("candidates") or ()
                if _matches_selected(candidate, selected_plan)
            ),
            None,
        )
        if selected_candidate is None:
            continue
        baseline = dict(selected_candidate)
        shadows = [
            candidate
            for candidate in bundle.get("shadow_candidates") or ()
            if _ranges(candidate.get("plan") or {}) != _ranges(selected_plan)
        ]
        for candidate in shadows:
            if int(candidate.get("page_count") or 0) <= len(selected_plan.get("pages") or ()):
                continue
            candidate_count += 1
            eligible, reasons = _eligible_extra_page(baseline, candidate)
            if not eligible:
                rejection_reasons.update(reasons)
                baseline_summary = _candidate_summary(baseline)
                candidate_summary = _candidate_summary(candidate)
                near_miss_candidates.append(
                    {
                        "parent_subtitle_id": parent_id,
                        "reasons": reasons,
                        "reason_count": len(reasons),
                        "risk_delta": candidate_summary["risk_score"]
                        - baseline_summary["risk_score"],
                        "pressure_delta": round(
                            candidate_summary["max_pressure"]
                            - baseline_summary["max_pressure"],
                            6,
                        ),
                        "min_page_words": min(candidate_summary["page_word_counts"]),
                        "min_page_duration_ms": min(candidate_summary["page_durations_ms"]),
                        "baseline": baseline_summary,
                        "candidate": candidate_summary,
                    }
                )
                if len(rejection_samples) < 12:
                    rejection_samples.append(
                        {
                            "parent_subtitle_id": parent_id,
                            "reasons": reasons,
                            "baseline": baseline_summary,
                            "candidate": candidate_summary,
                        }
                    )
                continue
            eligible_count += 1
            rows.append(
                {
                    "parent_subtitle_id": parent_id,
                    "baseline": _candidate_summary(baseline),
                    "candidate": _candidate_summary(candidate),
                }
            )
    return {
        "experiment": "competitor-safe-extra-page-promotion-v1",
        "status": "complete",
        "artifact_dir": str(run.artifact_dir),
        "word_ledger_hash": run.ledger_hash,
        "same_word_ledger": True,
        "api_calls": 0,
        "production_files_modified": False,
        "artifact_files_modified": False,
        "translation_evaluated": False,
        "parents_with_extra_page_candidates": candidate_count,
        "eligible_extra_page_candidates": eligible_count,
        "rejection_reason_counts": dict(rejection_reasons.most_common()),
        "rejection_samples": rejection_samples,
        "near_miss_candidates": sorted(
            near_miss_candidates,
            key=lambda item: (
                int(item["reason_count"]),
                int(item["risk_delta"]),
                float(item["pressure_delta"]),
                -int(item["min_page_words"]),
                -int(item["min_page_duration_ms"]),
            ),
        )[:12],
        "eligible_promotions": rows,
        "limits": [
            "Only candidates already enumerated by the existing planner were considered.",
            "Hard boundaries were not downgraded and no new split was synthesized.",
            "Candidate page-Chinese quality is not scored because existing page Chinese is bound to baseline ranges.",
            "This is a targeted planner probe, not a production change or a full-film quality score.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = _probe(args.run)
    if args.output:
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
                "parents_with_extra_page_candidates": report["parents_with_extra_page_candidates"],
                "eligible_extra_page_candidates": report["eligible_extra_page_candidates"],
                "rejection_reason_counts": report["rejection_reason_counts"],
                "rejection_samples": report["rejection_samples"],
                "near_miss_candidates": report["near_miss_candidates"],
                "eligible_promotions": report["eligible_promotions"],
                "output": str(args.output.resolve()) if args.output else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
