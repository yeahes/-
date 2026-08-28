## Latest Test Results

Command:

```powershell
runtime\python.exe scripts\run_regression.py
```

Result:

- stable caption smoke tests: pass
- syntax check: pass
- known output audit: completed
- 2026-07-26 recheck: stable caption smoke tests pass; syntax check passes.
- 2026-07-27 WhisperX backend check: FasterWhisper plus WhisperX CUDA alignment completed on `外卖骑手诗人的走红，标志着中国农民工文学的兴起`; subtitle validation passed, video synthesis completed, final SRT had no overlaps and no >1000ms gaps.
- 2026-08-02 boundary regression: sentence-final `over.` no longer triggers
  the preposition-object guard. A frozen replay of `如何识别人工智能写作`
  restored `I mean, the Delve era is over.` as one cue without changing word
  coverage. `runtime\python.exe -X utf8 scripts\run_regression.py` passed.
- 2026-08-02 QA queue/full-flow validation: `build_qa_summary.py` now emits a
  deterministic, time-addressable `qa-review-queue.srt` artifact and
  `SubtitleThread` exports it as `字幕质检队列.srt` beside the source audio.
  The full `如何识别人工智能写作` run completed with 217 fixed subtitle IDs,
  no translation structure errors, zero validation ERRORs, and a successfully
  rendered article-template video. The source report had 33 REVIEW/21 INFO
  items; the user-facing queue contained the first 12 REVIEW items only.
- 2026-08-02 strict A/B comparison guard: added
  `scripts/compare_frozen_mainline_runs.py` and fixture tests. A run now
  records active article-reference settings and hashes in the stable manifest;
  stale article artifacts cannot make a no-article run appear comparable to an
  article-assisted run. Only Chinese-by-ID text is permitted to differ in an
  allocation-only comparison.
- 2026-08-02 manual final subtitle editor: added a local word-ledger-backed
  edit layer for completed stable outputs. It can move a continuous English
  suffix/prefix across one adjacent cue boundary, recomputes that boundary's
  times from frozen word timestamps, rejects free-text pseudo-alignment, and
  writes an explicit manual-final override for video synthesis.
- 2026-08-02 final timing ownership migration: replaced the WhisperX
  time-only final-cue text remap with a frozen-word-ledger path. Final cue
  timing is derived by `subtitle_id -> word_start/word_end`, written to
  `final-cue-timeline.json`, and blocked on lost IDs, `S0000`, own-word
  envelope failure, or unreconcilable word-envelope overlap.

