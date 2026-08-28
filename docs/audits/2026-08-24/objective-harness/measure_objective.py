"""Measure the §28 objective on immutable manual-edit snapshots.

This is deliberately independent from production review-mark and generation
code. It reads only the three registered edit packages and writes optional
reports under the audit directory. The registered gate values are constants:
the command cannot change them through CLI options.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


PARENT_RE = re.compile(r"^(S\d+)")
ID_FIELDS = (
    "parent_subtitle_id",
    "display_page_id",
    "left_page_id",
    "right_page_id",
    "affected_parent_ids",
)
LAYOUT_OPERATIONS = frozenset(
    {
        "split_display_page",
        "split_parent_into_display_pages",
        "merge_display_page_with_next",
        "merge_adjacent_display_pages",
        "move_display_page_boundary",
        "move_prefix_to_previous",
        "move_suffix_to_next",
    }
)

DEFAULT_INPUTS = {
    "employment": Path(
        r"E:\VideoCaptioner-screen-subtitle\work-dir\无论怎么衡量，就业市场都很疲软"
    )
    / "manual-draft-safety-backup"
    / "employment-manual-draft-latest-20260821-183815.json",
    "dreamcore": Path(
        r"D:\经济学人\2026-08-15\其他媒体\中式梦核：千禧一代的怀旧密码"
    ),
    "bad_animation": Path(
        r"D:\经济学人\2026-08-15\其他媒体\烂到爆红：一部动画电影的逆袭"
    ),
}
DEFAULT_INPUTS["dreamcore"] = (
    DEFAULT_INPUTS["dreamcore"]
    / "中式梦核：千禧一代的怀旧密码-处理结果"
    / "人工终稿字幕包"
    / "generations"
    / "20260820T061937522986-12eebd05"
    / "人工终稿字幕-edits.json"
)
DEFAULT_INPUTS["bad_animation"] = (
    DEFAULT_INPUTS["bad_animation"]
    / "烂到爆红：一部动画的逆袭-处理结果"
    / "人工终稿字幕包"
    / "generations"
    / "20260818T065438686900-50c82531"
    / "人工终稿字幕-edits.json"
)

# §28.1 registered gates. Keep these values in code so a run cannot silently
# redefine its own pass condition.
REGISTERED_GATES = {
    "employment": {
        "parents": 237,
        "gt": 28,
        "e_numerator": 28,
        "confirm": 15,
        "chinese_steps": 61,
        "history_steps": 101,
        "signal_parents": 110,
        "signal_gt": 24,
    },
    "dreamcore": {
        "parents": 201,
        "gt": 60,
        "e_numerator": 60,
        "confirm": 6,
        "chinese_steps": 149,
        "history_steps": 201,
        "signal_parents": 90,
        "signal_gt": 43,
    },
    "bad_animation": {
        "parents": 173,
        "gt": 30,
        "e_numerator": 30,
        "confirm": 7,
        "chinese_steps": 75,
        "history_steps": 115,
        "signal_parents": 79,
        "signal_gt": 24,
    },
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _parent_ids(record: Mapping[str, Any]) -> set[str]:
    """Extract Sxxxx parents from all history identity fields."""

    result: set[str] = set()
    for field in ID_FIELDS:
        for value in _as_list(record.get(field)):
            if not isinstance(value, str):
                continue
            match = PARENT_RE.match(value.strip())
            if match:
                result.add(match.group(1))
    return result


def _root(document: Mapping[str, Any]) -> Mapping[str, Any]:
    state = document.get("state")
    return state if isinstance(state, Mapping) else document


def _load_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"registered input does not exist: {path}")
    with path.open("r", encoding="utf-8-sig") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"registered input is not a JSON object: {path}")
    return document


def _history(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in _as_list(document.get("history")) if isinstance(item, Mapping)]


def _page_rows(root: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        item
        for item in _as_list(root.get("display_page_edits"))
        if isinstance(item, Mapping) and isinstance(item.get("parent_subtitle_id"), str)
    ]


def _nonempty_override(value: Any) -> bool:
    # An empty list is a user confirmation, not a boundary edit. A scalar or
    # non-empty mapping is still evidence of a non-empty override.
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, str)):
        return len(value) > 0
    return True


def _registered_metrics(label: str, path: Path, signal_threshold: int = 58) -> dict[str, Any]:
    document = _load_document(path)
    root = _root(document)
    pages = _page_rows(root)
    active_parents = {
        str(row["parent_subtitle_id"])
        for row in pages
        if PARENT_RE.match(str(row["parent_subtitle_id"]))
    }
    if not active_parents:
        raise ValueError(f"no active display-page parents found in {path}")

    layout_ids: set[str] = set()
    chinese_ids: set[str] = set()
    english_ids: set[str] = set()
    confirm_ids: set[str] = set()
    history = _history(document)
    chinese_steps = 0

    for item in history:
        operation = str(item.get("operation") or "")
        ids = _parent_ids(item)
        if operation in LAYOUT_OPERATIONS:
            layout_ids.update(ids)
        elif operation == "edit_display_page_chinese":
            chinese_steps += 1
            chinese_ids.update(ids)
        elif operation == "edit_english_surface":
            english_ids.update(ids)
        elif operation == "confirm_display_page_boundary":
            confirm_ids.update(ids)

    overrides = root.get("display_page_boundary_overrides")
    if isinstance(overrides, Mapping):
        for parent_id, value in overrides.items():
            match = PARENT_RE.match(str(parent_id))
            if not match:
                continue
            normalized = match.group(1)
            if _nonempty_override(value):
                layout_ids.add(normalized)
            else:
                confirm_ids.add(normalized)

    # A parent that was merged away, hidden, suppressed, or trimmed out of the
    # final page model is not in the user-facing GT denominator.
    layout_ids &= active_parents
    chinese_ids &= active_parents
    english_ids &= active_parents
    confirm_ids &= active_parents
    gt_ids = (layout_ids | chinese_ids | english_ids) & active_parents

    signal_ids = {
        str(row["parent_subtitle_id"])
        for row in pages
        if len(str(row.get("english") or "")) >= signal_threshold
    }
    signal_ids &= active_parents
    signal_gt_ids = signal_ids & gt_ids

    source_hash = document.get("source_word_ledger_hash")
    if not source_hash and isinstance(root, Mapping):
        source_hash = root.get("source_word_ledger_hash")

    gate = REGISTERED_GATES.get(label)
    raw = {
        "label": label,
        "path": str(path),
        "path_exists": path.is_file(),
        "schema_version": document.get("schema_version"),
        "kind": document.get("kind"),
        "source_word_ledger_hash": source_hash,
        "parents": len(active_parents),
        "gt": len(gt_ids),
        "layout_gt": len(layout_ids),
        "chinese_gt": len(chinese_ids),
        "english_gt": len(english_ids),
        "e_numerator": len(gt_ids),
        "e_denominator": len(active_parents),
        "e_percent": round(100 * len(gt_ids) / len(active_parents), 1),
        "confirm": len(confirm_ids),
        "history_steps": len(history),
        "chinese_steps": chinese_steps,
        "chinese_step_ratio": f"{chinese_steps}/{len(history)}",
        "signal": {
            "definition": f"any active page English length >= {signal_threshold} characters",
            "parents": len(signal_ids),
            "gt": len(signal_gt_ids),
            "marked_percent": round(100 * len(signal_ids) / len(active_parents), 1),
            "recall_percent": round(100 * len(signal_gt_ids) / len(gt_ids), 1),
        },
        "gt_ids": sorted(gt_ids),
        "confirm_ids": sorted(confirm_ids),
    }
    if gate is not None:
        checks = {
            "parents": raw["parents"] == gate["parents"],
            "gt": raw["gt"] == gate["gt"],
            "e_numerator": raw["e_numerator"] == gate["e_numerator"],
            "confirm": raw["confirm"] == gate["confirm"],
            "chinese_step_ratio": (
                raw["chinese_steps"] == gate["chinese_steps"]
                and raw["history_steps"] == gate["history_steps"]
            ),
            "signal_parents": raw["signal"]["parents"] == gate["signal_parents"],
            "signal_gt": raw["signal"]["gt"] == gate["signal_gt"],
        }
        raw["gate"] = {
            "registered": gate,
            "checks": checks,
            "passed": all(checks.values()),
        }
    return raw


def _parse_marked_argument(values: Iterable[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--marked must use label=S0001,S0002: {value}")
        label, raw_ids = value.split("=", 1)
        ids = {
            match.group(1)
            for raw_id in raw_ids.split(",")
            if (match := PARENT_RE.match(raw_id.strip()))
        }
        result.setdefault(label.strip(), set()).update(ids)
    return result


def _load_marked_file(path: Path) -> dict[str, set[str]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("marked file must be an object keyed by run label")
    result: dict[str, set[str]] = {}
    for label, values in payload.items():
        if isinstance(values, Mapping):
            values = values.get("parent_ids", values.get("subtitle_ids", []))
        result[str(label)] = {
            match.group(1)
            for value in _as_list(values)
            if isinstance(value, str) and (match := PARENT_RE.match(value.strip()))
        }
    return result


def _mark_metrics(
    metrics: Mapping[str, Any], marked: set[str]
) -> dict[str, Any]:
    active = set(metrics["gt_ids"]) | {
        str(parent_id)
        for parent_id in marked
    }
    # The denominator is the registered active-parent set, not the supplied
    # mark count. Reconstruct it from the signal rate only is lossy, so the
    # caller supplies active parents through the hidden helper below.
    selected = marked & metrics["_active_parent_ids"]
    hit = selected & set(metrics["gt_ids"])
    return {
        "marked_parents": len(selected),
        "marked_percent": round(100 * len(selected) / len(metrics["_active_parent_ids"]), 1),
        "gt_hit": len(hit),
        "recall_percent": round(100 * len(hit) / len(metrics["gt_ids"]), 1)
        if metrics["gt_ids"]
        else 0.0,
        "missed_gt_ids": sorted(set(metrics["gt_ids"]) - hit),
    }


def _public_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    public = dict(metrics)
    public.pop("_active_parent_ids", None)
    return public


def _build_report(results: Mapping[str, Any]) -> str:
    lines = [
        "# §28 P0 objective harness",
        "",
        "只读测量；门禁值登记在脚本内，未从实测值反推或修改。",
        "",
        "| 集合 | P | GT | E | CONFIRM | 中文步数 | 字符>=58标出率/召回率 | 门禁 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for label, item in results["runs"].items():
        signal = item["signal"]
        gate = item.get("gate", {})
        lines.append(
            f"| {label} | {item['parents']} | {item['gt']} | "
            f"{item['e_percent']:.1f}% | {item['confirm']} | "
            f"{item['chinese_step_ratio']} | "
            f"{signal['marked_percent']:.1f}% / {signal['recall_percent']:.1f}% | "
            f"{'通过' if gate.get('passed') else '未通过'} |"
        )
    combined = results["combined"]
    combined_signal = combined["signal"]
    lines.extend(
        [
            "",
            f"合并：P={combined['parents']}，GT={combined['gt']}，"
            f"E={combined['e_percent']:.1f}%；字符>=58 标出率 "
            f"{combined_signal['marked_percent']:.1f}%、召回率 "
            f"{combined_signal['recall_percent']:.1f}%。",
            "",
            "这三个数衡量的是人工改动量、读取工作量和清单召回，不等价于字幕语言质量。",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--employment", type=Path, default=DEFAULT_INPUTS["employment"])
    parser.add_argument("--dreamcore", type=Path, default=DEFAULT_INPUTS["dreamcore"])
    parser.add_argument("--bad-animation", type=Path, default=DEFAULT_INPUTS["bad_animation"])
    parser.add_argument("--signal-threshold", type=int, default=58)
    parser.add_argument(
        "--marked",
        action="append",
        default=[],
        metavar="LABEL=S0001,S0002",
        help="optional mark set for the generic mark recall entry point",
    )
    parser.add_argument("--marked-file", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    args = parser.parse_args(argv)

    paths = {
        "employment": args.employment,
        "dreamcore": args.dreamcore,
        "bad_animation": args.bad_animation,
    }
    runs: dict[str, dict[str, Any]] = {}
    for label, path in paths.items():
        metrics = _registered_metrics(label, path, args.signal_threshold)
        # Keep the active set private for the optional generic mark entry point.
        metrics["_active_parent_ids"] = {
            str(row["parent_subtitle_id"])
            for row in _page_rows(_root(_load_document(path)))
        }
        runs[label] = metrics

    combined = {
        "parents": sum(item["parents"] for item in runs.values()),
        "gt": sum(item["gt"] for item in runs.values()),
        "e_numerator": sum(item["e_numerator"] for item in runs.values()),
        "e_denominator": sum(item["e_denominator"] for item in runs.values()),
        "confirm": sum(item["confirm"] for item in runs.values()),
        "signal": {
            "parents": sum(item["signal"]["parents"] for item in runs.values()),
            "gt": sum(item["signal"]["gt"] for item in runs.values()),
        },
    }
    combined["e_percent"] = round(
        100 * combined["e_numerator"] / combined["e_denominator"], 1
    )
    combined["signal"]["marked_percent"] = round(
        100 * combined["signal"]["parents"] / combined["parents"], 1
    )
    combined["signal"]["recall_percent"] = round(
        100 * combined["signal"]["gt"] / combined["gt"], 1
    )

    marked = _parse_marked_argument(args.marked)
    if args.marked_file:
        for label, values in _load_marked_file(args.marked_file).items():
            marked.setdefault(label, set()).update(values)
    mark_results: dict[str, Any] = {}
    for label, values in marked.items():
        if label not in runs:
            raise ValueError(f"unknown run label in mark set: {label}")
        mark_results[label] = _mark_metrics(runs[label], values)

    public_runs = {label: _public_metrics(item) for label, item in runs.items()}
    payload = {
        "schema": "objective-harness-p0-v1",
        "signal_threshold": args.signal_threshold,
        "registered_gates": REGISTERED_GATES,
        "runs": public_runs,
        "combined": combined,
        "marks": mark_results,
        "passed": all(item.get("gate", {}).get("passed", False) for item in runs.values()),
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    print(encoded, end="")
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(encoded, encoding="utf-8")
    if args.output_markdown:
        args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.output_markdown.write_text(_build_report(payload), encoding="utf-8")
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"P0 measurement failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
