"""Validated page-level Chinese mappings below one frozen subtitle ID."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from typing import Any, Mapping, Sequence

from app.core.subtitle_processor.chinese_token_boundaries import (
    chinese_token_boundaries,
    chinese_tokens,
)


DISPLAY_PAGE_SCHEMA_VERSION = 2
DISPLAY_PAGE_PLANNER_VERSION = "article-fixed-font-pages-v24"
DISPLAY_PAGE_TRANSLATION_PROMPT_VERSION = "display-page-translation-v5"
DISPLAY_PAGE_TRANSLATION_SOURCE_ECHO_VERSION = "display-page-translation-source-echo-v1"
DISPLAY_PAGE_TRANSLATION_ALGORITHM_VERSION = "fixed-parent-page-allocation-v6"


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


def _normalize_page_boundary(boundary: object) -> dict[str, Any]:
    value = dict(boundary) if isinstance(boundary, Mapping) else {}
    classification = str(value.get("classification") or "allow")
    confidence = str(value.get("confidence") or "low")
    if classification not in {"allow", "review", "hard"}:
        raise DisplayPageContractError(
            "display_page_boundary_classification_invalid",
            "A frozen page boundary has an invalid classification.",
            classification=classification,
        )
    if confidence not in {"low", "medium", "high"}:
        raise DisplayPageContractError(
            "display_page_boundary_confidence_invalid",
            "A frozen page boundary has an invalid confidence.",
            confidence=confidence,
        )
    result: dict[str, Any] = {
        "classification": classification,
        "confidence": confidence,
        "issue_codes": sorted(
            {str(code) for code in value.get("issue_codes") or [] if str(code)}
        ),
    }
    for key in ("pause_ms", "boundary_score"):
        if value.get(key) is not None:
            result[key] = value[key]
    if value.get("protected_syntax") is not None:
        result["protected_syntax"] = bool(value.get("protected_syntax"))
    return result


def _normalize_render_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    parent_id = str(plan.get("parent_subtitle_id") or "").strip()
    english = " ".join(str(plan.get("english") or "").split())
    chinese = re.sub(r"\s+", "", str(plan.get("chinese") or ""))
    try:
        word_start = int(plan["word_start"])
        word_end = int(plan["word_end"])
        english_font_size = int(plan["english_font_size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DisplayPageContractError(
            "display_render_plan_invalid",
            "A frozen render plan is missing its word span or font size.",
            parent_subtitle_id=parent_id,
        ) from exc
    if (
        not parent_id
        or not english
        or word_start < 0
        or word_end < word_start
        or english_font_size <= 0
    ):
        raise DisplayPageContractError(
            "display_render_plan_invalid",
            "A frozen render plan has invalid identity, text, span, or typography.",
            parent_subtitle_id=parent_id,
        )

    raw_pages = list(plan.get("pages") or [])
    if not raw_pages:
        raise DisplayPageContractError(
            "display_render_plan_page_missing",
            "Every frozen cue requires at least one render page.",
            parent_subtitle_id=parent_id,
        )
    pages: list[dict[str, Any]] = []
    cursor = word_start
    for page_index, page in enumerate(raw_pages, 1):
        page_id = str(page.get("display_page_id") or "").strip()
        expected_page_id = display_page_id(parent_id, page_index)
        try:
            page_word_start = int(page["word_start"])
            page_word_end = int(page["word_end"])
            start_ms = int(page["start_ms"])
            end_ms = int(page["end_ms"])
            page_font_size = int(page["english_font_size"])
            english_width = int(page["english_width"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DisplayPageContractError(
                "display_render_page_invalid",
                "A frozen render page is missing its span, timing, or typography.",
                display_page_id=page_id or expected_page_id,
            ) from exc
        page_english = " ".join(str(page.get("english") or "").split())
        english_lines = [
            " ".join(str(line or "").split())
            for line in page.get("english_lines") or []
            if str(line or "").strip()
        ]
        if (
            page_id != expected_page_id
            or page_word_start != cursor
            or page_word_end < page_word_start
            or not page_english
            or not english_lines
            or " ".join(english_lines).split() != page_english.split()
            or start_ms < 0
            or end_ms <= start_ms
            or page_font_size <= 0
            or english_width <= 0
        ):
            raise DisplayPageContractError(
                "display_render_page_invalid",
                "A frozen render page violates identity, coverage, timing, or layout.",
                display_page_id=page_id or expected_page_id,
            )
        pages.append(
            {
                "display_page_id": page_id,
                "page_index": page_index,
                "word_start": page_word_start,
                "word_end": page_word_end,
                "english": page_english,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "english_lines": english_lines,
                "english_font_size": page_font_size,
                "english_width": english_width,
                "boundary_before": _normalize_page_boundary(
                    page.get("boundary_before")
                ),
            }
        )
        cursor = page_word_end + 1
    if cursor - 1 != word_end or " ".join(
        page["english"] for page in pages
    ).split() != english.split():
        raise DisplayPageContractError(
            "display_render_plan_coverage_invalid",
            "Frozen render pages must reconstruct the parent word span and English.",
            parent_subtitle_id=parent_id,
        )
    if min(page["english_font_size"] for page in pages) != english_font_size:
        raise DisplayPageContractError(
            "display_render_plan_font_summary_invalid",
            "The parent font size must equal the smallest final-page font size.",
            parent_subtitle_id=parent_id,
        )
    return {
        "parent_subtitle_id": parent_id,
        "english": english,
        "chinese": chinese,
        "word_start": word_start,
        "word_end": word_end,
        "english_font_size": english_font_size,
        "font_fallback": dict(plan.get("font_fallback") or {"used": False}),
        "pages": pages,
    }


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
    render_plans: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    normalized = [_normalize_parent(parent) for parent in parents]
    parent_ids = [parent["parent_subtitle_id"] for parent in normalized]
    if len(parent_ids) != len(set(parent_ids)):
        raise DisplayPageContractError(
            "display_page_parent_id_duplicate",
            "A parent subtitle ID may appear only once in the page contract.",
        )
    normalized_render_plans = [_normalize_render_plan(plan) for plan in render_plans]
    render_plan_ids = [plan["parent_subtitle_id"] for plan in normalized_render_plans]
    if len(render_plan_ids) != len(set(render_plan_ids)):
        raise DisplayPageContractError(
            "display_render_plan_parent_id_duplicate",
            "A frozen subtitle ID may own only one render plan.",
        )
    if normalized_render_plans and not set(parent_ids).issubset(set(render_plan_ids)):
        raise DisplayPageContractError(
            "display_render_plan_parent_missing",
            "Every translated multi-page parent requires a frozen render plan.",
        )
    contract = {
        "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
        "planner_version": str(planner_version),
        "layout_profile": dict(layout_profile),
        "parents": normalized,
        "render_plans": normalized_render_plans,
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
            "render_plan_hash": _canonical_hash(
                contract.get("render_plans") or []
            ),
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
                        "source_echo_required": True,
                        "source_echo_version": DISPLAY_PAGE_TRANSLATION_SOURCE_ECHO_VERSION,
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


def _translation_content(text: object) -> str:
    return "".join(
        re.findall(r"[\u4e00-\u9fffA-Za-z0-9%$¥￥]+", str(text or "").lower())
    )


def _translation_content_tokens(text: object) -> tuple[str, ...] | None:
    tokens = chinese_tokens(str(text or ""))
    if tokens is None:
        return None
    return tuple(
        normalized
        for token in tokens
        if (normalized := _translation_content(token))
    )


def _nonoverlapping_phrase_count(
    tokens: Sequence[str], phrase: Sequence[str]
) -> int:
    if not phrase or len(tokens) < len(phrase):
        return 0
    count = 0
    index = 0
    width = len(phrase)
    target = tuple(phrase)
    while index + width <= len(tokens):
        if tuple(tokens[index : index + width]) == target:
            count += 1
            index += width
        else:
            index += 1
    return count


def _repeated_parent_phrase(source: str, aggregate: str) -> str:
    source_tokens = _translation_content_tokens(source)
    aggregate_tokens = _translation_content_tokens(aggregate)
    if not source_tokens or not aggregate_tokens:
        return ""
    max_width = min(6, len(source_tokens))
    for width in range(max_width, 1, -1):
        for start in range(0, len(source_tokens) - width + 1):
            phrase = source_tokens[start : start + width]
            phrase_text = "".join(phrase)
            if len(re.findall(r"[\u4e00-\u9fff]", phrase_text)) < 4:
                continue
            if _nonoverlapping_phrase_count(source_tokens, phrase) != 1:
                continue
            if _nonoverlapping_phrase_count(aggregate_tokens, phrase) >= 2:
                return phrase_text
    return ""


def _parent_projection_quality_errors(
    parent_subtitle_id: str,
    source: str,
    aggregate: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    repeated_phrase = _repeated_parent_phrase(source, aggregate)
    if repeated_phrase:
        errors.append(
            {
                "code": "page_translation_parent_meaning_repeated",
                "parent_subtitle_id": parent_subtitle_id,
                "repeated_phrase": repeated_phrase,
            }
        )

    source_content = _translation_content(source)
    aggregate_content = _translation_content(aggregate)
    growth = len(aggregate_content) - len(source_content)
    growth_limit = max(8, math.ceil(len(source_content) * 0.35))
    extra_characters = Counter(aggregate_content) - Counter(source_content)
    extra_chinese_count = sum(
        count
        for character, count in extra_characters.items()
        if "\u4e00" <= character <= "\u9fff"
    )
    if source_content and growth >= growth_limit and extra_chinese_count >= 4:
        errors.append(
            {
                "code": "page_translation_parent_meaning_expanded",
                "parent_subtitle_id": parent_subtitle_id,
                "source_content_length": len(source_content),
                "aggregate_content_length": len(aggregate_content),
                "growth": growth,
                "allowed_growth": growth_limit - 1,
                "extra_chinese_count": extra_chinese_count,
            }
        )
    return errors


def validate_page_translation_response(
    contract: Mapping[str, Any],
    response: object,
    *,
    require_source_echo: bool = False,
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
    expected_english_by_id = {
        str(page.get("display_page_id") or ""): str(page.get("english") or "")
        for page in expected_pages
    }
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
        if require_source_echo:
            source_echo = " ".join(str(row.get("source_english") or "").split())
            expected_english = " ".join(expected_english_by_id.get(page_id, "").split())
            if not source_echo:
                errors.append(
                    {
                        "code": "page_translation_source_echo_missing",
                        "display_page_id": page_id,
                    }
                )
            elif source_echo.split() != expected_english.split():
                errors.append(
                    {
                        "code": "page_translation_source_echo_mismatch",
                        "display_page_id": page_id,
                        "expected": expected_english,
                        "returned": source_echo,
                    }
                )
        by_id[page_id] = chinese

    if errors:
        return {
            "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
            "status": "ERROR",
            "contract_hash": contract.get("contract_hash"),
            "planner_version": contract.get("planner_version"),
            "layout_profile": dict(contract.get("layout_profile") or {}),
            "render_plans": [
                dict(plan) for plan in contract.get("render_plans") or []
            ],
            "errors": errors,
            "parents": [],
        }

    validated_parents: list[dict[str, Any]] = []
    for parent in contract.get("parents") or []:
        parent_error_count = len(errors)
        pages = [
            {
                **dict(page),
                "zh": by_id[str(page.get("display_page_id"))],
            }
            for page in parent.get("pages") or []
        ]
        aggregate_chinese = "".join(page["zh"] for page in pages)
        source_chinese = re.sub(
            r"\s+", "", str(parent.get("source_chinese") or "")
        )
        errors.extend(
            _parent_projection_quality_errors(
                str(parent.get("parent_subtitle_id") or ""),
                source_chinese,
                aggregate_chinese,
            )
        )
        token_boundaries = chinese_token_boundaries(aggregate_chinese)
        if token_boundaries is None:
            errors.append(
                {
                    "code": "page_translation_chinese_tokenizer_unavailable",
                    "parent_subtitle_id": parent.get("parent_subtitle_id"),
                }
            )
        else:
            offset = 0
            for page in pages[:-1]:
                offset += len(page["zh"])
                if offset not in token_boundaries:
                    errors.append(
                        {
                            "code": "page_translation_chinese_token_split",
                            "parent_subtitle_id": parent.get("parent_subtitle_id"),
                            "display_page_id": page.get("display_page_id"),
                            "boundary_offset": offset,
                        }
                    )
        if len(errors) == parent_error_count:
            validated_parents.append(
                {
                    "parent_subtitle_id": parent.get("parent_subtitle_id"),
                    "parent_english_hash": _text_hash(parent.get("english")),
                    "source_parent_chinese": source_chinese,
                    "source_parent_chinese_hash": _text_hash(parent.get("source_chinese")),
                    "render_parent_chinese_hash": _text_hash(aggregate_chinese),
                    "word_start": parent.get("word_start"),
                    "word_end": parent.get("word_end"),
                    "aggregate_chinese": aggregate_chinese,
                    "pages": pages,
                }
            )
    if errors:
        return {
            "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
            "status": "ERROR",
            "contract_hash": contract.get("contract_hash"),
            "planner_version": contract.get("planner_version"),
            "layout_profile": dict(contract.get("layout_profile") or {}),
            "render_plans": [
                dict(plan) for plan in contract.get("render_plans") or []
            ],
            "errors": errors,
            "parents": validated_parents,
        }
    return {
        "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
        "status": "PASS",
        "contract_hash": contract.get("contract_hash"),
        "planner_version": contract.get("planner_version"),
        "layout_profile": dict(contract.get("layout_profile") or {}),
        "render_plans": [
            dict(plan) for plan in contract.get("render_plans") or []
        ],
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
        chinese = re.sub(
            r"\s+", "", str(parent.get("source_parent_chinese") or "")
        )
        if not parent_id or not chinese or parent_id in result:
            raise DisplayPageContractError(
                "page_translation_artifact_parent_invalid",
                "The validated artifact contains an invalid parent mapping.",
                parent_subtitle_id=parent_id,
            )
        result[parent_id] = chinese
    return result
