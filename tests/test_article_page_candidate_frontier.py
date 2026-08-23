from __future__ import annotations

from types import SimpleNamespace

from scripts import audit_article_page_candidate_frontier as frontier


def _candidate(english: str) -> dict:
    return {
        "page_count": 1,
        "quality_cost": 0.0,
        "plan": {
            "pages": [
                {
                    "en": english,
                    "word_start": 0,
                    "word_end": 0,
                    "english_font_size": 56,
                    "en_lines": [english],
                    "start": 0.0,
                    "end": 1.0,
                }
            ]
        },
    }


def _rank_candidate(
    word_counts: tuple[int, ...],
    pressures: tuple[float, ...],
    *,
    fonts: tuple[int, ...] | None = None,
    boundary: dict | None = None,
    risk_score: int = 0,
    severe_risk_count: int = 0,
    incomplete_review_count: int = 0,
    relaxed_raw_hard_count: int = 0,
) -> dict:
    selected_fonts = fonts or tuple(56 for _value in word_counts)
    pages = []
    word_start = 0
    for index, (word_count, font_size) in enumerate(
        zip(word_counts, selected_fonts)
    ):
        page = {
            "en": " ".join(f"w{value}" for value in range(word_start, word_start + word_count)),
            "word_start": word_start,
            "word_end": word_start + word_count - 1,
            "english_font_size": font_size,
            "en_lines": ["line"],
        }
        if index:
            page["boundary_before"] = dict(boundary or {"classification": "allow"})
        pages.append(page)
        word_start += word_count
    return {
        "page_count": len(pages),
        "quality_cost": 0.0,
        "risk_score": risk_score,
        "severe_risk_count": severe_risk_count,
        "incomplete_review_count": incomplete_review_count,
        "relaxed_raw_hard_count": relaxed_raw_hard_count,
        "page_pressures": pressures,
        "plan": {"pages": pages},
    }


def test_material_selector_removes_overlong_four_word_lead_in():
    baseline = _rank_candidate(
        (4, 17),
        (0.7, 1.417),
        risk_score=2,
        boundary={
            "classification": "review",
            "complete_prepositional_continuation": True,
        },
    )
    candidate = _rank_candidate(
        (16, 5),
        (1.333, 0.8),
        risk_score=2,
        boundary={
            "classification": "review",
            "complete_prepositional_continuation": True,
        },
    )
    candidate["plan"]["pages"][1]["en"] = "in every major overseas market."

    selected, reason = frontier._select_material_readability_candidate(
        baseline,
        (baseline, candidate),
    )

    assert selected is candidate
    assert reason == "short_page_and_over_16_relief"


def test_material_selector_rejects_false_prepositional_completion():
    baseline = _rank_candidate(
        (4, 17),
        (0.7, 1.417),
        risk_score=2,
        boundary={
            "classification": "review",
        },
    )
    candidate = _rank_candidate(
        (16, 5),
        (1.333, 0.8),
        risk_score=2,
        boundary={
            "classification": "review",
            "complete_prepositional_continuation": True,
        },
    )
    candidate["plan"]["pages"][1]["en"] = "in tariff rates would backfire."

    selected, reason = frontier._select_material_readability_candidate(
        baseline,
        (baseline, candidate),
    )

    assert selected is baseline
    assert reason == "baseline_retained"


def test_material_selector_accepts_complete_predicate_to_remove_short_tail():
    baseline = _rank_candidate(
        (12, 5),
        (1.1, 0.8),
        risk_score=2,
        boundary={
            "classification": "review",
            "complete_prepositional_continuation": True,
        },
    )
    candidate = _rank_candidate(
        (8, 9),
        (0.955, 0.9),
        risk_score=2,
        relaxed_raw_hard_count=1,
        boundary={
            "classification": "review",
            "relaxed_raw_hard": True,
            "forced_complete_predicate_phrase": True,
        },
    )

    selected, reason = frontier._select_material_readability_candidate(
        baseline,
        (baseline, candidate),
    )

    assert selected is candidate
    assert reason == "short_page_relief"


def test_material_selector_uses_supported_pause_for_pressure_relief():
    baseline = _rank_candidate(
        (16, 6),
        (1.333, 0.8),
        risk_score=2,
        boundary={
            "classification": "review",
            "complete_object_continuation": True,
        },
    )
    candidate = _rank_candidate(
        (11, 11),
        (1.028, 0.95),
        risk_score=2,
        relaxed_raw_hard_count=1,
        boundary={
            "classification": "review",
            "relaxed_raw_hard": True,
            "strong_pause_evidence": True,
            "balanced_predicate_restart": True,
        },
    )

    selected, reason = frontier._select_material_readability_candidate(
        baseline,
        (baseline, candidate),
    )

    assert selected is candidate
    assert reason == "maximum_pressure_relief"


def test_material_selector_rejects_visual_churn_and_font_regression():
    baseline = _rank_candidate((12, 7), (1.223, 0.9), risk_score=2)
    merely_balanced = _rank_candidate(
        (9, 10),
        (1.345, 0.9),
        risk_score=2,
        relaxed_raw_hard_count=1,
        boundary={
            "classification": "review",
            "relaxed_raw_hard": True,
            "forced_complete_predicate_phrase": True,
        },
    )
    lower_font = _rank_candidate(
        (10, 9),
        (1.0, 0.9),
        fonts=(52, 56),
        risk_score=2,
        boundary={"classification": "allow"},
    )

    selected, reason = frontier._select_material_readability_candidate(
        baseline,
        (baseline, merely_balanced, lower_font),
    )

    assert selected is baseline
    assert reason == "baseline_retained"


def test_targeted_audit_keeps_full_sequence_and_reports_local_failure(monkeypatch):
    cues = [
        SimpleNamespace(subtitle_id="S0001", en="one"),
        SimpleNamespace(subtitle_id="S0002", en="two"),
        SimpleNamespace(subtitle_id="S0003", en="three"),
    ]
    monkeypatch.setattr(frontier, "_load_cues", lambda _path: cues)

    def build(cue, _draw, *, _return_candidates):
        assert _return_candidates is True
        if cue.subtitle_id == "S0002":
            return {
                "status": "render_structural_overflow",
                "errors": [{"reason": "no_partition"}],
            }
        candidate = _candidate(cue.en)
        return {
            "status": "candidate_bundle",
            "candidates": [candidate],
            "shadow_candidates": [candidate],
            "preferred_page_count": 1,
            "candidate_mode": "strict",
        }

    selected_group_counts = []

    def select(groups):
        selected_group_counts.append(len(groups))
        return [group[0] for group in groups]

    monkeypatch.setattr(
        frontier.podcast_learning_video,
        "_build_article_english_page_plan",
        build,
    )
    monkeypatch.setattr(
        frontier.podcast_learning_video,
        "_select_article_page_plan_sequence",
        select,
    )
    monkeypatch.setattr(
        frontier.podcast_learning_video,
        "_select_article_dominant_readability_candidate",
        lambda _cue, candidate, _shadow: candidate,
    )
    monkeypatch.setattr(
        frontier,
        "_final_plan",
        lambda _cue, _draw, _bundle, candidate: candidate["plan"],
    )

    report = frontier.audit(
        SimpleNamespace(resolve=lambda: "artifact"),
        subtitle_ids=("S0001", "S0002"),
        include_frontier=True,
    )

    assert selected_group_counts == [2, 2]
    assert report["status"] == "partial"
    assert report["source_cue_count"] == 3
    assert report["cue_count"] == 1
    assert report["failure_count"] == 1
    assert report["failures"][0]["subtitle_id"] == "S0002"
    assert [record["subtitle_id"] for record in report["cues"]] == ["S0001"]
    assert report["material_changed_cue_count"] == 0
    assert report["cues"][0]["material_selection_reason"] == "baseline_retained"
