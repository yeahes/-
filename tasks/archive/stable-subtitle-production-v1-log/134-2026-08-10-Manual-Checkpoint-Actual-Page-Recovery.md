## 2026-08-10 Manual Checkpoint Actual-Page Recovery

- Diagnosed the post-save parent-view fallback from the real `如何停止拖延`
  package. The 21:30:31 edit artifact still owns 283 cues, 92 history entries,
  353 page edits, 38 overrides, and tail trim; only the derived page artifact
  lost its render-plan list.
- Added a fail-closed recovery path that rebuilds an editor preview from exact
  saved page word ranges only after page IDs, parent IDs, English, continuous
  ledger coverage, boundary evidence, and cue coverage all match. It does not
  change frozen English, IDs, word timing, page boundaries, or confirmation
  state.
- Real read-only replay restores 353/353 page rows and all 19 visible stale
  Chinese drafts with zero blank rows. Formal synthesis stays blocked by
  `manual_page_translation_required`.
- Added a regression that deletes the derived page plan from a blocked package,
  reloads from the complete edits, saves again, and proves exact page identity
  survives. The full manual-editor script, syntax compilation, and 58 UI and
  publication tests pass. The required 25-stage regression passes in 361
  seconds. No external request or production write ran.

