## 2026-08-09 Local Manual Page State Ownership Repair

- Reproduced the `S0079/S0080` failure from the saved manual package: moving a
  word across formal parents caused the editor to clear all page edits and
  overrides, fall back to parent rows, and lose unrelated visible Chinese.
- Moved invalidation ownership into `ManualFinalSubtitleSession`. A formal
  boundary edit now snapshots the complete actual-page table, derives local
  ranges for only the two changed parents, stores explicit one-page overrides
  where needed, and preserves all unaffected page identities and translations.
- Changed affected page Chinese to visible, unconfirmed drafts. Save continues
  to return `manual_page_translation_required` until those drafts are confirmed;
  the draft page artifact remains available for preview.
- Added exact history recovery for already-damaged packages. It recovers only
  blank current pages with matching page ID, parent ID, frozen word range, and
  English. Current production-package replay recovered 77/77 blank pages and
  left zero blanks or unavailable rows without writing the package.
- Replaced visual row numbers with stable parent/page IDs in the table header.
  Focused tests, 54 stable-publication/UI tests, the complete manual-editor
  script, and the 25-stage unified regression pass. Final unified duration is
  359.2 seconds; external requests and production writes are zero.

