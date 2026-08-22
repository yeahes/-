# Project State
Status: active
Last verified: 2026-08-23 05:42:38 Asia/Shanghai
Branch: main
Verified HEAD: 119ca93
Working tree: clean except unrelated untracked output/

## Current Goal
Repair the verified causes of reduced automatic subtitle quality in independently tested commits.

## Confirmed Facts
- White House English replay removes 6/6 confirmed boundary defects with 2,586/2,586 ordered words preserved.
- Chocolate real-timing replay restores its complete 11+5 display plan; the passing White House guard changes 0/217 frozen page/font signatures.
- Page-Chinese v9 distinguishes HMM-only function-word joins from lexical word splits and source-owned wording plus one Chinese grammar marker from added meaning.
- White House frozen-contract replay passes 42/42 multipage parents and 92/92 page-Chinese IDs with zero contract error.
- Compatible dependency/participial evidence restores the numeric-range 7+10+7 plan; complete predicate evidence restores the expected `into ...` continuation without relaxing unrelated atomic issues.
- Planner v31 invalidates older page blueprints. Article readability passes 106/106 and the full regression passes 30/30 in 1010.71s.

## Approved Decisions
- A routine new-run audit checks one raw automatic result; regression claims require the same word ledger.
- Identity, pagination, parent-boundary, page-Chinese, quantifier, and cross-stage compatibility fixes remain independently tested commits.

## Relevant Paths
- Page translation: `app/core/subtitle_processor/stable_display_page_contract.py`
- Request/retry owner: `app/core/subtitle_processor/screen_editor.py`
- Page planner: `app/core/utils/podcast_learning_video.py`
- Audit: `docs/audits/2026-08-23/recent-actual-page-quality-audit.md`

## Last Verification
- `runtime\python.exe scripts\run_regression.py`: 30/30 PASS; focused planner-version guards: 7/7 PASS.

## Next Action
Restart the application, run one fresh held-out audio through the GUI, and audit its actual bilingual display pages.

## Do Not Regress
- Do not mutate production artifacts or relax word coverage, timing, font, semantic ownership, or genuine lexical-word split checks.

## Unknowns
- Held-out end-to-end GUI quality remains unverified.
