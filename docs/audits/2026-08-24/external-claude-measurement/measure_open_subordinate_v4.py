"""READ-ONLY counterfactual #2d.  The project on disk is NOT modified.

Run #2c enumerated every internal candidate gap and found arm E opens 105 new
legal gaps (0 newly illegal).  Eyeballing those 105 splits them cleanly:

  * the 69 whose left cue ends in a comma are overwhelmingly textbook
    fronted-subordinate breaks  ("If you look at all the chocolate eaten
    worldwide, | only a microscopic 2% ...")
  * the 36 whose left cue does NOT end in a comma are mostly places nothing
    should ever break  ("Because buyers are usually just way | too fragmented",
    "because the scale of this is hard | to wrap my head around",
    "... store on Main Street 50 years | ago")

Arm F (E + require a trailing comma to be exempted) resolves 12 fewer shipped
contradictions than E, but should also open far fewer bad new gaps.  Run #2b only
measured F on boundaries production already made, so the other half of F's
trade-off is unmeasured.  This script measures it: newly legal / newly illegal
candidate gaps under BOTH E and F over the same enumeration.

It does not assume the comma test applies to the left cue -- it re-runs the real
boundary evaluator under each arm.
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
_ORIG = E._is_open_subordinate_prefix
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


def arm_E(self, item) -> bool:
    s = gate_text(self, item)
    if s is None:
        return False
    return not has_finite_verb(s)


def arm_F(self, item) -> bool:
    s = gate_text(self, item)
    if s is None:
        return False
    if not has_finite_verb(s):
        return True
    return not s.rstrip().endswith(",")


ARMS = {"E": arm_E, "F": arm_F}


def main():
    st = Counter()
    samples = {"E_only": [], "F": []}
    t0 = time.time()
    for name, art in find_episodes():
        wl = json.loads((art / "word-ledger.json").read_text("utf-8"))
        tl = json.loads((art / "final-cue-timeline.json").read_text("utf-8"))
        words, recs = wl.get("words") or [], tl.get("records") or []
        if not words or not recs:
            continue
        E._is_open_subordinate_prefix = _ORIG
        ed = build_editor(words, wl.get("source_segments") or [])

        cand = []
        for rec in recs:
            a, b = int(rec["word_start"]), int(rec["word_end"])
            for i in range(a, b):
                st["gaps_total"] += 1
                left = ed._item_from_word_span(a, i)
                if not left or gate_text(ed, left) is None:
                    continue
                right = ed._item_from_word_span(i + 1, b)
                if not right:
                    continue
                st["gaps_in_gate"] += 1
                cand.append((rec.get("subtitle_id"), i, left, right))

        for sid, i, left, right in cand:
            E._is_open_subordinate_prefix = _ORIG
            h0 = set(ed._evaluate_item_pair_for_final_boundary(left, right)
                     .get("hard_issues") or [])
            got = {}
            for tag, fn in ARMS.items():
                E._is_open_subordinate_prefix = fn
                got[tag] = set(ed._evaluate_item_pair_for_final_boundary(left, right)
                               .get("hard_issues") or [])
            for tag in ARMS:
                if h0 and not got[tag]:
                    st["newly_legal_" + tag] += 1
                elif got[tag] and not h0:
                    st["newly_illegal_" + tag] += 1
            rec_s = {
                "episode": name, "parent_subtitle_id": sid, "gap": [i, i + 1],
                "left": ed._normalize_text(left.original),
                "right": ed._normalize_text(right.original)[:110],
            }
            if h0 and not got["F"] and len(samples["F"]) < 200:
                samples["F"].append(rec_s)
            if h0 and not got["E"] and got["F"] and len(samples["E_only"]) < 200:
                samples["E_only"].append(rec_s)
        E._is_open_subordinate_prefix = _ORIG
        print(f"[done] {name} gate={st['gaps_in_gate']} "
              f"E={st['newly_legal_E']} F={st['newly_legal_F']} "
              f"t={time.time()-t0:.0f}s", file=sys.stderr)

    out = {k: v for k, v in sorted(st.items())}
    out["distinct_left_right_F"] = len({(x["left"], x["right"]) for x in samples["F"]})
    out["distinct_left_right_E_only"] = len(
        {(x["left"], x["right"]) for x in samples["E_only"]})
    out["samples"] = samples
    (OUT / "open_subordinate_new_candidates_EF.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for k, v in out.items():
        if k != "samples":
            print(k, "=", v)


if __name__ == "__main__":
    main()
