# Progress Log

Historical rounds are archived under
`tasks/archive/stable-subtitle-production-v1-log/`; this file keeps the newest
round only.

## 2026-08-26 - Resume from the failed stable stage

- Root cause: durable resume allowed only article analysis and ASR correction.
  Retrying a display-page failure therefore reran stable English freezing,
  parent translation/allocation, fixed-ID publication, and WhisperX even though
  those stages had already passed.
- Added a hash-bound `frozen_parent_timeline` checkpoint immediately before
  display-page translation. Restore validates frozen English, IDs, word spans,
  word/source coverage, parent Chinese, semantic groups, boundary evidence, and
  the final timeline; any mismatch rejects reuse. Failed page output is not
  restored, while valid per-batch page caches remain reusable.
- The current unreviewed `中国职场女性为何悄然掉队？` checkpoint restored
  offline with 271 IDs, 2855 words, 245 semantic groups, 2845 source segments,
  and a PASS 271-record timeline. All 44 files remained byte-identical.
- Retry clears the qfluentwidgets error state as well as its value, and the
  checkpoint progress stage is fixed at 96% instead of prematurely reaching
  100%. Focused run-state tests pass 9/9 and publication tests pass 102/102.
- The remaining real blocker is local pagination for `S0089`
  (`no_complete_normal_font_page_partition`), not an API failure. Retry now
  reaches that stage directly but cannot resolve the unchanged planner defect.

## 2026-08-28 - §46.48 whole-parent-Chinese display flag

- Added the default-off `PODCAST_ARTICLE_WHOLE_PARENT_CHINESE` configuration
  flag and wired it only into the article renderer's page-text selection.
- With the flag off, the existing page-local Chinese is returned unchanged.
  With it on, only multi-page parents return the complete parent Chinese for
  every frozen English page; English, IDs, timing, word spans, page plans, and
  subtitle artifacts are not rewritten.
- Read-only validation on the machine stable run `20260828T032249.733500-9602f073`
  covered 17 multi-page parents and 37 pages. No API, audio rerun, video
  synthesis, checkpoint, or stable-run write was performed.

## 2026-08-28 - Same-screen severe-imbalance audit

- Root cause: same-screen wrapping could retain cross-page syntax penalties,
  fall back to a two-word short line after longer candidates were filtered, and
  rank a severe width imbalance without rejecting it. A manually split page
  could therefore be reflowed into a visibly orphaned first line.
- Added one display-layer invariant: if the measured shorter/longer line pixel
  ratio is below `0.48`, `_article_same_screen_english_lines` returns no layout.
  The upstream frozen page planner then chooses an existing validated span or
  records structural overflow for review. No sample-specific ID rule, timing
  change, English rewrite, or downstream subtitle patch was added.
- Regression tests for `S0006`, `S0063`, and `S0088` pass (`3 passed`); the
  same-layer focused contract passes (`18 passed, 94 deselected`). The full
  article readability file remains `111 passed, 1 failed` because the existing
  `S9522` fixture expects `into` while the current baseline selects `in`.
- Offline v33 re-planning of the current word ledger gives `S0006` one page
  (pixel ratio `0.789813`), `S0063` one page (`52px`, ratio `0.949885`), and
  `S0088` two pages (second-page ratio `0.833962`). The saved manual artifact
  was not changed; its three severe pages remain evidence only. Historical v19
  automatic packages contain the same defect class, with 16 and 21 severe
  pages respectively.
- Audit scope is targeted and read-only. The fresh checkpoint
  `20260828T124923.879908-6e68f0d2` is formally `ERROR` (187 parents, 219
  pages, 32 multipage parents); its stressed pass selected 43 parents and 75
  pages. Blocking display parents are `S0098`, `S0100`, and `S0116`; no API,
  audio rerun, video synthesis, checkpoint write, or stable-run write occurred.

## 2026-08-28 - Manual-final display-only reflow integration

- The synthesis loader now enables frozen-page same-screen reflow for an
  explicitly allowed manual-final package, regardless of whether its manifest
  reaches the `PASS` display-page artifact branch or the `REVIEW` manual-draft
  branch. The reflow changes only `english_lines`, `english_font_size`, and
  measured English width.
- Existing manual page ranges, deterministic page IDs, page Chinese, parent
  English/Chinese, and page timing are validated against the original frozen
  artifact. Automatic stable synthesis keeps the flag off and therefore keeps
  the previous load behavior.
- When the strict same-screen contract rejects a severe orphan, a bounded
  page-local fallback removes cross-page scoring only for line selection and
  accepts a measured two-line ratio of at least `0.48`. It cannot move a word
  between pages; an unrenderable page still returns a hard failure.
- Regression verification: article display tests `20 passed, 94 deselected`,
  manual editor affected tests `3 passed, 133 deselected`, and the new manual
  plus display-artifact load assertions pass. Two attempted full-contract
  runs exceeded two minutes and were stopped; no production process or desktop
  artifact was modified.
- No audio, API, or video synthesis was executed. A source checkpoint is still
  required before a real GUI synthesis run.
