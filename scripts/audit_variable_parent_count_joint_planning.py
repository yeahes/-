"""Test k-1/k+1 parent counts in a bounded pre-ID subtitle window.

The planner is read-only. It keeps the authoritative word ledger and timing,
uses production grammar/page gates, and assigns only provisional experiment
IDs. Optional model calls translate the selected provisional parents and page
projections without touching production caches or artifacts.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.subtitle_processor.stable_display_page_contract import (
    build_display_page_contract,
)
from app.core.utils.json_repair import loads as repair_json_loads
from app.core.utils.podcast_learning_video import current_llm_config
from scripts import audit_pre_id_joint_page_feasibility as fixed_count
from scripts import experiment_fixed_parent_bilingual_pages as bilingual


DEFAULT_TARGET_IDS = fixed_count.DEFAULT_TARGET_IDS
MIN_PARENT_WORDS = 4
MAX_PARENT_WORDS = 19


def _partitions(
    window_start: int,
    window_end: int,
    parent_count: int,
    *,
    minimum_words: int = MIN_PARENT_WORDS,
    maximum_words: int = MAX_PARENT_WORDS,
    baseline_ranges: Sequence[tuple[int, int]] = (),
) -> Iterable[tuple[tuple[int, int], ...]]:
    """Enumerate exact contiguous partitions with bounded parent lengths."""
    total_words = window_end - window_start + 1
    baseline_range_set = set(baseline_ranges)
    if (
        parent_count < 1
        or (
            not baseline_range_set
            and (
                total_words < parent_count * minimum_words
                or total_words > parent_count * maximum_words
            )
        )
    ):
        return
    for cuts in itertools.combinations(
        range(window_start + 1, window_end + 1),
        parent_count - 1,
    ):
        ranges = fixed_count._ranges_from_cuts(window_start, window_end, cuts)
        counts = [end - start + 1 for start, end in ranges]
        if all(
            current_range in baseline_range_set
            or minimum_words <= count <= maximum_words
            for current_range, count in zip(ranges, counts)
        ):
            yield ranges


def _new_parent_ids(target_id: str, parent_count: int) -> list[str]:
    stem = re.sub(r"[^A-Za-z0-9]", "", target_id) or "TARGET"
    return [f"{stem}.V{index:02d}" for index in range(1, parent_count + 1)]


def _variable_count_gate(
    editor: ScreenSubtitleEditor,
    old_items: Sequence[Any],
    new_items: Sequence[Any],
    *,
    previous_item: Any | None,
    next_item: Any | None,
) -> dict[str, Any]:
    """Validate only ranges and boundaries changed by a count migration.

    The production repair gate correctly revalidates every output item for a
    normal replacement, but that makes an unchanged pre-existing short answer
    veto an otherwise independent split in another parent. This experiment
    keeps unchanged ranges as baseline evidence and validates every changed
    range plus every new boundary with the same production predicates.
    """
    reasons: list[str] = []
    old_ranges = {
        (int(item.word_start), int(item.word_end))
        for item in old_items
        if item.word_start is not None and item.word_end is not None
    }
    if editor._items_word_tokens(old_items) != editor._items_word_tokens(new_items):
        reasons.append("word_order_changed")
    if editor._items_word_range(old_items) != editor._items_word_range(new_items):
        reasons.append("word_coverage_changed")
    old_anchors = editor._strong_sentence_anchor_pairs(old_items)
    new_boundaries = editor._pre_id_boundary_pairs(new_items)
    removed_anchors = sorted(old_anchors - new_boundaries)

    old_context = list(old_items)
    if previous_item is not None:
        old_context.insert(0, previous_item)
    if next_item is not None:
        old_context.append(next_item)
    old_context_boundaries = editor._pre_id_boundary_pairs(old_context)
    for left, right in zip(new_items, new_items[1:]):
        if not editor._items_are_continuous(left, right):
            reasons.append("non_continuous_word_range")
        if editor._items_cross_speaker(left, right):
            reasons.append("speaker_change")
        evaluation = editor._evaluate_item_pair_for_final_boundary(left, right)
        reasons.extend(evaluation.get("hard_issues") or [])
    edge_pairs = []
    if previous_item is not None and new_items:
        edge_pairs.append((previous_item, new_items[0]))
    if next_item is not None and new_items:
        edge_pairs.append((new_items[-1], next_item))
    for left, right in edge_pairs:
        if editor._pre_id_boundary_pair(left, right) in old_context_boundaries:
            continue
        evaluation = editor._evaluate_item_boundary(left, right)
        reasons.extend(evaluation.get("hard_issues") or [])

    for index, item in enumerate(new_items):
        item_range = (int(item.word_start), int(item.word_end))
        if item_range in old_ranges:
            continue
        item_previous = new_items[index - 1] if index else previous_item
        item_next = (
            new_items[index + 1]
            if index + 1 < len(new_items)
            else next_item
        )
        fragment = editor._evaluate_final_display_fragment(
            item,
            item_previous,
            item_next,
        )
        fragment_issues = list(fragment.get("hard_fragment_issues") or [])
        # A subtitle parent may be one phrase inside a continuing sentence.
        # Boundary legality already rejects dependency damage; only fragments
        # that are visibly dangling on their own remain hard in this probe.
        hard_fragment_issues = {
            "pronoun_only_fragment",
            "standalone_connector_fragment",
            "trailing_auxiliary_fragment",
            "trailing_possessive_fragment",
            "trailing_quantifier_fragment",
            "trailing_modifier_fragment",
            "trailing_protected_named_phrase_fragment",
            "trailing_protected_phrasal_fragment",
            "open_subordinate_prefix_fragment",
            "right_orphaned_finite_predicate",
        }
        reasons.extend(
            issue for issue in fragment_issues if issue in hard_fragment_issues
        )
        if editor._is_ordinary_one_word_fragment(item.original):
            reasons.append("ordinary_one_word_fragment")
        if (
            editor._word_count(item.original) > editor.max_english_words
            and not editor._is_allowed_pre_id_item_structural_overflow(item)
        ):
            reasons.append("max_english_words_exceeded")
    reasons = list(dict.fromkeys(reasons))
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "removed_sentence_anchors": [list(value) for value in removed_anchors],
        "unchanged_range_count": sum(
            (int(item.word_start), int(item.word_end)) in old_ranges
            for item in new_items
        ),
    }


def _candidate_record(
    run: fixed_count.ArtifactRun,
    editor: ScreenSubtitleEditor,
    original_ranges: Sequence[tuple[int, int]],
    candidate_ranges: Sequence[tuple[int, int]],
    *,
    target_id: str,
    previous_range: tuple[int, int] | None,
    next_range: tuple[int, int] | None,
    original_cuts: Sequence[int],
    plan_cache: dict[tuple[int, int], dict[str, Any]],
    rejection_counts: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    def reject(reason: str) -> None:
        if rejection_counts is not None:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    old_items = [
        editor._item_from_word_span(start, end) for start, end in original_ranges
    ]
    new_items = [
        editor._item_from_word_span(start, end) for start, end in candidate_ranges
    ]
    if any(item is None for item in [*old_items, *new_items]):
        reject("word_span_item_missing")
        return None
    old_items = [item for item in old_items if item is not None]
    new_items = [item for item in new_items if item is not None]
    previous_item = (
        editor._item_from_word_span(*previous_range) if previous_range else None
    )
    next_item = editor._item_from_word_span(*next_range) if next_range else None
    candidate_cuts = [start for start, _end in candidate_ranges[1:]]

    removed_long_pauses: list[dict[str, Any]] = []
    for left, right in zip(old_items, old_items[1:]):
        pause_ms = editor._boundary_pause_ms(left, right)
        if (
            pause_ms is not None
            and pause_ms >= 450
            and int(right.word_start) not in candidate_cuts
        ):
            removed_long_pauses.append(
                {
                    "left_word_end": int(left.word_end),
                    "right_word_start": int(right.word_start),
                    "pause_ms": int(pause_ms),
                }
            )
    if any(len(fixed_count._speaker_set(editor, item)) > 1 for item in new_items):
        reject("candidate_crosses_speaker")
        return None

    gate = _variable_count_gate(
        editor,
        old_items,
        new_items,
        previous_item=previous_item,
        next_item=next_item,
    )
    if not gate.get("accepted"):
        reasons = list(gate.get("reasons") or ["pre_id_gate_rejected"])
        for reason in reasons:
            reject(f"pre_id:{reason}")
        return None
    word_counts = [editor._word_count(item.original) for item in new_items]
    original_range_set = set(original_ranges)
    changed_parent_indices = [
        index
        for index, current_range in enumerate(candidate_ranges)
        if tuple(current_range) not in original_range_set
    ]
    if any(
        word_counts[index] < MIN_PARENT_WORDS
        or word_counts[index] > MAX_PARENT_WORDS
        for index in changed_parent_indices
    ):
        reject("parent_word_count_outside_experiment_bounds")
        return None
    if any(
        word_counts[index] > 16
        and not editor._is_complete_pre_id_structural_overflow_range(
            *candidate_ranges[index]
        )
        for index in changed_parent_indices
    ):
        reject("parent_over_16_without_structural_exception")
        return None

    parent_ids = _new_parent_ids(target_id, len(candidate_ranges))
    plans = []
    for (start, end), parent_id in zip(candidate_ranges, parent_ids):
        key = (start, end)
        if key not in plan_cache:
            plan_cache[key] = fixed_count._plan_range(
                run,
                start,
                end,
                parent_id,
            )
        plans.append(plan_cache[key])
    if any(plan.get("status") != "ok" for plan in plans):
        reject("page_plan_failed")
        return None

    metrics = fixed_count._aggregate_plan_metrics(plans)
    if any(
        int(plans[index]["metrics"].get("min_words") or 0) < 5
        for index in changed_parent_indices
    ):
        reject("display_page_below_five_words")
        return None
    boundary_evidence = []
    for left, right in zip(new_items, new_items[1:]):
        evaluation = editor._evaluate_item_pair_for_final_boundary(left, right)
        if not evaluation.get("legal"):
            reject("final_boundary_illegal")
            return None
        boundary_evidence.append(
            {
                "pause_ms": evaluation.get("pause_ms"),
                "soft_issues": list(evaluation.get("soft_issues") or []),
                "boundary_score": evaluation.get("boundary_score"),
                "speaker_change": bool(editor._items_cross_speaker(left, right)),
            }
        )
    shift_distance = sum(
        min(abs(cut - old_cut) for old_cut in original_cuts)
        for cut in candidate_cuts
    )
    return {
        "parent_count": len(candidate_ranges),
        "parent_ids": parent_ids,
        "ranges": [list(value) for value in candidate_ranges],
        "cuts": candidate_cuts,
        "texts": [item.original for item in new_items],
        "word_counts": word_counts,
        "changed_parent_indices": changed_parent_indices,
        "boundary_evidence": boundary_evidence,
        "page_plans": {
            parent_id: plan for parent_id, plan in zip(parent_ids, plans)
        },
        "metrics": metrics,
        "shift_distance_words": shift_distance,
        "word_coverage_preserved": True,
        "word_order_preserved": True,
        "word_timestamps_preserved": True,
        "speaker_ownership_preserved": True,
        "candidate_gate": gate,
        "removed_sentence_anchor_count": len(
            gate.get("removed_sentence_anchors") or []
        ),
        "removed_long_pauses": removed_long_pauses,
        "removed_long_pause_count": len(removed_long_pauses),
    }


def _materially_improves(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> bool:
    candidate_failures = int(candidate.get("render_failure_count") or 0)
    baseline_failures = int(baseline.get("render_failure_count") or 0)
    if candidate_failures:
        return False
    if int(candidate.get("pages_over_two_lines") or 0):
        return False
    if int(candidate.get("max_words") or 0) > 16:
        return False
    candidate_min_words = int(candidate.get("min_words") or 0)
    baseline_min_words = int(baseline.get("min_words") or 0)
    if candidate_min_words < 5 and candidate_min_words <= baseline_min_words:
        return False
    if baseline_failures > candidate_failures:
        return bool(
            int(candidate.get("review_boundaries") or 0)
            <= int(baseline.get("review_boundaries") or 0) + 2
        )
    return bool(
        fixed_count._not_worse(candidate, baseline)
        and fixed_count._quality_vector(candidate)
        < fixed_count._quality_vector(baseline)
    )


def _compare_target(
    run: fixed_count.ArtifactRun,
    editor: ScreenSubtitleEditor,
    subtitle_id: str,
    *,
    top_k: int,
) -> dict[str, Any]:
    id_to_index = {
        str(span["subtitle_id"]): index for index, span in enumerate(run.spans)
    }
    if subtitle_id not in id_to_index:
        raise ValueError(f"unknown subtitle ID: {subtitle_id}")
    target_index = id_to_index[subtitle_id]
    if target_index == 0 or target_index + 1 >= len(run.spans):
        raise ValueError(f"target requires both neighbors: {subtitle_id}")
    indices = (target_index - 1, target_index, target_index + 1)
    spans = [run.spans[index] for index in indices]
    original_ids = [str(span["subtitle_id"]) for span in spans]
    original_ranges = tuple(
        (int(span["word_start"]), int(span["word_end"])) for span in spans
    )
    original_cuts = tuple(start for start, _end in original_ranges[1:])
    window_start = original_ranges[0][0]
    window_end = original_ranges[-1][1]
    previous_range = None
    next_range = None
    if indices[0] > 0:
        previous = run.spans[indices[0] - 1]
        previous_range = (int(previous["word_start"]), int(previous["word_end"]))
    if indices[-1] + 1 < len(run.spans):
        following = run.spans[indices[-1] + 1]
        next_range = (int(following["word_start"]), int(following["word_end"]))

    baseline_plans = [
        fixed_count._plan_range(run, start, end, parent_id)
        for (start, end), parent_id in zip(original_ranges, original_ids)
    ]
    baseline_metrics = fixed_count._aggregate_plan_metrics(baseline_plans)
    plan_cache: dict[tuple[int, int], dict[str, Any]] = {
        current_range: plan
        for current_range, plan in zip(original_ranges, baseline_plans)
    }
    examined_by_count: dict[str, int] = {}
    feasible_by_count: dict[str, int] = {}
    rejection_counts: dict[str, int] = {}
    candidates = []
    for parent_count in (2, 4):
        examined = 0
        feasible = 0
        for ranges in _partitions(
            window_start,
            window_end,
            parent_count,
            baseline_ranges=original_ranges,
        ):
            examined += 1
            record = _candidate_record(
                run,
                editor,
                original_ranges,
                ranges,
                target_id=subtitle_id,
                previous_range=previous_range,
                next_range=next_range,
                original_cuts=original_cuts,
                plan_cache=plan_cache,
                rejection_counts=rejection_counts,
            )
            if record is None:
                continue
            feasible += 1
            record["material_improvement"] = _materially_improves(
                record["metrics"],
                baseline_metrics,
            )
            candidates.append(record)
        examined_by_count[str(parent_count)] = examined
        feasible_by_count[str(parent_count)] = feasible
    candidates.sort(
        key=lambda record: (
            not bool(record["material_improvement"]),
            fixed_count._quality_vector(record["metrics"]),
            int(record["removed_sentence_anchor_count"]),
            int(record["removed_long_pause_count"]),
            int(record["shift_distance_words"]),
            abs(int(record["parent_count"]) - 3),
        )
    )
    improvements = [
        record for record in candidates if bool(record["material_improvement"])
    ]
    return {
        "subtitle_id": subtitle_id,
        "window_ids": original_ids,
        "window_range": [window_start, window_end],
        "original_ranges": [list(value) for value in original_ranges],
        "original_texts": [str(span.get("original") or "") for span in spans],
        "baseline": {
            "page_plans": {
                parent_id: plan
                for parent_id, plan in zip(original_ids, baseline_plans)
            },
            "metrics": baseline_metrics,
        },
        "examined_by_parent_count": examined_by_count,
        "feasible_by_parent_count": feasible_by_count,
        "rejection_counts": dict(
            sorted(
                rejection_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "material_improvement_count": len(improvements),
        "best_candidates": improvements[:top_k],
    }


def _translate_candidate_parents(
    candidate: Mapping[str, Any],
    *,
    timeout: int,
) -> dict[str, Any]:
    base_url, api_key, model = current_llm_config()
    if not base_url or not api_key or not model:
        return {"status": "SKIPPED", "reason": "configured_llm_missing"}
    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_KEY"] = api_key
    editor = ScreenSubtitleEditor(
        model=model,
        full_translation_model=model,
        allocation_review_model=model,
        timeout=timeout,
        translation_request_budget=8,
        translation_request_max_attempts=2,
    )
    expected = [
        {"candidate_parent_id": parent_id, "source_english": english}
        for parent_id, english in zip(candidate["parent_ids"], candidate["texts"])
    ]
    prompt = (
        "Return JSON only as {\"parents\":[{\"candidate_parent_id\":\"...\","
        "\"source_english\":\"exact source\",\"zh\":\"...\"}]}. "
        "Return exactly one row for every supplied ID in order. Copy source_english "
        "exactly. Translate the full adjacent window into concise, natural Simplified "
        "Chinese subtitles. Each Chinese row must own only its English row's meaning, "
        "while all rows must read continuously. Preserve names, numbers, negation, "
        "modality, comparison, cause, and stance. Do not summarize or add facts."
    )
    attempts = []
    response_data = None
    error = ""
    for attempt in range(1, 3):
        started = time.perf_counter()
        try:
            response = editor.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(expected, ensure_ascii=False)},
                ],
                temperature=0.2,
                timeout=timeout,
            )
            response_data = repair_json_loads(response.choices[0].message.content)
            attempts.append(
                {"attempt": attempt, "elapsed_seconds": round(time.perf_counter() - started, 3), "error": ""}
            )
            error = ""
            break
        except Exception as exc:
            error = str(exc)
            attempts.append(
                {"attempt": attempt, "elapsed_seconds": round(time.perf_counter() - started, 3), "error": error}
            )
    rows = list((response_data or {}).get("parents") or []) if isinstance(response_data, Mapping) else []
    expected_by_id = {item["candidate_parent_id"]: item["source_english"] for item in expected}
    returned_ids = [str(row.get("candidate_parent_id") or "") for row in rows if isinstance(row, Mapping)]
    translations: dict[str, str] = {}
    validation_errors = []
    if returned_ids != list(expected_by_id):
        validation_errors.append("candidate_parent_id_order_or_cardinality_mismatch")
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        parent_id = str(row.get("candidate_parent_id") or "")
        source_echo = " ".join(str(row.get("source_english") or "").split())
        chinese = re.sub(r"\s+", "", str(row.get("zh") or ""))
        if parent_id not in expected_by_id:
            validation_errors.append(f"unknown_parent:{parent_id}")
            continue
        if source_echo != " ".join(expected_by_id[parent_id].split()):
            validation_errors.append(f"source_echo_mismatch:{parent_id}")
        if not re.search(r"[\u4e00-\u9fff]", chinese):
            validation_errors.append(f"chinese_missing:{parent_id}")
        translations[parent_id] = chinese
    if set(translations) != set(expected_by_id):
        validation_errors.append("translation_parent_set_incomplete")
    return {
        "status": "PASS" if not error and not validation_errors else "ERROR",
        "model": model,
        "attempts": attempts,
        "error": error,
        "validation_errors": validation_errors,
        "translations": translations,
    }


def _page_contract_for_candidate(
    artifact_dir: Path,
    candidate: Mapping[str, Any],
    translations: Mapping[str, str],
) -> dict[str, Any] | None:
    saved = fixed_count._read_json(artifact_dir / "display-page-translations.json")
    parents = []
    for parent_id, english, current_range in zip(
        candidate["parent_ids"],
        candidate["texts"],
        candidate["ranges"],
    ):
        plan = candidate["page_plans"][parent_id]
        pages = list(plan.get("pages") or [])
        if len(pages) < 2:
            continue
        parents.append(
            {
                "parent_subtitle_id": parent_id,
                "english": english,
                "chinese": str(translations.get(parent_id) or ""),
                "word_start": int(current_range[0]),
                "word_end": int(current_range[1]),
                "pages": [
                    {
                        "display_page_id": f"{parent_id}.P{index:02d}",
                        "word_start": int(page["word_start"]),
                        "word_end": int(page["word_end"]),
                        "english": str(page["english"]),
                        "start_ms": int(page["start_ms"]),
                        "end_ms": int(page["end_ms"]),
                    }
                    for index, page in enumerate(pages, 1)
                ],
            }
        )
    if not parents:
        return None
    return build_display_page_contract(
        parents,
        layout_profile=dict(saved.get("layout_profile") or {}),
    )


def _evaluate_bilingual_candidates(
    artifact_dir: Path,
    targets: Sequence[dict[str, Any]],
    *,
    timeout: int,
) -> int:
    api_attempt_count = 0
    for target in targets:
        candidates = list(target.get("best_candidates") or [])
        if not candidates:
            continue
        candidate = candidates[0]
        parent_translation = _translate_candidate_parents(candidate, timeout=timeout)
        api_attempt_count += len(parent_translation.get("attempts") or [])
        candidate["parent_translation"] = parent_translation
        if parent_translation.get("status") != "PASS":
            candidate["page_translation"] = {
                "status": "SKIPPED",
                "reason": "parent_translation_invalid",
            }
            candidate["bilingual_candidate_complete"] = False
            continue
        page_contract = _page_contract_for_candidate(
            artifact_dir,
            candidate,
            parent_translation["translations"],
        )
        if page_contract is None:
            page_translation = {
                "status": "NOT_REQUIRED",
                "api_attempt_count": 0,
                "pages_by_parent": {},
            }
        else:
            page_translation = bilingual._request_page_chinese(
                page_contract,
                timeout=timeout,
            )
        api_attempt_count += int(page_translation.get("api_attempt_count") or 0)
        candidate["page_translation"] = page_translation
        candidate["bilingual_candidate_complete"] = bool(
            parent_translation.get("status") == "PASS"
            and page_translation.get("status") in {"PASS", "NOT_REQUIRED"}
        )
    return api_attempt_count


def audit(
    artifact_dir: Path,
    *,
    subtitle_ids: Sequence[str],
    top_k: int = 2,
    translate_best: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    started = time.perf_counter()
    run = fixed_count._load_run(artifact_dir)
    editor, speaker_evidence = fixed_count._make_editor(run)
    targets = [
        _compare_target(run, editor, subtitle_id, top_k=top_k)
        for subtitle_id in subtitle_ids
    ]
    api_attempt_count = 0
    if translate_best:
        api_attempt_count = _evaluate_bilingual_candidates(
            run.artifact_dir,
            targets,
            timeout=timeout,
        )
    return {
        "schema_version": 1,
        "experiment": "offline-variable-parent-count-joint-planning-v1",
        "artifact_dir": str(run.artifact_dir),
        "word_ledger_hash": run.ledger_hash,
        "word_count": len(run.words),
        "parent_count": len(run.spans),
        "target_count": len(targets),
        "tested_parent_counts": [2, 4],
        "speaker_evidence_available": speaker_evidence,
        "translation_evaluated": bool(translate_best),
        "api_attempt_count": api_attempt_count,
        "production_files_modified": False,
        "artifact_files_modified": False,
        "production_cache_modified": False,
        "targets": targets,
        "summary": {
            "targets_with_material_improvement": sum(
                int(target["material_improvement_count"]) > 0
                for target in targets
            ),
            "bilingual_complete_target_count": sum(
                bool((target.get("best_candidates") or [{}])[0].get("bilingual_candidate_complete"))
                for target in targets
                if target.get("best_candidates")
            ),
            "examined_partition_count": sum(
                sum(int(value) for value in target["examined_by_parent_count"].values())
                for target in targets
            ),
            "feasible_partition_count": sum(
                sum(int(value) for value in target["feasible_by_parent_count"].values())
                for target in targets
            ),
        },
        "limits": [
            "Provisional parent IDs are experiment-only and never replace frozen production IDs.",
            "A candidate without speaker evidence cannot be approved for production even when its grammar and page checks pass.",
            "Experimental translation validates fixed source echo and project page contracts but is not a production cache artifact.",
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--subtitle-id", action="append", default=[])
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--translate-best", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(
        args.artifact_dir,
        subtitle_ids=tuple(args.subtitle_id or DEFAULT_TARGET_IDS),
        top_k=max(1, int(args.top_k)),
        translate_best=bool(args.translate_best),
        timeout=max(10, int(args.timeout)),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "api_attempt_count": report["api_attempt_count"],
                "elapsed_seconds": report["elapsed_seconds"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
