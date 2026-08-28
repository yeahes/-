## 2026-08-04 Single-Cue Allocation Containment

- Root cause: allocation validation applied a cross-cue terminal-modifier
  heuristic to a one-cue authoritative full translation. A complete sentence
  ending in `的` could therefore be marked as a fragment. The caller then
  returned an empty allocation dictionary, discarding successful mappings from
  other groups and creating a cascade of missing Chinese IDs.
- A one-cue group now writes its authoritative full translation directly to
  its only frozen ID without allocation-fragment validation. Full translation
  generation remains responsible for that sentence's meaning and fluency.
- An invalid one-cue group and an unavailable sequential allocation batch now
  record only their own unresolved groups; they no longer erase already
  accepted mappings. Final ID validation still blocks export for any missing
  Chinese cue.
- Regressions cover a complete `...写作的。` translation and containment of an
  invalid one-cue group while a following frozen ID remains allocated.

