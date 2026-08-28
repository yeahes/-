## 2026-08-04 Pre-ID Structural Fragment Merge

- Root cause: direct final-boundary repair correctly identified a trailing
  English fragment but rejected the only complete 19-word merge under the
  ordinary 16-word candidate gate. That left a known residual phrase split
  even when no grammar-safe normal-limit boundary existed.
- The candidate gate now permits exactly one direct, continuous, pre-ID
  two-cue-to-one merge when the source boundary has a high-confidence fragment
  issue and the shared structural-overflow check confirms a complete 17-19
  word sentence with no legal <=16-word split.
- The exception is not available to visual temporal splitting, general
  repartitioning, ID-assigned cues, Chinese allocation, timing, or export.
- Focused tests cover the allowed 19-word merge, rejection above 19 words,
  and rejection when a legal normal-limit split exists.

