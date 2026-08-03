"""Read-only, ID-driven quality marks for the manual subtitle editor.

The stable pipeline already emits validation artifacts.  This module turns
only high-confidence, subtitle-ID-addressable findings into editor marks.  It
does not recalculate quality, infer rows from text, or change subtitle data.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


_SUBTITLE_ID_RE = re.compile(r"S\d{4}")
_TERMINAL_SENTENCE_RE = re.compile(r"[.!?][\"'”’\)\]]*$")


@dataclass(frozen=True)
class SubtitleReviewMark:
    """One high-confidence review marker for a frozen subtitle ID."""

    subtitle_id: str
    severity: str
    category: str
    target: str
    code: str
    reason: str


def load_subtitle_review_marks(
    artifact_dir: str | Path,
) -> Dict[str, List[SubtitleReviewMark]]:
    """Load marker candidates without mutating subtitle or audit artifacts."""
    directory = Path(artifact_dir)
    validation = _read_json(directory / "validation-report.json", {})
    structure_errors = _read_json(directory / "translation-structure-errors.json", [])
    marks: List[SubtitleReviewMark] = []

    for error in _as_list(structure_errors):
        _append_marks(
            marks,
            _subtitle_ids(error),
            severity="BLOCKER",
            category="structure",
            target="both",
            code=str(error.get("code") or "translation_structure_error"),
            reason="中文返回结构与冻结 subtitle_id 不一致。",
        )

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
    marks.extend(_high_precision_english_cut_marks(directory))

    return _group_marks(marks)


def syntax_review_parser_available() -> bool:
    """Return whether the local spaCy dependency parser is available."""
    return _load_syntax_nlp() is not None


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
                )
            except KeyError:
                continue
            restored.setdefault(normalized_id, []).append(mark)
    return _group_marks(mark for marks in restored.values() for mark in marks)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _group_entries(group: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    items = group.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, Mapping)]
    return [group]


def _subtitle_ids(payload: Mapping[str, Any]) -> List[str]:
    values: List[Any] = [payload.get("subtitle_id")]
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
    reason = str(payload.get("reason") or "").strip()
    if reason:
        return reason
    codes = [str(code) for code in _as_list(payload.get("rule_codes"))]
    if codes:
        return ", ".join(codes)
    return str((group or {}).get("message") or "需要人工复核")


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
    for subtitle_id in subtitle_ids:
        marks.append(
            SubtitleReviewMark(
                subtitle_id=subtitle_id,
                severity=severity,
                category=category,
                target=target,
                code=code,
                reason=reason or "需要人工复核",
            )
        )


def _final_timeline_fallback_marks(directory: Path) -> List[SubtitleReviewMark]:
    """Mark only final cues whose time still contains a stable-ts fallback word.

    This is provenance from the final time artifact, not a heuristic about
    subtitle duration.  It therefore remains useful in the editor without
    turning routine short or fast cues into noisy review markers.
    """
    timeline = _read_json(directory / "final-cue-timeline.json", {})
    records = timeline.get("records") if isinstance(timeline, Mapping) else []
    if not isinstance(records, list):
        return []

    marks: List[SubtitleReviewMark] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        subtitle_id = str(record.get("subtitle_id") or "")
        sources = record.get("word_alignment_sources")
        if not _SUBTITLE_ID_RE.fullmatch(subtitle_id) or not isinstance(sources, list):
            continue
        fallback_sources = [
            str(source)
            for source in sources
            if str(source).startswith("stable-ts-fallback")
        ]
        if not fallback_sources:
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
