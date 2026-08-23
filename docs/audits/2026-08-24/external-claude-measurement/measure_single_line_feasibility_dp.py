"""READ-ONLY measurement C for report section 12.  The project is NOT modified.

measure_single_line_pages.py packed pages greedily.  Greedy minimises the page
count exactly, but it fills every page to the brim and dumps the remainder into a
short tail page -- so its page count is a LOWER bound while its
"<4 words / <900ms" counts are an UPPER bound.  The two bounds point opposite
ways, which is not good enough to decide anything.

This script closes the gap with a feasibility DP that asks the real question:

    does there EXIST a partition of the parent's words into <= MAX pages such
    that every page (a) fits on ONE line at font 56 within the given width,
    (b) holds >= ARTICLE_VISUAL_PAGE_MIN_WORDS words, and
    (c) lasts >= ARTICLE_PAGE_MIN_DURATION_MS?

Parents that cannot satisfy (b) or (c) even as a single whole page are counted
separately as `exempt_too_short` -- production violates those constraints on
those parents too, so charging them to single-line pagination would be unfair.

The same DP is run for the current two-line design (a page may hold two lines) as
the control, so the two layouts are compared under identical constraints.
"""
import glob
import json
import os
import sys
from collections import Counter
from pathlib import Path

PROJ = Path("/sessions/magical-zen-dijkstra/mnt/VideoCaptioner-screen-subtitle")
OUT = Path("/sessions/magical-zen-dijkstra/mnt/outputs")
os.environ.setdefault("OPENAI_API_KEY", "x")
sys.path.insert(0, str(PROJ))

from PIL import Image, ImageDraw  # noqa: E402
from app.core.utils.podcast_learning_video import (  # noqa: E402
    ARTICLE_PAGE_MIN_DURATION_MS as MIN_MS,
    ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH as W1260,
    ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH as W1100,
    ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH as W1498,
    ARTICLE_SUBTITLE_EN_WIDTH as W1455,
    ARTICLE_VISUAL_PAGE_MAX_PAGES as MAXP,
    ARTICLE_VISUAL_PAGE_MIN_WORDS as MINW,
    acx,
    article_subtitle_en_font,
    text_w,
)

FONT_SIZE = 56
_img = Image.new("RGB", (8, 8))
DRAW = ImageDraw.Draw(_img)
FONT = article_subtitle_en_font(FONT_SIZE, 600)
CAPS = {"1100_current_gate": acx(W1100), "1260_comfortable": acx(W1260),
        "1455_english": acx(W1455), "1498_wide_safe": acx(W1498)}
_wc: dict[str, int] = {}


def width(t):
    v = _wc.get(t)
    if v is None:
        v = text_w(DRAW, t, FONT)
        _wc[t] = v
    return v


def fits_one_line(toks, a, b, cap):
    return width(" ".join(toks[a:b + 1])) <= cap


def fits_two_lines(toks, a, b, cap):
    """Greedy wrap of this page's own words must land in <= 2 rows."""
    rows, cur = 1, ""
    for tok in toks[a:b + 1]:
        cand = (cur + " " + tok) if cur else tok
        if cur and width(cand) > cap:
            rows += 1
            if rows > 2:
                return False
            cur = tok
        else:
            cur = cand
    return True


def min_pages(toks, st, en, cap, fit, maxp):
    """Fewest pages satisfying width + min-words + min-duration, or None."""
    n = len(toks)
    best = [None] * (n + 1)
    best[0] = 0
    for b in range(n):
        for a in range(b + 1):
            if best[a] is None:
                continue
            if (b - a + 1) < MINW:
                continue
            if (en[b] - st[a]) < MIN_MS:
                continue
            if not fit(toks, a, b, cap):
                continue
            cand = best[a] + 1
            if best[b + 1] is None or cand < best[b + 1]:
                best[b + 1] = cand
    v = best[n]
    return v if (v is not None and v <= maxp) else (v if v is not None else None)


def main():
    dirs = sorted(
        d for d in glob.glob(str(PROJ / "work-dir/*/subtitle/*artifacts"))
        if os.path.exists(os.path.join(d, "display-page-translations.json"))
        and os.path.exists(os.path.join(d, "word-ledger.json"))
    )
    res = {k: Counter() for k in CAPS}
    ctrl = {k: Counter() for k in CAPS}
    tot = Counter()
    hard_examples = []

    for d in dirs:
        dp = json.load(open(os.path.join(d, "display-page-translations.json"),
                            encoding="utf-8"))
        wl = json.load(open(os.path.join(d, "word-ledger.json"), encoding="utf-8"))
        by_id = {int(w["word_id"]): w for w in wl.get("words") or []}
        for r in dp.get("render_plans") or []:
            ws, we = r.get("word_start"), r.get("word_end")
            if ws is None or we is None:
                continue
            ids = [i for i in range(int(ws), int(we) + 1) if i in by_id]
            if len(ids) != int(we) - int(ws) + 1:
                continue
            toks = [str(by_id[i]["surface"]) for i in ids]
            st = [int(by_id[i]["start_ms"]) for i in ids]
            en = [int(by_id[i]["end_ms"]) for i in ids]
            tot["parents"] += 1

            # A parent that is itself under the floors can never satisfy them.
            if len(toks) < MINW or (en[-1] - st[0]) < MIN_MS:
                tot["exempt_too_short"] += 1
                continue
            tot["eligible"] += 1

            for name, cap in CAPS.items():
                p1 = min_pages(toks, st, en, cap, fits_one_line, MAXP)
                p2 = min_pages(toks, st, en, cap, fits_two_lines, MAXP)
                res[name][("feasible_le_max" if (p1 and p1 <= MAXP)
                           else ("needs_more_pages" if p1 else "infeasible"))] += 1
                if p1:
                    res[name][f"pages_{min(p1, 9)}"] += 1
                ctrl[name][("feasible_le_max" if (p2 and p2 <= MAXP)
                            else ("needs_more_pages" if p2 else "infeasible"))] += 1
                if p2:
                    ctrl[name][f"pages_{min(p2, 9)}"] += 1

            p_1455 = min_pages(toks, st, en, CAPS["1455_english"],
                               fits_one_line, MAXP)
            if (p_1455 is None or p_1455 > MAXP) and len(hard_examples) < 40:
                hard_examples.append({
                    "parent_subtitle_id": r.get("parent_subtitle_id"),
                    "words": len(toks),
                    "duration_ms": en[-1] - st[0],
                    "min_single_line_pages_at_1455": p_1455,
                    "english": " ".join(toks)[:200],
                })

    out = {
        "totals": dict(tot),
        "constraints": {"min_words": MINW, "min_duration_ms": MIN_MS,
                        "max_pages": MAXP, "font_size": FONT_SIZE},
        "single_line_only": {k: dict(sorted(v.items())) for k, v in res.items()},
        "control_two_line": {k: dict(sorted(v.items())) for k, v in ctrl.items()},
        "hard_examples_at_1455": hard_examples,
    }
    (OUT / "single_line_feasibility_dp.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
