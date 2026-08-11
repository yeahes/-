# Progress Log

## 2026-08-11 Full-Strength First Vocabulary Card

- Reproduced the reported pale first card as a renderer-cache interaction. The
  title-to-card transition depended on frame time, while the cached frame key
  contained only card identity and subtitle state. A partially blended first
  frame could therefore remain unchanged until the following subtitle.
- Removed the first-card fade and its time-dependent rendering branch. The
  right panel still shows the episode title before the first eligible card; at
  the card's exact final-page start it switches directly to the complete card,
  which remains until replacement.
- Added a focused regression that checks both the first and a later card at
  their exact trigger times, verifies full card drawing, and rejects image
  blending. Vocabulary selection, timing, subtitles, IDs, SRT/ASS, manifest,
  and synthesis routing are unchanged.
- Two focused tests and Python syntax compilation pass. A pixel comparison
  confirms that the trigger frame's card area is identical to the settled card
  0.2 seconds later, while the preceding title frame differs. The complete
  25-stage regression exits zero in 380.5 seconds. Visual evidence:
  `tests/caption_audit/out/article-vocab-full-strength-first-card-20260811.png`.

## 2026-08-10 Semantic Two-Line Vocabulary Notes

- Replaced the article concept-note card's generic character wrapper with a
  dedicated two-line layout path. It uses the existing deterministic Chinese
  token boundaries, avoids attached punctuation and weak line starts, and
  prioritizes the semantic boundary after a short explanatory lead-in.
- The production note now renders as `本句用数学隐喻说明 / 留学回报的旧有优势已随市场变化而消失。`.
  Short notes remain one line; long notes remain capped at two lines.
- Two focused regressions and the existing card-content test pass. A read-only
  replay of 70 unique cached concept notes found zero content loss, overflow,
  non-token breaks, or invalid second-line starts.
- The checked 1920x1080 frame is
  `tests/caption_audit/out/article-vocab-semantic-wrap-20260810.png`.
- The unified regression completed 23/25 stages. Stable-caption smoke and the
  display-page translation contract fail on pre-existing English layout/font
  expectations that reproduce without the concept-note path. No English page
  behavior was changed here.
- No vocabulary prompt/cache schema, selection, timing, ASR, English or Chinese
  subtitle, fixed ID, timeline, SRT/ASS, manifest, or synthesis-entry contract
  changed. No full video or external model request ran.

## 2026-08-10 Multiline Title Input On Synthesis Page

- Replaced the one-line podcast title control with a 76px-high plain-text
  editor. Enter creates a real line boundary; Tab still moves focus instead of
  inserting a tab character.
- The UI saves `toPlainText()` and `TaskFactory` preserves internal newlines in
  `SynthesisConfig.podcast_template_title`. Automatic lexical wrapping remains
  available for titles entered on one line.
- The focused persistence/task test, complete video-synthesis safety script,
  syntax compilation, and 25-stage unified regression pass. The unified run
  completed in 412 seconds.
- A hidden-widget render confirmed a 1137x76 title control containing both
  requested lines without overlap. Evidence:
  `tests/caption_audit/out/synthesis-multiline-title-input-20260810.png`.
- No renderer, vocabulary, subtitle, cache, output-name, or manifest contract
  changed in this UI-only follow-up.

## 2026-08-10 Article Vocabulary Page Timing And Title Readability

- Reproduced early vocabulary cards when a selected phrase belonged to a later
  article display page but inherited the parent cue start. Article scheduling
  now binds each card to the final page containing its exact phrase and drops
  cross-page or ambiguous matches; dark-template timing is unchanged.
- Reproduced `中国年轻人为 / 何不爱留学了？`. The article opening title now
  chooses balanced breaks only from deterministic Chinese token or punctuation
  boundaries, preserves explicit newlines, and uses the bundled Heavy CJK face.
- Five focused card-timing checks, four focused title checks, the complete
  stable-caption script, and the 25-stage unified regression pass. The unified
  run completed in 395.1 seconds.
- Visual evidence:
  `tests/caption_audit/out/article-vocab-page-alignment-after-20260810.png` and
  `tests/caption_audit/out/study-abroad-title-wrap-heavy-20260810.png`.
- No prompt/cache schema, model selection, ASR, English segmentation, Chinese
  translation, fixed ID, final timeline, export, manifest, or synthesis-entry
  contract changed. No fresh full video was encoded.

## 2026-08-09 Manual Editor State Ownership Audit

- Audited the manual-final editor as a state machine rather than adding more
  sample-specific pagination rules. The live table draft, pending page plan,
  and published package now have explicit ownership and one session
  fingerprint for clean/dirty decisions.
- Active table delegates commit before structural actions, save, export,
  import-discard, and close. Parent Chinese writes back by fixed ID, frozen word
  range, time, and English identity; text edits are included in undo history.
- Repeated page splits and Chinese edits stay in memory and make no package
  write. Missing page Chinese can persist as a blocked checkpoint; formal
  publication still fails closed.
- Page edits and overrides clear/restore atomically. Save requests own their
  refresh intent, imports are blocked during publication, failed imports retain
  the current path, and stale review callbacks cannot reinstate edited IDs.
- REVIEW boundary metadata and unavailable-page blockers now reach table
  coloring, tooltips, and next-review navigation. Schema-3 manual overrides bind
  the edit journal hash and cross-check both ledgers on reload.
- Read-only replay of the real study-abroad package exposed 303/303 pages and
  20 REVIEW boundaries. A two-parent in-memory edit retained the first Chinese,
  called no save function, and left all 11 package hashes unchanged.
- Manual-final editor tests pass 36/36, stable-publication UI tests pass 43/43,
  video-synthesis safety passes 24/24, and unified regression passes 678/678
  plus syntax in 335.161 seconds. `git diff --check` passes.
- Windows QPA constructed the hidden real editor widget, but strict offscreen
  QPA remained blocked at `QApplication` initialization and the bounded widget
  grab produced no screenshot. This is recorded as an uncompleted visual audit,
  not a pass. No network, ASR, LLM, FFmpeg, synthesis, or paid request ran.

## 2026-08-07 Manual-Final Save Responsiveness

- A production GUI save of the 203-cue `中国AI为何更省钱？` failure checkpoint
  blocked the Qt event loop for about three minutes. The save did complete and
  publish a fail-closed manual package; no subtitle data was lost.
- Root cause profiling attributes 188.384 of 188.806 seconds to deterministic
  page-blueprint construction, dominated by 690,471 font-width measurements.
  SRT and JSON writes together were below half a second.
- The editor now deep-copies the synchronized manual session, disables editing
  and manual-final actions, and performs the unchanged package/page validation
  in a background worker. A Qt signal applies the result on the GUI thread;
  thread-start failures restore the controls, concurrent saves are serialized,
  and application exit is blocked until publication finishes.
- Focused publication regression and targeted `git diff --check` pass. The
  delegated real-checkpoint replay terminated normally, kept the expected
  `manual_page_translation_required` gate, made zero external/ASR/LLM/FFmpeg
  calls, and did not modify the production source checkpoint.
- Evidence:
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-manual-save-profile-20260807-r2`.

## 2026-08-07 Page Contract v9 and Cache-First Subtitle E2E

- Reordered display-plan selection so high-confidence structural risk and
  medium-confidence review risk are considered before measured visual cost;
  low-confidence hints remain soft. This lets a readable 50px static page
  beat a risky page turn without making uncertain ordinary cues shrink.
- Bumped only the page planner contract to
  `article-fixed-font-pages-v9`. ASR, complete-translation, and fixed-ID
  allocation caches retain their independent fingerprints.
- Focused page suites and the unified regression pass. Offline replay planned
  both real-audio samples completely with zero external requests; delegated
  representative frame checks reported zero structural, word-coverage,
  hard-boundary, font-floor, minimum-duration, blank, crop, overlap, or
  transition failures.
- The cache-first `How to Identify AI Writing Style` subtitle E2E completed at
  `E:\VideoCaptioner-e2e-runs\ai-writing-style-page-contract-v9-e2e-20260807-r1`.
  It reran current boundaries, WhisperX time-only, v9 planning, page Chinese,
  and publication from the same-audio ASR artifact: 207 cues, 1,993 words,
  final timeline `PASS`, no `source_audio_missing`, and no overall backend
  fallback. Three local expansion/compression protections are recorded.
- Full translation/allocation reused 17 cached batches. One v9 page-translation
  cache miss produced one external request and is now cached. The production
  page artifact is `PASS` with 233 pages, 26 transitions, and one non-blocking
  S0082 Chinese-fragment review.
- Delegated pre-synthesis validation passed all 207 IDs, 1,993 words, 233
  pages, 26 transitions, and 17 representative page/transition frames with
  zero structural, content, crop, overlap, blank, font-floor, or transition
  failures.
- Final synthesis consumed the stable manifest and original audio directly,
  disabled unrelated AI vocabulary cards, and made zero external requests. It
  completed in about 6 minutes 49 seconds and wrote `final-video.mp4`
  (30,157,031 bytes) under the E2E run.
- The actual MP4 fully decoded 16,684 frames over 667.341497 seconds. The final
  validator extracted 291 unique frames covering every page midpoint, every
  transition before/after pair, three timing probes, and S0082. Decode, crop,
  bilingual overlap, blank, wrong-page/content, transition, word-envelope,
  and alignment-probe failure counts were all zero. S0082 remains only a
  non-blocking Chinese continuation punctuation/fluency review; no automatic
  rewrite or repeat synthesis was performed.

## 2026-08-06 Fixed-ID Display-Page Contract E2E

- Replaced proportional parent-Chinese slicing with a post-timing display-page
  contract. Page IDs are deterministic children of the frozen subtitle ID;
  parent English, ID, word span, cue timing, SRT, and ASS structure stay fixed.
- Page responses are checked for exact ID/cardinality, semantic ownership,
  fixed-font fit, reading speed, cache fingerprint, contract hash, and artifact
  digest. Writes are atomic and failures block before synthesis.
- Added focused fixtures for reordered `S0078`, monotonic `S0252`, stale or
  tampered artifacts, write failure, cache invalidation, and parent-contract
  drift. Added generic page-boundary regressions for non-finite complements and
  numeric compound heads.
- Real E2E passed at
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r1`:
  262 frozen cues, 2,897 words, 46 multipage parents / 94 pages, final timeline
  `PASS`, `whisperx-time-only`, no overall fallback, no
  `source_audio_missing`, and unchanged frozen signature.
- Final synthesis produced `final-video.mp4` (46,217,829 bytes, 1003.66s,
  1920x1080 H.264/AAC). Production ffmpeg fully decoded it with zero errors;
  ffprobe was unavailable. Total external requests across four attempts: 11;
  the successful attempt used one and synthesis used zero.
- Targeted visual validation passed 22/22 sampled frames for `S0062`, `S0078`,
  `S0111`, `S0252`, all associated +/-80ms page transitions, and the
  64.8/65.6/66.4s speech interval. No sampled shrink, crop, overlap, blank, or
  page reversal was observed. The report does not claim full-video frame-by-
  frame manual review.
- Remaining risk: a separate unseen audio has not yet established a 90% blind
  reliability claim. Manual-final multipage Chinese overrides remain
  fail-closed until a page-aware editor exists.

## 2026-08-06 Boundary and Renderer Follow-up (committed as 3c70f4b)

- Corrected the renderer's grammar gate so a complete phrase such as
  `from human feedback` may begin a static line/page with a soft preference
  penalty, while lexical dependencies remain hard-blocked. Regression cases
  cover `according | to`, `completely | out`, and `far more | than`.
- Added parser-confirmed guards for zero-relative clause entrances and
  post-noun participial modifiers in the pre-ID English boundary stage.
- Extracted deterministic word-span page planning into
  `stable_display_planner.py`; the planner is presentation-only and cannot
  mutate frozen cue IDs, text, or timings.
- `tests/test_english_boundary_rules.py`,
  `tests/test_stable_caption_rules.py`, `scripts/run_regression.py`, and
  `git diff --check` pass. Real-audio E2E and synthesis remain the next gate;
  no external request was made by this follow-up.

## 2026-08-06 Real-Audio E2E Follow-up

- Replayed the same read-only `中国AI为何更省钱？.m4a` through the current
  stable pipeline with `SubtitleTask.source_audio_path` pointing at the
  original audio and all run output isolated under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-followup`.
- Subtitle gate passed: 266/266 fixed IDs, 2,897 ledger words, complete English
  and Chinese mappings, final timeline `PASS`, applied backend
  `whisperx-time-only`, no overall fallback, and no `source_audio_missing`.
  The 64.8-66.5s interval remains covered by `S0017` through 67.975s.
- External request count was 0 because all translation/allocation work came
  from the isolated E2E cache. WhisperX had eight per-word stable-ledger
  timing retentions, but did not trigger an overall fallback.
- Synthesis did not reach ffmpeg: the renderer's fixed-font structural gate
  rejected `S0052`, `S0176`, `S0196`, and `S0258` with
  `render_structural_overflow / no_fixed_font_page_partition`. No video was
  created. This was recorded as a blocking renderer risk instead of bypassed
  by altering English, IDs, timing, font size, or visual pagination.

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

## 2026-08-04 Article Template Visual Pagination

- The prior no-truncation repair was necessary but not sufficient: S0004 still
  showed its entire 37-word English/77-character Chinese cue in one screen.
  This preserved text but was not readable.
- Long article-template cues now paginate deterministically inside their
  existing frozen cue envelope. The page budget is at most 16 English words or
  30 Chinese characters; page transitions use equal fractions of the original
  cue duration. English, Chinese, IDs, word spans, cue times, allocation, SRT,
  ASS, and manifest output do not change.
- The render cache now includes the page index. The real S0004 at 13.5s,
  17.5s, and 21.5s produced three PNGs, each with two English lines and one
  Chinese line, no clip, zero visible English/Chinese overlap, and exact
  full-text reconstruction across pages. Evidence is under
  `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\visual-pagination-validation`.
- Delegated `tests\test_stable_caption_rules.py`, unified regression, and
  `git diff --check` passed. No external request or full video synthesis ran.

## 2026-08-04 Formal English Boundary Ownership

- Root cause: the formal pre-ID stage list still called the visual
  12-word/68-character budget pass. A display preference could therefore
  create frozen English IDs and fragment the downstream Chinese allocation.
- Fix: removed `_apply_visual_reading_budget` from the production stage list.
  It remains an offline historical diagnostic, while renderer-only pagination
  owns visual page breaks after formal English, IDs, and Chinese are frozen.
- Regression injects a raising visual-budget method and proves the finalizer
  does not invoke it; a 14-word grammatical cue stays one formal item.
- Delegated validation passed:
  `tests\test_stable_boundary_finalization.py`,
  `tests\test_stable_caption_rules.py`, `scripts\run_regression.py`, and
  `git diff --check`. No ASR, LLM request, or synthesis ran.

## 2026-08-04 Whole-File English Boundary Evidence Audit

- Root cause: the prior syntax audit examined only selected text pairs and
  could not distinguish an unresolved atomic split from a legitimate boundary
  supported by word timing, punctuation, or a speaker change.
- Fix: `english-boundary-audit.json` now records every final English boundary
  as `hard`, `review`, or `allow`. The scanner combines existing deterministic
  syntax rules with frozen word ranges, actual word pause, sentence terminal,
  continuity, and speaker evidence. It never mutates a final ID, translation,
  timing, SRT, or ASS cue.
- A residual `hard` record is now a blocking validation error. `review` records
  remain timed human-review entries; `allow` records remain only in the full
  machine artifact. Start-word part of speech alone cannot produce an error.
- Added screenshot-derived fixture cases for `three long | em-dashes`,
  `far more | than`, `completely | out`, `according | to`, and numeric
  magnitudes, plus allowed terminal-clause counterexamples and the long-pause
  review downgrade.
- Delegated validation passed:
  `tests\test_english_boundary_rules.py`,
  `tests\test_stable_caption_rules.py`, `scripts\run_regression.py`, and
  `git diff --check`. No ASR, LLM request, or synthesis ran.

## 2026-08-04 Article Renderer Word-Timeline Gate

- The article renderer now fails closed when the stable manifest, final cue
  timeline, or word ledger is missing or mismatched, even when all cues would
  otherwise fit on one page. This prevents unverified timing from reaching
  synthesis.
- Fixed 58px English / 46px Chinese pagination remains renderer-only. Page
  switches require ledger word gaps and 900ms minimum page duration; no font
  shrinking or cue/ID mutation is used as a fallback.
- Full-artifact preflight found 212/215 plans valid. `S0188`, `S0202`, and
  `S0208` remain blocked because no grammar-safe word-gap schedule satisfies
  the minimum page duration. Evidence:
  `E:\VideoCaptioner-e2e-runs\renderer-word-timeline-validation\preflight-short-cues.md`.

## 2026-08-04 Static Fixed-Width Renderer Layout

- Root cause: a same-page visual wrap and a timed visual page were treated as
  the same operation. The renderer then required a word-gap transition for
  text that already fit in two fixed-font lines. Chinese layout also used a
  30-character cutoff instead of the rendered 46px width.
- The planner now uses actual pixels: normal 1455px English width, then a
  1498px safe-width profile, with up to two static English lines. Chinese uses
  up to two 46px lines without a character-count gate. Only a cue that fails
  both static layouts is eligible for word-timed pagination and its 900ms gate.
- Offline replay of `ai-writing-style-full-e2e-20260804` now gives 215/215
  valid plans. `S0188`, `S0202`, `S0208`, and the former residual `S0110` stay
  on one static page with unchanged frozen cue data. Representative PNG/report:
  `E:\VideoCaptioner-e2e-runs\renderer-layout-profile-validation`.
- Delegated regression passed: `tests\test_stable_caption_rules.py`,
  `scripts\run_regression.py`, and `git diff --check`. No ASR, LLM request,
  or full-video synthesis ran.

## 2026-08-05 Chinese Compression Follow-up and Current-Code E2E

- Root cause: Chinese compression was evaluated before final display-duration
  reconciliation, and a single valid cue could be rejected by a multi-cue
  allocation coverage gate. LLM compression also occasionally omitted only
  the terminal punctuation of the frozen complete cue.
- Fix: run compression after display reconciliation; preserve terminal Chinese
  punctuation; allow a single cue only when local fragment, duplicate, semantic,
  and speed checks all pass. English text, boundaries, IDs, word spans, and
  alignment ownership remain unchanged.
- Focused tests, unified regression, and `git diff --check` passed.
- Cached current-code E2E for `中国AI为何更省钱？.m4a` completed with 273/273
  fixed IDs and Chinese mappings, `final-cue-timeline.json` validation `PASS`,
  `applied_backend=whisperx-time-only`, `fallback_used=false`, and zero
  `source_audio_missing`. Synthesis produced a 61,356,806-byte MP4 under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805`.
- Vocabulary-card generation timed out and was skipped after 301.7 seconds;
  this did not block subtitle rendering. The QA queue retains 40 review items
  and two unresolved allocation-quality items.

## 2026-08-05 Chinese Visual Page Word-Boundary Guard

- Root cause: renderer-only Chinese page allocation used raw character offsets
  proportional to English word counts, so `大陆` could be cut as `大 | 陆`.
- Added the required MIT `jieba` 0.42.1 runtime subset under `app/_vendor`.
  Strict article page planning uses its deterministic word-end offsets plus
  punctuation/phrase evidence. It fails closed with
  `chinese_no_safe_visual_boundary` when no safe split exists; no character
  slicing, font shrinking, cue mutation, or translation rerun is used.
- The real 273-cue `china-ai-cheaper-e2e-20260805` artifact replays with
  273/273 valid plans. S0055 now ends page one at `大陆` and starts page two
  at `那么`. Updated PNG evidence is under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805\visual-pagination-fixed-20260805`.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`,
  `runtime\python.exe -X utf8 scripts\run_regression.py`, and
  `git diff --check` passed. No external request or full-video synthesis ran.

## 2026-08-05 Boundary/Allocation E2E Regression Completion

- English pre-ID fixes are now isolated from the Chinese allocation contract:
  numeric result guards stop at punctuation/coordinators, content nouns stay
  with attached `that` clauses, and a complete `Oh.` lead-in may use the
  existing one-word structural overflow exception.
- Full-group Chinese translation cache keys no longer change when only the
  fixed-ID allocation algorithm changes. Verified legacy full-translation keys
  migrate once; allocation keys remain invalidated by the current frozen spans
  and algorithm version. Allocation validation rejects bare syntactic heads and
  displaced main clauses.
- Visual pagination protects English modifier heads and Chinese token boundaries
  using the vendored tokenizer. Unsafe Chinese page cuts fail closed without
  mutating frozen cue data.
- Current-code cached E2E for `中国AI为何更省钱？.m4a` completed at
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805-r3`: 271 IDs,
  2,897 ledger words, final timeline `PASS`,
  `applied_backend=whisperx-time-only`, no overall fallback, and no
  `source_audio_missing`. The 64.8-66.5s interval remains covered by S0019
  through 67.975s.
- Synthesis completed once at
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805-r3\final-video.mp4`
  (62,239,995 bytes; 16:43.66; 1920x1080 H.264/AAC). Vocabulary generation
  timed out after 319.1s and was skipped. Subtitle cache statistics recorded
  21 misses (13 full translations, 1 style retry, 4 allocations, 3 fragment
  retries); vocabulary per-attempt count is not instrumented.
- `runtime\python.exe -X utf8 scripts\run_regression.py` and `git diff --check`
  passed. QA has zero structural blockers and three unresolved Chinese
  allocation-quality reviews.

## 2026-08-06 WhisperX Expansion-Sensitive Timing Acceptance

- Root cause: final `whisperx-time-only` trusted exact normalized token matches
  even when a compact written numeral, currency value, year, or acronym
  represented several spoken words. The affected token could be compressed to
  a fraction of the frozen stable-ts duration and shift later word times early
  until WhisperX found a new acoustic anchor.
- The final frozen-ledger mapper now rejects only that local drift run and
  restores its original word times. It stops at the first word whose start/end
  drift returns to the pre-trigger anchor and caps one fallback run at 24
  words. Text, word IDs, order, cue ownership, and unrelated WhisperX times are
  immutable.
- The fallback is recorded as `whisperx_expansion_compression_fallback` in the
  final alignment provenance. The new acceptance gate is enabled only for
  final `whisperx-time-only`; the full-WhisperX pre-cut path is unchanged.
- Regression replays the production `53 billion ... 2026 ... 2028` compression:
  affected words restore `412.600-417.020s`, the recovery word `Now` remains
  on WhisperX at `417.580-417.720s`, and text, word IDs, order, and the default
  full-WhisperX mapping remain unchanged. Unified regression and
  `git diff --check` pass; external requests and synthesis were not run.

## 2026-08-06 56px Visual Budget and Manual-Final Checkpoint

- Changed the article English default from 58px to 56px and made the 16-word
  visual-page limit a planning penalty instead of a feasibility gate. Grammar,
  measured pixels, and minimum page duration remain higher-priority evidence.
- Added a recorded 54/52/50/48/46px fallback sequence for cues that have no safe
  higher-size plan. Font fallback cannot mutate frozen cue IDs, text, spans,
  timing, or Chinese allocation.
- Reduced editor noise by consuming the completed English boundary audit and
  surfacing only high-confidence English/Chinese, cue-edge timing fallback, and
  high-risk page-boundary evidence.
- Editor saves now publish a separate, hash-bound `人工终稿字幕包/`. Valid packages
  carry their source-media path and can be imported directly by the synthesis
  page; unresolved page-level Chinese mappings save as blocked checkpoints, so
  upstream ASR/translation work does not need to be repeated.
- Focused manual-final and synthesis-safety tests pass. No external request or
  synthesis ran.
- Bumped the page planner contract to `article-fixed-font-pages-v6`. A verified
  pause of at least 600ms may downgrade only clause-level subject/predicate or
  `that` + `-ing` page boundaries to high-confidence review; lexical phrase
  boundaries remain hard. This resolves the 28-word `S0120` case through its
  actual 901ms and 800ms pauses rather than a text-specific exception or a
  smaller font.
- Final v6 offline replay under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r10-offline-audit`
  plans 262/262 cues with zero failures. Font distribution is 56=242, 54=2,
  52=8, 50=5, 48=1, and 46=4. Twenty-one pages exceed the soft 16-word budget;
  selected boundary review is high=3, medium=8, acceptable=11, and none of the
  10 known bad cuts remains.
- `S0120` now uses three 56px pages split after `sources,` and at the verified
  800ms `gear | is` pause. No frozen cue, text, ID, Chinese mapping, or timing
  changed. Unified regression and representative transition-frame validation
  remain pending.

## 2026-08-06 50px English Font Floor and v7 Validation

- The v6 `54/52/50/48/46px` fallback sequence is superseded. Article English
  now defaults to 56px and may fall back only through 54px, 52px, and 50px.
  A cue that cannot satisfy the fixed two-line, legal-boundary, and timing
  contracts at 50px fails with `render_structural_overflow`; it cannot silently
  shrink further.
- The page planner contract is `article-fixed-font-pages-v7`, which invalidates
  render plans and page-translation caches created under the lower font floor.
  The change does not alter frozen English, subtitle IDs, Chinese ownership,
  word spans, or cue timing.
- Final offline replay under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r11-offline-audit`
  plans 262/262 cues and 289 pages with zero structural failures. Font
  distribution is 56px=247, 54px=2, 52px=8, and 50px=5. No page uses a font
  below 50px; all paginated pages last at least 1351ms.
- Twenty-nine representative 1920x1080 frames and six before/after transition
  pairs have zero blank frame, crop, bilingual overlap, page-time mismatch, or
  transition failure. Missing, duplicate, reordered, and uncovered word IDs
  are all zero.
- Four high-risk and twelve medium-risk semantic page boundaries remain for
  editor review. They are reported instead of being hidden by extra font
  reduction or sample-specific rules. Nineteen pages exceed the 16-word soft
  budget because a safer shorter partition was unavailable.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`, the four
  focused manual/package/page-contract suites, unified regression, and
  `git diff --check` pass. Validation used zero network, ASR, LLM, FFmpeg, or
  paid external requests.

## 2026-08-07 Page Contract v8 and Current-Code E2E

- Replaced the single-width page objective with a measured display objective:
  1260px comfortable width, 1455/1498px controlled fit widths, 56/54/52/50px
  fonts, and a global cost over pixel load, word load, spoken duration, short
  pages, syntax confidence, and balance. The display layer still cannot change
  formal English, IDs, word ownership, cue timing, SRT, or ASS boundaries.
- Added shared vendored Chinese token boundaries to the page allocation
  contract and reject page responses that split a Chinese token. Page-level
  Chinese is validated by exact page ID and aggregate parent content.
- Removed a duplicate unconditional `-ing/-ed + complement` prohibition. The
  authoritative rule is now pause-aware: attachments at or below 200ms remain
  hard, while a 400ms pause may enter the scored candidate set. Focused tests
  preserve `locked | in` at its real 80ms pause and allow the separate 400ms
  control case.
- `tests/test_article_display_readability_contract.py` passes 7/7, the page
  contract suite passes, the complete unified regression exits 0, and
  `git diff --check` reports no whitespace errors.
- Fresh E2E output is under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260807-page-contract-v8-r1`.
  It contains 259 fixed cues, 2,897 words, complete English/Chinese ID mapping,
  final timeline `PASS`, `whisperx-time-only`, no missing source audio, and no
  overall stable-ts backend fallback. Ten local numeral/acronym timing
  protections are recorded separately.
- Relative to the prior 262-cue artifact, the current pre-ID finalizer changes
  seven actual boundaries (five removed, two added). It removes known fragment
  boundaries such as `center | might` and `U.S. | right now`; the remaining
  244 positional differences are downstream ID renumbering, not 244 rewritten
  English cues.
- Page translation is `PASS`: 40 multi-page parents and 83 translated display
  pages. The frozen renderer artifact has 259 plans, 302 total pages, and 43
  transitions. Two continuation reviews remain non-blocking; the fixed-ID
  editor artifact contains one high-confidence allocation review.
- Frozen-artifact validation rendered 388 frames and reports zero mechanical or
  pixel failures. The authoritative report is
  `full-page-validation/frozen-artifact-full-validation.json`. A separate
  reconstructed offline replay yields 303 pages because it regenerates syntax
  evidence; synthesis loads the published hash-bound 302-page plan instead.
- The run made 22 DeepSeek requests: 14 full translation batches, three normal
  allocation batches, three fragment retries, one allocation retry, and one
  page translation batch. ASR requests were zero. Final synthesis ran once,
  with vocabulary cards disabled, and produced `final-video.mp4` (45,540,482
  bytes).
- The encoded MP4 then passed a separate zero-network validation. It extracted
  391/391 frames: 302 page midpoints, 86 before/after frames for all 43 page
  transitions, plus 64.8/65.6/66.5-second anchors. Every frame matched the
  published frozen artifact, and blank subtitle, crop, bilingual overlap,
  frozen-pixel mismatch, and transition failure counts were all zero.

## 2026-08-07 Page Contract v10 and Editor-Comparison Export

- Eight real 203-cue items could not satisfy the strict v9 page partition at
  50px or larger. V10 exhausts strict candidates first, supports at most four
  pages, and only then permits a complete continuation phrase/clause as a
  high-risk reviewed display boundary. Frozen parent IDs, English, word spans,
  timing, and word timestamps remain unchanged.
- Fixed dynamic-program risk propagation, published every render plan and the
  complete word-ledger-bound display-boundary evidence, and added planning
  memoization. The eight hardest fixture cues now plan in 71.631 seconds versus
  about 142 seconds before caching.
- Manual-final publication exports a page-level bilingual SRT plus exact page
  map. A missing/invalid page translation remains render-blocked and editable;
  no raw Chinese character slicing or silent font reduction is used.
- Fresh E2E under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-page-contract-v10-e2e-20260807-r1`
  produced 203 parent cues, 2,548 words, 252 pages, 49 transitions, and 38
  multipage parents. Minimum English font is 50px and minimum timed-page
  duration is 1,051ms. Final timing is `PASS` with
  `applied_backend=whisperx-time-only`, no `source_audio_missing`, and no
  overall backend fallback.
- External requests were 15: ten full-translation batches, three normal
  fixed-ID allocations, one fragment retry, and one page-translation request.
  No external ASR request or video synthesis ran.
- The older 16:36 checkpoint was rejected as an exact baseline because it
  omitted or rewrote four source words that are present in the shared input
  SRT. The current result instead passes its internal frozen ID/ledger/timeline
  contracts.
- Independent validation passed all 252 exported SRT/map pages and 2,548 word
  IDs. Forty-seven rendered midpoint and transition frames across the eight
  former hard cues had zero blank, crop, or bilingual overlap failures. Nine
  English page-boundary reviews and one S0202 Chinese continuation review remain
  visible for human judgment.

## 2026-08-07 Article-Correction Ownership and Full Review Queue

- The real v10 article-correction log showed `.S., Japan, -> Japan,` applied
  even though its entity gate failed with
  `candidate_would_delete_non_entity_token`. The fuzzy two-source-token collapse
  considered the whole window similar to `Japan` without proving that `S.`
  contributed to the canonical entity.
- Collapsed entity matching now requires character contribution from every
  source token. A lossless split form such as `A Drift -> Adrift` is promoted
  through the entity gate, while a failed gate cannot be overridden later.
- The playable QA queue no longer truncates `REVIEW` entries after the first
  12. It still excludes `INFO`, deduplicates identical code/ID findings, and
  preserves severity ordering from the QA summary.
- Direct article-correction tests pass 25/25, the QA queue script passes, and
  the saved v10 `.S., Japan,` candidate now returns
  `candidate_would_delete_non_entity_token` with `should_apply=False`.
- A read-only rebuild of the v10 QA data returns 0 blockers, 51 reviews, 12
  info items, and 51 default queue entries with zero omitted. The old queue's
  12 visible / 22 omitted metadata was not overwritten.
- Unified regression completed in 218.6 seconds with no failed suite;
  `git diff --check` exited 0 with only repository line-ending notices.
- This change does not alter English segmentation or word budgets, Chinese
  allocation, display pagination, timing, or rendering.

## 2026-08-08 Manual Draft and Actual Page Preview

- Root cause: `保存人工终稿` persisted a blocked checkpoint but exposed no
  user-authorized preview path. The UI hid the synthesis action and every
  downstream synthesis layer correctly rejected `render_blocked`, so users
  could not inspect a draft even when the only remaining risk was pagination.
- Added an explicit manual-draft capability from editor to home, synthesis
  input, task factory, synthesis thread, and article renderer. It is limited to
  three page-quality blockers, only applies to the `文章单词` template, and
  writes `【人工草稿】<media-stem>.mp4`.
- The capability does not weaken formal synthesis. SRT ownership/hash, manual
  package schema, final timeline and word-ledger hashes, fixed IDs, word spans,
  English text, and cue times are revalidated before draft page planning.
- The editor model now displays the saved renderer projection per cue and
  opens exact page detail. Any text edit removes the stale preview and clears
  both synthesis actions until another background save completes.
- The first v10 read-only replay exposed only 171/203 rows because the preview
  compared current Chinese with a stale `render_plans[].chinese` copy. It now
  uses `parents[].aggregate_chinese`; the replay returns 203/203 rows, 252
  pages, `S0202=4`, and zero missing IDs.
- Manual-editor, synthesis-safety, and publication tests pass. Unified
  regression passes in 223.132 seconds; `git diff --check` passes with only
  existing line-ending notices. External request count is zero; no synthesis
  has run.

## 2026-08-08 Audio-Folder SRT Package Recovery

- Reproduced the GUI failure from the application log: synthesis selected
  `C:\Users\19379\Desktop\中国AI为何更省钱？\中国AI为何更省钱？-原文在上双语字幕.srt`
  directly, so the article renderer had no adjacent final timeline or word
  ledger and raised `missing_or_mismatched_word_ledger` before FFmpeg.
- The same detached SRT also explained why importing it into the subtitle
  editor left `合成草稿` disabled: manifest discovery previously compared paths
  only and could not reconnect a renamed byte-for-byte copy.
- Manifest discovery now accepts only exact path or SHA-256 identity, prefers
  a saved manual package over an older hash-identical checkpoint, and restores
  editor/synthesis draft state only after the existing package hash gates pass.
- Manual save publishes and records a media-named SRT; saving that source copy
  uses a media-named portable package. Normal stable success also writes the
  media-named SRT. No English, Chinese,
  cue ID, word span, cue time, page-planning rule, or renderer style changed.

## 2026-08-08 Persisted Manual-Draft Pages

- Fixed the false invalidation that disabled synthesis after review marks were
  painted: background/tooltip `dataChanged` roles no longer count as text
  edits; English/Chinese `EditRole` updates still invalidate the saved package.
- Page-blocked saves now materialize `manual-draft-page-plan.json` with an
  explicit Chinese mapping for every frozen page and bind it by SHA-256 in the
  manifest and manual override. The editor and renderer read the same file.
- Manual-draft preflight now rejects missing, tampered, or cross-package page
  artifacts. It never recalculates pages during synthesis.
- Saved sessions own their package artifact directory and publish the current
  `translations.json`; incomplete legacy packages keep their source-artifact
  fallback until the next save.
- The current desktop package replayed as 203 plans / 252 pages, minimum 50px,
  with non-empty explicit Chinese on every page. No artifact was written back.
- Focused suites and unified regression pass; unified runtime was 284.672s and
  `git diff --check` returned zero. External requests and FFmpeg runs: zero.

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

## 2026-08-08 Flat Actual-Page Editor Contract

- Replaced the parent-row `actual pages` count/detail column with the normal
  four-column table projected as one real display page per row. This exposes
  the exact page timing and bilingual text where editing already happens and
  restores the full English/Chinese table width.
- Every page row retains its deterministic page ID, unchanged parent subtitle
  ID, continuous word range, page time, and selected font size. English remains
  frozen in page view; Chinese is directly editable. The user can switch to
  `查看父字幕` for word-ledger-backed formal English boundary operations.
- Page-view save validates all page identities and reuses the existing
  SHA-256-bound page artifact for no-op or Chinese-only edits. It never invokes
  a replacement page plan; identity, span, or time drift blocks the save.
- Stable publication and manual-final save now emit a discoverable
  `<media-stem>-实际分页双语字幕.srt` plus
  `<media-stem>-实际分页映射.json` next to the source audio. Authoritative page
  SRT import recovers parent/page ownership instead of minting new fixed IDs.
- Focused manual-editor and publication suites pass. The second full unified
  regression completed naturally with 25/25 suites passing, exit code 0, in
  494.303 seconds. Final `git diff --check` passes with only existing line-ending
  notices. No network, ASR, LLM, FFmpeg, synthesis, or paid request ran.

## 2026-08-08 V16 Frozen Whole-Episode Page Plan

- Root cause: a validated whole-episode page sequence was later replanned by
  the per-cue renderer. The replacement page identity no longer matched the
  fixed page-Chinese artifact, producing
  `missing_or_invalid_display_page_translations` downstream.
- `article-fixed-font-pages-v16` makes an applied `frozen_*` plan authoritative
  for renderer, editor preview, and manual-final save. It also removes
  `medium_risk_count` as an absolute whole-sequence rejection, protects tight
  complements/modifiers, and prevents a finite verb such as `and` from being
  misclassified as a modifier boundary.
- The planner now compares whole-episode combinations of already valid
  cue-local plans and penalizes adjacent dense pages. It preserves fixed parent
  IDs, English, word ranges, cue timing, and the 56/54/52/50px font floor; only
  a 50px last-resort page may use three English lines.
- Old page Chinese is not reused after parent-level Chinese polish unless its
  ordered aggregate exactly equals the current parent Chinese. Error artifacts
  may expose identity-validated pages for editing, but cannot authorize formal
  synthesis.
- Offline rebuild output:
  `E:\VideoCaptioner-e2e-runs\study-abroad-page-contract-v16-final-r1-20260808`.
  It contains 261 parent cues, 2,862 words, 303 pages, 37 multipage parents,
  50px minimum English, eight controlled three-line pages,
  `render_blocked=false`, and a PASS display artifact. External requests: 0.
- Frame validation reused 907 existing PNGs and reports PASS: 303 midpoints,
  302 transition pairs, 261/261 parent matches, and zero crop, overlap, blank,
  transition, or page-induced flash errors. Fifteen short source-owned
  single-page cues remain warnings. No new rendering or video synthesis ran.
- Seven low-confidence cross-page Chinese mappings remain explicit editor
  review points: `S0118`, `S0158`, `S0196`, `S0214`, `S0238`, `S0240`, and
  `S0247`.
- `tests/test_stable_caption_rules.py` passes 377/377. Unified regression passes
  25/25 in 313.799 seconds.

## 2026-08-08 Parent-Boundary Inspector and Page Refresh Contract

- Replaced the context-poor parent-table boundary workflow with an inline,
  resizable master/detail inspector. A selected parent row exposes the complete
  neighboring English and Chinese, cue IDs and times, highlighted movable words,
  a bounded word-count control, direct bidirectional moves, and visible undo.
- The existing `ManualFinalSubtitleSession` word-ledger operations still own all
  cue changes. The UI does not create free-form word timing, synthetic IDs, or a
  second boundary implementation.
- A parent move, merge, or parent-row edit now invalidates the old whole-episode
  page plan immediately. Actual-page switching and both synthesis actions stay
  disabled until background manual-final save finishes and reloads the newly
  planned package. Boundary undo restores the parent cue but conservatively
  keeps the package dirty; page-Chinese undo stays in page view.
- Focused UI/publication regressions pass 13/13; the independent page-translation
  suite passes 35/35; unified regression passes 25/25 in 310.535 seconds; final
  `git diff --check` passes. A 1400x850 qwindows inspector render under
  `E:\VideoCaptioner-e2e-runs\manual-boundary-inspector-20260808` has no crop,
  overlap, or missing control. No ASR, LLM, FFmpeg, synthesis, or paid request ran.

## 2026-08-08 Inline Boundary Controls and Responsive Manual Save

- Replaced the detached boundary inspector with temporary controls embedded in
  the two affected English cells. The controls distinguish same-parent visual
  page moves from cross-parent formal cue moves and highlight the exact words
  that will transfer.
- Added responsive row sizing from the actual English-column width. The table
  completes both row resizes before installing index widgets, then constrains
  each widget to its final cell geometry. This prevents long English clipping
  and adjacent control overlap at narrow window sizes.
- Same-parent page moves persist absolute next-page start word IDs rather than
  deltas or a copied render plan. Save and reload validate those boundaries,
  rebuild only affected parent-derived layout/timing fields, preserve page IDs,
  and reject hard syntax cuts, empty pages, sub-900ms pages, or overflow.
- Unchanged parent cues reuse the SHA-bound frozen blueprint even when the user
  has not edited page Chinese. Formal parent-boundary edits continue to invoke
  full planning and invalidate stale page translation ownership.
- Saving is asynchronous and exposes action text, progress animation, and stage
  messages. It no longer appears frozen while page validation runs.
- Focused publication tests pass 16/16; the article display readability contract
  passes. Twelve qwindows screenshots at DPR 1.0/1.25/1.5 and 419px, 509px,
  and 569px English widths pass with zero crop, overlap, child overflow, or
  legacy-panel visibility. Evidence is under
  `E:\VideoCaptioner-e2e-runs\manual-row-boundary-editor-20260808-dpi-r2`.
  External requests, ASR, LLM, FFmpeg, and video synthesis: zero.
- Manual-final editor and video-synthesis safety suites pass. Unified regression
  passes 25/25 in 327.980 seconds; final `git diff --check` passes with existing
  line-ending notices only.

## 2026-08-09 Article-Term Correction and Manual Structural Operations

- Root cause for domain-term misses: every `technical_terms` glossary item was
  excluded from ASR correction even when the article explicitly defined a
  distinctive term and supplied alias evidence. Eligibility is now narrow and
  evidence-based; ordinary technical vocabulary remains protected.
- Root cause for surprising adjacent-row changes: row selection and boundary
  editing shared one activation path. Selection now installs only an explicit
  entry action. Direction choice previews source words; only confirmation moves
  a word-ledger boundary.
- Added a constrained two/three/four-page operation for one frozen parent cue.
  It reuses the production syntax, pause, layout, and scheduling planner instead
  of averaging characters or time. The parent contract is unchanged and every
  new page requires explicit Chinese review.
- Added reversible suffix deletion and non-destructive audio derivation. The
  shortened word ledger and final cue timeline remain ID-addressable prefixes;
  the original audio is hash-checked and never overwritten. Manifest resolution
  makes the derived audio authoritative, including callers that still pass the
  old source path. The first version is restricted to static podcast synthesis.
- The first qwindows capture found a transparent embedded entry widget: the
  table delegate English remained visible underneath the widget English. Entry
  and direction widgets now paint an opaque theme background, and a render
  assertion prevents this double-draw regression.
- Focused tests pass: article correction 29/29, stable publication 20/20,
  manual-final editor 23/23, and video-synthesis safety 24/24. Unified
  regression passes 589 tests across 24 suites plus one syntax check with zero
  failures in 338.622 seconds; `git diff --check` passes with existing
  line-ending notices only.
- Final UI evidence is under
  `E:\VideoCaptioner-e2e-runs\manual-structural-editor-20260809-final-ui`.
  The fixed DPR 1.0/1.25/1.5 captures pass 195/195 deterministic checks and
  visual review across 12 PNGs. The older transparent captures are retained and
  explicitly classified as FAIL evidence.
- The real FFmpeg fixture cut 1000ms to 1003ms, preserved the source hash, and
  proved identical-save reuse. External network, ASR, LLM, paid, and full-video
  calls are zero. No fresh arbitrary-audio E2E was run.

## 2026-08-09 Manual Page Intermediate-State Contract

- Split and moved display pages now use an editor intermediate state. Page
  Chinese may be empty while boundaries are adjusted; formal publication still
  reports `manual_page_translation_required` until all pages are filled.
- Explicit manual confirmation may downgrade grammar-risk and sub-900ms page
  choices to REVIEW. Automatic planning remains strict. Non-contiguous word
  ownership, empty English pages, ID/range drift, impossible shared timing, and
  fixed-font overflow remain hard failures.
- Repeated moves rebuild from the currently confirmed page ranges instead of the
  original one-page artifact. A blocked checkpoint retains the hash-bound English
  page plan and restores it on reload even when no draft artifact can be built.
- The editor exposes upper/lower boundary entry points, one-word direction reset,
  live word highlighting, explicit confirm text, review-color legend, and an
  enabled background `refresh actual pages` path after formal boundary changes.
- Manual-final editor tests pass 25/25 and stable publication tests pass 23/23.
  Unified regression passes 594 tests across 24 suites plus one syntax check
  with zero failures in 335.056 seconds; final `git diff --check` passes with
  line-ending notices only.
- The first DPR run found stale Qt index widgets covering the refreshed parent
  model. The cleanup path now retains widget references, hides each widget
  synchronously, detaches it from the table index, and schedules deletion.
- Final qwindows validation under
  `E:\VideoCaptioner-e2e-runs\manual-page-intermediate-editor-20260809`
  passes 510/510 checks across DPR 1.0/1.25/1.5. All 18 PNGs were reviewed;
  stale controls, clipping, and overlap are zero. External network, ASR, LLM,
  video synthesis, and paid requests are zero.

## 2026-08-09 Stable Word-Count Preview and Lean Review UI

- Root cause: every SpinBox `valueChanged` event rebuilt the two inline index
  widgets, destroying the control being clicked and making the edit state appear
  to exit. Word-count changes now update highlights, capacity, and confirm text
  on the existing widgets. Only explicit confirmation mutates subtitle data.
- The redundant `quality report` command-bar action is hidden. The report and
  review artifacts, deterministic gates, table colors/tooltips, and `next review`
  navigation remain active.
- Stable publication tests pass 24/24. Parameterized qwindows validation under
  `E:\VideoCaptioner-e2e-runs\manual-page-interaction-followup-20260809`
  passes 411/411 checks at DPR 1.0/1.25/1.5 across 18 reviewed PNGs. The same
  SpinBox and row widgets survive repeated `1 -> 2 -> 3 -> 2` changes without
  clipping, overlap, stale controls, or unintended subtitle mutation.
- Unified regression passes 595 tests across 24 suites plus one syntax check in
  337.197 seconds with zero failures. Final `git diff --check` passes with only
  line-ending notices. External network, ASR, LLM, synthesis, and paid requests
  are zero.

## 2026-08-09 Manual Boundary Evidence and Deferred Page Split

- Root cause: manual-final publication wrote back only the evidence keys needed
  inside the current cue partition. Undo or a later formal boundary move could
  make an omitted cue edge internal and trigger
  `manual_page_boundary_evidence_required`.
- Publication now preserves all adjacent word-ledger boundary evidence. Legacy
  packages recover only accepted cue-edge boundaries proven by current cues or
  undo history and mark them as REVIEW; unexplained internal evidence gaps still
  fail closed.
- Parent rows retain two/three/four-page commands while pages are stale. A
  requested split starts one background refresh and runs once after the matching
  package reload; save/reload failure clears the request without changing cues.
- The real desktop study-abroad package passed a read-only full-undo check with
  2,861/2,861 boundaries and no package hash changes. A temporary-copy save and
  reload retained the same coverage. The remaining
  `manual_page_translation_required` result correctly requests new page Chinese
  after boundary ownership changes.
- Focused tests and syntax checks pass. Unified regression passes 603 tests
  across 24 suites plus one syntax step in 332.064 seconds. `git diff --check`
  passes. External requests, ASR, LLM, synthesis, and paid requests are zero.

## 2026-08-09 Manual REVIEW Page Proposal

- Reproduced the desktop row 113 long cue as fixed parent `S0114`. Its best
  two-page boundary, `ability | to fit...`, is REVIEW rather than HARD, but the
  automatic continuation filter removed it after boundary classification.
- Kept automatic pagination strict and added a manual-only fallback that ranks
  REVIEW candidates after strict planning fails. The 900ms page floor, fixed
  fonts, layout fit, continuous word coverage, and HARD boundary rejection are
  unchanged.
- Added a regression for the exact 17-word sentence. Focused and full manual
  editor tests pass. The current desktop package proposes
  `1129..1137 | 1138..1145`, preserves every frozen parent field, and retains
  all 11 package file hashes. Unified regression passes 24 suites plus one
  syntax step in 338.772 seconds; `git diff --check` passes. External requests,
  ASR, LLM, synthesis, and paid requests are zero.

## 2026-08-09 Stale Actual-Page Import Recovery

- Reproduced the real desktop state: the actual-page SRT was generated before
  a later manual-final save. The later manifest correctly cleared page
  authority, but the source-folder page SRT remained and could still be chosen
  by the user.
- Import now treats that page SRT only as a hash-verified recovery pointer. Its
  companion map identifies the parent subtitle; manifest discovery then opens
  the latest parent manual package without copying stale page rows.
- The stale-import regression passes 1/1 and the full manual editor script
  passes 30/30. Real desktop replay resolves 261 current parent cues and leaves
  all 32 files / 42,933,689 bytes hash-identical.
- Unified regression passes 658 test items across 24 suites plus one syntax
  step in 338.800 seconds. `git diff --check` passes. External requests, ASR,
  LLM, FFmpeg, synthesis, and paid requests are zero.

## 2026-08-09 Stale Page-Chinese Visibility and Ownership

- Real desktop replay found 79 blank Chinese actual-page rows while every one
  of the 261 parent cues still had Chinese. The missing text existed only in
  the imported, older actual-page SRT; the current ERROR artifact had no page
  Chinese to display.
- Recovery now accepts old Chinese only after SRT hash, companion-map content,
  page ID, parent ID, word range, English, Chinese, and timing checks, followed
  by an exact match against the current frozen page identity.
- Recovered Chinese is an unconfirmed, non-authoritative draft. It is persisted
  separately through zero-confirmation and partial-confirmation checkpoints;
  it cannot update parent Chinese or pass formal publication.
- Read-only real replay passes with 303 rows, 79 stale drafts, zero blank
  Chinese rows, and 261/261 non-empty parents. Source SRT hash and mtime are
  unchanged. Focused editor/publication suites pass. Final unified regression
  passes 25/25 stages in 356.408 seconds and `git diff --check` passes;
  external and paid calls remain zero.

## 2026-08-09 Empty Intermediate Page Edit Recovery

- The current desktop package had advanced from 303 to 309 display pages after
  six manual page-structure overrides. Its saved intermediate edit journal
  contained 89 blank page-Chinese records while the imported old page SRT still
  provided 79 exact identity-matched drafts.
- Root cause was ownership priority in `_display_page_previews`: the presence
  of a blank edit record hid the recovered draft unless the parent translation
  had also changed. Exact recovered drafts now remain visible and unconfirmed;
  changed word spans remain blank.
- Unrelated structural edits now preserve stale/unconfirmed draft metadata so
  visible old Chinese cannot be silently promoted to authoritative Chinese.
- Read-only real-package replay reports 309 rows, 79 recovered drafts, and 10
  legitimate blank changed-span pages. Source SRT SHA-256 and mtime are
  unchanged. Manual-editor tests pass 44/44, stable-publication UI tests pass
  43/43, and unified regression passes 25/25 stages in 339.2 seconds.
  `git diff --check` passes. Network, ASR, LLM, synthesis, and paid requests are
  zero.

## 2026-08-09 Resumable Vocabulary Batch Cache

- Production evidence from `中国AI为何更省钱？` showed 199 cues and 160 semantic
  groups split into seven requests. The old 240-second budget left nine raw
  cards concentrated in the first half, then wrote that subset as an ordinary
  cache with no batch-completion evidence. Later renders therefore skipped all
  missing batches.
- Added vocabulary cache schema v2 with stable content-derived chunk IDs,
  timeline-balanced request order, per-chunk cards, completed IDs, and an exact
  `complete` invariant. Successful empty chunks are completed; failed or
  unattempted chunks remain resumable.
- Every completed chunk is atomically written to separate local/global progress
  caches. Existing prompt-v16 caches remain display fallbacks and are preserved
  while progress is partial. Formal cache replacement occurs only after all
  current chunks complete.
- Seven focused tests pass for partial survival, resume-only-missing behavior,
  empty completion, balanced order, legacy fallback, empty legacy regeneration,
  and atomic replacement failure. Offline replay on the real 199-cue subtitle
  preserved the legacy cache at 3/7, requested only four chunks on pass two, and
  completed 7/7 with the same eight-card scheduled result.
- The 1920x1080 sample at
  `tests/caption_audit/out/vocab-cache-recovery-sample.png` was opened and
  reviewed: the real article cover, full card, English highlight, and Chinese
  subtitle render without clipping or overlap. Replay evidence is stored in
  `tests/caption_audit/out/vocab-cache-recovery-replay.json`.
- Unified regression passes all 25 stages with exit code `0` in 368.3 seconds.
  Existing log-rotation file-lock warnings did not fail tests. No network, ASR,
  LLM, FFmpeg, synthesis, or paid request ran.

## 2026-08-09 Manual Page Chinese Completion

- Replayed the current 309-page desktop manual package. The remaining ten blank
  pages belonged to five re-paged parents whose complete parent Chinese still
  existed, while no page-level Chinese matched the new word ranges.
- Added a strict local proposal path for manual overrides. It allocates current
  parent Chinese in English page-word proportions only at existing safe Chinese
  token boundaries. The proposal is visible and hash-persistable as an
  unconfirmed draft, but cannot become authoritative or pass publication until
  explicitly edited or confirmed.
- Preserved the source priority of confirmed manual Chinese and exact recovered
  drafts. A local proposal outranks stale artifact text, and failure to find a
  safe split remains blank and blocked rather than cutting a Chinese word.
- Fixed repeated `N pages -> N pages` requests so identical page identities are
  a no-op. Confirmed page Chinese, history, and boundary overrides remain
  unchanged; true page-count or word-range changes still invalidate page
  Chinese for review.
- Real read-only replay reports 309/309 rows with Chinese: 220 authoritative,
  79 recovered identity drafts, and 10 local proposals. The five affected
  parent groups all concatenate exactly to current parent Chinese. Source SRT
  SHA-256, length, and mtime did not change.
- Manual-editor tests pass 45/45, stable-publication/UI tests pass 43/43, and
  unified regression passes 25/25 stages in about 345 seconds. `git diff
  --check` passes. No external, ASR, LLM, FFmpeg, synthesis, or paid request ran.

## 2026-08-09 Manual Editor Command Surface Audit

- Separated the ordinary subtitle-processing command set from manual-final
  editing. A loaded stable manual session hides generic save, layout,
  translation, language, compatibility, prompt, settings, and start controls;
  importing a plain subtitle restores them.
- Kept the complete manual workflow: review navigation, parent/actual-page
  switching and refresh, manual-final save, undo, formal/draft synthesis, file
  import, and current-package folder access.
- Removed an unreachable legacy boundary panel, duplicate toolbar and
  right-click boundary actions, the never-exposed quality-report action, and
  the disabled single-row merge item. Inline highlighted boundary controls are
  now the sole word-move interaction.
- Direct SRT imports can open the current manual package folder without a task
  object. Stable-publication/UI tests pass 46/46, manual-final editor tests pass
  45/45, video-synthesis safety passes, and unified regression completes all
  25/25 stages with no failed-stage summary. `git diff --check` passes. A
  standalone hidden-widget probe timed out and is not claimed as visual proof.
  No network, ASR, LLM, FFmpeg, synthesis, or paid request ran.

## 2026-08-09 Vocabulary Timeline Distribution And Recovery Merge

- Changed the duration target from 1.25 to 1.0 cards per minute. The 912.8-second
  `中国AI为何更省钱？` production subtitle now targets 15 cards. Selection quality
  is unchanged: priority 1-2 candidates, basic-only phrases, duplicates, frozen
  group mismatches, and candidates inside the 15-second interval remain blocked.
- Replaced opening-biased global priority truncation with time-stratified local
  scheduling. Each occupied time stratum contributes its strongest valid
  candidate first; empty strata stay empty, and remaining capacity is filled by
  priority plus distance from already selected cards.
- Fixed recovery display ownership. A legacy cache and completed v2 batches are
  now combined as candidates and passed through the same scheduler. The previous
  `legacy_plan or partial_plan` path hid later recovered cards until every batch
  completed, allowing an early legacy card to remain through the whole tail.
- Real offline inspection found nine legacy candidates, eight scheduled cards,
  and the last legacy card at 409.5 seconds, leaving a 503.6-second tail hold.
  The report is
  `tests/caption_audit/out/vocab-card-schedule-report-20260809.json`; the
  re-rendered 1920x1080 production frame is
  `tests/caption_audit/out/vocab-card-schedule-sample-20260809.png` and was
  visually checked for crop, overlap, and highlighting. The labeled target and
  legacy timing comparison is
  `tests/caption_audit/out/vocab-card-timeline-comparison-20260809.png`.
- Syntax compilation and seven focused vocabulary tests pass. Two unified
  regression attempts both passed the vocabulary smoke stage but failed in
  unrelated dirty-worktree stages: `stable subtitle publication` passed 46/46
  immediately in isolation; `video synthesis publication safety` then failed in
  isolation because its `SimpleNamespace` fixture lacks
  `_set_manual_editor_mode`. No external model, ASR, FFmpeg, synthesis, or paid
  request ran.

## 2026-08-09 Existing-Page Expansion With Manual Review Boundaries

- Reproduced desktop rows 224 (`S0196.P01`) and 251 (`S0216.P02`). Both parents
  already contained two pages, so the former `split into 2 pages` action was a
  no-op while the UI still reported success. The menu now offers one or two
  additional pages relative to the current parent count and handles
  `changed=False` without mutating editor or synthesis state.
- The remaining `manual_page_boundary_is_hard` failure came from a contract
  mismatch: manual planning used `allow_review_boundary=True`, but the frozen
  plan rebuild did not receive `allow_manual_review=True`. The rebuild now
  receives that explicit manual authorization; automatic planning and all hard
  word-range, timing, layout, and fixed-parent invariants remain unchanged.
- Added a session-level regression that failed on the old call and passes after
  the fix. It verifies complete non-overlapping word coverage and unchanged
  frozen parent fields. The manual-editor script, 49 stable-publication/UI
  tests, video-synthesis safety, the unified 25-stage regression, and
  `git diff --check` pass.
- Read-only in-memory replay expands both real parents from two to three pages,
  changes 309 rows to 310, and leaves the other 307 rows, full word ledger, and
  package files unchanged. External requests, ASR, LLM, FFmpeg, synthesis, and
  paid requests are zero.

## 2026-08-09 Manual Review Acknowledgement And Frozen-Plan Reuse

- Added identity-bound acknowledgement for actual-page Chinese and REVIEW
  boundaries. Non-empty Chinese edits and explicit boundary moves acknowledge
  the resulting page automatically; current-item and bulk non-blocking actions
  cover unchanged content. HARD errors remain non-overridable.
- Fixed a state-ownership defect where a translation-blocked three-page manual
  checkpoint discarded its frozen plan and fell back to a new four-page
  automatic plan. Strict checkpoints now reuse their hash-bound PASS, REVIEW,
  or translation-blocked render plan.
- Save results now return the manual draft path and SHA-256 that are written to
  the manifest and override, preventing callers from treating a boolean as the
  complete draft contract.
- Six focused confirmation/recovery tests pass. The manual editor passes 50/50,
  stable publication passes 51/51, synthesis safety passes, and the unified
  regression passes all 25/25 stages (653 test items) in 403.562 seconds.
  `git diff --check` passes.
- Isolated replay of the current desktop package confirms 79 Chinese and 20
  REVIEW boundaries to 0/0/0, publishes formally, and preserves all 261 fixed
  cue identities/times plus the 2,862-word ledger. Evidence is stored at
  `E:\VideoCaptioner-e2e-runs\manual-review-confirmation-postcheck-20260809`.
  Desktop source-package and audio hashes are unchanged. Network, ASR, LLM,
  and real video synthesis calls are zero.

## 2026-08-09 Manual File Menu And Format Export

- The manual-final file menu no longer relies on action visibility for
  `兼容字幕校正` and `文稿提示`. The installed `RoundMenu` keeps hidden actions
  in its custom list, so manual mode now removes them and ordinary mode restores
  them before settings without duplicate entries.
- Restored the existing format-export dropdown in manual-final mode under the
  explicit `导出字幕` label. TXT export remains available and preserves the
  selected bilingual layout; no subtitle, page, timing, manifest, or synthesis
  contract changed.
- Focused tests pass 3/3, stable publication passes 51/51, the unified
  regression passes 25/25 stages (about 653 items) in 343.325 seconds, and
  `git diff --check` passes. No external request or media pipeline ran. An
  offscreen menu capture crashed before creating an image, so production GUI
  visual confirmation remains the next action.

## 2026-08-09 Interactive Review Gate And Organized Media Outputs

- Added a dedicated interactive review contract to `SubtitleTask`. Home-created
  full-process subtitle tasks set it, and `SubtitleInterface` no longer emits
  the automatic synthesis signal for those tasks after subtitle completion.
  Batch tasks keep the default automatic chain.
- Added one shared media result-directory helper. Stable subtitle exports,
  actual-page files, QA queue, summary, compatibility SRT, manual-final package,
  and formal/draft videos now use
  `<output-anchor-parent>/<source-media-stem>-处理结果/`. Normal Home output is
  beside the audio; isolated E2E report anchors remain isolated. No source or
  legacy loose file is moved or deleted.
- Task-context tests pass 5/5, stable-publication/UI tests pass 53/53, the
  manual-final editor and video-synthesis safety scripts pass, and the final
  unified regression passes 25/25 stages in 330.3 seconds. Two earlier unified
  runs identified stale path expectations and were corrected before the final
  pass. External requests, ASR, LLM, real synthesis, and paid requests are zero.

## 2026-08-09 Complete Vocabulary Plan Render Gate

- Production `5/9` evidence exposed the remaining ownership defect: v2 progress
  tracked incomplete chunks correctly, but the loader still returned a partial
  display plan and allowed FFmpeg to encode a formal video.
- Removed the 240-second global early-stop budget. Current chunks run
  sequentially with the existing 90-second per-attempt timeout and two explicit
  attempts. Successful empty arrays are complete batches; no quality threshold
  or vocabulary selection rule changed.
- Added `VocabularyPlanIncompleteError`. Failed chunks and missing model
  configuration retain all completed progress and fail synthesis before FFmpeg.
  A retry merges local/global progress, requests only unfinished chunk IDs, and
  returns a plan only when the complete invariant is true. Legacy caches are no
  longer a rendering authority during recovery.
- Syntax compilation and all 29 focused vocabulary/cache/display tests pass,
  including a direct assertion that `subprocess.Popen` is never called for an
  incomplete plan. The unified
  regression ran 365.6 seconds and passed all stages except `stable caption
  smoke tests`; its only failure was the unrelated order-dependent
  `test_whisperx_time_only_uses_explicit_source_audio_from_complete_task`, which
  passed in isolation.
- The fresh 1920x1080 real-data frame
  `tests/caption_audit/out/vocab-complete-gate-sample-20260809.png` was opened and
  checked for clipping, overlap, empty regions, highlight placement, and
  bilingual subtitle layout. External model, ASR, FFmpeg, synthesis, and paid
  requests are zero.

## 2026-08-09 English-Only Podcast Template Output

- Added the user-selected manual toggle workflow to the synthesis command bar:
  unchecked renders bilingual subtitles; checked renders English subtitles
  only. The action appears only with the English learning template and persists
  through the existing configuration system.
- Froze the value into `SynthesisConfig` and passed it explicitly through the
  synthesis thread to both static podcast renderers. Rendering omits only the
  bottom Chinese subtitle; English positioning, article pagination, vocabulary
  selection, card timing, and card Chinese content are unchanged.
- Added separate `-英文字幕版` output prefixes for article-word, dark-podcast,
  and manual-draft output, so the second run cannot overwrite the bilingual
  file. One-click dual output remains intentionally out of scope.
- Added regressions for default bilingual behavior, frozen task propagation,
  both output-name families, the UI handler, and pixel equality above the
  Chinese subtitle region in both templates. Syntax checks and focused scripts
  pass; the unified regression passes 25/25 stages in 362.9 seconds.
- Opened and checked the two 1920x1080 English-only template samples plus the
  1400x850 synthesis-page screenshot in `tests/caption_audit/out/`. No real
  encoded pair, ASR, external model, or paid request ran.

## 2026-08-09 Cached Article Evidence Handoff

- A fresh production run still retained `Higee` although article analysis was
  enabled. Its run state proved article correction ran without resume, while
  the saved context proved `haigui` and its source sentences were available.
- The in-memory analysis object lacked the evidence fields that
  `save_article_artifacts()` added only to its output copy. ASR correction and
  translation prompting therefore did not consume the same context shown in
  `article_context.json`.
- `SubtitleThread._resolve_article_context()` now enriches the context before
  save and downstream use. Existing cache entries remain reusable, and ASR
  replacement thresholds, stable English boundaries, word times, fixed IDs,
  Chinese allocation, and rendering are unchanged.
- A cross-stage cached-context regression covers both a person name and a
  domain term: `Li Yang Wenfing -> Liang Wenfeng` and `Higee -> haigui`, with
  preserved time envelopes and the expected Chinese glossary names. Task
  context passes 6/6, article correction passes 29/29, and the unified
  regression passes all 25 stages in 362.3 seconds. External requests are zero.

## 2026-08-09 Entity-Span Guard And Recoverable Page Failure

- The 19:54 production failure was isolated to one
  `page_translation_chinese_token_split` at `S0001.P02`. Deterministic planning
  had already produced 262 parent plans and 303 actual pages, but the validator
  discarded those plans when it returned `ERROR`.
- Page-validation errors now retain the full frozen render-plan list and all
  independently valid translated parents. The manual editor shows the failed
  parent's actual English pages with blank, unconfirmed Chinese and the exact
  validation issue. Formal publication and synthesis remain fail-closed.
- Fuzzy article correction now detects a complete canonical entity inside or
  adjacent to a non-expanding candidate window. It rejects the consuming
  candidate, preserving `Like,` and `President`, while existing phonetic and
  spelling corrections remain eligible.
- Read-only real-checkpoint replay produced 303/303 visible page rows, with all
  three `S0001` pages marked for review. Cached article replay retained both
  protected phrases and corrected all three `Higee/Higgies` forms to `haigui`.
  Focused article, page-contract, manual-editor, and syntax checks pass. The
  unified regression completes all 25 stages in 342.9 seconds and `git diff
  --check` exits zero. No network, ASR, LLM, FFmpeg, video synthesis, or
  production artifact write ran.

## 2026-08-09 Local Manual Page State Ownership Repair

- Reproduced the `S0079/S0080` failure from the saved manual package: moving a
  word across formal parents caused the editor to clear all page edits and
  overrides, fall back to parent rows, and lose unrelated visible Chinese.
- Moved invalidation ownership into `ManualFinalSubtitleSession`. A formal
  boundary edit now snapshots the complete actual-page table, derives local
  ranges for only the two changed parents, stores explicit one-page overrides
  where needed, and preserves all unaffected page identities and translations.
- Changed affected page Chinese to visible, unconfirmed drafts. Save continues
  to return `manual_page_translation_required` until those drafts are confirmed;
  the draft page artifact remains available for preview.
- Added exact history recovery for already-damaged packages. It recovers only
  blank current pages with matching page ID, parent ID, frozen word range, and
  English. Current production-package replay recovered 77/77 blank pages and
  left zero blanks or unavailable rows without writing the package.
- Replaced visual row numbers with stable parent/page IDs in the table header.
  Focused tests, 54 stable-publication/UI tests, the complete manual-editor
  script, and the 25-stage unified regression pass. Final unified duration is
  359.2 seconds; external requests and production writes are zero.

## 2026-08-10 Actual-Page Merge And Local Undo Interaction

- Added `merge_display_page_with_next()` as a visual-only operation. It removes
  one internal page boundary while preserving the fixed parent subtitle, word
  ledger, English, and timeline. Cross-parent selections continue through the
  formal adjacent-parent merge path.
- Formal parent merging now remaps only selected page rows and locally rebuilds
  the retained parent. A failed local rebuild rolls back cue state, page edits,
  page overrides, and history instead of leaving a half-merged session.
- Removed the visible global undo entry. The row inspector enables undo only
  when the current parent owns the newest history entry; arbitrary out-of-order
  row rollback is rejected. Selection after editing is restored by stable page,
  parent, and word identity rather than the previous table index.
- Focused session tests pass 3/3, focused UI tests pass 6/6,
  `tests.test_stable_publication` passes 57/57, the manual-editor script passes,
  and the unified regression completes 25/25 stages in 353.4 seconds.
- Read-only production-package replay loads 303 actual pages. Merging
  `S0001.P01` changes only that parent's pages, keeps 300 unrelated pages and
  the complete parent/ledger state byte-for-byte equivalent in memory, and undo
  restores all 303 pages. No package write, external request, ASR, LLM,
  synthesis, or paid request occurred.

## 2026-08-10 Actual-Page Tail Deletion And Media Lookup

- Added actual-page menu entries for tail-cut preview and deletion. The session
  maps the selected page ID to its first frozen word ID; a cut inside one parent
  retains earlier pages and truncates only that parent's suffix before removing
  all later cues.
- Added exact inverse lookup for the organized result-directory contract. A
  subtitle under `<stem>-处理结果/` may recover one same-stem supported media
  sibling from the outer directory when the manifest media path is absent or
  stale. Ambiguous candidates fail closed.
- Manual-final save continues to create a non-destructive derived M4A, records
  its path and SHA-256, and makes synthesis override a stale original-media UI
  selection with that derived file.
- Manual-editor tests pass, stable-publication/UI passes 57/57, and the unified
  regression passes 25/25 stages in 459.5 seconds. A read-only 303-page replay
  trims `S0254.P02` at 969.689 seconds, keeps its first page, restores exactly on
  undo, and changes zero of nine package files. External and paid requests are
  zero.

## 2026-08-10 Manual Import Semantics And Per-Page Font Recalculation

- Reproduced the damaged manual package without modifying it. Its history kept
  21 edits, but one failed formal-boundary move reduced 310 page rows and seven
  boundary overrides to zero; the old save also made the discoverable original
  parent SRT byte-identical to the manual-final SRT.
- Manual imports now have one meaning each: manual-final continues, original-top
  restarts from the stable checkpoint, and actual-page remains a snapshot that
  resolves to the latest matching manual package. Save preserves the immutable
  original parent and original actual-page exports.
- Formal-boundary reflow is transactional. Any local rebuild failure restores
  cues, pages, overrides, and history; publication detects and blocks a silent
  collapse of previously recorded manual page state.
- `article-fixed-font-pages-v17` selects 56/54/52/50px independently for every
  final page after automatic or manual page spans are frozen. The parent font is
  the minimum page size only as a summary. The focused fixture changes a
  two-page result from 52/52 to 52/56 without changing text, IDs, word spans,
  page boundaries, or timing.
- Read-only real-package replay checked 262 parents and 303 pages. Six pages
  increase in size, none decrease, and all nine package files remain
  SHA-256-identical. The unified regression passes all 25 stages in 374.5
  seconds; `git diff --check` exits zero. External and paid requests are zero.

## 2026-08-10 High-Pressure Single-Page Secondary Review

- Audited all 17 remaining high-pressure single pages in the current
  study-abroad manual package: mean 16.06 words, median 16, range 12-22.
- Added a bounded secondary review for pages over 16 words or at 52/50px. A
  promoted plan must keep at least six words and 900ms per page, fit at 56px,
  and use a complete-clause or 500ms-pause boundary. Lexically incomplete
  boundaries remain rejected.
- Offline 262-parent replay changes page boundaries only for `S0044`, `S0076`,
  and `S0257`. It continues to reject `going | abroad`, `drastically | higher`,
  and the unbalanced `S0167` candidate. Parent ID, English, Chinese, word-range,
  and page-coverage checks report zero mismatches.
- Added article-person context support for low-similarity titled names. Real
  replay corrects two `Ms. Howe` spans to `Ms Hao`, preserves all three
  `haigui` spans, and retains complete coverage of the 2860-word ledger.
- Added `article-asr-correction-v2` to interrupted-run stage details. Old
  correction output is recalculated while the article context and raw ASR stay
  reusable.
- Focused article-context tests pass 33/33, the article display contract passes,
  and the unified regression passes all 25 stages in 375.0 seconds. External
  requests and production writes are zero.

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

## 2026-08-10 Faster-Whisper Shutdown-Crash Recovery

- A fresh `如何停止拖延.m4a` run failed twice after Faster-Whisper r245.2
  reached 100%, wrote its SRT, and printed `Operation finished in:`. Windows
  Error Reporting identified `faster-whisper-xxl.exe`, `ucrtbase.dll`, and
  exception `0xC0000409`; older reports prove the executable had the same
  shutdown failure before the current code.
- The strict exit check introduced in `6bb5ba8` exposed the latent failure but
  discarded a completed transcript before shared ASR validation. The wrapper
  now accepts a nonzero exit only when both completion markers are present and
  the generated SRT passes the existing `BaseASR` validation contract.
- Regression coverage proves that a fully completed valid SRT is recovered,
  while progress-only completion, a missing operation-finished marker, and an
  invalid SRT all remain failures. No exit-code allowlist or synthetic timing
  fallback was added.
- Real local replay reproduced return code `3221226505` and successfully
  returned 3135 native word-timestamp segments with trusted timing. ASR trust
  tests pass 19/19, and the full 25-stage regression exits zero in 360.1
  seconds. Network, LLM, translation, WhisperX, synthesis, paid requests, and
  production cache writes were zero.

## 2026-08-10 Silent Tail Duplicate And Reading-Speed Gate

- Traced the later task failure past successful translation, WhisperX, final
  timeline validation, and display-page translation. The visible blocker was
  one `reading_speed_error`, but its timing pressure came from a 14-word
  Faster-Whisper tail duplicate compressed into 260ms of audio silence.
- Added a pre-freeze, Faster-Whisper-only tail guard. It requires extreme word
  rate, overlapping word times, a long repeated phrase, sentence-final
  position, and FFmpeg-confirmed silence. Ambiguous, audible, or non-repeated
  endings are retained.
- Real read-only replay changes 3,135 word entries to 3,121 and removes only
  `We're looking at a daily environment that requires less raw willpower to
  begin with.` The preceding legitimate sentence remains intact.
- Unified stable publication decisions around per-error review tiers. A
  top-level error classified as `REVIEW` no longer becomes render-blocking just
  because the legacy status string is `ERROR`; unknown and structural errors
  remain fail-closed. Unrelated allocation-review blockers do not change the
  existing production gate.
- ASR trust tests pass 22/22, four focused release-gate checks pass, real SRT
  plus audio replay selects the expected 14-word suffix, and the full 25-stage
  regression exits zero in 406.2 seconds. No LLM, translation, WhisperX,
  synthesis, paid request, or production artifact write ran during validation.

## 2026-08-10 Manual Checkpoint Actual-Page Recovery

- Diagnosed the post-save parent-view fallback from the real `如何停止拖延`
  package. The 21:30:31 edit artifact still owns 283 cues, 92 history entries,
  353 page edits, 38 overrides, and tail trim; only the derived page artifact
  lost its render-plan list.
- Added a fail-closed recovery path that rebuilds an editor preview from exact
  saved page word ranges only after page IDs, parent IDs, English, continuous
  ledger coverage, boundary evidence, and cue coverage all match. It does not
  change frozen English, IDs, word timing, page boundaries, or confirmation
  state.
- Real read-only replay restores 353/353 page rows and all 19 visible stale
  Chinese drafts with zero blank rows. Formal synthesis stays blocked by
  `manual_page_translation_required`.
- Added a regression that deletes the derived page plan from a blocked package,
  reloads from the complete edits, saves again, and proves exact page identity
  survives. The full manual-editor script, syntax compilation, and 58 UI and
  publication tests pass. The required 25-stage regression passes in 361
  seconds. No external request or production write ran.

## 2026-08-10 Manual Editor State And Latency Hardening

- Audited split, visual-boundary move, save, reload, and page/parent view
  transitions against the real 353-page procrastination package. Repeated full
  derivation of 38 overridden plans, GUI-thread session copying, destructive
  boundary-Chinese invalidation, and reload-failure parent fallback were the
  four root causes.
- Added state- and artifact-bound complete-model caching plus parent-level
  preview reuse. The cache fails closed on any cue, edit, override, recovered
  evidence/draft, manifest, page artifact, draft artifact, or boundary-evidence
  file change, and callers receive isolated row copies.
- A page-boundary move preserves existing Chinese visibly as an unconfirmed
  draft on only the two changed pages and leaves every unaffected page exact.
  Save snapshot copying now runs after the table is disabled and inside the
  worker; mutation during save is rejected.
- A save/reload verification failure keeps the current in-memory session and
  actual-page view instead of forcing parent rows. It clears synthesis authority
  and asks for another save without requiring import or audio rerun.
- Real read-only timings: cached full model 0.012-0.014s, split 0.159s plus
  0.122s refresh, boundary move 0.136s plus 0.129s refresh; 351 unaffected pages
  have zero identity/text/timing drift. A cross-parent formal-boundary move took
  0.940s plus 0.143s refresh with zero drift across 349 unaffected pages.
  Manual editor, 60 UI/publication tests, syntax compilation, `git diff --check`,
  and all 25 regression stages pass; the final unified run took 381.4 seconds.

## 2026-08-11 Missing Speech And Compressed Word-Timing Repair

- Reproduced the 08:51 omission as a Faster-Whisper history-context failure:
  the normal full-file pass jumped from `Wow.` to `You are borrowing...`, while
  a bounded context-free pass recovered 23 spoken words in the acoustic gap.
- Added a pre-freeze local repair that requires a long internal word gap,
  FFmpeg activity, and exact text anchors on both sides. It never gives the
  local model authority over existing words. Unanchored output is logged only;
  anchored inserted words retain acoustic times and the repaired SRT replaces
  the raw ASR cache value.
- Traced subtitle 281 to stable-ts: six words shared 1077.980-1078.100, and its
  eight-word cue covered only 741ms. Stable-ts now reverts a compressed local
  update to trusted native Faster-Whisper times; WhisperX reverts the same
  defect to the frozen ledger. A bad baseline cannot be used as fallback.
- Added one shared detector at the actual timing owner. The fixed thresholds
  are four words in at most 250ms, or eight words in at most 750ms at ten or
  more words per second. Historical audit of 99 ledgers found no plausible
  normal-speed false positive, but exposed a 40-word chain caused by merging
  overlapping windows. The detector now returns a minimum core and callers
  repair and detect again, preventing broad timing rollback.
- Final verification: ASR trust 33/33, final cue timeline pass, complete stable
  caption rules pass, Python compilation pass, and all 25 unified regression
  stages pass in 362.2 seconds. No translation, display-page, renderer, source
  audio, or production artifact was changed during these tests.

## 2026-08-11 Manual Numeric Boundary Comma Fix

- Reproduced the manual boundary false positive where moving `the` from
  `In the 12 months prior to early 2026, the` caused the numeric fallback to
  absorb `2026,` as well.
- The manual expansion guard now recognizes trailing comma, semicolon, and
  colon as completed clause boundaries. True numeric units and magnitudes
  remain atomic, while a following article can move independently.
- Added a regression for `2026, / the` and retained the existing `740 billion`
  bidirectional protection test. The manual-editor script and the complete
  25-stage unified regression pass.
