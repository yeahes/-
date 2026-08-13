# Project State
Status: complete
Last verified: 2026-08-13 12:40:12 Asia/Shanghai
Branch: main
Verified HEAD: 438d6068a23733545782c5c47ec8ceb53bfe2f3d
Working tree: modified by source-echo translation increment; `.workbuddy/` excluded

## Current Goal
Preserve the reviewed post-223975e subtitle, timing, editor, publication, tests, and documentation state as a Git checkpoint.

## Confirmed Facts
- The durable remaining-quality plan and pinned SmartSub findings are in
  `docs/QUALITY_CEILING_ROADMAP.md`; read it before repeating external source research.
- A moved manual-final package can relocate its owned subtitle, edit journal,
  word ledger, artifact directory, and page subtitle only inside the package;
  SHA-256 mismatches still fail closed.
- Saving freezes current mutable state without deep-copying append-only history
  entries. Real 258-cue/311-row snapshot cost fell from about 404ms to 22ms.
- `split_display_page` changes only the selected page range; sibling page text, Chinese confirmation, word ownership, and timing remain unchanged.
- `merge_adjacent_display_pages` combines a cross-parent cue merge and selected visual-boundary removal as one history operation; injected failure restores every mutable owner.
- Session/model refresh starts disarmed. Clicking a subtitle row arms its boundary entry; clicking an empty table area clears the controls and selection.
- Split and merge keep actual-page mode active and restore selection to the affected page without arming adjustment controls.
- Same-screen reflow keeps 56px whenever a legal one- or two-line layout exists; 54/52/50px remain ordered overflow fallbacks.
- Read-only replay of the latest rendered manual package changes only three of 310 pages from 54px to 56px and changes no page contract field.
- WhisperX cannot erase a trusted 200ms-or-longer pause before a number, percentage, currency form, or acronym when doing so would create an uncorroborated onset delay of at least 150ms.
- The numeric-pause fallback restores at most the two word records owning that boundary; fixed text, IDs, order, cue ownership, and unrelated word times remain unchanged.
- New stable runs write `authoritative-parent-chinese.json`, binding each fixed
  parent ID to its frozen English hash, word span, Chinese hash, provenance, and
  record hash. Legacy schema-v2 packages remain compatible only when their
  existing parent, translation, and page records agree.
- Read-only replay of the two requested moved packages succeeds:
  `如何停止拖延-处理结果` loads 283 cues and 3126 ledger words; `中国已成为世界石油强国-处理结果`
  loads 170 cues and 1676 ledger words. In-memory undo/redo round trips pass for
  both, and every production file keeps the same mtime, size, and SHA-256.
- Stable production and manual editing now share `canonical-word-ledger-v1`.
- A required display-page export must succeed before the root success manifest
  is published; failed candidates are removed and the previous success remains.
- Kimi's pause-insensitive stranded-complement tests and false completion
  records were removed; that segmentation change is not active.
- The retained boundary fix uses parser-confirmed modified-infinitive scope
  evidence; ordinary paused purpose-infinitive boundaries remain legal.
- Full-group and selective fixed-ID translation requests now carry up to two
  previous/next semantic groups as read-only context, versioned as
  `semantic-full-translation-context-v1`; neighboring IDs cannot be returned
  or written back.
- Full-group translation responses must echo the target frozen English as
  `source_english`; mismatched groups are isolated for single-group retry and
  cannot poison valid neighbors. Version:
  `semantic-full-translation-source-echo-v1`.
- New display-page translation requests also echo each page English and are
  validated by exact page ID plus word sequence; legacy page artifacts remain
  readable without the new flag.

## Approved Decisions
- Local display-page edits must not invoke whole-parent replanning unless the user explicitly chooses `整条字幕调整为 N 屏`.
- Cross-parent actual-page merge must be atomic and single-undo; partial parent/page state is invalid.
- Programmatic selection after refresh is navigation, not permission to enter edit mode.
- A valid two-line layout at a larger font outranks a smaller one-line layout; line-count reduction alone cannot shrink the font.
- Meaningful upstream numeric pauses outrank a conflicting local WhisperX boundary; shared local drift remains accepted.

## Relevant Paths
- `app/core/subtitle_processor/manual_final_subtitle_editor.py`
- `app/view/subtitle_interface.py`
- `app/core/subtitle_processor/stable_ts_alignment.py`
- `tests/test_manual_final_subtitle_editor.py`
- `tests/test_stable_publication.py`
- `tests/test_stable_caption_rules.py`

## Last Verification
- Manual-final editor direct script passes after portable package loading and
  save-snapshot isolation changes. Stable publication/UI passes 63/63.
- Read-only loading and in-memory undo/redo succeed for the moved `如何停止拖延`
  and `中国已成为世界石油强国` manual packages. No production file was written.
- The complete 25-stage regression passes after this editor increment in
  425.6 seconds; `git diff --check` and syntax compilation also pass.
- After recording `docs/QUALITY_CEILING_ROADMAP.md`, all 25 regression stages
  passed in 404.3 seconds and `git diff --check` passed; this documentation-only
  step made no production subtitle, cache, audio, video, or behavior change.
- Manual-final editor direct script passes, including local split, atomic merge, one-step undo, and injected-failure rollback.
- Stable publication/UI passes 63/63, including initial disarmed state, explicit row activation, and empty-area exit.
- Article readability, manual-final editor, and stable publication/UI 63/63 pass.
- Exact `field, / 73%` and `move. / 72%.` regressions plus a shared-shift counterexample pass.
- ASR trust passes 38/38, final-cue timeline and complete stable-caption rules pass.
- All 25 regression stages pass in 367.4 seconds; no production subtitle, audio, or video artifact was written.
- The full regression after the authoritative-Chinese checkpoint compatibility
  fix completed without any failed stage. Video synthesis safety and stable
  subtitle publication are green again, along with all other stages.
- `tests/test_stable_caption_rules.py` passes after the boundary follow-up.
- Immutable replay of the successful AI competition run keeps 226 cues and
  2,596 contiguous words with zero hard boundaries.
- The failed-checkpoint replay changes only `S0211 | S0212` from the invalid
  `likely, | to manage` to `well, | most likely, to manage`; hard issues drop
  from 1 to 0 and coverage remains complete.
- `runtime\\python.exe scripts\\run_regression.py` passes all 25 stages in
  359.5 seconds; `git diff --check` passes.

## Next Action
Run the complete 25-stage regression, then review and commit the source-echo translation increment.

## Do Not Regress
- Preserve frozen IDs, word order, sibling page state, actual-page view, single-command rollback, ordered 56/54/52/50px overflow fallback, and local-only numeric-pause timing fallback.

## Unknowns
- Package publication is still file-by-file rather than generation-atomic;
  delta history, redo, crash recovery, and a full real-GUI walkthrough remain open.
- A real GUI rerun has not yet regenerated the production ledger with the numeric-pause fix.
