"""Evaluate a completed subtitle run against a manually curated golden reference.

This tool is intentionally offline and read-only. It does not alter ASR,
English boundaries, translations, timing, or any runtime cache. A golden
reference measures only facts a reviewer has supplied explicitly. Schema v1
keeps the original transcript/entity/boundary checks. Schema v2 adds stable-run
hard gates and four weighted quality components without calling a model.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


LATEST_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {1, 2}
DEFAULT_V2_WEIGHTS = {
    "english_segmentation": 0.25,
    "parent_translation": 0.35,
    "fixed_id_allocation": 0.15,
    "display_pages": 0.25,
}
DEFAULT_V2_OVERALL_THRESHOLD = 0.90
DEFAULT_V2_COMPONENT_THRESHOLD = 0.85
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_optional_json(path: Path) -> Any | None:
    return _read_json(path) if path.is_file() else None


def _normalise_tokens(text: str) -> List[str]:
    return [match.group(0).casefold() for match in _WORD_RE.finditer(text or "")]


def _normalise_chinese(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _resolve_artifact_dir(run_root: Path) -> Path:
    run_root = run_root.resolve()
    if (run_root / "subtitle-spans.json").is_file():
        return run_root
    manifest_candidates = [
        run_root / "stable-final-manifest.json",
        run_root / "subtitle" / "stable-final-manifest.json",
    ]
    for manifest_path in manifest_candidates:
        if not manifest_path.is_file():
            continue
        manifest = _read_json(manifest_path)
        if not isinstance(manifest, Mapping):
            raise ValueError("stable_manifest_invalid")
        run_dir_text = str(manifest.get("stable_run_dir") or "").strip()
        if not run_dir_text:
            raise ValueError("stable_manifest_run_dir_missing")
        run_dir = Path(run_dir_text)
        if not run_dir.is_absolute():
            run_dir = (manifest_path.parent / run_dir).resolve()
        candidates = sorted(
            path
            for path in run_dir.glob("*-artifacts")
            if (path / "subtitle-spans.json").is_file()
        )
        if len(candidates) != 1:
            raise ValueError(
                "stable_manifest_artifact_dir_missing"
                if not candidates
                else "stable_manifest_artifact_dir_ambiguous"
            )
        return candidates[0]
    candidates = sorted(
        path
        for path in run_root.glob("**/*-artifacts")
        if (path / "subtitle-spans.json").is_file()
    )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("artifact_dir_not_found")
    raise ValueError("artifact_dir_ambiguous")


def _as_list(value: Any, name: str) -> List[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"golden_reference_invalid_{name}")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"golden_reference_invalid_{name}")
    return list(value)


def _load_run(artifact_dir: Path) -> Dict[str, Any]:
    spans = _as_list(_read_json(artifact_dir / "subtitle-spans.json"), "subtitle_spans")
    ledger_payload = _read_json(artifact_dir / "word-ledger.json")
    words = ledger_payload.get("words") if isinstance(ledger_payload, Mapping) else None
    if not isinstance(words, list) or not all(isinstance(item, Mapping) for item in words):
        raise ValueError("run_word_ledger_invalid")

    ids: set[str] = set()
    normalised_spans: List[Dict[str, Any]] = []
    for item in spans:
        subtitle_id = str(item.get("subtitle_id") or "").strip()
        if not subtitle_id or subtitle_id in ids:
            raise ValueError("run_subtitle_ids_invalid")
        ids.add(subtitle_id)
        normalised_spans.append(
            {
                "subtitle_id": subtitle_id,
                "english": str(item.get("original", item.get("english", "")) or ""),
                "chinese": str(item.get("translated", item.get("chinese", "")) or ""),
                "word_start": item.get("word_start"),
                "word_end": item.get("word_end"),
            }
        )

    normalised_words: List[Dict[str, Any]] = []
    for position, word in enumerate(words):
        word_id = word.get("word_id", position)
        try:
            word_id = int(word_id)
            start_ms = int(word.get("start_ms", word.get("start_time", 0)) or 0)
            end_ms = int(word.get("end_ms", word.get("end_time", 0)) or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("run_word_ledger_invalid") from exc
        normalised_words.append(
            {
                "word_id": word_id,
                "surface": str(word.get("surface", word.get("text", "")) or ""),
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
        )
    if [word["word_id"] for word in normalised_words] != list(range(len(normalised_words))):
        raise ValueError("run_word_ledger_ids_invalid")

    return {
        "artifact_dir": str(artifact_dir),
        "spans": normalised_spans,
        "words": normalised_words,
    }


def _flatten_ledger_tokens(words: Sequence[Mapping[str, Any]]) -> tuple[List[str], List[int]]:
    tokens: List[str] = []
    word_ids: List[int] = []
    for word in words:
        word_id = int(word["word_id"])
        for token in _normalise_tokens(str(word.get("surface") or "")):
            tokens.append(token)
            word_ids.append(word_id)
    return tokens, word_ids


def _span_ledger_tokens(run: Mapping[str, Any], word_start: int, word_end: int) -> List[str]:
    words = run["words"]
    if word_start < 0 or word_end < word_start or word_end >= len(words):
        return []
    return _normalise_tokens(
        " ".join(str(words[index]["surface"]) for index in range(word_start, word_end + 1))
    )


def _append_gate(failures: List[Dict[str, Any]], code: str, **details: Any) -> None:
    failures.append({"code": code, **details})


def _validate_span_contract(run: Mapping[str, Any], failures: List[Dict[str, Any]]) -> None:
    spans = list(run["spans"])
    words = list(run["words"])
    expected_start = 0
    for span in spans:
        try:
            word_start = int(span["word_start"])
            word_end = int(span["word_end"])
        except (TypeError, ValueError):
            _append_gate(failures, "run_span_range_invalid", subtitle_id=span["subtitle_id"])
            continue
        if word_start != expected_start or word_end < word_start or word_end >= len(words):
            _append_gate(
                failures,
                "run_span_coverage_invalid",
                subtitle_id=span["subtitle_id"],
                expected_word_start=expected_start,
                actual_word_start=word_start,
                actual_word_end=word_end,
            )
        expected_tokens = _span_ledger_tokens(run, word_start, word_end)
        actual_tokens = _normalise_tokens(str(span["english"]))
        if expected_tokens != actual_tokens:
            _append_gate(failures, "run_span_english_ledger_mismatch", subtitle_id=span["subtitle_id"])
        expected_start = word_end + 1
    if expected_start != len(words):
        _append_gate(
            failures,
            "run_span_word_coverage_incomplete",
            covered_word_count=expected_start,
            ledger_word_count=len(words),
        )


def _load_v2_parent_chinese(
    artifact_dir: Path,
    run: Dict[str, Any],
    ledger_payload: Mapping[str, Any],
    timeline_payload: Any,
    failures: List[Dict[str, Any]],
) -> tuple[Dict[str, str], str, Dict[str, Mapping[str, Any]]]:
    authority_path = artifact_dir / "authoritative-parent-chinese.json"
    by_id: Dict[str, str] = {}
    authority_records: Dict[str, Mapping[str, Any]] = {}
    if authority_path.is_file():
        try:
            from app.core.subtitle_processor.authoritative_parent_chinese import (
                validate_authoritative_parent_chinese_artifact,
            )

            validated = validate_authoritative_parent_chinese_artifact(
                _read_json(authority_path),
                expected_word_ledger_hash=str(ledger_payload.get("hash") or ""),
            )
            records = list(validated.get("records") or [])
            authority_records = {str(item["subtitle_id"]): item for item in records}
            by_id = {str(item["subtitle_id"]): str(item["chinese"]) for item in records}
        except (ImportError, OSError, ValueError) as exc:
            _append_gate(failures, "run_parent_chinese_authority_invalid", error=str(exc))
            return {}, "invalid_authority", {}
        source = "authoritative-parent-chinese.json"
    else:
        records = (
            list(timeline_payload.get("records") or [])
            if isinstance(timeline_payload, Mapping)
            else []
        )
        for position, item in enumerate(records):
            subtitle_id = str(item.get("subtitle_id") or "")
            chinese = str(item.get("translated", item.get("chinese", "")) or "")
            span = run["spans"][position] if position < len(run["spans"]) else None
            if span is None or (
                subtitle_id != str(span["subtitle_id"])
                or int(item.get("word_start", -1)) != int(span["word_start"])
                or int(item.get("word_end", -1)) != int(span["word_end"])
                or _normalise_tokens(str(item.get("original", item.get("english", "")) or ""))
                != _normalise_tokens(str(span["english"]))
            ):
                _append_gate(
                    failures,
                    "run_parent_chinese_legacy_identity_mismatch",
                    subtitle_id=subtitle_id,
                )
                continue
            if subtitle_id and chinese:
                by_id[subtitle_id] = chinese
        source = "final-cue-timeline.json" if by_id else "missing"

    expected_ids = [str(item["subtitle_id"]) for item in run["spans"]]
    if list(by_id) != expected_ids:
        _append_gate(
            failures,
            "run_parent_chinese_id_mismatch",
            expected_count=len(expected_ids),
            actual_count=len(by_id),
        )
    for span in run["spans"]:
        subtitle_id = str(span["subtitle_id"])
        if not _normalise_chinese(by_id.get(subtitle_id, "")):
            _append_gate(failures, "run_parent_chinese_missing", subtitle_id=subtitle_id)
        authority = authority_records.get(subtitle_id)
        if authority is not None and (
            int(authority.get("word_start", -1)) != int(span["word_start"])
            or int(authority.get("word_end", -1)) != int(span["word_end"])
            or _normalise_tokens(str(authority.get("english") or ""))
            != _normalise_tokens(str(span["english"]))
        ):
            _append_gate(failures, "run_parent_chinese_identity_mismatch", subtitle_id=subtitle_id)

    translations_payload = _read_optional_json(artifact_dir / "translations.json")
    if authority_records and isinstance(translations_payload, list):
        translations_by_id = {
            str(item.get("subtitle_id") or ""): item
            for item in translations_payload
            if isinstance(item, Mapping)
        }
        for subtitle_id, authority in authority_records.items():
            projection = translations_by_id.get(subtitle_id)
            if projection is None or (
                str(projection.get("parent_source_hash") or "")
                != str(authority.get("source_hash") or "")
                or str(projection.get("parent_record_hash") or "")
                != str(authority.get("record_hash") or "")
            ):
                _append_gate(failures, "run_parent_chinese_projection_mismatch", subtitle_id=subtitle_id)
    return by_id, source, authority_records


def _validate_timeline(
    timeline: Any,
    run: Mapping[str, Any],
    failures: List[Dict[str, Any]],
) -> None:
    if not isinstance(timeline, Mapping):
        _append_gate(failures, "run_final_timeline_missing")
        return
    validation = timeline.get("validation")
    if not isinstance(validation, Mapping) or (
        str(validation.get("status") or "") != "PASS"
        or int(validation.get("error_count") or 0) != 0
        or list(validation.get("errors") or [])
    ):
        _append_gate(failures, "run_final_timeline_invalid")
    records = list(timeline.get("records") or [])
    expected = [
        (str(item["subtitle_id"]), int(item["word_start"]), int(item["word_end"]))
        for item in run["spans"]
    ]
    actual = []
    for item in records:
        try:
            actual.append(
                (
                    str(item.get("subtitle_id") or ""),
                    int(item["word_start"]),
                    int(item["word_end"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            actual.append(("", -1, -1))
    if actual != expected:
        _append_gate(failures, "run_final_timeline_identity_mismatch")
    for position, item in enumerate(records):
        if position >= len(run["spans"]):
            break
        timeline_english = str(
            item.get("original", item.get("english", "")) or ""
        )
        if timeline_english and (
            _normalise_tokens(timeline_english)
            != _normalise_tokens(str(run["spans"][position]["english"]))
        ):
            _append_gate(
                failures,
                "run_final_timeline_english_mismatch",
                subtitle_id=str(item.get("subtitle_id") or ""),
            )


def _validate_report_and_boundaries(
    artifact_dir: Path,
    failures: List[Dict[str, Any]],
    *,
    require_modern_evidence: bool,
) -> tuple[Any, Any, List[Dict[str, Any]]]:
    compatibility_notes: List[Dict[str, Any]] = []
    validation = _read_optional_json(artifact_dir / "validation-report.json")
    if not isinstance(validation, Mapping):
        target = failures if require_modern_evidence else compatibility_notes
        _append_gate(target, "run_validation_report_missing")
    elif list(validation.get("errors") or []) or str(validation.get("status") or "") == "ERROR":
        _append_gate(
            failures,
            "run_validation_report_errors",
            error_count=len(list(validation.get("errors") or [])),
        )

    boundary = _read_optional_json(artifact_dir / "english-boundary-audit.json")
    if not isinstance(boundary, Mapping):
        target = failures if require_modern_evidence else compatibility_notes
        _append_gate(target, "run_english_boundary_audit_missing")
    else:
        summary = boundary.get("summary") or {}
        hard_count = int(summary.get("hard") or 0) if isinstance(summary, Mapping) else 0
        if hard_count:
            _append_gate(failures, "run_hard_english_boundaries", count=hard_count)
    return validation, boundary, compatibility_notes


def _load_run_v2(artifact_dir: Path) -> Dict[str, Any]:
    run = _load_run(artifact_dir)
    failures: List[Dict[str, Any]] = []
    ledger_payload = _read_json(artifact_dir / "word-ledger.json")
    if not isinstance(ledger_payload, Mapping):
        raise ValueError("run_word_ledger_invalid")
    _validate_span_contract(run, failures)
    timeline = _read_optional_json(artifact_dir / "final-cue-timeline.json")
    _validate_timeline(timeline, run, failures)
    run_manifest = _read_optional_json(artifact_dir / "run-manifest.json")
    modern_manifest = isinstance(run_manifest, Mapping) and int(
        run_manifest.get("artifact_schema_version") or 0
    ) >= 2
    modern_authority = (artifact_dir / "authoritative-parent-chinese.json").is_file()
    validation, boundary, compatibility_notes = _validate_report_and_boundaries(
        artifact_dir,
        failures,
        require_modern_evidence=modern_manifest or modern_authority,
    )
    parent_chinese, chinese_source, authority_records = _load_v2_parent_chinese(
        artifact_dir,
        run,
        ledger_payload,
        timeline,
        failures,
    )
    run.update(
        {
            "hard_gate_failures": failures,
            "ledger_payload": ledger_payload,
            "parent_chinese": parent_chinese,
            "parent_chinese_source": chinese_source,
            "authority_records": authority_records,
            "timeline": timeline,
            "validation_report": validation,
            "boundary_audit": boundary,
            "compatibility_notes": compatibility_notes,
            "display_pages": _read_optional_json(artifact_dir / "display-page-translations.json"),
        }
    )
    return run


def _word_error_distance(expected: Sequence[str], actual: Sequence[str]) -> int:
    if len(expected) < len(actual):
        expected, actual = actual, expected
    previous = list(range(len(actual) + 1))
    for expected_index, expected_word in enumerate(expected, 1):
        current = [expected_index]
        for actual_index, actual_word in enumerate(actual, 1):
            substitution = previous[actual_index - 1] + (expected_word != actual_word)
            deletion = previous[actual_index] + 1
            insertion = current[actual_index - 1] + 1
            current.append(min(substitution, deletion, insertion))
        previous = current
    return previous[-1]


def _contains_token_phrase(tokens: Sequence[str], phrase: str) -> bool:
    expected = _normalise_tokens(phrase)
    if not expected:
        return False
    width = len(expected)
    return any(tokens[index : index + width] == expected for index in range(len(tokens) - width + 1))


def _score_english(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any] | None:
    text = str(reference.get("english_text") or "").strip()
    if not text:
        return None
    expected = _normalise_tokens(text)
    actual = _normalise_tokens(" ".join(str(item["english"]) for item in run["spans"]))
    distance = _word_error_distance(expected, actual)
    return {
        "reference_word_count": len(expected),
        "actual_word_count": len(actual),
        "word_error_count": distance,
        "word_error_rate": distance / max(1, len(expected)),
    }


def _score_entities(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any] | None:
    entities = reference.get("entities")
    if entities is None:
        return None
    entities = _as_list(entities, "entities")
    actual_tokens = _normalise_tokens(" ".join(str(item["english"]) for item in run["spans"]))
    results = []
    for entity in entities:
        canonical_name = str(entity.get("canonical_name") or "").strip()
        if not canonical_name:
            raise ValueError("golden_reference_entity_missing_canonical_name")
        accepted_forms = [canonical_name]
        for value in entity.get("accepted_forms") or []:
            if isinstance(value, str) and value.strip():
                accepted_forms.append(value.strip())
        matched_form = next(
            (form for form in accepted_forms if _contains_token_phrase(actual_tokens, form)),
            "",
        )
        results.append(
            {
                "canonical_name": canonical_name,
                "category": str(entity.get("category") or ""),
                "matched": bool(matched_form),
                "matched_form": matched_form,
            }
        )
    matched = sum(1 for item in results if item["matched"])
    return {
        "expected_count": len(results),
        "matched_count": matched,
        "recall": matched / max(1, len(results)),
        "missing": [item for item in results if not item["matched"]],
        "items": results,
    }


def _score_boundaries(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any] | None:
    expected = reference.get("boundaries_after_word_index")
    if expected is None:
        return None
    if not isinstance(expected, list) or not all(isinstance(value, int) for value in expected):
        raise ValueError("golden_reference_invalid_boundaries")
    expected_set = set(expected)
    spans = list(run["spans"])
    actual_set = {
        int(item["word_end"])
        for item in spans[:-1]
        if isinstance(item.get("word_end"), int)
    }
    matched = expected_set & actual_set
    precision = len(matched) / max(1, len(actual_set))
    recall = len(matched) / max(1, len(expected_set))
    return {
        "expected_count": len(expected_set),
        "actual_count": len(actual_set),
        "matched_count": len(matched),
        "precision": precision,
        "recall": recall,
        "f1": (2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        "missing": sorted(expected_set - actual_set),
        "unexpected": sorted(actual_set - expected_set),
    }


def _score_timing(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any] | None:
    expected = reference.get("word_timings")
    if expected is None:
        return None
    expected = _as_list(expected, "word_timings")
    actual_by_id = {word["word_id"]: word for word in run["words"]}
    errors: List[int] = []
    missing: List[int] = []
    for item in expected:
        try:
            word_id = int(item["word_id"])
            start_ms = int(item["start_ms"])
            end_ms = int(item["end_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("golden_reference_invalid_word_timings") from exc
        actual = actual_by_id.get(word_id)
        if actual is None:
            missing.append(word_id)
            continue
        errors.extend(
            [
                abs(actual["start_ms"] - start_ms),
                abs(actual["end_ms"] - end_ms),
            ]
        )
    return {
        "expected_word_count": len(expected),
        "matched_word_count": len(expected) - len(missing),
        "missing_word_ids": missing,
        "mean_absolute_error_ms": statistics.fmean(errors) if errors else None,
        "p90_absolute_error_ms": _percentile(errors, 0.9) if errors else None,
        "max_absolute_error_ms": max(errors) if errors else None,
    }


def _percentile(values: Sequence[int], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _score_chinese_anchors(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any] | None:
    anchors = reference.get("chinese_anchors")
    if anchors is None:
        return None
    anchors = _as_list(anchors, "chinese_anchors")
    by_id = {str(item["subtitle_id"]): str(item["chinese"]) for item in run["spans"]}
    results = []
    for index, anchor in enumerate(anchors, 1):
        anchor_id = str(anchor.get("anchor_id") or f"anchor-{index}")
        subtitle_ids = [str(value) for value in anchor.get("subtitle_ids") or []]
        if not subtitle_ids:
            raise ValueError("golden_reference_anchor_missing_subtitle_ids")
        missing_ids = [subtitle_id for subtitle_id in subtitle_ids if subtitle_id not in by_id]
        text = _normalise_chinese("".join(by_id.get(subtitle_id, "") for subtitle_id in subtitle_ids))
        required_groups = anchor.get("must_contain_any") or []
        if not isinstance(required_groups, list) or not all(isinstance(group, list) for group in required_groups):
            raise ValueError("golden_reference_invalid_chinese_anchor")
        missing_requirements = []
        for group in required_groups:
            patterns = [_normalise_chinese(str(pattern)) for pattern in group if str(pattern).strip()]
            if not patterns:
                raise ValueError("golden_reference_invalid_chinese_anchor")
            if not any(pattern in text for pattern in patterns):
                missing_requirements.append(patterns)
        forbidden = [_normalise_chinese(str(pattern)) for pattern in anchor.get("must_not_contain") or []]
        forbidden_matches = [pattern for pattern in forbidden if pattern and pattern in text]
        results.append(
            {
                "anchor_id": anchor_id,
                "subtitle_ids": subtitle_ids,
                "matched": not missing_ids and not missing_requirements and not forbidden_matches,
                "missing_subtitle_ids": missing_ids,
                "missing_requirements": missing_requirements,
                "forbidden_matches": forbidden_matches,
            }
        )
    failures = [item for item in results if not item["matched"]]
    return {
        "expected_count": len(results),
        "passed_count": len(results) - len(failures),
        "failures": failures,
        "items": results,
    }


def _threshold_failures(scores: Mapping[str, Any], thresholds: Mapping[str, Any]) -> List[Dict[str, Any]]:
    failures = []

    def check_max(score_key: str, metric: str) -> None:
        value = (scores.get(score_key) or {}).get(metric)
        limit = thresholds.get(f"max_{metric}")
        if value is not None and limit is not None and float(value) > float(limit):
            failures.append({"code": f"{score_key}_{metric}_too_high", "actual": value, "limit": limit})

    def check_min(score_key: str, metric: str) -> None:
        value = (scores.get(score_key) or {}).get(metric)
        limit = thresholds.get(f"min_{metric}")
        if value is not None and limit is not None and float(value) < float(limit):
            failures.append({"code": f"{score_key}_{metric}_too_low", "actual": value, "limit": limit})

    check_max("english", "word_error_rate")
    check_min("entities", "recall")
    check_min("boundaries", "f1")
    check_max("timing", "mean_absolute_error_ms")
    check_max("timing", "p90_absolute_error_ms")
    chinese = scores.get("chinese_anchors")
    if chinese and chinese.get("failures"):
        failures.append({"code": "chinese_fact_anchor_failed", "items": chinese["failures"]})
    return failures


def _resolve_english_anchor(selector: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any]:
    phrase = str(selector.get("english_anchor") or "").strip()
    expected = _normalise_tokens(phrase)
    if not expected:
        raise ValueError("golden_reference_anchor_missing_english")
    tokens, word_ids = _flatten_ledger_tokens(run["words"])
    width = len(expected)
    matches = [
        index
        for index in range(len(tokens) - width + 1)
        if tokens[index : index + width] == expected
    ]
    occurrence_raw = selector.get("anchor_occurrence")
    if occurrence_raw is None:
        if len(matches) != 1:
            code = "unresolved" if not matches else "ambiguous"
            raise ValueError(f"golden_reference_anchor_{code}")
        match_index = matches[0]
    else:
        try:
            occurrence = int(occurrence_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("golden_reference_anchor_occurrence_invalid") from exc
        if occurrence < 1 or occurrence > len(matches):
            raise ValueError("golden_reference_anchor_unresolved")
        match_index = matches[occurrence - 1]
    selected_word_ids = word_ids[match_index : match_index + width]
    if not selected_word_ids:
        raise ValueError("golden_reference_anchor_unresolved")
    word_start = selected_word_ids[0]
    word_end = selected_word_ids[-1]
    relative = selector.get("relative_word_range")
    if relative is not None:
        if (
            not isinstance(relative, list)
            or len(relative) != 2
            or not all(isinstance(value, int) for value in relative)
        ):
            raise ValueError("golden_reference_relative_word_range_invalid")
        word_start += relative[0]
        word_end = selected_word_ids[0] + relative[1]
        if word_start < selected_word_ids[0] or word_end > selected_word_ids[-1] or word_end < word_start:
            raise ValueError("golden_reference_relative_word_range_invalid")
    return {
        "english_anchor": phrase,
        "word_start": word_start,
        "word_end": word_end,
    }


def _spans_overlapping(run: Mapping[str, Any], word_start: int, word_end: int) -> List[Mapping[str, Any]]:
    return [
        item
        for item in run["spans"]
        if int(item["word_end"]) >= word_start and int(item["word_start"]) <= word_end
    ]


def _require_single_owning_span(
    run: Mapping[str, Any],
    word_start: int,
    word_end: int,
) -> Mapping[str, Any]:
    owners = [
        item
        for item in run["spans"]
        if int(item["word_start"]) <= word_start and int(item["word_end"]) >= word_end
    ]
    if len(owners) != 1:
        raise ValueError("golden_reference_anchor_not_owned_by_one_parent")
    return owners[0]


def _normalised_edit_similarity(expected: str, actual: str) -> float:
    expected_chars = list(_normalise_chinese(expected))
    actual_chars = list(_normalise_chinese(actual))
    if not expected_chars and not actual_chars:
        return 1.0
    distance = _word_error_distance(expected_chars, actual_chars)
    return max(0.0, 1.0 - distance / max(1, len(expected_chars)))


def _score_text_requirements(check: Mapping[str, Any], text: str) -> Dict[str, Any]:
    normalised = _normalise_chinese(text)
    parts: List[float] = []
    missing_requirements: List[List[str]] = []
    required_groups = check.get("must_contain_any") or []
    if not isinstance(required_groups, list) or not all(isinstance(group, list) for group in required_groups):
        raise ValueError("golden_reference_invalid_text_requirements")
    for group in required_groups:
        patterns = [_normalise_chinese(str(pattern)) for pattern in group if str(pattern).strip()]
        if not patterns:
            raise ValueError("golden_reference_invalid_text_requirements")
        matched = any(pattern in normalised for pattern in patterns)
        parts.append(1.0 if matched else 0.0)
        if not matched:
            missing_requirements.append(patterns)

    forbidden = [_normalise_chinese(str(value)) for value in check.get("must_not_contain") or []]
    forbidden_matches = [value for value in forbidden if value and value in normalised]
    if forbidden:
        parts.append(1.0 if not forbidden_matches else 0.0)

    accepted = [str(value) for value in check.get("accepted_chinese") or [] if str(value).strip()]
    similarity = None
    if accepted:
        similarity = max(_normalised_edit_similarity(value, text) for value in accepted)
        parts.append(similarity)

    max_chars = check.get("max_chinese_chars")
    char_count = len(normalised)
    if max_chars is not None:
        try:
            maximum = int(max_chars)
        except (TypeError, ValueError) as exc:
            raise ValueError("golden_reference_max_chinese_chars_invalid") from exc
        if maximum < 1:
            raise ValueError("golden_reference_max_chinese_chars_invalid")
        parts.append(min(1.0, maximum / max(1, char_count)))

    if not parts:
        raise ValueError("golden_reference_text_check_empty")
    return {
        "score": statistics.fmean(parts),
        "text": text,
        "char_count": char_count,
        "missing_requirements": missing_requirements,
        "forbidden_matches": forbidden_matches,
        "accepted_chinese_similarity": similarity,
    }


def _expected_boundaries_from_segments(
    window: Mapping[str, Any],
    resolved: Mapping[str, Any],
    run: Mapping[str, Any],
) -> set[int]:
    segments = window.get("expected_segments")
    if not isinstance(segments, list) or not segments or not all(isinstance(value, str) for value in segments):
        raise ValueError("golden_reference_expected_segments_invalid")
    expected_tokens = [_normalise_tokens(value) for value in segments]
    if any(not tokens for tokens in expected_tokens):
        raise ValueError("golden_reference_expected_segments_invalid")
    joined = [token for segment in expected_tokens for token in segment]
    anchor_tokens = _normalise_tokens(str(window.get("english_anchor") or ""))
    if joined != anchor_tokens:
        raise ValueError("golden_reference_expected_segments_do_not_reconstruct_anchor")

    flattened_tokens, flattened_word_ids = _flatten_ledger_tokens(run["words"])
    start_token = next(
        (
            index
            for index, word_id in enumerate(flattened_word_ids)
            if word_id == int(resolved["word_start"])
            and flattened_tokens[index : index + len(anchor_tokens)] == anchor_tokens
        ),
        None,
    )
    if start_token is None:
        raise ValueError("golden_reference_anchor_unresolved")
    boundaries: set[int] = set()
    consumed = 0
    for segment in expected_tokens[:-1]:
        consumed += len(segment)
        left_word = flattened_word_ids[start_token + consumed - 1]
        right_word = flattened_word_ids[start_token + consumed]
        if left_word == right_word:
            raise ValueError("golden_reference_boundary_splits_ledger_word")
        boundaries.add(left_word)
    return boundaries


def _f1(expected: set[int], actual: set[int]) -> Dict[str, Any]:
    if not expected and not actual:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "missing": [], "unexpected": []}
    matched = expected & actual
    precision = len(matched) / max(1, len(actual))
    recall = len(matched) / max(1, len(expected))
    return {
        "precision": precision,
        "recall": recall,
        "f1": (2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        "missing": sorted(expected - actual),
        "unexpected": sorted(actual - expected),
    }


def _score_v2_english(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any]:
    config = reference.get("english_segmentation")
    windows = _as_list(config.get("windows") if isinstance(config, Mapping) else None, "english_segmentation_windows")
    items = []
    for index, window in enumerate(windows, 1):
        resolved = _resolve_english_anchor(window, run)
        expected = _expected_boundaries_from_segments(window, resolved, run)
        actual = {
            int(span["word_end"])
            for span in run["spans"]
            if int(resolved["word_start"]) <= int(span["word_end"]) < int(resolved["word_end"])
        }
        result = _f1(expected, actual)
        items.append(
            {
                "anchor_id": str(window.get("anchor_id") or f"english-{index}"),
                **resolved,
                **result,
                "score": result["f1"],
            }
        )
    return {"score": statistics.fmean(item["score"] for item in items), "items": items}


def _score_v2_parent_translation(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any]:
    config = reference.get("parent_translation")
    checks = _as_list(config.get("anchors") if isinstance(config, Mapping) else None, "parent_translation_anchors")
    items = []
    for index, check in enumerate(checks, 1):
        resolved = _resolve_english_anchor(check, run)
        spans = _spans_overlapping(run, int(resolved["word_start"]), int(resolved["word_end"]))
        text = "".join(str(run["parent_chinese"].get(str(span["subtitle_id"]), "")) for span in spans)
        result = _score_text_requirements(check, text)
        items.append(
            {
                "anchor_id": str(check.get("anchor_id") or f"parent-{index}"),
                **resolved,
                "resolved_subtitle_ids": [str(span["subtitle_id"]) for span in spans],
                **result,
            }
        )
    return {"score": statistics.fmean(item["score"] for item in items), "items": items}


def _score_v2_allocation(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any]:
    config = reference.get("fixed_id_allocation")
    checks = _as_list(config.get("anchors") if isinstance(config, Mapping) else None, "fixed_id_allocation_anchors")
    spans = list(run["spans"])
    items = []
    for index, check in enumerate(checks, 1):
        resolved = _resolve_english_anchor(check, run)
        owner = _require_single_owning_span(
            run,
            int(resolved["word_start"]),
            int(resolved["word_end"]),
        )
        owner_index = spans.index(owner)
        text = str(run["parent_chinese"].get(str(owner["subtitle_id"]), ""))
        result = _score_text_requirements(check, text)
        adjacent_matches: List[str] = []
        if bool(check.get("must_not_appear_in_adjacent")):
            required_groups = [
                [
                    _normalise_chinese(str(pattern))
                    for pattern in group
                    if str(pattern).strip()
                ]
                for group in check.get("must_contain_any") or []
            ]
            for adjacent_index in (owner_index - 1, owner_index + 1):
                if 0 <= adjacent_index < len(spans):
                    adjacent = spans[adjacent_index]
                    adjacent_text = _normalise_chinese(
                        run["parent_chinese"].get(str(adjacent["subtitle_id"]), "")
                    )
                    if required_groups and all(
                        any(pattern in adjacent_text for pattern in group)
                        for group in required_groups
                    ):
                        adjacent_matches.append(str(adjacent["subtitle_id"]))
            if adjacent_matches:
                result["score"] *= 0.5
        items.append(
            {
                "anchor_id": str(check.get("anchor_id") or f"allocation-{index}"),
                **resolved,
                "resolved_subtitle_id": str(owner["subtitle_id"]),
                "adjacent_matches": adjacent_matches,
                **result,
            }
        )
    return {"score": statistics.fmean(item["score"] for item in items), "items": items}


def _display_pages_for_range(
    artifact: Mapping[str, Any],
    word_start: int,
    word_end: int,
) -> List[Dict[str, Any]]:
    render_by_id = {
        str(plan.get("parent_subtitle_id") or ""): plan
        for plan in artifact.get("render_plans") or []
        if isinstance(plan, Mapping)
    }
    translated_by_id = {
        str(parent.get("parent_subtitle_id") or ""): parent
        for parent in artifact.get("parents") or []
        if isinstance(parent, Mapping)
    }
    rows: List[Dict[str, Any]] = []
    parent_ids = list(render_by_id) if render_by_id else list(translated_by_id)
    for parent_id in parent_ids:
        plan = render_by_id.get(parent_id) or translated_by_id[parent_id]
        translation = translated_by_id.get(parent_id) or {}
        chinese_by_page = {
            str(page.get("display_page_id") or ""): str(page.get("zh") or "")
            for page in translation.get("pages") or []
            if isinstance(page, Mapping)
        }
        for page in plan.get("pages") or []:
            if not isinstance(page, Mapping):
                continue
            try:
                page_start = int(page["word_start"])
                page_end = int(page["word_end"])
            except (KeyError, TypeError, ValueError):
                continue
            if page_end < word_start or page_start > word_end:
                continue
            row = dict(page)
            row["parent_subtitle_id"] = parent_id
            row["zh"] = chinese_by_page.get(str(page.get("display_page_id") or ""), str(page.get("zh") or ""))
            rows.append(row)
    return sorted(rows, key=lambda item: (int(item["word_start"]), int(item["word_end"])))


def _validate_required_page_artifact(run: Mapping[str, Any]) -> List[Dict[str, Any]]:
    artifact = run.get("display_pages")
    failures: List[Dict[str, Any]] = []
    if not isinstance(artifact, Mapping):
        return [{"code": "run_display_page_artifact_missing"}]
    if str(artifact.get("status") or "") != "PASS" or list(artifact.get("errors") or []):
        return [{"code": "run_display_page_artifact_invalid"}]
    authority_records = dict(run.get("authority_records") or {})
    if authority_records:
        try:
            from app.core.subtitle_processor.authoritative_parent_chinese import (
                validate_display_page_parent_records,
            )

            validate_display_page_parent_records(artifact, authority_records)
        except (ImportError, TypeError, ValueError) as exc:
            _append_gate(
                failures,
                "run_display_page_parent_authority_mismatch",
                error=str(exc),
            )
        multipage_parents = [
            parent
            for parent in artifact.get("parents") or []
            if isinstance(parent, Mapping) and len(list(parent.get("pages") or [])) >= 2
        ]
        if multipage_parents:
            try:
                from app.core.subtitle_processor.stable_display_page_contract import (
                    DISPLAY_PAGE_SCHEMA_VERSION,
                    build_display_page_contract,
                )

                parent_payloads = []
                plans = list(artifact.get("render_plans") or [])
                for parent in multipage_parents:
                    parent_id = str(parent.get("parent_subtitle_id") or "")
                    authority = authority_records.get(parent_id)
                    if authority is None:
                        raise ValueError(f"display_page_parent_unknown:{parent_id}")
                    parent_payloads.append(
                        {
                            "parent_subtitle_id": parent_id,
                            "english": authority.get("english"),
                            "chinese": authority.get("chinese"),
                            "word_start": authority.get("word_start"),
                            "word_end": authority.get("word_end"),
                            "pages": list(parent.get("pages") or []),
                        }
                    )
                rebuilt_contract = build_display_page_contract(
                    parent_payloads,
                    layout_profile=dict(artifact.get("layout_profile") or {}),
                    planner_version=str(artifact.get("planner_version") or ""),
                    render_plans=plans,
                )
                if (
                    int(artifact.get("schema_version") or 0) != DISPLAY_PAGE_SCHEMA_VERSION
                    or str(artifact.get("contract_hash") or "")
                    != str(rebuilt_contract.get("contract_hash") or "")
                ):
                    _append_gate(failures, "run_display_page_contract_mismatch")
            except (ImportError, TypeError, ValueError) as exc:
                _append_gate(
                    failures,
                    "run_display_page_contract_invalid",
                    error=str(exc),
                )
    render_plans = list(artifact.get("render_plans") or [])
    translated_parents = {
        str(parent.get("parent_subtitle_id") or ""): parent
        for parent in artifact.get("parents") or []
        if isinstance(parent, Mapping)
    }
    for plan in render_plans:
        if not isinstance(plan, Mapping):
            _append_gate(failures, "run_display_page_plan_invalid")
            continue
        pages = list(plan.get("pages") or [])
        try:
            expected_start = int(plan["word_start"])
            expected_end = int(plan["word_end"])
        except (KeyError, TypeError, ValueError):
            _append_gate(failures, "run_display_page_plan_invalid")
            continue
        for page_index, page in enumerate(pages, 1):
            try:
                page_start = int(page["word_start"])
                page_end = int(page["word_end"])
            except (KeyError, TypeError, ValueError):
                _append_gate(failures, "run_display_page_range_invalid")
                continue
            if page_start != expected_start or page_end < page_start:
                _append_gate(
                    failures,
                    "run_display_page_coverage_invalid",
                    parent_subtitle_id=str(plan.get("parent_subtitle_id") or ""),
                )
            expected_start = page_end + 1
            expected_page_id = f"{str(plan.get('parent_subtitle_id') or '')}.P{page_index:02d}"
            if str(page.get("display_page_id") or "") != expected_page_id:
                _append_gate(failures, "run_display_page_id_invalid", display_page_id=page.get("display_page_id"))
            expected_tokens = _span_ledger_tokens(run, page_start, page_end)
            if expected_tokens != _normalise_tokens(str(page.get("english") or "")):
                _append_gate(failures, "run_display_page_english_ledger_mismatch", display_page_id=page.get("display_page_id"))
        if expected_start != expected_end + 1:
            _append_gate(
                failures,
                "run_display_page_coverage_invalid",
                parent_subtitle_id=str(plan.get("parent_subtitle_id") or ""),
            )
        if len(pages) <= 1:
            continue
        parent_id = str(plan.get("parent_subtitle_id") or "")
        translated_parent = translated_parents.get(parent_id)
        translated_pages = (
            list(translated_parent.get("pages") or [])
            if isinstance(translated_parent, Mapping)
            else []
        )
        if len(translated_pages) != len(pages):
            _append_gate(
                failures,
                "run_display_page_translation_cardinality_mismatch",
                parent_subtitle_id=parent_id,
            )
            continue
        for planned, translated in zip(pages, translated_pages):
            identity = (
                str(translated.get("display_page_id") or "")
                == str(planned.get("display_page_id") or "")
                and int(translated.get("word_start", -1))
                == int(planned.get("word_start", -2))
                and int(translated.get("word_end", -1))
                == int(planned.get("word_end", -2))
                and _normalise_tokens(str(translated.get("english") or ""))
                == _normalise_tokens(str(planned.get("english") or ""))
            )
            if not identity:
                _append_gate(
                    failures,
                    "run_display_page_translation_identity_mismatch",
                    parent_subtitle_id=parent_id,
                )
            if not _normalise_chinese(str(translated.get("zh") or "")):
                _append_gate(
                    failures,
                    "run_display_page_translation_missing",
                    display_page_id=str(translated.get("display_page_id") or ""),
                )
    if not render_plans:
        for parent_id, parent in translated_parents.items():
            pages = list(parent.get("pages") or [])
            expected_start = int(parent.get("word_start", -1))
            expected_end = int(parent.get("word_end", -2))
            for page_index, page in enumerate(pages, 1):
                page_start = int(page.get("word_start", -1))
                page_end = int(page.get("word_end", -2))
                expected_page_id = f"{parent_id}.P{page_index:02d}"
                if (
                    page_start != expected_start
                    or page_end < page_start
                    or str(page.get("display_page_id") or "") != expected_page_id
                ):
                    _append_gate(
                        failures,
                        "run_display_page_coverage_invalid",
                        parent_subtitle_id=parent_id,
                    )
                if not _normalise_chinese(str(page.get("zh") or "")):
                    _append_gate(
                        failures,
                        "run_display_page_translation_missing",
                        display_page_id=str(page.get("display_page_id") or ""),
                    )
                expected_start = page_end + 1
            if expected_start != expected_end + 1:
                _append_gate(
                    failures,
                    "run_display_page_coverage_invalid",
                    parent_subtitle_id=parent_id,
                )
    return failures


def _score_v2_display_pages(reference: Mapping[str, Any], run: Mapping[str, Any]) -> Dict[str, Any]:
    config = reference.get("display_pages")
    windows = _as_list(config.get("windows") if isinstance(config, Mapping) else None, "display_page_windows")
    artifact = run.get("display_pages")
    if not isinstance(artifact, Mapping):
        return {"score": 0.0, "items": []}
    items = []
    for index, window in enumerate(windows, 1):
        resolved = _resolve_english_anchor(window, run)
        pages = _display_pages_for_range(
            artifact,
            int(resolved["word_start"]),
            int(resolved["word_end"]),
        )
        parts: List[float] = []
        expected_segments = window.get("expected_segments")
        boundary_result = None
        if expected_segments is not None:
            expected = _expected_boundaries_from_segments(window, resolved, run)
            actual = {
                int(page["word_end"])
                for page in pages
                if int(resolved["word_start"]) <= int(page["word_end"]) < int(resolved["word_end"])
            }
            boundary_result = _f1(expected, actual)
            parts.append(boundary_result["f1"])
        max_words = window.get("max_words_per_page")
        if max_words is not None:
            maximum = int(max_words)
            page_scores = [
                min(1.0, maximum / max(1, int(page["word_end"]) - int(page["word_start"]) + 1))
                for page in pages
            ]
            parts.append(statistics.fmean(page_scores) if page_scores else 0.0)
        min_font = window.get("min_english_font_size")
        if min_font is not None:
            known_fonts = [int(page["english_font_size"]) for page in pages if page.get("english_font_size") is not None]
            parts.append(
                statistics.fmean(min(1.0, value / int(min_font)) for value in known_fonts)
                if known_fonts
                else 1.0
            )
        max_lines = window.get("max_english_lines")
        if max_lines is not None:
            known_lines = [len(list(page.get("english_lines") or [])) for page in pages if "english_lines" in page]
            parts.append(
                statistics.fmean(min(1.0, int(max_lines) / max(1, value)) for value in known_lines)
                if known_lines
                else 1.0
            )
        text_checks = any(
            key in window
            for key in ("must_contain_any", "must_not_contain", "accepted_chinese", "max_chinese_chars")
        )
        text_result = None
        if text_checks:
            text_result = _score_text_requirements(window, "".join(str(page.get("zh") or "") for page in pages))
            parts.append(text_result["score"])
        page_expectations = window.get("page_expectations")
        page_results = None
        if page_expectations is not None:
            page_expectations = _as_list(page_expectations, "display_page_expectations")
            if len(page_expectations) != len(pages):
                page_results = []
                parts.append(0.0)
            else:
                page_results = [
                    _score_text_requirements(expectation, str(page.get("zh") or ""))
                    for expectation, page in zip(page_expectations, pages)
                ]
                parts.append(statistics.fmean(result["score"] for result in page_results))
        if not parts:
            raise ValueError("golden_reference_display_page_check_empty")
        item = {
            "anchor_id": str(window.get("anchor_id") or f"display-{index}"),
            **resolved,
            "resolved_page_ids": [str(page.get("display_page_id") or "") for page in pages],
            "score": statistics.fmean(parts),
        }
        if boundary_result is not None:
            item["boundaries"] = boundary_result
        if text_result is not None:
            item["chinese"] = text_result
        if page_results is not None:
            item["page_chinese"] = page_results
        items.append(item)
    return {"score": statistics.fmean(item["score"] for item in items), "items": items}


def _validate_v2_weights(reference: Mapping[str, Any]) -> Dict[str, float]:
    configured = reference.get("weights") or DEFAULT_V2_WEIGHTS
    if not isinstance(configured, Mapping) or set(configured) != set(DEFAULT_V2_WEIGHTS):
        raise ValueError("golden_reference_v2_weights_invalid")
    weights = {key: float(configured[key]) for key in DEFAULT_V2_WEIGHTS}
    if any(value <= 0 for value in weights.values()) or abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("golden_reference_v2_weights_invalid")
    return weights


def _evaluate_v2(reference: Mapping[str, Any], artifact_dir: Path) -> Dict[str, Any]:
    run = _load_run_v2(artifact_dir)
    hard_failures = list(run["hard_gate_failures"])
    hard_failures.extend(_validate_required_page_artifact(run))
    components = {
        "english_segmentation": _score_v2_english(reference, run),
        "parent_translation": _score_v2_parent_translation(reference, run),
        "fixed_id_allocation": _score_v2_allocation(reference, run),
        "display_pages": _score_v2_display_pages(reference, run),
    }
    weights = _validate_v2_weights(reference)
    overall = sum(weights[name] * float(component["score"]) for name, component in components.items())
    thresholds = reference.get("thresholds") or {}
    if not isinstance(thresholds, Mapping):
        raise ValueError("golden_reference_invalid_thresholds")
    overall_threshold = float(thresholds.get("min_overall_score", DEFAULT_V2_OVERALL_THRESHOLD))
    component_threshold = float(thresholds.get("min_component_score", DEFAULT_V2_COMPONENT_THRESHOLD))
    failures = list(hard_failures)
    if overall < overall_threshold:
        failures.append(
            {
                "code": "quality_overall_score_too_low",
                "actual": overall,
                "limit": overall_threshold,
            }
        )
    for name, component in components.items():
        score = float(component["score"])
        if score < component_threshold:
            failures.append(
                {
                    "code": "quality_component_score_too_low",
                    "component": name,
                    "actual": score,
                    "limit": component_threshold,
                }
            )
    return {
        "schema_version": 2,
        "sample_id": str(reference.get("sample_id") or ""),
        "artifact_dir": str(artifact_dir),
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "hard_gates": {
            "status": "PASS" if not hard_failures else "FAIL",
            "failures": hard_failures,
        },
        "quality": {
            "overall_score": overall,
            "weights": weights,
            "min_overall_score": overall_threshold,
            "min_component_score": component_threshold,
            "components": components,
        },
        "sources": {"parent_chinese": run["parent_chinese_source"]},
        "compatibility": {
            "notes": list(run.get("compatibility_notes") or []),
        },
    }


def evaluate_golden_subtitles(reference: Mapping[str, Any], artifact_dir: Path) -> Dict[str, Any]:
    schema_version = int(reference.get("schema_version", 0) or 0)
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError("golden_reference_schema_version_unsupported")
    if schema_version == 2:
        return _evaluate_v2(reference, artifact_dir)
    run = _load_run(artifact_dir)
    scores = {
        "english": _score_english(reference, run),
        "entities": _score_entities(reference, run),
        "boundaries": _score_boundaries(reference, run),
        "timing": _score_timing(reference, run),
        "chinese_anchors": _score_chinese_anchors(reference, run),
    }
    thresholds = reference.get("thresholds") or {}
    if not isinstance(thresholds, Mapping):
        raise ValueError("golden_reference_invalid_thresholds")
    failures = _threshold_failures(scores, thresholds)
    return {
        "schema_version": 1,
        "sample_id": str(reference.get("sample_id") or ""),
        "artifact_dir": str(artifact_dir),
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "scores": scores,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a stable subtitle artifact directory against a golden reference.")
    parser.add_argument("--reference", required=True, type=Path, help="Manually curated golden reference JSON")
    parser.add_argument("--run", required=True, type=Path, help="Artifact directory or a parent directory containing one artifact directory")
    parser.add_argument("--output", type=Path, help="Optional report JSON output path")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        reference = _read_json(args.reference)
        if not isinstance(reference, Mapping):
            raise ValueError("golden_reference_root_must_be_object")
        report = evaluate_golden_subtitles(reference, _resolve_artifact_dir(args.run))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {"status": "ERROR", "error": str(exc)}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
