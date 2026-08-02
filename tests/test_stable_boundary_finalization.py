from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor


def test_finalizer_runs_all_english_stages_before_ids_are_assigned():
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    snapshots = []

    editor._stable_cut_items = lambda source: ["stable"]
    editor._merge_standalone_discourse_markers = lambda items: [*items, "markers"]
    editor._merge_short_display_segments = lambda items: [*items, "short"]
    editor._rebalance_edge_discourse_markers = lambda items: [*items, "edge"]
    editor._validate_and_repair_final_pre_id_boundaries = lambda items: [*items, "final"]
    editor._boundary_snapshot_items = lambda stage: [stage]
    editor._capture_boundary_snapshot = lambda stage, items, **kwargs: snapshots.append(stage)

    result = editor._finalize_stable_english_boundaries(["source"])

    assert result == ["stable", "markers", "short", "edge", "final"]
    assert snapshots == [
        "_stable_cut_items",
        "_merge_standalone_discourse_markers",
        "_merge_short_display_segments",
        "_rebalance_edge_discourse_markers",
        "_validate_and_repair_final_pre_id_boundaries",
    ]


if __name__ == "__main__":
    test_finalizer_runs_all_english_stages_before_ids_are_assigned()
    print("Stable boundary finalization tests passed.")
