from app.core.subtitle_processor.stable_english_optimizer import (
    plan_english_cue_ranges,
    ranges_cover_interval,
)


def test_global_planner_looks_past_locally_cheapest_cut():
    allowed_cut_ends = {9: 0.0, 11: -5.0, 19: 0.0, 21: 0.0}

    def edge_cost(start: int, end: int, is_final: bool):
        if is_final:
            return 0.0
        return allowed_cut_ends.get(end)

    ranges = plan_english_cue_ranges(
        0,
        29,
        target_words=12,
        emergency_words=19,
        edge_cost=edge_cost,
    )

    assert ranges == [(0, 9), (10, 19), (20, 29)]
    assert ranges_cover_interval(ranges, 0, 29)


def test_global_planner_never_crosses_a_forbidden_boundary():
    def edge_cost(start: int, end: int, is_final: bool):
        if is_final:
            return 0.0
        if end == 11:
            return None
        return 0.0

    ranges = plan_english_cue_ranges(
        0,
        23,
        target_words=12,
        emergency_words=19,
        edge_cost=edge_cost,
    )

    assert ranges is not None
    assert all(end != 11 for _, end in ranges[:-1])
    assert ranges_cover_interval(ranges, 0, 23)


def test_global_planner_tie_break_is_deterministic():
    allowed_cut_ends = {10, 12}

    def edge_cost(start: int, end: int, is_final: bool):
        if is_final:
            return 0.0
        return 0.0 if end in allowed_cut_ends else None

    results = [
        plan_english_cue_ranges(
            0,
            23,
            target_words=12,
            emergency_words=19,
            edge_cost=edge_cost,
        )
        for _ in range(5)
    ]

    assert results == [[(0, 10), (11, 23)]] * 5


def test_global_planner_returns_none_without_a_complete_legal_path():
    def edge_cost(start: int, end: int, is_final: bool):
        if is_final and start == 0:
            return 0.0
        return None

    ranges = plan_english_cue_ranges(
        0,
        20,
        target_words=10,
        emergency_words=19,
        edge_cost=edge_cost,
    )

    assert ranges is None


if __name__ == "__main__":
    test_global_planner_looks_past_locally_cheapest_cut()
    test_global_planner_never_crosses_a_forbidden_boundary()
    test_global_planner_tie_break_is_deterministic()
    test_global_planner_returns_none_without_a_complete_legal_path()
