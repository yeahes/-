"""Read-only global boundary-scoring experiment for P1'.

This deliberately does not touch the production splitter.  It tests whether
global optimization over the same observable inputs can satisfy the P1' gate.
If it cannot, adding more local window tuning is not a defensible fix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_split_strategy import PUNCTUATION, _load_cases, _safe_boundary, compact
from app.core.subtitle_processor.chinese_token_boundaries import (
    chinese_token_boundaries,
)


def split_global(
    text: str,
    weights: Sequence[int],
    *,
    window: int,
    distance_weight: int,
    punctuation_reward: int,
    token_penalty: int,
) -> list[str] | None:
    compact_text = compact(text)
    page_count = len(weights)
    if page_count <= 1:
        return [compact_text] if compact_text else []
    total_weight = sum(int(value) for value in weights)
    token_boundaries = chinese_token_boundaries(compact_text)
    targets = [
        round(
            len(compact_text)
            * sum(int(value) for value in weights[:page])
            / total_weight
        )
        for page in range(1, page_count)
    ]
    options: list[list[tuple[int, tuple[str, int]]]] = [[(0, ("start", 0))]]
    for index, target in enumerate(targets):
        minimum = 1
        maximum = len(compact_text) - (page_count - index - 1)
        page_options = []
        for value in range(
            max(minimum, target - window),
            min(maximum, target + window) + 1,
        ):
            if not _safe_boundary(compact_text, value, token_boundaries):
                continue
            previous = compact_text[value - 1]
            kind = "punct" if previous in PUNCTUATION else "token"
            page_options.append((value, (kind, 0)))
        options.append(page_options)
    options.append([(len(compact_text), ("end", 0))])

    states: dict[int, tuple[int, list[int]]] = {0: (0, [0])}
    for level, page_options in enumerate(options[1:], 1):
        next_states: dict[int, tuple[int, list[int]]] = {}
        for value, (kind, _) in page_options:
            best: tuple[int, list[int]] | None = None
            for previous, (old_cost, old_path) in states.items():
                if previous >= value:
                    continue
                cost = old_cost
                if level < len(options) - 1:
                    cost += distance_weight * abs(value - targets[level - 1])
                    cost += -punctuation_reward if kind == "punct" else token_penalty
                candidate = (cost, [*old_path, value])
                if best is None or candidate[0] < best[0]:
                    best = candidate
            if best is not None:
                next_states[value] = best
        states = next_states
    final = states.get(len(compact_text))
    if final is None:
        return None
    path = final[1]
    return [compact_text[start:end] for start, end in zip(path, path[1:])]


def score(
    cases: Sequence[Mapping[str, Any]],
    *,
    window: int,
    distance_weight: int,
    punctuation_reward: int,
    token_penalty: int,
) -> dict[str, Any]:
    hits: list[str] = []
    edited_hits: list[str] = []
    edited_total = sum(bool(case["user_changed"]) for case in cases)
    for case in cases:
        result = split_global(
            str(case["text"]),
            case["production_weights"],
            window=window,
            distance_weight=distance_weight,
            punctuation_reward=punctuation_reward,
            token_penalty=token_penalty,
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


def main() -> int:
    results: list[dict[str, Any]] = []
    cases = _load_cases()
    for window in (8, 16, 32, 60):
        for distance_weight in (20, 100, 500):
            for punctuation_reward in (500, 1500, 3000, 8000):
                for token_penalty in (0, 300, 1000):
                    by_label = {
                        label: score(
                            label_cases,
                            window=window,
                            distance_weight=distance_weight,
                            punctuation_reward=punctuation_reward,
                            token_penalty=token_penalty,
                        )
                        for label, label_cases in cases.items()
                    }
                    total_hits = sum(value["hits"] for value in by_label.values())
                    total_edited_hits = sum(
                        value["edited_hits"] for value in by_label.values()
                    )
                    results.append(
                        {
                            "window": window,
                            "distance_weight": distance_weight,
                            "punctuation_reward": punctuation_reward,
                            "token_penalty": token_penalty,
                            "total_hits": total_hits,
                            "total_edited_hits": total_edited_hits,
                            "by_label": by_label,
                        }
                    )
    results.sort(
        key=lambda item: (
            item["total_hits"],
            item["total_edited_hits"],
        ),
        reverse=True,
    )
    payload = {
        "experiment": "global_boundary_scorer",
        "candidate_count": len(results),
        "best": results[:20],
        "gate_passes": [
            result
            for result in results
            if result["total_hits"] >= 70
            and all(
                value["hits"] / value["cases"] >= 0.60
                for value in result["by_label"].values()
            )
            and all(
                value["edited_hits"] / value["edited_cases"] >= 0.60
                for value in result["by_label"].values()
            )
        ],
    }
    output = Path(__file__).with_name("global-scorer-results.json")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
