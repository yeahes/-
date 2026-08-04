"""Orchestration contract for stable English boundaries before subtitle IDs.

The boundary rules remain local to the stable subtitle editor. This module
owns only their fixed stage order and snapshot handoff, so translation,
allocation, rendering, and LLM state cannot participate in English boundary
selection.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, TypeVar


T = TypeVar("T")


STABLE_ENGLISH_BOUNDARY_STAGES = (
    "_stable_cut_items",
    "_merge_standalone_discourse_markers",
    "_merge_short_display_segments",
    "_rebalance_edge_discourse_markers",
    "_validate_and_repair_final_pre_id_boundaries",
)


def finalize_stable_english_boundaries(
    source_segments: Sequence[T],
    *,
    run_stage: Callable[[str, Sequence[T]], Sequence[T]],
    capture_snapshot: Callable[[str, Sequence[T], str, Optional[Sequence[T]]], None],
    previous_snapshot_items: Callable[[str], Sequence[T]],
) -> list[T]:
    """Run the frozen pre-ID boundary stages in their production order.

    Callers provide all domain behavior through callbacks. This keeps the
    facade deterministic and free of editor, translation, timing, and render
    dependencies while retaining the existing snapshot evidence for every
    boundary stage.
    """
    items: Sequence[T] = source_segments
    previous_stage: Optional[str] = None
    for stage in STABLE_ENGLISH_BOUNDARY_STAGES:
        items = run_stage(stage, items)
        capture_snapshot(
            stage,
            items,
            stage,
            None if previous_stage is None else previous_snapshot_items(previous_stage),
        )
        previous_stage = stage
    return list(items)
