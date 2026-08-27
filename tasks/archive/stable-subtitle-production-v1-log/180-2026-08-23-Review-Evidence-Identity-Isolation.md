## 2026-08-23 Review Evidence Identity Isolation

- Reproduced the newest White House contamination: its saved semantic queue
  came from a 217-parent artifact and all 25 context rows disagreed with the
  current 221-parent English spans, but the editor consumed matching numeric
  IDs.
- Added one shared review-evidence identity contract. New semantic queues and
  editor ledgers bind the word-ledger hash, a deterministic hash of every
  frozen ID/English/word range, and subtitle count. Queue items additionally
  revalidate their exact context rows on load.
- The yellow-mark loader and manual translation-review UI now reject stale or
  unbound queues. Bumping the editor ledger schema makes old contaminated
  ledgers recompute from current artifacts instead of preserving stale tasks.
- Review-mark tests pass 24/24, QA queue tests pass 6/6, and the targeted editor
  action test passes. Real White House read-only replay returns zero marks from
  the stale semantic queue. Subtitle text, timing, page plans, caches, and
  saved production artifacts are unchanged.

