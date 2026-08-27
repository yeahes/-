## 2026-08-20 Page Restart And Manual Publication Diagnostics

- Reproduced three renderer-only failures from the saved White House artifact.
  `S0125` lost a valid coordinated restart because its frozen parent ended at
  a comma; `S0189` treated a common list noun as a name apposition; `S0193`
  promoted an attached `to` phrase over a balanced predicate restart.
- Replaced the generic tight-phrase promotion with named safe categories and
  restricted name-apposition syntax protection to proper nouns. Real replay
  now selects 8+11, 14+7+10 and 8+13 word pages respectively, without changing
  the frozen cue text, ID, ledger span or timing.
- Added one blocker-summary and focus path for preflight save errors,
  background save results, synthesis entry and synthesis-action tooltips.
  Exact `Sxxxx.Pxx` evidence is shown and the first page is selected when the
  session or manifest can identify it; failed saves explicitly retain the
  current in-memory edits.
- Stable-caption smoke tests, 90 editor/publication tests, the complete article
  readability contract, focused UI entry tests and real cue replay pass. The
  final project regression passes all 29 checks in 883.19 seconds. Verification
  made no paid API request and changed no production artifact.

