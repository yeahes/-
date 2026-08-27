## 2026-08-23 Cross-Stage Page Evidence Compatibility

- The full regression first exposed a 24-word numeric-range cue that regressed
  from 7+10+7 pages at 56px to 17+7 pages with a 52px first page. Candidate
  generation still produced the correct spans, but the renderer's
  participial-completeness predicate accepted either dependency or
  participial evidence and rejected the compatible pair produced by the new
  formal English guard.
- The next full article run exposed the same contract drift for
  `directly | into ...`: formal cutting correctly added
  `verb_adverb_preposition_split`, while the renderer's complete-predicate
  fallback did not recognize that evidence and chose a shorter `in ...` tail.
- The renderer now recognizes only those two compatible evidence shapes. Both
  formal boundaries remain HARD, both display fallbacks remain REVIEW, and an
  additional numeric or lexical atomic issue still blocks the page boundary.
- Planner identity advanced from v30 to v31 so stale blueprints cannot bypass
  the new selection. Focused tests pass 7/7, the complete article readability
  contract passes 106/106, and `scripts/run_regression.py` passes 30/30 in
  1010.71 seconds. Production audio, subtitle artifacts, API caches, and the
  untracked `output/` directory were not modified.

