## 2026-08-04 Fixed-ID Chinese Postprocess Audit

- Root cause: speed compression and same-group redistribution still accepted
  legacy positional response fields (`index`, `target_index`, and `id`). A
  stale cache could therefore target a different frozen subtitle after cue
  ordering changed. A separate phrase-specific local speed fallback could also
  shorten Chinese despite a semantic-omission finding.
- Compression, redistribution, and high-confidence Chinese repair now require
  explicit existing global `subtitle_id` values for every returned target and
  segment. Missing or unknown IDs are recorded as translation-structure errors
  and cannot write back. Prompts no longer describe an index response schema.
- Removed the phrase-specific local speed rewrite and its dead omission
  exception. When no ID-valid candidate is returned, the original Chinese is
  retained; the normal warning/error and fixed-ID candidate comparator remain
  the only decision path.
- The frozen invariant remains: Chinese-only candidates may alter only a
  current group dictionary keyed by existing subtitle IDs. English text/order,
  word ranges, cue times, IDs, and cache/concurrency ordering are unchanged.
- Added regression coverage for index-only compression and reallocation
  responses. Both are rejected without writeback.

