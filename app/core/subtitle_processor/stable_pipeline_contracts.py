"""Serializable contracts shared by stable subtitle pipeline stages.

The stable pipeline has a strict ownership rule: after English boundaries and
global subtitle IDs are assigned, later Chinese-only stages must not alter the
English source, word ledger, timing, or semantic-group membership. Keeping
this snapshot format outside ``screen_editor.py`` gives allocation, audit, and
export code one reproducible definition of those frozen inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, List, Mapping, Sequence


FROZEN_PIPELINE_HASH_KEYS = (
    "asr_text_hash",
    "corrected_english_hash",
    "word_ledger_hash",
    "english_text_hash",
    "word_timing_hash",
    "subtitle_id_time_hash",
    "semantic_group_input_hash",
    "authoritative_full_translation_hash",
)


def stable_payload_hash(payload: Any) -> str:
    """Hash a JSON-compatible payload with deterministic key ordering."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


WORD_LEDGER_HASH_VERSION = "canonical-word-ledger-v1"


def canonical_word_ledger_payload(
    ledger: Sequence[Mapping[str, Any]],
) -> List[List[Any]]:
    """Return the semantic identity shared by all word-ledger owners."""
    return [
        [
            str(word.get("surface", word.get("token", "")) or ""),
            str(word.get("normalized", word.get("token", "")) or ""),
            int(word.get("start_ms", word.get("start_time", 0)) or 0),
            int(word.get("end_ms", word.get("end_time", 0)) or 0),
        ]
        for word in ledger
    ]


def canonical_word_ledger_hash(ledger: Sequence[Mapping[str, Any]]) -> str:
    """Hash ordered word surfaces, normalized forms, and authoritative times."""
    raw = json.dumps(
        canonical_word_ledger_payload(ledger),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrozenPipelineSnapshot:
    """The immutable inputs that Chinese-only work is forbidden to change."""

    stage: str
    hashes: Mapping[str, str]
    payloads: Mapping[str, Sequence[Any]]

    @classmethod
    def build(
        cls,
        *,
        stage: str,
        source_segments: Sequence[Mapping[str, Any]],
        subtitle_items: Sequence[Mapping[str, Any]],
        subtitle_id_times: Sequence[Mapping[str, Any]],
        semantic_groups: Sequence[Mapping[str, Any]],
        full_translations: Sequence[Mapping[str, Any]],
        word_timing: Sequence[Sequence[Any]],
        word_ledger_hash: str,
        final_segments: Sequence[Mapping[str, Any]],
        include_final_segment_timing: bool,
    ) -> "FrozenPipelineSnapshot":
        payloads: Dict[str, Sequence[Any]] = {
            "source_segments": list(source_segments),
            "subtitle_items": list(subtitle_items),
            "subtitle_id_times": list(subtitle_id_times),
            "semantic_groups": list(semantic_groups),
            "full_translations": list(full_translations),
            "word_timing": list(word_timing),
            "final_segments": list(final_segments),
        }
        hashes = {
            "asr_text_hash": stable_payload_hash(payloads["source_segments"]),
            "corrected_english_hash": stable_payload_hash(payloads["source_segments"]),
            "word_ledger_hash": str(word_ledger_hash or stable_payload_hash(payloads["word_timing"])),
            "english_text_hash": stable_payload_hash(payloads["subtitle_items"]),
            "word_timing_hash": stable_payload_hash(payloads["word_timing"]),
            "subtitle_id_time_hash": stable_payload_hash(payloads["subtitle_id_times"]),
            "semantic_group_input_hash": stable_payload_hash(payloads["semantic_groups"]),
            "authoritative_full_translation_hash": stable_payload_hash(
                payloads["full_translations"]
            ),
            "final_subtitle_time_hash": (
                stable_payload_hash(payloads["final_segments"])
                if include_final_segment_timing
                else ""
            ),
        }
        return cls(stage=stage, hashes=hashes, payloads=payloads)

    def to_artifact(self) -> Dict[str, Any]:
        return {"stage": self.stage, **dict(self.hashes), "payloads": dict(self.payloads)}

    def changed_frozen_keys(self, other: "FrozenPipelineSnapshot") -> list[str]:
        return [
            key
            for key in FROZEN_PIPELINE_HASH_KEYS
            if self.hashes.get(key)
            and other.hashes.get(key)
            and self.hashes[key] != other.hashes[key]
        ]
