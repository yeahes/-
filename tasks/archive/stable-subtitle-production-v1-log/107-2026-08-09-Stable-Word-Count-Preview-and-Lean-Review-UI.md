## 2026-08-09 Stable Word-Count Preview and Lean Review UI

- Root cause: every SpinBox `valueChanged` event rebuilt the two inline index
  widgets, destroying the control being clicked and making the edit state appear
  to exit. Word-count changes now update highlights, capacity, and confirm text
  on the existing widgets. Only explicit confirmation mutates subtitle data.
- The redundant `quality report` command-bar action is hidden. The report and
  review artifacts, deterministic gates, table colors/tooltips, and `next review`
  navigation remain active.
- Stable publication tests pass 24/24. Parameterized qwindows validation under
  `E:\VideoCaptioner-e2e-runs\manual-page-interaction-followup-20260809`
  passes 411/411 checks at DPR 1.0/1.25/1.5 across 18 reviewed PNGs. The same
  SpinBox and row widgets survive repeated `1 -> 2 -> 3 -> 2` changes without
  clipping, overlap, stale controls, or unintended subtitle mutation.
- Unified regression passes 595 tests across 24 suites plus one syntax check in
  337.197 seconds with zero failures. Final `git diff --check` passes with only
  line-ending notices. External network, ASR, LLM, synthesis, and paid requests
  are zero.

