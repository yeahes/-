## 2026-08-21 Chocolate Full-Pipeline Repair

- Root-cause audit of `中国会有爱上巧克力的一天吗？` found a 96% page-stage
  failure, five rejected parent page plans, five missing Chinese page rows, and
  article-assisted ASR misses/false expansions caused by inconsistent token
  ownership and incomplete response acceptance.
- Article correction v6 shares Unicode-aware lexical rules, ignores terminal
  punctuation for similarity, preserves legitimate short entities and
  hyphenation variants, and limits whitespace-only connector repair to exact
  surfaces such as `R &D -> R&D`.
- Real ASR replay applies 14 high-confidence corrections with the expected
  `Nestlé` 1, `R&D` 4, `Choc Revive` 6, and `Saturnbird` 3 occurrences. The
  frozen-ID editor queue reduces to two actionable English checks:
  `S0069 stringing -> springing` and `S0078 Shi Liang -> Xie Liang`.
- The renderer candidate selector now carries a proven complete prepositional
  continuation through final readability selection. The real 229-parent
  checkpoint produces 258 pages and clears all five former plan failures at
  56px without changing parent English, IDs, word ranges, or timing.
- Fresh empty/partial page-translation JSON is no longer accepted as a valid
  batch. The same batch retries until every requested page ID is present or the
  bounded request fails explicitly; completed sibling batches remain reusable.
- White House replay retains the intended `Hinrich Foundation` corrections and
  blocks the previously observed `Navarro`, `Trump administration`,
  `G K. Chesterton`, and `Southeast Asian` expansions. A new GUI production run
  is still required to verify click-to-editor-to-save-to-synthesis behavior.
- Final focused article correction verification passes 57/57. The complete
  offline regression passes 30/30 in 875.03 seconds, and `git diff --check`
  passes with line-ending warnings only.

