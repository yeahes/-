#!/usr/bin/env python3
"""Read-only measurement of cross-parent semantic review signals.

The production ledger is intentionally not changed here.  This experiment
checks whether a spaCy dependency crossing between two frozen English parent
cues explains the manual-final changes in one immutable run, and reports the
cost of marking only the boundary pair versus a small neighbouring group.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable


NON_COORD_DEPENDENCIES = {
    "advcl",
    "acl",
    "attr",
    "ccomp",
    "csubj",
    "dobj",
    "npadvmod",
    "obl",
    "oprd",
    "pobj",
    "prep",
    "relcl",
    "xcomp",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--manual-final", required=True, type=Path)
    parser.add_argument("--max-pause-ms", type=int, default=700)
    parser.add_argument("--max-parent-duration-ms", type=int, default=3500)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def artifact_dir(run: Path) -> Path:
    run = run.resolve(strict=True)
    if (run / "word-ledger.json").is_file():
        return run
    candidates = [
        child for child in run.iterdir()
        if child.is_dir() and child.name.endswith("-artifacts")
    ]
    if len(candidates) != 1:
        raise ValueError(f"expected one *-artifacts directory below {run}, found {len(candidates)}")
    return candidates[0]


def history_parent_ids(history: Iterable[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for item in history:
        ids = item.get("affected_parent_ids")
        if not ids:
            parent_id = item.get("parent_subtitle_id")
            ids = [parent_id] if parent_id else list(
                (item.get("before_parent_states") or {}).keys()
            )
        result.update(str(value) for value in ids if value)
    return result


def parent_duration_ms(span: dict[str, Any], ledger: list[dict[str, Any]]) -> int:
    start = int(ledger[int(span["word_start"])] ["start_ms"])
    end = int(ledger[int(span["word_end"])] ["end_ms"])
    return max(0, end - start)


def cross_edges(nlp: Any, left_text: str, right_text: str) -> list[dict[str, Any]]:
    document = nlp(f"{left_text} {right_text}")
    boundary = len(left_text)
    edges: list[dict[str, Any]] = []
    for token in document:
        if token.is_punct or token.head == token:
            continue
        token_left = token.idx < boundary
        head_left = token.head.idx < boundary
        if token_left == head_left:
            continue
        edges.append(
            {
                "direction": "left_to_right" if token_left else "right_to_left",
                "dependency": token.dep_,
                "token": token.text,
                "head": token.head.text,
                "token_pos": token.pos_,
                "head_pos": token.head.pos_,
            }
        )
    return edges


def evaluate(
    rows: list[dict[str, Any]],
    ground_truth: set[str],
    existing_marks: set[str],
    *,
    candidate_key: str,
    expand_neighbors: bool,
) -> dict[str, Any]:
    selected = [row for row in rows if row[candidate_key]]
    flagged: set[str] = set()
    for row in selected:
        if expand_neighbors:
            flagged.update(row["neighbour_ids"])
        else:
            flagged.update(row["parent_ids"])
    union = existing_marks | flagged
    hits = flagged & ground_truth
    union_hits = union & ground_truth
    return {
        "candidate_boundary_count": len(selected),
        "flagged_parent_count": len(flagged),
        "flagged_parent_read_rate": len(flagged) / rows[0]["total_parents"] if rows else 0.0,
        "hit_count": len(hits),
        "recall": len(hits) / len(ground_truth) if ground_truth else 0.0,
        "false_flagged_parent_count": len(flagged - ground_truth),
        "flagged_ids": sorted(flagged, key=lambda value: int(value[1:])),
        "missed_ids": sorted(ground_truth - flagged, key=lambda value: int(value[1:])),
        "existing_mark_union_parent_count": len(union),
        "existing_mark_union_hit_count": len(union_hits),
        "existing_mark_union_recall": len(union_hits) / len(ground_truth) if ground_truth else 0.0,
        "existing_mark_union_read_rate": len(union) / rows[0]["total_parents"] if rows else 0.0,
    }


def main() -> int:
    import spacy

    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    artifact = artifact_dir(args.run)
    spans = read_json(artifact / "subtitle-spans.json")
    ledger = read_json(artifact / "word-ledger.json")["words"]
    manual = read_json(args.manual_final.resolve(strict=True))
    review_ledger = read_json(artifact / "editor-review-ledger.json")
    ground_truth = history_parent_ids(manual.get("history") or [])
    existing_marks = {
        str(subtitle_id)
        for item in review_ledger.get("items") or []
        for subtitle_id in item.get("subtitle_ids") or []
    }
    nlp = spacy.load(
        str(Path(__file__).resolve().parents[1] / "runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0"),
        disable=["ner", "textcat"],
    )
    rows: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(spans, spans[1:])):
        left_text = str(left.get("original") or "").strip()
        right_text = str(right.get("original") or "").strip()
        if not left_text or not right_text:
            continue
        pause_ms = int(ledger[int(right["word_start"])] ["start_ms"]) - int(
            ledger[int(left["word_end"])] ["end_ms"]
        )
        left_duration = parent_duration_ms(left, ledger)
        right_duration = parent_duration_ms(right, ledger)
        edges = cross_edges(nlp, left_text, right_text)
        right_attached = [
            edge for edge in edges
            if edge["direction"] == "right_to_left"
            and edge["dependency"] in NON_COORD_DEPENDENCIES
        ]
        candidate = bool(
            right_attached
            and 0 <= pause_ms <= args.max_pause_ms
            and left_duration <= args.max_parent_duration_ms
            and right_duration <= args.max_parent_duration_ms
        )
        conservative_candidate = bool(
            candidate
            and (
                not left_text.rstrip().endswith(",")
                or any(edge["dependency"] == "dobj" for edge in right_attached)
            )
        )
        left_id = str(left["subtitle_id"])
        right_id = str(right["subtitle_id"])
        rows.append(
            {
                "index": index,
                "row_count": len(spans),
                "total_parents": len(spans),
                "parent_ids": [left_id, right_id],
                "neighbour_ids": [
                    str(spans[neighbour_index]["subtitle_id"])
                    for neighbour_index in range(max(0, index - 1), min(len(spans), index + 3))
                ],
                "pause_ms": pause_ms,
                "left_duration_ms": left_duration,
                "right_duration_ms": right_duration,
                "left_english": left_text,
                "right_english": right_text,
                "right_attached_edges": right_attached,
                "candidate": candidate,
                "conservative_candidate": conservative_candidate,
            }
        )

    result = {
        "read_only": True,
        "run": str(args.run.resolve()),
        "artifact_dir": str(artifact),
        "manual_final": str(args.manual_final.resolve()),
        "ground_truth_parent_count": len(ground_truth),
        "existing_mark_parent_count": len(existing_marks),
        "parameters": {
            "max_pause_ms": args.max_pause_ms,
            "max_parent_duration_ms": args.max_parent_duration_ms,
            "dependency_direction": "right_to_left",
            "dependency_filter": sorted(NON_COORD_DEPENDENCIES),
        },
        "right_attached": {
            "direct_boundary_pair": evaluate(
                rows,
                ground_truth,
                existing_marks,
                candidate_key="candidate",
                expand_neighbors=False,
            ),
            "expanded_neighbour_group": evaluate(
                rows,
                ground_truth,
                existing_marks,
                candidate_key="candidate",
                expand_neighbors=True,
            ),
        },
        "conservative": {
            "direct_boundary_pair": evaluate(
                rows,
                ground_truth,
                existing_marks,
                candidate_key="conservative_candidate",
                expand_neighbors=False,
            ),
            "expanded_neighbour_group": evaluate(
                rows,
                ground_truth,
                existing_marks,
                candidate_key="conservative_candidate",
                expand_neighbors=True,
            ),
        },
        "candidate_rows": [row for row in rows if row["candidate"]],
        "conservative_candidate_rows": [
            row for row in rows if row["conservative_candidate"]
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
