# Project State
Status: complete
Last verified: 2026-08-17 23:31:32 Asia/Shanghai
Branch: main
Verified HEAD: 9e1d0b32f4ccf8039176818b3e87c76f8aed2aa5
Working tree: clean except untracked local audit output under `output/`

## Current Goal
Improve long-caption automatic pagination without changing frozen subtitle authority.

## Confirmed Facts
- The v25 planner keeps the existing whole-episode sequence pass, then promotes only an already validated cross-page-count candidate that objectively dominates its baseline.
- Promoted pages retain fixed English, IDs, ledger ownership, word times, parent timing, parent Chinese, and synthesis authority.
- The oil replay changes only S0059 (9+8), S0081 (8+8), and S0135 (10+4 to one 14-word page).
- Pages over 14 words fall 21 to 19; pages below 56px fall 16 to 14; three-line pages stay at 3.

## Approved Decisions
- Keep automatic promotion conservative; unresolved long captions remain manual-review work.
- Rebuild only v24 page-layout/page-Chinese cache identity; preserve unrelated ASR and translation caches.

## Relevant Paths
- `app/core/utils/podcast_learning_video.py`
- `app/core/subtitle_processor/stable_display_page_contract.py`
- `tests/test_article_display_readability_contract.py`
- `output/article-page-shadow-20260817/oil-market-v25-production-audit.json`

## Last Verification
- Article readability, stable page-Chinese, and complete `scripts/run_regression.py` suites passed; `git diff --check` passed.

## Next Action
Restart the GUI and run one new audio through the normal workflow to validate v25 on unseen material.

## Do Not Regress
- Do not mutate fixed English, subtitle IDs, word ledger/times, cue timing, parent Chinese, or manifest-owned synthesis input.

## Unknowns
- Blind-sample behavior on a fresh unseen audio has not yet been measured.
