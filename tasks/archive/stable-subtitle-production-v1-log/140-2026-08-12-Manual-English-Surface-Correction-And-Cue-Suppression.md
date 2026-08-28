## 2026-08-12 Manual English Surface Correction And Cue Suppression

- Traced `known literally OnlyFans Stifler's Mom` to an article-context fuzzy
  candidate that consumed the original `only as` because the same article has
  a later genuine `OnlyFans`. Added a generic entity gate: a fuzzy one-token
  entity cannot collapse a multi-token phrase containing function words unless
  their normalized forms are an exact orthographic join. The genuine entity
  occurrence remains unchanged.
- Added a constrained manual English surface edit from parent and actual-page
  views. It can change exactly one frozen word ID's displayed surface while
  preserving word identity, order, timing, and cue/page spans; broader English
  rewrites fail closed and the affected Chinese requires confirmation.
- Added an explicit single-row context-menu dialog, `修正当前英文（保持时间轴）`,
  because the QFluentWidgets row-selection delegate did not reliably expose the
  inline English editor. The dialog applies through the same session contract,
  keeps the current page selected, and surfaces an invalid edit immediately.
- Added `display_suppressed` for hiding an individual cue while preserving
  source audio, frozen word coverage, subtitle ID, and final-timeline record.
  Visible SRT and page rendering omit that cue; undo and restore are supported.
- Focused suites pass: article correction 34/34, manual-editor direct suite,
  stable publication/UI 61/61, and video-synthesis safety. The 25-stage unified
  regression passes in 390.3 seconds after the explicit English-edit dialog
  integration.
- Read-only production replay loaded the existing 258-parent/311-page manual
  package with 88 history operations. The two new in-memory operations hid
  `S0021` and corrected only word ID 353 to `only as`; word ID 828 retained the
  genuine `OnlyFans`, every word ID/time stayed exact, and no unrelated page
  changed. No production artifact was written.

