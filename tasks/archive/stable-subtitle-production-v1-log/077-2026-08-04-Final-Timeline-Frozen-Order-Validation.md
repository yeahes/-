## 2026-08-04 Final Timeline Frozen-Order Validation

- Root cause: final timeline validation checked ID membership, word-span
  continuity, and display timing, but did not compare returned cue-ID order to
  the frozen subtitle-ID sequence. A paired ID/span reorder could therefore
  preserve contiguous words and pass validation while breaking the fixed-ID
  export contract.
- Fix: final timeline validation now emits
  `final_timeline_subtitle_order_mismatch` when the exact returned ID sequence
  differs from the frozen sequence. This blocks SRT/ASS export without
  changing word timestamps, display timing, English, Chinese, or cue ranges.
- Regression: a two-cue paired ID/span reorder is rejected even though its
  word coverage and timestamps are otherwise valid.

