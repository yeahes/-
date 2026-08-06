"""Validated page-level Chinese mappings below one frozen subtitle ID."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


DISPLAY_PAGE_SCHEMA_VERSION = 1
DISPLAY_PAGE_PLANNER_VERSION = "article-fixed-font-pages-v1"
DISPLAY_PAGE_TRANSLATION_PROMPT_VERSION = "display-page-translation-v2"
DISPLAY_PAGE_TRANSLATION_ALGORITHM_VERSION = "fixed-parent-page-allocation-v2"


class DisplayPageContractError(ValueError):
    """Describe one deterministic page-contract violation."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = str(code)
        self.details = dict(details)
        super().__init__(f"{self.code}: {message}")


def _canonical_hash(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text_hash(text: object) -> str:
    return _canonical_hash(" ".join(str(text or "").split()))


def display_page_id(parent_subtitle_id: str, page_index: int) -> str:
    parent = str(parent_subtitle_id or "").strip()
    if not parent:
        raise DisplayPageContractError(
            "display_page_parent_id_missing",
            "A display page requires a frozen parent subtitle ID.",
        )
    if int(page_index) < 1:
        raise DisplayPageContractError(
            "display_page_index_invalid",
            "Display page indexes are one-based.",
            page_index=page_index,
        )
    return f"{parent}.P{int(page_index):02d}"


def _normalize_parent(parent: Mapping[str, Any]) -> dict[str, Any]:
    parent_id = str(
        parent.get("parent_subtitle_id") or parent.get("subtitle_id") or ""
    ).strip()
    english = " ".join(str(parent.get("english") or "").split())
    chinese = re.sub(r"\s+", "", str(parent.get("chinese") or ""))
    try:
        word_start = int(parent["word_start"])
        word_end = int(parent["word_end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DisplayPageContractError(
            "display_page_parent_word_span_invalid",
            "The parent word span is missing or invalid.",
            parent_subtitle_id=parent_id,
        ) from exc
    if not parent_id or not english or word_start < 0 or word_end < word_start:
        raise DisplayPageContractError(
            "display_page_parent_invalid",
            "The parent ID, English, and frozen word span must be valid.",
            parent_subtitle_id=parent_id,
        )

    raw_pages = list(parent.get("pages") or [])
    if len(raw_pages) < 2:
        raise DisplayPageContractError(
            "display_page_cardinality_invalid",
            "Only genuinely multi-page cues belong in the page contract.",
            parent_subtitle_id=parent_id,
            page_count=len(raw_pages),
        )

    pages: list[dict[str, Any]] = []
    cursor = word_start
    for page_index, page in enumerate(raw_pages, 1):
        page_id = str(page.get("display_page_id") or "").strip()
        expected_page_id = display_page_id(parent_id, page_index)
        try:
            page_word_start = int(page["word_start"])
            page_word_end = int(page["word_end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DisplayPageContractError(
                "display_page_word_span_invalid",
                "A display page word span is missing or invalid.",
                display_page_id=page_id or expected_page_id,
            ) from exc
        page_english = " ".join(str(page.get("english") or "").split())
        if page_id != expected_page_id:
            raise DisplayPageContractError(
                "display_page_id_invalid",
                "Display page IDs must be deterministic and ordered.",
                expected=expected_page_id,
                returned=page_id,
            )
        if page_word_start != cursor or page_word_end < page_word_start:
            raise DisplayPageContractError(
                "display_page_word_coverage_invalid",
                "Display pages must cover the parent words once in order.",
                display_page_id=page_id,
                expected_word_start=cursor,
                word_start=page_word_start,
                word_end=page_word_end,
            )
        if not page_english:
            raise DisplayPageContractError(
                "display_page_english_missing",
                "Every display page must reconstruct frozen English words.",
                display_page_id=page_id,
            )
        normalized_page = {
            "display_page_id": page_id,
            "page_index": page_index,
            "word_start": page_word_start,
            "word_end": page_word_end,
            "english": page_english,
        }
        for key in ("start_ms", "end_ms"):
            if page.get(key) is not None:
                normalized_page[key] = int(page[key])
        pages.append(normalized_page)
        cursor = page_word_end + 1

    if cursor - 1 != word_end:
        raise DisplayPageContractError(
            "display_page_word_coverage_invalid",
            "Display pages do not cover the complete parent word span.",
            parent_subtitle_id=parent_id,
            expected_word_end=word_end,
            actual_word_end=cursor - 1,
        )
    reconstructed_english = " ".join(page["english"] for page in pages)
    if reconstructed_english.split() != english.split():
        raise DisplayPageContractError(
            "display_page_english_drift",
            "Page English does not reconstruct the frozen parent English.",
            parent_subtitle_id=parent_id,
        )

    return {
        "parent_subtitle_id": parent_id,
        "english": english,
        "source_chinese": chinese,
        "word_start": word_start,
        "word_end": word_end,
        "pages": pages,
    }


def build_display_page_contract(
    parents: Sequence[Mapping[str, Any]],
    *,
    layout_profile: Mapping[str, Any],
    planner_version: str = DISPLAY_PAGE_PLANNER_VERSION,
) -> dict[str, Any]:
    normalized = [_normalize_parent(parent) for parent in parents]
    parent_ids = [parent["parent_subtitle_id"] for parent in normalized]
    if len(parent_ids) != len(set(parent_ids)):
        raise DisplayPageContractError(
            "display_page_parent_id_duplicate",
            "A parent subtitle ID may appear only once in the page contract.",
        )
    contract = {
        "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
        "planner_version": str(planner_version),
        "layout_profile": dict(layout_profile),
        "parents": normalized,
    }
    contract["contract_hash"] = _canonical_hash(contract)
    return contract


def page_translation_cache_key(
    contract: Mapping[str, Any],
    *,
    model: str,
    target_language: str,
    prompt_version: str = DISPLAY_PAGE_TRANSLATION_PROMPT_VERSION,
    algorithm_version: str = DISPLAY_PAGE_TRANSLATION_ALGORITHM_VERSION,
    context_hash: str = "",
) -> str:
    """Hash page ownership, translation source, and final display timing."""
    semantic_parents = []
    for parent in contract.get("parents") or []:
        semantic_parents.append(
            {
                "parent_subtitle_id": parent.get("parent_subtitle_id"),
                "english_hash": _text_hash(parent.get("english")),
                "source_chinese_hash": _text_hash(parent.get("source_chinese")),
                "word_start": parent.get("word_start"),
                "word_end": parent.get("word_end"),
                "pages": [
                    {
                        "display_page_id": page.get("display_page_id"),
                        "word_start": page.get("word_start"),
                        "word_end": page.get("word_end"),
                        "english_hash": _text_hash(page.get("english")),
                        "start_ms": page.get("start_ms"),
                        "end_ms": page.get("end_ms"),
                    }
                    for page in parent.get("pages") or []
                ],
            }
        )
    return _canonical_hash(
        {
            "schema_version": contract.get("schema_version"),
            "planner_version": contract.get("planner_version"),
            "layout_profile": contract.get("layout_profile"),
            "prompt_version": str(prompt_version),
            "algorithm_version": str(algorithm_version),
            "model": str(model),
            "target_language": str(target_language),
            "context_hash": str(context_hash),
            "parents": semantic_parents,
        }
    )


def page_translation_request_payload(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    layout_profile = dict(contract.get("layout_profile") or {})
    for parent_index, parent in enumerate(contract.get("parents") or [], 1):
        payload.append(
            {
                "id": parent_index,
                "parent_subtitle_id": parent.get("parent_subtitle_id"),
                "full_english": parent.get("english"),
                "full_translation": parent.get("source_chinese"),
                "pages": [
                    {
                        "display_page_id": page.get("display_page_id"),
                        "english": page.get("english"),
                        "duration_ms": max(
                            0,
                            int(page.get("end_ms") or 0)
                            - int(page.get("start_ms") or 0),
                        ),
                        "target_zh_chars": max(
                            4,
                            int(
                                max(
                                    0,
                                    int(page.get("end_ms") or 0)
                                    - int(page.get("start_ms") or 0),
                                )
                                / 1000.0
                                * 8
                            ),
                        ),
                        "absolute_max_zh_chars": max(
                            6,
                            int(
                                max(
                                    0,
                                    int(page.get("end_ms") or 0)
                                    - int(page.get("start_ms") or 0),
                                )
                                / 1000.0
                                * 12.25
                            ),
                        ),
                        "chinese_font_size": layout_profile.get("chinese_font_size"),
                        "max_lines": layout_profile.get("max_lines"),
                    }
                    for page in parent.get("pages") or []
                ],
            }
        )
    return payload


def _response_rows(response: object) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []

    def visit(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, Mapping):
            return
        if str(node.get("display_page_id") or "").strip():
            rows.append(node)
            return
        for key in ("parents", "groups", "pages", "page_translations"):
            nested = node.get(key)
            if isinstance(nested, list):
                visit(nested)

    visit(response)
    return rows


def validate_page_translation_response(
    contract: Mapping[str, Any],
    response: object,
) -> dict[str, Any]:
    expected_pages = [
        page
        for parent in contract.get("parents") or []
        for page in parent.get("pages") or []
    ]
    expected_ids = [str(page.get("display_page_id") or "") for page in expected_pages]
    rows = _response_rows(response)
    returned_ids = [str(row.get("display_page_id") or "").strip() for row in rows]
    duplicate_ids = sorted({page_id for page_id in returned_ids if returned_ids.count(page_id) > 1})
    missing_ids = sorted(set(expected_ids) - set(returned_ids))
    unknown_ids = sorted(set(returned_ids) - set(expected_ids))
    errors: list[dict[str, Any]] = []
    if duplicate_ids:
        errors.append({"code": "page_translation_id_duplicate", "ids": duplicate_ids})
    if missing_ids:
        errors.append({"code": "page_translation_id_missing", "ids": missing_ids})
    if unknown_ids:
        errors.append({"code": "page_translation_id_unknown", "ids": unknown_ids})
    if len(returned_ids) != len(expected_ids):
        errors.append(
            {
                "code": "page_translation_cardinality_mismatch",
                "expected_count": len(expected_ids),
                "returned_count": len(returned_ids),
            }
        )

    by_id: dict[str, str] = {}
    for row in rows:
        page_id = str(row.get("display_page_id") or "").strip()
        chinese = re.sub(r"\s+", "", str(row.get("zh") or row.get("chinese") or ""))
        if page_id not in expected_ids or page_id in by_id:
            continue
        if not chinese or not re.search(r"[\u4e00-\u9fff]", chinese):
            errors.append(
                {
                    "code": "page_translation_chinese_missing",
                    "display_page_id": page_id,
                }
            )
        by_id[page_id] = chinese

    if errors:
        return {
            "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
            "status": "ERROR",
            "contract_hash": contract.get("contract_hash"),
            "errors": errors,
            "parents": [],
        }

    validated_parents: list[dict[str, Any]] = []
    for parent in contract.get("parents") or []:
        pages = [
            {
                **dict(page),
                "zh": by_id[str(page.get("display_page_id"))],
            }
            for page in parent.get("pages") or []
        ]
        aggregate_chinese = "".join(page["zh"] for page in pages)
        validated_parents.append(
            {
                "parent_subtitle_id": parent.get("parent_subtitle_id"),
                "parent_english_hash": _text_hash(parent.get("english")),
                "source_parent_chinese_hash": _text_hash(parent.get("source_chinese")),
                "render_parent_chinese_hash": _text_hash(aggregate_chinese),
                "word_start": parent.get("word_start"),
                "word_end": parent.get("word_end"),
                "aggregate_chinese": aggregate_chinese,
                "pages": pages,
            }
        )
    return {
        "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
        "status": "PASS",
        "contract_hash": contract.get("contract_hash"),
        "planner_version": contract.get("planner_version"),
        "layout_profile": dict(contract.get("layout_profile") or {}),
        "errors": [],
        "parents": validated_parents,
    }


def parent_chinese_by_id(artifact: Mapping[str, Any]) -> dict[str, str]:
    if str(artifact.get("status") or "") != "PASS":
        raise DisplayPageContractError(
            "page_translation_artifact_invalid",
            "Only a validated page translation artifact can update parent cues.",
        )
    result: dict[str, str] = {}
    for parent in artifact.get("parents") or []:
        parent_id = str(parent.get("parent_subtitle_id") or "").strip()
        chinese = re.sub(r"\s+", "", str(parent.get("aggregate_chinese") or ""))
        if not parent_id or not chinese or parent_id in result:
            raise DisplayPageContractError(
                "page_translation_artifact_parent_invalid",
                "The validated artifact contains an invalid parent mapping.",
                parent_subtitle_id=parent_id,
            )
        result[parent_id] = chinese
    return result
