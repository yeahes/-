"""Compare two completed stable subtitle runs without re-running generation.

An allocation-only experiment is valid only when every upstream frozen input is
identical.  This tool reads artifacts from two completed runs and rejects a
comparison when ASR, article assistance, English boundaries, timing, semantic
groups, authoritative translations, or runtime configuration differ.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from app.core.subtitle_processor.stable_pipeline_contracts import stable_payload_hash


STATUS_COMPARABLE = "comparable"
STATUS_ISOLATION_FAILED = "allocation_isolation_failed"
STATUS_INCOMPLETE = "incomplete_artifacts"

_REQUIRED_ARTIFACTS = (
    "asr_raw.json",
    "asr_corrected.json",
    "word-ledger.json",
    "subtitle-spans.json",
    "semantic-groups.json",
    "llm-raw-returns.json",
)
_ARTICLE_STATE_KEYS = (
    "reference_text_present",
    "reference_text_hash",
    "normalized_context_hash",
    "glossary_hash",
    "use_article_reference_assist",
    "use_article_translation_terms",
    "article_reference_enabled",
    "correction_requested",
    "correction_ran",
    "correction_applied",
    "translation_terms_applied",
)
_RUNTIME_CONFIG_KEYS = (
    "translation_model",
    "prompt_version",
    "allocation_prompt_version",
    "target_language",
    "max_cjk_chars",
    "max_english_words",
    "allocation_batch_size",
    "allocation_max_concurrency",
    "chinese_polish_enabled",
)


@dataclass
class RunData:
    label: str
    requested_root: Path
    manifest_path: Path | None = None
    artifact_dir: Path | None = None
    missing: List[str] = field(default_factory=list)
    payloads: Dict[str, Any] = field(default_factory=dict)
    hashes: Dict[str, str] = field(default_factory=dict)
    article_state: Dict[str, Any] = field(default_factory=dict)
    runtime_config: Dict[str, Any] = field(default_factory=dict)
    final_by_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def _find_manifest(root: Path) -> Path | None:
    direct = root / "stable-final-manifest.json"
    if direct.exists():
        return direct
    parent = root.parent / "stable-final-manifest.json"
    if parent.exists():
        return parent
    found = sorted(root.glob("**/stable-final-manifest.json"))
    return found[0] if len(found) == 1 else None


def _find_artifact_dir(root: Path, manifest_path: Path | None) -> Path | None:
    if (root / "subtitle-spans.json").exists():
        return root
    candidates: List[Path] = []
    if manifest_path:
        candidates.extend(sorted(manifest_path.parent.glob("*-artifacts")))
    candidates.extend(sorted(root.glob("*-artifacts")))
    candidates.extend(sorted(root.glob("**/*-artifacts")))
    unique = []
    seen = set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        if (candidate / "subtitle-spans.json").exists():
            unique.append(candidate)
    return unique[0] if len(unique) == 1 else None


def _find_artifact_file(name: str, root: Path, manifest_path: Path | None, artifact_dir: Path | None) -> Path | None:
    parents = [artifact_dir, root, manifest_path.parent if manifest_path else None]
    return _first_existing(path / name for path in parents if path is not None)


def _extract_full_translations(raw_returns: Sequence[Any]) -> List[Dict[str, str]]:
    translations: Dict[str, str] = {}
    for entry in raw_returns:
        if not isinstance(entry, Mapping):
            continue
        if "semantic_full_translation" not in str(entry.get("task") or ""):
            continue
        data = entry.get("data") or {}
        for group in data.get("groups") or []:
            if not isinstance(group, Mapping):
                continue
            group_id = group.get("id", group.get("semantic_group_id"))
            if group_id in (None, ""):
                continue
            text = str(group.get("full_translation") or "")
            normalized_id = _semantic_group_id(group_id)
            if normalized_id in translations and translations[normalized_id] != text:
                raise ValueError(f"conflicting_authoritative_full_translation:{normalized_id}")
            translations[normalized_id] = text
    return [
        {"semantic_group_id": group_id, "full_translation": translations[group_id]}
        for group_id in sorted(translations)
    ]


def _semantic_group_id(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.upper().startswith("G"):
        raw = raw[1:]
    try:
        return f"G{int(raw):04d}"
    except (TypeError, ValueError):
        return str(value or "")


def _normalise_spans(spans: Sequence[Any]) -> List[Dict[str, Any]]:
    result = []
    for item in spans:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "subtitle_id": str(item.get("subtitle_id") or ""),
                "english": str(item.get("original", item.get("english", "")) or ""),
                "word_start": item.get("word_start"),
                "word_end": item.get("word_end"),
                "source_ids": list(item.get("source_ids") or []),
            }
        )
    return result


def _normalise_semantic_groups(groups: Sequence[Any]) -> List[Dict[str, Any]]:
    result = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        parts = group.get("subtitle_parts", group.get("items", [])) or []
        result.append(
            {
                "semantic_group_id": _semantic_group_id(group.get("group_id", group.get("id"))),
                "expected_subtitle_ids": [
                    str(item) for item in (group.get("expected_subtitle_ids") or [])
                ],
                "full_english": str(group.get("full_english") or ""),
                "subtitle_parts": [
                    {
                        "subtitle_id": str(part.get("subtitle_id") or ""),
                        "english": str(part.get("original", part.get("english", "")) or ""),
                        "word_start": part.get("word_start"),
                        "word_end": part.get("word_end"),
                    }
                    for part in parts
                    if isinstance(part, Mapping)
                ],
            }
        )
    return result


def _normalise_word_ledger(ledger: Any) -> Any:
    if not isinstance(ledger, Mapping):
        return ledger
    return {
        "words": list(ledger.get("words") or []),
        "source_segments": list(ledger.get("source_segments") or []),
    }


def _parse_timestamp(value: str) -> int:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"invalid_srt_timestamp:{value}")
    hours, minutes, seconds, milliseconds = (int(part) for part in match.groups())
    return (((hours * 60 + minutes) * 60) + seconds) * 1000 + milliseconds


def _parse_bilingual_srt(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    entries = []
    for block in re.split(r"\n{2,}", text.strip()):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 3:
            continue
        start_text, end_text = (part.strip() for part in lines[1].split("-->", 1))
        entries.append(
            {
                "start_ms": _parse_timestamp(start_text),
                "end_ms": _parse_timestamp(end_text),
                "english": lines[2],
                "chinese": "\n".join(lines[3:]),
            }
        )
    return entries


def _srt_path_from_manifest(manifest: Mapping[str, Any], root: Path, manifest_path: Path | None) -> Path | None:
    paths = manifest.get("paths") if isinstance(manifest, Mapping) else {}
    configured = str((paths or {}).get("original_top_srt") or "")
    candidates = [Path(configured)] if configured else []
    if configured and manifest_path:
        candidates.append(manifest_path.parent / Path(configured).name)
    candidates.extend(
        [
            root / "stable-final-original-top.srt",
            manifest_path.parent / "stable-final-original-top.srt" if manifest_path else root / "__missing__",
        ]
    )
    return _first_existing(candidates)


def _allocation_prompt_version(allocation_inputs: Any) -> str:
    values = {
        str(item.get("allocation_prompt_version") or "")
        for item in (allocation_inputs or [])
        if isinstance(item, Mapping) and item.get("allocation_prompt_version")
    }
    return next(iter(values)) if len(values) == 1 else ""


def _runtime_config(
    manifest: Mapping[str, Any], run_manifest: Mapping[str, Any], allocation_inputs: Any
) -> Dict[str, Any]:
    comparison_config = (manifest.get("run_comparison") or {}).get("translation_runtime_config") or {}
    sources = (comparison_config, run_manifest, manifest)

    def value(key: str) -> Any:
        for source in sources:
            if isinstance(source, Mapping) and source.get(key) not in (None, ""):
                return source.get(key)
        return ""

    return {
        "translation_model": value("translation_model"),
        "prompt_version": value("prompt_version"),
        "allocation_prompt_version": _allocation_prompt_version(allocation_inputs),
        "target_language": value("target_language"),
        "max_cjk_chars": value("max_cjk_chars"),
        "max_english_words": value("max_english_words"),
        "allocation_batch_size": value("allocation_batch_size"),
        "allocation_max_concurrency": value("allocation_max_concurrency"),
        "chinese_polish_enabled": value("chinese_polish_enabled"),
    }


def _article_state(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    state = (manifest.get("run_comparison") or {}).get("article_reference") or {}
    return {key: state.get(key, None) for key in _ARTICLE_STATE_KEYS}


def _first_difference(before: Any, after: Any, path: str = "$") -> Dict[str, Any]:
    if type(before) is not type(after):
        return {"path": path, "before": before, "after": after}
    if isinstance(before, Mapping):
        for key in sorted(set(before) | set(after), key=str):
            if key not in before or key not in after:
                return {"path": f"{path}.{key}", "before": before.get(key), "after": after.get(key)}
            if before[key] != after[key]:
                return _first_difference(before[key], after[key], f"{path}.{key}")
    elif isinstance(before, list):
        for index, (left, right) in enumerate(zip(before, after)):
            if left != right:
                return _first_difference(left, right, f"{path}[{index}]")
        if len(before) != len(after):
            return {"path": f"{path}.length", "before": len(before), "after": len(after)}
    return {"path": path, "before": before, "after": after}


def _load_run(label: str, root: Path) -> RunData:
    requested_root = root.resolve()
    result = RunData(label=label, requested_root=requested_root)
    result.manifest_path = _find_manifest(requested_root)
    if result.manifest_path is None:
        result.missing.append("stable-final-manifest.json")
        return result
    try:
        manifest = _read_json(result.manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        result.missing.append(f"stable-final-manifest.json:{exc}")
        return result
    result.payloads["manifest"] = manifest
    result.artifact_dir = _find_artifact_dir(requested_root, result.manifest_path)
    if result.artifact_dir is None:
        result.missing.append("artifact_dir")
        return result

    loaded: Dict[str, Any] = {}
    for name in _REQUIRED_ARTIFACTS:
        path = _find_artifact_file(name, requested_root, result.manifest_path, result.artifact_dir)
        if path is None:
            result.missing.append(name)
            continue
        try:
            loaded[name] = _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            result.missing.append(f"{name}:{exc}")
    if result.missing:
        return result

    final_srt = _srt_path_from_manifest(manifest, requested_root, result.manifest_path)
    if final_srt is None:
        result.missing.append("stable-final-original-top.srt")
        return result
    try:
        final_srt_entries = _parse_bilingual_srt(final_srt)
    except (OSError, ValueError) as exc:
        result.missing.append(f"stable-final-original-top.srt:{exc}")
        return result

    spans = _normalise_spans(loaded["subtitle-spans.json"])
    if len(spans) != len(final_srt_entries):
        result.missing.append(
            f"stable_srt_span_cardinality:{len(final_srt_entries)}!={len(spans)}"
        )
        return result
    result.final_by_id = {
        span["subtitle_id"]: {
            "english": entry["english"],
            "chinese": entry["chinese"],
            "start_ms": entry["start_ms"],
            "end_ms": entry["end_ms"],
        }
        for span, entry in zip(spans, final_srt_entries)
    }
    if len(result.final_by_id) != len(spans) or any(not item["subtitle_id"] for item in spans):
        result.missing.append("subtitle_spans_invalid_ids")
        return result

    try:
        full_translations = _extract_full_translations(loaded["llm-raw-returns.json"])
    except ValueError as exc:
        result.missing.append(str(exc))
        return result
    if not full_translations:
        result.missing.append("authoritative_full_translations")
        return result
    run_manifest_path = _find_artifact_file(
        "run-manifest.json", requested_root, result.manifest_path, result.artifact_dir
    )
    run_manifest = _read_json(run_manifest_path) if run_manifest_path else {}
    allocation_inputs_path = _find_artifact_file(
        "allocation-inputs.json", requested_root, result.manifest_path, result.artifact_dir
    )
    allocation_inputs = _read_json(allocation_inputs_path) if allocation_inputs_path else []
    result.payloads.update(
        {
            "asr_raw": loaded["asr_raw.json"],
            "asr_corrected": loaded["asr_corrected.json"],
            "word_ledger": _normalise_word_ledger(loaded["word-ledger.json"]),
            "subtitle_spans": spans,
            "semantic_groups": _normalise_semantic_groups(loaded["semantic-groups.json"]),
            "authoritative_full_translations": full_translations,
            "final_id_sequence": [span["subtitle_id"] for span in spans],
            "final_english_by_id": {
                subtitle_id: item["english"] for subtitle_id, item in result.final_by_id.items()
            },
            "final_timing_by_id": {
                subtitle_id: [item["start_ms"], item["end_ms"]]
                for subtitle_id, item in result.final_by_id.items()
            },
        }
    )
    result.hashes = {
        "asr_text_hash": stable_payload_hash(result.payloads["asr_raw"]),
        "corrected_english_hash": stable_payload_hash(result.payloads["asr_corrected"]),
        "word_ledger_hash": stable_payload_hash(result.payloads["word_ledger"]),
        "english_text_hash": stable_payload_hash(result.payloads["subtitle_spans"]),
        "word_timing_hash": stable_payload_hash(result.payloads["word_ledger"]),
        "subtitle_id_time_hash": stable_payload_hash(
            {
                "ids": result.payloads["final_id_sequence"],
                "timing": result.payloads["final_timing_by_id"],
            }
        ),
        "semantic_group_input_hash": stable_payload_hash(result.payloads["semantic_groups"]),
        "authoritative_full_translation_hash": stable_payload_hash(full_translations),
    }
    result.article_state = _article_state(manifest)
    if any(value is None for value in result.article_state.values()):
        result.missing.append("manifest.run_comparison.article_reference")
    result.runtime_config = _runtime_config(manifest, run_manifest, allocation_inputs)
    for key in _RUNTIME_CONFIG_KEYS:
        if result.runtime_config.get(key, "") in (None, ""):
            result.missing.append(f"runtime_config.{key}")
    return result


def _run_summary(run: RunData) -> Dict[str, Any]:
    return {
        "requested_root": str(run.requested_root),
        "manifest_path": str(run.manifest_path) if run.manifest_path else "",
        "artifact_dir": str(run.artifact_dir) if run.artifact_dir else "",
        "missing": list(run.missing),
        "frozen_hashes": dict(run.hashes),
        "article_reference": dict(run.article_state),
        "runtime_config": dict(run.runtime_config),
        "subtitle_count": len(run.final_by_id),
    }


def compare_frozen_mainline_runs(baseline_root: str | Path, candidate_root: str | Path) -> Dict[str, Any]:
    """Return a deterministic A/B verdict for two completed stable runs."""
    baseline = _load_run("baseline", Path(baseline_root))
    candidate = _load_run("candidate", Path(candidate_root))
    report: Dict[str, Any] = {
        "schema_version": 1,
        "baseline": _run_summary(baseline),
        "candidate": _run_summary(candidate),
        "changed_frozen_inputs": [],
        "changed_runtime_config": [],
        "changed_article_reference_state": [],
        "final_output_changes": {},
        "chinese_changed_subtitle_ids": [],
    }
    if baseline.missing or candidate.missing:
        report["status"] = STATUS_INCOMPLETE
        return report

    for key in sorted(baseline.hashes):
        if baseline.hashes[key] != candidate.hashes.get(key):
            payload_key = {
                "asr_text_hash": "asr_raw",
                "corrected_english_hash": "asr_corrected",
                "word_ledger_hash": "word_ledger",
                "word_timing_hash": "word_ledger",
                "english_text_hash": "subtitle_spans",
                "semantic_group_input_hash": "semantic_groups",
                "authoritative_full_translation_hash": "authoritative_full_translations",
                "subtitle_id_time_hash": "final_timing_by_id",
            }.get(key, "")
            report["changed_frozen_inputs"].append(
                {
                    "key": key,
                    "baseline": baseline.hashes[key],
                    "candidate": candidate.hashes.get(key, ""),
                    "first_difference": _first_difference(
                        baseline.payloads.get(payload_key), candidate.payloads.get(payload_key)
                    ),
                }
            )
    for key in _ARTICLE_STATE_KEYS:
        if baseline.article_state.get(key) != candidate.article_state.get(key):
            report["changed_article_reference_state"].append(
                {
                    "key": key,
                    "baseline": baseline.article_state.get(key),
                    "candidate": candidate.article_state.get(key),
                }
            )
    for key in _RUNTIME_CONFIG_KEYS:
        if baseline.runtime_config.get(key) != candidate.runtime_config.get(key):
            report["changed_runtime_config"].append(
                {
                    "key": key,
                    "baseline": baseline.runtime_config.get(key),
                    "candidate": candidate.runtime_config.get(key),
                }
            )

    final_checks = {
        "subtitle_id_sequence": ("final_id_sequence", "subtitle_id_sequence"),
        "english_by_subtitle_id": ("final_english_by_id", "english_by_subtitle_id"),
        "timing_by_subtitle_id": ("final_timing_by_id", "timing_by_subtitle_id"),
    }
    for output_key, (payload_key, report_key) in final_checks.items():
        before = baseline.payloads[payload_key]
        after = candidate.payloads[payload_key]
        if before != after:
            report["final_output_changes"][report_key] = _first_difference(before, after)

    all_ids = sorted(set(baseline.final_by_id) | set(candidate.final_by_id))
    report["chinese_changed_subtitle_ids"] = [
        subtitle_id
        for subtitle_id in all_ids
        if baseline.final_by_id.get(subtitle_id, {}).get("chinese")
        != candidate.final_by_id.get(subtitle_id, {}).get("chinese")
    ]
    report["status"] = (
        STATUS_COMPARABLE
        if not report["changed_frozen_inputs"]
        and not report["changed_runtime_config"]
        and not report["changed_article_reference_state"]
        and not report["final_output_changes"]
        else STATUS_ISOLATION_FAILED
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify whether two stable subtitle runs are valid allocation-only A/B inputs."
    )
    parser.add_argument("--baseline-artifact-dir", required=True, type=Path)
    parser.add_argument("--candidate-artifact-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = compare_frozen_mainline_runs(
        args.baseline_artifact_dir, args.candidate_artifact_dir
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == STATUS_COMPARABLE else 1


if __name__ == "__main__":
    raise SystemExit(main())
