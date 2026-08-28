## 2026-08-16 Reference-Style Display Planning v21

- Replaced the single-best span state with a bounded page-span frontier and
  retained candidates separately by page count and safety tier. Production
  scoring uses the same final font and line wrap stored in frozen render plans.
- Page count is a local measured-load decision; whole-episode continuity only
  selects boundaries within that count. High-pressure cues enumerate reviewed
  and forced alternatives even when an earlier strict partition exists.
- Added complete high-pressure upgrades for all-56px partitions, complete
  two-line replacements for 50px three-line fallbacks, controlled `to ...` and
  `from + gerund` restarts, and explicit rejection of attached modifiers and
  incomplete clause-introducer transitions.
- Mixue read-only replay: 245 pages, 20.0 pages/minute for the first three
  minutes, zero three-line pages, four 50px pages, two-line balance median
  0.796, adjacent word-delta P90 7, and zero frozen-field drift.
- Oil read-only replay: 165 pages, 19.0 pages/minute for the first three
  minutes, three-line pages 4 to 2, 50px pages 7 to 5, two-line balance median
  0.775 to 0.808, adjacent word-delta P90 10 to 8, and zero frozen-field drift.
  Remaining three-line cues have no safe timed page boundary. No source or
  production artifact, ASR, translation, synthesis, network, or paid request
  was used.

