## 2026-08-03 Pre-ID Candidate Write Gate And Generic Syntax Guards

- Root cause: local post-processing accepted a repartition after calculating
  `hard_issues_after`; the audit recorded the problem but the candidate still
  replaced the current items. The write path now rejects that candidate before
  mutation and retains the previous items.
- Added `_can_apply_pre_id_repair_candidate()` as the common candidate gate.
  It checks exact word order and coverage, new internal/changed edge
  boundaries, fragment validity, speaker/range continuity, one-word fragments,
  and the hard word limit. Pre-existing untouched edge warnings are excluded
  from the candidate decision.
- The gate is used by pre-ID window repair, balanced short/discourse splits,
  overlong splitting, visual temporal splitting, internal transition splitting,
  and non-finite-prefix rebalance.
- Added parser-backed protections for direct verb particles, compact
  coordinated subjects, short verb-dative-object starts, and `from number to
  number` ranges. The word mapper's compound subtoken fallback now requires a
  delimiter, avoiding false consumption such as `in` inside `stepping`.
- Added regression coverage for all four parser shapes, candidate rejection,
  and preservation of existing long-object behavior.

