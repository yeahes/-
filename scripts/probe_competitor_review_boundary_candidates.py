"""Audit existing page candidates for clean, punctuation-backed boundaries.

The probe is read-only. It derives the target parents from a stressed audit
report, reuses only candidates already enumerated by the production planner,
and never changes a stable run or calls an LLM.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping


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
TERMINAL_PUNCTUATION = re.compile(r"[.!?;:]$")
ANY_PUNCTUATION = re.compile(r"[,.!?;:]$")


def _ranges(plan: Mapping[str, Any]) -> list[tuple[int, int]]:
    return [_page_global_range(page) for page in plan.get("pages") or ()]


def _page_counts(plan: Mapping[str, Any]) -> list[int]:
    return [end - start + 1 for start, end in _ranges(plan)]


def _page_durations(plan: Mapping[str, Any]) -> list[int]:
    durations: list[int] = []
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
        (
            float(planner._article_display_page_pressure(page))
            for page in plan.get("pages") or ()
        ),
        default=0.0,
    )


def _boundary_evidence(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    pages = list(plan.get("pages") or ())
    evidence: list[dict[str, Any]] = []
    for index, page in enumerate(pages[1:], start=1):
        previous = str(pages[index - 1].get("en") or "").split()
        current = str(page.get("en") or "").split()
        decision = page.get("boundary_before") or {}
        previous_last = previous[-1] if previous else ""
        current_first = current[0] if current else ""
        issue_codes = [str(code) for code in decision.get("issue_codes") or ()]
        evidence.append(
            {
                "page_index": index,
                "previous_last_word": previous_last,
                "next_first_word": current_first,
                "classification": str(decision.get("classification") or ""),
                "issue_codes": issue_codes,
                "pause_ms": decision.get("pause_ms"),
                "boundary_score": decision.get("boundary_score"),
                "clean_allow": (
                    str(decision.get("classification") or "") == "allow"
                    and not issue_codes
                ),
                "previous_terminal_punctuation": bool(
                    TERMINAL_PUNCTUATION.search(previous_last)
                ),
                "previous_any_punctuation": bool(
                    ANY_PUNCTUATION.search(previous_last)
                ),
            }
        )
    return evidence


def _summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    plan = candidate.get("plan") or {}
    boundaries = _boundary_evidence(plan)
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
        "incomplete_review_count": int(candidate.get("incomplete_review_count") or 0),
        "quality_cost": round(float(candidate.get("quality_cost") or 0.0)),
        "english": [str(page.get("en") or "") for page in plan.get("pages") or ()],
        "boundaries": boundaries,
        "clean_boundary_count": sum(
            bool(item["clean_allow"]) for item in boundaries
        ),
        "terminal_punctuation_boundary_count": sum(
            bool(item["previous_terminal_punctuation"]) for item in boundaries
        ),
        "any_punctuation_boundary_count": sum(
            bool(item["previous_any_punctuation"]) for item in boundaries
        ),
    }


def _matches_selected(candidate: Mapping[str, Any], selected: Mapping[str, Any]) -> bool:
    return _ranges(candidate.get("plan") or {}) == _ranges(selected)


def _gate_reasons(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> list[str]:
    base = _summary(baseline)
    current = _summary(candidate)
    reasons: list[str] = []
    if current["page_count"] != base["page_count"]:
        reasons.append("page_count_changed")
    if current["clean_boundary_count"] != current["page_count"] - 1:
        reasons.append("boundary_not_clean_allow")
    if current["terminal_punctuation_boundary_count"] == 0 and current[
        "any_punctuation_boundary_count"
    ] == 0:
        reasons.append("no_punctuation_evidence")
    if current["severe_risk_count"]:
        reasons.append("severe_risk")
    if current["relaxed_raw_hard_count"]:
        reasons.append("relaxed_raw_hard_boundary")
    if current["incomplete_review_count"]:
        reasons.append("incomplete_review")
    if any(font < 56 for font in current["fonts"]):
        reasons.append("font_below_56px")
    if any(count < 6 for count in current["page_word_counts"]):
        reasons.append("page_below_6_words")
    if any(duration < 900 for duration in current["page_durations_ms"]):
        reasons.append("page_below_900ms")
    if current["risk_score"] > base["risk_score"]:
        reasons.append("risk_increased")
    if current["max_pressure"] >= base["max_pressure"]:
        reasons.append("maximum_pressure_not_reduced")
    return reasons


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


def _probe(run_path: Path, audit_path: Path) -> dict[str, Any]:
    run = _load_run(run_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    target_ids = [
        str(row["subtitle_id"])
        for row in audit.get("rows") or ()
        if any(
            str(page.get("boundary_before", {}).get("classification") or "")
            == "review"
            for page in row.get("pages") or ()
        )
    ]
    parent_by_id = {
        str(parent["subtitle_id"]): parent
        for parent in run.spans
        if str(parent["subtitle_id"]) in target_ids
    }
    parent_chinese = _load_parent_chinese(run.artifact_dir)
    rows: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    candidate_count = 0
    for parent_id in target_ids:
        parent = parent_by_id.get(parent_id)
        if parent is None:
            continue
        cue = _cue_for_parent(run, parent, parent_chinese.get(parent_id, ""))
        selected = planner._build_article_english_page_plan(cue, DRAW)
        bundle = planner._build_article_english_page_plan(
            cue,
            DRAW,
            _return_candidates=True,
            max_page_count=planner.ARTICLE_VISUAL_PAGE_MAX_PAGES,
        )
        if str(selected.get("status") or "") != "ok":
            continue
        baseline = next(
            (
                candidate
                for candidate in bundle.get("candidates") or ()
                if _matches_selected(candidate, selected)
            ),
            None,
        )
        if baseline is None:
            continue
        shadows = [
            candidate
            for candidate in bundle.get("shadow_candidates") or ()
            if _ranges(candidate.get("plan") or {}) != _ranges(selected)
        ]
        candidate_count += len(shadows)
        candidate_rows: list[dict[str, Any]] = []
        for candidate in shadows:
            reasons = _gate_reasons(baseline, candidate)
            candidate_summary = _summary(candidate)
            item = {
                "reasons": reasons,
                "reason_count": len(reasons),
                "risk_delta": candidate_summary["risk_score"]
                - _summary(baseline)["risk_score"],
                "pressure_delta": round(
                    candidate_summary["max_pressure"]
                    - _summary(baseline)["max_pressure"],
                    6,
                ),
                "candidate": candidate_summary,
            }
            candidate_rows.append(item)
            if not reasons:
                eligible.append(
                    {
                        "parent_subtitle_id": parent_id,
                        "baseline": _summary(baseline),
                        **item,
                    }
                )
        candidate_rows.sort(
            key=lambda item: (
                int(item["reason_count"]),
                int(item["risk_delta"]),
                float(item["pressure_delta"]),
            )
        )
        rows.append(
            {
                "parent_subtitle_id": parent_id,
                "baseline": _summary(baseline),
                "candidate_count": len(candidate_rows),
                "nearest_candidates": candidate_rows[:5],
            }
        )
    return {
        "experiment": "competitor-review-boundary-candidates-v1",
        "status": "complete",
        "run_dir": str(run_path),
        "audit_path": str(audit_path),
        "word_ledger_hash": run.ledger_hash,
        "same_word_ledger": True,
        "api_calls": 0,
        "production_files_modified": False,
        "artifact_files_modified": False,
        "target_parent_count": len(target_ids),
        "parents_with_candidates": len(rows),
        "same_or_alternate_page_candidate_count": candidate_count,
        "eligible_clean_punctuation_promotions": len(eligible),
        "eligible_promotions": eligible,
        "parents": rows,
        "gates": [
            "Candidate must already be enumerated by the existing planner.",
            "Every internal boundary must be classification=allow with no issue codes.",
            "At least one punctuation boundary is required; comma is recorded as weak evidence.",
            "Every page must be at least 6 words, 900ms, and 56px.",
            "Risk, hard-boundary status, and maximum pressure must not worsen.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--audit-json", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = _probe(args.run, args.audit_json)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "same_word_ledger",
                    "target_parent_count",
                    "parents_with_candidates",
                    "same_or_alternate_page_candidate_count",
                    "eligible_clean_punctuation_promotions",
                    "eligible_promotions",
                    "output",
                )
                if key in report
            }
            | ({"output": str(args.output.resolve())} if args.output else {}),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
