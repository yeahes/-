"""Stage A2 (proper falsification) + Stage C (analysis of opened boundaries).

Stage A2: every boundary BETWEEN consecutive frozen parents was accepted by
production. Feed each through the SAME function stage B uses
(_evaluate_item_pair_for_final_boundary). If the harness marks an accepted
boundary illegal, either the harness is wrong or the rules drifted after the
run. Either way the counterfactual number needs that caveat, so measure it.

Stage C: characterise the boundaries that open up.
"""
import json
import os
import sys
import logging
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

PROJ = Path("/sessions/magical-zen-dijkstra/mnt/VideoCaptioner-screen-subtitle")
MODEL = PROJ / "runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0"
os.environ.setdefault("OPENAI_API_KEY", "x")
sys.path.insert(0, str(PROJ))

import spacy  # noqa: E402
from app.core.subtitle_processor import screen_editor as se_mod  # noqa: E402
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor  # noqa: E402

logging.disable(logging.CRITICAL)
se_mod.logger.disabled = True
TARGET = {"relative_clause_entrance_split", "dependent_clause_entrance_split"}
_NLP = spacy.load(str(MODEL), disable=["ner", "textcat"])

sys.path.insert(0, "/sessions/magical-zen-dijkstra/mnt/outputs")
from measure_boundary_flips import build_editor, find_episodes  # noqa: E402


def main():
    accepted = illegal_accepted = 0
    illegal_code_hist = Counter()
    accepted_target_hist = Counter()
    examples = []
    per_ep = {}

    for name, art in find_episodes():
        wl = json.loads((art / "word-ledger.json").read_text("utf-8"))
        tl = json.loads((art / "final-cue-timeline.json").read_text("utf-8"))
        words, recs = wl.get("words") or [], tl.get("records") or []
        if not words or not recs:
            continue
        ed = build_editor(words, wl.get("source_segments") or [])
        a_tot = a_bad = 0
        for r0, r1 in zip(recs, recs[1:]):
            if int(r1["word_start"]) != int(r0["word_end"]) + 1:
                continue          # non-contiguous: not a cut decision
            left = ed._item_from_word_span(int(r0["word_start"]), int(r0["word_end"]))
            right = ed._item_from_word_span(int(r1["word_start"]), int(r1["word_end"]))
            if not left or not right:
                continue
            res = ed._evaluate_item_pair_for_final_boundary(left, right)
            hard = set(res.get("hard_issues") or [])
            accepted += 1
            a_tot += 1
            if hard:
                illegal_accepted += 1
                a_bad += 1
                for c in hard:
                    illegal_code_hist[c] += 1
                for c in hard & TARGET:
                    accepted_target_hist[c] += 1
                if len(examples) < 20:
                    examples.append({
                        "episode": name,
                        "ids": [r0.get("subtitle_id"), r1.get("subtitle_id")],
                        "hard": sorted(hard),
                        "left_tail": " ".join(ed._normalize_text(left.original).split()[-7:]),
                        "right_head": " ".join(ed._normalize_text(right.original).split()[:7]),
                        "pause_ms": res.get("pause_ms"),
                    })
        per_ep[name] = {"accepted_boundaries": a_tot, "now_illegal": a_bad}
        print(f"[A2] {name}: {a_bad}/{a_tot} 生产已接受但现规则判非法", file=sys.stderr)

    prev = json.loads(Path("/sessions/magical-zen-dijkstra/mnt/outputs/"
                           "boundary_flip_measurement.json").read_text("utf-8"))
    opened = prev["opened_boundaries"]

    by_parent_len = Counter()
    ev = Counter()
    for o in opened:
        n = o["parent_words"]
        bucket = ("<=12" if n <= 12 else "13-16" if n <= 16 else "17-19" if n <= 19 else ">=20")
        by_parent_len[bucket] += 1
        if "relative_clause_entrance_split" in o["issues"]:
            ev["relative__left_ends_comma" if o["left_ends_comma"]
               else "relative__no_comma"] += 1
        if "dependent_clause_entrance_split" in o["issues"]:
            ev["dependent__left_has_finite_predicate" if o["left_has_finite_predicate"]
               else "dependent__left_no_finite_predicate"] += 1
        p = o["pause_ms"]
        ev["pause_ge_450" if (p is not None and p >= 450) else "pause_lt_450"] += 1

    distinct_parents = {(o["episode"], o["subtitle_id"]) for o in opened}
    long_parents = {(o["episode"], o["subtitle_id"]) for o in opened if o["parent_words"] >= 17}
    tri = [o for o in opened
           if o["subtitle_id"] in {"S0123", "S0132", "S0192"} and "白宫" in o["episode"]]

    out = {
        "stage_a2_falsification": {
            "production_accepted_boundaries_checked": accepted,
            "now_judged_illegal_by_harness": illegal_accepted,
            "illegal_pct": round(100.0 * illegal_accepted / accepted, 2) if accepted else None,
            "illegal_code_histogram": illegal_code_hist.most_common(20),
            "of_which_our_two_target_predicates": dict(accepted_target_hist),
            "per_episode": per_ep,
            "examples": examples,
        },
        "stage_c_opened_analysis": {
            "opened_cut_points": len(opened),
            "distinct_parents_affected": len(distinct_parents),
            "distinct_long_parents_affected_ge17w": len(long_parents),
            "by_parent_word_bucket": dict(by_parent_len),
            "evidence_breakdown": dict(ev),
            "hits_on_the_three_unpageable": tri,
            "samples": opened[:30],
        },
    }
    Path("/sessions/magical-zen-dijkstra/mnt/outputs/boundary_flip_stage2.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(out["stage_a2_falsification"], ensure_ascii=False, indent=1)[:2600])
    print(json.dumps(out["stage_c_opened_analysis"], ensure_ascii=False, indent=1)[:1800])


if __name__ == "__main__":
    main()
