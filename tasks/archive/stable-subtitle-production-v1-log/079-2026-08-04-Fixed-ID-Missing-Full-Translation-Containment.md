## 2026-08-04 Fixed-ID Missing Full-Translation Containment

- Root cause: `_allocate_semantic_group_translations()` returned an empty
  dictionary if any semantic group had no authoritative full translation. This
  discarded direct fixed-ID mappings already accepted for earlier groups.
- Fix: the allocation owner records the missing group's expected IDs as a
  blocking structure error and unresolved allocation, then continues with the
  remaining groups. Existing fixed-ID mappings remain intact; final validation
  still blocks the missing Chinese cue.
- Regression: a prior single-cue group keeps `S0001` while the later missing
  full translation is reported only for `S0002`.
