"""Validation helpers for optional, ID-bound Chinese review suggestions.

Suggestions are deliberately separate from stable translation artifacts.  A
caller may display or manually accept a validated suggestion, but this module
never mutates subtitles, English text, IDs, timing, or page geometry.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.core.subtitle_processor.stable_artifacts import write_json_artifact


_ID_RE = re.compile(r"^S\d{4}(?:\.P\d{2})?$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?")
_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?(?![A-Za-z])")
_NEGATION_RE = re.compile(r"\b(?:no|not|never|neither|nor|without|hardly|cannot|can't|won't|don't|doesn't|didn't)\b", re.I)
_CURRENCY_UNITS = {
    "美元": ("usd", "dollar", "dollars", "u.s. dollar", "u.s. dollars", "$"),
    "元": ("cny", "rmb", "yuan", "renminbi", "元"),
    "英镑": ("gbp", "pound", "pounds", "£"),
    "欧元": ("eur", "euro", "euros", "€"),
}
_MONEY_CONTEXT_RE = re.compile(
    r"\b(?:cost|costs|price|prices|fee|fees|charge|charges|pay|paid|payment|"
    r"salary|salaries|rent|wage|wages|budget|funding|worth|"
    r"(?:per|a)\s+(?:session|month|year|day)|"
    r"pay(?:ing|s)?|"
    r"dollar|dollars|yuan|renminbi|rmb|usd|eur|euro|pound|pounds)\b",
    re.I,
)
_COUNT_NOUN_AFTER_NUMBER_RE = re.compile(
    r"^\s*(?:people|persons|clients|patients|sessions|cases|women|men|children|"
    r"students|years?|months?|days?|times?|percent|percentage\s+points?)\b",
    re.I,
)


def _normalized_tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(str(text or ""))]


def current_chinese_hash(chinese: str) -> str:
    """Return the stable identity of the Chinese text a suggestion reviewed."""
    normalized = " ".join(str(chinese or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalized_source(text: str) -> str:
    return " ".join(str(text or "").split())


def _protected_terms(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    protected = row.get("protected_anchors") or row.get("fact_anchors") or {}
    terms = protected.get("terms") if isinstance(protected, Mapping) else protected
    result: list[tuple[str, str]] = []
    for term in terms or []:
        if isinstance(term, Mapping):
            source = str(term.get("source") or term.get("english") or "").strip()
            target = str(term.get("target") or term.get("chinese") or "").strip()
        else:
            source = target = str(term or "").strip()
        if source and target:
            result.append((source, target))
    return result


def _fact_anchors(text: str) -> dict[str, set[str]]:
    source = str(text or "")
    return {
        "numbers": {value.casefold() for value in _NUMBER_RE.findall(source)},
        "negation": {"negation"} if _NEGATION_RE.search(source) else set(),
    }


def validate_translation_review_suggestions(
    payload: Any,
    expected: Mapping[str, Mapping[str, str]],
    *,
    require_complete: bool = False,
) -> dict[str, Any]:
    """Validate suggestion rows against an exact fixed-ID source map.

    ``expected`` maps a stable ID to ``english`` and the current ``chinese``.
    The returned payload contains only valid rows and explicit errors.  It is
    safe to persist as a read-only review artifact.
    """
    raw_rows = payload.get("suggestions") if isinstance(payload, Mapping) else payload
    if not isinstance(raw_rows, list):
        return {"valid": False, "suggestions": [], "errors": [{"code": "suggestions_not_a_list"}]}
    valid: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            errors.append({"code": "suggestion_row_invalid"})
            continue
        subtitle_id = str(raw.get("subtitle_id") or "").strip()
        expected_row = expected.get(subtitle_id)
        if not _ID_RE.fullmatch(subtitle_id):
            errors.append({"code": "suggestion_id_invalid", "subtitle_id": subtitle_id})
            continue
        if expected_row is None:
            errors.append({"code": "suggestion_id_unknown", "subtitle_id": subtitle_id})
            continue
        if subtitle_id in seen:
            errors.append({"code": "suggestion_id_duplicate", "subtitle_id": subtitle_id})
            continue
        seen.add(subtitle_id)
        source_echo = _normalized_source(raw.get("source_english") or "")
        expected_english = _normalized_source(expected_row.get("english") or "")
        if source_echo != expected_english:
            errors.append({"code": "suggestion_source_echo_mismatch", "subtitle_id": subtitle_id})
            continue
        current_hash = str(raw.get("current_chinese_hash") or "").strip()
        if not current_hash or current_hash != current_chinese_hash(
            str(expected_row.get("chinese") or "")
        ):
            errors.append({"code": "suggestion_current_chinese_mismatch", "subtitle_id": subtitle_id})
            continue
        replacement = str(raw.get("suggested_chinese") or raw.get("chinese") or "").strip()
        if not replacement or not re.search(r"[\u4e00-\u9fff]", replacement):
            errors.append({"code": "suggestion_chinese_missing", "subtitle_id": subtitle_id})
            continue
        source_anchors = _fact_anchors(expected_english)
        candidate_anchors = _fact_anchors(replacement)
        if source_anchors["numbers"] and not source_anchors["numbers"].issubset(
            candidate_anchors["numbers"]
        ):
            errors.append({"code": "suggestion_lost_numbers", "subtitle_id": subtitle_id})
        for number in source_anchors["numbers"]:
            source_currency = _currency_units_attached_to_number(
                expected_english, number
            )
            if source_currency and not source_currency.issubset(
                _currency_units_attached_to_number(replacement, number)
            ):
                errors.append(
                    {
                        "code": "suggestion_lost_currency_unit",
                        "subtitle_id": subtitle_id,
                    }
                )
                break
        if source_anchors["negation"] and not re.search(
            r"(?:不|没|无|未|从不|不能|不会|并非|没有|不再)", replacement
        ):
            errors.append({"code": "suggestion_lost_negation", "subtitle_id": subtitle_id})
        protected_terms = _protected_terms(expected_row)
        echoed_sources = {str(value).casefold() for value in raw.get("source_anchor_echo") or []}
        for source, target in protected_terms:
            if source.casefold() not in echoed_sources or target not in replacement:
                errors.append({"code": "suggestion_lost_protected_anchor", "subtitle_id": subtitle_id})
                break
        if any(error.get("subtitle_id") == subtitle_id for error in errors):
            continue
        valid.append(
            {
                "subtitle_id": subtitle_id,
                "source_english": expected_english,
                "current_chinese": str(expected_row.get("chinese") or ""),
                "current_chinese_hash": current_hash,
                "suggested_chinese": replacement,
                "reason": str(raw.get("reason") or "")[:500],
            }
        )
    expected_ids = set(expected)
    missing = sorted(expected_ids - seen)
    return {
        "valid": not errors and (not missing or not require_complete),
        "suggestions": valid,
        "errors": errors,
        "missing_ids": missing,
        "accepted_ids": [item["subtitle_id"] for item in valid],
    }


def apply_translation_review_suggestion(
    rows: Mapping[str, Mapping[str, Any]],
    suggestion: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return a copied row map with one already-validated suggestion applied."""
    subtitle_id = str(suggestion.get("subtitle_id") or "").strip()
    if not _ID_RE.fullmatch(subtitle_id):
        raise ValueError("suggestion must target an existing stable subtitle ID")
    replacement = str(suggestion.get("suggested_chinese") or "").strip()
    if not replacement:
        raise ValueError("suggestion has no Chinese replacement")
    result = {str(key): dict(value) for key, value in rows.items()}
    if ".P" in subtitle_id:
        target_keys = [
            key
            for key, row in result.items()
            if str(row.get("display_page_id") or "") == subtitle_id
        ]
    else:
        target_keys = [
            key
            for key, row in result.items()
            if subtitle_id
            in {
                str(row.get("manual_cue_id") or ""),
                str(row.get("subtitle_id") or ""),
            }
        ]
    if not target_keys:
        raise ValueError("suggestion must target an existing stable subtitle ID")
    if len(target_keys) != 1:
        raise ValueError(
            "parent suggestion is ambiguous in display-page rows; use the parent view"
        )
    target_key = target_keys[0]
    row_chinese = str(result[target_key].get("translated_subtitle") or "")
    suggestion_hash = str(suggestion.get("current_chinese_hash") or "").strip()
    if not suggestion_hash or suggestion_hash != current_chinese_hash(row_chinese):
        raise ValueError("suggestion is stale for the current Chinese text")
    result[target_key]["translated_subtitle"] = replacement
    result[target_key]["translation_suggestion_applied"] = True
    return result


def currency_unit_review_suggestions(
    expected: Mapping[str, Mapping[str, str]],
    article_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build high-confidence ID-bound suggestions for explicit currency conflicts.

    A bare number in English is never enough. The same number must have one
    unambiguous currency unit in article evidence, and the current Chinese must
    attach a different recognized unit to that exact number.
    """
    evidence_by_number: dict[str, set[str]] = {}
    for item in article_context.get("numbers_and_dates") or []:
        if not isinstance(item, Mapping):
            continue
        evidence_text = " ".join(
            str(value or "")
            for value in (
                item.get("canonical_name"),
                item.get("chinese_name"),
                " ".join(str(alias or "") for alias in item.get("aliases") or []),
                (item.get("evidence") or {}).get("evidence_sentence"),
            )
        )
        numbers = set(_NUMBER_RE.findall(evidence_text))
        if not bool(item.get("canonical_in_article")):
            continue
        for number in numbers:
            units = _currency_units_attached_to_number(evidence_text, number)
            if len(units) == 1:
                evidence_by_number.setdefault(number, set()).update(units)

    suggestions: list[dict[str, Any]] = []
    for subtitle_id, row in expected.items():
        english = str(row.get("english") or "")
        chinese = str(row.get("chinese") or "")
        english_numbers = _NUMBER_RE.findall(english)
        if len(english_numbers) != len(set(english_numbers)):
            # Repeated values cannot be safely bound to one translated
            # occurrence without word-level semantic alignment.
            continue
        for number in sorted(set(english_numbers)):
            source_units = _currency_units_attached_to_number(english, number)
            if not source_units and not _number_has_money_context(english, number):
                continue
            evidence_units = source_units or (evidence_by_number.get(number) or set())
            current_occurrences = _currency_unit_occurrences(chinese, number)
            current_units = {unit for unit, _start, _end in current_occurrences}
            if re.search(
                rf"(?<!\d){re.escape(number)}\s*(?:元|人民币)\s*人民币",
                chinese,
            ) or re.search(
                rf"(?<!\d){re.escape(number)}\s*元人民币",
                chinese,
            ):
                continue
            if len(current_occurrences) != 1:
                continue
            if len(evidence_units) != 1 or len(current_units) != 1:
                continue
            expected_unit = next(iter(evidence_units))
            current_unit = next(iter(current_units))
            if expected_unit == current_unit:
                continue
            _unit, start, end = current_occurrences[0]
            replacement = f"{chinese[:start]}{number}{expected_unit}{chinese[end:]}"
            if replacement == chinese:
                continue
            suggestions.append(
                {
                    "subtitle_id": str(subtitle_id),
                    "source_english": english,
                    "current_chinese_hash": current_chinese_hash(chinese),
                    "suggested_chinese": replacement,
                    "reason": (
                        f"文章证据明确 {number} 的单位是{expected_unit}，"
                        f"当前译文写成了{current_unit}。"
                    ),
                    "evidence": {
                        "number": number,
                        "expected_unit": expected_unit,
                        "current_unit": current_unit,
                    },
                }
            )
    return suggestions


def translation_review_cache_key(
    entries: Sequence[Mapping[str, Any]],
    *,
    model: str = "",
    prompt_version: str = "translation-review-v1",
) -> str:
    """Deterministically identify one review request, without list-position authority."""
    canonical = {
        "model": str(model),
        "prompt_version": str(prompt_version),
        "entries": [
            {
                "subtitle_id": str(entry.get("subtitle_id") or ""),
                "source_english": _normalized_source(entry.get("source_english") or ""),
                "current_chinese_hash": str(entry.get("current_chinese_hash") or ""),
                "protected_anchors": entry.get("protected_anchors") or {},
                "review_reason": str(entry.get("review_reason") or ""),
                "review_context": entry.get("review_context") or [],
            }
            for entry in sorted(entries, key=lambda item: str(item.get("subtitle_id") or ""))
        ],
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def generate_translation_review_suggestions(
    expected: Mapping[str, Mapping[str, Any]],
    completion: Callable[[dict[str, Any]], Any],
    *,
    groups: Sequence[Sequence[str]] | None = None,
    cache_dir: str | Path | None = None,
    model: str = "",
    prompt_version: str = "translation-review-v1",
) -> dict[str, Any]:
    """Generate optional fixed-ID review suggestions without mutating subtitles.

    A failed or malformed group is isolated.  Valid suggestions from every
    other group remain available for human review, never auto-applied.
    """
    ordered_ids = sorted(expected)
    requested_groups = list(groups or [ordered_ids])
    accepted: list[dict[str, Any]] = []
    group_errors: list[dict[str, Any]] = []
    entry_errors: list[dict[str, Any]] = []
    cache_root = Path(cache_dir) if cache_dir is not None else None
    if cache_root is not None:
        cache_root.mkdir(parents=True, exist_ok=True)
    for requested_ids in requested_groups:
        ids = [str(subtitle_id) for subtitle_id in requested_ids if str(subtitle_id) in expected]
        if not ids:
            continue
        entries = [
            {
                "subtitle_id": subtitle_id,
                "source_english": _normalized_source(expected[subtitle_id].get("english") or ""),
                "current_chinese": str(expected[subtitle_id].get("chinese") or ""),
                "current_chinese_hash": current_chinese_hash(str(expected[subtitle_id].get("chinese") or "")),
                "protected_anchors": expected[subtitle_id].get("protected_anchors") or {},
                "review_reason": str(expected[subtitle_id].get("review_reason") or ""),
                "review_context": expected[subtitle_id].get("review_context") or [],
            }
            for subtitle_id in ids
        ]
        key = translation_review_cache_key(entries, model=model, prompt_version=prompt_version)
        cache_path = cache_root / f"{key}.json" if cache_root is not None else None
        try:
            if cache_path is not None and cache_path.is_file():
                raw_response = json.loads(cache_path.read_text(encoding="utf-8"))
            else:
                raw_response = completion(
                    {
                        "model": str(model),
                        "prompt_version": str(prompt_version),
                        "entries": entries,
                    }
                )
                if cache_path is not None:
                    write_json_artifact(cache_path, raw_response)
        except Exception:
            group_errors.append({"code": "translation_review_completion_failed", "subtitle_ids": ids})
            continue
        response_rows = raw_response.get("reviews") if isinstance(raw_response, Mapping) else None
        if not isinstance(response_rows, list) or len(response_rows) != len(ids):
            group_errors.append({"code": "translation_review_cardinality_mismatch", "subtitle_ids": ids})
            continue
        suggestion_rows = [
            row for row in response_rows
            if isinstance(row, Mapping) and str(row.get("action") or "suggest") == "suggest"
        ]
        response_ids = [str(row.get("subtitle_id") or "") for row in response_rows if isinstance(row, Mapping)]
        if len(response_ids) != len(set(response_ids)) or set(response_ids) != set(ids):
            group_errors.append({"code": "translation_review_cardinality_mismatch", "subtitle_ids": ids})
            continue
        expected_group = {subtitle_id: expected[subtitle_id] for subtitle_id in ids}
        for row in response_rows:
            if not isinstance(row, Mapping) or str(row.get("action") or "suggest") == "suggest":
                continue
            subtitle_id = str(row.get("subtitle_id") or "")
            expected_row = expected_group[subtitle_id]
            if (
                _normalized_source(row.get("source_english") or "")
                != _normalized_source(expected_row.get("english") or "")
                or str(row.get("current_chinese_hash") or "")
                != current_chinese_hash(str(expected_row.get("chinese") or ""))
            ):
                entry_errors.append(
                    {"code": "translation_review_response_binding_failed", "subtitle_ids": [subtitle_id]}
                )
        for row in suggestion_rows:
            row_id = str(row.get("subtitle_id") or "")
            checked = validate_translation_review_suggestions(
                {"suggestions": [row]},
                expected_group,
            )
            if checked.get("errors"):
                entry_errors.append(
                    {
                        "code": "translation_review_entry_validation_failed",
                        "subtitle_ids": [row_id] if row_id in expected_group else [],
                    }
                )
                continue
            accepted.extend(checked.get("suggestions") or [])
    accepted.sort(key=lambda item: str(item["subtitle_id"]))
    return {
        "suggestions": accepted,
        "accepted_ids": [item["subtitle_id"] for item in accepted],
        "group_errors": group_errors,
        "entry_errors": entry_errors,
    }


def _number_has_money_context(text: str, number: str) -> bool:
    source = str(text or "")
    matches = list(
        re.finditer(rf"(?<![A-Za-z0-9]){re.escape(number)}(?![A-Za-z0-9])", source)
    )
    if len(matches) != 1:
        return False
    match = matches[0]
    if _COUNT_NOUN_AFTER_NUMBER_RE.search(source[match.end() :]):
        return False
    left_words = " ".join(source[: match.start()].split()[-5:])
    right_words = " ".join(source[match.end() :].split()[:4])
    return bool(
        _MONEY_CONTEXT_RE.search(left_words)
        or re.match(r"^\s*(?:a|per)\s+(?:session|month|year|day)\b", right_words, re.I)
    )


def _currency_units_attached_to_number(text: str, number: str) -> set[str]:
    return {unit for unit, _start, _end in _currency_unit_occurrences(text, number)}


def _currency_unit_occurrences(
    text: str,
    number: str,
) -> list[tuple[str, int, int]]:
    source = str(text or "")
    result: list[tuple[str, int, int]] = []
    for unit, aliases in _CURRENCY_UNITS.items():
        for alias in aliases:
            escaped = re.escape(alias)
            if alias in {"$", "£", "€"}:
                pattern = rf"{escaped}\s*(?<!\d){re.escape(number)}(?!\d)"
            elif alias == "元":
                pattern = rf"(?<!\d){re.escape(number)}(?!\d)\s*{escaped}(?:人民币)?"
            else:
                pattern = (
                    rf"(?<!\d){re.escape(number)}(?!\d)\s*"
                    rf"(?:u\.?\s*s\.?\s*)?{escaped}"
                )
            match = re.search(pattern, source, re.IGNORECASE)
            if match:
                if alias == "元" and re.match(r"人民币", source[match.end() :]):
                    # The compound phrase is not interchangeable with the
                    # bare unit; leave it for human review instead of
                    # emitting a partial replacement.
                    continue
                # Store the whole number+unit span so composite forms such as
                # ``75元人民币`` are replaced atomically.
                result.append((unit, match.start(), match.end()))
                break
    return result
