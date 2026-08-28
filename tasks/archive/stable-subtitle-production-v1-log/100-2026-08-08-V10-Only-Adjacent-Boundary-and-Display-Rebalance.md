## 2026-08-08 V10-Only Adjacent Boundary and Display Rebalance

- Locked the acceptance source to the v10 run
  `china-ai-cheaper-page-contract-v10-e2e-20260807-r1`; later 6-7 and 12-13
  examples were not used to add rules or claim success.
- Added a general pre-ID adjacent-window rebalance for parser-confirmed short
  dependent tails and misplaced adjunct prefixes. Preserved complete terminal
  parallel prepositional continuations without admitting short fragments.
- Reworked article planning so display load selects page count before boundary
  ranking. Added explicit risk tiers, fixed 56/54/52/50px fallback selection,
  and a two-step low-confidence policy: 52px static may beat a low-confidence
  turn, while a 50px fallback does not automatically beat a 56px low-risk turn.
- Added v10-focused regressions, including the 174-176 contract
  (`S0148=1 page`, `S0149=1 page`), and updated old test setup that had split
  Chinese through token interiors.
- Final v10-only replay: 203/203 parents, 250 pages, font counts
  56/54/52/50=181/9/6/7, minimum multipage duration 1015ms, and zero hard page
  boundaries, hard line breaks, sub-900ms pages, or English coverage errors.
- Twenty-one changed parents require new page-level Chinese. S0169 remains a
  forced-continuation REVIEW. Unified regression is 24/24 PASS in 256.214s;
  `git diff --check` passes. External requests and FFmpeg runs are zero.

