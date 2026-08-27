"""READ-ONLY counterfactual #2b.  The project on disk is NOT modified.

Run #2a tested a "dependency-ancestry" replacement for
_is_open_subordinate_prefix (screen_editor.py:6575-6591) and resolved only 15 of
the 516 contradictions.  Inspecting the 15 showed WHY: spaCy labels subordinating
`when` as advmod/WRB, not mark, so a mark-only ancestry test silently exempts
every `when`-led cue regardless of structure.  The rule was right by accident.

Reading the resolved cases also corrected the diagnosis.  Every one of them is a
fronted subordinate clause + comma + main clause in the NEXT cue, e.g.

    When you refine a barrel of crude, | you only get a tiny percentage of jet fuel

That is one of the safest break points in English, and production shipped it.
So the real over-strictness is not "did the main clause already appear" but
"is the subordinate clause itself complete".  Contrast the one case the shipped
rule catches correctly:

    Because instead of hiring traditional film crews, | production companies ...

Here the left cue has no finite verb at all -- `Because` governs nothing.

Arms measured on the same 5,180 production-accepted parent boundaries:

    A  shipped code
    E  flag only when the cue has NO finite predicate of its own (spaCy)
    F  E, and additionally require the cue to end in a comma to be exempted
    G  E + the finite-predicate fix from report section 3.3

Reference from run #2a: B (finite fix alone) = 484 illegal, 32 resolved, 0 new.
"""
import json
import os
import re
import sys
import logging
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
_ORIG_FINITE = E._fragment_has_finite_predicate.__func__
_fin_cache: dict[str, bool] = {}


def has_finite_verb(text: str) -> bool:
    hit = _fin_cache.get(text)
    if hit is None:
        hit = any(t.pos_ in {"VERB", "AUX"} and t.tag_ not in NONFINITE
                  for t in NLP(text))
        _fin_cache[text] = hit
    return hit


def patched_finite(words):
    if _ORIG_FINITE(E, words):
        return True
    joined = " ".join(words).strip()
    return bool(joined) and has_finite_verb(joined)


def _entry(self, item) -> str | None:
    """Return the backchannel-stripped text when the shipped gate would fire."""
    text = self._normalize_text(item.original)
    if TERMINAL_RE.search(text):
        return None
    stripped = BACKCHANNEL_RE.sub("", text)
    if not SUBORD_RE.match(stripped.casefold()):
        return None
    return stripped


def open_sub_E(self, item) -> bool:
    stripped = _entry(self, item)
    if stripped is None:
        return False
    return not has_finite_verb(stripped)


def open_sub_F(self, item) -> bool:
    stripped = _entry(self, item)
    if stripped is None:
        return False
    if not has_finite_verb(stripped):
        return True
    return not stripped.rstrip().endswith(",")


ARMS = {
    "A_shipped": (False, None),
    "E_incomplete_subclause": (False, open_sub_E),
    "F_E_plus_comma_required": (False, open_sub_F),
    "G_E_plus_finite_fix": (True, open_sub_E),
}


def apply_arm(finite_fix: bool, open_sub):
    E._fragment_has_finite_predicate = (
        staticmethod(patched_finite) if finite_fix else classmethod(_ORIG_FINITE)
    )
    E._is_open_subordinate_prefix = open_sub or _ORIG_OPEN_SUB


def main():
    accepted = 0
    per = {k: {"illegal": 0, "codes": Counter(), "keys": set()} for k in ARMS}
    samples = {"E_resolved": [], "F_still_blocked": []}

    for name, art in find_episodes():
        wl = json.loads((art / "word-ledger.json").read_text("utf-8"))
        tl = json.loads((art / "final-cue-timeline.json").read_text("utf-8"))
        words, recs = wl.get("words") or [], tl.get("records") or []
        if not words or not recs:
            continue
        apply_arm(False, None)
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

        arm_hard = {}
        for arm, (ff, osub) in ARMS.items():
            apply_arm(ff, osub)
            got = {}
            for sid, left, right in pairs:
                hard = set(ed._evaluate_item_pair_for_final_boundary(left, right)
                           .get("hard_issues") or [])
                got[sid] = hard
                if hard:
                    per[arm]["illegal"] += 1
                    per[arm]["keys"].add((name, sid))
                    for c in hard:
                        per[arm]["codes"][c] += 1
            arm_hard[arm] = got

        base = arm_hard["A_shipped"]
        by_sid = {sid: (l, r) for sid, l, r in pairs}
        for sid, h0 in base.items():
            hE = arm_hard["E_incomplete_subclause"].get(sid, set())
            if h0 and not hE and len(samples["E_resolved"]) < 60:
                l, r = by_sid[sid]
                samples["E_resolved"].append({
                    "episode": name, "subtitle_id": sid, "was": sorted(h0),
                    "left": ed._normalize_text(l.original),
                    "right_head": " ".join(ed._normalize_text(r.original).split()[:9]),
                })
            if ("open_subordinate_prefix_fragment" in hE
                    and len(samples["F_still_blocked"]) < 60):
                l, r = by_sid[sid]
                samples["F_still_blocked"].append({
                    "episode": name, "subtitle_id": sid, "now": sorted(hE),
                    "left": ed._normalize_text(l.original),
                    "right_head": " ".join(ed._normalize_text(r.original).split()[:9]),
                })
        apply_arm(False, None)
        print(f"[done] {name} "
              + " ".join(f"{a}={per[a]['illegal']}" for a in ARMS), file=sys.stderr)

    ak = per["A_shipped"]["keys"]
    out = {"production_accepted_boundaries": accepted, "arms": {}}
    for arm in ARMS:
        k = per[arm]["keys"]
        out["arms"][arm] = {
            "illegal": per[arm]["illegal"],
            "illegal_pct": round(100.0 * per[arm]["illegal"] / accepted, 2) if accepted else None,
            "resolved_vs_shipped": len(ak - k),
            "newly_illegal_vs_shipped": len(k - ak),
            "open_sub_code_hits": per[arm]["codes"].get("open_subordinate_prefix_fragment", 0),
            "top_codes": per[arm]["codes"].most_common(12),
        }
    out["samples"] = samples
    (OUT / "open_subordinate_counterfactual_v2.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    slim = dict(out)
    slim["samples"] = {k: v[:8] for k, v in samples.items()}
    print(json.dumps(slim, ensure_ascii=False, indent=1)[:5000])


if __name__ == "__main__":
    main()
