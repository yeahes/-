# Progress Log

Historical rounds are archived under
`tasks/archive/stable-subtitle-production-v1-log/`; this file keeps the newest
round only.

## 2026-08-26 - Resume from the failed stable stage

- Root cause: durable resume allowed only article analysis and ASR correction.
  Retrying a display-page failure therefore reran stable English freezing,
  parent translation/allocation, fixed-ID publication, and WhisperX even though
  those stages had already passed.
- Added a hash-bound `frozen_parent_timeline` checkpoint immediately before
  display-page translation. Restore validates frozen English, IDs, word spans,
  word/source coverage, parent Chinese, semantic groups, boundary evidence, and
  the final timeline; any mismatch rejects reuse. Failed page output is not
  restored, while valid per-batch page caches remain reusable.
- The current unreviewed `中国职场女性为何悄然掉队？` checkpoint restored
  offline with 271 IDs, 2855 words, 245 semantic groups, 2845 source segments,
  and a PASS 271-record timeline. All 44 files remained byte-identical.
- Retry clears the qfluentwidgets error state as well as its value, and the
  checkpoint progress stage is fixed at 96% instead of prematurely reaching
  100%. Focused run-state tests pass 9/9 and publication tests pass 102/102.
- The remaining real blocker is local pagination for `S0089`
  (`no_complete_normal_font_page_partition`), not an API failure. Retry now
  reaches that stage directly but cannot resolve the unchanged planner defect.
