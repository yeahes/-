## 2026-08-06 WhisperX Expansion-Sensitive Timing Acceptance

- Root cause: final `whisperx-time-only` trusted exact normalized token matches
  even when a compact written numeral, currency value, year, or acronym
  represented several spoken words. The affected token could be compressed to
  a fraction of the frozen stable-ts duration and shift later word times early
  until WhisperX found a new acoustic anchor.
- The final frozen-ledger mapper now rejects only that local drift run and
  restores its original word times. It stops at the first word whose start/end
  drift returns to the pre-trigger anchor and caps one fallback run at 24
  words. Text, word IDs, order, cue ownership, and unrelated WhisperX times are
  immutable.
- The fallback is recorded as `whisperx_expansion_compression_fallback` in the
  final alignment provenance. The new acceptance gate is enabled only for
  final `whisperx-time-only`; the full-WhisperX pre-cut path is unchanged.
- Regression replays the production `53 billion ... 2026 ... 2028` compression:
  affected words restore `412.600-417.020s`, the recovery word `Now` remains
  on WhisperX at `417.580-417.720s`, and text, word IDs, order, and the default
  full-WhisperX mapping remain unchanged. Unified regression and
  `git diff --check` pass; external requests and synthesis were not run.

