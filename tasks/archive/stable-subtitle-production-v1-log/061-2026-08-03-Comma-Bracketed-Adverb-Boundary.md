## 2026-08-03 Comma-Bracketed Adverb Boundary

- Root cause: the stable greedy cutter gives commas a boundary reward. In a
  repeated phrase such as `for me, adverb, for anyone`, that could make the
  sentence-internal adverb the first word of the next cue.
- Added a narrow parser-backed guard for a punctuation-bracketed `ADV/advmod`
  immediately followed by its `ADP` head, with no long pause. The guard rejects
  only the boundary before the adverb and preserves ordinary sentence-initial
  adverbs and adverb-verb boundaries.

