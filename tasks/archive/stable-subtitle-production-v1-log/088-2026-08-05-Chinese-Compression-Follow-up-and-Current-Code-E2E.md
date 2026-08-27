## 2026-08-05 Chinese Compression Follow-up and Current-Code E2E

- Root cause: Chinese compression was evaluated before final display-duration
  reconciliation, and a single valid cue could be rejected by a multi-cue
  allocation coverage gate. LLM compression also occasionally omitted only
  the terminal punctuation of the frozen complete cue.
- Fix: run compression after display reconciliation; preserve terminal Chinese
  punctuation; allow a single cue only when local fragment, duplicate, semantic,
  and speed checks all pass. English text, boundaries, IDs, word spans, and
  alignment ownership remain unchanged.
- Focused tests, unified regression, and `git diff --check` passed.
- Cached current-code E2E for `中国AI为何更省钱？.m4a` completed with 273/273
  fixed IDs and Chinese mappings, `final-cue-timeline.json` validation `PASS`,
  `applied_backend=whisperx-time-only`, `fallback_used=false`, and zero
  `source_audio_missing`. Synthesis produced a 61,356,806-byte MP4 under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805`.
- Vocabulary-card generation timed out and was skipped after 301.7 seconds;
  this did not block subtitle rendering. The QA queue retains 40 review items
  and two unresolved allocation-quality items.

