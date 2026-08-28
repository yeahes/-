## 2026-08-10 Exact Display-Page Failure Attribution And Numeric Moves

- Replayed the failed `中国AI为何更省钱？` checkpoint. Only `S0199` failed the
  frozen renderer plan: its 25-word English fit a 50px single page, but its
  complete Chinese did not fit the fixed 46px/two-line region. The editor then
  fell back to marking all 39 multipage parents because the apply function
  returned only `False` and the normalizer did not know single-page render IDs.
- One-page candidates now prove Chinese fit before selection. Artifact apply
  records the exact failed parent ID, and failure normalization accepts the
  complete render-plan ID set. `S0199` is planned as two pages at
  `down / might`; a general forced-fallback ranking prevents the tighter
  `meant / to` verb-complement split from beating a subject/predicate fallback.
- Manual formal and visual page-boundary moves share one numeric expansion
  rule. Moving one member of `740 billion spend` moves all three words when
  required; the editor preview highlights and confirms the expanded count.
  Terminal punctuation prevents `2019. / Right.` from being combined.
- Offline 199-parent replay reports 197 unchanged neighboring page structures.
  Existing whole-episode pressure optimization changes `S0198` from four pages
  to three after `S0199` becomes less dense; frozen parent identity, English,
  word ownership, and timing remain unchanged. The denser result is retained
  as a documented visual-review risk rather than expanding this defect repair
  into another page-count policy rewrite.
- Four focused suites pass, including 58 publication/UI tests. The unified
  regression exits zero in 374.9 seconds. External requests, ASR, LLM, network,
  synthesis, paid requests, and production writes are zero.

