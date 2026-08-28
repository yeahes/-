import pytest

from app.core.subtitle_processor.derived_media_timeline import (
    DerivedMediaTimelineError,
    build_kept_segments,
    build_presentation_timeline,
    map_source_time_ms,
    normalize_deleted_intervals,
    project_retained_interval,
)


def test_no_deletion_is_identity_mapping():
    assert normalize_deleted_intervals([]) == []
    assert map_source_time_ms(4200, []) == 4200
    assert project_retained_interval(1000, 2400, []) == {
        "start_ms": 1000,
        "end_ms": 2400,
    }


def test_overlapping_and_adjacent_deletions_merge_with_stable_ids():
    assert normalize_deleted_intervals(
        [
            {"subtitle_ids": ["S0003"], "start_ms": 3000, "end_ms": 4000},
            {"subtitle_ids": ["S0001"], "start_ms": 1000, "end_ms": 2000},
            {"subtitle_ids": ["S0002"], "start_ms": 2000, "end_ms": 3200},
        ]
    ) == [
        {
            "subtitle_ids": ["S0001", "S0002", "S0003"],
            "start_ms": 1000,
            "end_ms": 4000,
        }
    ]


def test_non_contiguous_deletions_shift_later_time_by_total_removed_duration():
    deleted = [
        {"subtitle_ids": ["S0002"], "start_ms": 1000, "end_ms": 1500},
        {"subtitle_ids": ["S0004"], "start_ms": 3000, "end_ms": 3800},
    ]
    assert map_source_time_ms(1000, deleted) == 1000
    assert map_source_time_ms(1500, deleted) == 1000
    assert map_source_time_ms(4200, deleted) == 2900
    assert project_retained_interval(4000, 4600, deleted) == {
        "start_ms": 2700,
        "end_ms": 3300,
    }
    with pytest.raises(DerivedMediaTimelineError):
        map_source_time_ms(1200, deleted)
    with pytest.raises(DerivedMediaTimelineError):
        project_retained_interval(900, 1100, deleted)


def test_kept_segments_cover_start_middle_and_bounded_end():
    deleted = [
        {"subtitle_ids": ["S0001"], "start_ms": 0, "end_ms": 500},
        {"subtitle_ids": ["S0003"], "start_ms": 1500, "end_ms": 2200},
        {"subtitle_ids": ["S0005"], "start_ms": 3500, "end_ms": 4000},
    ]
    assert build_kept_segments(deleted, source_end_ms=4000) == [
        {"source_start_ms": 500, "source_end_ms": 1500, "output_start_ms": 0},
        {
            "source_start_ms": 2200,
            "source_end_ms": 3500,
            "output_start_ms": 1000,
        },
    ]


def test_unbounded_kept_segments_preserve_trailing_media():
    assert build_kept_segments(
        [{"subtitle_ids": ["S0002"], "start_ms": 1000, "end_ms": 1500}]
    ) == [
        {"source_start_ms": 0, "source_end_ms": 1000, "output_start_ms": 0},
        {
            "source_start_ms": 1500,
            "source_end_ms": None,
            "output_start_ms": 1000,
        },
    ]


def test_presentation_timeline_keeps_source_ids_and_projects_survivors():
    source_records = [
        {"subtitle_id": "S0001", "start_ms": 0, "end_ms": 1000},
        {"subtitle_id": "S0002", "start_ms": 1000, "end_ms": 1800},
        {"subtitle_id": "S0003", "start_ms": 1800, "end_ms": 3000},
    ]
    presentation = build_presentation_timeline(
        source_records,
        [
            {
                "subtitle_ids": ["S0002"],
                "start_ms": 1000,
                "end_ms": 1800,
            }
        ],
    )
    assert [item["subtitle_id"] for item in presentation["records"]] == [
        "S0001",
        "S0002",
        "S0003",
    ]
    assert presentation["records"][1]["timeline_deleted"] is True
    assert presentation["records"][2]["output_start_ms"] == 1000
    assert presentation["records"][2]["output_end_ms"] == 2200


def test_presentation_timeline_rejects_unknown_or_all_deleted_ids():
    source_records = [
        {"subtitle_id": "S0001", "start_ms": 0, "end_ms": 1000},
    ]
    with pytest.raises(DerivedMediaTimelineError):
        build_presentation_timeline(
            source_records,
            [{"subtitle_ids": ["S9999"], "start_ms": 0, "end_ms": 1000}],
        )
    with pytest.raises(DerivedMediaTimelineError):
        build_presentation_timeline(
            source_records,
            [{"subtitle_ids": ["S0001"], "start_ms": 0, "end_ms": 1000}],
        )
