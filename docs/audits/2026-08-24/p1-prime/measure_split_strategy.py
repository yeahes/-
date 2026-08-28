"""Offline P1' experiment for deterministic Chinese page splitting.

This script compares the shipped strict splitter with narrowly scoped
counterfactuals.  It reads the three registered manual-final snapshots only;
it never writes to a run directory and never changes production code.

The benchmark intentionally keeps the external audit's definition: the
English page weight is the number of rendered English words, and a hit means
that every compacted Chinese page matches the recorded final page exactly.
The separate ``production_weights`` result exposes the current call-site
contract, which derives weights from inclusive frozen word spans.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.core.subtitle_processor.chinese_token_boundaries import (  # noqa: E402
    chinese_token_boundaries,
)
from app.core.utils import podcast_learning_video  # noqa: E402


def _load_registered_inputs() -> dict[str, dict[str, Any]]:
    """Load only the final page snapshots needed by this audit."""
    objective_path = (
        ROOT
        / "docs"
        / "audits"
        / "2026-08-24"
        / "objective-harness"
        / "measure_objective.py"
    )
    spec = importlib.util.spec_from_file_location(
        "objective_harness_measurement", objective_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load registered inputs: {objective_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded: dict[str, dict[str, Any]] = {}
    for label, path in module.DEFAULT_INPUTS.items():
        document = module._load_document(path)
        root = module._root(document)
        pages = module._page_rows(root)
        edited_parent_ids = {
            parent_id
            for item in module._history(document)
            if str(item.get("operation") or "") == "edit_display_page_chinese"
            for parent_id in module._parent_ids(item)
        }
        loaded[label] = {
            "pages": pages,
            "edited_parent_ids": edited_parent_ids,
        }
    return loaded


PUNCTUATION = frozenset("，。；：！？、")
COMPACT_RE = re.compile(r"\s+")


def compact(value: Any) -> str:
    return COMPACT_RE.sub("", str(value or ""))


def _safe_boundary(
    text: str,
    value: int,
    token_boundaries: Mapping[int, tuple[int, int]] | None,
    *,
    strict: bool = True,
) -> bool:
    if value <= 0 or value >= len(text):
        return False
    previous = text[value - 1]
    following = text[value]
    if following in PUNCTUATION:
        return False
    if previous in PUNCTUATION:
        return True
    if previous.isascii() and following.isascii() and (
        previous.isalnum() or following.isalnum()
    ):
        return False
    if not (
        "\u4e00" <= previous <= "\u9fff"
        and "\u4e00" <= following <= "\u9fff"
    ):
        return True
    context = token_boundaries.get(value) if token_boundaries else None
    if context is not None and min(context) >= 2:
        return True
    prefix = text[value : min(len(text), value + 2)]
    if prefix in podcast_learning_video.CHINESE_VISUAL_SAFE_PREFIXES:
        return True
    return not strict


def split_reference(
    text: str,
    page_count: int,
    weights: Sequence[int],
    *,
    window: int = 8,
    punctuation_first: bool = False,
    strict: bool = True,
) -> list[str] | None:
    """Reference implementation of the current splitter plus one variant."""
    compact_text = compact(text)
    page_count = max(1, min(int(page_count or 1), len(compact_text) or 1))
    if page_count == 1:
        return [compact_text] if compact_text else []
    normalized_weights = [int(value) for value in weights]
    if len(normalized_weights) != page_count or any(
        value <= 0 for value in normalized_weights
    ):
        normalized_weights = [1] * page_count
    total_weight = sum(normalized_weights)
    token_boundaries = chinese_token_boundaries(compact_text)
    boundaries = [0]
    for page in range(1, page_count):
        target = round(
            len(compact_text)
            * sum(normalized_weights[:page])
            / total_weight
        )
        minimum = boundaries[-1] + 1
        maximum = len(compact_text) - (page_count - page)
        nearby = [
            value
            for value in range(
                max(minimum, target - window),
                min(maximum, target + window) + 1,
            )
            if _safe_boundary(
                compact_text,
                value,
                token_boundaries,
                strict=strict,
            )
        ]
        if not nearby:
            if strict:
                return None
            nearby = [target]
        if punctuation_first:
            punctuation = [
                value
                for value in nearby
                if compact_text[value - 1] in PUNCTUATION
            ]
            candidates = punctuation or nearby
        else:
            candidates = nearby
        boundaries.append(
            min(
                candidates,
                key=lambda value: (
                    abs(value - target),
                    0 if compact_text[value - 1] in PUNCTUATION else 1,
                    -value,
                ),
            )
        )
    boundaries.append(len(compact_text))
    return [
        compact_text[start:end]
        for start, end in zip(boundaries, boundaries[1:])
    ]


def _load_cases() -> dict[str, list[dict[str, Any]]]:
    cases: dict[str, list[dict[str, Any]]] = {}
    for label, document in _load_registered_inputs().items():
        pages_by_parent: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for page in document["pages"]:
            pages_by_parent[str(page["parent_subtitle_id"])].append(page)
        label_cases: list[dict[str, Any]] = []
        for parent_id, pages in pages_by_parent.items():
            if len(pages) <= 1 or any(not compact(page.get("chinese")) for page in pages):
                continue
            label_cases.append(
                {
                    "parent_subtitle_id": parent_id,
                    "text": "".join(str(page.get("chinese") or "") for page in pages),
                    "expected": [compact(page.get("chinese")) for page in pages],
                    "english_weights": [
                        len(str(page.get("english") or "").split())
                        for page in pages
                    ],
                    "production_weights": [
                        int(page.get("word_end", -1))
                        - int(page.get("word_start", -1))
                        + 1
                        for page in pages
                    ],
                    "user_changed": bool(document["edited_parent_ids"].intersection({parent_id})),
                }
            )
        cases[label] = label_cases
    return cases


def _score(
    cases: Sequence[Mapping[str, Any]],
    *,
    weights_key: str,
    window: int,
    punctuation_first: bool,
) -> dict[str, Any]:
    hits: list[str] = []
    edited_hits: list[str] = []
    edited_total = 0
    for case in cases:
        if case["user_changed"]:
            edited_total += 1
        result = split_reference(
            str(case["text"]),
            len(case["expected"]),
            case[weights_key],
            window=window,
            punctuation_first=punctuation_first,
        )
        if result == case["expected"]:
            parent_id = str(case["parent_subtitle_id"])
            hits.append(parent_id)
            if case["user_changed"]:
                edited_hits.append(parent_id)
    return {
        "cases": len(cases),
        "hits": len(hits),
        "rate_percent": round(100 * len(hits) / len(cases), 1) if cases else 0.0,
        "edited_cases": edited_total,
        "edited_hits": len(edited_hits),
        "edited_rate_percent": round(100 * len(edited_hits) / edited_total, 1)
        if edited_total
        else 0.0,
        "hit_ids": hits,
    }


def _score_production(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Score the currently imported production splitter, not a copy of it."""
    hits: list[str] = []
    edited_hits: list[str] = []
    edited_total = 0
    none_count = 0
    empty_page_count = 0
    for case in cases:
        if case["user_changed"]:
            edited_total += 1
        result = podcast_learning_video._strict_split_chinese_visual_pages(
            str(case["text"]),
            len(case["expected"]),
            case["production_weights"],
            strict=True,
        )
        if result is None:
            none_count += 1
        else:
            empty_page_count += sum(not str(page) for page in result)
        if result == case["expected"]:
            parent_id = str(case["parent_subtitle_id"])
            hits.append(parent_id)
            if case["user_changed"]:
                edited_hits.append(parent_id)
    return {
        "cases": len(cases),
        "hits": len(hits),
        "rate_percent": round(100 * len(hits) / len(cases), 1) if cases else 0.0,
        "edited_cases": edited_total,
        "edited_hits": len(edited_hits),
        "edited_rate_percent": round(100 * len(edited_hits) / edited_total, 1)
        if edited_total
        else 0.0,
        "none_count": none_count,
        "empty_page_count": empty_page_count,
        "hit_ids": hits,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("p1-prime-results.json"),
    )
    args = parser.parse_args()
    cases = _load_cases()
    payload: dict[str, Any] = {
        "benchmark_definition": {
            "source": "registered manual-final snapshots",
            "match": "all compacted Chinese pages exactly equal recorded final pages",
            "english_weights": "number of English words in each recorded page",
            "production_weights": "inclusive frozen word span used by production call sites",
        },
        "baseline": {},
        "counterfactuals": {},
    }
    for label, label_cases in cases.items():
        payload["baseline"][label] = {
            "english_weights": _score(
                label_cases,
                weights_key="english_weights",
                window=8,
                punctuation_first=False,
            ),
            "production_weights": _score(
                label_cases,
                weights_key="production_weights",
                window=8,
                punctuation_first=False,
            ),
        }
    for window in (8, 12, 16, 24, 32):
        for punctuation_first in (False, True):
            key = f"window_{window}_{'punctuation_first' if punctuation_first else 'current_score'}"
            payload["counterfactuals"][key] = {
                label: _score(
                    label_cases,
                    weights_key="production_weights",
                    window=window,
                    punctuation_first=punctuation_first,
                )
                for label, label_cases in cases.items()
            }
    payload["production_function"] = {
        label: _score_production(label_cases)
        for label, label_cases in cases.items()
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
