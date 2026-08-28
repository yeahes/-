## 2026-08-09 Manual Editor State Ownership Audit

- Audited the manual-final editor as a state machine rather than adding more
  sample-specific pagination rules. The live table draft, pending page plan,
  and published package now have explicit ownership and one session
  fingerprint for clean/dirty decisions.
- Active table delegates commit before structural actions, save, export,
  import-discard, and close. Parent Chinese writes back by fixed ID, frozen word
  range, time, and English identity; text edits are included in undo history.
- Repeated page splits and Chinese edits stay in memory and make no package
  write. Missing page Chinese can persist as a blocked checkpoint; formal
  publication still fails closed.
- Page edits and overrides clear/restore atomically. Save requests own their
  refresh intent, imports are blocked during publication, failed imports retain
  the current path, and stale review callbacks cannot reinstate edited IDs.
- REVIEW boundary metadata and unavailable-page blockers now reach table
  coloring, tooltips, and next-review navigation. Schema-3 manual overrides bind
  the edit journal hash and cross-check both ledgers on reload.
- Read-only replay of the real study-abroad package exposed 303/303 pages and
  20 REVIEW boundaries. A two-parent in-memory edit retained the first Chinese,
  called no save function, and left all 11 package hashes unchanged.
- Manual-final editor tests pass 36/36, stable-publication UI tests pass 43/43,
  video-synthesis safety passes 24/24, and unified regression passes 678/678
  plus syntax in 335.161 seconds. `git diff --check` passes.
- Windows QPA constructed the hidden real editor widget, but strict offscreen
  QPA remained blocked at `QApplication` initialization and the bounded widget
  grab produced no screenshot. This is recorded as an uncompleted visual audit,
  not a pass. No network, ASR, LLM, FFmpeg, synthesis, or paid request ran.

