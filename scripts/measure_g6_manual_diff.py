"""Read-only G6 measurement against an immutable manual-final package.

The script treats the current manual package history as the reference answer
and compares it with the generated QA queue.  It never imports production
pipeline code and never writes to a run or a manual package.  An optional
``--output-json`` path is intended for a report outside ``work-dir``.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any


PARENT_RE = re.compile(r"\b(S\d{4,})\b")

# Confirmation/acknowledgement records are not edits.  The remaining names
# cover the editor operations used by current manual-final packages, including
# older schema spellings observed in saved packages.
EDIT_OPERATIONS = frozenset(
    {
        "edit_display_page_chinese",
        "edit_english_surface",
        "move_display_page_boundary",
        "move_prefix_to_previous",
        "move_suffix_to_next",
        "split_display_page",
        "split_parent_into_display_pages",
        "merge_display_page_with_next",
        "merge_adjacent_display_pages",
        "merge_adjacent",
        "trim_tail_from_cue",
        "set_display_suppressed",
        "set_hidden_and_media_muted",
        "confirm_display_page_boundary",
    }
)

WORD_OPERATIONS = frozenset({"edit_english_surface"})
ID_FIELDS = (
    "parent_subtitle_id",
    "affected_parent_ids",
    "subtitle_id",
    "subtitle_ids",
    "left_page_id",
    "right_page_id",
    "display_page_id",
)


class G6MeasurementError(ValueError):
    """Raised when the inputs cannot support a comparable measurement."""


def _load_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise G6MeasurementError(f"input does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise G6MeasurementError(f"cannot read JSON input {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise G6MeasurementError(f"JSON root must be an object: {path}")
    return payload


def _load_queue(path: Path) -> Mapping[str, Any]:
    """Load the JSON queue or the exported human-readable QC SRT."""

    if path.suffix.lower() != ".srt":
        return _load_json(path)
    if not path.is_file():
        raise G6MeasurementError(f"input does not exist: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise G6MeasurementError(f"cannot read queue SRT {path}: {exc}") from exc
    items: list[dict[str, list[str]]] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        ids: set[str] = set()
        for line in block.splitlines():
            match = re.match(r"^ID:\s*(.+?)\s*$", line.strip())
            if not match:
                continue
            ids.update(
                parent
                for parent in PARENT_RE.findall(match.group(1))
                if PARENT_RE.fullmatch(parent)
            )
        if ids:
            items.append({"subtitle_ids": sorted(ids)})
    if not items:
        raise G6MeasurementError(f"queue SRT contains no ID lines: {path}")
    return {"schema_version": "qc-srt", "items": items}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _ids_from_value(value: Any) -> set[str]:
    """Extract parent IDs from editor identity fields without trusting prose."""

    result: set[str] = set()
    if isinstance(value, str):
        result.update(match.group(1) for match in PARENT_RE.finditer(value))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if key in ID_FIELDS or key.endswith("_id") or key.endswith("_ids"):
                result.update(_ids_from_value(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            result.update(_ids_from_value(item))
    return result


def _history_ids(record: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for field in ID_FIELDS:
        result.update(_ids_from_value(record.get(field)))
    # A few schema-v2 records put identity inside before_parent_states.
    if not result:
        result.update(_ids_from_value(record.get("before_parent_states")))
    if not result:
        result.update(_ids_from_value(record.get("before_cues")))
    return {item for item in result if PARENT_RE.fullmatch(item)}


def _source_parent_english(document: Mapping[str, Any]) -> dict[str, str]:
    source_dir = document.get("source_artifact_dir")
    if not isinstance(source_dir, str):
        return {}
    path = Path(source_dir) / "subtitle-spans.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, list):
        return {}
    return {
        str(item["subtitle_id"]): str(item.get("original") or "")
        for item in payload
        if isinstance(item, Mapping) and isinstance(item.get("subtitle_id"), str)
    }


def _final_parent_english(document: Mapping[str, Any]) -> dict[str, str]:
    cues = document.get("cues")
    if not isinstance(cues, list):
        return {}
    return {
        str(item["cue_id"]): str(item.get("original_subtitle") or "")
        for item in cues
        if isinstance(item, Mapping) and isinstance(item.get("cue_id"), str)
    }


def _is_single_word_substitution(before: str, after: str) -> bool:
    token_pattern = r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*"
    before_tokens = re.findall(token_pattern, before)
    after_tokens = re.findall(token_pattern, after)
    changes = [
        item
        for item in difflib.SequenceMatcher(a=before_tokens, b=after_tokens).get_opcodes()
        if item[0] != "equal"
    ]
    if len(changes) != 1:
        return False
    tag, before_start, before_end, after_start, after_end = changes[0]
    return tag == "replace" and before_end - before_start == 1 and after_end - after_start == 1


def _manual_change_sets(document: Mapping[str, Any]) -> tuple[set[str], set[str], dict[str, int]]:
    history = document.get("history")
    if not isinstance(history, list):
        raise G6MeasurementError("manual package has no list-valued history")

    changed: set[str] = set()
    word_changed: set[str] = set()
    operation_counts: dict[str, int] = {}
    for raw_record in history:
        if not isinstance(raw_record, Mapping):
            continue
        operation = str(raw_record.get("operation") or "")
        operation_counts[operation] = operation_counts.get(operation, 0) + 1
        if operation not in EDIT_OPERATIONS:
            continue
        ids = _history_ids(raw_record)
        if operation == "trim_tail_from_cue":
            ids = {
                match.group(1)
                for match in PARENT_RE.finditer(str(raw_record.get("first_removed_display_page_id") or ""))
            }
        changed.update(ids)
        if operation in WORD_OPERATIONS:
            word_changed.update(ids)

    # A surface edit can be a multi-token phrase/entity replacement.  G6's
    # word-level denominator is limited to one-token substitutions; this keeps
    # phrase rewrites in the parent/display bucket instead of mislabelling them
    # as single-word ASR errors.
    source_english = _source_parent_english(document)
    final_english = _final_parent_english(document)
    if source_english and final_english:
        word_changed = {
            parent_id
            for parent_id in word_changed
            if _is_single_word_substitution(
                source_english.get(parent_id, ""), final_english.get(parent_id, "")
            )
        }

    if not changed:
        raise G6MeasurementError("manual package history contains no recognised edits")
    return changed, word_changed, operation_counts


def _queue_items(document: Mapping[str, Any]) -> list[set[str]]:
    raw_items = document.get("items")
    if isinstance(raw_items, list):
        items: list[set[str]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            ids = _ids_from_value(raw_item.get("subtitle_ids"))
            if not ids:
                ids = _ids_from_value(raw_item.get("parent_subtitle_id"))
            if not ids:
                ids = _ids_from_value(raw_item.get("context"))
            if ids:
                items.append({item for item in ids if PARENT_RE.fullmatch(item)})
        if items:
            return items

    queue = document.get("queue")
    if isinstance(queue, Mapping) and isinstance(queue.get("subtitle_ids"), list):
        fallback = []
        for value in queue["subtitle_ids"]:
            ids = _ids_from_value(value)
            if ids:
                fallback.append({item for item in ids if PARENT_RE.fullmatch(item)})
        if fallback:
            return fallback
    raise G6MeasurementError("QA queue contains neither usable items nor queue.subtitle_ids")


def _source_hashes(manual: Mapping[str, Any], queue: Mapping[str, Any]) -> tuple[str | None, str | None]:
    manual_hash = manual.get("source_word_ledger_hash")
    source_run = queue.get("source_run")
    queue_hash = source_run.get("word_ledger_hash") if isinstance(source_run, Mapping) else None
    return (str(manual_hash) if manual_hash else None, str(queue_hash) if queue_hash else None)


def _percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 6) if denominator else 0.0


def measure(manual_path: Path, queue_path: Path) -> dict[str, Any]:
    manual = _load_json(manual_path)
    queue = _load_queue(queue_path)
    manual_hash, queue_hash = _source_hashes(manual, queue)
    if manual_hash and queue_hash and manual_hash != queue_hash:
        raise G6MeasurementError(
            "manual package and QA queue use different word ledgers: "
            f"{manual_hash} != {queue_hash}"
        )

    changed, word_changed, operation_counts = _manual_change_sets(manual)
    queue_items = _queue_items(queue)
    queue_parents = set().union(*queue_items) if queue_items else set()
    hit_items = [ids for ids in queue_items if ids & changed]
    hit_parents = queue_parents & changed
    word_hit_parents = set().union(*(ids & word_changed for ids in queue_items)) if queue_items else set()

    return {
        "schema": "g6-manual-diff-v1",
        "manual_edits": str(manual_path),
        "qa_queue": str(queue_path),
        "word_ledger_hash": manual_hash or queue_hash,
        "manual_change_parent_count": len(changed),
        "manual_change_parent_ids": sorted(changed),
        "queue_item_count": len(queue_items),
        "queue_unique_parent_count": len(queue_parents),
        "queue_hit_item_count": len(hit_items),
        "queue_hit_parent_count": len(hit_parents),
        "queue_hit_parent_ids": sorted(hit_parents),
        "recall_percent": _percent(len(hit_parents), len(changed)),
        "precision_percent": round(_percent(len(hit_parents), len(queue_parents)), 0),
        "precision_percent_exact": _percent(len(hit_parents), len(queue_parents)),
        "word_change_parent_count": len(word_changed),
        "word_change_parent_ids": sorted(word_changed),
        "word_hit_parent_count": len(word_hit_parents),
        "word_hit_parent_ids": sorted(word_hit_parents),
        "word_hit_fraction": f"{len(word_hit_parents)}/{len(word_changed)}",
        "operation_counts": operation_counts,
    }


def _check_expected(result: Mapping[str, Any], args: argparse.Namespace) -> list[str]:
    failures: list[str] = []
    if args.expect_manual_parents is not None and result["manual_change_parent_count"] != args.expect_manual_parents:
        failures.append(
            f"manual parents {result['manual_change_parent_count']} != {args.expect_manual_parents}"
        )
    if args.expect_recall_percent is not None and result["recall_percent"] != args.expect_recall_percent:
        failures.append(f"recall {result['recall_percent']} != {args.expect_recall_percent}")
    if args.expect_precision_percent is not None and result["precision_percent"] != args.expect_precision_percent:
        failures.append(
            f"precision {result['precision_percent']} != {args.expect_precision_percent}"
        )
    if args.expect_word_fraction is not None and result["word_hit_fraction"] != args.expect_word_fraction:
        failures.append(
            f"word hit {result['word_hit_fraction']} != {args.expect_word_fraction}"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual-edits", type=Path, required=True)
    parser.add_argument("--qa-queue", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--expect-manual-parents", type=int)
    parser.add_argument("--expect-recall-percent", type=float)
    parser.add_argument("--expect-precision-percent", type=float)
    parser.add_argument("--expect-word-fraction")
    args = parser.parse_args(argv)

    try:
        result = measure(args.manual_edits, args.qa_queue)
    except G6MeasurementError as exc:
        print(f"G6 measurement failed: {exc}", file=sys.stderr)
        return 2

    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(encoded, end="")
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(encoded, encoding="utf-8")

    failures = _check_expected(result, args)
    if failures:
        print("G6 acceptance mismatch: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
