## 2026-08-04 Stable English Boundary Routing Audit

- Root cause: `SubtitleThread` still invoked the legacy LLM
  `SubtitleOptimizer` when `need_optimize=True`, including stable screen mode.
  This created a second owner for final English text before deterministic
  boundary finalization.
- Fix: `_should_run_legacy_subtitle_optimization()` now permits that optimizer
  only outside stable screen mode. The stable route stays local and
  word-ledger-based; no existing valid cue, ID, word range, timing, Chinese
  field, or renderer behavior changes.
- Root cause: `ScreenSubtitleEditor.edit()` could silently fall through to the
  legacy LLM editor when the word ledger was absent or source-to-word mapping
  was incomplete. Stable mode then had no authoritative complete word ledger.
- Fix: stable mode now fails before any legacy edit unless the ledger exists
  and every source segment maps to it. This belongs at the screen-editor
  ingress because only that module receives both source segments and the
  authoritative ledger; upstream cannot prove their one-to-one mapping.
- Added focused regressions for both routes. Full automated validation passed:
  `tests/test_english_boundary_rules.py`,
  `tests/test_stable_boundary_finalization.py`,
  `tests/test_stable_caption_rules.py`, and `scripts/run_regression.py`.
- Audit note: `split.py` and `split_by_llm.py` remain legacy-mode facilities.
  Stable production excludes `SubtitleSplitter`, and no stable production
  caller imports `split_by_llm.py`; removing either requires an explicit
  legacy-mode migration rather than an audit cleanup.

