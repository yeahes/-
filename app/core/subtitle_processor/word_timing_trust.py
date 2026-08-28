"""Shared acoustic word-timing trust checks.

The stable subtitle pipeline may change display boundaries, but it must not
hide a word ledger whose acoustic timing is physically implausible.  This
module intentionally owns detection only; callers decide whether a local
alignment update can be reverted or whether the run must stop.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


DENSE_WINDOW_MIN_WORDS = 8
DENSE_WINDOW_MAX_WORDS = 12
DENSE_WINDOW_MAX_MS = 750
DENSE_WINDOW_MIN_WORDS_PER_SECOND = 10.0
EXTREME_WINDOW_MIN_WORDS = 4
EXTREME_WINDOW_MAX_MS = 250


def find_implausible_word_timing_runs(
    segments: Sequence[Any],
) -> list[dict[str, Any]]:
    """Return conservative local word-density failures.

    Natural speech can contain very short function words, so a single short
    token is not evidence of bad alignment.  A run is reported only when
    several consecutive words are compressed into an implausibly small
    acoustic envelope.
    """

    raw_issues: list[dict[str, Any]] = []
    segment_count = len(segments)
    for start_index in range(segment_count):
        first_start = _time_value(segments[start_index], "start_time", "start_ms")
        if first_start is None:
            continue
        max_end = first_start
        search_end = min(segment_count, start_index + DENSE_WINDOW_MAX_WORDS)
        for end_index in range(start_index, search_end):
            start = _time_value(segments[end_index], "start_time", "start_ms")
            end = _time_value(segments[end_index], "end_time", "end_ms")
            if start is None or end is None or end <= start:
                continue
            max_end = max(max_end, end)
            word_count = end_index - start_index + 1
            duration_ms = max_end - first_start
            if duration_ms <= 0:
                continue
            words_per_second = word_count * 1000.0 / duration_ms
            extreme = (
                word_count >= EXTREME_WINDOW_MIN_WORDS
                and duration_ms <= EXTREME_WINDOW_MAX_MS
            )
            dense = (
                word_count >= DENSE_WINDOW_MIN_WORDS
                and duration_ms <= DENSE_WINDOW_MAX_MS
                and words_per_second >= DENSE_WINDOW_MIN_WORDS_PER_SECOND
            )
            if not (extreme or dense):
                continue
            raw_issues.append(
                {
                    "code": "implausible_word_timing_density",
                    "start_index": start_index,
                    "end_index": end_index,
                    "start_ms": first_start,
                    "end_ms": max_end,
                    "duration_ms": duration_ms,
                    "word_count": word_count,
                    "words_per_second": round(words_per_second, 3),
                }
            )

    if not raw_issues:
        return []

    extreme_issues = [
        issue
        for issue in raw_issues
        if issue["word_count"] >= EXTREME_WINDOW_MIN_WORDS
        and issue["duration_ms"] <= EXTREME_WINDOW_MAX_MS
    ]
    selected = _select_component_cores(extreme_issues)

    # A dense sliding window can overlap an extreme core and make a six-word
    # alignment defect look like a 12- or 40-word failure.  The extreme core is
    # sufficient evidence; callers can repair it and run this detector again.
    dense_issues = [
        issue
        for issue in raw_issues
        if issue not in extreme_issues
        and not any(_issues_overlap(issue, extreme) for extreme in extreme_issues)
    ]
    selected.extend(_select_component_cores(dense_issues))
    return sorted(selected, key=lambda item: (item["start_index"], item["end_index"]))


def _select_component_cores(
    issues: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    components: list[list[Mapping[str, Any]]] = []
    component_ends: list[int] = []
    for issue in sorted(
        issues,
        key=lambda item: (int(item["start_index"]), int(item["end_index"])),
    ):
        if not components:
            components.append([issue])
            component_ends.append(int(issue["end_index"]))
            continue
        if int(issue["start_index"]) > component_ends[-1]:
            components.append([issue])
            component_ends.append(int(issue["end_index"]))
        else:
            components[-1].append(issue)
            component_ends[-1] = max(
                component_ends[-1],
                int(issue["end_index"]),
            )

    return [
        dict(
            min(
                component,
                key=lambda item: (
                    int(item["word_count"]),
                    int(item["duration_ms"]),
                    -float(item["words_per_second"]),
                    int(item["start_index"]),
                ),
            )
        )
        for component in components
    ]


def _issues_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return not (
        int(left["end_index"]) < int(right["start_index"])
        or int(right["end_index"]) < int(left["start_index"])
    )


def describe_word_timing_issue(issue: Mapping[str, Any]) -> str:
    start_ms = int(issue.get("start_ms") or 0)
    end_ms = int(issue.get("end_ms") or start_ms)
    return (
        f"{_format_ms(start_ms)}-{_format_ms(end_ms)} "
        f"words={int(issue.get('word_count') or 0)} "
        f"duration_ms={int(issue.get('duration_ms') or 0)}"
    )


def _time_value(segment: Any, attr_name: str, key_name: str) -> int | None:
    if isinstance(segment, Mapping):
        value = segment.get(key_name)
        if value is None:
            value = segment.get(attr_name)
    else:
        value = getattr(segment, attr_name, None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_ms(value: int) -> str:
    seconds, milliseconds = divmod(max(0, int(value)), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
