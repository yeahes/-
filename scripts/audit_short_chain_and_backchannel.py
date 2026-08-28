"""Read-only measurement for short-chain review signals and backchannels.

This script compares one immutable stable run with its manual-final history.
It does not write to the run, its caches, or its manual-final package.  The
short-chain detector is deliberately an experiment: it reports recall and
reading burden, but it is not wired into the production review ledger.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")
MARKER_RE = re.compile(
    r"\b(right|yeah|yes|mm[- ]?hmm|you know|i mean|wow|okay|exactly|sure|ah|oh|wait|well)\b",
    re.IGNORECASE,
)

SUBORDINATORS = {
    "although",
    "as",
    "after",
    "before",
    "because",
    "if",
    "since",
    "though",
    "unless",
    "until",
    "when",
    "whereas",
    "whether",
    "while",
}
RELATIVE_WORDS = {"that", "which", "where", "who", "whom", "whose"}
PREPOSITIONS = {
    "against",
    "among",
    "around",
    "at",
    "between",
    "by",
    "despite",
    "during",
    "for",
    "from",
    "in",
    "into",
    "like",
    "of",
    "on",
    "onto",
    "over",
    "through",
    "to",
    "toward",
    "towards",
    "under",
    "upon",
    "via",
    "with",
    "without",
}
START_PHRASES = {
    ("instead", "of"),
    ("just", "to"),
    ("the", "second"),
    ("who", "are"),
    ("which", "is"),
}

MARKER_ZH = {
    "right": ("对", "没错", "是的", "确实", "嗯"),
    "yeah": ("对", "没错", "是的", "确实", "嗯"),
    "yes": ("对", "没错", "是的", "确实", "嗯"),
    "mm-hmm": ("嗯", "嗯哼", "对"),
    "you know": ("你知道", "你也知道", "你看"),
    "i mean": ("我的意思", "我是说"),
    "wow": ("哇", "天啊"),
    "okay": ("好", "好的", "好吧", "行", "嗯"),
    "exactly": ("没错", "正是", "确实"),
    "sure": ("当然", "好的", "可以"),
    "ah": ("啊", "哦"),
    "oh": ("哦", "啊"),
    "wait": ("等等",),
    "well": ("好", "那么", "嗯"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--manual-final", required=True, type=Path)
    parser.add_argument("--max-duration-ms", type=int, default=3500)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def artifact_dir(run: Path) -> Path:
    run = run.resolve(strict=True)
    if (run / "word-ledger.json").is_file():
        return run
    candidates = [child for child in run.iterdir() if child.is_dir() and child.name.endswith("-artifacts")]
    if len(candidates) != 1:
        raise ValueError(f"expected one *-artifacts directory below {run}, found {len(candidates)}")
    return candidates[0]


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def signal_reasons(text: str) -> list[str]:
    words = tokens(text)
    if not words:
        return []
    reasons: list[str] = []
    first = words[0]
    last = words[-1]
    if first in SUBORDINATORS | RELATIVE_WORDS | PREPOSITIONS:
        reasons.append(f"start:{first}")
    if last in SUBORDINATORS | RELATIVE_WORDS | PREPOSITIONS:
        reasons.append(f"end:{last}")
    prefix = tuple(words[:2])
    if prefix in START_PHRASES:
        reasons.append(f"start:{' '.join(prefix)}")
    suffix = tuple(words[-2:])
    if suffix in START_PHRASES:
        reasons.append(f"end:{' '.join(suffix)}")
    return reasons


def history_parent_ids(history: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for item in history:
        ids = item.get("affected_parent_ids")
        if not ids:
            parent_id = item.get("parent_subtitle_id")
            ids = [parent_id] if parent_id else list((item.get("before_parent_states") or {}).keys())
        result.update(str(value) for value in ids if value)
    return result


def marker_names(text: str) -> list[str]:
    return [match.group(1).lower().replace(" ", " ") for match in MARKER_RE.finditer(text)]


def marker_evidence(text: str, marker: str) -> bool:
    normalized = marker.lower().replace(" ", " ")
    return any(phrase in text for phrase in MARKER_ZH.get(normalized, ()))


def main() -> int:
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    artifact = artifact_dir(args.run)
    spans = read_json(artifact / "subtitle-spans.json")
    ledger = read_json(artifact / "word-ledger.json")["words"]
    parent_chinese = read_json(artifact / "authoritative-parent-chinese.json")["records"]
    review_ledger = read_json(artifact / "editor-review-ledger.json")
    manual = read_json(args.manual_final.resolve(strict=True))

    by_id = {str(row["subtitle_id"]): row for row in spans}
    auto_zh = {str(row["subtitle_id"]): str(row.get("chinese") or "") for row in parent_chinese}
    manual_cues = {str(row["cue_id"]): row for row in manual.get("cues") or []}
    ground_truth = history_parent_ids(manual.get("history") or [])
    marked = {
        str(subtitle_id)
        for item in review_ledger.get("items") or []
        for subtitle_id in item.get("subtitle_ids") or []
    }

    signal_rows: list[dict[str, Any]] = []
    flagged: set[str] = set()
    for index, span in enumerate(spans):
        subtitle_id = str(span["subtitle_id"])
        start = int(ledger[int(span["word_start"])]["start_ms"])
        end = int(ledger[int(span["word_end"])]["end_ms"])
        duration = end - start
        reasons = signal_reasons(str(span.get("original") or "")) if duration < args.max_duration_ms else []
        if not reasons:
            continue
        neighbors = []
        for neighbor_index in (index - 1, index, index + 1):
            if 0 <= neighbor_index < len(spans):
                neighbor_id = str(spans[neighbor_index]["subtitle_id"])
                flagged.add(neighbor_id)
                neighbors.append(neighbor_id)
        signal_rows.append(
            {
                "subtitle_id": subtitle_id,
                "duration_ms": duration,
                "reasons": reasons,
                "flagged_group": neighbors,
                "english": span.get("original", ""),
            }
        )

    marker_rows: list[dict[str, Any]] = []
    for subtitle_id in sorted(ground_truth, key=lambda value: int(value[1:])):
        span = by_id.get(subtitle_id)
        cue = manual_cues.get(subtitle_id)
        if not span or not cue:
            continue
        markers = marker_names(str(span.get("original") or ""))
        if not markers:
            continue
        auto_text = auto_zh.get(subtitle_id, "")
        final_text = str(cue.get("translated_subtitle") or "")
        restored = [marker for marker in markers if marker_evidence(final_text, marker) and not marker_evidence(auto_text, marker)]
        removed = [marker for marker in markers if marker_evidence(auto_text, marker) and not marker_evidence(final_text, marker)]
        marker_rows.append(
            {
                "subtitle_id": subtitle_id,
                "markers": markers,
                "auto_marker_evidence": {marker: marker_evidence(auto_text, marker) for marker in markers},
                "manual_marker_evidence": {marker: marker_evidence(final_text, marker) for marker in markers},
                "manual_restored_evidence": restored,
                "manual_removed_evidence": removed,
                "auto_chinese": auto_text,
                "manual_chinese": final_text,
            }
        )

    hit = sorted(ground_truth & flagged, key=lambda value: int(value[1:]))
    missed = sorted(ground_truth - flagged, key=lambda value: int(value[1:]))
    marker_parent_count = len(marker_rows)
    restored_count = sum(bool(row["manual_restored_evidence"]) for row in marker_rows)
    removed_count = sum(bool(row["manual_removed_evidence"]) for row in marker_rows)
    result = {
        "read_only": True,
        "run": str(args.run.resolve()),
        "artifact_dir": str(artifact),
        "manual_final": str(args.manual_final.resolve()),
        "ground_truth": {
            "user_modified_parent_count": len(ground_truth),
            "editor_marked_parent_count": len(marked),
            "editor_mark_hit_count": len(ground_truth & marked),
            "editor_mark_missed_ids": sorted(ground_truth - marked, key=lambda value: int(value[1:])),
        },
        "short_chain_signal": {
            "max_duration_ms": args.max_duration_ms,
            "signal_cue_count": len(signal_rows),
            "flagged_parent_count": len(flagged),
            "flagged_parent_read_rate": len(flagged) / len(spans) if spans else 0.0,
            "hit_count": len(hit),
            "recall": len(hit) / len(ground_truth) if ground_truth else 0.0,
            "false_flagged_parent_count": len(flagged - ground_truth),
            "hit_ids": hit,
            "missed_ids": missed,
            "signal_rows": signal_rows,
        },
        "backchannel_prompt_evidence": {
            "ground_truth_modified_parents_with_markers": marker_parent_count,
            "manual_added_marker_evidence_parent_count": restored_count,
            "manual_removed_marker_evidence_parent_count": removed_count,
            "rows": marker_rows,
            "interpretation": "Heuristic evidence only; no provider request or production prompt change was made.",
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
