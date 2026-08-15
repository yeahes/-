"""ID-addressable final subtitle timing derived from the frozen word ledger.

The stable subtitle pipeline freezes English cue word ranges before Chinese
translation.  This module is the sole owner of the final cue timeline: it
derives each cue's display range from its own first and last ledger words and
validates the result without looking up a cue by list position or text.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence

from app.core.subtitle_processor.word_timing_trust import (
    find_implausible_word_timing_runs,
)


SUBTITLE_ID_RE = re.compile(r"S\d{4}")
TARGET_DISPLAY_DURATION_MS = 700
HARD_MIN_DISPLAY_DURATION_MS = 150


def reconcile_frozen_word_ledger(words: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Make the authoritative word ledger monotonic at overlapping boundaries.

    Stable-ts and forced aligners may return two adjacent word envelopes that
    overlap by a few milliseconds.  A cue-level trim would hide that defect by
    cutting one cue inside its own speech.  Instead, this function moves only
    the shared boundary between the two words and records the adjustment.
    """
    errors: List[Dict[str, Any]] = []
    timing_issues = find_implausible_word_timing_runs(words)
    if timing_issues:
        errors.append(
            {
                "code": "final_timeline_word_timing_density_invalid",
                "issues": timing_issues,
            }
        )
        return {"words": [], "reconciliations": [], "errors": errors}
    indexed = _word_index(words, errors)
    expected_ids = set(range(len(words)))
    if set(indexed) != expected_ids:
        errors.append(
            {
                "code": "final_timeline_word_id_set_mismatch",
                "expected_word_count": len(expected_ids),
                "returned_word_count": len(indexed),
            }
        )
        return {"words": [], "reconciliations": [], "errors": _unique_errors(errors)}

    result = [dict(indexed[word_id]) for word_id in range(len(words))]
    reconciliations: List[Dict[str, Any]] = []
    for left, right in zip(result, result[1:]):
        left_end = int(left["end_ms"])
        right_start = int(right["start_ms"])
        if left_end <= right_start:
            continue
        lower_bound = int(left["start_ms"]) + 1
        upper_bound = int(right["end_ms"]) - 1
        proposed = (left_end + right_start) // 2
        if lower_bound > upper_bound:
            errors.append(
                {
                    "code": "final_timeline_word_overlap_unresolvable",
                    "left_word_id": left["word_id"],
                    "right_word_id": right["word_id"],
                    "left_word_range": [left["start_ms"], left_end],
                    "right_word_range": [right_start, right["end_ms"]],
                }
            )
            continue
        boundary = min(upper_bound, max(lower_bound, proposed))
        left["end_ms"] = boundary
        right["start_ms"] = boundary
        marker = "final-ledger-boundary-reconciled"
        left["alignment_source"] = _combined_alignment_source(left["alignment_source"], marker)
        right["alignment_source"] = _combined_alignment_source(right["alignment_source"], marker)
        reconciliations.append(
            {
                "code": "final_timeline_word_boundary_reconciled",
                "left_word_id": left["word_id"],
                "right_word_id": right["word_id"],
                "old_left_end_ms": left_end,
                "old_right_start_ms": right_start,
                "new_boundary_ms": boundary,
            }
        )
    return {
        "words": result,
        "reconciliations": reconciliations,
        "errors": _unique_errors(errors),
    }


def derive_final_cue_timeline(
    cues: Sequence[Mapping[str, Any]],
    words: Sequence[Mapping[str, Any]],
    *,
    expected_subtitle_ids: Sequence[str],
    lead_in_ms: int,
    tail_padding_ms: int,
) -> Dict[str, Any]:
    """Derive final cue times from frozen word ranges.

    The returned records are keyed by ``subtitle_id`` and contain their own
    word envelope.  A shared display boundary may remove padding overlap, but
    it never cuts either cue inside that envelope.
    """
    errors: List[Dict[str, Any]] = []
    expected_ids = [str(value or "") for value in expected_subtitle_ids]
    word_by_id = _word_index(words, errors)
    cue_by_id: Dict[str, Mapping[str, Any]] = {}
    returned_ids: List[str] = []

    for cue in cues:
        subtitle_id = str(cue.get("subtitle_id") or "")
        returned_ids.append(subtitle_id)
        if not SUBTITLE_ID_RE.fullmatch(subtitle_id) or subtitle_id == "S0000":
            errors.append(
                {
                    "code": "final_timeline_subtitle_id_invalid",
                    "subtitle_id": subtitle_id,
                    "message": "Final cue timeline contains a missing or synthetic subtitle_id.",
                }
            )
            continue
        if subtitle_id in cue_by_id:
            errors.append(
                {
                    "code": "final_timeline_subtitle_id_duplicate",
                    "subtitle_id": subtitle_id,
                    "message": "Final cue timeline contains a duplicate subtitle_id.",
                }
            )
            continue
        cue_by_id[subtitle_id] = cue

    expected_set = set(expected_ids)
    returned_set = set(returned_ids)
    missing_ids = [subtitle_id for subtitle_id in expected_ids if subtitle_id not in returned_set]
    unknown_ids = [subtitle_id for subtitle_id in returned_ids if subtitle_id not in expected_set]
    if missing_ids:
        errors.append(
            {
                "code": "final_timeline_subtitle_id_missing",
                "subtitle_ids": missing_ids,
                "message": "Final cue timeline is missing frozen subtitle IDs.",
            }
        )
    if unknown_ids:
        errors.append(
            {
                "code": "final_timeline_subtitle_id_unknown",
                "subtitle_ids": unknown_ids,
                "message": "Final cue timeline contains subtitle IDs outside the frozen set.",
            }
        )

    records: List[Dict[str, Any]] = []
    for subtitle_id in expected_ids:
        cue = cue_by_id.get(subtitle_id)
        if cue is None:
            continue
        record = _cue_record(
            cue,
            word_by_id,
            lead_in_ms=max(0, int(lead_in_ms)),
            tail_padding_ms=max(0, int(tail_padding_ms)),
            errors=errors,
        )
        if record is not None:
            records.append(record)

    boundary_repairs = _resolve_display_padding_overlaps(records, errors)
    boundary_repairs.extend(
        _extend_short_display_ranges(
            records,
            target_duration_ms=TARGET_DISPLAY_DURATION_MS,
        )
    )
    validation = validate_final_cue_timeline(
        records,
        expected_subtitle_ids=expected_ids,
        words=words,
        prior_errors=errors,
    )
    return {
        "schema_version": 1,
        "source": "frozen_word_ledger",
        "expected_subtitle_ids": expected_ids,
        "returned_subtitle_ids": returned_ids,
        "records": records,
        "boundary_reconciliations": boundary_repairs,
        "validation": validation,
    }


def final_cue_timeline_artifact(
    cues: Sequence[Mapping[str, Any]],
    words: Sequence[Mapping[str, Any]],
    *,
    expected_subtitle_ids: Sequence[str],
    prior_errors: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Serialize and validate existing final cue times without rewriting them."""
    errors = [dict(item) for item in prior_errors or []]
    records: List[Dict[str, Any]] = []
    for cue in cues:
        records.append(
            {
                "subtitle_id": str(cue.get("subtitle_id") or ""),
                "word_start": cue.get("word_start"),
                "word_end": cue.get("word_end"),
                "word_envelope_start_ms": cue.get("word_envelope_start_ms"),
                "word_envelope_end_ms": cue.get("word_envelope_end_ms"),
                "start_ms": int(cue.get("start_ms") or 0),
                "end_ms": int(cue.get("end_ms") or 0),
                "word_alignment_sources": list(cue.get("word_alignment_sources") or []),
            }
        )
    validation = validate_final_cue_timeline(
        records,
        expected_subtitle_ids=expected_subtitle_ids,
        words=words,
        prior_errors=errors,
    )
    return {
        "schema_version": 1,
        "source": "frozen_word_ledger",
        "expected_subtitle_ids": [str(value or "") for value in expected_subtitle_ids],
        "returned_subtitle_ids": [record["subtitle_id"] for record in records],
        "records": records,
        "boundary_reconciliations": [],
        "validation": validation,
    }


def validate_final_cue_timeline(
    records: Sequence[Mapping[str, Any]],
    *,
    expected_subtitle_ids: Sequence[str],
    words: Sequence[Mapping[str, Any]],
    prior_errors: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Validate ID coverage, word spans, own-word coverage, and order."""
    errors = [dict(item) for item in prior_errors or []]
    expected_ids = [str(value or "") for value in expected_subtitle_ids]
    returned_ids = [str(record.get("subtitle_id") or "") for record in records]
    expected_set = set(expected_ids)
    returned_set = set(returned_ids)
    duplicate_ids = sorted(
        subtitle_id for subtitle_id in returned_set if returned_ids.count(subtitle_id) > 1
    )
    invalid_ids = [
        subtitle_id
        for subtitle_id in returned_ids
        if not SUBTITLE_ID_RE.fullmatch(subtitle_id) or subtitle_id == "S0000"
    ]
    missing_ids = [subtitle_id for subtitle_id in expected_ids if subtitle_id not in returned_set]
    unknown_ids = [subtitle_id for subtitle_id in returned_ids if subtitle_id not in expected_set]
    if duplicate_ids:
        errors.append({"code": "final_timeline_subtitle_id_duplicate", "subtitle_ids": duplicate_ids})
    if invalid_ids:
        errors.append({"code": "final_timeline_subtitle_id_invalid", "subtitle_ids": invalid_ids})
    if missing_ids:
        errors.append({"code": "final_timeline_subtitle_id_missing", "subtitle_ids": missing_ids})
    if unknown_ids:
        errors.append({"code": "final_timeline_subtitle_id_unknown", "subtitle_ids": unknown_ids})
    if returned_ids != expected_ids:
        errors.append(
            {
                "code": "final_timeline_subtitle_order_mismatch",
                "expected_subtitle_ids": expected_ids,
                "returned_subtitle_ids": returned_ids,
            }
        )

    word_by_id = _word_index(words, errors)
    expected_word_ids = set(range(len(words)))
    if set(word_by_id) != expected_word_ids:
        errors.append(
            {
                "code": "final_timeline_word_id_set_mismatch",
                "expected_word_count": len(expected_word_ids),
                "returned_word_count": len(word_by_id),
            }
        )
    previous_end = -1
    previous_subtitle_id = ""
    previous_word_end = -1
    covered_word_ids: List[int] = []
    for record in records:
        subtitle_id = str(record.get("subtitle_id") or "")
        start = int(record.get("start_ms") or 0)
        end = int(record.get("end_ms") or 0)
        word_start = _int_or_none(record.get("word_start"))
        word_end = _int_or_none(record.get("word_end"))
        envelope_start = _int_or_none(record.get("word_envelope_start_ms"))
        envelope_end = _int_or_none(record.get("word_envelope_end_ms"))
        if word_start is None or word_end is None or word_start > word_end:
            errors.append(
                {
                    "code": "final_timeline_word_range_invalid",
                    "subtitle_id": subtitle_id,
                    "word_start": word_start,
                    "word_end": word_end,
                }
            )
            continue
        first = word_by_id.get(word_start)
        last = word_by_id.get(word_end)
        missing_word_ids = [
            word_id for word_id in range(word_start, word_end + 1) if word_id not in word_by_id
        ]
        if first is None or last is None or missing_word_ids:
            errors.append(
                {
                    "code": "final_timeline_word_range_unknown",
                    "subtitle_id": subtitle_id,
                    "word_start": word_start,
                    "word_end": word_end,
                    "missing_word_ids": missing_word_ids,
                }
            )
            continue
        covered_word_ids.extend(range(word_start, word_end + 1))
        expected_envelope_start = int(first["start_ms"])
        expected_envelope_end = int(last["end_ms"])
        if envelope_start != expected_envelope_start or envelope_end != expected_envelope_end:
            errors.append(
                {
                    "code": "final_timeline_word_envelope_mismatch",
                    "subtitle_id": subtitle_id,
                    "expected_word_envelope": [expected_envelope_start, expected_envelope_end],
                    "actual_word_envelope": [envelope_start, envelope_end],
                }
            )
        if start > expected_envelope_start or end < expected_envelope_end:
            errors.append(
                {
                    "code": "final_timeline_word_envelope_uncovered",
                    "subtitle_id": subtitle_id,
                    "cue_range": [start, end],
                    "word_envelope": [expected_envelope_start, expected_envelope_end],
                }
            )
        if end <= start:
            errors.append(
                {
                    "code": "final_timeline_time_invalid",
                    "subtitle_id": subtitle_id,
                    "cue_range": [start, end],
                }
            )
        elif end - start < HARD_MIN_DISPLAY_DURATION_MS:
            errors.append(
                {
                    "code": "final_timeline_display_duration_invalid",
                    "subtitle_id": subtitle_id,
                    "cue_range": [start, end],
                    "duration_ms": end - start,
                    "minimum_duration_ms": HARD_MIN_DISPLAY_DURATION_MS,
                }
            )
        if previous_end > start:
            errors.append(
                {
                    "code": "final_timeline_overlap",
                    "left_subtitle_id": previous_subtitle_id,
                    "right_subtitle_id": subtitle_id,
                }
            )
        if previous_word_end >= 0 and word_start != previous_word_end + 1:
            errors.append(
                {
                    "code": "final_timeline_word_range_noncontiguous",
                    "subtitle_id": subtitle_id,
                    "previous_word_end": previous_word_end,
                    "word_start": word_start,
                }
            )
        previous_end = max(previous_end, end)
        previous_subtitle_id = subtitle_id
        previous_word_end = word_end

    covered_word_id_set = set(covered_word_ids)
    missing_ledger_word_ids = sorted(expected_word_ids - covered_word_id_set)
    duplicate_ledger_word_ids = sorted(
        word_id for word_id in covered_word_id_set if covered_word_ids.count(word_id) > 1
    )
    if missing_ledger_word_ids or duplicate_ledger_word_ids:
        errors.append(
            {
                "code": "final_timeline_word_coverage_incomplete",
                "missing_word_ids": missing_ledger_word_ids,
                "duplicate_word_ids": duplicate_ledger_word_ids,
                "expected_word_range": [0, len(words) - 1] if words else [],
                "covered_word_range": (
                    [min(covered_word_id_set), max(covered_word_id_set)]
                    if covered_word_id_set
                    else []
                ),
            }
        )

    unique_errors = _unique_errors(errors)
    return {
        "status": "ERROR" if unique_errors else "PASS",
        "error_count": len(unique_errors),
        "errors": unique_errors,
        "expected_subtitle_ids": expected_ids,
        "returned_subtitle_ids": returned_ids,
        "missing_subtitle_ids": missing_ids,
        "duplicate_subtitle_ids": duplicate_ids,
        "unknown_subtitle_ids": unknown_ids,
    }


def _word_index(words: Sequence[Mapping[str, Any]], errors: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for position, word in enumerate(words):
        word_id = _int_or_none(word.get("word_id"))
        if word_id is None:
            errors.append({"code": "final_timeline_word_id_missing", "position": position})
            continue
        if word_id in result:
            errors.append({"code": "final_timeline_word_id_duplicate", "word_id": word_id})
            continue
        start = int(word.get("start_ms") or 0)
        end = int(word.get("end_ms") or 0)
        if end < start:
            errors.append(
                {
                    "code": "final_timeline_word_time_invalid",
                    "word_id": word_id,
                    "word_range": [start, end],
                }
            )
        result[word_id] = {
            "word_id": word_id,
            "start_ms": start,
            "end_ms": max(start, end),
            "alignment_source": str(word.get("alignment_source") or "unknown"),
        }
    return result


def _cue_record(
    cue: Mapping[str, Any],
    word_by_id: Mapping[int, Mapping[str, Any]],
    *,
    lead_in_ms: int,
    tail_padding_ms: int,
    errors: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    subtitle_id = str(cue.get("subtitle_id") or "")
    word_start = _int_or_none(cue.get("word_start"))
    word_end = _int_or_none(cue.get("word_end"))
    if word_start is None or word_end is None or word_start > word_end:
        errors.append(
            {
                "code": "final_timeline_word_range_invalid",
                "subtitle_id": subtitle_id,
                "word_start": word_start,
                "word_end": word_end,
            }
        )
        return None
    first = word_by_id.get(word_start)
    last = word_by_id.get(word_end)
    if first is None or last is None:
        errors.append(
            {
                "code": "final_timeline_word_range_unknown",
                "subtitle_id": subtitle_id,
                "word_start": word_start,
                "word_end": word_end,
            }
        )
        return None
    envelope_start = int(first["start_ms"])
    envelope_end = int(last["end_ms"])
    if envelope_end < envelope_start:
        errors.append(
            {
                "code": "final_timeline_word_envelope_invalid",
                "subtitle_id": subtitle_id,
                "word_envelope": [envelope_start, envelope_end],
            }
        )
        return None
    sources = sorted(
        {
            str(word_by_id[word_id].get("alignment_source") or "unknown")
            for word_id in range(word_start, word_end + 1)
            if word_id in word_by_id
        }
    )
    return {
        "subtitle_id": subtitle_id,
        "word_start": word_start,
        "word_end": word_end,
        "word_envelope_start_ms": envelope_start,
        "word_envelope_end_ms": envelope_end,
        "start_ms": max(0, envelope_start - lead_in_ms),
        "end_ms": max(envelope_start + 1, envelope_end + tail_padding_ms),
        "word_alignment_sources": sources,
    }


def _resolve_display_padding_overlaps(
    records: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    repairs: List[Dict[str, Any]] = []
    for left, right in zip(records, records[1:]):
        if int(left["end_ms"]) <= int(right["start_ms"]):
            continue
        left_word_end = int(left["word_envelope_end_ms"])
        right_word_start = int(right["word_envelope_start_ms"])
        if left_word_end > right_word_start:
            errors.append(
                {
                    "code": "final_timeline_word_envelope_overlap",
                    "left_subtitle_id": left["subtitle_id"],
                    "right_subtitle_id": right["subtitle_id"],
                    "left_word_end_ms": left_word_end,
                    "right_word_start_ms": right_word_start,
                }
            )
            continue
        boundary = (left_word_end + right_word_start) // 2
        old_left_end = int(left["end_ms"])
        old_right_start = int(right["start_ms"])
        left["end_ms"] = boundary
        right["start_ms"] = boundary
        repairs.append(
            {
                "code": "final_timeline_padding_overlap_reconciled",
                "left_subtitle_id": left["subtitle_id"],
                "right_subtitle_id": right["subtitle_id"],
                "old_left_end_ms": old_left_end,
                "old_right_start_ms": old_right_start,
                "new_boundary_ms": boundary,
            }
        )
    return repairs


def _extend_short_display_ranges(
    records: List[Dict[str, Any]],
    *,
    target_duration_ms: int,
) -> List[Dict[str, Any]]:
    """Use only non-word time to improve short cue display duration.

    A neighboring cue keeps its own word envelope and up to the same soft
    display target.  The function may move a shared display boundary, but it
    never changes word times or creates overlapping cue ranges.
    """
    repairs: List[Dict[str, Any]] = []
    soft_target = max(HARD_MIN_DISPLAY_DURATION_MS, int(target_duration_ms))
    for target in dict.fromkeys((HARD_MIN_DISPLAY_DURATION_MS, soft_target)):
        for index, record in enumerate(records):
            old_start = int(record["start_ms"])
            old_end = int(record["end_ms"])
            duration = old_end - old_start
            if duration >= target:
                continue

            needed = target - duration
            right_limit = old_end + needed
            if index + 1 < len(records):
                right = records[index + 1]
                right_duration = int(right["end_ms"]) - int(right["start_ms"])
                right_preserve = max(
                    HARD_MIN_DISPLAY_DURATION_MS,
                    min(target, max(0, right_duration)),
                )
                right_limit = min(
                    int(right["word_envelope_start_ms"]),
                    int(right["end_ms"]) - right_preserve,
                )
            new_end = min(old_end + needed, max(old_end, right_limit))
            if index + 1 < len(records) and new_end > int(records[index + 1]["start_ms"]):
                records[index + 1]["start_ms"] = new_end
            record["end_ms"] = new_end
            needed -= new_end - old_end

            if needed > 0:
                left_limit = max(0, old_start - needed)
                if index > 0:
                    left = records[index - 1]
                    left_duration = int(left["end_ms"]) - int(left["start_ms"])
                    left_preserve = max(
                        HARD_MIN_DISPLAY_DURATION_MS,
                        min(target, max(0, left_duration)),
                    )
                    left_limit = max(
                        int(left["word_envelope_end_ms"]),
                        int(left["start_ms"]) + left_preserve,
                    )
                new_start = max(old_start - needed, min(old_start, left_limit))
                if index > 0 and new_start < int(records[index - 1]["end_ms"]):
                    records[index - 1]["end_ms"] = new_start
                record["start_ms"] = new_start

            if int(record["start_ms"]) != old_start or int(record["end_ms"]) != old_end:
                repairs.append(
                    {
                        "code": "final_timeline_short_display_extended",
                        "subtitle_id": str(record.get("subtitle_id") or ""),
                        "old_range_ms": [old_start, old_end],
                        "new_range_ms": [int(record["start_ms"]), int(record["end_ms"])],
                        "target_duration_ms": target,
                    }
                )
    return repairs


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None or value == "" else int(value)
    except (TypeError, ValueError):
        return None


def _unique_errors(errors: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen = set()
    for error in errors:
        payload = dict(error)
        marker = repr(sorted(payload.items()))
        if marker in seen:
            continue
        seen.add(marker)
        result.append(payload)
    return result


def _combined_alignment_source(source: str, marker: str) -> str:
    values = [value for value in str(source or "").split("+") if value]
    if marker not in values:
        values.append(marker)
    return "+".join(values) or marker
