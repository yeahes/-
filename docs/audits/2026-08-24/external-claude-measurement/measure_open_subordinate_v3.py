"""READ-ONLY counterfactual #2c.  The project on disk is NOT modified.

Run #2b showed arm E (flag `open_subordinate_prefix_fragment` only when the cue
has no finite predicate of its own) resolves 76 of the 516 contradictions with
zero newly-illegal boundaries.  But that measurement only looks at boundaries
production ALREADY made.  Report section 1 was retracted for exactly this reason:
a relaxation can look free on shipped output while opening bad NEW cut points.

So this script asks the complementary question:

    over every internal candidate gap of every frozen parent cue, how many gaps
    become LEGAL under arm E that are ILLEGAL under the shipped code, and what do
    they look like?

Only gaps whose left fragment matches the shipped gate's entry condition can
differ between the two arms, so those are the only ones evaluated twice.
"""
import json
import os
import re
import sys
import logging
import time
from collections import Counter
from pathlib import Path

# Repo root and script dir are derived from this file's location so the
# script runs unmodified on Windows or Linux. Override with VC_REPO if moved.
_HERE = Path(__file__).resolve().parent
PROJ = Path(os.environ.get("VC_REPO") or _HERE.parents[3])
OUT = _HERE
MODEL = PROJ / "runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0"
os.environ.setdefault("OPENAI_API_KEY", "x")
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(_HERE))
import spacy  # noqa: E402
from app.core.subtitle_processor import screen_editor as se_mod  # noqa: E402
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor as E  # noqa: E402
from measure_boundary_flips import build_editor, find_episodes  # noqa: E402

logging.disable(logging.CRITICAL)
se_mod.logger.disabled = True
NLP = spacy.load(str(MODEL), disable=["ner", "textcat"])

TERMINAL_RE = re.compile(r"[.!?][\"')\]]*\s*$")
BACKCHANNEL_RE = re.compile(
    r"^(?:(?:yes|yeah|right|exactly|absolutely|definitely|sure|okay|ok)[.!?]\s*)+",
    re.IGNORECASE,
)
SUBORD_RE = re.compile(
    r"^(?:because\s+)?(?:because|if|when|while|although|though|unless|until|once|whereas)\b"
)
NONFINITE = {"VB", "VBG", "VBN"}
_ORIG_OPEN_SUB = E._is_open_subordinate_prefix
_fin: dict[str, bool] = {}


def has_finite_verb(text: str) -> bool:
    hit = _fin.get(text)
    if hit is None:
        hit = any(t.pos_ in {"VERB", "AUX"} and t.tag_ not in NONFINITE
                  for t in NLP(text))
        _fin[text] = hit
    return hit


def gate_text(ed, item):
    text = ed._normalize_text(item.original)
    if TERMINAL_RE.search(text):
        return None
    stripped = BACKCHANNEL_RE.sub("", text)
    if not SUBORD_RE.match(stripped.casefold()):
        return None
    return stripped


def open_sub_E(self, item) -> bool:
    stripped = gate_text(self, item)
    if stripped is None:
        return False
    return not has_finite_verb(stripped)


def main():
    st = Counter()
    newly_legal = []
    t0 = time.time()
    for name, art in find_episodes():
        wl = json.loads((art / "word-ledger.json").read_text("utf-8"))
        tl = json.loads((art / "final-cue-timeline.json").read_text("utf-8"))
        words, recs = wl.get("words") or [], tl.get("records") or []
        if not words or not recs:
            continue
        E._is_open_subordinate_prefix = _ORIG_OPEN_SUB
        ed = build_editor(words, wl.get("source_segments") or [])

        candidates = []
        for rec in recs:
            a, b = int(rec["word_start"]), int(rec["word_end"])
            for i in range(a, b):
                st["gaps_total"] += 1
                left = ed._item_from_word_span(a, i)
                if not left:
                    continue
                if gate_text(ed, left) is None:
                    continue          # arms cannot differ here
                right = ed._item_from_word_span(i + 1, b)
                if not right:
                    continue
                st["gaps_in_gate"] += 1
                candidates.append((rec.get("subtitle_id"), i, left, right))

        for sid, i, left, right in candidates:
            E._is_open_subordinate_prefix = _ORIG_OPEN_SUB
            h0 = set(ed._evaluate_item_pair_for_final_boundary(left, right)
                     .get("hard_issues") or [])
            E._is_open_subordinate_prefix = open_sub_E
            h1 = set(ed._evaluate_item_pair_for_final_boundary(left, right)
                     .get("hard_issues") or [])
            if h0 and not h1:
                st["newly_legal"] += 1
                if len(newly_legal) < 400:
                    newly_legal.append({
                        "episode": name, "parent_subtitle_id": sid, "gap": [i, i + 1],
                        "was": sorted(h0),
                        "left": ed._normalize_text(left.original),
                        "right": ed._normalize_text(right.original)[:110],
                    })
            elif h1 and not h0:
                st["newly_illegal"] += 1
        E._is_open_subordinate_prefix = _ORIG_OPEN_SUB
        print(f"[done] {name} gate={st['gaps_in_gate']} newly_legal={st['newly_legal']} "
              f"t={time.time()-t0:.0f}s", file=sys.stderr)

    out = {
        "gaps_enumerated": st["gaps_total"],
        "gaps_matching_shipped_gate_entry": st["gaps_in_gate"],
        "newly_legal_under_arm_E": st["newly_legal"],
        "newly_illegal_under_arm_E": st["newly_illegal"],
        "newly_legal_samples": newly_legal,
        "left_ends_with_comma_count": sum(
            1 for x in newly_legal if x["left"].rstrip().endswith(",")),
        "sampled": len(newly_legal),
    }
    (OUT / "open_subordinate_new_candidates.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for k, v in out.items():
        if k != "newly_legal_samples":
            print(k, "=", v)


if __name__ == "__main__":
    main()
