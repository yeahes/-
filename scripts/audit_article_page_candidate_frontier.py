"""Compare production and shadow article-page candidate frontiers read-only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from app.core.utils import podcast_learning_video


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_cues(artifact_dir: Path) -> list[podcast_learning_video.Cue]:
    ledger_payload = _read_json(artifact_dir / "word-ledger.json")
    spans_payload = _read_json(artifact_dir / "subtitle-spans.json")
    timeline_payload = _read_json(artifact_dir / "final-cue-timeline.json")
    evidence_payload = _read_json(artifact_dir / "display-boundary-evidence.json")

    ledger = {
        int(item["word_id"]): dict(item)
        for item in ledger_payload.get("words", [])
    }
    timeline = {
        str(item["subtitle_id"]): dict(item)
        for item in timeline_payload.get("records", [])
    }
    evidence = dict(evidence_payload.get("boundaries") or {})
    cues: list[podcast_learning_video.Cue] = []
    for index, span in enumerate(spans_payload, start=1):
        subtitle_id = str(span.get("subtitle_id") or "")
        record = timeline.get(subtitle_id)
        if not subtitle_id or record is None:
            raise ValueError(f"missing final timeline record for {subtitle_id or index}")
        word_start = int(span["word_start"])
        word_end = int(span["word_end"])
        word_timing = []
        for word_id in range(word_start, word_end + 1):
            item = ledger.get(word_id)
            if item is None:
                raise ValueError(f"missing word-ledger record {word_id}")
            word_timing.append(
                {
                    "word_id": word_id,
                    "surface": str(item.get("surface") or ""),
                    "start": int(item["start_ms"]) / 1000.0,
                    "end": int(item["end_ms"]) / 1000.0,
                }
            )
        english = " ".join(str(span.get("original") or "").split())
        ledger_english = " ".join(item["surface"] for item in word_timing)
        if english != ledger_english:
            raise ValueError(f"word-ledger English mismatch for {subtitle_id}")
        cues.append(
            podcast_learning_video.Cue(
                index=index,
                start=int(record["start_ms"]) / 1000.0,
                end=int(record["end_ms"]) / 1000.0,
                en=english,
                zh=str(span.get("translated") or ""),
                speaker="",
                subtitle_id=subtitle_id,
                word_timing=tuple(word_timing),
                display_boundary_evidence=evidence,
            )
        )
    return cues


def _final_plan(
    cue: podcast_learning_video.Cue,
    draw: ImageDraw.ImageDraw,
    bundle: Mapping[str, object],
    candidate: Mapping[str, object],
) -> dict:
    plan = podcast_learning_video._finalize_article_sequence_candidate(
        candidate,
        bundle,
    )
    return podcast_learning_video._finalize_article_same_screen_layout(
        cue,
        draw,
        plan,
    )


def _page_summary(page: Mapping[str, object]) -> dict[str, object]:
    english = " ".join(str(page.get("en") or "").split())
    return {
        "english": english,
        "word_start": int(page.get("global_word_start", page.get("word_start", 0))),
        "word_end": int(page.get("global_word_end", page.get("word_end", 0))),
        "word_count": len(english.split()),
        "start_ms": round(float(page.get("start") or 0.0) * 1000),
        "end_ms": round(float(page.get("end") or 0.0) * 1000),
        "font_size": int(page.get("english_font_size") or 0),
        "line_count": len(list(page.get("en_lines") or [])),
        "pressure": podcast_learning_video._article_display_page_pressure(page),
        "boundary_classification": str(
            (page.get("boundary_before") or {}).get("classification") or "allow"
        ),
        "boundary_issues": list(
            (page.get("boundary_before") or {}).get("issue_codes") or []
        ),
    }


def _plan_signature(plan: Mapping[str, object]) -> tuple[tuple[int, int], ...]:
    return tuple(
        (int(page.get("word_start") or 0), int(page.get("word_end") or 0))
        for page in plan.get("pages") or []
    )


def _aggregate(records: Sequence[Mapping[str, object]], key: str) -> dict[str, object]:
    pages = [
        dict(page)
        for record in records
        for page in (record.get(key) or {}).get("pages", [])
    ]
    return {
        "page_count": len(pages),
        "pages_over_14_words": sum(int(page["word_count"]) > 14 for page in pages),
        "pages_over_16_words": sum(int(page["word_count"]) > 16 for page in pages),
        "pages_over_pressure_1": sum(float(page["pressure"]) > 1.0 for page in pages),
        "pages_below_56px": sum(int(page["font_size"]) < 56 for page in pages),
        "pages_over_two_lines": sum(int(page["line_count"]) > 2 for page in pages),
        "review_boundaries": sum(
            page["boundary_classification"] == "review" for page in pages
        ),
        "max_words": max((int(page["word_count"]) for page in pages), default=0),
        "max_pressure": max((float(page["pressure"]) for page in pages), default=0.0),
    }


_MATERIAL_FINITE_AUXILIARIES = frozenset(
    {
        "am",
        "are",
        "be",
        "been",
        "being",
        "can",
        "could",
        "did",
        "do",
        "does",
        "had",
        "has",
        "have",
        "is",
        "may",
        "might",
        "must",
        "shall",
        "should",
        "was",
        "were",
        "will",
        "would",
    }
)


def _material_boundary_has_support(
    decision: Mapping[str, object],
    page: Mapping[str, object],
) -> bool:
    if str(decision.get("classification") or "allow") != "review":
        return True
    if decision.get("complete_prepositional_continuation"):
        words = [
            "".join(character for character in token.casefold() if character.isalpha())
            for token in str(page.get("en") or "").split()
        ]
        if any(word in _MATERIAL_FINITE_AUXILIARIES for word in words[1:]):
            return False
    return any(
        bool(decision.get(key))
        for key in (
            "strong_pause_evidence",
            "complete_page_clause_start",
            "complete_content_clause_start",
            "complete_title_restart",
            "balanced_predicate_restart",
            "complete_prepositional_continuation",
            "complete_object_continuation",
            "forced_complete_predicate_phrase",
            "forced_complete_to_phrase",
        )
    )


def _material_candidate_metrics(
    candidate: Mapping[str, object],
) -> dict[str, float | int]:
    pages = list((candidate.get("plan") or {}).get("pages") or [])
    word_counts = [len(str(page.get("en") or "").split()) for page in pages]
    font_sizes = [
        int(
            page.get("english_font_size")
            or podcast_learning_video.ARTICLE_SUBTITLE_EN_FONT_SIZE
        )
        for page in pages
    ]
    stored_pressures = tuple(
        float(value) for value in candidate.get("page_pressures") or ()
    )
    if len(stored_pressures) == len(pages):
        pressures = list(stored_pressures)
    else:
        pressures = [
            podcast_learning_video._article_display_page_pressure(page)
            for page in pages
        ]
    review_pages = [
        page
        for page in pages[1:]
        if str((page.get("boundary_before") or {}).get("classification") or "allow")
        == "review"
    ]
    minimum_words = podcast_learning_video.ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
    soft_max_words = podcast_learning_video.ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS
    default_font = podcast_learning_video.ARTICLE_SUBTITLE_EN_FONT_SIZE
    return {
        "page_count": len(pages),
        "under_five_pages": sum(value < 5 for value in word_counts),
        "short_page_deficit": sum(
            max(0, minimum_words - value) for value in word_counts
        ),
        "over_16_word_excess": sum(
            max(0, value - soft_max_words) for value in word_counts
        ),
        "font_deficit": sum(max(0, default_font - value) for value in font_sizes),
        "three_line_pages": sum(
            len(list(page.get("en_lines") or [])) > 2 for page in pages
        ),
        "review_boundaries": len(review_pages),
        "unsupported_review_boundaries": sum(
            not _material_boundary_has_support(
                page.get("boundary_before") or {},
                page,
            )
            for page in review_pages
        ),
        "severe_risk_count": int(candidate.get("severe_risk_count") or 0),
        "incomplete_review_count": int(
            candidate.get("incomplete_review_count") or 0
        ),
        "risk_score": int(candidate.get("risk_score") or 0),
        "max_pressure": max(pressures, default=0.0),
        "word_count_imbalance": (
            max(word_counts, default=0) - min(word_counts, default=0)
        ),
    }


def _material_improvement_reason(
    baseline: Mapping[str, float | int],
    candidate: Mapping[str, float | int],
) -> str | None:
    short_relief = int(candidate["short_page_deficit"]) < int(
        baseline["short_page_deficit"]
    )
    over_16_relief = int(candidate["over_16_word_excess"]) < int(
        baseline["over_16_word_excess"]
    )
    font_relief = int(candidate["font_deficit"]) < int(baseline["font_deficit"])
    pressure_relief = (
        float(baseline["max_pressure"]) - float(candidate["max_pressure"])
        >= podcast_learning_video.ARTICLE_PAGE_PRESSURE_TRANSITION_FREE_DELTA
    )
    if short_relief and over_16_relief:
        return "short_page_and_over_16_relief"
    if short_relief:
        return "short_page_relief"
    if over_16_relief:
        return "over_16_relief"
    if font_relief:
        return "font_floor_relief"
    if pressure_relief:
        return "maximum_pressure_relief"
    return None


def _select_material_readability_candidate(
    baseline: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], str]:
    """Select only non-regressive candidates with material display relief.

    This is an offline policy probe. It deliberately ignores small balance-only
    improvements so the experiment cannot justify broad page churn.
    """
    baseline_metrics = _material_candidate_metrics(baseline)
    eligible: list[
        tuple[
            tuple[float | int, ...],
            Mapping[str, object],
            str,
        ]
    ] = []
    for candidate in candidates:
        if candidate is baseline:
            continue
        metrics = _material_candidate_metrics(candidate)
        if (
            int(metrics["unsupported_review_boundaries"]) > 0
            or int(metrics["under_five_pages"])
            > int(baseline_metrics["under_five_pages"])
            or int(metrics["short_page_deficit"])
            > int(baseline_metrics["short_page_deficit"])
            or int(metrics["over_16_word_excess"])
            > int(baseline_metrics["over_16_word_excess"])
            or int(metrics["font_deficit"])
            > int(baseline_metrics["font_deficit"])
            or int(metrics["three_line_pages"])
            > int(baseline_metrics["three_line_pages"])
            or int(metrics["review_boundaries"])
            > int(baseline_metrics["review_boundaries"])
            or int(metrics["severe_risk_count"])
            > int(baseline_metrics["severe_risk_count"])
            or int(metrics["incomplete_review_count"])
            > int(baseline_metrics["incomplete_review_count"])
            or int(metrics["risk_score"]) > int(baseline_metrics["risk_score"])
            or float(metrics["max_pressure"])
            > float(baseline_metrics["max_pressure"])
            or int(metrics["word_count_imbalance"])
            > int(baseline_metrics["word_count_imbalance"])
            or int(metrics["page_count"])
            > int(baseline_metrics["page_count"]) + 1
        ):
            continue
        reason = _material_improvement_reason(baseline_metrics, metrics)
        if reason is None:
            continue
        rank = (
            int(metrics["under_five_pages"]),
            int(metrics["short_page_deficit"]),
            int(metrics["over_16_word_excess"]),
            int(metrics["font_deficit"]),
            int(metrics["unsupported_review_boundaries"]),
            int(metrics["severe_risk_count"]),
            int(metrics["incomplete_review_count"]),
            float(metrics["max_pressure"]),
            int(metrics["word_count_imbalance"]),
            int(metrics["risk_score"]),
            int(metrics["page_count"]),
            float(candidate.get("quality_cost") or 0.0),
        )
        eligible.append((rank, candidate, reason))
    if not eligible:
        return baseline, "baseline_retained"
    _rank, selected, reason = min(eligible, key=lambda item: item[0])
    return selected, reason


def audit(
    artifact_dir: Path,
    *,
    subtitle_ids: Sequence[str] = (),
    include_frontier: bool = False,
) -> dict[str, object]:
    cues = _load_cues(artifact_dir)
    requested_ids = {str(value) for value in subtitle_ids if str(value)}
    if requested_ids:
        missing_ids = requested_ids - {cue.subtitle_id for cue in cues}
        if missing_ids:
            raise ValueError(
                "unknown subtitle IDs: " + ", ".join(sorted(missing_ids))
            )
    draw = ImageDraw.Draw(
        Image.new(
            "RGB",
            (podcast_learning_video.ARTICLE_WIDTH, podcast_learning_video.ARTICLE_HEIGHT),
        )
    )
    bundles = [
        podcast_learning_video._build_article_english_page_plan(
            cue,
            draw,
            _return_candidates=True,
        )
        for cue in cues
    ]
    bundle_entries = [
        (cue, bundle)
        for cue, bundle in zip(cues, bundles)
        if bundle.get("status") == "candidate_bundle"
    ]
    failures = [
        {
            "subtitle_id": cue.subtitle_id,
            **dict(bundle),
        }
        for cue, bundle in zip(cues, bundles)
        if bundle.get("status") != "candidate_bundle"
        and (not requested_ids or cue.subtitle_id in requested_ids)
    ]

    production_selected = podcast_learning_video._select_article_page_plan_sequence(
        [bundle["candidates"] for _cue, bundle in bundle_entries]
    )
    shadow_selected = podcast_learning_video._select_article_page_plan_sequence(
        [bundle["shadow_candidates"] for _cue, bundle in bundle_entries]
    )
    if (
        len(production_selected) != len(bundle_entries)
        or len(shadow_selected) != len(bundle_entries)
    ):
        raise ValueError("candidate sequence selection did not cover every cue")

    conservative_selected = [
        podcast_learning_video._select_article_dominant_readability_candidate(
            cue,
            production_candidate,
            bundle["shadow_candidates"],
        )
        for (cue, bundle), production_candidate in zip(
            bundle_entries,
            production_selected,
        )
    ]
    material_selections = [
        _select_material_readability_candidate(
            production_candidate,
            bundle["shadow_candidates"],
        )
        for (_cue, bundle), production_candidate in zip(
            bundle_entries,
            production_selected,
        )
    ]
    records = []
    for (
        (cue, bundle),
        production_candidate,
        shadow_candidate,
        conservative_candidate,
        material_selection,
    ) in zip(
        bundle_entries,
        production_selected,
        shadow_selected,
        conservative_selected,
        material_selections,
    ):
        if requested_ids and cue.subtitle_id not in requested_ids:
            continue
        material_candidate, material_reason = material_selection
        production_plan = _final_plan(cue, draw, bundle, production_candidate)
        shadow_plan = _final_plan(cue, draw, bundle, shadow_candidate)
        conservative_plan = _final_plan(
            cue,
            draw,
            bundle,
            conservative_candidate,
        )
        material_plan = _final_plan(
            cue,
            draw,
            bundle,
            material_candidate,
        )
        production_pages = [
            _page_summary(page) for page in production_plan.get("pages") or []
        ]
        shadow_pages = [
            _page_summary(page) for page in shadow_plan.get("pages") or []
        ]
        conservative_pages = [
            _page_summary(page)
            for page in conservative_plan.get("pages") or []
        ]
        material_pages = [
            _page_summary(page) for page in material_plan.get("pages") or []
        ]
        if " ".join(page["english"] for page in production_pages) != cue.en:
            raise ValueError(f"production English coverage failed for {cue.subtitle_id}")
        if " ".join(page["english"] for page in shadow_pages) != cue.en:
            raise ValueError(f"shadow English coverage failed for {cue.subtitle_id}")
        if " ".join(page["english"] for page in conservative_pages) != cue.en:
            raise ValueError(
                f"conservative English coverage failed for {cue.subtitle_id}"
            )
        if " ".join(page["english"] for page in material_pages) != cue.en:
            raise ValueError(
                f"material candidate English coverage failed for {cue.subtitle_id}"
            )
        record = {
                "subtitle_id": cue.subtitle_id,
                "english": cue.en,
                "changed": _plan_signature(production_plan)
                != _plan_signature(shadow_plan),
                "production": {
                    "page_count": len(production_pages),
                    "sequence_cost": podcast_learning_video._article_candidate_sequence_cost(
                        production_candidate
                    ),
                    "pages": production_pages,
                },
                "shadow": {
                    "page_count": len(shadow_pages),
                    "sequence_cost": podcast_learning_video._article_candidate_sequence_cost(
                        shadow_candidate
                    ),
                    "pages": shadow_pages,
                },
                "conservative_changed": _plan_signature(production_plan)
                != _plan_signature(conservative_plan),
                "conservative": {
                    "page_count": len(conservative_pages),
                    "sequence_cost": podcast_learning_video._article_candidate_sequence_cost(
                        conservative_candidate
                    ),
                    "pages": conservative_pages,
                },
                "material_changed": _plan_signature(production_plan)
                != _plan_signature(material_plan),
                "material_selection_reason": material_reason,
                "material": {
                    "page_count": len(material_pages),
                    "sequence_cost": podcast_learning_video._article_candidate_sequence_cost(
                        material_candidate
                    ),
                    "metrics": _material_candidate_metrics(material_candidate),
                    "pages": material_pages,
                },
            }
        if include_frontier:
            record["frontier"] = [
                {
                    "page_count": int(candidate.get("page_count") or 0),
                    "fallback_tier": podcast_learning_video._article_candidate_fallback_tier(
                        candidate
                    ),
                    "risk_score": int(candidate.get("risk_score") or 0),
                    "sequence_cost": podcast_learning_video._article_candidate_sequence_cost(
                        candidate
                    ),
                    "pages": [
                        _page_summary(page)
                        for page in (candidate.get("plan") or {}).get("pages", [])
                    ],
                }
                for candidate in bundle["shadow_candidates"]
            ]
        records.append(record)
    report = {
        "schema_version": 2,
        "status": "partial" if failures else "ok",
        "artifact_dir": str(artifact_dir.resolve()),
        "source_cue_count": len(cues),
        "cue_count": len(records),
        "failure_count": len(failures),
        "failures": failures,
        "changed_cue_count": sum(bool(record["changed"]) for record in records),
        "production": _aggregate(records, "production"),
        "shadow": _aggregate(records, "shadow"),
        "conservative_changed_cue_count": sum(
            bool(record["conservative_changed"]) for record in records
        ),
        "conservative": _aggregate(records, "conservative"),
        "material_changed_cue_count": sum(
            bool(record["material_changed"]) for record in records
        ),
        "material": _aggregate(records, "material"),
        "material_policy": {
            "name": "material-readability-non-regression-v1",
            "minimum_page_words": 5,
            "pressure_relief_minimum": podcast_learning_video.ARTICLE_PAGE_PRESSURE_TRANSITION_FREE_DELTA,
            "production_behavior_changed": False,
        },
        "changed_cues": [record for record in records if record["changed"]],
        "conservative_changed_cues": [
            record for record in records if record["conservative_changed"]
        ],
        "material_changed_cues": [
            record for record in records if record["material_changed"]
        ],
    }
    if include_frontier:
        report["cues"] = records
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--subtitle-id", action="append", default=[])
    parser.add_argument("--include-frontier", action="store_true")
    args = parser.parse_args()
    report = audit(
        args.artifact_dir,
        subtitle_ids=args.subtitle_id,
        include_frontier=args.include_frontier,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": report.get("status"),
                    "cue_count": report.get("cue_count"),
                    "changed_cue_count": report.get("changed_cue_count"),
                    "conservative_changed_cue_count": report.get(
                        "conservative_changed_cue_count"
                    ),
                    "production": report.get("production"),
                    "shadow": report.get("shadow"),
                    "conservative": report.get("conservative"),
                    "material_changed_cue_count": report.get(
                        "material_changed_cue_count"
                    ),
                    "material": report.get("material"),
                    "output": str(args.output.resolve()),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
