# Cross-Module Issue List

Status: resolved in the current working-tree checkpoint; retained as the
root-cause and regression record for baseline review.

## XMOD-20260804-001: Single-Cue Chinese Allocation False Positive Aborts Entire Run

- **Reproduction evidence:** The 2026-08-04 run for
  `work-dir/如何识别人工智能写作` returned all `201` semantic full translations,
  but wrote no allocation request inputs and left all `291` frozen subtitle IDs
  without Chinese. `allocation-unresolved.json` records `G0006` / `S0010` as
  `authoritative_single_cue_allocation_invalid`. Its complete text,
  `但数据表明，眼下机器根本不是那样写作的。`, is classified as
  `unnatural_chinese_fragment` solely because its stripped ending is `的`.
- **Root-cause module:** Chinese fixed-ID allocation validation in
  `ScreenSubtitleEditor._is_bad_allocation_chinese_fragment()` and the
  single-cue branch of `_allocate_semantic_group_translations()`.
- **Broken invariant:** A complete, terminal-punctuated one-cue authoritative
  Chinese translation must be retained for its existing subtitle ID. One
  invalid allocation group must not erase valid allocations for every other
  frozen ID.
- **Recommended change location:** The Chinese allocation owner should align
  the single-cue validation with the existing complete-sentence semantic audit
  and preserve already-valid group allocations when one group is unresolved.
  Do not add a sample-specific suffix exception and do not relax validation for
  multi-cue continuation fragments.
- **Required regression tests:**
  1. A terminal-punctuated one-cue translation ending in `写作的。` is valid.
  2. A genuine bare terminal modifier remains invalid.
  3. An invalid single-cue group does not discard allocations for unrelated
     groups; final Chinese ID coverage is either complete or reports the
     affected group without converting every subtitle to an empty translation.

- **Resolution:** Implemented fixed-ID single-cue containment and preserved
  unrelated allocations in `_allocate_semantic_group_translations()`. Added
  regressions for the terminal `写作的。` sentence, genuine invalid allocation,
  and unrelated-group retention. Verified by the unified regression.
