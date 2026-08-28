## 2026-08-10 Faster-Whisper Shutdown-Crash Recovery

- A fresh `如何停止拖延.m4a` run failed twice after Faster-Whisper r245.2
  reached 100%, wrote its SRT, and printed `Operation finished in:`. Windows
  Error Reporting identified `faster-whisper-xxl.exe`, `ucrtbase.dll`, and
  exception `0xC0000409`; older reports prove the executable had the same
  shutdown failure before the current code.
- The strict exit check introduced in `6bb5ba8` exposed the latent failure but
  discarded a completed transcript before shared ASR validation. The wrapper
  now accepts a nonzero exit only when both completion markers are present and
  the generated SRT passes the existing `BaseASR` validation contract.
- Regression coverage proves that a fully completed valid SRT is recovered,
  while progress-only completion, a missing operation-finished marker, and an
  invalid SRT all remain failures. No exit-code allowlist or synthetic timing
  fallback was added.
- Real local replay reproduced return code `3221226505` and successfully
  returned 3135 native word-timestamp segments with trusted timing. ASR trust
  tests pass 19/19, and the full 25-stage regression exits zero in 360.1
  seconds. Network, LLM, translation, WhisperX, synthesis, paid requests, and
  production cache writes were zero.

