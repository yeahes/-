## 2026-08-11 Missing Speech And Compressed Word-Timing Repair

- Reproduced the 08:51 omission as a Faster-Whisper history-context failure:
  the normal full-file pass jumped from `Wow.` to `You are borrowing...`, while
  a bounded context-free pass recovered 23 spoken words in the acoustic gap.
- Added a pre-freeze local repair that requires a long internal word gap,
  FFmpeg activity, and exact text anchors on both sides. It never gives the
  local model authority over existing words. Unanchored output is logged only;
  anchored inserted words retain acoustic times and the repaired SRT replaces
  the raw ASR cache value.
- Traced subtitle 281 to stable-ts: six words shared 1077.980-1078.100, and its
  eight-word cue covered only 741ms. Stable-ts now reverts a compressed local
  update to trusted native Faster-Whisper times; WhisperX reverts the same
  defect to the frozen ledger. A bad baseline cannot be used as fallback.
- Added one shared detector at the actual timing owner. The fixed thresholds
  are four words in at most 250ms, or eight words in at most 750ms at ten or
  more words per second. Historical audit of 99 ledgers found no plausible
  normal-speed false positive, but exposed a 40-word chain caused by merging
  overlapping windows. The detector now returns a minimum core and callers
  repair and detect again, preventing broad timing rollback.
- Final verification: ASR trust 33/33, final cue timeline pass, complete stable
  caption rules pass, Python compilation pass, and all 25 unified regression
  stages pass in 362.2 seconds. No translation, display-page, renderer, source
  audio, or production artifact was changed during these tests.

