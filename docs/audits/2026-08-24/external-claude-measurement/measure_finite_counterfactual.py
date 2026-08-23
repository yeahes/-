"""READ-ONLY counterfactual. The project on disk is NOT modified.

_fragment_has_finite_predicate is monkeypatched *inside this measurement
process only*, to the wordlist-first / spaCy-fallback algorithm the project
already ships at scripts/audit_visual_temporal_splits.py:45-67.

Question: of the 516 production-ACCEPTED boundaries that today's rules call
illegal, how many stop being illegal once that one 19-line helper stops
under-reporting finite verbs?
"""
import json
import os
import sys
import logging
from collections import Counter
from functools import lru_cache
from pathlib import Path

PROJ = Path("/sessions/magical-zen-dijkstra/mnt/VideoCaptioner-screen-subtitle")
MODEL = PROJ / "runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0"
os.environ.setdefault("OPENAI_API_KEY", "x")
sys.path.insert(0, str(PROJ))
sys.path.insert(0, "/sessions/magical-zen-dijkstra/mnt/outputs")

import spacy  # noqa: E402
from app.core.subtitle_processor import screen_editor as se_mod  # noqa: E402
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor as E  # noqa: E402
from measure_boundary_flips import build_editor, find_episodes  # noqa: E402

logging.disable(logging.CRITICAL)
se_mod.logger.disabled = True
NLP = spacy.load(str(MODEL), disable=["ner", "textcat"])

_ORIG = E._fragment_has_finite_predicate.__func__      # unwrap classmethod
NONFINITE_TAGS = {"VB", "VBG", "VBN"}                  # same exclusion as the audit script


@lru_cache(maxsize=200_000)
def _spacy_finite(joined: str) -> bool:
    return any(t.pos_ in {"VERB", "AUX"} and t.tag_ not in NONFINITE_TAGS
               for t in NLP(joined))


def patched(words):
    if _ORIG(E, words):
        return True
    joined = " ".join(words).strip()
    return bool(joined) and _spacy_finite(joined)


def collect(mode: str):
    """mode: 'before' uses shipped helper, 'after' uses patched helper."""
    if mode == "after":
        E._fragment_has_finite_predicate = staticmethod(patched)
    else:
        E._fragment_has_finite_predicate = classmethod(_ORIG)

    accepted = illegal = 0
    codes = Counter()
    keys = set()
    for name, art in find_episodes():
        wl = json.loads((art / "word-ledger.json").read_text("utf-8"))
        tl = json.loads((art / "final-cue-timeline.json").read_text("utf-8"))
        words, recs = wl.get("words") or [], tl.get("records") or []
        if not words or not recs:
            continue
        ed = build_editor(words, wl.get("source_segments") or [])
        for r0, r1 in zip(recs, recs[1:]):
            if int(r1["word_start"]) != int(r0["word_end"]) + 1:
                continue
            left = ed._item_from_word_span(int(r0["word_start"]), int(r0["word_end"]))
            right = ed._item_from_word_span(int(r1["word_start"]), int(r1["word_end"]))
            if not left or not right:
                continue
            accepted += 1
            hard = set(ed._evaluate_item_pair_for_final_boundary(left, right).get("hard_issues") or [])
            if hard:
                illegal += 1
                keys.add((name, r0.get("subtitle_id")))
                for c in hard:
                    codes[c] += 1
        print(f"[{mode}] {name} done", file=sys.stderr)
    return accepted, illegal, codes, keys


def main():
    a0, i0, c0, k0 = collect("before")
    a1, i1, c1, k1 = collect("after")

    per_code = []
    for c in sorted(set(c0) | set(c1), key=lambda x: -c0.get(x, 0)):
        b, a = c0.get(c, 0), c1.get(c, 0)
        per_code.append({"code": c, "before": b, "after": a, "resolved": b - a})

    out = {
        "production_accepted_boundaries": a0,
        "illegal_before_fix": i0,
        "illegal_after_fix": i1,
        "resolved_by_one_helper_fix": i0 - i1,
        "resolved_pct_of_contradictions": round(100.0 * (i0 - i1) / i0, 1) if i0 else None,
        "illegal_pct_before": round(100.0 * i0 / a0, 2) if a0 else None,
        "illegal_pct_after": round(100.0 * i1 / a1, 2) if a1 else None,
        "still_illegal_after": i1,
        "per_code": per_code,
        "boundaries_fixed_not_in_after_set": len(k0 - k1),
        "boundaries_newly_illegal_after": len(k1 - k0),
    }
    Path("/sessions/magical-zen-dijkstra/mnt/outputs/finite_predicate_counterfactual.json"
         ).write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    o = dict(out); o["per_code"] = [p for p in per_code if p["resolved"]][:14]
    print(json.dumps(o, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
