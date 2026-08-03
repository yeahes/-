from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.subtitle_processor.stable_english_boundaries import (
    STABLE_ENGLISH_BOUNDARY_STAGES,
    finalize_stable_english_boundaries,
)


def test_boundary_facade_runs_the_fixed_pre_id_order_with_snapshot_handoffs():
    snapshots = []

    result = finalize_stable_english_boundaries(
        ["source"],
        run_stage=lambda stage, items: [*items, stage],
        capture_snapshot=lambda stage, items, changed_by, previous_items: snapshots.append(
            (stage, list(items), changed_by, previous_items)
        ),
        previous_snapshot_items=lambda stage: [f"snapshot:{stage}"],
    )

    assert result == ["source", *STABLE_ENGLISH_BOUNDARY_STAGES]
    assert [snapshot[0] for snapshot in snapshots] == list(STABLE_ENGLISH_BOUNDARY_STAGES)
    assert snapshots[0][3] is None
    assert snapshots[1][3] == ["snapshot:_stable_cut_items"]
    assert snapshots[-1][3] == [
        "snapshot:_validate_and_repair_final_pre_id_boundaries"
    ]


def test_finalizer_runs_all_english_stages_before_ids_are_assigned():
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    snapshots = []

    editor._stable_cut_items = lambda source: ["stable"]
    editor._merge_standalone_discourse_markers = lambda items: [*items, "markers"]
    editor._merge_short_display_segments = lambda items: [*items, "short"]
    editor._rebalance_edge_discourse_markers = lambda items: [*items, "edge"]
    editor._validate_and_repair_final_pre_id_boundaries = lambda items: [*items, "final"]
    editor._apply_visual_reading_budget = lambda items: [*items, "visual"]
    editor._boundary_snapshot_items = lambda stage: [stage]
    editor._capture_boundary_snapshot = lambda stage, items, **kwargs: snapshots.append(stage)

    result = editor._finalize_stable_english_boundaries(["source"])

    assert result == ["stable", "markers", "short", "edge", "final", "visual"]
    assert snapshots == [
        "_stable_cut_items",
        "_merge_standalone_discourse_markers",
        "_merge_short_display_segments",
        "_rebalance_edge_discourse_markers",
        "_validate_and_repair_final_pre_id_boundaries",
        "_apply_visual_reading_budget",
    ]


if __name__ == "__main__":
    test_boundary_facade_runs_the_fixed_pre_id_order_with_snapshot_handoffs()
    test_finalizer_runs_all_english_stages_before_ids_are_assigned()
    print("Stable boundary finalization tests passed.")
