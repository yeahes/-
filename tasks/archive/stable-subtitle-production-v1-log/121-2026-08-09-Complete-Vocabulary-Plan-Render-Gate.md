## 2026-08-09 Complete Vocabulary Plan Render Gate

- Production `5/9` evidence exposed the remaining ownership defect: v2 progress
  tracked incomplete chunks correctly, but the loader still returned a partial
  display plan and allowed FFmpeg to encode a formal video.
- Removed the 240-second global early-stop budget. Current chunks run
  sequentially with the existing 90-second per-attempt timeout and two explicit
  attempts. Successful empty arrays are complete batches; no quality threshold
  or vocabulary selection rule changed.
- Added `VocabularyPlanIncompleteError`. Failed chunks and missing model
  configuration retain all completed progress and fail synthesis before FFmpeg.
  A retry merges local/global progress, requests only unfinished chunk IDs, and
  returns a plan only when the complete invariant is true. Legacy caches are no
  longer a rendering authority during recovery.
- Syntax compilation and all 29 focused vocabulary/cache/display tests pass,
  including a direct assertion that `subprocess.Popen` is never called for an
  incomplete plan. The unified
  regression ran 365.6 seconds and passed all stages except `stable caption
  smoke tests`; its only failure was the unrelated order-dependent
  `test_whisperx_time_only_uses_explicit_source_audio_from_complete_task`, which
  passed in isolation.
- The fresh 1920x1080 real-data frame
  `tests/caption_audit/out/vocab-complete-gate-sample-20260809.png` was opened and
  checked for clipping, overlap, empty regions, highlight placement, and
  bilingual subtitle layout. External model, ASR, FFmpeg, synthesis, and paid
  requests are zero.

