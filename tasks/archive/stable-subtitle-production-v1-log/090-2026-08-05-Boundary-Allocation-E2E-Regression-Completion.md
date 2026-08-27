## 2026-08-05 Boundary/Allocation E2E Regression Completion

- English pre-ID fixes are now isolated from the Chinese allocation contract:
  numeric result guards stop at punctuation/coordinators, content nouns stay
  with attached `that` clauses, and a complete `Oh.` lead-in may use the
  existing one-word structural overflow exception.
- Full-group Chinese translation cache keys no longer change when only the
  fixed-ID allocation algorithm changes. Verified legacy full-translation keys
  migrate once; allocation keys remain invalidated by the current frozen spans
  and algorithm version. Allocation validation rejects bare syntactic heads and
  displaced main clauses.
- Visual pagination protects English modifier heads and Chinese token boundaries
  using the vendored tokenizer. Unsafe Chinese page cuts fail closed without
  mutating frozen cue data.
- Current-code cached E2E for `中国AI为何更省钱？.m4a` completed at
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805-r3`: 271 IDs,
  2,897 ledger words, final timeline `PASS`,
  `applied_backend=whisperx-time-only`, no overall fallback, and no
  `source_audio_missing`. The 64.8-66.5s interval remains covered by S0019
  through 67.975s.
- Synthesis completed once at
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805-r3\final-video.mp4`
  (62,239,995 bytes; 16:43.66; 1920x1080 H.264/AAC). Vocabulary generation
  timed out after 319.1s and was skipped. Subtitle cache statistics recorded
  21 misses (13 full translations, 1 style retry, 4 allocations, 3 fragment
  retries); vocabulary per-attempt count is not instrumented.
- `runtime\python.exe -X utf8 scripts\run_regression.py` and `git diff --check`
  passed. QA has zero structural blockers and three unresolved Chinese
  allocation-quality reviews.

