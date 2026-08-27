## 2026-08-10 Actual-Page Merge And Local Undo Interaction

- Added `merge_display_page_with_next()` as a visual-only operation. It removes
  one internal page boundary while preserving the fixed parent subtitle, word
  ledger, English, and timeline. Cross-parent selections continue through the
  formal adjacent-parent merge path.
- Formal parent merging now remaps only selected page rows and locally rebuilds
  the retained parent. A failed local rebuild rolls back cue state, page edits,
  page overrides, and history instead of leaving a half-merged session.
- Removed the visible global undo entry. The row inspector enables undo only
  when the current parent owns the newest history entry; arbitrary out-of-order
  row rollback is rejected. Selection after editing is restored by stable page,
  parent, and word identity rather than the previous table index.
- Focused session tests pass 3/3, focused UI tests pass 6/6,
  `tests.test_stable_publication` passes 57/57, the manual-editor script passes,
  and the unified regression completes 25/25 stages in 353.4 seconds.
- Read-only production-package replay loads 303 actual pages. Merging
  `S0001.P01` changes only that parent's pages, keeps 300 unrelated pages and
  the complete parent/ledger state byte-for-byte equivalent in memory, and undo
  restores all 303 pages. No package write, external request, ASR, LLM,
  synthesis, or paid request occurred.

