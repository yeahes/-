## 2026-08-10 Silent Tail Duplicate And Reading-Speed Gate

- Traced the later task failure past successful translation, WhisperX, final
  timeline validation, and display-page translation. The visible blocker was
  one `reading_speed_error`, but its timing pressure came from a 14-word
  Faster-Whisper tail duplicate compressed into 260ms of audio silence.
- Added a pre-freeze, Faster-Whisper-only tail guard. It requires extreme word
  rate, overlapping word times, a long repeated phrase, sentence-final
  position, and FFmpeg-confirmed silence. Ambiguous, audible, or non-repeated
  endings are retained.
- Real read-only replay changes 3,135 word entries to 3,121 and removes only
  `We're looking at a daily environment that requires less raw willpower to
  begin with.` The preceding legitimate sentence remains intact.
- Unified stable publication decisions around per-error review tiers. A
  top-level error classified as `REVIEW` no longer becomes render-blocking just
  because the legacy status string is `ERROR`; unknown and structural errors
  remain fail-closed. Unrelated allocation-review blockers do not change the
  existing production gate.
- ASR trust tests pass 22/22, four focused release-gate checks pass, real SRT
  plus audio replay selects the expected 14-word suffix, and the full 25-stage
  regression exits zero in 406.2 seconds. No LLM, translation, WhisperX,
  synthesis, paid request, or production artifact write ran during validation.

