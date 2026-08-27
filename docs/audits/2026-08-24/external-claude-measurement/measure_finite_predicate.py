"""READ-ONLY. Writes nothing into the project.

Measures the accuracy of ScreenSubtitleEditor._fragment_has_finite_predicate
(screen_editor.py:6697-6715) -- a 45-word hardcoded auxiliary list + 10 ad-hoc
lexical verbs, with no morphology and no spaCy -- against spaCy's own
finite-verb tagging, on the project's own frozen parent cues.

spaCy is NOT an external yardstick here: the same class already loads
en_core_web_sm in _load_syntax_nlp for syntax cut hints, so this compares the
helper against a signal the project already trusts and already pays for.

Each frozen parent cue is a full cue, so spaCy has sentence context and its
tagging is reliable -- this avoids fragment-parsing degradation.
"""
import json
import os
import sys
import logging
from collections import Counter
from pathlib import Path

# Repo root and script dir are derived from this file's location so the
# script runs unmodified on Windows or Linux. Override with VC_REPO if moved.
_HERE = Path(__file__).resolve().parent
PROJ = Path(os.environ.get("VC_REPO") or _HERE.parents[3])
MODEL = PROJ / "runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0"
os.environ.setdefault("OPENAI_API_KEY", "x")
sys.path.insert(0, str(PROJ))

import spacy  # noqa: E402
from app.core.subtitle_processor import screen_editor as se_mod  # noqa: E402
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor as E  # noqa: E402

logging.disable(logging.CRITICAL)
se_mod.logger.disabled = True
NLP = spacy.load(str(MODEL), disable=["ner", "textcat"])

FINITE_TAGS = {"VBZ", "VBD", "VBP", "MD"}


def spacy_has_finite(doc):
    """A finite verb per spaCy: tag in VBZ/VBD/VBP/MD, or VerbForm=Fin."""
    for t in doc:
        if t.pos_ not in {"VERB", "AUX"}:
            continue
        if t.tag_ in FINITE_TAGS:
            return t
        if "Fin" in (t.morph.get("VerbForm") or ()):
            return t
    return None


def main():
    sys.path.insert(0, str(_HERE))
    from measure_boundary_flips import find_episodes

    texts, meta = [], []
    for name, art in find_episodes():
        wl = json.loads((art / "word-ledger.json").read_text("utf-8"))
        tl = json.loads((art / "final-cue-timeline.json").read_text("utf-8"))
        words = {int(w["word_id"]): str(w.get("surface") or "") for w in (wl.get("words") or [])}
        for r in tl.get("records") or []:
            a, b = int(r["word_start"]), int(r["word_end"])
            txt = " ".join(words.get(i, "") for i in range(a, b + 1)).strip()
            if not txt:
                continue
            texts.append(txt)
            meta.append((name, r.get("subtitle_id"), b - a + 1))

    tot = both_yes = both_no = fn = fp = 0
    fn_verbs = Counter()
    fn_samples, fp_samples = [], []

    for (txt, (ep, sid, n)), doc in zip(zip(texts, meta), NLP.pipe(texts, batch_size=64)):
        words = [w.casefold() for w in E._word_tokens(txt)]
        mine = bool(E._fragment_has_finite_predicate(words))
        tok = spacy_has_finite(doc)
        theirs = tok is not None
        tot += 1
        if mine and theirs:
            both_yes += 1
        elif not mine and not theirs:
            both_no += 1
        elif theirs and not mine:                      # over-strict direction
            fn += 1
            fn_verbs[f"{tok.lemma_}/{tok.tag_}"] += 1
            if len(fn_samples) < 25:
                fn_samples.append({"episode": ep, "id": sid, "words": n,
                                   "text": txt[:110],
                                   "spacy_verb": f"{tok.text}({tok.tag_})"})
        else:                                          # helper says yes, spaCy no
            fp += 1
            if len(fp_samples) < 15:
                fp_samples.append({"episode": ep, "id": sid, "text": txt[:110]})

    out = {
        "cues_checked": tot,
        "helper_yes__spacy_yes": both_yes,
        "helper_no__spacy_no": both_no,
        "helper_NO_but_spacy_YES__over_strict": fn,
        "over_strict_pct_of_all_cues": round(100.0 * fn / tot, 2) if tot else None,
        "over_strict_pct_of_cues_spacy_calls_finite": (
            round(100.0 * fn / (both_yes + fn), 2) if (both_yes + fn) else None),
        "helper_YES_but_spacy_NO": fp,
        "missed_verbs_top40": fn_verbs.most_common(40),
        "distinct_missed_verb_lemmas": len(fn_verbs),
        "over_strict_samples": fn_samples,
        "helper_yes_spacy_no_samples": fp_samples,
    }
    (_HERE / "finite_predicate_audit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    o = dict(out)
    o["missed_verbs_top40"] = out["missed_verbs_top40"][:18]
    o["over_strict_samples"] = out["over_strict_samples"][:8]
    o["helper_yes_spacy_no_samples"] = out["helper_yes_spacy_no_samples"][:3]
    print(json.dumps(o, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
