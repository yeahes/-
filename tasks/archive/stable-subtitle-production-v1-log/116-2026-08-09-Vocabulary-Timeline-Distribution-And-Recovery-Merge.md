## 2026-08-09 Vocabulary Timeline Distribution And Recovery Merge

- Changed the duration target from 1.25 to 1.0 cards per minute. The 912.8-second
  `中国AI为何更省钱？` production subtitle now targets 15 cards. Selection quality
  is unchanged: priority 1-2 candidates, basic-only phrases, duplicates, frozen
  group mismatches, and candidates inside the 15-second interval remain blocked.
- Replaced opening-biased global priority truncation with time-stratified local
  scheduling. Each occupied time stratum contributes its strongest valid
  candidate first; empty strata stay empty, and remaining capacity is filled by
  priority plus distance from already selected cards.
- Fixed recovery display ownership. A legacy cache and completed v2 batches are
  now combined as candidates and passed through the same scheduler. The previous
  `legacy_plan or partial_plan` path hid later recovered cards until every batch
  completed, allowing an early legacy card to remain through the whole tail.
- Real offline inspection found nine legacy candidates, eight scheduled cards,
  and the last legacy card at 409.5 seconds, leaving a 503.6-second tail hold.
  The report is
  `tests/caption_audit/out/vocab-card-schedule-report-20260809.json`; the
  re-rendered 1920x1080 production frame is
  `tests/caption_audit/out/vocab-card-schedule-sample-20260809.png` and was
  visually checked for crop, overlap, and highlighting. The labeled target and
  legacy timing comparison is
  `tests/caption_audit/out/vocab-card-timeline-comparison-20260809.png`.
- Syntax compilation and seven focused vocabulary tests pass. Two unified
  regression attempts both passed the vocabulary smoke stage but failed in
  unrelated dirty-worktree stages: `stable subtitle publication` passed 46/46
  immediately in isolation; `video synthesis publication safety` then failed in
  isolation because its `SimpleNamespace` fixture lacks
  `_set_manual_editor_mode`. No external model, ASR, FFmpeg, synthesis, or paid
  request ran.

