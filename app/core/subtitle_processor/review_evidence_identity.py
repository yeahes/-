"""Identity contract for review evidence derived from frozen subtitles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from app.core.subtitle_processor.stable_pipeline_contracts import (
    canonical_word_ledger_hash,
    stable_payload_hash,
)


SEMANTIC_REVIEW_QUEUE_SCHEMA_VERSION = 2
_SUBTITLE_ID_RE = re.compile(r"S\d{4}")


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _english(span: Mapping[str, Any]) -> str:
    return str(
        span.get("original")
        or span.get("text")
        or span.get("english")
        or ""
    )


def _word_bound(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def frozen_span_identity_records(
    subtitle_spans: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return the ID/text/word-range identity owned before review generation."""
    return [
        {
            "subtitle_id": str(span.get("subtitle_id") or ""),
            "english": _english(span),
            "word_start": _word_bound(span.get("word_start")),
            "word_end": _word_bound(span.get("word_end")),
        }
        for span in subtitle_spans
        if isinstance(span, Mapping)
    ]


def build_review_source_identity(
    word_ledger: Mapping[str, Any],
    subtitle_spans: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Build the source identity required by every persisted review queue."""
    words = [
        word
        for word in _as_list(word_ledger.get("words"))
        if isinstance(word, Mapping)
    ]
    word_ledger_hash = str(word_ledger.get("hash") or "")
    if not word_ledger_hash:
        word_ledger_hash = canonical_word_ledger_hash(words)
    span_records = frozen_span_identity_records(subtitle_spans)
    return {
        "word_ledger_hash": word_ledger_hash,
        "frozen_span_hash": stable_payload_hash(span_records),
        "subtitle_count": len(span_records),
    }


def review_source_identity_matches(
    source: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    """Return whether review evidence proves the current frozen source."""
    return all(
        source.get(key) not in (None, "") and source.get(key) == current.get(key)
        for key in ("word_ledger_hash", "frozen_span_hash", "subtitle_count")
    )


def review_run_identity_matches(
    source: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    artifact_dir: str | Path | None = None,
) -> bool:
    """Reject review evidence copied from another run or code revision."""
    for key in ("code_commit", "stable_run_id", "attempt_id"):
        current_value = str(current.get(key) or "")
        source_value = str(source.get(key) or "")
        # Once the current artifact declares a run identity, an older payload
        # that predates that field is not evidence for this run.  Artifacts
        # without a manifest retain the legacy source/span contract.
        if current_value and source_value != current_value:
            return False
    source_artifact_dir = str(source.get("artifact_dir") or "").strip()
    if source_artifact_dir and artifact_dir is not None:
        try:
            if Path(source_artifact_dir).resolve() != Path(artifact_dir).resolve():
                return False
        except OSError:
            return False
    return True


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def load_bound_semantic_review_queue(
    artifact_dir: str | Path,
) -> Dict[str, Any] | None:
    """Load a semantic queue only when every frozen identity field matches."""
    directory = Path(artifact_dir)
    payload = _read_json(directory / "semantic-review-queue.json")
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") != SEMANTIC_REVIEW_QUEUE_SCHEMA_VERSION:
        return None

    ledger = _read_json(directory / "word-ledger.json")
    spans = _read_json(directory / "subtitle-spans.json")
    if not isinstance(ledger, Mapping) or not isinstance(spans, list):
        return None
    span_records = frozen_span_identity_records(
        [span for span in spans if isinstance(span, Mapping)]
    )
    current_identity = build_review_source_identity(ledger, spans)
    source_identity = payload.get("source_run")
    if not isinstance(source_identity, Mapping) or not review_source_identity_matches(
        source_identity,
        current_identity,
    ):
        return None
    run_manifest = _read_json(directory / "run-manifest.json")
    current_run_identity = (
        run_manifest if isinstance(run_manifest, Mapping) else {}
    )
    if not review_run_identity_matches(
        source_identity,
        current_run_identity,
        artifact_dir=directory,
    ):
        return None

    current_by_id = {
        str(record.get("subtitle_id") or ""): record for record in span_records
    }
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        subtitle_ids = [
            str(value)
            for value in _as_list(item.get("subtitle_ids"))
            if _SUBTITLE_ID_RE.fullmatch(str(value))
        ]
        if not subtitle_ids:
            continue
        context_by_id = {
            str(context.get("subtitle_id") or ""): context
            for context in _as_list(item.get("context"))
            if isinstance(context, Mapping)
        }
        for subtitle_id in subtitle_ids:
            current = current_by_id.get(subtitle_id)
            context = context_by_id.get(subtitle_id)
            if current is None or context is None:
                return None
            if (
                str(context.get("english") or "") != current["english"]
                or _word_bound(context.get("word_start")) != current["word_start"]
                or _word_bound(context.get("word_end")) != current["word_end"]
            ):
                return None
    return dict(payload)
