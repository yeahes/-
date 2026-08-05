"""Global optimization for stable English cue boundaries.

The optimizer owns only ordered word-range selection inside one source
sentence.  The caller remains responsible for linguistic legality and returns
``None`` for a forbidden range.  This separation keeps ASR text, timestamps,
subtitle IDs, translation, and rendering outside the optimization layer.
"""

from __future__ import annotations

import math
from typing import Callable, Optional, Sequence


EdgeCost = Callable[[int, int, bool], Optional[float]]


def plan_english_cue_ranges(
    word_start: int,
    word_end: int,
    *,
    target_words: int,
    emergency_words: int,
    edge_cost: EdgeCost,
    count_deviation_penalty: float = 48.0,
    balance_weight: float = 1.0,
) -> list[tuple[int, int]] | None:
    """Return the minimum-cost complete partition of an inclusive word span.

    Dynamic-programming states retain the best path for each
    ``(next_word, cue_count)`` pair.  This is necessary because a locally good
    boundary can force a short or structurally expensive suffix.  The caller's
    ``edge_cost`` is authoritative for linguistic legality; this function adds
    only whole-sentence balance and cue-count costs.

    Complexity is ``O(n^2 * c)`` time and ``O(n * c)`` space in the general
    form, where ``c`` is the number of reachable cue counts.  In production,
    every edge is capped by ``emergency_words``, so sentence-sized inputs are
    small and deterministic.
    """
    if word_end < word_start:
        return []
    if target_words <= 0 or emergency_words < target_words:
        raise ValueError("invalid English cue word limits")

    word_count = word_end - word_start + 1
    target_count = max(1, math.ceil(word_count / target_words))
    ideal_words = word_count / target_count

    # next word -> cue count -> (raw cost, ranges)
    states: dict[
        int,
        dict[int, tuple[float, tuple[tuple[int, int], ...]]],
    ] = {word_start: {0: (0.0, ())}}

    for start in range(word_start, word_end + 1):
        by_count = states.get(start)
        if not by_count:
            continue
        last_end = min(word_end, start + emergency_words - 1)
        for end in range(start, last_end + 1):
            is_final = end == word_end
            caller_cost = edge_cost(start, end, is_final)
            if caller_cost is None or not math.isfinite(float(caller_cost)):
                continue
            length = end - start + 1
            balance_cost = (length - ideal_words) ** 2 * balance_weight
            if length <= 2:
                balance_cost += 48.0
            elif length <= 4:
                balance_cost += 14.0
            if length > target_words:
                balance_cost += (length - target_words) ** 2 * 10.0

            next_word = end + 1
            destination = states.setdefault(next_word, {})
            for cue_count, (path_cost, ranges) in by_count.items():
                new_count = cue_count + 1
                candidate = (
                    path_cost + float(caller_cost) + balance_cost,
                    (*ranges, (start, end)),
                )
                current = destination.get(new_count)
                if current is None or _path_key(candidate) < _path_key(current):
                    destination[new_count] = candidate

    completed = states.get(word_end + 1, {})
    if not completed:
        return None

    best: tuple[
        tuple[float, int, int, tuple[int, ...]],
        tuple[tuple[int, int], ...],
    ] | None = None
    for cue_count, (raw_cost, ranges) in completed.items():
        count_delta = abs(cue_count - target_count)
        final_cost = raw_cost + count_delta * count_deviation_penalty
        key = (
            round(final_cost, 9),
            count_delta,
            cue_count,
            tuple(end for _, end in ranges),
        )
        if best is None or key < best[0]:
            best = (key, ranges)
    return list(best[1]) if best is not None else None


def ranges_cover_interval(
    ranges: Sequence[tuple[int, int]],
    word_start: int,
    word_end: int,
) -> bool:
    """Return whether inclusive ranges cover the source interval once."""
    if word_end < word_start:
        return not ranges
    if not ranges:
        return False
    cursor = word_start
    for start, end in ranges:
        if start != cursor or end < start or end > word_end:
            return False
        cursor = end + 1
    return cursor == word_end + 1


def _path_key(
    candidate: tuple[float, tuple[tuple[int, int], ...]],
) -> tuple[float, tuple[int, ...]]:
    cost, ranges = candidate
    return round(cost, 9), tuple(end for _, end in ranges)
