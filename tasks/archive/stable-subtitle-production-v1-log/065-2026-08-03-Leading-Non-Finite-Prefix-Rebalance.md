## 2026-08-03 Leading Non-Finite Prefix Rebalance

- Added a post-gate, pre-ID local rebalance for a short comma-terminated
  non-finite conditional prefix at the start of a cue. It only moves the prefix
  to the preceding incomplete clause when spaCy confirms a clause marker with
  no subject or finite predicate, the following cue is a complete main clause,
  the speaker and word ledger are continuous, the pause is below 450ms, and
  both resulting cues remain within the normal word limit.
- This repairs a generic shape such as an ellipted condition separated from its
  governing action without treating finite conditional introductions as errors.
  The repaired boundary records the parser-backed exception that prevents a
  text-only preposition heuristic from re-reporting the same cut.

