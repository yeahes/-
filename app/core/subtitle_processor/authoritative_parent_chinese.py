"""Versioned, ID-bound Chinese records for stable parent subtitles.

The stable pipeline has several serialized projections of parent Chinese text.
This module gives those projections one content-addressed authority without
owning English segmentation, display-page planning, or timing.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping, Sequence

from app.core.subtitle_processor.stable_pipeline_contracts import (
    stable_payload_hash,
)


PARENT_CHINESE_AUTHORITY_SCHEMA_VERSION = 1


class AuthoritativeParentChineseError(ValueError):
    """Describe a deterministic authority-contract violation."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = str(code)
        self.details = dict(details)
        super().__init__(f"{self.code}: {message}")


def _normalise_english(value: object) -> str:
    return " ".join(str(value or "").split())


def _normalise_chinese(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _text_hash(value: str) -> str:
    return stable_payload_hash(value)


def _source_payload(
    subtitle_id: str,
    english_hash: str,
    word_start: int,
    word_end: int,
) -> dict[str, Any]:
    return {
        "subtitle_id": subtitle_id,
        "english_hash": english_hash,
        "word_start": word_start,
        "word_end": word_end,
    }


def _record_payload_without_hash(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "record_version": int(record.get("record_version") or 1),
        "subtitle_id": str(record.get("subtitle_id") or ""),
        "english": _normalise_english(record.get("english")),
        "english_hash": str(record.get("english_hash") or ""),
        "word_start": int(record.get("word_start") or 0),
        "word_end": int(record.get("word_end") or 0),
        "source_hash": str(record.get("source_hash") or ""),
        "chinese": _normalise_chinese(record.get("chinese")),
        "chinese_hash": str(record.get("chinese_hash") or ""),
        "provenance": dict(record.get("provenance") or {}),
    }


def build_authoritative_parent_chinese_artifact(
    records: Sequence[Mapping[str, Any]],
    *,
    source_word_ledger_hash: str,
    producer: str,
) -> dict[str, Any]:
    """Build one deterministic Chinese record for every frozen parent ID."""
    normalized_records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in records:
        subtitle_id = str(raw.get("subtitle_id") or raw.get("cue_id") or "").strip()
        english = _normalise_english(
            raw.get("english")
            or raw.get("original_subtitle")
            or raw.get("text")
        )
        chinese = _normalise_chinese(
            raw.get("chinese")
            or raw.get("translated_subtitle")
            or raw.get("translated_text")
        )
        try:
            word_start = int(raw["word_start"])
            word_end = int(raw["word_end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthoritativeParentChineseError(
                "authoritative_parent_chinese_span_invalid",
                "A parent Chinese record is missing its frozen word span.",
                subtitle_id=subtitle_id,
            ) from exc
        invalid_fields: list[str] = []
        if not subtitle_id:
            invalid_fields.append("subtitle_id")
        elif subtitle_id in seen_ids:
            invalid_fields.append("duplicate_subtitle_id")
        if not english:
            invalid_fields.append("english")
        if not chinese:
            invalid_fields.append("chinese")
        if word_start < 0:
            invalid_fields.append("word_start")
        if word_end < word_start:
            invalid_fields.append("word_end")
        if invalid_fields:
            raise AuthoritativeParentChineseError(
                "authoritative_parent_chinese_record_invalid",
                "A parent Chinese record has invalid identity, text, or coverage.",
                subtitle_id=subtitle_id,
                invalid_fields=invalid_fields,
                english=english,
                chinese=chinese,
                word_start=word_start,
                word_end=word_end,
            )
        seen_ids.add(subtitle_id)
        english_hash = _text_hash(english)
        source_hash = stable_payload_hash(
            _source_payload(subtitle_id, english_hash, word_start, word_end)
        )
        provenance = dict(raw.get("provenance") or {})
        provenance.setdefault("kind", "automatic")
        provenance.setdefault("producer", str(producer or "unknown"))
        provenance.setdefault("base_record_hash", "")
        provenance.setdefault("display_page_contract_hash", "")
        record = {
            "record_version": 1,
            "subtitle_id": subtitle_id,
            "english": english,
            "english_hash": english_hash,
            "word_start": word_start,
            "word_end": word_end,
            "source_hash": source_hash,
            "chinese": chinese,
            "chinese_hash": _text_hash(chinese),
            "provenance": provenance,
        }
        record["record_hash"] = stable_payload_hash(
            _record_payload_without_hash(record)
        )
        normalized_records.append(record)

    payload = {
        "schema_version": PARENT_CHINESE_AUTHORITY_SCHEMA_VERSION,
        "source_word_ledger_hash": str(source_word_ledger_hash or ""),
        "producer": str(producer or "unknown"),
        "records": normalized_records,
    }
    payload["artifact_hash"] = stable_payload_hash(payload)
    return payload


def validate_authoritative_parent_chinese_artifact(
    payload: Mapping[str, Any],
    *,
    expected_parents: Sequence[Mapping[str, Any]] = (),
    expected_word_ledger_hash: str = "",
) -> dict[str, Any]:
    """Validate hashes, cardinality, and optional frozen parent projections."""
    if int(payload.get("schema_version") or 0) != PARENT_CHINESE_AUTHORITY_SCHEMA_VERSION:
        raise AuthoritativeParentChineseError(
            "authoritative_parent_chinese_schema_invalid",
            "The parent Chinese authority schema is unsupported.",
        )
    ledger_hash = str(payload.get("source_word_ledger_hash") or "")
    if expected_word_ledger_hash and ledger_hash != str(expected_word_ledger_hash):
        raise AuthoritativeParentChineseError(
            "authoritative_parent_chinese_ledger_mismatch",
            "The parent Chinese authority belongs to a different word ledger.",
        )
    raw_records = list(payload.get("records") or [])
    rebuilt = build_authoritative_parent_chinese_artifact(
        raw_records,
        source_word_ledger_hash=ledger_hash,
        producer=str(payload.get("producer") or "unknown"),
    )
    for raw, normalized in zip(raw_records, rebuilt["records"]):
        for key in (
            "english_hash",
            "source_hash",
            "chinese_hash",
            "record_hash",
        ):
            if str(raw.get(key) or "") != str(normalized.get(key) or ""):
                raise AuthoritativeParentChineseError(
                    "authoritative_parent_chinese_hash_mismatch",
                    "A parent Chinese record hash does not match its content.",
                    subtitle_id=normalized["subtitle_id"],
                    field=key,
                )
    declared_artifact_hash = str(payload.get("artifact_hash") or "")
    if not declared_artifact_hash or declared_artifact_hash != rebuilt["artifact_hash"]:
        raise AuthoritativeParentChineseError(
            "authoritative_parent_chinese_artifact_hash_mismatch",
            "The parent Chinese authority artifact hash is invalid.",
        )

    if expected_parents:
        expected = build_authoritative_parent_chinese_artifact(
            expected_parents,
            source_word_ledger_hash=ledger_hash,
            producer="expected_projection",
        )
        actual_by_id = {
            str(record["subtitle_id"]): record for record in rebuilt["records"]
        }
        expected_by_id = {
            str(record["subtitle_id"]): record for record in expected["records"]
        }
        if set(actual_by_id) != set(expected_by_id):
            raise AuthoritativeParentChineseError(
                "authoritative_parent_chinese_id_mismatch",
                "The parent Chinese authority does not cover the expected IDs.",
            )
        for subtitle_id, expected_record in expected_by_id.items():
            actual = actual_by_id[subtitle_id]
            if (
                actual["source_hash"] != expected_record["source_hash"]
                or actual["chinese_hash"] != expected_record["chinese_hash"]
            ):
                raise AuthoritativeParentChineseError(
                    "authoritative_parent_chinese_projection_mismatch",
                    "The parent subtitle projection conflicts with its authority record.",
                    subtitle_id=subtitle_id,
                )
    return rebuilt


def parent_chinese_records_by_id(
    payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    validated = validate_authoritative_parent_chinese_artifact(payload)
    return {
        str(record["subtitle_id"]): dict(record)
        for record in validated["records"]
    }


def bind_display_page_parent_records(
    display_artifact: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind a display projection to the unchanged authoritative parent record."""
    result = copy.deepcopy(dict(display_artifact))
    for parent in result.get("parents") or []:
        parent_id = str(parent.get("parent_subtitle_id") or "")
        record = records_by_id.get(parent_id)
        if record is None:
            raise AuthoritativeParentChineseError(
                "authoritative_parent_chinese_page_parent_missing",
                "A display-page parent has no authoritative Chinese record.",
                subtitle_id=parent_id,
            )
        source_chinese_present = "source_parent_chinese" in parent
        source_hash_present = "source_parent_chinese_hash" in parent
        if not source_chinese_present:
            legacy_aggregate = _normalise_chinese(parent.get("aggregate_chinese"))
            authoritative_chinese = _normalise_chinese(record.get("chinese"))
            if not legacy_aggregate or legacy_aggregate != authoritative_chinese:
                raise AuthoritativeParentChineseError(
                    "authoritative_parent_chinese_page_conflict",
                    "A legacy display projection does not reconstruct the authoritative parent Chinese.",
                    subtitle_id=parent_id,
                )
            parent["source_parent_chinese"] = str(record.get("chinese") or "")
            parent["source_parent_chinese_hash"] = str(
                record.get("chinese_hash") or ""
            )
        elif not source_hash_present:
            source_chinese = _normalise_chinese(parent.get("source_parent_chinese"))
            if source_chinese != _normalise_chinese(record.get("chinese")):
                raise AuthoritativeParentChineseError(
                    "authoritative_parent_chinese_page_conflict",
                    "A legacy display projection references different parent Chinese.",
                    subtitle_id=parent_id,
                )
            parent["source_parent_chinese_hash"] = str(
                record.get("chinese_hash") or ""
            )
        source_chinese = _normalise_chinese(parent.get("source_parent_chinese"))
        source_chinese_hash = str(parent.get("source_parent_chinese_hash") or "")
        if (
            source_chinese != _normalise_chinese(record.get("chinese"))
            or source_chinese_hash != str(record.get("chinese_hash") or "")
        ):
            raise AuthoritativeParentChineseError(
                "authoritative_parent_chinese_page_conflict",
                "The display projection was created from a different parent Chinese record.",
                subtitle_id=parent_id,
            )
        if (
            int(parent.get("word_start", -1)) != int(record.get("word_start", -2))
            or int(parent.get("word_end", -1)) != int(record.get("word_end", -2))
            or str(parent.get("parent_english_hash") or "")
            != str(record.get("english_hash") or "")
        ):
            raise AuthoritativeParentChineseError(
                "authoritative_parent_chinese_page_identity_mismatch",
                "Display-page identity conflicts with the authoritative parent record.",
                subtitle_id=parent_id,
            )
        parent["parent_source_hash"] = str(record["source_hash"])
        parent["parent_record_hash"] = str(record["record_hash"])
    return result


def validate_display_page_parent_records(
    display_artifact: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    """Require every stored page parent to carry the current authority refs."""
    bound = bind_display_page_parent_records(display_artifact, records_by_id)
    original_parents = list(display_artifact.get("parents") or [])
    bound_parents = list(bound.get("parents") or [])
    for original, expected in zip(original_parents, bound_parents):
        source_ref = str(original.get("parent_source_hash") or "")
        record_ref = str(original.get("parent_record_hash") or "")
        expected_source_ref = str(expected.get("parent_source_hash") or "")
        expected_record_ref = str(expected.get("parent_record_hash") or "")
        legacy_without_source = "source_parent_chinese" not in original
        references_invalid = (
            (bool(source_ref) and source_ref != expected_source_ref)
            or (bool(record_ref) and record_ref != expected_record_ref)
            or (
                not legacy_without_source
                and (source_ref != expected_source_ref or record_ref != expected_record_ref)
            )
        )
        if references_invalid:
            raise AuthoritativeParentChineseError(
                "authoritative_parent_chinese_page_reference_mismatch",
                "Display-page Chinese is not bound to the current parent record.",
                subtitle_id=str(original.get("parent_subtitle_id") or ""),
            )
