"""READ-ONLY counterfactual #2.  The project on disk is NOT modified.

Question (report section 10.2): `open_subordinate_prefix_fragment` is the single
largest self-contradiction code (110 of the 516 production-accepted boundaries
that today's rules call illegal).  Its source is _is_open_subordinate_prefix
(screen_editor.py:6575-6591), a pure regex that never checks whether a main
clause has already appeared in the same cue.

Counterfactual: replace the "is there a subordinator at the start and no
terminal punctuation" test with a DEPENDENCY-ANCESTRY test --

    the cue is still an open subordinate prefix  <=>
        no sentence in the cue has a finite ROOT that is NOT itself marked by a
        subordinator (i.e. no closed subordinate clause + main clause pair)

Four arms, all measured on the same 5,180 production-accepted parent boundaries:

    A  shipped code                                  (expected 516 illegal)
    B  + finite-predicate fix        (report 3.3)
    C  + open-subordinate fix        (report 10.2)
    D  both fixes together

Everything is monkeypatched inside this process only.
"""
import json
import os
import re
import sys
import logging
from collections import Counter
from pathlib import Path

PROJ = Path("/sessions/magical-zen-dijkstra/mnt/VideoCaptioner-screen-subtitle")
OUT = Path("/sessions/magical-zen-dijkstra/mnt/outputs")
MODEL = PROJ / "runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0"
os.environ.setdefault("OPENAI_API_KEY", "x")
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(OUT))

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
FINITE_AUX_TAGS = {"MD", "VBD", "VBP", "VBZ"}

_ORIG_OPEN_SUB = E._is_open_subordinate_prefix
_ORIG_FINITE = E._fragment_has_finite_predicate.__func__

_parse_cache: dict[str, bool] = {}
_finite_cache: dict[str, bool] = {}


# ---------------------------------------------------------------- fix (3.3)
def _spacy_finite(joined: str) -> bool:
    hit = _finite_cache.get(joined)
    if hit is None:
        hit = any(t.pos_ in {"VERB", "AUX"} and t.tag_ not in NONFINITE
                  for t in NLP(joined))
        _finite_cache[joined] = hit
    return hit


def patched_finite(words):
    if _ORIG_FINITE(E, words):
        return True
    joined = " ".join(words).strip()
    return bool(joined) and _spacy_finite(joined)


# --------------------------------------------------------------- fix (10.2)
def _main_clause_present(text: str) -> bool:
    """True when some sentence has a finite ROOT that no subordinator marks.

    Mirrors the finite tests the project already uses in
    _visual_temporal_clause_shape (screen_editor.py:5583-5595) but replaces its
    positional `token.i < root.i` proxy with a dependency-ancestry check: the
    subordinator must not be a `mark` child of ROOT itself.
    """
    hit = _parse_cache.get(text)
    if hit is not None:
        return hit
    result = False
    doc = NLP(text)
    for sent in doc.sents:
        root = sent.root
        if root is None:
            continue
        finite = root.pos_ in {"VERB", "AUX"} and root.tag_ not in NONFINITE
        finite_aux = bool(
            root.pos_ == "VERB"
            and root.tag_ in NONFINITE
            and any(c.dep_ in {"aux", "auxpass"} and c.tag_ in FINITE_AUX_TAGS
                    for c in root.children)
        )
        if not (finite or finite_aux):
            continue
        # ROOT itself sits inside a subordinate clause -> nothing is closed yet.
        if any(c.dep_ == "mark" for c in root.children):
            continue
        result = True
        break
    _parse_cache[text] = result
    return result


def patched_open_sub(self, item) -> bool:
    text = self._normalize_text(item.original)
    if TERMINAL_RE.search(text):
        return False
    stripped = BACKCHANNEL_RE.sub("", text)
    if not SUBORD_RE.match(stripped.casefold()):
        return False
    # NEW: only an *unclosed* subordinate introduction counts.
    return not _main_clause_present(stripped)


# -------------------------------------------------------------------- arms
ARMS = {
    "A_shipped": (False, False),
    "B_finite_only": (True, False),
    "C_opensub_only": (False, True),
    "D_both": (True, True),
}


def apply_arm(finite_fix: bool, opensub_fix: bool) -> None:
    E._fragment_has_finite_predicate = (
        staticmethod(patched_finite) if finite_fix else classmethod(_ORIG_FINITE)
    )
    E._is_open_subordinate_prefix = (
        patched_open_sub if opensub_fix else _ORIG_OPEN_SUB
    )


def main():
    accepted = 0
    per_arm = {k: {"illegal": 0, "codes": Counter(), "keys": set()} for k in ARMS}
    samples = {"C_resolved": [], "C_new": [], "D_resolved": [], "D_new": []}

    for name, art in find_episodes():
        wl = json.loads((art / "word-ledger.json").read_text("utf-8"))
        tl = json.loads((art / "final-cue-timeline.json").read_text("utf-8"))
        words, recs = wl.get("words") or [], tl.get("records") or []
        if not words or not recs:
            continue
        apply_arm(False, False)
        ed = build_editor(words, wl.get("source_segments") or [])

        pairs = []
        for r0, r1 in zip(recs, recs[1:]):
            if int(r1["word_start"]) != int(r0["word_end"]) + 1:
                continue
            left = ed._item_from_word_span(int(r0["word_start"]), int(r0["word_end"]))
            right = ed._item_from_word_span(int(r1["word_start"]), int(r1["word_end"]))
            if left and right:
                pairs.append((r0.get("subtitle_id"), left, right))
        accepted += len(pairs)

        arm_hard: dict[str, dict] = {}
        for arm, (ff, of) in ARMS.items():
            apply_arm(ff, of)
            got = {}
            for sid, left, right in pairs:
                hard = set(
                    ed._evaluate_item_pair_for_final_boundary(left, right).get("hard_issues") or []
                )
                got[sid] = hard
                if hard:
                    per_arm[arm]["illegal"] += 1
                    per_arm[arm]["keys"].add((name, sid))
                    for c in hard:
                        per_arm[arm]["codes"][c] += 1
            arm_hard[arm] = got

        base = arm_hard["A_shipped"]
        by_sid = {sid: (left, right) for sid, left, right in pairs}
        for arm, tag in (("C_opensub_only", "C"), ("D_both", "D")):
            cur = arm_hard[arm]
            for sid, hard0 in base.items():
                hard1 = cur.get(sid, set())
                if hard0 and not hard1 and len(samples[tag + "_resolved"]) < 40:
                    left, right = by_sid[sid]
                    samples[tag + "_resolved"].append({
                        "episode": name, "subtitle_id": sid,
                        "was": sorted(hard0),
                        "left": ed._normalize_text(left.original),
                        "right_head": " ".join(
                            ed._normalize_text(right.original).split()[:9]),
                    })
                if hard1 and not hard0 and len(samples[tag + "_new"]) < 40:
                    left, right = by_sid[sid]
                    samples[tag + "_new"].append({
                        "episode": name, "subtitle_id": sid,
                        "now": sorted(hard1),
                        "left": ed._normalize_text(left.original),
                        "right_head": " ".join(
                            ed._normalize_text(right.original).split()[:9]),
                    })
        apply_arm(False, False)
        print(f"[done] {name} pairs={len(pairs)} "
              + " ".join(f"{a}={per_arm[a]['illegal']}" for a in ARMS), file=sys.stderr)

    a_keys = per_arm["A_shipped"]["keys"]
    summary = {"production_accepted_boundaries": accepted, "arms": {}}
    for arm in ARMS:
        k = per_arm[arm]["keys"]
        summary["arms"][arm] = {
            "illegal": per_arm[arm]["illegal"],
            "illegal_pct": round(100.0 * per_arm[arm]["illegal"] / accepted, 2) if accepted else None,
            "resolved_vs_shipped": len(a_keys - k),
            "newly_illegal_vs_shipped": len(k - a_keys),
            "top_codes": per_arm[arm]["codes"].most_common(14),
        }
    summary["per_code_A_to_C"] = [
        {"code": c,
         "A": per_arm["A_shipped"]["codes"].get(c, 0),
         "C": per_arm["C_opensub_only"]["codes"].get(c, 0),
         "D": per_arm["D_both"]["codes"].get(c, 0)}
        for c in sorted(per_arm["A_shipped"]["codes"],
                        key=lambda x: -per_arm["A_shipped"]["codes"][x])
    ]
    summary["samples"] = samples
    (OUT / "open_subordinate_counterfactual.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    slim = dict(summary)
    slim["samples"] = {k: v[:6] for k, v in samples.items()}
    print(json.dumps(slim, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
