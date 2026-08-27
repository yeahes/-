## 2026-08-12 WhisperX Numeric Pause Preservation

- Reproduced the delayed second subtitle from the authoritative ledgers. Native
  Faster-Whisper ended `field,` at 1.080s and started `73%` at 1.560s;
  WhisperX instead ended `field,` at 2.001s and started `73%` at 2.041s, so
  final display began about 461ms after the spoken numeric onset.
- Added a frozen-ledger handoff invariant for numbers, percentages, currency
  forms, and acronyms. A trusted 200ms-or-longer pause cannot be substantially
  erased when the resulting onset delay is at least 150ms and the preceding
  word start does not corroborate the same local shift. Only the two boundary
  owners can revert to trusted upstream timing.
- Exact tests cover `field, / 73%`, unmatched `move. / 72%.`, and a
  corroborated-shift non-regression. Complete stable-caption rules, ASR trust
  38/38, final-cue timeline tests, and `git diff --check` pass. No production
  subtitle, audio, video, cache, ASR, LLM, or paid request was written or run.
- The complete 25-stage unified regression passes in 367.4 seconds.

