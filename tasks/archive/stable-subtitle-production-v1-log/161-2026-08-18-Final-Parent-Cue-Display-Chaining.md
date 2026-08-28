## 2026-08-18 Final Parent-Cue Display Chaining

- Kept the frozen word ledger and final cue timeline as the only timing owner;
  the original non-word-timestamp `optimize_timing()` path remains disabled in
  stable mode.
- The final timeline closes only positive display gaps whose adjacent word
  pause is below 1000ms. It uses the original approximate 75/25 boundary and a
  stricter 200ms maximum incoming lead. A 1000ms-or-longer pause is retained.
- Removed downstream midpoint retiming from final display coverage repair. The
  stage now records chained-boundary evidence and unresolved gaps without
  mutating cue times. A final artifact refresh preserves that evidence.
- Focused timeline and stable-caption regressions cover short-gap chaining,
  lead limiting, long-pause retention, and read-only coverage auditing.
- Read-only replay of 173 real cues closed all 69 short visible gaps, retained
  the single long pause, produced no overlap, and preserved ID order and word
  ranges. No production artifact was rewritten.

