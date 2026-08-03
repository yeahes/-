"""Evaluate a completed subtitle run against a manually curated golden reference.

This tool is intentionally offline and read-only. It does not alter ASR,
English boundaries, translations, timing, or any runtime cache. A golden
reference measures only facts a reviewer has supplied explicitly: English word
sequence, named entities, frozen boundaries, word timing, and Chinese fact
anchors.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


SCHEMA_VERSION = 1
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalise_tokens(text: str) -> List[str]:
    return [match.group(0).casefold() for match in _WORD_RE.finditer(text or "")]


def _normalise_chinese(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _resolve_artifact_dir(run_root: Path) -> Path:
    run_root = run_root.resolve()
    if (run_root / "subtitle-spans.json").is_file():
        return run_root
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


def evaluate_golden_subtitles(reference: Mapping[str, Any], artifact_dir: Path) -> Dict[str, Any]:
    if int(reference.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        raise ValueError("golden_reference_schema_version_unsupported")
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
        "schema_version": SCHEMA_VERSION,
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
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
