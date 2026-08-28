"""Audit historical visual-only subtitle splits from stable boundary snapshots.

This reads one completed run's immutable artifacts.  It never contacts an LLM
and never modifies subtitle output.  The report separates visual time-boundary
creation from renderer-only line wrapping so a review can name the correct
owner of each defect.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


LEADING_DEPENDENTS = frozenset(
    {
        "although", "as", "because", "before", "if", "once", "since", "though",
        "unless", "until", "when", "whereas", "while", "whether", "which", "who",
        "whose", "whom",
    }
)
LEADING_PREPOSITIONS = frozenset(
    {
        "about", "after", "around", "at", "before", "between", "by", "for", "from",
        "in", "into", "of", "on", "over", "through", "to", "under", "with", "without",
    }
)
FINITE_AUXILIARIES = frozenset(
    {
        "am", "are", "be", "been", "being", "can", "could", "did", "do", "does",
        "had", "has", "have", "is", "may", "might", "must", "shall", "should", "was",
        "were", "will", "would",
    }
)


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?", text)]


def _has_finite_predicate(text: str) -> bool:
    tokens = _tokens(text)
    if any(token in FINITE_AUXILIARIES for token in tokens):
        return True
    try:
        import spacy  # type: ignore

        nlp = _has_finite_predicate.nlp
    except AttributeError:
        try:
            nlp = spacy.load("en_core_web_sm", disable=["ner", "textcat"])
        except Exception:
            nlp = False
        _has_finite_predicate.nlp = nlp
    except Exception:
        nlp = False
    if not nlp:
        return False
    return any(
        token.pos_ in {"VERB", "AUX"}
        and token.tag_ not in {"VB", "VBG", "VBN"}
        for token in nlp(text)
    )


def _display_unit_reasons(text: str) -> list[str]:
    words = _tokens(text)
    if not words:
        return ["empty"]
    reasons: list[str] = []
    first = words[0]
    if first in LEADING_DEPENDENTS:
        reasons.append("dependent_clause_lead")
    if first in LEADING_PREPOSITIONS:
        reasons.append("preposition_or_infinitive_lead")
    if not _has_finite_predicate(text):
        terminal_response = bool(re.search(r"[.!?]\s*$", text)) and len(words) <= 4
        if not terminal_response:
            reasons.append("no_finite_predicate")
    if re.search(r"[,;:]\s*$", text) and not _has_finite_predicate(text):
        reasons.append("open_phrase_punctuation")
    return reasons


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def audit(artifact_dir: Path) -> dict[str, Any]:
    snapshots = _read_json(artifact_dir / "stable-boundary-snapshots.json")
    ledger = _read_json(artifact_dir / "word-ledger.json")
    timeline = _read_json(artifact_dir / "final-cue-timeline.json")
    words = ledger.get("words", []) if isinstance(ledger, dict) else []
    records: list[dict[str, Any]] = []
    for repair in snapshots.get("pre_id_boundary_repairs", []):
        if not (
            repair.get("repaired_by") == "_apply_visual_reading_budget"
            and repair.get("repair_succeeded")
            and repair.get("repair_reason")
            in {
                "visual_reading_budget_split",
                "visual_temporal_display_unit_split",
            }
        ):
            continue
        before = list(repair.get("old_items") or [])
        after = list(repair.get("new_items") or [])
        if len(before) != 1 or len(after) != 2:
            continue
        left, right = after
        left_text = str(left.get("original") or "")
        right_text = str(right.get("original") or "")
        cut = int(left.get("word_end"))
        next_index = cut + 1
        pause_ms = None
        if 0 <= cut < len(words) and 0 <= next_index < len(words):
            pause_ms = int(words[next_index]["start_ms"]) - int(words[cut]["end_ms"])
        left_reasons = _display_unit_reasons(left_text)
        right_reasons = _display_unit_reasons(right_text)
        if left_reasons or right_reasons:
            classification = "invalid_temporal_split"
        elif pause_ms is None or pause_ms < 450:
            classification = "unnecessary_visual_boundary"
        else:
            classification = "possibly_valid_semantic_boundary"
        records.append(
            {
                "word_range": [int(before[0]["word_start"]), int(before[0]["word_end"])],
                "cut_word_index": cut,
                "pause_ms": pause_ms,
                "before": str(before[0].get("original") or ""),
                "left": left_text,
                "right": right_text,
                "left_reasons": left_reasons,
                "right_reasons": right_reasons,
                "classification": classification,
            }
        )
    counts = Counter(record["classification"] for record in records)
    return {
        "artifact_dir": str(artifact_dir),
        "final_cue_count": len(timeline.get("records", [])),
        "visual_split_count": len(records),
        "projected_cue_count_without_visual_splits": len(timeline.get("records", [])) - len(records),
        "classification_counts": dict(sorted(counts.items())),
        "records": records,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Visual Temporal Boundary Audit",
        "",
        f"- Artifact directory: `{report['artifact_dir']}`",
        f"- Final cues in this run: `{report['final_cue_count']}`",
        f"- Visual time boundaries created: `{report['visual_split_count']}`",
        f"- Projected cues without visual-only splits: `{report['projected_cue_count_without_visual_splits']}`",
        "- Classification counts: " + ", ".join(
            f"`{name}={count}`" for name, count in report["classification_counts"].items()
        ),
        "",
        "The classification is local and reproducible: a temporal split is invalid when either side is an incomplete display unit; an otherwise complete pair without a 450ms pause is unnecessary rather than a required new subtitle screen.",
        "",
        "| # | Word range | Pause | Classification | Before | New temporal boundary |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, record in enumerate(report["records"], start=1):
        boundary = f"{record['left']} | {record['right']}"
        reason = ", ".join(record["left_reasons"] + record["right_reasons"])
        classification = record["classification"]
        if reason:
            classification = f"{classification}: {reason}"
        lines.append(
            "| {index} | {range} | {pause}ms | {classification} | {before} | {boundary} |".format(
                index=index,
                range="-".join(str(value) for value in record["word_range"]),
                pause=record["pause_ms"] if record["pause_ms"] is not None else "n/a",
                classification=classification.replace("|", "/"),
                before=record["before"].replace("|", "/"),
                boundary=boundary.replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report = audit(args.artifact_dir)
    output_dir = args.output_dir or args.artifact_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "visual-temporal-boundary-audit.json"
    markdown_path = output_dir / "visual-temporal-boundary-audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(f"visual splits={report['visual_split_count']}")
    print(" ".join(f"{key}={value}" for key, value in report["classification_counts"].items()))
    print(json_path)
    print(markdown_path)


if __name__ == "__main__":
    main()
