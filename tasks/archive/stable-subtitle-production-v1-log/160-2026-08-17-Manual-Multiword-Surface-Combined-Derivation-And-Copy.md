## 2026-08-17 Manual Multiword Surface, Combined Derivation, And Copy

- Added a raw-to-display span projection for deliberate many-to-one English
  correction. The raw word ledger and every timing/identity field remain
  immutable; pagination retains raw first/last word IDs while rendering the
  projected display tokens.
- Routed ordinary one-word edits, parent merges, formal boundary changes,
  tail deletion, render-plan rebuild, save/reload, and undo/redo through the
  same display projection. A boundary or tail cut cannot split a display span.
- Replaced the old mute/tail-trim mutual exclusion with one schema-v2 media
  derivation decision containing ordered mute intervals and an optional cut.
  FFmpeg applies `volume`, `atrim`, and `asetpts` in one pass from original
  media; legacy mute-only packages prefer their recorded original on upgrade.
- Added whole-row extended selection, `Ctrl+C`, and `复制英文`. Selected English
  is copied in display order without invoking model writeback or manual-final
  history.
- Added regressions for span preservation through a separate word edit and
  parent merge, atomic tail cuts, legacy-source recovery, and read-only
  multi-row copy. Focused editor, UI/publication, synthesis-safety,
  page-translation, and readability suites pass.

