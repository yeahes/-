## 2026-08-09 Resumable Vocabulary Batch Cache

- Production evidence from `中国AI为何更省钱？` showed 199 cues and 160 semantic
  groups split into seven requests. The old 240-second budget left nine raw
  cards concentrated in the first half, then wrote that subset as an ordinary
  cache with no batch-completion evidence. Later renders therefore skipped all
  missing batches.
- Added vocabulary cache schema v2 with stable content-derived chunk IDs,
  timeline-balanced request order, per-chunk cards, completed IDs, and an exact
  `complete` invariant. Successful empty chunks are completed; failed or
  unattempted chunks remain resumable.
- Every completed chunk is atomically written to separate local/global progress
  caches. Existing prompt-v16 caches remain display fallbacks and are preserved
  while progress is partial. Formal cache replacement occurs only after all
  current chunks complete.
- Seven focused tests pass for partial survival, resume-only-missing behavior,
  empty completion, balanced order, legacy fallback, empty legacy regeneration,
  and atomic replacement failure. Offline replay on the real 199-cue subtitle
  preserved the legacy cache at 3/7, requested only four chunks on pass two, and
  completed 7/7 with the same eight-card scheduled result.
- The 1920x1080 sample at
  `tests/caption_audit/out/vocab-cache-recovery-sample.png` was opened and
  reviewed: the real article cover, full card, English highlight, and Chinese
  subtitle render without clipping or overlap. Replay evidence is stored in
  `tests/caption_audit/out/vocab-cache-recovery-replay.json`.
- Unified regression passes all 25 stages with exit code `0` in 368.3 seconds.
  Existing log-rotation file-lock warnings did not fail tests. No network, ASR,
  LLM, FFmpeg, synthesis, or paid request ran.

