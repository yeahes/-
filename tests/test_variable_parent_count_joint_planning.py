from __future__ import annotations

from scripts import audit_variable_parent_count_joint_planning as experiment
from types import SimpleNamespace


def test_partitions_cover_window_once_and_change_parent_count():
    partitions = list(experiment._partitions(10, 25, 2))

    assert partitions
    for ranges in partitions:
        assert len(ranges) == 2
        assert [word for start, end in ranges for word in range(start, end + 1)] == list(
            range(10, 26)
        )
        assert all(4 <= end - start + 1 <= 19 for start, end in ranges)


def test_partitions_reject_impossible_parent_count():
    assert list(experiment._partitions(0, 9, 4)) == []
    assert list(experiment._partitions(0, 99, 4)) == []


def test_partitions_may_preserve_preexisting_short_parent():
    partitions = list(
        experiment._partitions(
            0,
            17,
            4,
            baseline_ranges=((0, 2), (3, 16), (17, 17)),
        )
    )

    assert ((0, 2), (3, 8), (9, 16), (17, 17)) in partitions


def test_material_improvement_requires_real_render_and_page_quality():
    baseline = {
        "render_failure_count": 1,
        "pages_over_two_lines": 0,
        "pages_over_16_words": 0,
        "pages_below_56px": 0,
        "review_boundaries": 1,
        "pages_over_pressure_1": 1,
        "max_pressure": 1.2,
        "max_words": 16,
        "min_words": 6,
    }
    fixed = dict(
        baseline,
        render_failure_count=0,
        review_boundaries=2,
        max_words=14,
        min_words=5,
    )
    short_fragment = dict(fixed, min_words=4)
    overlong = dict(fixed, max_words=17)

    assert experiment._materially_improves(fixed, baseline)
    assert not experiment._materially_improves(short_fragment, baseline)
    assert not experiment._materially_improves(overlong, baseline)


def test_new_parent_ids_are_provisional_and_ordered():
    assert experiment._new_parent_ids("S0123", 4) == [
        "S0123.V01",
        "S0123.V02",
        "S0123.V03",
        "S0123.V04",
    ]


def test_variable_gate_does_not_reject_unchanged_legacy_short_neighbor():
    old = [
        SimpleNamespace(word_start=0, word_end=1, original="303 billion."),
        SimpleNamespace(word_start=2, word_end=9, original="a complete long clause"),
    ]
    new = [
        old[0],
        SimpleNamespace(word_start=2, word_end=5, original="a complete"),
        SimpleNamespace(word_start=6, word_end=9, original="long clause"),
    ]

    class Editor:
        max_english_words = 16

        @staticmethod
        def _items_word_tokens(items):
            return list(range(items[0].word_start, items[-1].word_end + 1))

        @staticmethod
        def _items_word_range(items):
            return items[0].word_start, items[-1].word_end

        @staticmethod
        def _strong_sentence_anchor_pairs(_items):
            return {(1, 2)}

        @staticmethod
        def _pre_id_boundary_pairs(items):
            return {(left.word_end, right.word_start) for left, right in zip(items, items[1:])}

        @staticmethod
        def _items_are_continuous(left, right):
            return left.word_end + 1 == right.word_start

        @staticmethod
        def _items_cross_speaker(_left, _right):
            return False

        @staticmethod
        def _evaluate_item_pair_for_final_boundary(_left, _right):
            return {"hard_issues": []}

        @staticmethod
        def _pre_id_boundary_pair(left, right):
            return left.word_end, right.word_start

        @staticmethod
        def _evaluate_item_boundary(_left, _right):
            return {"hard_issues": []}

        @staticmethod
        def _evaluate_final_display_fragment(item, _previous, _next):
            return {
                "hard_fragment_issues": (
                    ["incomplete_short_fragment"]
                    if item.original == "303 billion."
                    else []
                )
            }

        @staticmethod
        def _is_ordinary_one_word_fragment(_text):
            return False

        @staticmethod
        def _word_count(text):
            return len(text.split())

        @staticmethod
        def _is_allowed_pre_id_item_structural_overflow(_item):
            return False

    gate = experiment._variable_count_gate(
        Editor(),
        old,
        new,
        previous_item=None,
        next_item=None,
    )

    assert gate["accepted"] is True
    assert gate["unchanged_range_count"] == 1


def test_variable_gate_records_removed_sentence_anchor_as_review_cost():
    old = [
        SimpleNamespace(word_start=0, word_end=4, original="First sentence."),
        SimpleNamespace(word_start=5, word_end=9, original="Second sentence."),
    ]
    merged = [
        SimpleNamespace(
            word_start=0,
            word_end=9,
            original="First sentence. Second sentence.",
        )
    ]

    class Editor:
        max_english_words = 16
        _items_word_tokens = staticmethod(
            lambda items: list(range(items[0].word_start, items[-1].word_end + 1))
        )
        _items_word_range = staticmethod(
            lambda items: (items[0].word_start, items[-1].word_end)
        )
        _strong_sentence_anchor_pairs = staticmethod(lambda _items: {(4, 5)})
        _pre_id_boundary_pairs = staticmethod(
            lambda items: {
                (left.word_end, right.word_start)
                for left, right in zip(items, items[1:])
            }
        )
        _evaluate_final_display_fragment = staticmethod(
            lambda *_args: {"hard_fragment_issues": []}
        )
        _is_ordinary_one_word_fragment = staticmethod(lambda _text: False)
        _word_count = staticmethod(lambda text: len(text.split()))
        _is_allowed_pre_id_item_structural_overflow = staticmethod(lambda _item: False)

    gate = experiment._variable_count_gate(
        Editor(),
        old,
        merged,
        previous_item=None,
        next_item=None,
    )

    assert gate["accepted"] is True
    assert gate["removed_sentence_anchors"] == [[4, 5]]
