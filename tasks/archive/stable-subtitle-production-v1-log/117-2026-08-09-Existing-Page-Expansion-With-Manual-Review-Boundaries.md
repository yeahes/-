## 2026-08-09 Existing-Page Expansion With Manual Review Boundaries

- Reproduced desktop rows 224 (`S0196.P01`) and 251 (`S0216.P02`). Both parents
  already contained two pages, so the former `split into 2 pages` action was a
  no-op while the UI still reported success. The menu now offers one or two
  additional pages relative to the current parent count and handles
  `changed=False` without mutating editor or synthesis state.
- The remaining `manual_page_boundary_is_hard` failure came from a contract
  mismatch: manual planning used `allow_review_boundary=True`, but the frozen
  plan rebuild did not receive `allow_manual_review=True`. The rebuild now
  receives that explicit manual authorization; automatic planning and all hard
  word-range, timing, layout, and fixed-parent invariants remain unchanged.
- Added a session-level regression that failed on the old call and passes after
  the fix. It verifies complete non-overlapping word coverage and unchanged
  frozen parent fields. The manual-editor script, 49 stable-publication/UI
  tests, video-synthesis safety, the unified 25-stage regression, and
  `git diff --check` pass.
- Read-only in-memory replay expands both real parents from two to three pages,
  changes 309 rows to 310, and leaves the other 307 rows, full word ledger, and
  package files unchanged. External requests, ASR, LLM, FFmpeg, synthesis, and
  paid requests are zero.

