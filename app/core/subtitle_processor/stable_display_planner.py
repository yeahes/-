"""Pure planning primitives for presentation-only subtitle pages.

The planner owns neither subtitle IDs nor cue timing.  Callers provide the
fixed-font and language-specific readability checks, while this module chooses
deterministic word spans inside one already-frozen cue.
"""

from __future__ import annotations

from typing import Callable, Mapping, MutableSet, Sequence


SpanReadable = Callable[[int, int, bool, bool], bool]
BreakCost = float | tuple[int, float]
BreakScore = Callable[[int, float], BreakCost | None]
SpanScore = Callable[[int, int], float]


def plan_word_page_spans(
    word_count: int,
    page_count: int,
    *,
    cue_start: float,
    cue_end: float,
    word_timing: Sequence[Mapping[str, object]] = (),
    min_page_duration: float = 0.9,
    span_is_readable: SpanReadable,
    break_score: BreakScore,
    span_score: SpanScore | None = None,
    diagnostics: MutableSet[str] | None = None,
) -> list[tuple[int, int]] | None:
    """Choose a minimum-cost partition of frozen words into display pages.

    Spans use the normal Python convention ``[start, end)``.  The dynamic
    program considers every legal word boundary, applies the caller's syntax
    and fixed-font checks, and rejects schedules that cannot give every page
    the minimum display duration.  It never edits text or timing.
    """
    def record(reason: str) -> None:
        if diagnostics is not None:
            diagnostics.add(reason)

    if word_count <= 0 or page_count <= 0:
        record("invalid_page_partition_input")
        return None
    page_count = min(int(page_count), int(word_count))
    if page_count == 1:
        if span_is_readable(0, word_count, True, False):
            return [(0, word_count)]
        record("fixed_font_span_unreadable")
        return None
    if float(cue_end) - float(cue_start) + 1e-6 < page_count * min_page_duration:
        record("cue_duration_below_page_minimum")
        return None

    timed_words = tuple(word_timing or ())
    has_timing = len(timed_words) == word_count
    memo: dict[
        tuple[int, int],
        tuple[tuple[int, float], list[tuple[int, int]]] | None,
    ] = {}

    def normalized_cost(value: BreakCost) -> tuple[int, float]:
        if isinstance(value, tuple):
            return int(value[0]), float(value[1])
        return 0, float(value)

    def page_cost(start: int, end: int) -> float:
        if span_score is None:
            return 0.0
        return max(0.0, float(span_score(start, end)))

    def has_minimum_timing(
        start: int,
        end: int,
        remaining_pages: int,
    ) -> bool:
        if not has_timing:
            return True
        completed_pages = page_count - remaining_pages + 1
        trailing_pages = remaining_pages - 1
        previous_end = float(timed_words[end - 1].get("end", cue_start))
        next_start = float(timed_words[end].get("start", cue_end))
        if next_start + 1e-6 < float(cue_start) + completed_pages * min_page_duration:
            return False
        if previous_end - 1e-6 > float(cue_end) - trailing_pages * min_page_duration:
            return False
        return True

    def solve(start: int, remaining_pages: int):
        key = (start, remaining_pages)
        if key in memo:
            return memo[key]
        remaining_words = word_count - start
        if remaining_words < remaining_pages:
            record("insufficient_words_for_page_count")
            memo[key] = None
            return None
        paginated = page_count > 1
        if remaining_pages == 1:
            if not span_is_readable(start, word_count, start == 0, paginated):
                record("fixed_font_span_unreadable")
                memo[key] = None
                return None
            result = ((0, page_cost(start, word_count)), [(start, word_count)])
            memo[key] = result
            return result

        best: tuple[tuple[int, float], list[tuple[int, int]]] | None = None
        target_words = remaining_words / remaining_pages
        last_end = word_count - (remaining_pages - 1)
        for end in range(start + 1, last_end + 1):
            if not has_minimum_timing(start, end, remaining_pages):
                record("page_boundary_timing_invalid")
                continue
            if not span_is_readable(start, end, start == 0, paginated):
                record("fixed_font_span_unreadable")
                continue
            boundary_cost = break_score(end, start + target_words)
            if boundary_cost is None:
                record("hard_page_boundary")
                continue
            risk, score = normalized_cost(boundary_cost)
            suffix = solve(end, remaining_pages - 1)
            if suffix is None:
                continue
            candidate = (
                (
                    risk + suffix[0][0],
                    score + page_cost(start, end) + suffix[0][1],
                ),
                [(start, end), *suffix[1]],
            )
            if best is None or candidate[0] < best[0]:
                best = candidate
        memo[key] = best
        return best

    result = solve(0, page_count)
    if result is None:
        record("no_complete_legal_page_partition")
    return result[1] if result is not None else None


def spans_cover_words(spans: Sequence[tuple[int, int]], word_count: int) -> bool:
    """Return whether ordered half-open spans cover each word exactly once."""
    if word_count <= 0 or not spans or spans[0][0] != 0:
        return False
    cursor = 0
    for start, end in spans:
        if start != cursor or end <= start or end > word_count:
            return False
        cursor = end
    return cursor == word_count
