"""Evaluate pre-ID English boundary moves against the real page planner.

This is an offline experiment. It reads immutable stable artifacts, creates
candidate parent ranges in memory, and optionally writes one standalone JSON
report. It never writes into the supplied artifact directory.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from app.core.subtitle_processor import screen_editor as screen_editor_module
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.utils import podcast_learning_video as page_planner


DEFAULT_TARGET_IDS = (
    "S0037",
    "S0051",
    "S0072",
    "S0081",
    "S0083",
    "S0107",
    "S0110",
    "S0123",
    "S0132",
    "S0158",
    "S0183",
    "S0192",
    "S0201",
    "S0206",
)

DRAW = ImageDraw.Draw(
    Image.new("RGB", (page_planner.ARTICLE_WIDTH, page_planner.ARTICLE_HEIGHT))
)


@dataclass(frozen=True)
class ArtifactRun:
    artifact_dir: Path
    words: tuple[dict[str, Any], ...]
    spans: tuple[dict[str, Any], ...]
    timeline: Mapping[str, dict[str, Any]]
    evidence: Mapping[str, object]
    saved_plans: Mapping[str, dict[str, Any]]
    ledger_hash: str
    source_segments: tuple[dict[str, Any], ...]


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_artifact_dir(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_dir() and resolved.name.endswith("-artifacts"):
        return resolved
    candidates = sorted(
        item
        for item in resolved.iterdir()
        if item.is_dir() and item.name.endswith("-artifacts")
    )
    if len(candidates) != 1:
        raise ValueError(
            f"expected one *-artifacts directory below {resolved}, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def _load_run(path: Path) -> ArtifactRun:
    artifact_dir = _resolve_artifact_dir(path)
    ledger_payload = _read_json(artifact_dir / "word-ledger.json")
    spans = tuple(dict(item) for item in _read_json(artifact_dir / "subtitle-spans.json"))
    timeline_payload = _read_json(artifact_dir / "final-cue-timeline.json")
    evidence_payload = _read_json(artifact_dir / "display-boundary-evidence.json")
    page_payload = _read_json(artifact_dir / "display-page-translations.json")

    words = tuple(dict(item) for item in ledger_payload.get("words") or ())
    word_ids = [int(item["word_id"]) for item in words]
    if word_ids != list(range(len(words))):
        raise ValueError("word ledger is not contiguous and zero-based")
    if not spans:
        raise ValueError("subtitle spans are empty")
    expected_start = 0
    seen_ids: set[str] = set()
    for span in spans:
        subtitle_id = str(span.get("subtitle_id") or "")
        start = int(span["word_start"])
        end = int(span["word_end"])
        if not subtitle_id or subtitle_id in seen_ids:
            raise ValueError(f"invalid or duplicate subtitle ID: {subtitle_id!r}")
        if start != expected_start or end < start:
            raise ValueError(f"non-contiguous subtitle span at {subtitle_id}")
        ledger_text = " ".join(str(words[index].get("surface") or "") for index in range(start, end + 1))
        if " ".join(str(span.get("original") or "").split()) != " ".join(ledger_text.split()):
            raise ValueError(f"word-ledger English mismatch at {subtitle_id}")
        seen_ids.add(subtitle_id)
        expected_start = end + 1
    if expected_start != len(words):
        raise ValueError("subtitle spans do not cover the complete word ledger")

    timeline = {
        str(item["subtitle_id"]): dict(item)
        for item in timeline_payload.get("records") or ()
    }
    if set(timeline) != seen_ids:
        raise ValueError("final timeline ID set does not match subtitle spans")
    return ArtifactRun(
        artifact_dir=artifact_dir,
        words=words,
        spans=spans,
        timeline=timeline,
        evidence=dict(evidence_payload.get("boundaries") or {}),
        saved_plans={
            str(item["parent_subtitle_id"]): dict(item)
            for item in page_payload.get("render_plans") or ()
        },
        ledger_hash=str(ledger_payload.get("hash") or ""),
        source_segments=tuple(
            dict(item) for item in ledger_payload.get("source_segments") or ()
        ),
    )


def _source_segment_state(
    run: ArtifactRun,
) -> tuple[dict[int, tuple[int, int]], dict[int, SimpleNamespace], bool]:
    ranges: dict[int, tuple[int, int]] = {}
    for word in run.words:
        word_id = int(word["word_id"])
        for raw_source_id in word.get("source_segment_ids") or ():
            source_id = int(raw_source_id)
            if source_id in ranges:
                current_start, current_end = ranges[source_id]
                ranges[source_id] = (
                    min(current_start, word_id),
                    max(current_end, word_id),
                )
            else:
                ranges[source_id] = (word_id, word_id)
    source_objects: dict[int, SimpleNamespace] = {}
    speaker_evidence = False
    for raw in run.source_segments:
        source_id = int(raw.get("id") or 0)
        if not source_id:
            continue
        source_objects[source_id] = SimpleNamespace(**raw)
        speaker_evidence = speaker_evidence or any(
            raw.get(key) not in (None, "")
            for key in ("speaker", "speaker_id", "speaker_name")
        )
    if not ranges:
        ranges = {
            index: (int(span["word_start"]), int(span["word_end"]))
            for index, span in enumerate(run.spans, start=1)
        }
    return ranges, source_objects, speaker_evidence


def _make_editor(run: ArtifactRun) -> tuple[ScreenSubtitleEditor, bool]:
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = 16
    editor._active_word_entries = []
    for word in run.words:
        surface = str(word.get("surface") or "")
        tokens = ScreenSubtitleEditor._word_tokens(surface)
        editor._active_word_entries.append(
            {
                "token": tokens[0] if tokens else str(word.get("normalized") or surface),
                "surface": surface,
                "start_time": int(word["start_ms"]),
                "end_time": int(word["end_ms"]),
                "alignment_source": str(word.get("alignment_source") or "offline-ledger"),
            }
        )
    ranges, source_objects, speaker_evidence = _source_segment_state(run)
    editor._active_source_word_spans = ranges
    editor._active_source_segments_by_id = source_objects
    editor._syntax_protected_cuts = set()
    editor._syntax_hard_cut_issues = {}
    editor._syntax_soft_cut_issues = {}
    editor._orphaned_finite_predicate_cache = {}
    editor._syntax_nlp = None
    logger_was_disabled = screen_editor_module.logger.disabled
    screen_editor_module.logger.disabled = True
    try:
        editor._prepare_syntax_cut_hints()
    finally:
        screen_editor_module.logger.disabled = logger_was_disabled
    return editor, speaker_evidence


def _cue_for_range(
    run: ArtifactRun,
    start: int,
    end: int,
    subtitle_id: str,
    *,
    chinese: str = "",
    display_start_ms: int | None = None,
    display_end_ms: int | None = None,
) -> page_planner.Cue:
    words = run.words[start : end + 1]
    timing = tuple(
        {
            "word_id": int(word["word_id"]),
            "surface": str(word.get("surface") or ""),
            "start": int(word["start_ms"]) / 1000.0,
            "end": int(word["end_ms"]) / 1000.0,
        }
        for word in words
    )
    if not timing:
        raise ValueError(f"empty cue range {start}:{end}")
    return page_planner.Cue(
        index=int(re.sub(r"\D", "", subtitle_id) or 0),
        start=(
            int(display_start_ms) / 1000.0
            if display_start_ms is not None
            else float(timing[0]["start"])
        ),
        end=(
            int(display_end_ms) / 1000.0
            if display_end_ms is not None
            else float(timing[-1]["end"])
        ),
        en=" ".join(str(word.get("surface") or "") for word in words),
        zh=chinese,
        speaker="",
        subtitle_id=subtitle_id,
        word_timing=timing,
        display_boundary_evidence=run.evidence,
    )


def _page_summary(page: Mapping[str, object]) -> dict[str, object]:
    english = " ".join(str(page.get("en") or page.get("english") or "").split())
    lines = list(page.get("en_lines") or page.get("english_lines") or ())
    start_ms = round(float(page.get("start") or 0.0) * 1000)
    end_ms = round(float(page.get("end") or 0.0) * 1000)
    if page.get("start_ms") is not None:
        start_ms = int(page["start_ms"])
    if page.get("end_ms") is not None:
        end_ms = int(page["end_ms"])
    return {
        "english": english,
        "word_start": int(page.get("global_word_start", page.get("word_start", 0))),
        "word_end": int(page.get("global_word_end", page.get("word_end", 0))),
        "word_count": len(ScreenSubtitleEditor._word_tokens(english)),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": max(0, end_ms - start_ms),
        "font_size": int(
            page.get("english_font_size")
            or page_planner.ARTICLE_SUBTITLE_EN_FONT_SIZE
        ),
        "line_count": len(lines),
        "pressure": round(page_planner._article_display_page_pressure(page), 6),
        "boundary_classification": str(
            (page.get("boundary_before") or {}).get("classification") or "allow"
        ),
        "boundary_issues": list(
            (page.get("boundary_before") or {}).get("issue_codes") or ()
        ),
    }


def _plan_metrics(pages: Sequence[Mapping[str, object]]) -> dict[str, object]:
    word_counts = [int(page["word_count"]) for page in pages]
    pressures = [float(page["pressure"]) for page in pages]
    return {
        "page_count": len(pages),
        "pages_over_16_words": sum(value > 16 for value in word_counts),
        "pages_below_56px": sum(int(page["font_size"]) < 56 for page in pages),
        "pages_over_two_lines": sum(int(page["line_count"]) > 2 for page in pages),
        "pages_over_pressure_1": sum(value > 1.0 for value in pressures),
        "review_boundaries": sum(
            str(page["boundary_classification"]) == "review" for page in pages[1:]
        ),
        "max_words": max(word_counts, default=0),
        "min_words": min(word_counts, default=0),
        "word_count_imbalance": (
            max(word_counts, default=0) - min(word_counts, default=0)
        ),
        "max_pressure": round(max(pressures, default=0.0), 6),
        "min_duration_ms": min(
            (int(page["duration_ms"]) for page in pages),
            default=0,
        ),
    }


def _plan_range(
    run: ArtifactRun,
    start: int,
    end: int,
    subtitle_id: str,
    *,
    chinese: str = "",
) -> dict[str, object]:
    cue = _cue_for_range(run, start, end, subtitle_id, chinese=chinese)
    plan = page_planner._build_article_english_page_plan(cue, DRAW)
    if plan.get("status") != "ok":
        return {
            "status": str(plan.get("status") or "render_structural_overflow"),
            "errors": list(plan.get("errors") or ()),
            "pages": [],
            "metrics": _plan_metrics(()),
        }
    pages = [_page_summary(page) for page in plan.get("pages") or ()]
    expected_words = [
        str(word.get("surface") or "") for word in run.words[start : end + 1]
    ]
    actual_words = [
        token
        for page in pages
        for token in ScreenSubtitleEditor._word_tokens(str(page["english"]))
    ]
    expected_tokens = ScreenSubtitleEditor._word_tokens(" ".join(expected_words))
    if [token.casefold() for token in actual_words] != [
        token.casefold() for token in expected_tokens
    ]:
        raise ValueError(f"page planner changed English coverage for {subtitle_id}")
    return {
        "status": "ok",
        "errors": [],
        "pages": pages,
        "metrics": _plan_metrics(pages),
    }


def _ranges_from_cuts(
    window_start: int,
    window_end: int,
    cuts: Sequence[int],
) -> tuple[tuple[int, int], ...]:
    boundaries = (window_start, *cuts, window_end + 1)
    if tuple(sorted(boundaries)) != boundaries or len(set(boundaries)) != len(boundaries):
        raise ValueError("cut positions must be strictly increasing")
    return tuple(
        (boundaries[index], boundaries[index + 1] - 1)
        for index in range(len(boundaries) - 1)
    )


def _aggregate_plan_metrics(plans: Sequence[Mapping[str, object]]) -> dict[str, object]:
    pages = [page for plan in plans for page in plan.get("pages") or ()]
    metrics = _plan_metrics(pages)
    metrics["render_failure_count"] = sum(plan.get("status") != "ok" for plan in plans)
    return metrics


def _quality_vector(metrics: Mapping[str, object]) -> tuple[float, ...]:
    return (
        float(metrics.get("render_failure_count") or 0),
        float(metrics.get("pages_over_two_lines") or 0),
        float(metrics.get("pages_over_16_words") or 0),
        float(metrics.get("pages_below_56px") or 0),
        float(metrics.get("review_boundaries") or 0),
        float(metrics.get("pages_over_pressure_1") or 0),
        float(metrics.get("max_pressure") or 0),
        float(metrics.get("word_count_imbalance") or 0),
    )


def _not_worse(
    candidate: Mapping[str, object],
    baseline: Mapping[str, object],
) -> bool:
    return all(
        float(candidate.get(key) or 0) <= float(baseline.get(key) or 0)
        for key in (
            "render_failure_count",
            "pages_over_two_lines",
            "pages_over_16_words",
            "pages_below_56px",
            "review_boundaries",
            "pages_over_pressure_1",
            "max_pressure",
        )
    )


def _speaker_set(editor: ScreenSubtitleEditor, item: object) -> set[str]:
    by_id = getattr(editor, "_active_source_segments_by_id", {}) or {}
    return {
        editor._segment_speaker(by_id[source_id])
        for source_id in getattr(item, "source_ids", ())
        if source_id in by_id and editor._segment_speaker(by_id[source_id])
    }


def _candidate_record(
    run: ArtifactRun,
    editor: ScreenSubtitleEditor,
    original_ranges: Sequence[tuple[int, int]],
    candidate_ranges: Sequence[tuple[int, int]],
    subtitle_ids: Sequence[str],
    previous_range: tuple[int, int] | None,
    next_range: tuple[int, int] | None,
    original_cuts: Sequence[int],
) -> dict[str, object] | None:
    old_items = [editor._item_from_word_span(start, end) for start, end in original_ranges]
    new_items = [editor._item_from_word_span(start, end) for start, end in candidate_ranges]
    if any(item is None for item in old_items + new_items):
        return None
    old_items = [item for item in old_items if item is not None]
    new_items = [item for item in new_items if item is not None]
    previous_item = (
        editor._item_from_word_span(*previous_range) if previous_range else None
    )
    next_item = editor._item_from_word_span(*next_range) if next_range else None

    candidate_cuts = [start for start, _end in candidate_ranges[1:]]
    for left, right in zip(old_items, old_items[1:]):
        pause_ms = editor._boundary_pause_ms(left, right)
        old_cut = int(right.word_start)
        if pause_ms is not None and pause_ms >= 450 and old_cut not in candidate_cuts:
            return None
    if any(len(_speaker_set(editor, item)) > 1 for item in new_items):
        return None

    gate = editor._can_apply_pre_id_repair_candidate(
        old_items,
        new_items,
        previous_item=previous_item,
        next_item=next_item,
    )
    if not gate.get("accepted"):
        return None
    word_counts = [editor._word_count(item.original) for item in new_items]
    if any(count > 19 for count in word_counts):
        return None
    if any(
        count > 16
        and not editor._is_complete_pre_id_structural_overflow_range(start, end)
        for count, (start, end) in zip(word_counts, candidate_ranges)
    ):
        return None

    boundary_evidence = []
    for left, right in zip(new_items, new_items[1:]):
        evaluation = editor._evaluate_item_pair_for_final_boundary(left, right)
        if not evaluation.get("legal"):
            return None
        boundary_evidence.append(
            {
                "pause_ms": evaluation.get("pause_ms"),
                "soft_issues": list(evaluation.get("soft_issues") or ()),
                "boundary_score": evaluation.get("boundary_score"),
                "speaker_change": bool(editor._items_cross_speaker(left, right)),
            }
        )
    plans = [
        _plan_range(run, start, end, subtitle_id)
        for (start, end), subtitle_id in zip(candidate_ranges, subtitle_ids)
    ]
    if any(plan["status"] != "ok" for plan in plans):
        return None
    metrics = _aggregate_plan_metrics(plans)
    shift_distance = sum(
        abs(cut - original) for cut, original in zip(candidate_cuts, original_cuts)
    )
    soft_issue_count = sum(
        len(item.get("soft_issues") or ()) for item in boundary_evidence
    )
    rank = (
        *_quality_vector(metrics),
        float(soft_issue_count),
        float(shift_distance),
        float(max(word_counts, default=0)),
    )
    return {
        "rank": list(rank),
        "ranges": [list(value) for value in candidate_ranges],
        "cuts": candidate_cuts,
        "shift_distance_words": shift_distance,
        "word_counts": word_counts,
        "texts": [item.original for item in new_items],
        "boundary_evidence": boundary_evidence,
        "page_plans": {
            subtitle_id: plan for subtitle_id, plan in zip(subtitle_ids, plans)
        },
        "metrics": metrics,
        "word_coverage_preserved": True,
        "word_order_preserved": True,
        "word_timestamps_preserved": True,
        "speaker_ownership_preserved": True,
        "boundary_changed": tuple(candidate_cuts) != tuple(original_cuts),
    }


def _compare_target(
    run: ArtifactRun,
    editor: ScreenSubtitleEditor,
    subtitle_id: str,
    *,
    radius: int,
    top_k: int,
) -> dict[str, object]:
    id_to_index = {
        str(span["subtitle_id"]): index for index, span in enumerate(run.spans)
    }
    if subtitle_id not in id_to_index:
        raise ValueError(f"unknown subtitle ID: {subtitle_id}")
    target_index = id_to_index[subtitle_id]
    if target_index == 0 or target_index + 1 >= len(run.spans):
        raise ValueError(f"target requires both neighbors: {subtitle_id}")
    window_indices = (target_index - 1, target_index, target_index + 1)
    window_spans = [run.spans[index] for index in window_indices]
    subtitle_ids = [str(span["subtitle_id"]) for span in window_spans]
    original_ranges = tuple(
        (int(span["word_start"]), int(span["word_end"])) for span in window_spans
    )
    original_cuts = tuple(start for start, _end in original_ranges[1:])
    window_start = original_ranges[0][0]
    window_end = original_ranges[-1][1]
    previous_range = None
    next_range = None
    if window_indices[0] > 0:
        span = run.spans[window_indices[0] - 1]
        previous_range = (int(span["word_start"]), int(span["word_end"]))
    if window_indices[-1] + 1 < len(run.spans):
        span = run.spans[window_indices[-1] + 1]
        next_range = (int(span["word_start"]), int(span["word_end"]))

    baseline_plans = [
        _plan_range(run, start, end, current_id)
        for (start, end), current_id in zip(original_ranges, subtitle_ids)
    ]
    baseline_metrics = _aggregate_plan_metrics(baseline_plans)
    baseline_target_metrics = dict(baseline_plans[1]["metrics"])
    baseline_target_metrics["render_failure_count"] = int(
        baseline_plans[1]["status"] != "ok"
    )
    baseline_neighbor_metrics = _aggregate_plan_metrics(
        (baseline_plans[0], baseline_plans[2])
    )

    option_groups = [
        range(
            max(window_start + 1, cut - radius),
            min(window_end, cut + radius) + 1,
        )
        for cut in original_cuts
    ]
    examined = 0
    candidates = []
    for cuts in itertools.product(*option_groups):
        if tuple(sorted(cuts)) != tuple(cuts) or len(set(cuts)) != len(cuts):
            continue
        examined += 1
        ranges = _ranges_from_cuts(window_start, window_end, cuts)
        record = _candidate_record(
            run,
            editor,
            original_ranges,
            ranges,
            subtitle_ids,
            previous_range,
            next_range,
            original_cuts,
        )
        if record is None:
            continue
        target_plan = record["page_plans"][subtitle_id]
        target_metrics = dict(target_plan["metrics"])
        target_metrics["render_failure_count"] = 0
        neighbor_metrics = _aggregate_plan_metrics(
            (
                record["page_plans"][subtitle_ids[0]],
                record["page_plans"][subtitle_ids[2]],
            )
        )
        target_improved = _quality_vector(target_metrics) < _quality_vector(
            baseline_target_metrics
        )
        neighbors_not_worse = _not_worse(neighbor_metrics, baseline_neighbor_metrics)
        record["target_improved"] = target_improved
        record["neighbors_not_worse"] = neighbors_not_worse
        record["potential_joint_improvement"] = bool(
            target_improved and neighbors_not_worse
        )
        candidates.append(record)
    candidates.sort(
        key=lambda item: (
            not bool(item["potential_joint_improvement"]),
            tuple(item["rank"]),
        )
    )
    alternatives = [item for item in candidates if item["boundary_changed"]]
    return {
        "subtitle_id": subtitle_id,
        "window_ids": subtitle_ids,
        "original_ranges": [list(value) for value in original_ranges],
        "original_texts": [str(span["original"]) for span in window_spans],
        "baseline": {
            "page_plans": {
                current_id: plan
                for current_id, plan in zip(subtitle_ids, baseline_plans)
            },
            "metrics": baseline_metrics,
        },
        "examined_boundary_combinations": examined,
        "valid_combination_count": len(candidates),
        "original_combination_feasible": any(
            not item["boundary_changed"] for item in candidates
        ),
        "feasible_alternative_count": len(alternatives),
        "potential_improvement_count": sum(
            bool(item["potential_joint_improvement"]) for item in alternatives
        ),
        "best_candidates": alternatives[:top_k],
    }


def _saved_plan_signature(plan: Mapping[str, object]) -> tuple[tuple[int, int, int], ...]:
    return tuple(
        (
            int(page.get("word_start") or 0),
            int(page.get("word_end") or 0),
            int(page.get("english_font_size") or 0),
        )
        for page in plan.get("pages") or ()
    )


def _current_plan_signature(plan: Mapping[str, object]) -> tuple[tuple[int, int, int], ...]:
    return tuple(
        (
            int(page["word_start"]),
            int(page["word_end"]),
            int(page["font_size"]),
        )
        for page in plan.get("pages") or ()
    )


def _episode_current_plans(
    run: ArtifactRun,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    entries: list[tuple[page_planner.Cue, dict[str, object]]] = []
    failures: list[dict[str, object]] = []
    for span in run.spans:
        subtitle_id = str(span["subtitle_id"])
        timeline = run.timeline[subtitle_id]
        saved = run.saved_plans.get(subtitle_id) or {}
        cue = _cue_for_range(
            run,
            int(span["word_start"]),
            int(span["word_end"]),
            subtitle_id,
            chinese=str(saved.get("chinese") or span.get("translated") or ""),
            display_start_ms=int(timeline["start_ms"]),
            display_end_ms=int(timeline["end_ms"]),
        )
        bundle = page_planner._build_article_english_page_plan(
            cue,
            DRAW,
            _return_candidates=True,
        )
        if bundle.get("status") != "candidate_bundle":
            failures.append(
                {
                    "subtitle_id": subtitle_id,
                    "reason": str(bundle.get("status") or "render_structural_overflow"),
                    "errors": list(bundle.get("errors") or ()),
                }
            )
            continue
        entries.append((cue, bundle))

    selected = page_planner._select_article_page_plan_sequence(
        [bundle["candidates"] for _cue, bundle in entries]
    )
    if len(selected) != len(entries):
        failures.append(
            {
                "subtitle_id": "all",
                "reason": "display_page_sequence_unavailable",
                "errors": [],
            }
        )
        return {}, failures

    plans: dict[str, dict[str, object]] = {}
    for (cue, bundle), candidate in zip(entries, selected):
        candidate = page_planner._select_article_dominant_readability_candidate(
            cue,
            candidate,
            bundle.get("shadow_candidates") or (),
        )
        plan = page_planner._finalize_article_sequence_candidate(candidate, bundle)
        plan = page_planner._finalize_article_same_screen_layout(cue, DRAW, plan)
        pages = [_page_summary(page) for page in plan.get("pages") or ()]
        page_english = ScreenSubtitleEditor._word_tokens(
            " ".join(str(page["english"]) for page in pages)
        )
        cue_english = ScreenSubtitleEditor._word_tokens(cue.en)
        if [value.casefold() for value in page_english] != [
            value.casefold() for value in cue_english
        ]:
            failures.append(
                {
                    "subtitle_id": cue.subtitle_id,
                    "reason": "page_english_coverage_changed",
                    "errors": [],
                }
            )
            continue
        plans[str(cue.subtitle_id)] = {
            "status": "ok",
            "errors": [],
            "pages": pages,
            "metrics": _plan_metrics(pages),
        }
    return plans, failures


def _replay_passing_guard(run: ArtifactRun) -> dict[str, object]:
    failures = []
    changes = []
    replay_plans, episode_failures = _episode_current_plans(run)
    failures.extend(episode_failures)
    for span in run.spans:
        subtitle_id = str(span["subtitle_id"])
        saved = run.saved_plans.get(subtitle_id)
        if saved is None:
            failures.append({"subtitle_id": subtitle_id, "reason": "saved_plan_missing"})
            continue
        replay = replay_plans.get(subtitle_id)
        if replay is None:
            if not any(item.get("subtitle_id") == subtitle_id for item in failures):
                failures.append(
                    {"subtitle_id": subtitle_id, "reason": "replay_plan_missing"}
                )
            continue
        if _current_plan_signature(replay) != _saved_plan_signature(saved):
            changes.append(
                {
                    "subtitle_id": subtitle_id,
                    "saved": [list(value) for value in _saved_plan_signature(saved)],
                    "replay": [list(value) for value in _current_plan_signature(replay)],
                }
            )
    failed_ids = {
        str(item.get("subtitle_id") or "")
        for item in failures
        if str(item.get("subtitle_id") or "") not in {"", "all"}
    }
    return {
        "parent_count": len(run.spans),
        "pass_count": len(run.spans) - len(failed_ids),
        "failure_count": len(failures),
        "signature_change_count": len(changes),
        "failures": failures,
        "signature_changes": changes,
    }


def audit(
    artifact_dir: Path,
    *,
    subtitle_ids: Sequence[str],
    radius: int = 8,
    top_k: int = 3,
    guard_artifact_dir: Path | None = None,
) -> dict[str, object]:
    if radius < 0:
        raise ValueError("radius must be non-negative")
    if top_k < 1:
        raise ValueError("top_k must be at least one")
    started = time.perf_counter()
    run = _load_run(artifact_dir)
    editor, speaker_evidence = _make_editor(run)
    targets = [
        _compare_target(
            run,
            editor,
            str(subtitle_id),
            radius=radius,
            top_k=top_k,
        )
        for subtitle_id in subtitle_ids
    ]
    guard = None
    if guard_artifact_dir is not None:
        guard = _replay_passing_guard(_load_run(guard_artifact_dir))
    guard_passed = bool(
        guard is None
        or (
            not int(guard["failure_count"])
            and not int(guard["signature_change_count"])
        )
    )
    return {
        "schema_version": 1,
        "experiment": "offline-pre-id-boundary-and-real-page-feasibility-v1",
        "status": "complete" if guard_passed else "guard_failed",
        "artifact_dir": str(run.artifact_dir),
        "word_ledger_hash": run.ledger_hash,
        "word_count": len(run.words),
        "parent_count": len(run.spans),
        "target_count": len(targets),
        "word_radius": radius,
        "timing_basis": "unchanged_word_ledger_envelopes",
        "speaker_evidence_available": speaker_evidence,
        "translation_evaluated": False,
        "api_calls": 0,
        "production_files_modified": False,
        "artifact_files_modified": False,
        "targets": targets,
        "summary": {
            "targets_with_feasible_candidate": sum(
                int(target["feasible_alternative_count"]) > 0 for target in targets
            ),
            "targets_with_potential_improvement": sum(
                int(target["potential_improvement_count"]) > 0 for target in targets
            ),
            "examined_boundary_combinations": sum(
                int(target["examined_boundary_combinations"]) for target in targets
            ),
            "feasible_boundary_combinations": sum(
                int(target["feasible_alternative_count"]) for target in targets
            ),
        },
        "passing_guard": guard,
        "limits": [
            "The experiment validates English boundaries, word timing, and real fixed-font page geometry only.",
            "Changed parent boundaries invalidate existing Chinese ownership, so translation and page-Chinese quality are intentionally not scored.",
            "A potential candidate is evidence for a production A/B test, not permission to change stable mode.",
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _ensure_report_outside_artifact(report_path: Path, artifact_dir: Path) -> None:
    report = report_path.resolve()
    artifact = artifact_dir.resolve()
    try:
        report.relative_to(artifact)
    except ValueError:
        return
    raise ValueError("report output must be outside the immutable artifact directory")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--subtitle-id", action="append", default=[])
    parser.add_argument("--word-radius", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--guard-artifact-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    subtitle_ids = tuple(args.subtitle_id or DEFAULT_TARGET_IDS)
    report = audit(
        args.artifact_dir,
        subtitle_ids=subtitle_ids,
        radius=args.word_radius,
        top_k=args.top_k,
        guard_artifact_dir=args.guard_artifact_dir,
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
                "summary": report["summary"],
                "passing_guard": report["passing_guard"],
                "elapsed_seconds": report["elapsed_seconds"],
                "output": str(args.output.resolve()) if args.output else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
