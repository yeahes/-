from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import audit_pre_id_joint_page_feasibility as experiment


def test_ranges_from_cuts_preserve_exact_coverage():
    ranges = experiment._ranges_from_cuts(10, 29, (16, 24))

    assert ranges == ((10, 15), (16, 23), (24, 29))
    assert [word for start, end in ranges for word in range(start, end + 1)] == list(
        range(10, 30)
    )


@pytest.mark.parametrize(
    "cuts",
    [
        (10, 20),
        (20, 20),
        (24, 16),
        (16, 30),
    ],
)
def test_ranges_from_cuts_reject_invalid_boundaries(cuts):
    with pytest.raises(ValueError, match="strictly increasing"):
        experiment._ranges_from_cuts(10, 29, cuts)


def test_not_worse_keeps_hard_and_readability_metrics_monotonic():
    baseline = {
        "render_failure_count": 1,
        "pages_over_two_lines": 0,
        "pages_over_16_words": 1,
        "pages_below_56px": 1,
        "review_boundaries": 2,
        "pages_over_pressure_1": 2,
        "max_pressure": 1.4,
    }
    improved = dict(baseline, render_failure_count=0, max_pressure=1.2)
    regressed = dict(improved, review_boundaries=3)

    assert experiment._not_worse(improved, baseline)
    assert not experiment._not_worse(regressed, baseline)


def test_quality_vector_prioritizes_renderability_over_balance():
    blocked = {
        "render_failure_count": 1,
        "pages_over_two_lines": 0,
        "pages_over_16_words": 0,
        "pages_below_56px": 0,
        "review_boundaries": 0,
        "pages_over_pressure_1": 0,
        "max_pressure": 0.0,
        "word_count_imbalance": 0,
    }
    renderable_but_uneven = dict(
        blocked,
        render_failure_count=0,
        word_count_imbalance=10,
    )

    assert experiment._quality_vector(renderable_but_uneven) < experiment._quality_vector(
        blocked
    )


def test_report_cannot_be_written_inside_immutable_artifact(tmp_path: Path):
    artifact = tmp_path / "run-artifacts"
    artifact.mkdir()

    with pytest.raises(ValueError, match="outside the immutable artifact"):
        experiment._ensure_report_outside_artifact(
            artifact / "joint-report.json",
            artifact,
        )

    experiment._ensure_report_outside_artifact(
        tmp_path / "output" / "joint-report.json",
        artifact,
    )


def test_episode_guard_selects_pages_in_full_sequence(monkeypatch, tmp_path: Path):
    spans = (
        {"subtitle_id": "S0001", "word_start": 0, "word_end": 0, "translated": "一"},
        {"subtitle_id": "S0002", "word_start": 1, "word_end": 1, "translated": "二"},
    )
    run = experiment.ArtifactRun(
        artifact_dir=tmp_path,
        words=(
            {"word_id": 0, "surface": "one", "start_ms": 0, "end_ms": 500},
            {"word_id": 1, "surface": "two", "start_ms": 500, "end_ms": 1000},
        ),
        spans=spans,
        timeline={
            "S0001": {"start_ms": 0, "end_ms": 500},
            "S0002": {"start_ms": 500, "end_ms": 1000},
        },
        evidence={},
        saved_plans={},
        ledger_hash="ledger",
        source_segments=(),
    )
    monkeypatch.setattr(
        experiment,
        "_cue_for_range",
        lambda _run, _start, _end, subtitle_id, **_kwargs: SimpleNamespace(
            subtitle_id=subtitle_id,
            en="one" if subtitle_id == "S0001" else "two",
        ),
    )

    def page(english: str, word_id: int) -> dict:
        return {
            "english": english,
            "word_start": word_id,
            "word_end": word_id,
            "word_count": 1,
            "start_ms": word_id * 500,
            "end_ms": (word_id + 1) * 500,
            "duration_ms": 500,
            "font_size": 56,
            "line_count": 1,
            "pressure": 0.5,
            "boundary_classification": "allow",
            "boundary_issues": [],
        }

    bundles = {
        "S0001": {"plan": {"pages": [page("one", 0)]}},
        "S0002": {"plan": {"pages": [page("two", 1)]}},
    }
    monkeypatch.setattr(
        experiment.page_planner,
        "_build_article_english_page_plan",
        lambda cue, _draw, *, _return_candidates: {
            "status": "candidate_bundle",
            "candidates": [bundles[cue.subtitle_id]],
            "shadow_candidates": [bundles[cue.subtitle_id]],
        },
    )
    selected_group_counts = []

    def select(groups):
        selected_group_counts.append(len(groups))
        return [group[0] for group in groups]

    monkeypatch.setattr(
        experiment.page_planner,
        "_select_article_page_plan_sequence",
        select,
    )
    monkeypatch.setattr(
        experiment.page_planner,
        "_select_article_dominant_readability_candidate",
        lambda _cue, candidate, _shadow: candidate,
    )
    monkeypatch.setattr(
        experiment.page_planner,
        "_finalize_article_sequence_candidate",
        lambda candidate, _bundle: candidate["plan"],
    )
    monkeypatch.setattr(
        experiment.page_planner,
        "_finalize_article_same_screen_layout",
        lambda _cue, _draw, plan: plan,
    )
    monkeypatch.setattr(experiment, "_page_summary", lambda value: dict(value))

    plans, failures = experiment._episode_current_plans(run)

    assert selected_group_counts == [2]
    assert failures == []
    assert list(plans) == ["S0001", "S0002"]
