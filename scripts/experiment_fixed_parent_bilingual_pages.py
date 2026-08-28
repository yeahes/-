"""Run a read-only bilingual A/B for fixed-parent page candidate ordering.

The experiment never writes to a stable artifact, production cache, subtitle,
or checkpoint. Optional model calls allocate the already authoritative parent
Chinese over changed page candidates and are stored only in the report.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.subtitle_processor.stable_display_page_contract import (
    build_display_page_contract,
    validate_page_translation_response,
)
from app.core.utils.podcast_learning_video import current_llm_config
from scripts import audit_article_page_candidate_frontier as frontier


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _resolve_artifact_dir(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_dir() and resolved.name.endswith("-artifacts"):
        return resolved
    candidates = sorted(
        item
        for item in resolved.iterdir()
        if item.is_dir() and item.name.endswith("-artifacts")
    )
    if len(candidates) != 1:
        raise ValueError(
            f"expected one *-artifacts directory below {resolved}, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def _parent_chinese_by_id(artifact_dir: Path) -> dict[str, str]:
    payload = _read_json(artifact_dir / "authoritative-parent-chinese.json")
    result: dict[str, str] = {}
    for record in payload.get("records") or []:
        subtitle_id = str(record.get("subtitle_id") or "")
        chinese = str(record.get("chinese") or "").strip()
        if subtitle_id and chinese:
            result[subtitle_id] = chinese
    return result


def _spans_by_id(artifact_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        str(record.get("subtitle_id") or ""): dict(record)
        for record in _read_json(artifact_dir / "subtitle-spans.json")
    }


def build_changed_page_contract(
    artifact_dir: Path,
    changed_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not changed_records:
        return None
    spans = _spans_by_id(artifact_dir)
    chinese_by_id = _parent_chinese_by_id(artifact_dir)
    saved_page_artifact = _read_json(
        artifact_dir / "display-page-translations.json"
    )
    parents = []
    for record in changed_records:
        subtitle_id = str(record.get("subtitle_id") or "")
        span = spans.get(subtitle_id)
        chinese = chinese_by_id.get(subtitle_id, "")
        pages = list((record.get("material") or {}).get("pages") or [])
        if span is None or not chinese or len(pages) < 2:
            raise ValueError(
                f"changed page candidate lacks parent authority: {subtitle_id}"
            )
        parents.append(
            {
                "parent_subtitle_id": subtitle_id,
                "english": str(span.get("original") or ""),
                "chinese": chinese,
                "word_start": int(span["word_start"]),
                "word_end": int(span["word_end"]),
                "pages": [
                    {
                        "display_page_id": f"{subtitle_id}.P{index:02d}",
                        "word_start": int(page["word_start"]),
                        "word_end": int(page["word_end"]),
                        "english": str(page["english"]),
                        "start_ms": int(page["start_ms"]),
                        "end_ms": int(page["end_ms"]),
                    }
                    for index, page in enumerate(pages, 1)
                ],
            }
        )
    return build_display_page_contract(
        parents,
        layout_profile=dict(saved_page_artifact.get("layout_profile") or {}),
    )


def _page_rows_by_parent(artifact: Mapping[str, Any]) -> dict[str, list[dict]]:
    return {
        str(parent.get("parent_subtitle_id") or ""): [
            {
                "display_page_id": str(page.get("display_page_id") or ""),
                "english": str(page.get("english") or ""),
                "chinese": str(page.get("zh") or ""),
                "word_start": int(page.get("word_start") or 0),
                "word_end": int(page.get("word_end") or 0),
                "start_ms": int(page.get("start_ms") or 0),
                "end_ms": int(page.get("end_ms") or 0),
            }
            for page in parent.get("pages") or []
        ]
        for parent in artifact.get("parents") or []
    }


def _request_page_chinese(
    contract: Mapping[str, Any],
    *,
    timeout: int,
) -> dict[str, Any]:
    base_url, api_key, model = current_llm_config()
    if not base_url or not api_key or not model:
        return {
            "status": "SKIPPED",
            "reason": "configured_llm_missing",
            "api_attempt_count": 0,
        }
    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_KEY"] = api_key
    editor = ScreenSubtitleEditor(
        model=model,
        full_translation_model=model,
        allocation_review_model=model,
        timeout=timeout,
        translation_request_budget=8,
        translation_request_max_attempts=2,
    )
    response, error, attempts = editor._request_display_page_translation_api_only(
        contract
    )
    if error or response is None:
        return {
            "status": "ERROR",
            "reason": error or "empty_response",
            "api_attempt_count": len(attempts),
        }
    artifact = validate_page_translation_response(
        contract,
        response,
        require_source_echo=True,
    )
    quality_errors = editor._display_page_translation_quality_errors(
        contract,
        artifact,
    )
    retry_attempts = []
    if artifact.get("status") != "PASS" or quality_errors:
        retry_errors = [
            *list(artifact.get("errors") or []),
            *quality_errors,
        ]
        retry_response, retry_error, retry_attempts = (
            editor._request_display_page_translation_api_only(
                contract,
                retry_errors=retry_errors,
            )
        )
        if retry_response is not None and not retry_error:
            retry_artifact = validate_page_translation_response(
                contract,
                retry_response,
                require_source_echo=True,
            )
            retry_quality_errors = editor._display_page_translation_quality_errors(
                contract,
                retry_artifact,
            )
            if retry_artifact.get("status") == "PASS" and not retry_quality_errors:
                artifact = retry_artifact
                quality_errors = []
            else:
                artifact = retry_artifact
                quality_errors = retry_quality_errors
        elif retry_error:
            quality_errors.append(
                {
                    "code": "experimental_page_translation_retry_failed",
                    "message": retry_error,
                }
            )
    status = (
        "PASS"
        if artifact.get("status") == "PASS" and not quality_errors
        else "ERROR"
    )
    return {
        "status": status,
        "model": model,
        "api_attempt_count": len(attempts) + len(retry_attempts),
        "contract_hash": contract.get("contract_hash"),
        "validator_errors": list(artifact.get("errors") or []),
        "quality_errors": quality_errors,
        "pages_by_parent": _page_rows_by_parent(artifact),
    }


def _baseline_pages_by_parent(
    artifact_dir: Path,
    parent_ids: set[str],
) -> dict[str, list[dict]]:
    artifact = _read_json(artifact_dir / "display-page-translations.json")
    return {
        parent_id: pages
        for parent_id, pages in _page_rows_by_parent(artifact).items()
        if parent_id in parent_ids
    }


def audit_case(
    name: str,
    path: Path,
    *,
    translate_changed: bool,
    timeout: int,
) -> dict[str, Any]:
    artifact_dir = _resolve_artifact_dir(path)
    english_report = frontier.audit(artifact_dir)
    changed = list(english_report.get("material_changed_cues") or [])
    parent_ids = {str(record.get("subtitle_id") or "") for record in changed}
    contract = build_changed_page_contract(artifact_dir, changed)
    if contract is None:
        chinese_result = {
            "status": "NOT_REQUIRED",
            "api_attempt_count": 0,
            "pages_by_parent": {},
        }
    elif translate_changed:
        chinese_result = _request_page_chinese(contract, timeout=timeout)
    else:
        chinese_result = {
            "status": "SKIPPED",
            "reason": "translation_disabled",
            "api_attempt_count": 0,
            "pages_by_parent": {},
        }
    candidate_pages = dict(chinese_result.get("pages_by_parent") or {})
    baseline_pages = _baseline_pages_by_parent(artifact_dir, parent_ids)
    comparisons = []
    for record in changed:
        subtitle_id = str(record.get("subtitle_id") or "")
        comparisons.append(
            {
                "subtitle_id": subtitle_id,
                "english": record.get("english"),
                "improvement_reason": record.get("material_selection_reason"),
                "baseline_pages": (record.get("production") or {}).get("pages", []),
                "candidate_pages": (record.get("material") or {}).get("pages", []),
                "baseline_page_chinese": baseline_pages.get(subtitle_id, []),
                "candidate_page_chinese": candidate_pages.get(subtitle_id, []),
                "bilingual_candidate_complete": bool(
                    chinese_result.get("status") == "PASS"
                    and candidate_pages.get(subtitle_id)
                ),
            }
        )
    return {
        "name": name,
        "artifact_dir": str(artifact_dir),
        "status": english_report.get("status"),
        "source_cue_count": english_report.get("source_cue_count"),
        "english_failure_count": english_report.get("failure_count"),
        "material_changed_cue_count": len(changed),
        "production_metrics": english_report.get("production"),
        "candidate_metrics": english_report.get("material"),
        "page_chinese": chinese_result,
        "comparisons": comparisons,
    }


def _parse_case(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("case must use NAME=PATH")
    name, path = value.split("=", 1)
    if not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError("case must use NAME=PATH")
    return name.strip(), Path(path.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", required=True, type=_parse_case)
    parser.add_argument("--translate-changed", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    cases = [
        audit_case(
            name,
            path,
            translate_changed=bool(args.translate_changed),
            timeout=max(10, int(args.timeout)),
        )
        for name, path in args.case
    ]
    report = {
        "schema_version": 1,
        "experiment": "fixed-parent-bilingual-page-ordering-v1",
        "production_files_modified": False,
        "artifact_files_modified": False,
        "production_cache_modified": False,
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "changed_cue_count": sum(
                int(case["material_changed_cue_count"]) for case in cases
            ),
            "bilingual_complete_change_count": sum(
                sum(
                    bool(item["bilingual_candidate_complete"])
                    for item in case["comparisons"]
                )
                for case in cases
            ),
            "api_attempt_count": sum(
                int((case.get("page_chinese") or {}).get("api_attempt_count") or 0)
                for case in cases
            ),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "elapsed_seconds": report["elapsed_seconds"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
