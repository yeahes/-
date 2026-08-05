"""Pure planning primitives for presentation-only subtitle pages.

The planner owns neither subtitle IDs nor cue timing.  Callers provide the
fixed-font and language-specific readability checks, while this module chooses
deterministic word spans inside one already-frozen cue.
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence


SpanReadable = Callable[[int, int, bool, bool], bool]
BreakScore = Callable[[int, float], float]


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
) -> list[tuple[int, int]] | None:
    """Choose a minimum-cost partition of frozen words into display pages.

    Spans use the normal Python convention ``[start, end)``.  The dynamic
    program considers every legal word boundary, applies the caller's syntax
    and fixed-font checks, and rejects schedules that cannot give every page
    the minimum display duration.  It never edits text or timing.
    """
    if word_count <= 0 or page_count <= 0:
        return None
    page_count = min(int(page_count), int(word_count))
    if page_count == 1:
        return [(0, word_count)] if span_is_readable(0, word_count, True, False) else None
    if float(cue_end) - float(cue_start) + 1e-6 < page_count * min_page_duration:
        return None

    timed_words = tuple(word_timing or ())
    has_timing = len(timed_words) == word_count
    memo: dict[tuple[int, int], tuple[float, list[tuple[int, int]]] | None] = {}

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
            memo[key] = None
            return None
        paginated = page_count > 1
        if remaining_pages == 1:
            if not span_is_readable(start, word_count, start == 0, paginated):
                memo[key] = None
                return None
            result = (0.0, [(start, word_count)])
            memo[key] = result
            return result

        best: tuple[float, list[tuple[int, int]]] | None = None
        target_words = remaining_words / remaining_pages
        last_end = word_count - (remaining_pages - 1)
        for end in range(start + 1, last_end + 1):
            if not has_minimum_timing(start, end, remaining_pages):
                continue
            if not span_is_readable(start, end, start == 0, paginated):
                continue
            score = float(break_score(end, start + target_words))
            if score >= 12_000:
                continue
            suffix = solve(end, remaining_pages - 1)
            if suffix is None:
                continue
            candidate = (score + suffix[0], [(start, end), *suffix[1]])
            if best is None or candidate[0] < best[0]:
                best = candidate
        memo[key] = best
        return best

    result = solve(0, page_count)
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
