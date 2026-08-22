"""Build and load the ID-driven review ledger for the manual subtitle editor.

The stable pipeline owns the ledger.  Every actionable item must be backed by
frozen subtitle IDs and existing audit evidence; compatibility checks for old
runs may derive deterministic text-format findings without changing subtitles.
"""

from __future__ import annotations

import json
import hashlib
import re
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from app.core.subtitle_processor.user_facing_issue_text import (
    issue_codes_text,
    user_facing_issue_reason,
)
from app.core.subtitle_processor.review_evidence_identity import (
    build_review_source_identity,
    load_bound_semantic_review_queue,
)
from app.core.subtitle_processor.stable_artifacts import write_json_artifact


_SUBTITLE_ID_RE = re.compile(r"S\d{4}")
_TERMINAL_SENTENCE_RE = re.compile(r"[.!?][\"'”’\)\]]*$")
_REVIEW_LEDGER_NAME = "editor-review-ledger.json"
_REVIEW_LEDGER_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class SubtitleReviewMark:
    """One high-confidence review marker for a frozen subtitle ID."""

    subtitle_id: str
    severity: str
    category: str
    target: str
    code: str
    reason: str
    task_id: str = ""


def load_subtitle_review_marks(
    artifact_dir: str | Path,
) -> Dict[str, List[SubtitleReviewMark]]:
    """Load the frozen ledger, or derive the same marks for a legacy run."""
    directory = Path(artifact_dir)
    ledger_marks = _review_marks_from_ledger(directory)
    if ledger_marks is not None:
        return ledger_marks
    return _group_marks(_collect_subtitle_review_marks(directory))


def write_subtitle_review_ledger(artifact_dir: str | Path) -> Dict[str, Any]:
    """Materialize one deterministic review queue beside stable artifacts."""
    directory = Path(artifact_dir)
    grouped = _group_marks(_collect_subtitle_review_marks(directory))
    task_items: Dict[str, Dict[str, Any]] = {}
    for marks in grouped.values():
        for mark in marks:
            task_id = mark.task_id or _review_task_id(
                [mark.subtitle_id],
                severity=mark.severity,
                category=mark.category,
                target=mark.target,
                code=mark.code,
                reason=mark.reason,
            )
            item = task_items.setdefault(
                task_id,
                {
                    "task_id": task_id,
                    "severity": mark.severity,
                    "category": mark.category,
                    "target": mark.target,
                    "code": mark.code,
                    "reason": mark.reason,
                    "subtitle_ids": [],
                    "recommended_action": "manual_review",
                },
            )
            item["subtitle_ids"].append(mark.subtitle_id)

    items = []
    for item in task_items.values():
        item["subtitle_ids"] = _normalise_ids(item["subtitle_ids"])
        items.append(item)
    items.sort(
        key=lambda item: (
            0 if item["severity"] == "BLOCKER" else 1,
            int(item["subtitle_ids"][0][1:]) if item["subtitle_ids"] else 10**9,
            item["task_id"],
        )
    )
    word_ledger = _read_json(directory / "word-ledger.json", {})
    subtitle_spans = _as_list(
        _read_json(directory / "subtitle-spans.json", [])
    )
    source_identity = build_review_source_identity(
        word_ledger if isinstance(word_ledger, Mapping) else {},
        [span for span in subtitle_spans if isinstance(span, Mapping)],
    )
    payload: Dict[str, Any] = {
        "schema_version": _REVIEW_LEDGER_SCHEMA_VERSION,
        "source_word_ledger_hash": source_identity["word_ledger_hash"],
        "source_frozen_span_hash": source_identity["frozen_span_hash"],
        "source_subtitle_count": source_identity["subtitle_count"],
        "summary": {
            "task_count": len(items),
            "blocker_count": sum(item["severity"] == "BLOCKER" for item in items),
            "review_count": sum(item["severity"] == "REVIEW" for item in items),
            "subtitle_count": len(
                {subtitle_id for item in items for subtitle_id in item["subtitle_ids"]}
            ),
        },
        "items": items,
    }
    payload["artifact_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    write_json_artifact(directory / _REVIEW_LEDGER_NAME, payload)
    return payload


def _collect_subtitle_review_marks(directory: Path) -> List[SubtitleReviewMark]:
    validation = _read_json(directory / "validation-report.json", {})
    model_audit = _read_json(directory / "translation-quality-audit.json", {})
    complete_model_audit = bool(
        isinstance(model_audit, Mapping)
        and model_audit.get("status") == "PASS"
        and int(model_audit.get("source_subtitle_count") or 0) > 0
        and int(model_audit.get("audited_subtitle_count") or 0)
        == int(model_audit.get("source_subtitle_count") or 0)
    )
    structure_errors = _read_json(
        directory / "translation-structure-errors.json",
        [],
        strict=True,
    )
    marks: List[SubtitleReviewMark] = []

    marks.extend(_structure_error_marks(structure_errors))

    for group in _as_list(validation.get("errors") if isinstance(validation, Mapping) else []):
        code = str(group.get("code") or "validation_error")
        for entry in _group_entries(group):
            _append_marks(
                marks,
                _subtitle_ids(entry),
                severity="BLOCKER",
                category="validation",
                target="both",
                code=code,
                reason=_reason(entry, group),
            )

    marks.extend(_final_timeline_fallback_marks(directory))
    boundary_marks, has_boundary_audit = _english_boundary_audit_marks(directory)
    marks.extend(boundary_marks)
    if not has_boundary_audit:
        marks.extend(_high_precision_english_cut_marks(directory))
    marks.extend(_high_value_validation_warning_marks(validation))
    if not complete_model_audit:
        marks.extend(_high_confidence_chinese_marks(validation))
        marks.extend(_allocation_unresolved_marks(directory))
    marks.extend(_visual_page_review_marks(directory))
    marks.extend(_display_page_chinese_review_marks(directory))
    marks.extend(_model_translation_quality_marks(directory))
    if not complete_model_audit:
        marks.extend(_semantic_review_queue_marks(directory))
    marks.extend(_article_asr_correction_review_marks(directory))
    marks.extend(_deterministic_text_review_marks(directory))

    return marks


def syntax_review_parser_available() -> bool:
    """Return whether the local spaCy dependency parser is available."""
    return _load_syntax_nlp() is not None


def review_marks_require_syntax_parser(artifact_dir: str | Path) -> bool:
    """Legacy runs need parser fallback only when no boundary audit exists."""
    payload = _read_json(Path(artifact_dir) / "english-boundary-audit.json", {})
    return not (
        isinstance(payload, Mapping)
        and isinstance(payload.get("records"), list)
    )


def review_marks_to_payload(
    marks_by_subtitle_id: Mapping[str, Iterable[SubtitleReviewMark]],
) -> Dict[str, List[Dict[str, str]]]:
    """Serialize editor markers for an isolated local worker process."""
    return {
        str(subtitle_id): [asdict(mark) for mark in marks]
        for subtitle_id, marks in marks_by_subtitle_id.items()
    }


def review_marks_from_payload(payload: Any) -> Dict[str, List[SubtitleReviewMark]]:
    """Parse a validated marker payload produced by the local worker."""
    if not isinstance(payload, Mapping):
        raise ValueError("复查标记返回格式无效。")
    restored: Dict[str, List[SubtitleReviewMark]] = {}
    for subtitle_id, items in payload.items():
        normalized_id = str(subtitle_id)
        if not _SUBTITLE_ID_RE.fullmatch(normalized_id) or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            try:
                mark = SubtitleReviewMark(
                    subtitle_id=normalized_id,
                    severity=str(item["severity"]),
                    category=str(item["category"]),
                    target=str(item["target"]),
                    code=str(item["code"]),
                    reason=str(item["reason"]),
                    task_id=str(item.get("task_id") or ""),
                )
            except KeyError:
                continue
            restored.setdefault(normalized_id, []).append(mark)
    return _group_marks(mark for marks in restored.values() for mark in marks)


def _review_marks_from_ledger(
    directory: Path,
) -> Dict[str, List[SubtitleReviewMark]] | None:
    payload = _read_json(directory / _REVIEW_LEDGER_NAME, None)
    if not isinstance(payload, Mapping):
        return None
    if int(payload.get("schema_version") or 0) != _REVIEW_LEDGER_SCHEMA_VERSION:
        return None
    current_ledger = _read_json(directory / "word-ledger.json", {})
    current_spans = _as_list(
        _read_json(directory / "subtitle-spans.json", [])
    )
    current_identity = build_review_source_identity(
        current_ledger if isinstance(current_ledger, Mapping) else {},
        [span for span in current_spans if isinstance(span, Mapping)],
    )
    if (
        str(payload.get("source_word_ledger_hash") or "")
        != current_identity["word_ledger_hash"]
        or str(payload.get("source_frozen_span_hash") or "")
        != current_identity["frozen_span_hash"]
        or payload.get("source_subtitle_count")
        != current_identity["subtitle_count"]
    ):
        return None

    marks: List[SubtitleReviewMark] = []
    for item in _as_list(payload.get("items")):
        if not isinstance(item, Mapping):
            continue
        subtitle_ids = _normalise_ids(_as_list(item.get("subtitle_ids")))
        if not subtitle_ids:
            continue
        task_id = str(item.get("task_id") or "")
        for subtitle_id in subtitle_ids:
            marks.append(
                SubtitleReviewMark(
                    subtitle_id=subtitle_id,
                    severity=str(item.get("severity") or "REVIEW"),
                    category=str(item.get("category") or "validation"),
                    target=str(item.get("target") or "both"),
                    code=str(item.get("code") or "review_required"),
                    reason=str(item.get("reason") or "需要人工复核"),
                    task_id=task_id,
                )
            )
    return _group_marks(marks)


def _read_json(path: Path, default: Any, *, strict: bool = False) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise ValueError(f"无法读取复查证据：{path}") from exc
        return default


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _group_entries(group: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    items = group.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, Mapping)]
    return [group]


def _subtitle_ids(payload: Mapping[str, Any]) -> List[str]:
    display_page_id = str(payload.get("display_page_id") or "")
    values: List[Any] = [
        payload.get("subtitle_id"),
        payload.get("parent_subtitle_id"),
        display_page_id.partition(".")[0] if display_page_id else "",
    ]
    for key in (
        "subtitle_ids",
        "expected_subtitle_ids",
        "returned_subtitle_ids",
        "mapped_subtitle_ids",
    ):
        values.extend(_as_list(payload.get(key)))
    return _normalise_ids(values)


def _normalise_ids(values: Iterable[Any]) -> List[str]:
    return sorted(
        {str(value) for value in values if _SUBTITLE_ID_RE.fullmatch(str(value or ""))},
        key=lambda subtitle_id: int(subtitle_id[1:]),
    )


def _reason(payload: Mapping[str, Any], group: Mapping[str, Any] | None) -> str:
    code = str(payload.get("code") or (group or {}).get("code") or "")
    reason = str(payload.get("reason") or "").strip()
    if reason:
        return user_facing_issue_reason(reason, code=code)
    codes = [str(code) for code in _as_list(payload.get("rule_codes"))]
    if codes:
        return issue_codes_text(codes)
    message = str((group or {}).get("message") or "需要人工复核")
    return user_facing_issue_reason(message, code=code)


def _append_marks(
    marks: List[SubtitleReviewMark],
    subtitle_ids: Iterable[str],
    *,
    severity: str,
    category: str,
    target: str,
    code: str,
    reason: str,
) -> None:
    normalized_ids = _normalise_ids(subtitle_ids)
    task_id = _review_task_id(
        normalized_ids,
        severity=severity,
        category=category,
        target=target,
        code=code,
        reason=reason,
    )
    for subtitle_id in normalized_ids:
        marks.append(
            SubtitleReviewMark(
                subtitle_id=subtitle_id,
                severity=severity,
                category=category,
                target=target,
                code=code,
                reason=reason or "需要人工复核",
                task_id=task_id,
            )
        )


def _review_task_id(
    subtitle_ids: Iterable[str],
    *,
    severity: str,
    category: str,
    target: str,
    code: str,
    reason: str,
) -> str:
    identity_code = str(code)
    identity_reason = str(reason)
    if category in {
        "chinese_allocation",
        "chinese_length",
        "chinese_fluency",
        "chinese_coherence",
        "asr_correction",
    }:
        identity_code = f"fixed_id_{category}_review"
        identity_reason = ""
    identity = "\n".join(
        [
            *_normalise_ids(subtitle_ids),
            str(severity),
            str(category),
            str(target),
            identity_code,
            identity_reason,
        ]
    )
    return "R" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def _structure_error_mark_fields(
    group_code: str,
    entry: Mapping[str, Any],
) -> tuple[str, str, str]:
    """Map one structure failure to the editor cell that actually owns it."""
    item_code = str(entry.get("code") or entry.get("reason") or "").strip()
    if item_code.startswith("page_translation_"):
        return "chinese_allocation", "chinese", item_code
    if group_code == "display_page_fixed_font_layout_invalid":
        return "chinese_length", "chinese", group_code
    if group_code in {
        "display_page_translation_invalid",
        "display_page_translation_request_failed",
    }:
        return "chinese_allocation", "chinese", group_code
    if group_code.startswith("display_page_"):
        return "visual_page", "english", group_code
    return "structure", "both", group_code


def _structure_error_marks(structure_errors: Any) -> List[SubtitleReviewMark]:
    marks: List[SubtitleReviewMark] = []
    for error in _as_list(structure_errors):
        if not isinstance(error, Mapping):
            continue
        group_code = str(error.get("code") or "translation_structure_error")
        entries = [
            entry
            for entry in _as_list(error.get("items"))
            if isinstance(entry, Mapping) and _subtitle_ids(entry)
        ]
        handled_ids: set[str] = set()
        for entry in entries:
            subtitle_ids = _subtitle_ids(entry)
            handled_ids.update(subtitle_ids)
            category, target, code = _structure_error_mark_fields(group_code, entry)
            _append_marks(
                marks,
                subtitle_ids,
                severity="BLOCKER",
                category=category,
                target=target,
                code=code,
                reason=_reason(entry, error),
            )

        remaining_ids = [
            subtitle_id
            for subtitle_id in _subtitle_ids(error)
            if subtitle_id not in handled_ids
        ]
        if entries and not remaining_ids:
            continue
        category, target, code = _structure_error_mark_fields(group_code, error)
        _append_marks(
            marks,
            remaining_ids if entries else _subtitle_ids(error),
            severity="BLOCKER",
            category=category,
            target=target,
            code=code,
            reason=(
                user_facing_issue_reason(
                    str(error.get("message") or ""),
                    code=code,
                )
                if group_code.startswith("display_page_")
                else "中文返回结构与固定字幕编号不一致。"
            ),
        )
    return marks


def _final_timeline_fallback_marks(directory: Path) -> List[SubtitleReviewMark]:
    """Mark only cues whose first or last word retained fallback timing.

    This is provenance from the final time artifact, not a heuristic about
    subtitle duration.  It therefore remains useful in the editor without
    turning routine short or fast cues into noisy review markers.
    """
    timeline = _read_json(directory / "final-cue-timeline.json", {})
    ledger_payload = _read_json(directory / "word-ledger.json", {})
    ledger = ledger_payload.get("words") if isinstance(ledger_payload, Mapping) else []
    records = timeline.get("records") if isinstance(timeline, Mapping) else []
    if not isinstance(records, list) or not isinstance(ledger, list):
        return []

    marks: List[SubtitleReviewMark] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        subtitle_id = str(record.get("subtitle_id") or "")
        try:
            word_start = int(record.get("word_start"))
            word_end = int(record.get("word_end"))
            edge_words = (ledger[word_start], ledger[word_end])
        except (IndexError, TypeError, ValueError):
            continue
        if not _SUBTITLE_ID_RE.fullmatch(subtitle_id):
            continue
        fallback_edge_words = [
            word
            for word in edge_words
            if isinstance(word, Mapping)
            and str(word.get("alignment_source") or "").startswith(
                "stable-ts-fallback"
            )
        ]
        if not any(
            int(word.get("end_ms") or 0) - int(word.get("start_ms") or 0)
            <= 40
            or int(word.get("end_ms") or 0) - int(word.get("start_ms") or 0)
            > 1500
            for word in fallback_edge_words
        ):
            continue
        _append_marks(
            marks,
            [subtitle_id],
            severity="REVIEW",
            category="timeline_alignment",
            target="both",
            code="timeline_alignment_fallback",
            reason="最终时间轴含 stable-ts 回退词；建议试听本条字幕的首尾。",
        )
    return marks


def _english_boundary_audit_marks(
    directory: Path,
) -> tuple[List[SubtitleReviewMark], bool]:
    payload = _read_json(directory / "english-boundary-audit.json", {})
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(records, list):
        return [], False
    marks: List[SubtitleReviewMark] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if str(record.get("scope") or "parent_cue") != "parent_cue":
            continue
        classification = str(record.get("classification") or "")
        if classification not in {"hard", "review"}:
            continue
        rule_codes = {
            str(value) for value in _as_list(record.get("rule_codes"))
        }
        rule_codes.update(
            value.strip()
            for value in str(record.get("reason") or "").split(";")
            if value.strip()
        )
        if (
            rule_codes == {"right_orphaned_finite_predicate"}
            and _boundary_has_two_complete_sentences(record)
        ):
            continue
        right_id = str(record.get("right_subtitle_id") or "")
        left_id = str(record.get("left_subtitle_id") or "")
        target_id = right_id if _SUBTITLE_ID_RE.fullmatch(right_id) else left_id
        if not _SUBTITLE_ID_RE.fullmatch(target_id):
            continue
        boundary = str(record.get("boundary") or "").strip()
        reason = str(record.get("reason") or "英文边界需要人工复核").strip()
        if boundary:
            reason = f"{reason}：{boundary}"
        _append_marks(
            marks,
            [target_id],
            severity="BLOCKER" if classification == "hard" else "REVIEW",
            category="english_cut",
            target="english",
            code="english_boundary_audit",
            reason=reason,
        )
    return marks, True


def _boundary_has_two_complete_sentences(record: Mapping[str, Any]) -> bool:
    """Reject stale orphan-predicate evidence between standalone sentences."""
    left = str(
        record.get("previous_english") or record.get("previous") or ""
    ).strip()
    right = str(
        record.get("current_english") or record.get("current") or ""
    ).strip()
    terminal = re.compile(r"[.!?][\"')\]]*$")
    return bool(terminal.search(left) and terminal.search(right))


def _high_value_validation_warning_marks(validation: Any) -> List[SubtitleReviewMark]:
    if not isinstance(validation, Mapping):
        return []
    marks: List[SubtitleReviewMark] = []
    for group in _as_list(validation.get("warnings")):
        if not isinstance(group, Mapping):
            continue
        code = str(group.get("code") or "")
        for entry in _group_entries(group):
            subtitle_ids = _subtitle_ids(entry)
            if not subtitle_ids:
                continue
            if code == "reading_speed_warning" and entry.get("zh_chars"):
                _append_marks(
                    marks,
                    subtitle_ids,
                    severity="REVIEW",
                    category="chinese_length",
                    target="chinese",
                    code="chinese_reading_speed_warning",
                    reason=str(entry.get("reason") or "中文字幕阅读速度偏快。"),
                )
            elif code == "translationese":
                _append_marks(
                    marks,
                    subtitle_ids,
                    severity="REVIEW",
                    category="chinese_fluency",
                    target="chinese",
                    code="translation_fluency_review",
                    reason=str(entry.get("reason") or "中文表达疑似不够自然。"),
                )
            elif code == "duplicate_chinese":
                _append_marks(
                    marks,
                    subtitle_ids,
                    severity="REVIEW",
                    category="chinese_coherence",
                    target="chinese",
                    code="adjacent_chinese_duplicate_review",
                    reason=str(
                        entry.get("reason")
                        or "相邻中文字幕高度相似，可能重复或串条。"
                    ),
                )
            elif code == "asr_suspicious" and str(
                entry.get("confidence") or ""
            ).lower() == "high":
                _append_marks(
                    marks,
                    subtitle_ids,
                    severity="REVIEW",
                    category="asr_correction",
                    target="english",
                    code=str(entry.get("rule_code") or "asr_suspicious"),
                    reason=str(entry.get("reason") or "英文转录疑似异常，请回听。"),
                )
            elif (
                code == "subtitle_duration_short_warning"
                and not bool(entry.get("simple_response"))
                and int(entry.get("text_load") or 0) >= 8
            ):
                _append_marks(
                    marks,
                    subtitle_ids,
                    severity="REVIEW",
                    category="timeline_alignment",
                    target="both",
                    code="high_load_short_duration",
                    reason=str(entry.get("reason") or "字幕负载较高但显示时间偏短。"),
                )
    return marks


def _high_confidence_chinese_marks(validation: Any) -> List[SubtitleReviewMark]:
    if not isinstance(validation, Mapping):
        return []
    marks: List[SubtitleReviewMark] = []
    for group in _as_list(validation.get("warnings")):
        if not isinstance(group, Mapping) or group.get("code") != "chinese_semantic_group_warning":
            continue
        for entry in _group_entries(group):
            if not bool(entry.get("mapping_valid")):
                continue
            subtitle_ids = _subtitle_ids(entry)
            if str(entry.get("confidence") or "").lower() != "high" or not subtitle_ids:
                continue
            _append_marks(
                marks,
                subtitle_ids,
                severity="REVIEW",
                category="chinese_allocation",
                target="chinese",
                code="high_confidence_chinese_semantic_issue",
                reason=_reason(entry, group),
            )
    return marks


def _allocation_unresolved_marks(directory: Path) -> List[SubtitleReviewMark]:
    unresolved = _read_json(directory / "allocation-unresolved.json", [])
    high_value_codes = {
        "entity_allocation_mismatch",
        "missing_predicate",
        "negation_allocation_mismatch",
        "number_allocation_mismatch",
        "semantic_loss",
        "unnatural_chinese_fragment",
        "dangling_preposition",
        "english_word_order",
        "modifier_head_split",
        "punctuation_discontinuity",
    }
    marks: List[SubtitleReviewMark] = []
    for entry in _as_list(unresolved):
        if not isinstance(entry, Mapping):
            continue
        issue_codes = {str(code) for code in _as_list(entry.get("issue_codes"))}
        allocation = entry.get("allocation")
        subtitle_ids = _subtitle_ids(entry)
        if isinstance(allocation, Mapping):
            subtitle_ids = _normalise_ids([*subtitle_ids, *allocation.keys()])
        if not subtitle_ids or not issue_codes.intersection(high_value_codes):
            continue
        _append_marks(
            marks,
            subtitle_ids,
            severity="REVIEW",
            category="chinese_allocation",
            target="chinese",
            code="allocation_unresolved",
            reason=user_facing_issue_reason(
                str(entry.get("reason") or issue_codes_text(sorted(issue_codes))),
                code="allocation_unresolved",
            ),
        )
    return marks


def _visual_page_review_marks(directory: Path) -> List[SubtitleReviewMark]:
    artifact = _read_json(directory / "display-page-translations.json", {})
    plans = artifact.get("render_plans") if isinstance(artifact, Mapping) else None
    if not isinstance(plans, list):
        return []
    high_value_codes = {
        "compound_noun_split",
        "modifier_head_split",
        "object_attached_modifier_split",
        "post_noun_participial_modifier_split",
        "relative_clause_subject_verb_split",
        "subject_finite_verb_split",
        "subject_predicate_split",
        "verb_complement_split",
        "verb_preposition_complement_split",
        "zero_relative_clause_split",
    }
    relative_starts = {"that", "which", "who", "whom", "whose"}
    marks: List[SubtitleReviewMark] = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            continue
        subtitle_id = str(plan.get("parent_subtitle_id") or "")
        pages = plan.get("pages")
        if not _SUBTITLE_ID_RE.fullmatch(subtitle_id) or not isinstance(pages, list):
            continue
        for page_index, page in enumerate(pages[1:], 1):
            if not isinstance(page, Mapping):
                continue
            decision = page.get("boundary_before")
            if not isinstance(decision, Mapping) or decision.get("classification") != "review":
                continue
            issue_codes = {str(code) for code in _as_list(decision.get("issue_codes"))}
            current_words = str(page.get("english") or "").split()
            previous_words = str(pages[page_index - 1].get("english") or "").split()
            starts_relative = bool(
                current_words
                and re.sub(r"[^A-Za-z']", "", current_words[0]).lower() in relative_starts
                and "dependency_phrase_entrance_split" in issue_codes
            )
            high_confidence = bool(
                issue_codes.intersection(high_value_codes) or starts_relative
            )
            boundary = " | ".join(
                [
                    previous_words[-1] if previous_words else "",
                    current_words[0] if current_words else "",
                ]
            ).strip(" |")
            _append_marks(
                marks,
                [subtitle_id],
                severity="REVIEW",
                category="visual_page",
                target="both",
                code=(
                    "high_confidence_visual_page_boundary"
                    if high_confidence
                    else "visual_page_boundary_review"
                ),
                reason=(
                    f"视觉分页可能切开紧密语法单元：{boundary}。"
                    if high_confidence
                    else f"该分页边界需要人工确认：{boundary}。"
                ),
            )
            break
    return marks


def _display_page_chinese_review_marks(directory: Path) -> List[SubtitleReviewMark]:
    artifact = _read_json(directory / "display-page-translations.json", {})
    if not isinstance(artifact, Mapping):
        return []
    marks: List[SubtitleReviewMark] = []
    high_value_codes = {
        "semantic_loss",
        "missing_predicate",
        "dangling_preposition",
        "modifier_head_split",
        "punctuation_discontinuity",
        "english_word_order",
        "entity_allocation_mismatch",
        "number_allocation_mismatch",
        "negation_allocation_mismatch",
    }
    for item in _as_list(artifact.get("reviews")):
        if not isinstance(item, Mapping):
            continue
        issue_codes = {str(code) for code in _as_list(item.get("issue_codes"))}
        if not issue_codes.intersection(high_value_codes):
            continue
        parent_id = str(item.get("parent_subtitle_id") or "")
        _append_marks(
            marks,
            [parent_id],
            severity="REVIEW",
            category="chinese_coherence",
            target="chinese",
            code="display_page_chinese_continuity_review",
            reason="逐页中文可能存在不连贯或中英对应问题："
            + issue_codes_text(sorted(issue_codes)),
        )

    run_manifest = _read_json(directory / "run-manifest.json", {})
    configured_limit = int(
        (run_manifest.get("max_cjk_chars") if isinstance(run_manifest, Mapping) else 0)
        or 24
    )
    for parent in _as_list(artifact.get("parents")):
        if not isinstance(parent, Mapping):
            continue
        parent_id = str(parent.get("parent_subtitle_id") or "")
        for page in _as_list(parent.get("pages")):
            if not isinstance(page, Mapping):
                continue
            chinese = str(page.get("zh") or "")
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", chinese))
            duration_ms = max(
                1,
                int(page.get("end_ms") or 0) - int(page.get("start_ms") or 0),
            )
            cps = chinese_chars / (duration_ms / 1000.0)
            if chinese_chars <= configured_limit and cps <= 9.0:
                continue
            page_id = str(page.get("display_page_id") or "")
            reasons = []
            if chinese_chars > configured_limit:
                reasons.append(f"{chinese_chars} 个汉字，超过当前建议值 {configured_limit}")
            if cps > 9.0:
                reasons.append(f"阅读速度 {cps:.2f} 字/秒，超过 9.0 字/秒")
            _append_marks(
                marks,
                [parent_id],
                severity="REVIEW",
                category="chinese_length",
                target="chinese",
                code="display_page_chinese_load_review",
                reason=f"{page_id} 中文偏长：" + "；".join(reasons) + "。",
            )
    return marks


def _deterministic_text_review_marks(directory: Path) -> List[SubtitleReviewMark]:
    spans = _read_json(directory / "subtitle-spans.json", [])
    if not isinstance(spans, list):
        return []
    marks: List[SubtitleReviewMark] = []
    checks = (
        (
            re.compile(r"\b(?:18|19|20)\d{2}\s+s\b", re.IGNORECASE),
            "asr_split_decade_suffix",
            "年代后缀被拆开，疑似应写成紧连形式（例如 2000s）。",
        ),
        (
            re.compile(r"\b\d+\s+(?:st|nd|rd|th)\b", re.IGNORECASE),
            "asr_split_ordinal_suffix",
            "英文序数词后缀被拆开，疑似转录格式错误。",
        ),
        (
            re.compile(r"\b([A-Z])\.?\s+([A-Z])\.?\s+\1\.?\s+\2\.?\b"),
            "asr_repeated_initials",
            "姓名或缩写首字母序列重复，疑似 ASR 重复识别。",
        ),
    )
    for record in spans:
        if not isinstance(record, Mapping):
            continue
        subtitle_id = str(record.get("subtitle_id") or "")
        text = str(
            record.get("original")
            or record.get("text")
            or record.get("english")
            or ""
        )
        if not _SUBTITLE_ID_RE.fullmatch(subtitle_id) or not text:
            continue
        for pattern, code, reason in checks:
            match = pattern.search(text)
            if not match:
                continue
            _append_marks(
                marks,
                [subtitle_id],
                severity="REVIEW",
                category="asr_correction",
                target="english",
                code=code,
                reason=f"{reason} 异常片段：{match.group(0)}。",
            )
    return marks


def _semantic_review_queue_marks(directory: Path) -> List[SubtitleReviewMark]:
    """Expose the persisted semantic queue as read-only editor marks."""
    payload = load_bound_semantic_review_queue(directory)
    items = payload.get("items") if isinstance(payload, Mapping) else None
    if not isinstance(items, list):
        return []
    marks: List[SubtitleReviewMark] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        subtitle_ids = _normalise_ids(item.get("subtitle_ids") or [])
        if not subtitle_ids:
            continue
        reason = str(item.get("reason") or item.get("title") or "中文语义复核")
        code = str(item.get("code") or "semantic_translation_review")
        _append_marks(
            marks,
            subtitle_ids,
            severity="REVIEW",
            category="chinese_allocation",
            target="chinese",
            code=code,
            reason=reason,
        )
    return marks


def _model_translation_quality_marks(directory: Path) -> List[SubtitleReviewMark]:
    payload = _read_json(directory / "translation-quality-audit.json", {})
    if not isinstance(payload, Mapping):
        return []
    category_by_code = {
        "semantic_loss": "chinese_allocation",
        "meaning_error": "chinese_allocation",
        "number_or_negation_error": "chinese_allocation",
        "english_chinese_mismatch": "chinese_allocation",
        "adjacent_coherence": "chinese_coherence",
        "translationese": "chinese_fluency",
        "chinese_too_long": "chinese_length",
        "asr_suspicious": "asr_correction",
        "asr_format_error": "asr_correction",
    }
    marks: List[SubtitleReviewMark] = []
    for item in _as_list(payload.get("items")):
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("code") or "")
        subtitle_ids = _subtitle_ids(item)
        if code not in category_by_code or not subtitle_ids:
            continue
        _append_marks(
            marks,
            subtitle_ids,
            severity="REVIEW",
            category=category_by_code[code],
            target=("english" if code.startswith("asr_") else "chinese"),
            code=f"model_{code}",
            reason=str(
                item.get("reason") or item.get("title") or "中文质量需要复核"
            ),
        )
    return marks


def _article_asr_correction_review_marks(
    directory: Path,
) -> List[SubtitleReviewMark]:
    """Load only review candidates bound to the current frozen word ledger."""
    payload = _read_json(directory / "article-asr-correction-review.json", {})
    ledger = _read_json(directory / "word-ledger.json", {})
    if not isinstance(payload, Mapping) or not isinstance(ledger, Mapping):
        return []
    expected_hash = str(payload.get("word_ledger_hash") or "")
    current_hash = str(ledger.get("hash") or "")
    if not expected_hash or expected_hash != current_hash:
        return []

    span_text_by_id = {
        str(record.get("subtitle_id") or ""): str(
            record.get("original") or record.get("text") or ""
        )
        for record in _as_list(
            _read_json(directory / "subtitle-spans.json", [])
        )
        if isinstance(record, Mapping)
    }
    marks: List[SubtitleReviewMark] = []
    for item in _as_list(payload.get("items")):
        if not isinstance(item, Mapping) or item.get("action") != "review_only":
            continue
        subtitle_ids = _normalise_ids(item.get("subtitle_ids") or [])
        original = str(item.get("original_text") or "").strip()
        suggested = str(item.get("suggested_text") or "").strip()
        if not subtitle_ids or not original or not suggested:
            continue
        frozen_text = " ".join(
            span_text_by_id.get(subtitle_id, "") for subtitle_id in subtitle_ids
        )
        if not _legacy_article_review_is_actionable(
            original,
            suggested,
            source_key=str(item.get("source_key") or ""),
            category=str(item.get("category") or ""),
            frozen_text=frozen_text,
        ):
            continue
        _append_marks(
            marks,
            subtitle_ids,
            severity="REVIEW",
            category="asr_correction",
            target="english",
            code="article_asr_correction_review",
            reason=(
                f"疑似转录词“{original}”；文章术语建议“{suggested}”，"
                "请结合音频确认。"
            ),
        )
    return marks


def _legacy_article_review_is_actionable(
    original: str,
    suggested: str,
    *,
    source_key: str,
    category: str,
    frozen_text: str,
) -> bool:
    original_key = re.sub(r"[^a-z0-9]+", " ", original.casefold()).strip()
    suggested_key = re.sub(r"[^a-z0-9]+", " ", suggested.casefold()).strip()
    frozen_key = re.sub(r"[^a-z0-9]+", " ", frozen_text.casefold()).strip()
    place_scope = source_key.casefold() == "places" or category.casefold() in {
        "place",
        "places",
        "location",
        "country",
        "city",
    }
    if (
        place_scope
        and original_key != suggested_key
        and original_key.startswith(suggested_key[:3])
        and original_key.endswith(("an", "ans", "ian", "ians", "ese", "ish"))
    ):
        return False
    if suggested_key and re.search(
        rf"(?:^| ){re.escape(suggested_key)}(?: |$)", frozen_key
    ):
        return False
    return True


def _high_precision_english_cut_marks(directory: Path) -> List[SubtitleReviewMark]:
    """Flag only direct, within-sentence dependency breaks at a cue boundary."""
    spans = _read_json(directory / "subtitle-spans.json", [])
    ledger_payload = _read_json(directory / "word-ledger.json", {})
    ledger = ledger_payload.get("words") if isinstance(ledger_payload, Mapping) else []
    nlp = _load_syntax_nlp()
    if not isinstance(spans, list) or not isinstance(ledger, list) or nlp is None:
        return []

    marks: List[SubtitleReviewMark] = []
    for left, right in zip(spans, spans[1:]):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            continue
        left_id = str(left.get("subtitle_id") or "")
        right_id = str(right.get("subtitle_id") or "")
        left_text = str(left.get("original") or "").strip()
        right_text = str(right.get("original") or "").strip()
        if (
            not _SUBTITLE_ID_RE.fullmatch(left_id)
            or not _SUBTITLE_ID_RE.fullmatch(right_id)
            or not left_text
            or not right_text
            or _TERMINAL_SENTENCE_RE.search(left_text)
            or not _has_continuous_short_pause(left, right, ledger)
        ):
            continue
        if not _has_tail_subject_or_preposition_dependency(nlp, left_text, right_text):
            continue
        reason = "同句中的主语/名词短语与后续谓语或介词补语被切开。"
        _append_marks(
            marks,
            [left_id, right_id],
            severity="REVIEW",
            category="english_cut",
            target="english",
            code="verified_cross_boundary_dependency",
            reason=reason,
        )
    return marks


def _has_continuous_short_pause(
    left: Mapping[str, Any], right: Mapping[str, Any], ledger: List[Mapping[str, Any]]
) -> bool:
    try:
        left_end = int(left.get("word_end"))
        right_start = int(right.get("word_start"))
        if right_start != left_end + 1:
            return False
        pause_ms = int(ledger[right_start].get("start_ms", 0)) - int(
            ledger[left_end].get("end_ms", 0)
        )
    except (IndexError, TypeError, ValueError, AttributeError):
        return False
    return 0 <= pause_ms <= 180


def _has_tail_subject_or_preposition_dependency(nlp: Any, left_text: str, right_text: str) -> bool:
    """Require a direct cross-boundary dependency anchored at the left cue tail."""
    doc = nlp(f"{left_text} {right_text}")
    boundary_char = len(left_text)
    left_tokens = [token for token in doc if token.idx < boundary_char and not token.is_punct]
    if not left_tokens:
        return False
    tail = left_tokens[-1]
    for token in doc:
        if token.is_punct or token.head == token:
            continue
        token_left = token.idx < boundary_char
        head_left = token.head.idx < boundary_char
        if token_left == head_left:
            continue
        if (
            token_left
            and token == tail
            and token.dep_ in {"nsubj", "nsubjpass", "expl"}
            and token.head.pos_ in {"VERB", "AUX"}
        ):
            return True
        if (
            not token_left
            and token.dep_ == "prep"
            and token.head == tail
            and token.head.pos_ in {"NOUN", "PROPN"}
            and not _has_finite_verb_since_last_sentence(doc, boundary_char)
        ):
            return True
    return False


def _has_finite_verb_since_last_sentence(doc: Any, boundary_char: int) -> bool:
    left_tokens = [token for token in doc if token.idx < boundary_char]
    last_terminal = max(
        (index for index, token in enumerate(left_tokens) if token.text in {".", "!", "?"}),
        default=-1,
    )
    return any(token.pos_ in {"VERB", "AUX"} for token in left_tokens[last_terminal + 1 :])


@lru_cache(maxsize=1)
def _load_syntax_nlp() -> Any | None:
    try:
        import spacy  # type: ignore

        return spacy.load("en_core_web_sm", disable=["ner", "textcat"])
    except Exception:
        return None


def _group_marks(marks: Iterable[SubtitleReviewMark]) -> Dict[str, List[SubtitleReviewMark]]:
    grouped: Dict[str, List[SubtitleReviewMark]] = {}
    seen: set[tuple[str, str, str, str, str]] = set()
    for mark in marks:
        key = (mark.subtitle_id, mark.target, mark.severity, mark.code, mark.reason)
        if key in seen:
            continue
        seen.add(key)
        grouped.setdefault(mark.subtitle_id, []).append(mark)
    return grouped


def _main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m app.core.subtitle_processor.subtitle_review_marks <artifact_dir>", file=sys.stderr)
        return 2
    marks = load_subtitle_review_marks(Path(sys.argv[1]))
    payload = {
        "schema_version": 1,
        "syntax_parser_available": syntax_review_parser_available(),
        "marks": review_marks_to_payload(marks),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
