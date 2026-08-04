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

## 2026-08-04 Complete Fixed-ID Final Allocation Artifact

- Root cause: `allocation-final.json` was assembled only from allocation
  attempts accepted by the quality gate. When a retry remained unresolved, the
  final subtitle writeback retained an ID-bound Chinese value but the final
  allocation artifact omitted that group's IDs.
- The artifact now derives every group mapping from the final fixed-ID subtitle
  items used for export. Existing accepted-attempt provenance is retained when
  it still matches; otherwise the record explicitly identifies final-item or
  unresolved-final-item provenance. `allocation-unresolved.json` remains the
  sole record of why a quality issue was not resolved.
- English text/order, subtitle IDs, word ranges, timings, allocation decisions,
  and render gating are unchanged.
- Added a regression case for an unresolved group whose retained Chinese must
  still appear in the final allocation artifact.

## 2026-08-04 Chinese Allocation Quality And Near-Threshold Rendering

- Root cause: allocation validation returned success for a terminal Chinese
  modifier whenever it carried closing punctuation. This bypassed the existing
  fragment retry and allowed a phrase without its governed noun or predicate
  to reach final subtitles. The generic allocation retry also reused the
  ordinary prompt despite knowing that the failure was grammatical.
- Final modifier fragments now fail fixed-ID validation after permitted
  non-final continuations are considered. They use the existing one-group
  retry with a grammar-focused fixed-ID prompt and a distinct cache key; no
  extra retry or English/timing mutation is introduced.
- Root cause: the same `12.0` Chinese-CPS threshold classified a 15-character
  subtitle over 1241ms as a render error at `12.09` CPS. It was a discrete
  character-count boundary case rather than a sustained reading overload.
  The explicit error boundary is now `12.25` CPS; `9.0-12.25` CPS remains
  review evidence. Structural translation/timeline errors are unchanged.
- The Chinese semantic audit no longer applies fragment rules to a fully
  punctuated single-cue sentence, eliminating a known class of false positives
  without weakening multi-cue allocation checks.
- Added focused regression coverage for terminal modifiers, specialized retry
  selection, single-cue audit false positives, the 12.09-CPS near-threshold
  case, and final allocation artifact coverage.

## 2026-08-04 Pre-ID Structural Fragment Merge

- Root cause: direct final-boundary repair correctly identified a trailing
  English fragment but rejected the only complete 19-word merge under the
  ordinary 16-word candidate gate. That left a known residual phrase split
  even when no grammar-safe normal-limit boundary existed.
- The candidate gate now permits exactly one direct, continuous, pre-ID
  two-cue-to-one merge when the source boundary has a high-confidence fragment
  issue and the shared structural-overflow check confirms a complete 17-19
  word sentence with no legal <=16-word split.
- The exception is not available to visual temporal splitting, general
  repartitioning, ID-assigned cues, Chinese allocation, timing, or export.
- Focused tests cover the allowed 19-word merge, rejection above 19 words,
  and rejection when a legal normal-limit split exists.

## 2026-08-04 Rejected Direct Merge Fallback

- Root cause: after a direct weak-fragment merge was rejected by the candidate
  gate, the pre-ID repair loop skipped the normal safe-repartition search for
  that same local window. This left a legal repair untried, as in the
  `Yeah, so Todd` subject-fragment regression.
- A rejected direct merge now falls through to the existing local repartition
  candidates. The successful candidate must still pass the shared word-order,
  word-range, speaker, syntax, fragment, and word-limit gate before writeback.
- The regression now asserts the selected frozen word spans `(0, 8)` and
  `(9, 14)`. No post-ID English, Chinese, timing, or synthesis behavior is
  changed.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py` and
  `runtime\python.exe -X utf8 scripts\run_regression.py` passed.

## 2026-08-04 Fixed-ID Chinese Postprocess Audit

- Root cause: speed compression and same-group redistribution still accepted
  legacy positional response fields (`index`, `target_index`, and `id`). A
  stale cache could therefore target a different frozen subtitle after cue
  ordering changed. A separate phrase-specific local speed fallback could also
  shorten Chinese despite a semantic-omission finding.
- Compression, redistribution, and high-confidence Chinese repair now require
  explicit existing global `subtitle_id` values for every returned target and
  segment. Missing or unknown IDs are recorded as translation-structure errors
  and cannot write back. Prompts no longer describe an index response schema.
- Removed the phrase-specific local speed rewrite and its dead omission
  exception. When no ID-valid candidate is returned, the original Chinese is
  retained; the normal warning/error and fixed-ID candidate comparator remain
  the only decision path.
- The frozen invariant remains: Chinese-only candidates may alter only a
  current group dictionary keyed by existing subtitle IDs. English text/order,
  word ranges, cue times, IDs, and cache/concurrency ordering are unchanged.
- Added regression coverage for index-only compression and reallocation
  responses. Both are rejected without writeback.

## 2026-08-04 Single-Cue Allocation Containment

- Root cause: allocation validation applied a cross-cue terminal-modifier
  heuristic to a one-cue authoritative full translation. A complete sentence
  ending in `的` could therefore be marked as a fragment. The caller then
  returned an empty allocation dictionary, discarding successful mappings from
  other groups and creating a cascade of missing Chinese IDs.
- A one-cue group now writes its authoritative full translation directly to
  its only frozen ID without allocation-fragment validation. Full translation
  generation remains responsible for that sentence's meaning and fluency.
- An invalid one-cue group and an unavailable sequential allocation batch now
  record only their own unresolved groups; they no longer erase already
  accepted mappings. Final ID validation still blocks export for any missing
  Chinese cue.
- Regressions cover a complete `...写作的。` translation and containment of an
  invalid one-cue group while a following frozen ID remains allocated.

## 2026-08-04 Stable English Boundary Routing Audit

- Root cause: `SubtitleThread` still invoked the legacy LLM
  `SubtitleOptimizer` when `need_optimize=True`, including stable screen mode.
  This created a second owner for final English text before deterministic
  boundary finalization.
- Fix: `_should_run_legacy_subtitle_optimization()` now permits that optimizer
  only outside stable screen mode. The stable route stays local and
  word-ledger-based; no existing valid cue, ID, word range, timing, Chinese
  field, or renderer behavior changes.
- Root cause: `ScreenSubtitleEditor.edit()` could silently fall through to the
  legacy LLM editor when the word ledger was absent or source-to-word mapping
  was incomplete. Stable mode then had no authoritative complete word ledger.
- Fix: stable mode now fails before any legacy edit unless the ledger exists
  and every source segment maps to it. This belongs at the screen-editor
  ingress because only that module receives both source segments and the
  authoritative ledger; upstream cannot prove their one-to-one mapping.
- Added focused regressions for both routes. Full automated validation passed:
  `tests/test_english_boundary_rules.py`,
  `tests/test_stable_boundary_finalization.py`,
  `tests/test_stable_caption_rules.py`, and `scripts/run_regression.py`.
- Audit note: `split.py` and `split_by_llm.py` remain legacy-mode facilities.
  Stable production excludes `SubtitleSplitter`, and no stable production
  caller imports `split_by_llm.py`; removing either requires an explicit
  legacy-mode migration rather than an audit cleanup.

## 2026-08-04 Stable Manifest Authority

- Root cause: a malformed or unusable `stable-final-manifest.json` was caught
  and ignored by podcast-template subtitle resolution. The resolver then used
  filename-based discovery, which could select a stale SRT in the same folder.
- Fix: an existing manifest is authoritative. Decode, schema, and declared
  final-SRT failures now stop synthesis; filename discovery remains available
  only when no manifest exists. Manual-final override and legacy
  reading-speed revalidation retain their existing manifest-bound behavior.
- Added regression coverage for malformed manifests and missing manifest SRTs
  in a folder containing a stale candidate.

## 2026-08-04 Renderer-Owned Unsplittable English Sentence

- Root cause: `_stable_greedy_ranges()` forced a 19-word cue when no legal
  normal-limit cut existed. It also accepted a grammatically incomplete
  17-19-word emergency candidate merely because its local boundary was legal.
  The final validator correctly rejected both incomplete cues as overlong,
  producing a stable pipeline contradiction before subtitle IDs were assigned.
- Fix: an emergency 17-19-word cut is eligible only when it is a complete
  terminal cue or parser-confirmed comma subordinate clause. Otherwise the
  pre-ID cutter preserves the remaining complete source sentence for renderer
  wrapping. It is an audited structural-overflow warning, not an export error.
- Invariant: pre-ID stable cutting must not manufacture a cue which the final
  English validator is guaranteed to reject. English text/order, the word
  ledger, IDs, Chinese allocation, and final cue timing remain outside this
  change.
- Regression and frozen-ledger replay cover both prior production shapes:
  a protected `synthetic text` phrase and the terminal `websites on the
  internet` preposition phrase. The replay uses no ASR or LLM request.

## 2026-08-04 Baseline Contract Reconciliation

- Unified the standalone caption audit's Chinese CPS error boundary with the
  runtime and synthesis threshold at `12.25`; values from `9.0` through
  `12.25` remain review warnings.
- Added a regression for a `12.09` CPS cue to ensure the audit and runtime do
  not disagree at the discrete near-threshold boundary.
- Refreshed `CODEX_STATE.md` to the actual verified HEAD and recorded the next
  action and remaining unknowns. Marked the resolved cross-module allocation
  issue as a retained root-cause/regression record.
- Focused stable-caption tests, unified regression, and `git diff --check`
  passed after the reconciliation.

## 2026-08-04 Final Timeline Frozen-Order Validation

- Root cause: final timeline validation checked ID membership, word-span
  continuity, and display timing, but did not compare returned cue-ID order to
  the frozen subtitle-ID sequence. A paired ID/span reorder could therefore
  preserve contiguous words and pass validation while breaking the fixed-ID
  export contract.
- Fix: final timeline validation now emits
  `final_timeline_subtitle_order_mismatch` when the exact returned ID sequence
  differs from the frozen sequence. This blocks SRT/ASS export without
  changing word timestamps, display timing, English, Chinese, or cue ranges.
- Regression: a two-cue paired ID/span reorder is rejected even though its
  word coverage and timestamps are otherwise valid.

## 2026-08-04 Fixed-ID Allocation Audit And Imperative Boundary Integration

- Allocation attempts that violate fixed-ID structure before a successful
  retry now remain auditable as `retry_required` evidence without becoming
  final render-blocking structure errors. Regression covers a missing ID
  followed by an ID-correct retry and verifies frozen English fields remain
  unchanged.
- The conservative visual pre-ID gate can now recognize a complete terminal
  imperative as a display unit. It preserves all existing pause, duration,
  continuity, grammar, and write-gate requirements; an infinitive beginning
  with `To` remains unsplittable by this rule.
- Both feature branches were reviewed and merged to main. The unified
  regression and `git diff --check` passed; unseen-audio production and
  article-template visual validation remain the next verification step.
## 2026-08-04 Fixed-ID Missing Full-Translation Containment

- Root cause: `_allocate_semantic_group_translations()` returned an empty
  dictionary if any semantic group had no authoritative full translation. This
  discarded direct fixed-ID mappings already accepted for earlier groups.
- Fix: the allocation owner records the missing group's expected IDs as a
  blocking structure error and unresolved allocation, then continues with the
  remaining groups. Existing fixed-ID mappings remain intact; final validation
  still blocks the missing Chinese cue.
- Regression: a prior single-cue group keeps `S0001` while the later missing
  full translation is reported only for `S0002`.
## 2026-08-04 Parser-Confirmed English Boundary Protection

- Root cause: stable pre-ID cutting did not protect several parser-confirmed
  local dependencies, allowing a cue boundary after an object before a content
  clause, inside compact coordination, or before a verb-attached post-object
  modifier.
- Added local, pause-aware protections for these dependency shapes. A
  comma-delimited `but`, `or`, `so`, or `yet` finite-clause transition remains
  outside the compact-coordination rule so approved visual temporal splits are
  preserved.
- Regressions cover coordinated predicates and lists, object-content clauses,
  object-attached modifiers, and the existing non-finite-prefix/visual-clause
  behavior. English text, word order, word timestamps, post-ID timing,
  Chinese allocation, and export are unchanged.

## 2026-08-04 Relative-Clause Predicate Boundary E2E

- Root cause: the final pre-ID validator did not inspect a right cue for a
  finite predicate without a subject. The 480 ms pause at that invalid
  production boundary caused the generic repair window to skip it.
- Fix: `right_orphaned_finite_predicate` is now a final-boundary hard issue.
  The repair loop may cross only that target boundary's pause and only for a
  direct merge that passes the pre-existing structural-overflow proof. It does
  not relax the pause rule for generic repartitioning.
- Added a 480 ms regression for `yet ... are completely contradicted ...`.
  `tests/test_stable_caption_rules.py`, `scripts/run_regression.py`, and
  `git diff --check` passed.
- The first isolated E2E artifact remains preserved as a failing regression
  witness. The second E2E subtitle-only rerun passed with 276 fixed IDs,
  `render_blocked=false`, zero final-timeline errors, and delegated 7/10/15/18
  second PNG review. No video was synthesized.

## 2026-08-04 Article Template Structural-Overflow Rendering

- Root cause: the article-template renderer sliced Chinese wrapping to two
  lines, silently dropping all remaining translated characters for a long,
  structurally protected English cue.
- Fix: the renderer now selects the largest Chinese font that fits the complete
  translation in two lines and draws every wrapped line. It does not change
  English boundaries, text, IDs, word ledger, Chinese allocation, or timing.
- Real S0004 offline frame validation confirmed the full 77-character Chinese
  text, zero English/Chinese alpha-mask overlap, and no crop. The evidence is
  under `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\overflow-fix-frame`.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`,
  `runtime\python.exe -X utf8 scripts\run_regression.py`, and
  `git diff --check` passed. No long production video was rerendered.
