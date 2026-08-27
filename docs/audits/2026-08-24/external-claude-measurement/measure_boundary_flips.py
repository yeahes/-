"""READ-ONLY measurement. Writes nothing into the project.

Question: how many cut points are currently illegal ONLY because of
  _cross_item_structural_boundary_issues -> relative_clause_entrance_split
                                        -> dependent_clause_entrance_split
i.e. how many boundaries would open up if those two HARD predicates were given
the same evidence checks the other three predicates in the same function
already have.

Stage A validates the harness against the project's own recorded boundary audit
before any counterfactual number is reported.
"""
import json
import os
import sys
import logging
from pathlib import Path
from types import SimpleNamespace

# Repo root and script dir are derived from this file's location so the
# script runs unmodified on Windows or Linux. Override with VC_REPO if moved.
_HERE = Path(__file__).resolve().parent
PROJ = Path(os.environ.get("VC_REPO") or _HERE.parents[3])
MODEL = PROJ / "runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0"

os.environ.setdefault("OPENAI_API_KEY", "not-used-offline")
os.environ.setdefault("OPENAI_BASE_URL", "http://127.0.0.1:1/v1")
sys.path.insert(0, str(PROJ))

import spacy  # noqa: E402
from app.core.subtitle_processor import screen_editor as se_mod  # noqa: E402
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor  # noqa: E402

logging.disable(logging.CRITICAL)
se_mod.logger.disabled = True

TARGET = {"relative_clause_entrance_split", "dependent_clause_entrance_split"}
_NLP = spacy.load(str(MODEL), disable=["ner", "textcat"])


def find_episodes():
    out = []
    for wd in sorted((PROJ / "work-dir").iterdir()):
        if not wd.is_dir():
            continue
        sub = wd / "subtitle"
        if not sub.is_dir():
            continue
        for art in sorted(sub.glob("*artifacts")):
            wl, tl = art / "word-ledger.json", art / "final-cue-timeline.json"
            if wl.is_file() and tl.is_file():
                out.append((wd.name, art))
                break
    return out


def build_editor(words, source_segments):
    ed = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    ed.max_english_words = 16
    ed._active_word_entries = []
    for w in words:
        surface = str(w.get("surface") or "")
        toks = ScreenSubtitleEditor._word_tokens(surface)
        ed._active_word_entries.append({
            "token": toks[0] if toks else str(w.get("normalized") or surface),
            "surface": surface,
            "start_time": int(w["start_ms"]),
            "end_time": int(w["end_ms"]),
            "alignment_source": str(w.get("alignment_source") or "offline-ledger"),
        })
    ranges = {}
    for w in words:
        wid = int(w["word_id"])
        for raw in w.get("source_segment_ids") or ():
            sid = int(raw)
            if sid in ranges:
                a, b = ranges[sid]
                ranges[sid] = (min(a, wid), max(b, wid))
            else:
                ranges[sid] = (wid, wid)
    objs = {}
    for raw in source_segments:
        sid = int(raw.get("id") or 0)
        if sid:
            objs[sid] = SimpleNamespace(**raw)
    ed._active_source_word_spans = ranges
    ed._active_source_segments_by_id = objs
    ed._syntax_protected_cuts = set()
    ed._syntax_hard_cut_issues = {}
    ed._syntax_soft_cut_issues = {}
    ed._orphaned_finite_predicate_cache = {}
    ed._syntax_nlp = _NLP          # pre-loaded: _load_syntax_nlp returns it as-is
    ed._prepare_syntax_cut_hints()
    return ed


def stage_a(ed, audit):
    """Validate harness against production's own recorded boundary audit."""
    tot = agree = 0
    disagree = []
    for rec in audit.get("records") or []:
        if rec.get("scope") != "parent_cue":
            continue
        ev = rec.get("evidence") or {}
        wb = ev.get("word_boundary")
        if not ev.get("word_continuity") or not wb or len(wb) != 2:
            continue
        left, right = int(wb[0]), int(wb[1])
        if right != left + 1:
            continue
        try:
            got = ed._evaluate_stable_cut_boundary(left, right)
        except Exception as exc:
            disagree.append((left, right, "EXC:" + type(exc).__name__, str(exc)[:60]))
            tot += 1
            continue
        mine = set(got.get("hard_issues") or []) | set(got.get("soft_issues") or [])
        theirs = set(rec.get("rule_codes") or [])
        tot += 1
        if mine == theirs:
            agree += 1
        else:
            disagree.append((left, right, sorted(theirs), sorted(mine)))
    return tot, agree, disagree


def stage_b(ed, records):
    """Counterfactual over every internal gap of every frozen parent cue."""
    st = {
        "gaps": 0, "legal_now": 0, "blocked": 0,
        "only_target": 0, "only_relative": 0, "only_dependent": 0, "only_both": 0,
        "target_plus_other": 0,
    }
    opened = []
    for rec in records:
        a, b = int(rec["word_start"]), int(rec["word_end"])
        sid = rec.get("subtitle_id")
        nwords = b - a + 1
        for i in range(a, b):
            st["gaps"] += 1
            left = ed._item_from_word_span(a, i)
            right = ed._item_from_word_span(i + 1, b)
            if not left or not right:
                continue
            res = ed._evaluate_item_pair_for_final_boundary(left, right)
            hard = set(res.get("hard_issues") or [])
            if not hard:
                st["legal_now"] += 1
                continue
            st["blocked"] += 1
            hit = hard & TARGET
            if not hit:
                continue
            if hard - TARGET:
                st["target_plus_other"] += 1
                continue
            st["only_target"] += 1
            if hit == {"relative_clause_entrance_split"}:
                st["only_relative"] += 1
            elif hit == {"dependent_clause_entrance_split"}:
                st["only_dependent"] += 1
            else:
                st["only_both"] += 1
            lt = ed._normalize_text(left.original)
            lw = [w.casefold() for w in ed._word_tokens(lt)]
            opened.append({
                "subtitle_id": sid, "parent_words": nwords, "gap": [i, i + 1],
                "issues": sorted(hit),
                "left_tail": " ".join(lt.split()[-6:]),
                "right_head": " ".join(ed._normalize_text(right.original).split()[:6]),
                "left_ends_comma": lt.rstrip().endswith(","),
                "left_has_finite_predicate": bool(ed._fragment_has_finite_predicate(lw)),
                "pause_ms": res.get("pause_ms"),
                "left_words": len(lw),
            })
    return st, opened


def main():
    grand = {}
    all_opened = []
    va_tot = va_agree = 0
    va_bad = []
    for name, art in find_episodes():
        try:
            wl = json.loads((art / "word-ledger.json").read_text("utf-8"))
            tl = json.loads((art / "final-cue-timeline.json").read_text("utf-8"))
        except Exception as exc:
            print(f"[skip] {name}: {type(exc).__name__}", file=sys.stderr)
            continue
        words = wl.get("words") or []
        recs = tl.get("records") or []
        if not words or not recs:
            continue
        ed = build_editor(words, wl.get("source_segments") or [])
        ap = art / "english-boundary-audit.json"
        if ap.is_file():
            try:
                t, a, d = stage_a(ed, json.loads(ap.read_text("utf-8")))
                va_tot += t
                va_agree += a
                va_bad.extend([(name,) + tuple(x) for x in d[:5]])
            except Exception as exc:
                print(f"[stageA skip] {name}: {exc}", file=sys.stderr)
        st, opened = stage_b(ed, recs)
        st["parents"] = len(recs)
        st["words"] = len(words)
        grand[name] = st
        for o in opened:
            o["episode"] = name
        all_opened.extend(opened)
        print(f"[done] {name}: parents={len(recs)} gaps={st['gaps']} "
              f"only_target={st['only_target']}", file=sys.stderr)

    out = {
        "harness_validation": {
            "boundaries_checked": va_tot,
            "rule_codes_identical": va_agree,
            "agreement_pct": round(100.0 * va_agree / va_tot, 2) if va_tot else None,
            "sample_disagreements": va_bad[:25],
        },
        "per_episode": grand,
        "totals": {
            k: sum(v[k] for v in grand.values())
            for k in ("parents", "words", "gaps", "legal_now", "blocked",
                      "only_target", "only_relative", "only_dependent",
                      "only_both", "target_plus_other")
        } if grand else {},
        "opened_boundaries": all_opened,
    }
    (_HERE / "boundary_flip_measurement.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(out["harness_validation"], ensure_ascii=False, indent=1)[:2000])
    print(json.dumps(out["totals"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
