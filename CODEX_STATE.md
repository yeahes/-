# Project State
Status: complete
Last verified: 2026-08-16 21:10:56 Asia/Shanghai
Branch: main
Verified HEAD: a77ec41a5bec620723240320ab2638cc09375778
Working tree after the pending checkpoint commit: only untracked `.workbuddy/`,
intentionally excluded.

## Current Goal
Produce more concise natural Chinese subtitles and raise article-template
Chinese typography without changing frozen English, IDs, timing, or synthesis.

## Confirmed Facts
- Pro full translation uses `semantic-full-translation-v6`; old v5 translation caches are not reused.
- Full-translation payloads carry fixed IDs, exact English, word-ledger display durations, per-ID soft budgets, and a summed group budget.
- Concision removes empty spoken/written scaffolding but preserves facts, entities, numbers, negation, causality, modality, reactions, hedges, and stance.
- Fixed-ID allocation and page projection retain their existing ownership; English and timeline contracts are unchanged.
- Article Chinese is 48px with the existing two-line/1455px limit; page planning is `article-fixed-font-pages-v22`.
- Oil replay preserved all 140 parent fields and produced 157 pages; only `S0134` changed from one 50px three-line page to a two-page 50px/56px plan.
- Fresh oil v6 production preserved all 140 frozen parent IDs, English, and word spans. Parent Chinese fell from 2674 to 2380 CJK characters and actual-page Chinese from 2687 to 2440; pages above 28 CJK characters fell from 7 to 2 and the longest page from 39 to 30.
- Focused translation tests, the complete 26-stage regression, syntax compilation,
  and `git diff --check` exit zero. No paid request or production artifact write
  occurred during implementation; the later GUI run supplied the production A/B.

## Approved Decisions
- Match the reference video's compact documentary Chinese without mechanical truncation or a whole-film extra polish request.
- Keep `.workbuddy/` untracked and do not commit unless the user asks.

## Relevant Paths
- `app/core/subtitle_processor/screen_editor.py`
- `app/core/subtitle_processor/stable_display_page_contract.py`
- `app/core/utils/podcast_learning_video.py`
- `docs/CURRENT_STATE.md`
- `docs/handoffs/2026-08-16-concise-chinese-translation-v6.md`

## Last Verification
Complete 26-stage unified regression passed under v6 at 2026-08-16 21:10:56.
Fresh production artifacts at
`20260816T195901.871590-95b43f33` pass page translation and preserve frozen
English fields against v5 with zero drift.

## Next Action
Constrain display-page Chinese projection so it cannot substantially re-expand
or duplicate a concise authoritative parent translation.

## Do Not Regress
- Never let Chinese concision change English text/order, subtitle IDs, word spans, word timestamps, or final cue timing.

## Unknowns
- Residual page projections can reintroduce filler or repeat facts even when the parent Chinese is concise.
- A few parent translations remain overcompressed or semantically awkward and require stronger fixed-ID semantic review.
- Existing packages retain saved typography until refreshed or regenerated under v22.
