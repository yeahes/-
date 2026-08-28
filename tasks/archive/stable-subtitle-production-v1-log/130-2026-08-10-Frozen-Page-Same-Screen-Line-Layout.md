## 2026-08-10 Frozen-Page Same-Screen Line Layout

- Added a post-freeze, renderer-only English line-layout pass under
  `article-fixed-font-pages-v19`. It can choose one or two lines and
  56/54/52/50px inside an already frozen page, but cannot alter page count,
  page boundaries, word spans, IDs, English, Chinese, or timing.
- Kept the existing layout as a monotonic baseline. Equal breaks keep the
  larger size; a smaller size requires a strictly better legal break. Any
  feasible size above 50px excludes 50px. Explicit non-atomic
  subject/predicate evidence is soft for same-screen ranking, while lexical
  atoms remain hard protected.
- Read-only replay of the study-abroad manual package checked 253 parents and
  311 pages. Twenty-seven line layouts changed, while structural changes were
  zero and all 15 source-package hashes remained unchanged. The first offline
  comparison appeared to remove every 50px page, but it had not exercised the
  renderer's exact frozen-artifact validator.
- The article display readability contract and the full 25-stage unified
  regression pass; the final unified run completed in 407 seconds. Visual
  inspection found no overflow, overlap, or unexpected third line. External
  requests and production writes are zero.
- Closed the old-manual-package integration gap. Manual-final save now applies
  the v19 same-screen reflow to every frozen render plan before publishing the
  new contract, while copying page IDs, spans, English, Chinese, page timing,
  and boundary evidence unchanged.
- A read-only replay of the actual saved manual session checks 253 parents, 311
  pages, and 311 page edits. It changes 23 same-screen layouts and zero
  structural fields. Both complete focused scripts and the post-integration
  25-stage unified regression pass; the unified run takes 393.2 seconds.
- A subsequent synthesis attempt rejected three retained v18 line layouts:
  `S0065.P01`, `S0185.P01`, and `S0223.P01`. Baseline retention now first
  proves that the old lines are legal under v19. The renderer accepts a
  temporary full manual-save artifact with final font counts
  56/54/52/50 = 297/6/5/3, and the final unified regression passes all 25
  stages in 375.9 seconds.

