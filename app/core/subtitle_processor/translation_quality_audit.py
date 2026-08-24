"""Fixed-ID, model-assisted Chinese translation quality audit."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.core.subtitle_processor.stable_artifacts import write_json_artifact


PROMPT_VERSION = "fixed-id-translation-quality-audit-v6"
VERIFICATION_PROMPT_VERSION = "fixed-id-translation-quality-candidate-verification-v2"
ISSUE_CODES = {
    "semantic_loss",
    "meaning_error",
    "number_or_negation_error",
    "english_chinese_mismatch",
    "adjacent_coherence",
    "translationese",
    "chinese_too_long",
    "asr_suspicious",
    "asr_format_error",
}
_ID_RE = re.compile(r"S\d{4}")
_GROUNDED_SOURCE_CODES = {
    "semantic_loss",
    "meaning_error",
    "number_or_negation_error",
    "english_chinese_mismatch",
    "asr_suspicious",
    "asr_format_error",
}
_SUBJECTIVE_VERIFICATION_CODES = {
    "adjacent_coherence",
    "translationese",
}
_OPTIONAL_DISCOURSE_MARKERS = {
    "absolutely",
    "basically",
    "exactly",
    "okay",
    "ok",
    "oh wow",
    "right",
    "yes",
    "yeah",
}
_OPTIONAL_DISCOURSE_WORDS = {
    word
    for marker in _OPTIONAL_DISCOURSE_MARKERS
    for word in marker.split()
}
_OPTIONAL_CHINESE_PRONOUNS = {
    "他",
    "她",
    "它",
    "他们",
    "她们",
    "它们",
    "这个人",
    "这位",
}
_ENGLISH_NUMBER_SCALES = {
    "hundred": Decimal(100),
    "thousand": Decimal(1_000),
    "million": Decimal(1_000_000),
    "billion": Decimal(1_000_000_000),
}


SYSTEM_PROMPT = """You audit Simplified Chinese subtitles for an English podcast.
English and subtitle IDs are frozen. Never rewrite English, IDs, order, or timing.
Report only clear problems a human should fix: semantic loss, wrong meaning,
lost number/negation, English-Chinese mismatch, broken adjacent continuity,
stiff translationese, materially excessive Chinese reading load, or an obvious
ASR error in English such as a nonsensical phrase, malformed proper name,
split number suffix, or broken compound. Do not rewrite merely awkward speech.
Do not report acceptable paraphrases, minor preferences, or punctuation alone.
Do not report omitted backchannels or discourse fillers (for example yeah,
right, exactly, absolutely, oh wow, or basically), optional pronouns whose
referent remains clear, or small tone differences when core meaning is intact.
Use only target IDs from the input and explain reasons in Simplified Chinese.
For adjacent_coherence, subtitle_ids must contain exactly the two adjacent IDs;
one may be an adjacent context ID even when it is not a target ID.
Return one JSON object with exactly these fields:
{"audited_ids":["S0001"],"issues":[{"subtitle_ids":["S0001"],
"code":"semantic_loss","source_quote":"exact English source span",
"claimed_missing_chinese":"中文中明确缺失的最短概念",
"reason":"简短说明","confidence":"high"}]}
Allowed codes: semantic_loss, meaning_error, number_or_negation_error,
english_chinese_mismatch, adjacent_coherence, translationese, chinese_too_long.
Also allowed: asr_suspicious, asr_format_error.
For semantic, mapping, number, negation, or ASR findings, source_quote is
required and must be the shortest exact substring of the supplied English that
proves the issue. Use an empty source_quote for fluency, coherence, and length.
For semantic_loss, claimed_missing_chinese is also required. It must be the
shortest concrete Chinese concept that is absent from the target row and its
immediate adjacent rows. Do not report semantic_loss when that concept is
already carried by an adjacent Chinese row. Omitted Chinese pronouns are not
semantic loss when the adjacent row already names the referent.
Return every target ID once in audited_ids even when issues is empty.
"""

VERIFICATION_SYSTEM_PROMPT = """You verify subjective subtitle audit findings.
English, Chinese, subtitle IDs, order, and timing are frozen. You may only keep
or reject each supplied candidate; never create a new issue or rewrite text.
You receive only Chinese fluency or adjacent-coherence candidates. Grounded
meaning, number, negation, mapping, reading-load, and English ASR findings are
validated separately and are outside your authority.
Keep a candidate only when the cited problem is definite and materially useful
for a human editor. Reject style preferences, acceptable paraphrases, ordinary
Chinese subject/pronoun omission, meaning already carried by an immediate
adjacent row, faithful repetition when adjacent English is also repeated, and
self-contradictory claims whose alleged missing or awkward text is visibly
present. Read each candidate together with the supplied adjacent rows.
Return exactly one decision for every candidate_id and no other IDs:
{"decisions":[{"candidate_id":"C0001","verdict":"keep",
"reason":"简短、可核验的中文理由"}]}
Allowed verdicts are keep and reject.
"""

AUDIT_FOCUSES = (
    (
        "accuracy_asr",
        "Focus on meaning accuracy, omissions, numbers, negation, mapping, and obvious ASR errors.",
    ),
    (
        "fluency_page_load",
        "Focus only on unnatural Chinese expression and actual display-page reading load.",
    ),
    (
        "continuity_mapping",
        "Inspect every adjacent target pair for broken continuation, incomplete Chinese "
        "clauses, content mapped to the wrong row, and meaning that is lost only when the "
        "two rows are read together.",
    ),
)
FOCUS_CODES = {
    "accuracy_asr": {
        "semantic_loss",
        "meaning_error",
        "number_or_negation_error",
        "english_chinese_mismatch",
        "asr_suspicious",
        "asr_format_error",
    },
    "fluency_page_load": {
        "translationese",
        "chinese_too_long",
    },
    "continuity_mapping": {
        "semantic_loss",
        "meaning_error",
        "number_or_negation_error",
        "english_chinese_mismatch",
        "adjacent_coherence",
    },
}


def build_translation_audit_rows(
    final_segments: Sequence[Any],
    display_page_artifact: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    pages_by_parent: dict[str, list[dict[str, Any]]] = {}
    artifact = dict(display_page_artifact or {})
    for parent in artifact.get("parents") or []:
        if not isinstance(parent, Mapping):
            continue
        parent_id = str(parent.get("parent_subtitle_id") or "")
        if not _ID_RE.fullmatch(parent_id):
            continue
        pages_by_parent[parent_id] = [
            {
                "display_page_id": str(page.get("display_page_id") or ""),
                "english": str(page.get("english") or ""),
                "chinese": str(page.get("zh") or ""),
                "duration_ms": max(
                    1,
                    int(page.get("end_ms") or 0)
                    - int(page.get("start_ms") or 0),
                ),
            }
            for page in parent.get("pages") or []
            if isinstance(page, Mapping)
        ]
    rows = []
    for index, segment in enumerate(final_segments, 1):
        subtitle_id = str(
            getattr(segment, "subtitle_id", "") or f"S{index:04d}"
        )
        if not _ID_RE.fullmatch(subtitle_id):
            continue
        rows.append(
            {
                "subtitle_id": subtitle_id,
                "english": str(getattr(segment, "text", "") or "").strip(),
                "chinese": str(
                    getattr(segment, "translated_text", "") or ""
                ).strip(),
                "duration_ms": max(
                    1,
                    int(getattr(segment, "end_time", 0) or 0)
                    - int(getattr(segment, "start_time", 0) or 0),
                ),
                "pages": pages_by_parent.get(subtitle_id, []),
            }
        )
    return rows


def audit_fixed_id_translation_quality(
    rows: Sequence[Mapping[str, Any]],
    completion: Callable[[dict[str, Any]], Any],
    *,
    model: str,
    cache_dir: str | Path | None = None,
    batch_size: int = 40,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Audit every row while keeping model output read-only and ID-bound."""
    ordered = [dict(row) for row in rows if _ID_RE.fullmatch(str(row.get("subtitle_id") or ""))]
    cache_root = Path(cache_dir) if cache_dir is not None else None
    if cache_root is not None:
        cache_root.mkdir(parents=True, exist_ok=True)
    issues: list[dict[str, Any]] = []
    batch_errors: list[dict[str, Any]] = []
    audit_passes_by_id: dict[str, set[str]] = {
        str(row["subtitle_id"]): set() for row in ordered
    }
    effective_batch_size = max(1, int(batch_size))
    total_steps = (
        ((len(ordered) + effective_batch_size - 1) // effective_batch_size)
        * len(AUDIT_FOCUSES)
    )
    completed_steps = 0
    cache_hits = 0

    def emit_progress(*, request_error: bool = False) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "completed": completed_steps,
                "total": total_steps,
                "cache_hits": cache_hits,
                "retries": 0,
                "request_error": request_error,
            }
        )

    emit_progress()
    for offset in range(0, len(ordered), effective_batch_size):
        batch = ordered[offset : offset + effective_batch_size]
        expected_ids = [str(row["subtitle_id"]) for row in batch]
        context_start = max(0, offset - 1)
        context_end = min(len(ordered), offset + len(batch) + 1)
        context_rows = ordered[context_start:context_end]
        context_ids = {str(row["subtitle_id"]) for row in context_rows}
        for focus, focus_instruction in AUDIT_FOCUSES:
            request = {
                "model": str(model),
                "prompt_version": PROMPT_VERSION,
                "audit_focus": focus,
                "system_prompt": SYSTEM_PROMPT + "\n" + focus_instruction,
                "target_ids": expected_ids,
                "rows": context_rows,
            }
            cache_key = hashlib.sha256(
                json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            cache_path = cache_root / f"{cache_key}.json" if cache_root else None
            try:
                if cache_path is not None and cache_path.is_file():
                    response = json.loads(
                        cache_path.read_text(encoding="utf-8-sig")
                    )
                    cache_hits += 1
                else:
                    response = completion(request)
                    if cache_path is not None:
                        write_json_artifact(cache_path, response)
            except Exception as exc:
                batch_errors.append(
                    {
                        "code": "translation_quality_audit_request_failed",
                        "audit_focus": focus,
                        "subtitle_ids": expected_ids,
                        "reason": str(exc)[:500],
                    }
                )
                completed_steps += 1
                emit_progress(request_error=True)
                continue
            completed_steps += 1
            emit_progress()
            response_ids = [
                str(value) for value in (response or {}).get("audited_ids") or []
            ]
            if (
                len(response_ids) != len(set(response_ids))
                or not set(expected_ids).issubset(response_ids)
                or not set(response_ids).issubset(context_ids)
            ):
                batch_errors.append(
                    {
                        "code": "translation_quality_audit_binding_failed",
                        "audit_focus": focus,
                        "subtitle_ids": expected_ids,
                        "returned_audited_ids": response_ids,
                    }
                )
                continue
            for subtitle_id in expected_ids:
                audit_passes_by_id[subtitle_id].add(focus)
            issues.extend(
                _validated_model_issues(
                    response,
                    context_rows,
                    target_ids=set(expected_ids),
                    allowed_codes=FOCUS_CODES[focus],
                )
            )

    deduplicated = []
    seen = set()
    for item in issues:
        key = (
            tuple(item["subtitle_ids"]),
            item["code"],
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    verified_issues, verification_errors = _verify_candidate_issues(
        deduplicated,
        ordered,
        completion,
        model=str(model),
        cache_root=cache_root,
    )
    audited_ids = [
        subtitle_id
        for subtitle_id, completed_focuses in audit_passes_by_id.items()
        if len(completed_focuses) == len(AUDIT_FOCUSES)
    ]
    audited_id_set = set(audited_ids)
    unaudited_ids = [
        str(row["subtitle_id"])
        for row in ordered
        if str(row["subtitle_id"]) not in audited_id_set
    ]
    return {
        "schema_version": 1,
        "prompt_version": PROMPT_VERSION,
        "model": str(model),
        "status": "PASS" if len(audited_ids) == len(ordered) else "PARTIAL",
        "source_subtitle_count": len(ordered),
        "audited_subtitle_count": len(audited_ids),
        "unaudited_subtitle_ids": unaudited_ids,
        "candidate_issue_count": len(deduplicated),
        "issue_count": len(verified_issues),
        "items": verified_issues,
        "batch_errors": batch_errors,
        "verification_errors": verification_errors,
    }


def _verify_candidate_issues(
    issues: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    completion: Callable[[dict[str, Any]], Any],
    *,
    model: str,
    cache_root: Path | None,
    batch_size: int = 20,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not issues:
        return [], []
    ordered_rows = [dict(row) for row in rows]
    row_positions = {
        str(row.get("subtitle_id") or ""): index
        for index, row in enumerate(ordered_rows)
    }
    indexed_candidates = [
        (index, dict(item))
        for index, item in enumerate(issues)
        if str(item.get("code") or "") in _SUBJECTIVE_VERIFICATION_CODES
    ]
    if not indexed_candidates:
        return [dict(item) for item in issues], []
    kept_indexes = set(range(len(issues)))
    errors: list[dict[str, Any]] = []
    for offset in range(0, len(indexed_candidates), max(1, int(batch_size))):
        indexed_batch = indexed_candidates[offset : offset + batch_size]
        raw_batch = [item for _, item in indexed_batch]
        candidate_batch = [
            {"candidate_id": f"C{offset + index:04d}", **item}
            for index, item in enumerate(raw_batch, 1)
        ]
        context_positions: set[int] = set()
        for candidate in candidate_batch:
            for subtitle_id in candidate.get("subtitle_ids") or []:
                position = row_positions.get(str(subtitle_id))
                if position is None:
                    continue
                context_positions.update(
                    range(
                        max(0, position - 1),
                        min(len(ordered_rows), position + 2),
                    )
                )
        context_rows = [ordered_rows[index] for index in sorted(context_positions)]
        expected_ids = [item["candidate_id"] for item in candidate_batch]
        request = {
            "model": model,
            "prompt_version": VERIFICATION_PROMPT_VERSION,
            "audit_focus": "finding_verification",
            "system_prompt": VERIFICATION_SYSTEM_PROMPT,
            "target_ids": expected_ids,
            "rows": context_rows,
            "candidate_issues": candidate_batch,
        }
        cache_key = hashlib.sha256(
            json.dumps(
                request,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        cache_path = cache_root / f"{cache_key}.json" if cache_root else None
        try:
            if cache_path is not None and cache_path.is_file():
                response = json.loads(cache_path.read_text(encoding="utf-8-sig"))
            else:
                response = completion(request)
                if cache_path is not None:
                    write_json_artifact(cache_path, response)
            decisions = list((response or {}).get("decisions") or [])
            returned_ids = [
                str(item.get("candidate_id") or "")
                for item in decisions
                if isinstance(item, Mapping)
            ]
            verdict_by_id = {
                str(item.get("candidate_id") or ""): str(
                    item.get("verdict") or ""
                ).lower()
                for item in decisions
                if isinstance(item, Mapping)
                and str(item.get("verdict") or "").lower() in {"keep", "reject"}
            }
            if (
                len(returned_ids) != len(set(returned_ids))
                or set(returned_ids) != set(expected_ids)
                or set(verdict_by_id) != set(expected_ids)
            ):
                raise ValueError("candidate verification response binding failed")
        except Exception as exc:
            errors.append(
                {
                    "code": "translation_quality_candidate_verification_failed",
                    "candidate_ids": expected_ids,
                    "reason": str(exc)[:500],
                }
            )
            continue
        for (issue_index, _issue), candidate in zip(indexed_batch, candidate_batch):
            if verdict_by_id[candidate["candidate_id"]] == "reject":
                kept_indexes.discard(issue_index)
    return [dict(issues[index]) for index in sorted(kept_indexes)], errors


def _validated_model_issues(
    response: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    target_ids: set[str] | None = None,
    allowed_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows_by_id = {str(row["subtitle_id"]): row for row in rows}
    owned_ids = set(rows_by_id) if target_ids is None else set(target_ids)
    result = []
    for raw in response.get("issues") or []:
        if not isinstance(raw, Mapping):
            continue
        subtitle_ids = sorted(
            {
                str(value)
                for value in raw.get("subtitle_ids") or []
                if str(value) in rows_by_id
            },
            key=lambda value: int(value[1:]),
        )
        code = str(raw.get("code") or "")
        reason = str(raw.get("reason") or "").strip()[:500]
        source_quote = str(raw.get("source_quote") or "").strip()[:300]
        claimed_missing_chinese = str(
            raw.get("claimed_missing_chinese") or ""
        ).strip()[:120]
        source_english = " ".join(
            str(rows_by_id[subtitle_id].get("english") or "")
            for subtitle_id in subtitle_ids
        )
        if (
            not subtitle_ids
            or len(subtitle_ids) > 2
            or not owned_ids.intersection(subtitle_ids)
            or code not in ISSUE_CODES
            or (allowed_codes is not None and code not in allowed_codes)
            or str(raw.get("confidence") or "").lower() != "high"
            or not reason
        ):
            continue
        if code == "adjacent_coherence" and (
            len(subtitle_ids) != 2
            or int(subtitle_ids[1][1:]) - int(subtitle_ids[0][1:]) != 1
        ):
            continue
        if code == "adjacent_coherence" and not _adjacent_issue_has_local_evidence(
            [rows_by_id[subtitle_id] for subtitle_id in subtitle_ids],
            reason,
        ):
            continue
        if code in _GROUNDED_SOURCE_CODES and (
            not source_quote
            or source_quote.casefold() not in source_english.casefold()
        ):
            continue
        if code in {
            "semantic_loss",
            "meaning_error",
            "english_chinese_mismatch",
        } and (
            _is_optional_discourse_marker(source_quote)
            or _reason_cites_only_optional_discourse_markers(reason)
        ):
            continue
        if code == "semantic_loss" and (
            not claimed_missing_chinese
            or _semantic_loss_claim_is_already_present(
                claimed_missing_chinese,
                subtitle_ids,
                rows_by_id,
            )
        ):
            continue
        if code == "number_or_negation_error" and (
            _number_issue_is_locally_disproved(
                source_quote,
                reason,
                subtitle_ids,
                rows_by_id,
            )
        ):
            continue
        if code == "chinese_too_long" and not any(
            _row_has_excessive_page_load(rows_by_id[subtitle_id])
            for subtitle_id in subtitle_ids
        ):
            continue
        if code in {"meaning_error", "english_chinese_mismatch"} and all(
            _is_valid_short_response(rows_by_id[subtitle_id])
            for subtitle_id in subtitle_ids
        ):
            continue
        result.append(
            {
                "code": code,
                "title": _issue_title(code),
                "reason": reason,
                "confidence": "high",
                "subtitle_ids": subtitle_ids,
                "source_quote": source_quote,
                "claimed_missing_chinese": claimed_missing_chinese,
                "recommended_action": "manual_review",
            }
        )
    return result


def _semantic_loss_claim_is_already_present(
    claimed_missing_chinese: str,
    subtitle_ids: Sequence[str],
    rows_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    claim = re.sub(r"[^\w\u4e00-\u9fff]+", "", claimed_missing_chinese).casefold()
    if not claim or claim in _OPTIONAL_CHINESE_PRONOUNS:
        return True
    owned_indexes = [int(subtitle_id[1:]) for subtitle_id in subtitle_ids]
    neighborhood_ids = {
        f"S{index:04d}"
        for owned_index in owned_indexes
        for index in (owned_index - 1, owned_index, owned_index + 1)
        if index > 0
    }
    neighborhood = "".join(
        str(row.get("chinese") or "")
        for subtitle_id, row in rows_by_id.items()
        if subtitle_id in neighborhood_ids
    )
    normalized_neighborhood = re.sub(
        r"[^\w\u4e00-\u9fff]+",
        "",
        neighborhood,
    ).casefold()
    return claim in normalized_neighborhood


def _number_issue_is_locally_disproved(
    source_quote: str,
    reason: str,
    subtitle_ids: Sequence[str],
    rows_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Reject only numeric claims contradicted by exact local evidence."""
    if re.search(r"否定|相反|\b(?:not|without|cannot|never)\b", reason, re.I):
        return False
    numeric_reason = bool(
        re.search(r"数字|数值|金额|货币|单位|million|billion|美元|人民币|元", reason, re.I)
    )
    if not numeric_reason:
        return False
    anchors = _english_number_anchor_variants(source_quote)
    source_currency = _source_currency_unit(source_quote)
    if not anchors:
        return bool(
            not source_currency
            and re.search(r"缺少|遗漏|未.*(?:标明|体现)", reason)
            and re.search(r"货币|美元|人民币|元|dollar|yuan", reason, re.I)
        )
    owned_indexes = [int(subtitle_id[1:]) for subtitle_id in subtitle_ids]
    neighborhood_ids = {
        f"S{index:04d}"
        for owned_index in owned_indexes
        for index in (owned_index - 1, owned_index, owned_index + 1)
        if index > 0
    }
    chinese = "".join(
        str(row.get("chinese") or "")
        for subtitle_id, row in rows_by_id.items()
        if subtitle_id in neighborhood_ids
    )
    compact_chinese = re.sub(r"[,，\s]", "", chinese)
    if not all(any(variant in compact_chinese for variant in variants) for variants in anchors):
        return False
    if not source_currency:
        return bool(
            re.search(r"缺少|遗漏|未.*(?:标明|体现)", reason)
            and re.search(r"货币|美元|人民币|元|dollar|yuan", reason, re.I)
        )
    return source_currency in _chinese_currency_units(chinese)


def _english_number_anchor_variants(source_quote: str) -> list[set[str]]:
    anchors: list[set[str]] = []
    for match in re.finditer(
        r"(?<![A-Za-z0-9])(?P<number>\d+(?:[.,]\d+)?)"
        r"(?:\s+(?P<scale>hundred|thousand|million|billion))?\b",
        source_quote or "",
        re.I,
    ):
        raw_number = match.group("number").replace(",", "")
        scale_name = str(match.group("scale") or "").lower()
        try:
            value = Decimal(raw_number) * _ENGLISH_NUMBER_SCALES.get(
                scale_name,
                Decimal(1),
            )
        except InvalidOperation:
            continue
        expanded = format(value, "f").rstrip("0").rstrip(".")
        if value == value.to_integral_value():
            expanded = str(int(value))
        variants = {expanded, raw_number}
        if value >= Decimal(100_000_000):
            yi = value / Decimal(100_000_000)
            variants.add(f"{format(yi, 'f').rstrip('0').rstrip('.')}亿")
        if value >= Decimal(10_000):
            wan = value / Decimal(10_000)
            variants.add(f"{format(wan, 'f').rstrip('0').rstrip('.')}万")
        anchors.append({variant for variant in variants if variant})
    return anchors


def _source_currency_unit(text: str) -> str:
    source = str(text or "")
    if re.search(r"(?:\$|\bdollars?\b|\bu\.?\s*s\.?\s*d\b)", source, re.I):
        return "usd"
    if re.search(r"\b(?:yuan|renminbi|rmb)\b", source, re.I):
        return "cny"
    return ""


def _chinese_currency_units(text: str) -> set[str]:
    result: set[str] = set()
    if re.search(r"美元|美金|\$", text or ""):
        result.add("usd")
    if re.search(r"人民币|(?<!美)元", text or ""):
        result.add("cny")
    return result


def _is_optional_discourse_marker(source_quote: str) -> bool:
    normalized = re.sub(r"[^a-z']+", " ", source_quote.casefold()).strip()
    words = normalized.split()
    return bool(
        normalized in _OPTIONAL_DISCOURSE_MARKERS
        or words and set(words).issubset(_OPTIONAL_DISCOURSE_WORDS)
    )


def _reason_cites_only_optional_discourse_markers(reason: str) -> bool:
    cited_words = re.findall(r"[a-z']+", reason.casefold())
    return bool(cited_words) and set(cited_words).issubset(_OPTIONAL_DISCOURSE_WORDS)


def _is_valid_short_response(row: Mapping[str, Any]) -> bool:
    english = re.sub(r"[^a-z']+", " ", str(row.get("english") or "").casefold()).strip()
    chinese = re.sub(r"[\s，。！？、,.!?]+", "", str(row.get("chinese") or ""))
    valid = {
        "yes": {"对", "是", "是的", "没错"},
        "no": {"不", "不是", "没有", "不对"},
        "right": {"对", "没错", "是的"},
        "exactly": {"对", "没错", "正是", "正是如此"},
        "okay": {"好", "好的", "行", "可以"},
        "ok": {"好", "好的", "行", "可以"},
    }
    if english in valid and chinese in valid[english]:
        return True
    english_words = english.split()
    return bool(
        english_words
        and set(english_words).issubset(_OPTIONAL_DISCOURSE_WORDS)
        and chinese in {"对", "是", "是的", "没错", "正是", "确实", "确实如此"}
    )


def _adjacent_issue_has_local_evidence(
    rows: Sequence[Mapping[str, Any]],
    reason: str,
) -> bool:
    """Require a visible cross-row defect before surfacing model preference."""
    if len(rows) != 2:
        return False
    left_english = str(rows[0].get("english") or "").strip().casefold()
    right_english = str(rows[1].get("english") or "").strip().casefold()
    left_chinese = re.sub(r"\s+", "", str(rows[0].get("chinese") or ""))
    right_chinese = re.sub(r"\s+", "", str(rows[1].get("chinese") or ""))
    if not left_chinese or not right_chinese:
        return True
    if re.search(r"(?:在于|因为|由于|如果|虽然|但是|而|但|和|与|的|会|将|是|为|把|被)[，,。.!?！？]*$", right_chinese):
        return True
    if re.search(r"[，,](?:终于|因此|所以|但是|但|而)?[，,。.!?！？]*$", right_chinese):
        return True
    inverted_subordinate = bool(
        re.match(r"^(?:when|if|because|although|while|as)\b", right_english)
        and re.match(r"^(?:当|如果|因为|虽然|尽管|随着|在)", right_chinese)
        and re.search(r"(?:时|后|下)[。.!?！？]*$", right_chinese)
        and not re.search(r"[。.!?！？]$", left_chinese)
    )
    if inverted_subordinate:
        return True
    return bool(re.search(r"错位|映射|对应错误|前后颠倒|语序倒置", reason))


def _row_has_excessive_page_load(row: Mapping[str, Any]) -> bool:
    pages = [page for page in row.get("pages") or [] if isinstance(page, Mapping)]
    if not pages:
        pages = [
            {
                "chinese": str(row.get("chinese") or ""),
                "duration_ms": max(1, int(row.get("duration_ms") or 0)),
            }
        ]
    for page in pages:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", str(page.get("chinese") or "")))
        duration_ms = max(1, int(page.get("duration_ms") or 0))
        if chinese_chars > 28 or chinese_chars / (duration_ms / 1000.0) > 9.0:
            return True
    return False


def _issue_title(code: str) -> str:
    return {
        "semantic_loss": "中文信息遗漏",
        "meaning_error": "中文含义错误",
        "number_or_negation_error": "数字或否定关系错误",
        "english_chinese_mismatch": "中英文不对应",
        "adjacent_coherence": "相邻中文不连贯",
        "translationese": "中文表达不通顺",
        "chinese_too_long": "中文字幕负载过高",
        "asr_suspicious": "英文转录疑似有误",
        "asr_format_error": "英文转录格式异常",
    }[code]
