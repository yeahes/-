## 2026-08-24 - Manual editor interaction latency

- Traced the shared slow path for text edits, page splits, adjacent merges,
  boundary moves, and page confirmations to synchronous Qt model publication.
  `update_incremental()` emitted an edit-role signal while applying the
  authoritative session, so the editor treated its own refresh as a new user
  edit and repeated review invalidation, dirty-state work, and recovery-draft
  scheduling.
- Added an internal-publication guard around the model update. User-originated
  `dataChanged(EditRole)` behavior is unchanged; internal refreshes no longer
  re-enter it. Existing boundary-inspector and preview debounce timers remain
  UI-only coalescing layers.
- Focused verification passes: `tests/test_stable_publication.py` 96 tests
  and `tests/test_manual_final_subtitle_editor.py` 130 tests. No API,
  subtitle, audio, cache, checkpoint, or synthesis artifact was changed.
- Remaining check: restart the working-copy GUI and measure the four reported
  operations interactively.

