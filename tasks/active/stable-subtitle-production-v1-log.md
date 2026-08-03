# Progress Log

## Current Objective

Stabilize the production subtitle path and make the project recoverable for future Codex sessions.

## Completed

- Added root `AGENTS.md`.
- Added project docs under `docs/`.
- Added active task file.
- Added this task log.
- Existing tests already cover stable segmentation and output audit basics.
- Added `scripts/run_regression.py`.
- Verified the unified regression command exits successfully.
- Current known local samples audit as WARNING only, with no ERROR.

## Latest Test Results

Command:

```powershell
runtime\python.exe scripts\run_regression.py
```

Result:

- stable caption smoke tests: pass
- syntax check: pass
- known output audit: completed
- 2026-07-26 recheck: stable caption smoke tests pass; syntax check passes.
- 2026-07-27 WhisperX backend check: FasterWhisper plus WhisperX CUDA alignment completed on `外卖骑手诗人的走红，标志着中国农民工文学的兴起`; subtitle validation passed, video synthesis completed, final SRT had no overlaps and no >1000ms gaps.
- 2026-08-02 boundary regression: sentence-final `over.` no longer triggers
  the preposition-object guard. A frozen replay of `如何识别人工智能写作`
  restored `I mean, the Delve era is over.` as one cue without changing word
  coverage. `runtime\python.exe -X utf8 scripts\run_regression.py` passed.
- 2026-08-02 QA queue/full-flow validation: `build_qa_summary.py` now emits a
  deterministic, time-addressable `qa-review-queue.srt` artifact and
  `SubtitleThread` exports it as `字幕质检队列.srt` beside the source audio.
  The full `如何识别人工智能写作` run completed with 217 fixed subtitle IDs,
  no translation structure errors, zero validation ERRORs, and a successfully
  rendered article-template video. The source report had 33 REVIEW/21 INFO
  items; the user-facing queue contained the first 12 REVIEW items only.
- 2026-08-02 strict A/B comparison guard: added
  `scripts/compare_frozen_mainline_runs.py` and fixture tests. A run now
  records active article-reference settings and hashes in the stable manifest;
  stale article artifacts cannot make a no-article run appear comparable to an
  article-assisted run. Only Chinese-by-ID text is permitted to differ in an
  allocation-only comparison.
- 2026-08-02 manual final subtitle editor: added a local word-ledger-backed
  edit layer for completed stable outputs. It can move a continuous English
  suffix/prefix across one adjacent cue boundary, recomputes that boundary's
  times from frozen word timestamps, rejects free-text pseudo-alignment, and
  writes an explicit manual-final override for video synthesis.
- 2026-08-02 final timing ownership migration: replaced the WhisperX
  time-only final-cue text remap with a frozen-word-ledger path. Final cue
  timing is derived by `subtitle_id -> word_start/word_end`, written to
  `final-cue-timeline.json`, and blocked on lost IDs, `S0000`, own-word
  envelope failure, or unreconcilable word-envelope overlap.

## Current Decisions

- Stable mode should skip old LLM segmentation.
- Stable mode should skip candidate quality check.
- Backchannels should be preserved by default.
- Synthesis should resolve subtitles through `stable-final-manifest.json`.
- Timeline alignment defaults to stable-ts; WhisperX is available as an experimental backend with failure fallback.
- Article-template layout is presentation-only. Its two-line wrapper may
  change visual line breaks but must not recut frozen stable English subtitles.

## 2026-08-02 Structural Migration

- Consolidated stable English cutting into
  `ScreenSubtitleEditor._finalize_stable_english_boundaries()`.
- Removed the article-template layout recut from the pre-ID path. This removes
  a template-dependent writer of English subtitle boundaries while retaining
  the renderer's existing text wrapping.
- Added `stable_pipeline_contracts.py` as the shared serialization and hash
  contract for allocation-isolation checks. This is the first extraction from
  `screen_editor.py`; it preserves the existing artifact schema.
- Unified the word-limit contract: 6-12 words is the visual target, 16 is the
  normal stable-cut maximum, and 17-19 requires an audited parser-confirmed
  grammar exception. Allocation-only replay now uses the same 16-word fallback
  when reading older manifests.
- Moved selective Chinese polish onto the allocation candidate comparator used
  by allocation retry. Retry still requires a proven high-confidence repair;
  polish only requires an ID-valid, non-regressive candidate and records the
  same comparison evidence.
- Moved post-allocation Chinese compression and same-group reallocation onto
  that same evidence contract. A candidate must reduce local reading pressure
  and cannot add a semantic, entity, number, negation, duplicate, fragment, or
  adjacent-naturalness regression. Rejected candidates restore the original
  fixed-ID Chinese values.

## Current Risk

- Existing `work-dir` outputs may be stale after code changes.
- `screen_editor.py` remains too coupled for large changes without fixture tests.
- Local sample availability is not stable; prefer fixture-backed tests for repeatable validation.

## 2026-08-03 GUI Simplification

- Kept stable bilingual production controls visible while moving allocation
  tuning and legacy LLM splitting controls into collapsed sections.
- Collapsed optional article-reference input on the task entry screen; active
  analysis and cache state remain visible in its header.
- Kept compatibility correction and prompt actions available from the subtitle
  editor's `More` menu. Manual-final and next-review commands appear only when
  their matching stable artifacts exist.
- No subtitle, timestamp, translation, or output behavior was changed.

## Next Action

Use a previously unseen audio to review the fixed-ID Chinese allocation and
time-only alignment from the generated `字幕质检队列.srt`. Treat the queue as a
human-review aid: it must not turn WARNING evidence into a render blocker.

## 2026-08-03 Same-Source Rerun

- Sample: `C:\Users\19379\Desktop\创业者的天堂\创业者的天堂.m4a`.
- Completed at `10:42:49+08:00` with `338` final cues, article assistance,
  DeepSeek Flash allocation concurrency `3`, and WhisperX time-only timing.
- `translation-structure-errors.json` is `[]`; final cue timeline validation
  is `PASS` with zero errors; render is not blocked.
- Confirmed final text preserves `466 000 Americans` and `American Enterprise
  Institute details`; the previous false entity rewrite `America have applied`
  is absent.
- Full regression passed. `git diff --check` has only pre-existing CRLF
  conversion notices.

## 2026-08-03 Stage Progress And Safe Resume

- Added a durable `run-state.json` state machine outside subtitle processing.
- The bottom status label now receives stage-aware messages with completed
  batch count, cache hits, retries, elapsed time, and a bounded ETA.
- Resume is intentionally narrow: only article-context and corrected-ASR
  artifacts with matching input/configuration hashes and verified file digests
  are reused. Existing ID-bound LLM batch cache continues to avoid duplicate
  completed translation/allocation calls.
- No English, subtitle ID, word ledger, final timing, Chinese allocation, or
  export writer is restored from an incomplete in-memory pipeline stage.

## 2026-08-03 Article Entity Alias Collision Guard

- A local candidate gate now rejects a high-score short alias when the same
  original ASR word range contains a conflicting discriminator token from a
  different article-supported canonical entity.
- Rejected candidates remain review-only and record the target canonical,
  conflicting canonical(s), alias evidence, word range, and discriminator in
  `correction_log.json`. The correction path does not modify English cutting,
  timing, IDs, Chinese allocation, or export.

## Files Changed

- `AGENTS.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/ARCHITECTURE.md`
- `docs/PIPELINE.md`
- `docs/SUBTITLE_RULES.md`
- `docs/DECISIONS.md`
- `docs/CURRENT_STATE.md`
- `docs/TESTING.md`
- `tasks/active/stable-subtitle-production-v1.md`
- `tasks/active/stable-subtitle-production-v1-log.md`
- `scripts/run_regression.py`

## 2026-08-03 Visual Reading Budget Regression Guard

- Root cause: the pre-ID visual reading-budget pass accepted a candidate when
  its cut point had no hard syntax issue, but did not require both newly
  created cues to be independently readable on screen. This could split a
  complete sentence into a short connector-led, comma-ended, or
  preposition-led fragment.
- Added a visual-only display-unit gate to
  `ScreenSubtitleEditor._safe_item_split_for_budget`. The 16-word structural
  overflow path is unchanged; only the optional 12-word/68-character visual
  pass opts into the stricter gate.
- Candidate audits now include `visual_display_issues`. A rejected visual-only
  split keeps the existing complete cue and records `visual_budget_unresolved`
  as REVIEW evidence rather than a structural error.
- Added regression coverage for short comma-ended phrases, connector-led noun
  phrase fragments, preposition-led tails, and preservation of word order,
  ranges, and timestamp ownership.
- Validation passed:
  `runtime\\python.exe -X utf8 tests\\test_stable_caption_rules.py`,
  `tests\\test_stable_boundary_finalization.py`,
  `tests\\test_article_context.py`, and
  `runtime\\python.exe -X utf8 scripts\\run_regression.py`.

## 2026-08-03 Parser-Confirmed Preposition Complements

- Root cause: a noun-attached example phrase can be parsed as
  `NOUN -> ADP/prep -> NOUN/pobj`; the former visual split gate did not assign
  ownership to the `prep -> pobj` boundary. It could therefore strand the
  example introducer in the preceding temporal cue.
- Added a parser-backed preposition-complement protection in the shared word
  ledger syntax hints. It is used by stable cutting, visual budget splitting,
  and final pre-ID validation. A safe visual split may move the entire example
  phrase to the next cue, but cannot strand its introducer above the
  complement. No audio-specific text condition was added.

## 2026-08-03 Comma-Bracketed Adverb Boundary

- Root cause: the stable greedy cutter gives commas a boundary reward. In a
  repeated phrase such as `for me, adverb, for anyone`, that could make the
  sentence-internal adverb the first word of the next cue.
- Added a narrow parser-backed guard for a punctuation-bracketed `ADV/advmod`
  immediately followed by its `ADP` head, with no long pause. The guard rejects
  only the boundary before the adverb and preserves ordinary sentence-initial
  adverbs and adverb-verb boundaries.

## 2026-08-03 Short Gerundial Manner Phrase

- Root cause: the visual character budget could split an otherwise valid
  13-16 word question immediately before a compact unpunctuated `VBG/advcl`
  manner phrase, leaving a brief instrumental tail as a separate time cue.
- Added a parser-backed local protection for that boundary and made the visual
  display-unit gate reject non-finite preposition-led tails at every length.
  Punctuated or long-paused participial clauses remain eligible for a normal
  subtitle boundary.

## 2026-08-03 Temporal Boundaries Versus Renderer Wrapping

- Audited the completed `如何识别人工智能写作` run from its frozen
  `stable-boundary-snapshots.json` and word ledger. The former visual
  12-word/68-character pass created 49 additional temporal subtitle
  boundaries: 31 are locally incomplete display units, 17 are unnecessary
  without a supporting 450ms pause, and 1 is only potentially semantic.
- Root cause: a renderer reading target had authority to create English cue
  boundaries before IDs. That fragmented Chinese allocation even when the
  stable syntax cutter had already produced a complete 13-16 word cue.
- `_apply_visual_reading_budget()` is now a deliberately narrow pre-ID visual
  temporal stage. It considers only a sentence terminal, two complete
  punctuated clauses, or a punctuated non-finite introduction followed by a
  complete main clause, and only with a recorded pause plus safe display
  duration on both sides. Structural overflow remains owned by the existing
  syntax cutter; every other long cue stays intact for renderer wrapping.
- The renderer now strongly avoids a new visual line before a preposition,
  infinitive marker, connector, or clause introducer, after a determiner,
  function word, or auxiliary, and inside a hyphenated compound. It may reduce
  font size only when needed to find a phrase-safe two-line layout.
- Added `scripts/audit_visual_temporal_splits.py` for repeatable historical
  snapshot review. It writes a complete JSON and Markdown table for every
  visual time boundary without using an LLM or changing a subtitle.
- Validation passed: `tests/test_stable_caption_rules.py`,
  `tests/test_article_context.py`, and `scripts/run_regression.py`.
- A final-boundary audit also found and removed a generic QC false positive:
  an unambiguous sentence terminal now wins over token-only determiner and
  modifier guesses, while title and initial abbreviations before names remain
  protected as non-terminal boundaries.

## 2026-08-03 Conservative Visual Temporal Split

- Restored visual temporal splitting only as a pre-ID, syntax-owned stage.
  The soft 12-word/68-character budget merely starts candidate evaluation; it
  cannot independently create a cue boundary.
- Accepted generic categories are `sentence_terminal`,
  `complete_clause_boundary`, and `fronted_introduction_boundary`. Every
  accepted boundary is recorded with category, word ranges, recorded pause,
  candidate display durations, and preservation checks.
- Immutable replay of `如何识别人工智能写作` selected six boundaries from 216
  frozen English cues, producing 222 pre-ID cues. All six preserve word order
  and word coverage; 57 remaining soft-budget cues have no safe split and stay
  renderer-owned.
- Confirmed that `You know, this robotic vocabulary actually connects ...`
  remains unsplit: the potential cut separates the subject from its finite
  verb, which is still a parser-confirmed hard grammar boundary.

## 2026-08-03 Leading Non-Finite Prefix Rebalance

- Added a post-gate, pre-ID local rebalance for a short comma-terminated
  non-finite conditional prefix at the start of a cue. It only moves the prefix
  to the preceding incomplete clause when spaCy confirms a clause marker with
  no subject or finite predicate, the following cue is a complete main clause,
  the speaker and word ledger are continuous, the pause is below 450ms, and
  both resulting cues remain within the normal word limit.
- This repairs a generic shape such as an ellipted condition separated from its
  governing action without treating finite conditional introductions as errors.
  The repaired boundary records the parser-backed exception that prevents a
  text-only preposition heuristic from re-reporting the same cut.

## 2026-08-03 Pre-ID Candidate Write Gate And Generic Syntax Guards

- Root cause: local post-processing accepted a repartition after calculating
  `hard_issues_after`; the audit recorded the problem but the candidate still
  replaced the current items. The write path now rejects that candidate before
  mutation and retains the previous items.
- Added `_can_apply_pre_id_repair_candidate()` as the common candidate gate.
  It checks exact word order and coverage, new internal/changed edge
  boundaries, fragment validity, speaker/range continuity, one-word fragments,
  and the hard word limit. Pre-existing untouched edge warnings are excluded
  from the candidate decision.
- The gate is used by pre-ID window repair, balanced short/discourse splits,
  overlong splitting, visual temporal splitting, internal transition splitting,
  and non-finite-prefix rebalance.
- Added parser-backed protections for direct verb particles, compact
  coordinated subjects, short verb-dative-object starts, and `from number to
  number` ranges. The word mapper's compound subtoken fallback now requires a
  delimiter, avoiding false consumption such as `in` inside `stepping`.
- Added regression coverage for all four parser shapes, candidate rejection,
  and preservation of existing long-object behavior.
