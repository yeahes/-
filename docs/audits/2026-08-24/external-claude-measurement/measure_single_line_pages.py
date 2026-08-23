"""READ-ONLY measurement for report section 12.  The project is NOT modified.

Two questions, both answered with the project's OWN font metrics
(`article_subtitle_en_font` + `text_w` + `acx`, i.e. real PIL RobotoSlab-SemiBold
advance widths, not the CJK-oriented estimator in ass_auto_wrap.py:70).

A. The intra-page wrapper returns a single line only when the text fits inside
   ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH = 1100 design px
   (podcast_learning_video.py:3591) -- while the panel itself is 1260 / 1455 /
   1498 wide (_article_english_layout_width, 3703-3717).  So: of the pages
   production actually rendered as TWO lines, how many would fit on ONE line if
   that single gate were raised to 1260 / 1455 / 1498?  This is a one-constant
   change, no architecture change.

B. If pagination went single-line-only, how many pages would each frozen parent
   need?  Greedy packing minimises the line count exactly when breaks may fall at
   any word gap, so the number reported is a LOWER BOUND on what a real planner
   (which also has to respect break legality) would need.  A lower bound is the
   useful direction: if even it blows past ARTICLE_VISUAL_PAGE_MAX_PAGES = 4,
   single-line-only is infeasible without raising the cap.

Also records, per planner_version, the three declared page constraints
(max_lines / minimum_page_duration_ms / ARTICLE_VISUAL_PAGE_MIN_WORDS) against
what the frozen artifacts actually contain.
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJ = Path("/sessions/magical-zen-dijkstra/mnt/VideoCaptioner-screen-subtitle")
OUT = Path("/sessions/magical-zen-dijkstra/mnt/outputs")
os.environ.setdefault("OPENAI_API_KEY", "x")
sys.path.insert(0, str(PROJ))

from PIL import Image, ImageDraw  # noqa: E402
from app.core.utils.podcast_learning_video import (  # noqa: E402
    ARTICLE_PAGE_MIN_DURATION_MS,
    ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
    ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH,
    ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
    ARTICLE_SUBTITLE_EN_WIDTH,
    ARTICLE_VISUAL_PAGE_MAX_PAGES,
    ARTICLE_VISUAL_PAGE_MIN_WORDS,
    acx,
    article_subtitle_en_font,
    text_w,
)

PROFILES = [
    ("1100_current_gate", ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH),
    ("1260_comfortable", ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH),
    ("1455_english", ARTICLE_SUBTITLE_EN_WIDTH),
    ("1498_wide_safe", ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH),
]
FONT_SIZE = 56

_img = Image.new("RGB", (8, 8))
DRAW = ImageDraw.Draw(_img)
FONT = article_subtitle_en_font(FONT_SIZE, 600)
CAPS = {name: acx(w) for name, w in PROFILES}
_wcache: dict[str, int] = {}


def width(text: str) -> int:
    hit = _wcache.get(text)
    if hit is None:
        hit = text_w(DRAW, text, FONT)
        _wcache[text] = hit
    return hit


def greedy_lines(tokens, cap):
    """Minimum number of single-line rows; greedy is optimal for line count."""
    rows, cur = [], ""
    for tok in tokens:
        cand = (cur + " " + tok) if cur else tok
        if cur and width(cand) > cap:
            rows.append(cur)
            cur = tok
        else:
            cur = cand
    if cur:
        rows.append(cur)
    return rows


def row_spans(tokens, cap):
    """Same packing, but return token index ranges so timing can be checked."""
    spans, start, cur = [], 0, ""
    for i, tok in enumerate(tokens):
        cand = (cur + " " + tok) if cur else tok
        if cur and width(cand) > cap:
            spans.append((start, i - 1))
            start, cur = i, tok
        else:
            cur = cand
    if cur:
        spans.append((start, len(tokens) - 1))
    return spans


def main():
    dirs = sorted(
        d for d in glob.glob(str(PROJ / "work-dir/*/subtitle/*artifacts"))
        if os.path.exists(os.path.join(d, "display-page-translations.json"))
        and os.path.exists(os.path.join(d, "word-ledger.json"))
    )

    # ---- A: production pages, one-line width -----------------------------
    fitA = {name: Counter() for name, _ in CAPS.items()}
    prod_lines = Counter()
    page_px = []

    # ---- B: single-line-only page count per parent ------------------------
    pagesB = {name: Counter() for name, _ in CAPS.items()}
    violB = {name: Counter() for name, _ in CAPS.items()}
    two_line_pages = Counter()
    prod_page_count = Counter()

    # ---- declared-vs-actual per planner version ---------------------------
    per_ver = defaultdict(Counter)
    fidelity = Counter()
    parents = 0

    for d in dirs:
        dp = json.load(open(os.path.join(d, "display-page-translations.json"),
                            encoding="utf-8"))
        wl = json.load(open(os.path.join(d, "word-ledger.json"), encoding="utf-8"))
        ver = dp.get("planner_version") or "None"
        by_id = {int(w["word_id"]): w for w in wl.get("words") or []}

        for r in dp.get("render_plans") or []:
            parents += 1
            ws, we = r.get("word_start"), r.get("word_end")
            prod_page_count[len(r.get("pages") or [])] += 1

            for p in r.get("pages") or []:
                el = p.get("english_lines")
                n = len(el) if isinstance(el, list) else -1
                prod_lines[n] += 1
                per_ver[ver]["pages"] += 1
                if n > 2:
                    per_ver[ver]["lines_gt_2"] += 1
                if n == 0:
                    per_ver[ver]["lines_eq_0"] += 1
                txt = " ".join(str(x) for x in (el or [])) or str(p.get("english") or "")
                txt = " ".join(txt.split())
                if txt:
                    px = width(txt)
                    page_px.append(px)
                    for name, cap in CAPS.items():
                        fitA[name][("fits" if px <= cap else "no", n)] += 1
                pw = (p.get("word_end") or 0) - (p.get("word_start") or 0) + 1
                if p.get("word_start") is not None and pw < ARTICLE_VISUAL_PAGE_MIN_WORDS:
                    per_ver[ver]["words_lt_min"] += 1
                if p.get("start_ms") is not None and p.get("end_ms") is not None:
                    if p["end_ms"] - p["start_ms"] < ARTICLE_PAGE_MIN_DURATION_MS:
                        per_ver[ver]["dur_lt_min"] += 1

            if ws is None or we is None:
                continue
            ids = [i for i in range(int(ws), int(we) + 1) if i in by_id]
            if len(ids) != int(we) - int(ws) + 1:
                fidelity["ledger_gap"] += 1
                continue
            toks = [str(by_id[i]["surface"]) for i in ids]
            joined = " ".join(toks)
            fidelity["match" if joined == " ".join(str(r.get("english") or "").split())
                      else "text_differs"] += 1

            for name, cap in CAPS.items():
                spans = row_spans(toks, cap)
                pagesB[name][min(len(spans), 9)] += 1
                if len(spans) > ARTICLE_VISUAL_PAGE_MAX_PAGES:
                    violB[name]["parent_over_max_pages"] += 1
                for a, b in spans:
                    if (b - a + 1) < ARTICLE_VISUAL_PAGE_MIN_WORDS:
                        violB[name]["page_under_min_words"] += 1
                    dur = int(by_id[ids[b]]["end_ms"]) - int(by_id[ids[a]]["start_ms"])
                    if dur < ARTICLE_PAGE_MIN_DURATION_MS:
                        violB[name]["page_under_min_duration"] += 1
                    violB[name]["pages_total"] += 1
                if name == "1260_comfortable":
                    two_line_pages[min((len(spans) + 1) // 2, 9)] += 1

    out = {
        "artifact_sets": len(dirs),
        "parents": parents,
        "font_size": FONT_SIZE,
        "font_file": getattr(FONT, "path", None),
        "caps_render_px": CAPS,
        "ledger_text_fidelity": dict(fidelity),
        "production_lines_per_page": dict(prod_lines),
        "production_pages_per_parent": dict(sorted(prod_page_count.items())),
        "A_one_line_fit_by_threshold": {
            name: {
                "fits_total": sum(v for (k, _n), v in c.items() if k == "fits"),
                "of_production_1line_fits": c.get(("fits", 1), 0),
                "of_production_2line_fits": c.get(("fits", 2), 0),
                "of_production_2line_total": c.get(("fits", 2), 0) + c.get(("no", 2), 0),
            }
            for name, c in fitA.items()
        },
        "B_min_single_line_pages_per_parent": {
            name: dict(sorted(c.items())) for name, c in pagesB.items()
        },
        "B_constraint_violations": {name: dict(c) for name, c in violB.items()},
        "B_control_min_two_line_pages_at_1260": dict(sorted(two_line_pages.items())),
        "declared_vs_actual_per_planner_version": {
            k: dict(v) for k, v in sorted(per_ver.items())
        },
    }
    page_px.sort()
    if page_px:
        q = lambda p: page_px[min(len(page_px) - 1, int(len(page_px) * p))]
        out["page_one_line_px"] = {
            "min": page_px[0], "p25": q(.25), "median": q(.5),
            "p75": q(.75), "p90": q(.9), "p99": q(.99), "max": page_px[-1],
        }
    (OUT / "single_line_pagination_feasibility.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
