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
