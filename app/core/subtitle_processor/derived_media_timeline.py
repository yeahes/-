"""Deterministic source-to-output timing for non-destructive media deletion.

The source word ledger and cue timings remain immutable.  This module owns the
derived presentation clock used after complete parent subtitle intervals are
removed from the final media.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence


class DerivedMediaTimelineError(ValueError):
    """Raised when a media compaction decision cannot be mapped safely."""


def normalize_deleted_intervals(
    intervals: Sequence[Mapping[str, Any]],
    *,
    source_end_ms: int | None = None,
) -> List[Dict[str, Any]]:
    """Validate, sort, and merge overlapping or adjacent source intervals."""
    normalized: List[Dict[str, Any]] = []
    for raw in intervals:
        try:
            start_ms = int(raw["start_ms"])
            end_ms = int(raw["end_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DerivedMediaTimelineError("Deleted media interval is invalid.") from exc
        raw_ids = raw.get("subtitle_ids")
        if raw_ids is None:
            raw_ids = [raw.get("subtitle_id")]
        subtitle_ids = list(
            dict.fromkeys(str(value or "").strip() for value in raw_ids)
        )
        if (
            start_ms < 0
            or end_ms <= start_ms
            or not subtitle_ids
            or any(not subtitle_id for subtitle_id in subtitle_ids)
            or (source_end_ms is not None and end_ms > int(source_end_ms))
        ):
            raise DerivedMediaTimelineError("Deleted media interval is invalid.")
        normalized.append(
            {
                "subtitle_ids": subtitle_ids,
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
        )

    normalized.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    merged: List[Dict[str, Any]] = []
    for item in normalized:
        if not merged or item["start_ms"] > merged[-1]["end_ms"]:
            merged.append(dict(item))
            continue
        current = merged[-1]
        current["end_ms"] = max(current["end_ms"], item["end_ms"])
        current["subtitle_ids"] = list(
            dict.fromkeys([*current["subtitle_ids"], *item["subtitle_ids"]])
        )
    return merged


def deleted_intervals_from_cues(
    cues: Sequence[Mapping[str, Any]],
    *,
    source_end_ms: int | None = None,
) -> List[Dict[str, Any]]:
    """Build canonical source intervals from complete deleted parent cues."""
    raw = [
        {
            "subtitle_ids": [str(cue.get("cue_id") or "")],
            "start_ms": int(cue.get("start_time") or 0),
            "end_ms": int(cue.get("end_time") or 0),
        }
        for cue in cues
        if cue.get("timeline_deleted")
    ]
    return normalize_deleted_intervals(raw, source_end_ms=source_end_ms)


def map_source_time_ms(
    source_time_ms: int,
    deleted_intervals: Sequence[Mapping[str, Any]],
) -> int:
    """Map a retained source timestamp onto the compacted output clock."""
    value = int(source_time_ms)
    removed_ms = 0
    for interval in normalize_deleted_intervals(deleted_intervals):
        start_ms = int(interval["start_ms"])
        end_ms = int(interval["end_ms"])
        if value < start_ms:
            break
        if start_ms < value < end_ms:
            raise DerivedMediaTimelineError(
                "A retained timestamp falls inside deleted media."
            )
        if value >= end_ms:
            removed_ms += end_ms - start_ms
    return value - removed_ms


def project_retained_interval(
    start_ms: int,
    end_ms: int,
    deleted_intervals: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    """Project a retained source interval and reject any partial deletion."""
    start = int(start_ms)
    end = int(end_ms)
    if start < 0 or end <= start:
        raise DerivedMediaTimelineError("Retained media interval is invalid.")
    canonical = normalize_deleted_intervals(deleted_intervals)
    for interval in canonical:
        if start < int(interval["end_ms"]) and end > int(interval["start_ms"]):
            raise DerivedMediaTimelineError(
                "A retained interval overlaps deleted media."
            )
    output_start = map_source_time_ms(start, canonical)
    output_end = map_source_time_ms(end, canonical)
    if output_end <= output_start:
        raise DerivedMediaTimelineError("Compacted media interval is empty.")
    return {"start_ms": output_start, "end_ms": output_end}


def build_kept_segments(
    deleted_intervals: Sequence[Mapping[str, Any]],
    *,
    source_end_ms: int | None = None,
) -> List[Dict[str, int | None]]:
    """Return ordered source slices and their output offsets for FFmpeg concat."""
    if source_end_ms is not None and int(source_end_ms) <= 0:
        raise DerivedMediaTimelineError("Source media end is invalid.")
    canonical = normalize_deleted_intervals(
        deleted_intervals,
        source_end_ms=source_end_ms,
    )
    cursor = 0
    output_cursor = 0
    kept: List[Dict[str, int | None]] = []
    for interval in canonical:
        start_ms = int(interval["start_ms"])
        end_ms = int(interval["end_ms"])
        if start_ms > cursor:
            kept.append(
                {
                    "source_start_ms": cursor,
                    "source_end_ms": start_ms,
                    "output_start_ms": output_cursor,
                }
            )
            output_cursor += start_ms - cursor
        cursor = max(cursor, end_ms)
    if source_end_ms is None:
        kept.append(
            {
                "source_start_ms": cursor,
                "source_end_ms": None,
                "output_start_ms": output_cursor,
            }
        )
    elif cursor < int(source_end_ms):
        kept.append(
            {
                "source_start_ms": cursor,
                "source_end_ms": int(source_end_ms),
                "output_start_ms": output_cursor,
            }
        )
    if not kept or all(
        item["source_end_ms"] is not None
        and int(item["source_end_ms"]) <= int(item["source_start_ms"])
        for item in kept
    ):
        raise DerivedMediaTimelineError("Media compaction would delete all audio.")
    return kept


def build_presentation_timeline(
    source_records: Sequence[Mapping[str, Any]],
    deleted_intervals: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Project every retained cue while retaining deleted cue provenance."""
    canonical = normalize_deleted_intervals(deleted_intervals)
    deleted_ids = {
        subtitle_id
        for interval in canonical
        for subtitle_id in interval["subtitle_ids"]
    }
    source_ids = [str(record.get("subtitle_id") or "") for record in source_records]
    if deleted_ids - set(source_ids):
        raise DerivedMediaTimelineError("Deleted media references an unknown subtitle ID.")
    if source_ids and deleted_ids == set(source_ids):
        raise DerivedMediaTimelineError("Media compaction cannot delete every subtitle.")

    records: List[Dict[str, Any]] = []
    previous_output_end = -1
    for record in source_records:
        subtitle_id = str(record.get("subtitle_id") or "")
        source_start = int(record.get("start_ms") or 0)
        source_end = int(record.get("end_ms") or 0)
        deleted = subtitle_id in deleted_ids
        output_range = None
        if not deleted:
            output_range = project_retained_interval(
                source_start,
                source_end,
                canonical,
            )
            if int(output_range["start_ms"]) < previous_output_end:
                raise DerivedMediaTimelineError(
                    "Compacted subtitle timeline is not monotonic."
                )
            previous_output_end = int(output_range["end_ms"])
        records.append(
            {
                "subtitle_id": subtitle_id,
                "timeline_deleted": deleted,
                "source_start_ms": source_start,
                "source_end_ms": source_end,
                "output_start_ms": (
                    int(output_range["start_ms"]) if output_range else None
                ),
                "output_end_ms": (
                    int(output_range["end_ms"]) if output_range else None
                ),
            }
        )
    return {
        "schema_version": 1,
        "coordinate_system": "compacted_media_ms",
        "deleted_subtitle_ids": [
            subtitle_id for subtitle_id in source_ids if subtitle_id in deleted_ids
        ],
        "deleted_intervals": canonical,
        "records": records,
        "validation": {"status": "PASS", "errors": []},
    }
