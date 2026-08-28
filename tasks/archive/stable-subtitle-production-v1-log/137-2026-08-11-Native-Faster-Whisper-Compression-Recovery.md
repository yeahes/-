## 2026-08-11 Native Faster-Whisper Compression Recovery

- `好莱坞最新热潮：姐弟恋` completed its 931-second Faster-Whisper pass, but
  four words at 14:34 occupied 240ms. The raw SRT emitted `She realizes that
  the` in the correct order; millisecond zero-width repair advanced `that`
  past the same-start `the`, and the generic ASR container then time-sorted the
  words into `She realizes the that`.
- Zero-width repair now preserves emission order when a later nonzero word has
  the same start. Residual native compression triggers a bounded local run with
  `condition_on_previous_text=False` before cache and ledger freeze. Automatic
  recovery requires unique exact anchors, identical word count and word
  multiset, valid monotonic times, and no remaining local density failure. It
  may restore order and timing but cannot add, remove, or substitute a word.
- A global `condition_on_previous_text=False` run repaired the sample and was
  faster, but was rejected as the production default because upstream documents
  a cross-window consistency trade-off. The local fail-closed recovery changes
  only an already-proven defective span.
- Focused ASR trust tests pass 38/38. Read-only replay of production cache row
  481 restored `She realizes that the sex itself`, left zero residual timing
  issues, and did not write cache, subtitles, translation, or video artifacts.
  Final-cue timeline and complete stable-caption rules pass. All 25 unified
  regression stages pass in 364.5 seconds; no external ASR, LLM, translation,
  synthesis, paid request, or production artifact write ran during tests.

