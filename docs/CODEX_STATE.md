# Project State

Status: active
Last verified: 2026-08-04 00:23:13 Asia/Shanghai
Branch: main
Verified HEAD: 34ff08a25ebe9b649ab3bb91114104232491c45a
Working tree: clean after the implementation, root-state, and vocabulary-handoff checkpoints

## Current Goal
Continue verification or refinement of the article-template smart vocabulary-card experience from the documented handoff.

## Last Verification
- Static code and focused-test audit completed for vocabulary selection, scheduling, rendering, subtitle highlighting, UI configuration, and cache behavior.
- `runtime\python.exe scripts\run_regression.py` passed on 2026-08-04; `git diff --check` passed. The known local audit samples `222`, `777`, and `999` remain unavailable and report `MISSING`, as documented.
- The broader stable-subtitle checkpoint is recorded in the root `CODEX_STATE.md`; it is consistent with the current committed implementation.

## Next Action
Use `docs/handoffs/2026-08-04-vocabulary-cards.md` to render and visually review one fresh article-template vocabulary-card sample before making any behavior change.

## Do Not Regress
- Cards cannot change stable English subtitle text, IDs, timing, order, or word ownership.
- Start a card only when its exact source phrase's subtitle starts; keep the active full card until a later card replaces it.
- Keep the article right-panel container and its `#FBF6ED` fill; do not restore an opening vocabulary overview or an active compact review-bar transition.
- Keep phrase highlighting exact, without underlines, including directly attached punctuation only.

## Unknowns
- Fresh end-to-end render evidence after the latest vocabulary UI changes has not been verified in this checkpoint.
- `docs/CURRENT_STATE.md` and one prompt sentence still describe a retired review-bar behavior; current code and tests are authoritative.
