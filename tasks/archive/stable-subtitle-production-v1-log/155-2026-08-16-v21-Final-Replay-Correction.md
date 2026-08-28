## 2026-08-16 v21 Final Replay Correction

- Replayed the same two frozen manual-final packages after the three root-layer
  fixes. Frozen parent IDs, English, word ranges, and cue start/end times had
  zero drift.
- Current v21 output is 238 Mixue pages (56 in the first three minutes,
  18.667/minute) and 163 oil pages (54 in the first three minutes, 18.0/minute).
  Mixue has 0 three-line and 5 50px pages; oil has 2 three-line and 6 50px
  pages. Two-line balance medians are 0.806 and 0.803; adjacent word-delta P90
  is 9 for both.
- The page-rate decrease from the earlier replay is intentional and bounded:
  three cues were no longer split solely because their cue duration exceeded
  the comfortable maximum, and incomplete 5-word/attached-modifier review
  partitions remain rejected. This favors readable complete pages over a
  frequency target and does not modify frozen cue timing.
- Replay was read-only and offline. No production artifact, ASR, LLM,
  translation, synthesis, network, or paid request was used.

