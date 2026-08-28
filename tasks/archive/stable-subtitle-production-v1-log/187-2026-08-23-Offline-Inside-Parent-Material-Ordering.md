## 2026-08-23 Offline Inside-Parent Material Ordering

- Extended `scripts/audit_article_page_candidate_frontier.py` with a read-only
  `material-readability-non-regression-v1` selector. It considers only existing
  production-generated candidates and does not change English, word ranges,
  IDs, timing, Chinese ownership, or production selection.
- The initial whole-episode A/B changed five of 217 newest White House parents:
  `S0051`, `S0072`, `S0097`, `S0201`, and `S0205`. Aggregate page count fell
  from 264 to 263 and over-16-word pages from 14 to 12, but actual-page review
  found that `S0051` merely exchanged a 4+17 split for the false 16+5 fragment
  `in tariff rates would backfire.`
- Root cause in the offline selector: the real baseline and candidate each had
  one unsupported REVIEW boundary, so a relative `1 <= 1` non-regression check
  admitted the false fragment. The selector now requires zero unsupported
  REVIEW boundaries for every promoted candidate. The real `S0051` replay
  retains production, and the unit test reproduces the equal-defect baseline.
- The resulting four proposals include clear improvements at
  `S0072/S0201/S0205` and a modest improvement at `S0097`. `S0201` matches the
  existing `balanced_predicate_restart_beats_attached_preposition_restart`
  contract: preserving `... logic | would be ...` is preferable to splitting
  `set | a maximum threshold`, while the new boundary remains REVIEW.
  `S0123/S0132/S0192` still return
  `no_complete_normal_font_page_partition`. Four requested targets have only
  one candidate, so ordering cannot improve them.
- The historical checkpoint `20260821T100422.077341-a50938d8` replays all
  217 parents with zero material changes and identical production/material
  aggregates. Focused tests pass 6/6. Page-Chinese for changed page boundaries
  has not been A/B tested, so the selector is not approved for production.
  The complete offline regression passes 30/30 in 948.16 seconds; GUI-held log
  rotation still emits harmless `WinError 32` messages without failing tests.

