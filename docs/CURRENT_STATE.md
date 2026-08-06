# Current State

Last updated: 2026-08-06

## 2026-08-06 Fixed-ID Display-Page Translation Contract

- Root cause: the renderer could split one frozen English cue into timed pages
  only after parent-level Chinese allocation had finished, then divided the
  reordered Chinese string by English word proportions. The parent cue was
  valid while individual pages could show meaning from a later or earlier
  English span.
- Multipage spans now receive deterministic IDs such as `S0078.P01` after the
  final WhisperX word timeline is frozen. The LLM maps concise Chinese to each
  exact page ID; validation aggregates the pages back to the unchanged parent
  cue. English text, parent IDs, word spans, cue times, word timestamps, SRT,
  and ASS ownership remain frozen.
- Cache identity includes the English/page text, word spans, display timing,
  layout profile, translation/model/prompt versions, and context hash. Artifact
  writes are atomic and fail closed. The stable manifest binds the page
  artifact by SHA-256 and contract hash; missing or tampered data blocks before
  ffmpeg. The renderer has no proportional-Chinese fallback.
- Generic display-boundary scoring additionally protects tightly spoken
  non-finite complements and numeric compound heads. A real 400ms pause may
  still remain eligible, so the change does not globally merge all such
  phrases.
- Real-audio E2E output is under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r1`.
  It retained the frozen 262-ID English signature, produced 46 multipage
  parents / 94 display pages, passed the final timeline with
  `whisperx-time-only`, had no overall fallback or `source_audio_missing`, and
  covered 64.8-66.5s through `S0017`.
- Synthesis produced `final-video.mp4` (46,217,829 bytes, 1003.66s,
  1920x1080 H.264/AAC). Production `ffmpeg.exe` decoded the complete video with
  zero errors; `ffprobe.exe` was unavailable and was not claimed as run.
- Visual validation sampled 22/22 planned frames across `S0062`, `S0078`,
  `S0111`, `S0252`, every associated page transition at +/-80ms, and
  64.8/65.6/66.4s. Page English/Chinese matched the artifact, the speech
  interval retained `S0017`, minimum English/Chinese separation was 80px, and
  no sampled frame showed shrinking, clipping, overlap, blanking, or a reversed
  page. This is targeted transition evidence, not a claim of manual review of
  every frame in the full video.
- External request accounting across four subtitle attempts is 11. The final
  successful attempt used one page request; synthesis used zero. No credential
  value is present in the reports.
- Unified regression 17/17 and `git diff --check` passed after final documentation.
  Unseen-audio confidence remains unproven until a separate blind input passes;
  manual-final multipage Chinese overrides do not yet have a page-aware editor.

## 2026-08-06 Stable Boundary and Display Planner Follow-up

- A renderer-only line wrap incorrectly treated every preposition at the next
  line start as a hard error. This rejected the valid static layout
  `through reinforcement learning` / `from human feedback.`.
- The break scorer now distinguishes a complete prepositional or infinitive
  phrase at the next line/page start (soft preference penalty) from a stranded
  lexical dependency (hard penalty). High-confidence pairs such as
  `according | to`, `completely | out`, and `far more | than` remain
  blocked.
- English boundary protection now also covers parser-confirmed zero-relative
  clause entrances and post-noun participial modifiers before ID freezing.
- Visual page span selection is delegated to the deterministic
  `stable_display_planner` dynamic program. It only chooses word spans inside
  an existing cue and preserves cue IDs, English text, Chinese allocation, and
  cue timing.
- Focused English-boundary tests, stable-caption tests, the unified regression,
  and `git diff --check` pass.

## 2026-08-06 Real-Audio E2E Verification

- Cache-first E2E used the read-only source audio
  `C:\Users\19379\Desktop\中国AI为何更省钱？\中国AI为何更省钱？.m4a` and wrote all
  outputs under `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-followup`.
- Subtitle processing passed with 266 fixed IDs and 2,897 ledger words.
  `final-cue-timeline.json` is `PASS`, `alignment.applied_backend` is
  `whisperx-time-only`, `fallback_used` is false, and no `source_audio_missing`
  occurred. English text and Chinese ID mappings stayed complete and aligned.
- The 64.8-66.5s speech check is covered by `S0017` through 67.975s. WhisperX
  retained stable-ledger timing locally for eight unmatched words; this was not
  an overall backend fallback.
- External LLM requests: 0. All translation/allocation entries were cache hits;
  the run disabled vocabulary-card generation.
- Video synthesis was stopped before ffmpeg by the fixed-font structural gate
  for `S0052`, `S0176`, `S0196`, and `S0258`:
  `render_structural_overflow / no_fixed_font_page_partition`. No
  `final-video.mp4` or `e2e-summary.json` was produced for this run. The gate
  remains an unresolved renderer risk and was not bypassed by changing text,
  IDs, timing, font size, or visual pagination rules.

## Working

- E-drive working copy is the active project.
- Stable mode uses local English segmentation from word-level timestamps.
- Stable English boundaries are finalized by the language-cutting phase before
  global subtitle IDs are assigned. Video templates may wrap or scale the
  frozen text, but cannot create or move English subtitle boundaries.
- Stable mode now forces word-level timestamp preparation even when the old
  subtitle splitting compatibility switch is off. It fails explicitly rather
  than silently falling back to the legacy LLM editing route.
- Timeline alignment now supports selectable backends: `stable-ts` (default), experimental `whisperx`, and `whisperx-time-only`.
- WhisperX runs through the isolated `whisperx-runtime` environment and falls back to stable-ts/original timing if unavailable.
- `whisperx-time-only` keeps local stable English cutting, aligns pre-cut ASR
  phrases with WhisperX, maps only frozen ledger words, then derives final cue
  times from the fixed cue word spans.
- If WhisperX time-only is unavailable, returns an incomplete ledger, or raises
  during alignment, the same frozen cue spans are rebuilt from stable-ts word
  times. The final manifest and `final-cue-timeline.json` record the requested
  backend, applied `stable-ts-fallback` backend, and fallback reason.
- Stable screen subtitles request native ASR word timestamps at task creation
  independently of the legacy coarse-splitting switch.
- LLM translation is limited to Chinese generation/allocation.
- A missing, duplicate, or unknown Chinese subtitle ID is a structural failure.
  Stable mode does not use a free single-line fallback that could hide the
  error or cause positional drift.
- Podcast template can resolve subtitles from `stable-final-manifest.json`.
- Article-template smart vocabulary cards are selected per local English semantic
  group, then globally filtered by model-provided learning priority. The target
  density is about 1.25 cards per minute, capped at 22; low-priority candidates
  and duplicate words are not rendered. A card starts with the subtitle that
  contains its word, not at the start of the earlier semantic group.
- Smart vocabulary cards preserve the selected expression exactly as it appears
  in its triggering subtitle. The regular card shows only that expression and
  one compact Chinese contextual gloss. A concept card may add one short
  Chinese explanation for a non-transparent technical, cultural, or economic
  concept; the plan caps such expanded cards at three per episode.
- Vocabulary cards omit phonetics, part-of-speech labels, exam labels, English
  dictionary definitions, and `IN CONTEXT` blocks. A new card uses the full
  learning panel for eight seconds, then becomes a compact expression-and-gloss
  review state until a newer card replaces it. The last review state remains in
  place for the rest of the rendered video.
- Before the first vocabulary card, the article template keeps the right panel
  occupied with the episode title rather than a vocabulary preview. It requires
  no vocabulary-model output and fades out before the first card fades in over
  0.25 seconds. The container remains in place; later cards do not use this
  transition.
- When a vocabulary expression is highlighted in an English subtitle, directly
  attached punctuation and closing quotation marks or brackets use the same
  highlight color; following whitespace and text remain unhighlighted.
- Regression smoke tests exist in `tests/test_stable_caption_rules.py`.
- Generated subtitle audits exist in `tests/audit_stable_outputs.py`.
- A single regression entry exists: `runtime\python.exe scripts\run_regression.py`.
- Stable runs now write a concise, time-addressable `字幕质检队列.srt` beside the
  source audio. It is built from the current coverage report's sibling artifact
  directory, contains only `BLOCKER` and capped `REVIEW` items, and preserves
  the affected final subtitle timings. Semantic audit items whose
  `mapping_valid` is false are retained as `INFO`, not added to the human queue.
- Stable subtitle processing writes `run-state.json` to the subtitle output
  directory. It records the input/configuration fingerprint, stage status,
  verified artifact digests, actual cache/batch/retry progress, elapsed time,
  and bounded ETA. The existing bottom status label presents this live state.
- An interrupted task may reuse only a verified article context and corrected
  ASR artifact when the subtitle input, article state, model/prompt,
  allocation settings, and alignment backend match. Full translation and
  allocation remain ID-bound cache-backed work; English boundaries, frozen
  IDs, timings, and export are never rehydrated from partial memory state.
- Allocation now uses global subtitle IDs (`S0001`, `S0002`, ...), not positional lists, for Chinese writeback.
- Allocation artifacts record inputs, raw returns, validation, retry logs, final mappings, unresolved groups, and structure errors.
- `allocation-final.json` is reconstructed from the final fixed-ID subtitle
  writeback at export time. It includes every semantic group's current
  `subtitle_id -> Chinese` mapping even when a quality retry remains unresolved;
  `allocation-unresolved.json` retains the failure provenance separately.
- Completed stable runs now record a `run_comparison` manifest section containing
  the task's actual article-reference state, article/context/glossary hashes,
  correction execution state, and allocation-relevant runtime configuration.
  It is written from the active task, not inferred from files left by an older
  run.
- `scripts\\compare_frozen_mainline_runs.py` can compare two completed runs
  before an allocation-only A/B claim. It accepts Chinese-by-ID differences
  only; raw/corrected ASR, word ledger, English boundaries, final ID/timing,
  semantic groups, authoritative full translations, article state, and runtime
  configuration must otherwise match exactly.
- The subtitle table can now enter a local manual-final-edit mode when an
  imported bilingual SRT resolves to its stable artifacts. It supports only
  adjacent merges and word-ledger-backed transfers of a cue suffix/prefix to
  its neighbour. Text-only edits retain their times; boundary moves recompute
  the two affected cue times from frozen word timestamps. Saving writes
  `人工终稿字幕.srt` and an edit log beside the source subtitle, and synthesis
  prefers that explicit manual override without re-running generation.
- The GUI now presents the normal stable bilingual workflow first: optional
  article assistance is collapsed by default, production subtitle controls are
  separated from advanced performance and legacy compatibility controls, and
  the editor keeps compatibility correction, prompt, import, and folder actions
  under `More`. This changes no processing configuration or pipeline behavior.
- Generated-output auditing is on-demand and requires an explicit fresh
  `work-dir` sample; it is not part of the unified regression.

## In Progress

- Reducing coupling in `screen_editor.py`.
- Making final SRT/ASS output and video synthesis use the same stable subtitle.
- Converting discussion-derived rules into tests and docs.
- Verifying long-audio Chinese allocation drift with fresh generated outputs.

## Known Issues

- `screen_editor.py` remains highly coupled.
- Current tests are smoke/regression tests, not full fixture coverage.
- Existing generated outputs under `work-dir` may be stale unless regenerated after code changes.
- Runs produced before the `run_comparison` manifest schema cannot be used as
  strict allocation-only A/B baselines. The comparison tool reports
  `incomplete_artifacts` rather than guessing article-assist state from stale
  `article_*.json` files.
- A manual boundary move requires the matching `subtitle-spans.json` and
  `word-ledger.json`. An isolated SRT remains editable as text, but cannot
  safely gain automatic split timing from its text alone.
- Some ASR/stable-ts word timings can be too short or contain gaps.
- Full `whisperx` backend changes word timestamp alignment before stable cutting, so English boundaries and downstream Chinese can change.
- `whisperx-time-only` is the lower-risk WhisperX mode for samples where timing improves but existing cutting/translation should remain stable.
- When any timing backend is selected, English text, Chinese text, IDs, order,
  and word-ledger anchors are frozen before the final cue timeline is built.
  Every cue must cover its own first and final ledger word. A narrow display
  pass may only move a shared boundary in the space between adjacent word
  envelopes; it never changes cue content, word timestamps, or ownership.
- Stable-ts remains the display-timing authority for the default `stable-ts` backend. Its display padding runs once during finalization, not both before and after final alignment.
- Final display coverage is reconciled once after the chosen timing backend.
  It bridges only adjacent gaps of at most 800ms that lie inside a continuous
  source-word envelope and whose frozen word pause is at most 450ms.  Longer
  or uncertain gaps remain unchanged and are saved as WARNING evidence in
  `display-coverage-unresolved.json`.
- Chinese translation quality still depends on LLM output and prompt stability.
- Semantic full-translation prompting now defaults to Chinese punctuation rather
  than em dashes. Only a group with an em dash at its start/end or multiple
  em-dash runs receives one isolated style retry; that retry is accepted only
  when it lowers the local dash-style score without losing an already-present
  number, negation, or entity anchor. The result is recorded in
  `full-translation-style-retry-log.json`.
- Optional Chinese polish is restricted to fixed semantic groups. It may change
  Chinese only by existing subtitle ID and is rejected if structural validation
  finds an ID, entity, number, negation, or semantic regression.
- Audit and generator now share the same narrow complete-sentence overflow
  exception for Plus at 17 words, preventing a passing cue from being reported
  as an overlong ERROR.
- A word-timestamp pause of 450ms or more can relax an ordinary clause
  boundary, but it cannot legalise a hard grammar split such as a preposition
  separated from its object, an auxiliary separated from its predicate, or a
  number separated from its unit. This prevents aligned pauses around function
  words from producing visibly stranded English lines.
- Stable English cutting now uses deterministic local candidate selection rather
  than dynamic programming. The normal target is at most 16 English words;
  17-19 words are allowed only when every shorter candidate would cross a
  parser-confirmed grammar boundary. A forced 19-word cut remains auditable.
- A direct pre-ID merge may remove a high-confidence English fragment into one
  complete 17-19 word cue only after the shared structural-overflow check
  proves that no legal 16-word split exists. This exception is unavailable to
  visual splitting, general repartitioning, or any ID-assigned stage.
- The 12-word/68-character reading target normally remains renderer-only. A
  complete 13-16 word cue stays intact and is wrapped over up to two visual
  lines by the selected video template unless the pre-ID visual temporal pass
  finds a high-confidence, independently readable boundary with a real pause.
- spaCy-confirmed verb-object, verb-preposition complement, and
  subordinate-clause-introducer boundaries remain illegal even when a word
  timestamp contains a long pause. This protects display cuts such as a verb
  separated from `in ...` or a line ending in `how`/`because`.
- Chinese semantic allocation now receives advisory per-cue display budgets
  derived from the fixed cue duration. These budgets guide the LLM but do not
  authorise omission or change the frozen timing.
- Fixed-ID allocation now treats a terminal Chinese modifier without its head
  as a quality failure even when it has closing punctuation. Its existing
  one-group retry uses a fragment-specific prompt; it preserves the same IDs,
  English, word spans, order, timing, and retry count.
- Chinese reading speed remains a warning above `9.0` characters per second.
  The render-error boundary is now `12.25` characters per second, an explicit
  near-threshold tolerance for discrete CJK character counts; values above it
  remain validation errors.
- Chinese semantic auditing skips fragment heuristics for a fully punctuated
  single-cue group. It still audits semantic loss and all multi-cue allocation
  boundaries.
- Single-cue semantic groups write the authoritative full translation to their
  sole frozen ID. Allocation fragment rules apply only where a group has an
  actual cross-cue allocation boundary; one invalid group or failed allocation
  batch records its own unresolved evidence and cannot discard other groups'
  ID-bound Chinese mappings.
- A missing authoritative full translation now records the affected frozen IDs
  as a blocking structure error and unresolved allocation while preserving
  already completed fixed-ID mappings from other groups.
- Optional Chinese polish now includes a narrowly selected complex
  enumeration/comparison group class. It remains capped, writes only existing
  subtitle IDs, and never changes English, order, or timing.
- Chinese compression, same-group reallocation, and high-confidence repair
  accept only explicit global `subtitle_id` values. Legacy index-based cached
  replies are structural failures and cannot write Chinese into a cue.
- Post-allocation Chinese compression and same-group reallocation compare the
  original and candidate ID dictionaries before writeback. A candidate must
  reduce local reading pressure and remain non-regressive for semantic
  coverage, entities, numbers, negation, duplication, fragments, and adjacent
  Chinese naturalness; otherwise the original group is restored.
- Validation blocking is strongest for translation-structure errors; confirm any new ERROR class is wired to synthesis blocking before relying on it.
- Git has no `checkpoint-2026-07-23` tag or branch in this checkout.

## Current Production Recommendation

Use:

- Stable mode on.
- stable-ts/time alignment on when available.
- Keep `stable-ts` as the default alignment backend.
- Prefer `whisperx-time-only` when WhisperX timing is better but stable-ts cutting/translation should be preserved.
- Use full `whisperx` only as an experimental backend when boundary changes are acceptable.
- Candidate quality check off.
- Preserve backchannels.
- Use `stable-final-manifest.json` for podcast template synthesis.
- After code changes, regenerate subtitle outputs before judging a newly rendered video.

Avoid:

- LLM-based English segmentation in production stable flow.
- Broad edits to `screen_editor.py` without tests.
- Judging fixes from old rendered videos or stale subtitle files.

## Latest WhisperX Full-Flow Check

Sample:

- `C:\Users\19379\Desktop\外卖骑手诗人的走红，标志着中国农民工文学的兴起\外卖骑手诗人的走红，标志着中国农民工文学的兴起.m4a`

Result:

- FasterWhisper ASR plus WhisperX CUDA alignment completed.
- WhisperX mapping: `source=2616`, `aligned=2616`, `matched=2616`, `zeroish=0`, alignment elapsed about `17s`.
- Stable subtitle output passed validation: `subtitle_count=303`, `translation_structure_errors=[]`, `render_blocked=false`.
- Final SRT timing audit: `overlap_count=0`, `gap_gt800=1`, `gap_gt1000=0`, `empty_chinese=0`.
- Podcast learning template video rendered successfully to the source audio folder.

## Latest WhisperX Time-Only Change

- Added `whisperx-time-only` backend.
- In transcript alignment, this mode still uses stable-ts word timestamps for stable cutting.
- After screen subtitle editing, it aligns the pre-cut ASR phrases and maps
  each result monotonically to the frozen word ledger; an unmatched word keeps
  its own stable-ts time.
- It derives final cue times only from the existing subtitle ID word spans. A
  full cue is never mapped by its final cue text.
- `final-cue-timeline.json` is the shared timing artifact for validation and
  export. Own-word envelope failures, `S0000` IDs, or a cue order that differs
  from frozen subtitle-ID order block SRT/ASS export.

## Latest Alignment Verification

Sample:

- `C:\Users\19379\Desktop\如何识别人工智能写作\如何识别人工智能写作.m4a`

Result:

- CUDA WhisperX alignment returned `2780` raw words and mapped all `304/304` final subtitle cues.
- The retimed output had no overlaps and no cue shorter than `250ms`.
- Median cue start moved by about `-44ms` and median end by about `-78ms` versus the prior stable-ts display-padded result.
- The new path does not add a second display-duration extension after WhisperX alignment.

## Next Recommended Task

Use a previously unseen audio as a blind validation run before changing further
generation rules. Review the result by these four dimensions:

- English word coverage, order, IDs, and final timing remain frozen.
- No translation-ID structure failure or final render blocker occurs.
- High-confidence English syntax boundaries are counted separately from
  low-confidence reading-speed and short-response warnings.
- Optional Chinese polish only touches selected semantic groups and must show
  an accepted fixed-ID validation result.

Historical sample patterns and non-actions are recorded in
docs/audits/2026-08-01/historical_work_dir_pattern_review.md.

## Latest Stable Cutting Verification

- Pre-ID boundary repair candidates now pass a single local write gate before
  they can replace word spans. The gate preserves exact word order/range and
  rejects newly introduced hard syntax issues, ordinary one-word fragments,
  discontinuous ranges, speaker crossings, and hard word-limit violations.
  Unchanged external boundaries are not re-evaluated as new candidate errors.
- Parser-backed protections now cover direct verb particles, compact
  coordinated subjects, short verb-dative-object starts, and contiguous
  `from number to number` ranges. These rules use spaCy dependencies, the
  frozen word ledger, and local pauses; they contain no sample-specific text.
- The spaCy-to-word-ledger mapper no longer treats an arbitrary stop-word
  substring inside the preceding word as a consumed compound token. Subtoken
  suppression is limited to delimiter-backed compounds, preventing `in`
  from disappearing inside `stepping` during syntax hint preparation.

- Sentence-final tokens that are also prepositions, such as `over.` in
  `the era is over.`, are treated as explicit sentence boundaries rather than
  preposition-object splits. This prevents final pre-ID repair from moving a
  following discourse marker into the preceding subtitle.

## Visual Reading Budget

- The final English pre-ID pipeline now has a conservative visual reading pass
  after syntax and fragment repairs. It prefers safe splits for cues over 12
  words or 68 visible English characters, matching the 1080p bilingual
  template's two-line reading budget.
- The pass reuses the same local syntax, fragment, continuity, speaker, and
  sentence-transition checks as the stable cutter. It does not alter ASR
  text, word times, Chinese, IDs, or the existing 16-word structural limit.
- Parser-confirmed `prep -> pobj/pcomp` relations are protected at the word
  ledger layer, including noun-attached example phrases. This prevents a
  visual-only temporal split from stranding an example introducer above its
  complement. When a local display split is otherwise safe, the whole example
  phrase moves to the next cue; its internal word boundary is never used.
- A parser-confirmed comma-bracketed adverb that locally modifies a following
  preposition is retained with the preceding list item, so visual pressure
  cannot create a new cue beginning with an orphaned sentence-internal aside.
- A compact `VBG/advcl` manner phrase without punctuation or a long pause is
  retained with its main action. The visual pass also rejects any newly
  created non-finite preposition-led tail, regardless of its word count.
- A cue with no safe split remains intact for renderer wrapping. The visual
  temporal pass does not manufacture an unresolved structural issue merely
  because a cue exceeds the soft reading target.

Historical word-ledger replay sample:

- `C:\Users\19379\Desktop\韩国\韩国.m4a` (replayed from its frozen word ledger;
  no ASR or LLM request was made during the cut verification).

Result:

- Parser-backed replay no longer selected the former boundaries after a clause
  introducer, between a verb and its preposition complement, or between a
  phrasal verb and its object.
- The replay produced 93 local English cues. Four structural exceptions were
  longer than 16 words; no cue exceeded 19 words.
- A 19-word proper phrase was retained as one unit rather than split into an
  18-word cue plus a one-word orphan.
- `runtime\python.exe scripts\run_regression.py` completed successfully after
  the change. Existing stale sample audit paths remain `MISSING` in this
  checkout and are not evidence of a generation failure.

## Latest Chinese Allocation Verification

Sample:

- `C:\Users\19379\Desktop\AI\AI.m4a` (completed stable output, 82 cues).

Result:

- The production output had no blocking validation errors, but its four-cue
  comparison/source-list group `S0018`-`S0021` was grammatically weak in
  Chinese despite valid IDs and intact source text.
- The new optional polish selector chose only that group in a dry replay.
  One LLM request rewrote only its four Chinese fields by their existing IDs;
  no English, subtitle ID, or timing data was changed.
- The replay evidence is stored beside the artifacts as
  `chinese-polish-id-protocol-test.json`. It is a verification artifact and
  does not overwrite the Desktop SRT files.

## Latest Full-Flow Verification

Sample:

- `C:\Users\19379\Desktop\如何识别人工智能写作\如何识别人工智能写作.m4a`

Result:

- FasterWhisper, stable-ts cutting, DeepSeek allocation, WhisperX time-only,
  and the article-template render completed in one run.
- The final manifest recorded 217 frozen subtitle IDs; returned Chinese IDs
  matched exactly, with no missing, duplicate, unknown, or empty translation.
- `translation-structure-errors.json` was empty, validation had zero `ERROR`,
  and rendering was not blocked.
- The source audio directory contains the current bilingual/English/Chinese
  SRT exports, `字幕质检队列.srt`, and the completed template video.
- The QC source report held 33 `REVIEW` and 21 `INFO` items; the user-facing
  queue was deterministically capped to 12 timed review entries.

## Latest Same-Source Verification

Sample:

- `C:\Users\19379\Desktop\创业者的天堂\创业者的天堂.m4a`

Result:

- Completed at `2026-08-03T10:42:49+08:00` using FasterWhisper, article
  assistance, DeepSeek Flash allocation concurrency `3`, and
  `whisperx-time-only` timing.
- Produced `338` final bilingual subtitle cues. Translation structure errors
  were empty and `final-cue-timeline.json` reported `PASS` with `0` errors;
  export was not blocked.
- Local article-entity protection was verified in the final SRT: `Americans`
  remained unchanged, the invalid `America have applied` rewrite did not
  occur, and `American Enterprise Institute details` retained `details`.
- Article-assisted ASR correction now rejects an automatic short-alias
  replacement when the original word range supports a different documented
  canonical entity with a conflicting discriminator token. The rejected
  candidate remains `review_only` with both entities and their source evidence
  in `correction_log.json`; no English segmentation, timing, ID, translation,
  or export stage is involved.
- `runtime\python.exe -X utf8 scripts\run_regression.py` passed after the
  rerun. The remaining CRLF messages from `git diff --check` are repository
  line-ending notices, not whitespace failures.

## Latest Allocation And Boundary Regression

- Fixed-ID Chinese allocation rejects terminal modifier fragments and performs
  one grammar-specific retry without changing English, IDs, word spans, order,
  or timing. Fully punctuated single-cue Chinese groups no longer receive
  fragment-only semantic warnings.
- Chinese reading speed from `9.0` through `12.25` characters per second is
  recorded for review; only a sustained value above `12.25` remains an error.
- A rejected direct pre-ID fragment merge now continues to the existing safe
  repartition search in the same local window. This restores a legal English
  boundary without changing the frozen post-ID subtitle contract.
- `runtime\python.exe -X utf8 scripts\run_regression.py` and
  `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py` passed on
  2026-08-04 after these changes.

## Latest Stable English Boundary Routing Audit

- Stable screen mode now excludes the legacy `SubtitleOptimizer` even when
  the legacy `need_optimize` option remains enabled. Its English text, order,
  and boundaries therefore remain owned by the local word-ledger path.
- Stable screen editing now fails closed when the required word ledger is
  absent or any source segment cannot map to it. It cannot silently enter the
  legacy LLM screen-editor path with incomplete timing ownership.
- These are routing-only changes: existing frozen cue text, word spans,
  subtitle IDs, Chinese allocation, final cue timing, and rendering behavior
  are unchanged for valid stable inputs.
- Regression coverage verifies both conditions. On 2026-08-04,
  `tests/test_english_boundary_rules.py`,
  `tests/test_stable_boundary_finalization.py`,
  `tests/test_stable_caption_rules.py`, and
  `scripts/run_regression.py` passed. A fresh ASR/alignment production run on
  unseen audio remains the outstanding validation risk.

## Latest Renderer-Owned Structural Overflow

- The stable greedy cutter no longer forces a 19-word boundary when every
  normal-limit boundary would break protected syntax or leave a grammatical
  fragment. A 17-19 word candidate is accepted only when it is itself a
  complete terminal cue or a parser-confirmed comma subordinate clause.
- If no such pre-ID cue boundary exists, the remaining complete source
  sentence stays frozen as one renderer-owned cue. It is recorded as a
  `structural_english_overflow` warning, never an `overlong_english` export
  blocker. A safely splittable or incomplete overlong cue remains blocking.
- Frozen-ledger replay of `如何识别人工智能写作` converts the former incomplete
  19-word `synthetic` and `websites` cues into their complete 38-word and
  22-word source sentences. The replay uses no ASR or LLM request.
- Regression coverage verifies the forced-cut branch, the incomplete
  17-19 candidate branch, and the validation distinction.

## Latest Parser-Confirmed English Boundary Protection

- Stable pre-ID cutting now protects three additional local dependency shapes:
  compact coordination, an object immediately followed by a content-clause
  marker, and a verb-attached post-object modifier. The protection applies
  only to continuous short spans without a meaningful recorded pause.
- A comma-delimited `but`, `or`, `so`, or `yet` clause boundary remains
  eligible for the existing visual temporal split; it is not treated as a
  compact coordination.
- This changes English boundary eligibility before IDs are assigned. English
  source order, word-ledger timestamps, Chinese allocation, final cue timing,
  and export behavior remain unchanged. Fresh production validation is still
  required for the prior `识别` run because that artifact predates the fix.

## Stable Manifest Resolution

- When `stable-final-manifest.json` exists beside the selected subtitle path,
  podcast-template synthesis treats it as authoritative. A malformed manifest
  or unavailable declared final SRT blocks synthesis instead of falling back
  to filename-based discovery, preventing stale subtitle reuse.

## 2026-08-04 Fixed-ID Retry Audit And Imperative Visual Boundary

- A retryable initial allocation response that omits, duplicates, or invents a
  fixed subtitle ID is now retained in `allocation-validation.json` as an
  `allocation_structure_attempt`. A later successful per-group retry clears
  the final blocking structure error but does not erase the protocol evidence.
  English text/order, IDs, word spans, final cue timing, and final Chinese
  writeback remain unchanged.
- The pre-ID visual temporal pass now recognizes a terminal imperative with a
  bare `VB` root as a complete display unit only when it has no explicit
  subject, attached `to`, or leading subordinator. It still requires the
  existing terminal pause, duration, word-range continuity, syntax, and
  candidate-write gates; `To consider ...` remains ineligible.
- `runtime\python.exe -X utf8 scripts\run_regression.py` and
  `git diff --check` passed after integrating both changes. A fresh unseen
  audio production run remains required to assess real ASR parsing and Chinese
  allocation behavior.

## 2026-08-04 Relative-Clause Predicate Boundary E2E

- Root cause: final pre-ID boundary validation evaluated only the left cue's
  display fragment. A right cue that began with a finite predicate but lacked
  a subject could therefore remain legal. The local repair-window pause gate
  then excluded the 480 ms production boundary even though the two cues were
  syntactically dependent.
- Fix: final boundary evaluation now records
  `right_orphaned_finite_predicate` from the local spaCy parse. Only that
  target boundary may enter a direct merge across its recorded pause; the
  merged 17-19 word cue must still satisfy the existing complete-sentence,
  no-legal-normal-split structural-overflow proof. Other pre-ID repairs retain
  their original pause rule.
- Regression coverage includes the production relative-clause shape with a
  480 ms pause. `tests/test_stable_caption_rules.py` and the unified
  `scripts/run_regression.py` passed.
- The isolated subtitle-stage E2E rerun at
  `E:\VideoCaptioner-e2e-runs\ai-writing-relative-predicate-fixed-r2` passed
  with 276 cues, no render block, no final-timeline errors, and delegated PNG
  review at 7, 10, 15, and 18 seconds. It used a copied E2E cache/config,
  produced no ASR, WhisperX, or video-synthesis work, and used stable-ts
  fallback timing because no source audio was supplied to this subtitle-only
  runner.

## 2026-08-04 Article Template Structural-Overflow Rendering

- Root cause: `draw_article_frame()` rendered only the first two Chinese
  wrapped lines. A grammatically protected 37-word English cue therefore
  retained its frozen subtitle boundary but silently lost the tail of its
  77-character Chinese translation in the article-template video.
- Initial containment: article-template rendering no longer slices wrapped
  Chinese text. The subsequent visual-pagination behavior below is now the
  acceptance path for long bilingual cues; fitting an entire long cue into one
  two-line panel is not considered readable output.
- Regression and real-frame validation used the former S0004 shape. The PNG
  at `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\overflow-fix-frame\S0004-fixed.png`
  contains the entire Chinese text with no English/Chinese alpha-mask overlap.
  `tests\test_stable_caption_rules.py`, `scripts\run_regression.py`, and
  `git diff --check` passed. No full video was rerendered for this layout-only
  verification.

## 2026-08-04 Article Template Visual Pagination

- Root cause: the structural-overflow path deliberately retained a grammatically
  protected English cue as one frozen subtitle timeline item. The renderer only
  wrapped that cue, so the real 37-word S0004 was still displayed as a large
  bilingual paragraph in one frame. Keeping all characters visible did not
  satisfy the template's reading requirement.
- Fix: article-template rendering now creates deterministic visual pages inside
  one existing cue when it exceeds the normal 16-English-word screen ceiling or
  30 visible Chinese characters. English pages preserve exact word order and
  prefer nearby punctuation; Chinese pages prefer nearby Chinese punctuation.
  Otherwise both use balanced local splits. The active page is selected from
  the current render time as an equal fraction of the original cue envelope.
- Invariant: the renderer does not change SRT/ASS text, subtitle IDs, frozen
  word spans, cue start/end times, Chinese allocation, or manifest resolution.
  A visual page is presentation state only. Video frame caching includes the
  visual page index so a long cue actually advances instead of reusing page 1.
- The real S0004 envelope (`13.290s` to `25.440s`) renders as three readable
  pages. Delegated PNG checks at `13.5s`, `17.5s`, and `21.5s` found two English
  lines plus one Chinese line per page, no crop, and zero visible English/
  Chinese alpha-mask overlap. The page texts concatenate exactly to the frozen
  source cue. Evidence: `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\visual-pagination-validation`.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`,
  `runtime\python.exe -X utf8 scripts\run_regression.py`, and
  `git diff --check` passed. No ASR, LLM call, or full-video synthesis was run.

## 2026-08-04 Formal English Boundary Ownership

- Root cause: the active pre-ID boundary stage list still invoked
  `_apply_visual_reading_budget`. Its 12-word/68-character trigger could
  create extra formal English cues before IDs froze, forcing Chinese allocation
  to mirror a visual fragment.
- Fix: removed that function from `STABLE_ENGLISH_BOUNDARY_STAGES`. The helper
  remains an offline historical diagnostic only; production boundaries now end
  with syntax/timing validation and long cues flow unchanged to renderer-only
  pagination.
- Regression injects a failing visual-budget method into the editor and proves
  the formal finalizer cannot call it. A 14-word grammatical cue also remains
  one pre-ID item in the finalization test.
- `tests\test_stable_boundary_finalization.py`,
  `tests\test_stable_caption_rules.py`, `scripts\run_regression.py`, and
  `git diff --check` passed. No ASR, LLM request, or synthesis ran.
- Earlier references to the pre-ID visual temporal pass are retained as
  historical records and are superseded by this ownership rule.

## 2026-08-04 Whole-File English Boundary Evidence Audit

- Root cause: the old syntax audit emitted only selected text-pair warnings.
  It did not prove whole-file coverage, distinguish a hard atomic split from an
  ambiguous boundary, or use the frozen word-ledger pause and speaker evidence.
- Fix: every final English boundary now receives `hard`, `review`, or `allow`
  evidence in `english-boundary-audit.json`. A `hard` item has an atomic
  structure rule and no sentence-terminal, 450ms pause, speaker-change, or
  discontinuous-ledger counterevidence; it blocks export if it survives the
  existing pre-ID auto-repair. `review` items enter the quality queue; `allow`
  items are recorded only in the full audit artifact.
- Screenshot-derived fixtures cover measured hyphenated heads, comparisons,
  intensifier particles, compound prepositions, and numeric magnitudes. They
  also prove that terminal `Because`, `In`, and finite-clause starts remain
  allowed, while a long pause downgrades a comparative shape to review.
- The scanner uses local rules, frozen word times, punctuation, and speaker
  evidence. spaCy hints remain evidence only, never a final judge.
- `tests\test_english_boundary_rules.py`,
  `tests\test_stable_caption_rules.py`, `scripts\run_regression.py`, and
  `git diff --check` passed. No ASR, LLM request, or synthesis ran.

## 2026-08-04 Article Renderer Word-Timeline Gate

- Article-template rendering now requires a verified stable manifest, final
  cue timeline, and word ledger for every cue, including cues that fit on one
  visual page. A missing or mismatched ledger raises
  `render_structural_overflow` before any vocabulary work or ffmpeg process.
- Fixed article subtitle fonts remain 58px English and 46px Chinese. Visual
  pages are presentation-only, preserve frozen cue IDs/text/times, switch only
  at word gaps, and require 900ms minimum duration. The renderer does not
  lower the font size or weaken the page-duration gate to force a video.
- Offline preflight of the 215-cue `ai-writing-style-full-e2e-20260804` stable
  artifact found 212 valid plans and three intentional render blocks:
  `S0188`, `S0202`, and `S0208`. Evidence is under
  `E:\VideoCaptioner-e2e-runs\renderer-word-timeline-validation`.

## 2026-08-04 Article Renderer Static Fixed-Width Layout

- Root cause: the page planner treated a normal same-page line wrap as a
  timed page requirement. It also treated Chinese character count above 30 as
  overflow despite a valid 46px two-line pixel layout. Short source cues could
  therefore be blocked when no legal 900ms word-gap transition existed.
- Fix: fixed-font planning now accepts a static page with up to two English
  lines at either the normal 1455px width or a 1498px safe-width profile, and
  up to two Chinese lines measured at 46px. Character count is not a layout
  authority. A timed page is still permitted only when static layout fails,
  and it retains the word-ledger gap and 900ms duration gate.
- Frozen English text, subtitle IDs, word spans, cue times, Chinese allocation,
  SRT/ASS output, and manifest resolution are unchanged. No font reduction,
  cue merge, or direct output patch is used.
- Offline replay of the 215-cue `ai-writing-style-full-e2e-20260804` artifact
  now produces 215 valid page plans. Representative fixed-font PNGs for
  `S0188`, `S0202`, and `S0208` are at
  `E:\VideoCaptioner-e2e-runs\renderer-layout-profile-validation`; they show
  no crop or English/Chinese overlap. `S0110` also uses the safe-width static
  two-line profile instead of a time page.
- `tests\test_stable_caption_rules.py`, `scripts\run_regression.py`, and
  `git diff --check` passed. No ASR, LLM request, or full-video synthesis ran.

## 2026-08-05 Explicit E2E Source Audio Contract

- Root cause: the E2E subtitle task used a report-anchor `video_path` that did
  not exist, while final WhisperX time-only alignment read that same field and
  therefore recorded `source_audio_missing` before invoking WhisperX.
- `SubtitleTask.source_audio_path` now owns the read-only original media used
  by final alignment. `TaskFactory.create_subtitle_task()` defaults it to the
  legacy `video_path` for existing production callers, while E2E supplies the
  real `.m4a` separately and keeps report sidecars inside its run directory.
- The task-level regression verifies that an existing source `.m4a` reaches the
  time-only aligner without changing the report anchor. Unified regression and
  `git diff --check` pass.
- The ASR preflight with the production model directory reproduced the prior
  `original-transcript.srt` byte-for-byte. The subsequent full E2E reached the
  existing hard English boundary gate at `S0160 -> S0161` (`to | so`) before
  final alignment, so no new `final-cue-timeline.json` or video was produced.
  This task does not alter English boundaries, IDs, or text to bypass that
  independent blocker.

## 2026-08-05 Comma-Scoped Elliptical Infinitive Boundary Audit

- Root cause: the whole-file English boundary audit treated every `to | so`
  boundary as a high-confidence `preposition_object_split`, even when the
  left cue ended in comma-scoped ellipted infinitive syntax, a real pause was
  present, and the right cue was a complete result clause.
- Fix: that combination is now recorded as `review` evidence with
  `preposition_object_split` retained in `rule_codes`; it no longer creates a
  render-blocking `hard_english_boundary`. Ordinary preposition/object,
  numeric, comparative, and named-phrase splits retain their hard gates.
- Regression coverage adds the real `forced to, | so it doesn't...` shape with
  a 380ms pause. The focused English-boundary tests, unified regression, and
  `git diff --check` pass.
- Commit: `efe368b` (`fix boundary audit ellipted result clauses`).
- A fresh full E2E using the current code completed under
  `E:\VideoCaptioner-e2e-runs\ai-writing-current-boundary-fix-e2e-20260805`:
  210 fixed IDs, 210 English/Chinese mappings, final timeline `PASS`,
  `applied_backend=whisperx-time-only`, no `source_audio_missing`, and one
  synthesized 11:07.36 video. Three display-coverage warnings remain in the
  runtime log for later targeted visual review; they did not block this final
  timeline or synthesis.

## 2026-08-05 Current-Code Full E2E and Chinese Compression Validation

- The current-code subtitle rerun for `中国AI为何更省钱？.m4a` completed in
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805` using cached
  translation/allocation artifacts (zero external LLM requests).
- Final timeline validation passed for all 273 fixed IDs. The applied backend
  is `whisperx-time-only`, with `fallback_used=false` and no
  `source_audio_missing` record. The 64.8-66.5s audit interval is covered by
  S0019 through 67.975s, including its final word envelope through 67.645s.
- Chinese post-processing now inherits terminal punctuation from the frozen
  complete cue, permits a validated single-cue speed compression, and runs
  after final display-duration reconciliation. These changes are covered by
  focused regression tests.
- Synthesis produced `final-video.mp4` (61,356,806 bytes). Vocabulary-card
  generation exceeded its responsiveness timeout and was skipped; subtitle
  rendering still completed successfully. The QA queue retains 40 review items
  and two unresolved allocation-quality items for later human review.

## 2026-08-05 Chinese Visual Page Word-Boundary Guard

- Root cause: the article renderer mapped English page word proportions to raw
  Chinese character offsets. A target inside `大陆` therefore produced the
  visible `大 | 陆` split even though the frozen Chinese cue was complete.
- Fix: visual-page planning now obtains deterministic Chinese word-end offsets
  from the vendored MIT `jieba` 0.42.1 runtime subset and only switches at a
  tokenizer boundary, punctuation, or an explicit phrase-start boundary. The
  renderer never changes the frozen SRT, subtitle IDs, English text, Chinese
  allocation, word ledger, or page timing.
- If the local tokenizer cannot provide a safe boundary, the strict planner
  fails closed with `chinese_no_safe_visual_boundary`; it does not fall back to
  character slicing. The tokenizer cache is written below the active E2E
  `AppData` cache, never to the production runtime.
- Offline replay of the 273-cue `china-ai-cheaper-e2e-20260805` artifact now
  produces 273/273 valid plans. `S0055` renders as `...一片大陆` then
  `那么大的...`; representative PNGs are in
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805\visual-pagination-fixed-20260805`.
- Added regression coverage for the observed `大陆` split, punctuation-free
  Chinese compounds, and the fail-closed path. Stable caption tests, unified
  regression, and `git diff --check` pass. No ASR, LLM request, or video
  synthesis was run for this renderer-only change.

## 2026-08-05 Boundary, Allocation, and Blind E2E Verification

- Stable English cutting now stops numeric-result protection at punctuation or
  coordinator boundaries, protects a content noun from an attached `that`
  clause, and keeps a complete `Oh.` lead-in with the next 16-word unit only
  when the one-word overflow contract is satisfied. These rules remain pre-ID
  and local.
- Fixed-ID Chinese allocation now invalidates allocation caches independently of
  complete-group translation caches. Verified legacy full-translation cache keys
  may be migrated once; allocation and retry keys still require the current
  frozen-boundary and allocation algorithm contract. Allocation validation also
  rejects bare Chinese syntactic heads and displaced main clauses before a
  candidate can replace the current ID mapping.
- Article visual pagination now keeps modifier-head English phrases together and
  uses vendored deterministic Chinese token boundaries. It never changes frozen
  English, Chinese, IDs, word spans, cue times, or font size; an unsafe Chinese
  split fails closed.
- Cached current-code E2E for `中国AI为何更省钱？.m4a` completed under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805-r3`. It produced 271
  fixed IDs, 2,897 frozen words, `final-cue-timeline.json` status `PASS`,
  `applied_backend=whisperx-time-only`, `fallback_used=false`, and no
  `source_audio_missing`. Eight individual words retained stable timestamps as
  unmatched-word fallbacks; this was not an overall stable-ts backend fallback.
- ID and English text sets remained identical between `subtitle-spans.json` and
  `translations.json`; Chinese mappings contained all 271 IDs. The 64.8-66.5s
  interval is covered by `S0019` from 62.312s through 67.975s, including the
  spoken words through 66.585s.
- Synthesis completed once at
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805-r3\final-video.mp4`:
  62,239,995 bytes, 16:43.66, 1920x1080 H.264/AAC. Vocabulary-card
  generation timed out after 319.1s and was skipped; subtitle rendering was
  unaffected.
- Subtitle LLM cache statistics recorded 21 misses: 13 full translations, one
  style retry, four allocations, and three fragment retries. The vocabulary
  runner does not expose a per-attempt request counter; its timed-out attempt is
  reported separately and no credential material was recorded.
- Unified regression passed. The final QA report has zero structural blockers,
  three unresolved Chinese allocation-quality reviews, and ordinary timing and
  reading warnings that remain for human review.
