# Current State

Last updated: 2026-08-17

## 2026-08-17 Balanced Same-Screen Wrap And Manual Split Fallback

- Article-template same-screen English wrapping now compares every legal width
  profile instead of accepting the first fit. It scores measured pixel balance,
  keeps lexical atoms hard, and ignores only the page-turn-specific
  `unsupported_tight_page_transition` warning because both lines remain visible.
- The article display planner is `article-fixed-font-pages-v24`; older page
  layout/projection caches are rebuilt while ASR, full-translation, and fixed-ID
  caches retain their independent fingerprints.
- Automatic page planning remains conservative. When strict and REVIEW
  partitions cannot satisfy a requested manual page count, the editor offers a
  Chinese confirmation dialog. Confirming creates a timed-word, pixel-load and
  duration-balanced high-risk proposal, preserves the original HARD evidence,
  and requires the user to adjust boundaries and confirm page Chinese.
- The override cannot change the parent ID, English, word ledger, word times,
  cue envelope, or audio. It cannot permit missing timing, non-contiguous word
  ownership, lost/duplicated/reordered words, or fixed-font overflow.
- Read-only oil replay kept 163 pages and two three-line pages while reducing
  two-line balance ratios below 0.60 from 23 to 18 and ratios below 0.45 from
  eight to two. The complete regression command passes.

## 2026-08-17 Display-Page Chinese Candidate Fallback Recovery

- The fresh `肠道菌群，能人为操控吗？` run later reached 96% and failed in
  display-page Chinese assignment. Its ASR, 217 frozen subtitle IDs, English,
  word ledger, final timing, and 33 paginated parent contracts were complete.
- The stricter page audit correctly detected repetition and significant
  expansion, but the retry control flow treated Pro as a second authority.
  The initial Flash projection was complete with zero hard errors and six
  local-fluency REVIEW findings; Pro made several parents worse, and the old
  flow incorrectly converted that optional improvement failure into an
  episode-wide render blocker.
- Local page-edge fluency evidence (`unnatural_chinese_fragment`, missing local
  predicate, dangling preposition/modifier, punctuation discontinuity, or
  English-shaped page order) is now REVIEW evidence after retry. It does not
  hide missing Chinese, page-ID/cardinality errors, semantic loss, repetition,
  significant expansion, entity/number/negation/relation drift, illegal Chinese
  token cuts, or hard page reading-speed overflow; those remain blockers.
- When a complete initial projection has only REVIEW evidence, Pro is an
  optional candidate. If the request fails or the candidate introduces hard
  errors, the system preserves the usable Flash pages and records the rejected
  attempt in `retry_attempt_errors`. An initially incomplete or semantically
  invalid projection still fails closed.
- Read-only replay of the failed package passes all 33 paginated parents with
  zero hard errors and six retained REVIEW findings. Focused tests, the full
  page-translation contract suite, `runtime\python.exe scripts\run_regression.py`,
  and `git diff --check` pass. No English, ID, word-time, page-geometry, font,
  rendering, or production artifact was changed by this repair.

## 2026-08-17 Single-Cue Chinese Quality-Gate Recovery

- A fresh `肠道菌群，能人为操控吗？` run reached 84% and failed while
  building `authoritative-parent-chinese.json`. The page planner and page-level
  Chinese gates had not run. Cached response replay traced the empty parent to
  `G0163 / S0194`.
- The semantic detector treated every English `because` as requiring a literal
  Chinese causal marker. It therefore misclassified the natural construction
  `Just because ... does not mean ... -> ...不等于...` as `semantic_loss`.
  The detector now recognizes negative-entailment Chinese for that general
  English construction without weakening ordinary causal checks.
- A non-empty authoritative translation for a one-cue semantic group can no
  longer be erased by a heuristic quality finding. The translation remains
  ID-bound and the unresolved quality evidence is retained for editor review,
  matching the existing multi-cue retry-failure contract. Missing upstream
  translations still fail the fixed-ID structural gate.
- Read-only replay of the saved model caches covered 180 semantic groups and
  all 217 fixed subtitle IDs: no empty multi-cue allocation and no invalid
  direct group remained. The stable-caption suite and complete
  `runtime\python.exe scripts\run_regression.py` command pass.

## 2026-08-16 Page Quality And Analysis-Cache Audit Repair

- Page-level Chinese projection now validates the concatenated rendered text
  against its authoritative fixed-ID parent Chinese. Exact fact repetition and
  significant expansion with novel Chinese content fail the page contract and
  enter the existing parent-local retry path; normal reordering and small
  connective changes remain legal. The allocation contract is
  `fixed-parent-page-allocation-v6` and the request prompt is
  `display-page-translation-v5`, so older accepted page responses are not
  silently reused.
- The article display planner is `article-fixed-font-pages-v23`. Boundary
  evidence retains its raw hard and atomic syntax codes after an acoustic or
  continuation relaxation. A plan without a relaxed atomic boundary wins over
  a pause-relaxed hard split. The existing verified complete-continuation
  fallback may still replace an emergency three-line page, but it cannot
  compete with a safe one- or two-line plan.
- High-confidence Chinese semantic-group findings now feed the existing
  parent/group-local Pro retry before publication. If they remain unresolved,
  the editor trusts the producer's high-confidence classification and marks
  every affected fixed subtitle ID instead of applying a second threshold or
  marking only the first ID.
- Article-analysis cache identity now includes the source article, schema,
  prompt contents, and an explicit prompt-policy version. GUI-provided context,
  resume artifacts, and stable-run fingerprints use the same identity, so a
  prompt improvement cannot reuse an older proper-noun or terminology analysis.
- Read-only replay of the saved 140-parent oil package produced 156 pages with
  zero selected relaxed-atomic boundaries. The new Chinese projection gate
  identified the known expansion in `S0117` and `S0136`; the inspected
  manifest, SRT, and page artifact hashes were unchanged.
- Focused suites and the complete
  `runtime\python.exe scripts\run_regression.py` command exit zero. No model
  request, production subtitle write, or synthesis run was performed.

## 2026-08-16 Concise Chinese Translation And 48px Article Subtitle

- Fresh production A/B compared oil v6 run
  `20260816T195901.871590-95b43f33` with v5 run
  `20260816T180732.415118-413818b4`. Both retained the same 140 fixed parent
  IDs, English text, and word spans with zero frozen-field drift. Parent
  Chinese fell from 2674 to 2380 CJK characters (-11.0%), actual-page Chinese
  from 2687 to 2440 (-9.2%), pages above 28 characters from 7 to 2, and the
  longest page from 39 to 30. Both page translation contracts pass.
- Remaining production defects are no longer primarily whole-group verbosity.
  They are concentrated in page projection re-expansion or duplication and a
  few parent translations that overcompress or choose an awkward relation.
- The Pro-owned complete semantic-group translation prompt is now
  `semantic-full-translation-v6`. Every target group carries its fixed
  subtitle IDs, exact English, word-ledger display duration, per-ID advisory
  Chinese budget, and the summed group budget. Pro therefore writes compact
  Chinese against the real reading window instead of receiving only an
  unmeasurable request to be concise.
- The target is soft rather than a deletion gate. Meaning-free conversational
  and written scaffolding, repeated subjects, and English-shaped noun phrases
  should be compressed first. Facts, entities, numbers, negation, causal and
  contrast relations, modality, reactions, hedges, and speaker stance remain
  mandatory; brevity cannot turn translation into a summary. A supplied old
  Chinese translation is terminology reference, not a style or length owner.
- The full-translation cache task is v6, so an old v5 translation without the
  duration budget is not silently reused. This adds no second model request.
  Fixed-ID allocation and display-page projection retain their existing
  ownership and cannot change English, IDs, word spans, timing, or parent/page
  authority.
- The 1080p article-template Chinese font is now 48px instead of 46px. The
  fixed two-line and 1455-design-pixel safe-width contract remains unchanged.
  The page planner is `article-fixed-font-pages-v22`, so artifacts rendered
  with the former typography are not mistaken for current page contracts.
- The style follows the observable compact phrasing of the first three minutes
  of the reference video `我们正进入一个普遍“性压抑”的时代。.mp4`, while the
  layout limits are cross-checked against the Netflix Simplified Chinese guide
  (16 characters per line) and TED's two-line, linguistic-unit guidance.
- Read-only v22 replay of the latest 140-parent oil run preserved every frozen
  parent field. It produced 157 pages, with 145/1/4/7 pages at 56/54/52/50px
  and two three-line pages. Only `S0134` changed: its former 50px three-line
  page became a two-page 50px/56px display plan. No ASR, LLM, synthesis, cache,
  or production artifact was written by the replay.
- Focused translation/font/page tests and the complete
  `runtime\python.exe scripts\run_regression.py` command exit zero.

## 2026-08-16 Frozen English Dependency Boundary Repair

- The pre-ID English boundary owner now protects cross-cue syntactic
  dependencies that the previous word-budget search could cut: date nominal
  continuations, comparative complements, subject/finite-predicate and
  verb/object dependencies, object-control complements, zero-relative clauses,
  embedded `wh` clauses, post-nominal attachments, and predicate clause
  complements. These are parser/timestamp rules, not text-specific exceptions.
- Repair first searches for another legal temporal partition. If none exists,
  the shared structural-overflow contract may retain the complete parent cue
  for renderer pagination instead of manufacturing a grammatical fragment.
  English word text, order, word IDs, word timestamps, and continuous coverage
  remain unchanged; fixed subtitle IDs are assigned only after this repair.
- The visual layer retains a narrower reviewed path only for independently
  complete clause restarts with the existing pause and minimum-page evidence.
  Atomic lexical dependencies remain hard. A visible regression proves that
  `the strait was shut.` cannot become an isolated display page.
- Read-only replay of the frozen oil ledger changed 147 old parent cues with
  eight hard boundaries into 140 current parent cues with zero hard
  boundaries. All 1,537 words remain in exact order with contiguous coverage;
  the 25-word conditional becomes a legal 17+8-word pair. Evidence is recorded
  in
  `E:\VideoCaptioner-e2e-runs\oil-market-english-boundary-fix-20260816\frozen-mainline-report.json`.
- The complete `runtime\python.exe scripts\run_regression.py` command exits
  zero after the focused English-boundary and visible-page regressions. No
  production subtitle, audio, video, cache, or source-media file was modified
  by the read-only replay.

## 2026-08-16 Display-Page Chinese Stale-State Correction

- The manual editor now compares a current parent cue with the page artifact's
  explicit `source_parent_chinese` binding. It no longer treats a valid
  page-local Chinese reordering as stale merely because concatenated page
  Chinese differs from the authoritative parent wording.
- Legacy page artifacts without `source_parent_chinese` retain the prior
  reconstruction check and still fail closed when their page Chinese no longer
  matches the current parent translation.
- Read-only loading of the fresh 147-parent oil run produced all 163 display
  pages, zero missing Chinese rows, and zero stale-Chinese rows. The four
  remaining review-class pages are English boundary reviews, not missing page
  translations. No subtitle text, ID, word range, timing, page boundary, or
  production artifact was changed.
- The manual editor suite and complete regression command exit zero.

## 2026-08-16 Reference-Style Display Planning v21

- The article display planner is now `article-fixed-font-pages-v21`. A bounded
  candidate frontier retains several distinct legal word partitions per page
  count and fallback tier. Candidate scoring uses the final per-page font,
  line wrap, measured width, and two-line balance that the renderer publishes.
- Local measured reading load owns page count. Whole-episode continuity may
  choose only among boundaries for that locally selected count; it cannot
  trade away pages merely to reduce transitions. Strict, reviewed, and forced
  candidates remain separate safety tiers.
- High-pressure cues (long duration, over 14 words, or no 56px static layout)
  enumerate bounded fallback alternatives even when a strict plan exists. A
  complete all-56px partition wins over a smaller-font alternative. When no
  all-56px plan exists, replacing a 50px three-line page with complete pages of
  at most two lines is still a valid improvement. A complete `to ...` phrase
  and `from + gerund` complement have reviewed paths; noun-attached modifiers
  and incomplete clause-introducer boundaries remain ineligible.
- Two-line wrapping uses a measured 1100-design-pixel line target and balanced
  line lengths. A 50px page exhausts two-line layouts before the three-line
  emergency fallback. Ordinary readable 56px two-line pages are not split only
  to raise page frequency.
- Final read-only v21 replay preserved all 211 Mixue and 147 oil parent IDs,
  English text, word ranges, and cue start/end times. The current planner emits
  238 Mixue pages (56 in the first three minutes, 18.667 pages/minute) and 163
  oil pages (54 in the first three minutes, 18.0 pages/minute). Mixue has 228
  56px, 3 54px, 2 52px, and 5 50px pages; oil has 154 56px, 3 52px, and 6
  50px pages. There are zero three-line Mixue pages and two oil pages.
- The final two-line balance medians are 0.806 (Mixue) and 0.803 (oil); adjacent
  page word-delta P90 is 9 for both. The lower page rate versus the earlier v21
  replay is intentional: three cues that were paginated only by duration are
  now stable one-page 56px layouts, and candidates that would create 5-word or
  attached-modifier pages remain rejected. The remaining oil three-line pages
  have no safe timed boundary under the frozen word ledger. No production file,
  ASR, LLM, synthesis, network, or paid request was used by this replay.

## 2026-08-15 Display Page Visual Stability v20

- The article display planner is now `article-fixed-font-pages-v20`. It still
  chooses only among locally timed, fixed-English page candidates; English,
  subtitle IDs, word ownership, word times, and cue timing remain unchanged.
- Whole-episode selection now treats adjacent pressure changes as a bounded
  preference and font/line-count changes as weaker tie-breakers. Consecutive
  overload remains more expensive than a density change, and typography
  continuity alone cannot make an incomplete review boundary beat a better
  local parent plan. Incomplete review boundaries remain available only when
  their existing readability benefit outweighs the explicit review penalty.
- A 54px static page may enter the existing secondary safe-page review path.
  The replacement must keep 56px, at least six words and 900ms per page, and a
  complete supported boundary. Ordinary 56px two-line pages are not promoted
  merely because their word or speaking load is above average; 50px and three
  lines remain last-resort fallbacks.
- The priorities match the official Netflix English timed-text guide and TED
  subtitling tips: at most two ordinary lines, retain linguistic units, balance
  line lengths, and control reading load. Neither source defines a universal
  adjacent-density delta, so the project-specific continuity score remains a
  soft selector rather than an industry threshold.
- Focused readability contracts pass. Read-only before/after replay of the
  147-parent oil package changed one 10+4-word two-page plan into one 56px
  two-line page; replay of the 211-parent Mixue package changed one 6+7-word
  two-page plan the same way. Both replays preserved complete English coverage,
  order, IDs, word ranges, and timing, with no new small-font, three-line, or
  incomplete-review selection. Existing v19 manual-final packages also reopen
  under v20 with all 22/70 files byte- and metadata-identical. The complete
  26-stage regression exits zero. No production output was written.

## 2026-08-15 Final Parent Chinese State Synchronization

- Final punctuation alignment and optional Chinese compression now publish
  their resulting Chinese text back to the fixed-ID `ScreenSubtitleItem`
  projection before stable artifacts and display-page translations are built.
- The synchronization is ID-addressed and validates the complete ordered ID
  set, English text, and frozen word spans before changing any Chinese field.
  A count, ID, order, English, or word-span drift fails closed; page projection
  retains its independent parent-Chinese drift gate.
- This fixes the fresh `石油市场，现在中国说了算？` run where final segments
  contained punctuation-normalized Chinese but `subtitle-spans.json` retained
  three pre-normalization values (`S0062`, `S0102`, and `S0146`). The mismatch
  incorrectly blocked `display-page-translations.json`, so the editor opened
  only the parent-caption view.
- A read-only replay of the 147-cue failed checkpoint reproduced three
  differences before synchronization and zero afterwards. Focused state,
  final-alignment, and page-drift tests pass; the complete 26-stage regression
  exits zero. No production sample, cache, ASR, LLM request, or synthesis output
  was modified during verification.

## 2026-08-15 Translation Role And Page Projection Contracts

- DeepSeek translation now has explicit task owners: complete semantic-group
  translation uses Pro; ordinary fixed-ID and display-page allocation use
  Flash; deterministic quality retries escalate only the affected group or
  parent page set to Pro. Stable English, subtitle IDs, word spans, word times,
  and page geometry remain local and unchanged.
- The authoritative parent Chinese and its display-page Chinese are separate
  projections. Page-local Chinese may use natural Chinese order and never
  writes back into the parent translation. Every new page artifact binds the
  exact source-parent Chinese text/hash from which it was created.
- Legacy schema-v2 page artifacts without an explicit source-parent reference
  remain readable only when their ordered page Chinese exactly reconstructs
  the current authoritative parent Chinese. A conflicting legacy artifact
  fails closed.
- Runtime manifests record the full, allocation, page, allocation-retry, and
  page-retry model roles. Chinese cache keys bind only the model that owns the
  request, so changing Flash does not invalidate verified Pro full-translation
  cache entries. Verified older full-translation caches retain a validated
  one-release migration path.
- Focused model-routing, cache-ownership, two-parent scoped page-retry,
  residual REVIEW, legacy-compatibility, syntax, and diff checks pass. The
  complete 26-stage regression passes. Read-only production replay reopened
  `石油市场，现在中国说了算？` (147 cues) and
  `蜜雪冰城为何卖起了啤酒` (213 cues); recursive size, mtime, and SHA-256
  snapshots were identical before and after loading.

## 2026-08-15 Manual Editor Performance And Compact Recovery

- Parent-scoped page, Chinese, confirmation, and suppression edits now persist
  only the affected parent cue, pages, boundary override, and stale drafts in
  undo history. Existing full-snapshot packages are compacted in memory when
  loaded; their source files are not rewritten until the user explicitly
  saves a new manual-final generation.
- English surface edits retain only the changed frozen word records plus the
  prior formal-ledger hash. Undo, redo, boundary-evidence validation, word IDs,
  word times, and fixed cue spans remain unchanged. Cross-parent edits, formal
  cue-boundary changes, and audio tail trimming remain whole-document
  transactions because their ownership is not parent-local.
- Manual recovery drafts use the same atomic replace path but compact JSON.
  The full current state remains present for crash recovery; only repeated
  historical snapshots were removed. Legacy draft and edit-journal payloads
  remain readable.
- The Qt table keeps full model resets for imports and parent/actual-page view
  switches. Local Chinese, split, merge, boundary, undo, and redo changes use
  row updates/inserts/removals, and identical review marks no longer repaint
  the full table.
- On the real 211-parent, 2,355-word, 119-operation `蜜雪冰城为何卖起了啤酒`
  package, in-memory history fell from 20.7 MB to 2.5 MB and a recovery draft
  from 32.8 MB to 3.1 MB. Hashing fell from about 222 ms to 31 ms and compact
  atomic writing from about 1.30 s to 0.14 s. Read-only replay on that package
  and `石油市场，现在中国说了算？` preserved every unrelated parent through
  Chinese edit, split, undo, and redo.
- Focused manual-editor, review-mark, stable-artifact, and 79-case publication
  tests pass. The final complete regression passed in 346.3 seconds and
  `git diff --check` passes. A mouse-driven GUI pass remains the final
  user-perceived latency check.

## 2026-08-14 Evidence-Bound Failure Reduction

- Display-page Chinese retry now distinguishes local parent-quality failures
  from contract-wide ID/cardinality failures. Local failures retry only the
  affected complete parent page sets; missing, duplicate, or unknown page IDs
  retry the complete contract because no partial parent artifact is safe.
- A failed local retry retains the initial diagnostics and accepted parent
  records, and records the exact retry parent IDs for the editor checkpoint.
  It never changes English, fixed IDs, word spans, word times, or page geometry.
- Article-backed ASR correction v3 supports the evidenced local term
  `fudaoke` and a titled person only when article and nearby audio share an
  informative continuous description. Generic mental-health topic words are
  insufficient, so uncertain names remain review-only.
- Currency suggestions require one unambiguous numeric occurrence, explicit
  money context, and one complete unit occurrence. Count nouns, repeated
  numbers, and ambiguous compound Chinese units are not auto-suggested.
  Parent-ID suggestions may be applied only in parent view; the lower-level
  helper also rejects ambiguous parent IDs in child-page rows.
- Read-only replay of `心理治疗，中国社会的奢侈品` changed the evidenced ASR
  surfaces to four `fudaoke` occurrences and one `Yuan Chengmei`, and emitted
  only `S0053: 75元 -> 75美元` as a manual Chinese suggestion. Source artifacts
  were not modified and no paid request ran.
- Focused article, page-contract, QA-queue, suggestion, syntax, and diff checks
  pass. The final complete 26-stage regression passed in 363.9 seconds;
  subsequent retry-scope evidence passed its owning focused suites.

## 2026-08-13 Real Manual-Final Workflow Acceptance

- A byte-identical temporary copy of the real `如何停止拖延` manual-final
  package loaded 283 frozen parent cues, 353 display pages, 3,126 ledger words,
  and 97 existing history entries. The source package remained read-only.
- The temporary copy completed the actual workflow: split `S0001.P02`, move
  its new internal boundary, merge the two new pages, undo, redo, then undo all
  three operations back to the exact initial session fingerprint.
- A one-page parent Chinese edit was saved without a render blocker, reloaded
  from the newly published manifest, and retained all parent IDs, cue word
  spans, cue times, word IDs, word surfaces, and word times. The synthesis
  resolver accepted that same manual-final manifest as authority.
- Recursive size and SHA-256 records for all 15 production-package files were
  identical before and after the acceptance run. No production subtitle,
  audio, video, cache, or manifest was written.
- This validates the session and publication path against a real package. It
  is not a claim that the Qt candidate dialog has received a full mouse-driven
  walkthrough or that model-backed Chinese suggestions are implemented.
- After the queue and concurrent-prompt follow-up, the complete 25-stage
  regression passes in 397.5 seconds and `git diff --check` passes.

## 2026-08-13 Manual Long-Caption Candidate Workspace

- The stable article renderer now exposes a read-only candidate bundle for a
  single frozen parent cue. Candidates include page count, global word ranges,
  page English, font size, risk score, and quality cost; the helper does not
  mutate IDs, Chinese, timing, or production page artifacts.
- The subtitle editor's actual-page context menu can open these alternatives
  and apply one selected plan to only the current parent subtitle. Matching
  page word ranges keep their existing Chinese; new ranges remain visibly
  unconfirmed until the user edits/confirms them and saves the manual final.
- This is intentionally local and synchronous. It does not call an LLM, rerun
  ASR, refresh the whole document, or change automatic pagination for other
  parents.
- The high-signal queue is now a cheap index over existing page state; it no
  longer precomputes two-to-four-page candidate bundles for every listed
  parent on the Qt thread. The real 283-parent package improved from 45.89
  seconds to 0.020 seconds and retained 34 overlong, low-font, boundary-review,
  or Chinese-review items. Candidate planning remains available on demand for
  one selected parent.

## 2026-08-13 Hit-Only Terminology And Semantic Review Queue

- Article-derived glossary terms are filtered against the current translation
  source window before prompt construction. A canonical term or supported alias
  must be present as a token/phrase; unrelated terms are omitted. Article title
  and summary remain read-only context.
- Prompt/cache fingerprints differ by the matched terminology in each batch.
  Frozen English boundaries, fixed IDs, word ledger, timing, page geometry, and
  synthesis resolution are unchanged.
- QA output includes `semantic-review-queue.json` and
  `semantic-review-queue.srt` in the artifact directory, plus
  `字幕语义复核队列.srt` beside source audio. It is a shortlist for high-signal
  semantic loss, allocation mismatch, translationese, and related Chinese
  issues; it does not auto-rewrite or block a valid stable manifest.
- Focused task-context, QA-queue, stable-caption, page-translation, syntax,
  and `git diff --check` verification pass. The complete 25-stage regression
  also passes after this increment.

## 2026-08-13 English Boundary Gate Repair

- Reproduced the cached `AI竞赛：中美殊途` failure at `S0211 | S0212`:
  `most likely, | to manage` was blocked after alignment reduced the pause.
- The repair now uses parser-confirmed modified-infinitive scope evidence for
  this class of boundary. It preserves `most likely, to manage` together while
  leaving ordinary purpose clauses such as `..., | to manage ...` legal when
  the audio has a genuine pause.
- The pre-ID repair gate is the only owner changed. English word text, order,
  frozen IDs, word times, Chinese allocation, display pagination, and rendering
  contracts are unchanged.
- Focused regression, the complete stable-caption suite, and a read-only replay
  of the immutable 2,596-word production ledger pass. The replay keeps 226
  cues, complete contiguous coverage, and reports zero hard English boundaries;
  its target boundary is `well, | most likely, to manage`.

## Recorded Quality-Ceiling Plan

- `docs/QUALITY_CEILING_ROADMAP.md` is the durable plan for remaining
  translation quality, fixed-ID review, editor efficiency, and selected
  SmartSub patterns. It is planning evidence, not implemented behavior.
- SmartSub findings are pinned to commit
  `27459b3fd0652bc5447ccf4ab30cb398014c35f7`; read the roadmap before
  re-opening the external repository.

## 2026-08-13 Manual Review Workflow Increment

- The editor now exposes a read-only `长字幕复查` queue in stable actual-page
  mode. It groups concrete evidence by frozen parent ID: over-16-word cues,
  reduced font, page-boundary review, and stale/unconfirmed page Chinese.
  Double-clicking an item only locates that parent.
- Candidate pagination rows show word count, page duration, and pause evidence
  before application. Candidate selection still changes only the selected parent
  and preserves matching page Chinese.
- Optional Chinese review suggestions now have a standalone fixed-ID validator
  in `translation_review_suggestions.py`. Source echo, exact IDs, Chinese
  presence, numbers, negation, and existing confirmed Chinese anchors are
  checked before a human can apply a suggestion. The validator is copy-on-write
  and does not change stable artifacts automatically.
- Focused manual-editor and translation-suggestion tests pass. The complete
  25-stage regression also passes after the UI queue increment.

## 2026-08-13 Stable Publication Contract Repair

- The stable producer and manual editor now share one semantic word-ledger
  identity, `canonical-word-ledger-v1`, over ordered surface text, normalized
  text, start time, and end time. New ledgers declare the hash version; legacy
  manual edit schema below version 4 remains readable through its former hash.
- Stable display-page export is publication-critical. A failed page export now
  raises `stable_display_page_export_failed`; the root success manifest is
  published only after that export succeeds, so the GUI cannot report a new
  optimization as complete while its synthesis input is missing or invalid.
- Cached replay of `AI竞赛：中美殊途` loaded the immutable run-local subtitle:
  226 cues and 2,596 words produced a valid display-page SRT and page map. This
  resolves the observed `authoritative_parent_chinese_ledger_mismatch` without
  changing English segmentation, cue timing, translation mapping, or rendering.
- The attempted pause-insensitive `stranded_leading_complement_split` change was
  not retained. It merely moved `most likely, | to manage` to the also-invalid
  `most | likely, to manage`; its contradictory tests and completion claim were
  removed.

## 2026-08-12 Pre-ID Overlong Contract Consistency

- The failed `好莱坞最新热潮：姐弟恋` run had zero final-ledger, timeline,
  or missing-Chinese errors. Its two blocking `overlong_english` entries came
  from conflicting English-boundary decisions.
- `_rebalance_adjacent_pre_id_windows` had removed the valid sentence boundary
  in `... exact dynamic. / Lots of money.` because the three-word right cue
  looked parser-dependent. An over-limit merge now proceeds only when the
  shared structural-overflow check proves that no legal normal-limit split
  exists. Existing genuinely dependent 17-18 word merges remain accepted.
- Final overlong validation previously treated any locally proposed split as
  applicable even when the pre-ID write gate rejected that split in context.
  Validation now supplies the adjacent frozen cues to the same write gate. A
  rejected candidate remains one complete audited structural warning instead
  of becoming a blocking overlong error.
- Read-only replay from the production word ledger and boundary snapshot keeps
  the 15/3-word sentence split, reports zero blocking overlong entries, and
  records 24 structural warnings. Frozen word text/order/times are unchanged;
  no translation, pagination, font, timeline, renderer, or cache contract was
  changed.
- Both production regressions, the complete stable-caption script, Python
  compilation, and all 25 unified regression stages pass. The final unified
  run completed in 368.1 seconds without network, LLM, ASR, synthesis, paid
  requests, or production artifact writes.

## 2026-08-11 Full-Strength First Vocabulary Card

- Removed the article template's 0.25-second title-to-card fade. The render
  cache keys vocabulary state by card identity rather than transition progress,
  so the first partially blended frame could remain visible for the entire
  triggering subtitle and only become fully opaque on the next cue.
- Before the first card, the right panel still shows the episode title. At the
  exact final-page start of the first selected expression, the complete card is
  now drawn immediately and remains stable until a newer card replaces it.
- Selection, final-page alignment, card duration, subtitle highlighting, and
  the rule that the last card remains through the video end are unchanged.
- Two focused first-card tests, Python syntax compilation, and a pixel-level
  trigger-frame comparison pass. The complete 25-stage regression exits zero
  in 380.5 seconds. The checked 1920x1080 trigger frame is
  `tests/caption_audit/out/article-vocab-full-strength-first-card-20260811.png`.

## 2026-08-10 Faster-Whisper Completed-Output Recovery

- Root cause of the new `如何停止拖延` transcription failure: standalone
  Faster-Whisper r245.2 completed all 1099 audio seconds, wrote the SRT, and
  printed its operation-finished marker before crashing in `ucrtbase.dll` with
  Windows status `0xC0000409`. Archived Windows Error Reporting entries show
  the same post-run crash in July. Commit `6bb5ba8` correctly added nonzero-exit
  enforcement but treated this completed-output shutdown failure as if no
  transcript existed.
- Faster-Whisper recovery is now output-contract based rather than exit-code
  specific. A nonzero exit is recoverable only when the process printed both
  `Subtitles are written to` and `Operation finished in:`, the expected SRT
  exists, and the shared `BaseASR` parser, non-empty-data, and timing validation
  all pass. Progress reaching 100%, an output-written marker alone, a missing
  file, or malformed/empty SRT still fails closed.
- Real local replay of `如何停止拖延.m4a` reproduced external exit
  `3221226505` and then returned 3135 validated word segments with
  `native_word_timestamps` and trusted word timing. It made no network, LLM,
  translation, WhisperX, synthesis, or paid request and did not write an ASR
  cache entry.
- The ASR trust contract passes 19 tests. The complete 25-stage regression
  exits zero in 360.1 seconds. The currently open GUI must be restarted before
  rerunning because it loaded the old Python module; the two failed temporary
  outputs were already removed by the prior failure path.

## 2026-08-10 Single-Page Chinese Fit And Numeric Manual Boundaries

- Root cause of the pale-red batch mark: the article page planner treated
  parent Chinese length as a page-count signal but did not prove that a
  selected one-page candidate fit the fixed 46px/two-line Chinese region. A
  later frozen-artifact validator rejected `S0199`, while the failure adapter
  knew only the 39 multipage parent IDs and therefore marked all 39 instead of
  the one failing subtitle.
- A one-page candidate with non-empty Chinese now enters the candidate pool
  only after `_article_fixed_chinese_lines()` succeeds. Frozen-artifact apply
  failures carry their exact parent subtitle ID, and failure normalization may
  resolve that ID against every render plan rather than only multipage
  translation parents.
- Forced fallback ranking now treats a verb/complement split as less desirable
  than a subject/predicate page split. The real `S0199` checkpoint therefore
  uses `down / might` rather than `meant / to` while retaining its parent ID,
  English, word ledger, cue timing, and word timestamps.
- Manual parent and display-page boundary moves now expand a requested word
  count to include the complete numeric phrase. UI preview and confirmation
  show the expanded count before mutation. Sentence-final numbers such as
  `2019. / Right.` remain separate and do not absorb the following sentence.
- Read-only replay of the 199-parent `中国AI为何更省钱？` failure checkpoint
  changes `S0199` from one page to two and narrows a simulated apply failure to
  `S0199`; external requests remain zero. The whole-episode sequence planner
  also changes adjacent `S0198` from four pages to three because the new
  `S0199` first-page pressure changes the existing cross-cue cost. Its parent
  text, ID, word coverage, and cue timing remain unchanged, but the denser
  17/14/19-word projection remains a visual review risk.
- Article readability, page-translation, manual-editor, and 58 publication/UI
  tests pass. The unified regression passes all stages in 374.9 seconds;
  `git diff --check` and production syntax compilation pass. No ASR, LLM,
  network, FFmpeg synthesis, paid request, or production artifact write ran.

## 2026-08-10 Semantic Two-Line Vocabulary Notes

- Root cause: article vocabulary-card concept notes still used the generic
  mixed-text wrapper, which treated Chinese as individual characters. Its
  short-tail rebalance ran only when one line had at most three Chinese
  characters, so `市场变 / 化而消失` remained eligible.
- Concept notes now use a dedicated display-only wrapper. Candidate breaks come
  from the vendored Chinese tokenizer, reject attached punctuation and weak
  line starts, and prefer the boundary after a short explanatory lead-in such
  as `本句用数学隐喻说明`. Notes remain limited to two lines; short notes remain
  on one line.
- The reported note now renders as `本句用数学隐喻说明 / 留学回报的旧有优势已随市场变化而消失。`
  at the existing 26-unit font. No note text, prompt version, cache schema,
  selection, timing, subtitle, manifest, or synthesis contract changed.
- Focused renderer tests pass. A read-only scan of 70 unique cached concept
  notes reports zero third lines, truncation, width overflow, non-token breaks,
  or rejected line starts. The 1920x1080 checked sample is
  `tests/caption_audit/out/article-vocab-semantic-wrap-20260810.png`.
- The unified regression completed 23/25 stages. Its two failures reproduce
  outside this change: one stale English line-layout expectation in stable
  caption smoke tests and one existing 56px expectation in the display-page
  translation contract. Both are outside vocabulary-card rendering.

## 2026-08-10 Multiline Podcast Title Input

- The synthesis page's `模板标题` field is now a two-line plain-text editor.
  Enter inserts a real newline; the field no longer requires users to encode a
  line break inside a one-line control.
- The UI persists the exact plain text, including internal newlines, to
  `PodcastTemplateTitle`. `TaskFactory` freezes that same value in
  `SynthesisConfig.podcast_template_title`, and the renderer's existing title
  wrapper treats each explicit line as a fixed boundary.
- No additional config field, cache key, output-name rule, subtitle field, or
  rendering contract was added. Automatic lexical title wrapping remains the
  fallback when the user enters a single line.
- The focused UI/task snapshot test and complete video-synthesis safety script
  pass. The unified regression passes all 25 stages in 412 seconds. A rendered
  1280x720 synthesis-page sample is at
  `tests/caption_audit/out/synthesis-multiline-title-input-20260810.png`.

## 2026-08-10 Article Card Page Timing And Title Wrapping

- Root cause of early cards: article cues may be divided into several final
  display pages, while the vocabulary scheduler used only the parent cue start.
  A phrase on page two or three therefore appeared while an earlier page was
  still visible.
- Article-template scheduling now resolves each exact source phrase against the
  final frozen page plan and starts the card at the page that contains it. A
  phrase split across pages or without one unique page is omitted. The dark
  podcast template retains parent-cue timing.
- Root cause of the broken title was the generic width-first character wrapper.
  The title panel now uses the vendored deterministic Chinese tokenizer plus
  punctuation boundaries, selects a balanced legal break, and preserves an
  explicit newline. `中国年轻人为何不爱留学了？` renders as
  `中国年轻人为何 / 不爱留学了？`.
- Chinese opening titles use the bundled `ChillYunmoGothicHeavy.otf`, one step
  heavier than the previous Bold face. Font sizing and the three-line panel
  safety limit remain unchanged.
- No vocabulary prompt, cache schema, card selection, ASR, subtitle boundary,
  translation, fixed ID, cue timeline, SRT/ASS, manifest, or synthesis-entry
  contract changed.
- Focused timing and title tests pass; `tests/test_stable_caption_rules.py`
  passes in 96.3 seconds; the unified regression passes all 25 stages in 395.1
  seconds. Visual evidence is in
  `tests/caption_audit/out/article-vocab-page-alignment-after-20260810.png` and
  `tests/caption_audit/out/study-abroad-title-wrap-heavy-20260810.png`.

## 2026-08-09 Recoverable Display-Page Translation Failure

- Root cause: article-assisted fuzzy correction could select a window such as
  `Like, Peking University` or `President Donald` even when the complete
  canonical entity already existed inside or immediately beside that window.
  Replacing the whole window deleted the discourse word or title.
- A local source-span guard now rejects only non-expanding fuzzy candidates
  that overlap an already complete canonical span. Legitimate spelling and
  phonetic corrections, including three cached `Higee/Higgies -> haigui`
  replacements, retain their existing thresholds and time envelopes.
- Root cause of the editor fallback: one invalid page-Chinese token boundary
  returned an `ERROR` artifact with empty `parents` and no `render_plans`.
  The existing editable-checkpoint path therefore had only parent subtitles to
  show even though deterministic English pagination had succeeded.
- Error artifacts now retain every frozen render plan and every independently
  valid page-Chinese parent. Invalid parents contribute no authoritative page
  Chinese; their real English pages remain visible, blank, and explicitly
  marked for manual review. Formal publication and synthesis remain blocked.
- The real 19:54 study-abroad checkpoint was replayed read-only: 262 frozen
  parents produce 303 actual pages across 36 multipage parents. `S0001` exposes
  all three English pages with blank Chinese and review markers. Article replay
  preserves `Like, Peking University` and `President Donald Trump` while still
  correcting all three `haigui` variants. No network, ASR, LLM, FFmpeg, or
  source-artifact write occurred.
- Article correction passes 30/30, the complete page-translation contract and
  manual-final editor scripts pass, and production-file syntax compilation
  passes. Unified regression completes all 25 stages in 342.9 seconds and
  `git diff --check` exits zero with line-ending notices only.

## 2026-08-09 Cached Article Evidence Handoff

- Root cause: article analysis returned a normalized in-memory context, while
  `save_article_artifacts()` enriched only a separate copy with
  `canonical_in_article`, source evidence, and supported aliases. The saved
  `article_context.json` therefore looked correct, but ASR correction and the
  translation glossary still received the unenriched object. In the observed
  run, article correction executed without resume, produced 299 review
  candidates, applied zero replacements, and left `Higee` in the word ledger.
- `SubtitleThread._resolve_article_context()` now enriches the resolved context
  before it is saved or passed downstream. This applies equally to fresh LLM
  analysis, analysis-cache hits, and matching context supplied by the UI. It
  does not invalidate or delete the article cache.
- The contract is category-generic: article-evidenced people, companies,
  organisations, places, works, brands, and eligible domain terms share the
  same evidence-bearing object for English ASR correction and Chinese
  terminology prompting. Existing high-confidence, article-scope, and grammar
  gates remain unchanged; this is not a sample-specific replacement rule.
- The cross-stage regression corrects cached `Li Yang Wenfing` to
  `Liang Wenfeng` and `Higee` to `haigui`, preserves their source time
  envelopes, and verifies `Liang Wenfeng -> 梁文锋` plus `haigui -> 海归` in the
  translation context. Task-context tests pass 6/6 and article-correction tests
  pass 29/29. The unified regression passes all 25 stages in 362.3 seconds.
  No network, ASR model, LLM, real FFmpeg encoding, or paid request ran.

## 2026-08-09 Complete Vocabulary Plan Render Gate

- Root cause: resumable v2 progress correctly distinguished complete and
  incomplete request chunks, but `load_or_generate_vocab_plan()` still returned
  legacy plus partial candidates after the 240-second global budget or a failed
  batch. The renderer then treated that partial plan as final and started
  FFmpeg; a production episode therefore encoded with only `5/9` chunks.
- Smart vocabulary rendering now requires every current chunk to complete before
  the plan is returned. The global 240-second early-stop budget is removed;
  requests remain sequential with a 90-second per-attempt timeout, no SDK
  retry, and two explicit attempts. Successful empty arrays remain valid
  completed chunks and do not force ordinary words into the episode.
- A failed chunk, incomplete cache without a configured model, or unexpected
  generation error raises `VocabularyPlanIncompleteError`. All completed chunks
  are atomically retained, the next attempt requests only missing chunks, and
  no legacy or partial plan can authorize FFmpeg. A complete zero-card result
  remains renderable.
- All 29 focused vocabulary/cache/display tests and syntax compilation pass;
  six of those tests directly cover completion, resume, and the render gate.
  The full 25-stage regression ran for 365.6 seconds: all stages except `stable
  caption smoke tests` passed, and the vocabulary smoke plus video-synthesis
  safety stages passed. Its sole failure was the unrelated
  `test_whisperx_time_only_uses_explicit_source_audio_from_complete_task` order-
  dependent assertion; that test passed immediately in isolation.
- A fresh 1920x1080 real-data frame was generated from `中国AI为何更省钱？` and
  visually checked for clipping, overlap, blank regions, card highlight, and
  bilingual subtitle placement:
  `tests/caption_audit/out/vocab-complete-gate-sample-20260809.png`. No external
  model, ASR, FFmpeg, or paid request ran for this change.

## 2026-08-09 Manual Page Review Acknowledgement

- Root cause: recovered page Chinese and REVIEW page boundaries were shown as
  warnings, but the editor had no durable user acknowledgement for the exact
  page identity. A translation-blocked checkpoint also discarded its frozen
  page geometry during save and could silently replan a three-page cue as four
  pages.
- Editing non-empty page Chinese now confirms that exact page Chinese. Moving a
  page boundary confirms the newly chosen boundary. The actual-page context
  menu also exposes `confirm current Chinese`, `confirm current page boundary`,
  and `confirm all non-blocking reviews`.
- Chinese and boundary acknowledgements are stored with page ID, parent ID,
  English word range, and frozen English. A changed word range or rebuilt page
  identity invalidates the old acknowledgement. HARD structure errors cannot
  be acknowledged away.
- Unconfirmed page Chinese and REVIEW boundaries remain formal-publication
  warnings, not structural corruption. A hash-bound manual draft may still be
  synthesized when its fixed IDs, English, word ledger, timeline, page plan,
  and media ownership are valid.
- Saving a strict manual checkpoint now reuses its hash-bound PASS, REVIEW, or
  translation-blocked frozen page plan. Chinese review state no longer grants
  the automatic planner authority to replace the saved page count or ranges.
- Real isolated replay of the current study-abroad package changed 79 Chinese
  and 20 boundary reviews with zero HARD items to 0/0/0 after explicit bulk
  acknowledgement. Formal publication then passed with all 261 fixed cue
  identities/times and all 2,862 ledger words unchanged. Evidence is under
  `E:\VideoCaptioner-e2e-runs\manual-review-confirmation-postcheck-20260809`;
  the desktop source package and audio hashes remained unchanged.
- Focused confirmation tests pass 6/6, the manual editor passes 50/50, stable
  publication passes 51/51, video-synthesis safety passes, and the unified
  regression passes all 25/25 stages (653 test items) in 403.562 seconds.
  `git diff --check` passes. No network, ASR, LLM, or real video synthesis ran.

## 2026-08-09 Manual Editor Command Surface Audit

- Root cause: loading a manual-final session exposed its editing actions without
  hiding the ordinary reprocessing controls. Generic table export, subtitle
  layout/translation settings, and `Start` therefore competed with the
  authoritative manual-final save and could send the user into the wrong flow.
- Manual-final mode now presents one command set: next review, parent/actual-page
  view or refresh, manual-final save, undo, and the mutually exclusive formal or
  draft synthesis action. `File` retains only import and open-current-package.
  Ordinary save, layout, translation, language, compatibility correction,
  prompt, settings, and start return when no stable manual session is available.
- Removed the unreachable detached boundary panel, the duplicate command-bar
  boundary action, the old dialog-based right-click word moves, the never-shown
  quality-report action, and the disabled single-row merge command. The inline
  highlighted word-count/confirm workflow remains the only boundary UI.
- `Open manual-final folder` now resolves a loaded manifest or manual subtitle
  even when the user imported the SRT directly and no `SubtitleTask` exists.
- This changes only editor command visibility and file navigation. Frozen
  English, Chinese ownership, subtitle IDs, word timing, page planning,
  publication gates, and synthesis authority are unchanged.
- Stable-publication/UI tests pass 46/46, the manual-final editor script passes
  45/45, video-synthesis safety passes, and the unified regression completes
  all 25/25 stages with no `Regression failed` entry. `git diff --check` passes.
  A separate hidden-widget probe timed out and is not counted as visual
  acceptance; no network, ASR, LLM, FFmpeg, synthesis, or paid request ran for
  this audit.

## 2026-08-09 Manual Editor State Ownership Audit

- Root cause: the editor mixed the live table draft, pending display-page edits,
  and the last published manual package. An active Qt delegate could be rebuilt
  before committing its Chinese text, page edits were partly cleared without
  their boundary overrides, and stale artifact review rows remained active
  after the user changed the corresponding subtitle.
- The editor now has one in-memory mutable session fingerprint. Chinese edits,
  repeated two/three/four-page splits, and page-boundary moves update only that
  session. They do not invoke `save_to_source_folder`; the user performs one
  explicit background save after finishing the batch of edits.
- Split, boundary, save, ordinary export, import-discard, and close checks first
  commit the active table delegate. Parent rows are written back by fixed cue
  ID plus frozen word range and time, never by an unchecked row number.
- Display-page edits and boundary overrides invalidate and undo atomically.
  Parent Chinese edits are undoable without deleting an otherwise current page
  plan. Incomplete page Chinese may be saved as a blocked checkpoint, but it
  cannot authorize formal synthesis.
- Manual package override schema 3 binds the edit artifact SHA-256. Reload also
  cross-checks the embedded ledger against the package word ledger before the
  session becomes editable.
- Review navigation now combines unchanged artifact evidence with current
  manual state. Editing one subtitle filters only that subtitle's stale marks;
  manual Chinese review, REVIEW page boundaries, and unavailable pages remain
  visible in table colors, tooltips, and `next review`. A late asynchronous
  artifact result cannot restore invalidated IDs or replace an unsaved status.
- The real desktop study-abroad package was replayed read-only: 303/303 English
  pages were visible, including 20 REVIEW boundaries. Filling one page Chinese
  and splitting a second parent retained the first edit and made zero save
  calls. All 11 source-package size, mtime, and SHA-256 records were unchanged.
- Manual-final editor tests pass 36/36, stable-publication UI tests pass 43/43,
  video-synthesis safety passes 24/24, and the unified regression passes
  678/678 plus its syntax step in 335.161 seconds. `git diff --check` passes.
- Windows QPA plus `WA_DontShowOnScreen` constructed and processed the real
  editor widget successfully. Strict offscreen QPA remained blocked at
  `QApplication` initialization, and the bounded widget-grab attempt produced
  no screenshot; no visual screenshot acceptance is claimed. No network, ASR,
  LLM, FFmpeg, synthesis, or paid request ran.

## 2026-08-09 Manual Boundary Evidence Recovery

- Root cause: manual-final save validated only boundaries inside the current
  parent cues, then wrote that filtered subset back as the package evidence.
  A later parent-boundary move or full undo could turn a previously omitted
  cue edge into an internal page candidate and fail with
  `manual_page_boundary_evidence_required`.
- Manual packages now retain every adjacent boundary in the authoritative word
  ledger. Older filtered packages recover only boundaries proven by current or
  historical frozen cue edges; recovered edges remain REVIEW evidence. A
  missing arbitrary internal boundary still fails closed.
- Parent rows expose the existing two/three/four-page commands even while their
  old page plan is stale. Selecting one queues exactly one background refresh
  and applies the requested split once the matching saved package reloads.
  Display-page boundary moves remain immediate and require no refresh.
- The real desktop `中国年轻人为何不爱留学了？` package was verified read-only:
  undoing all history restored 2,861/2,861 boundary records, including recovered
  word ID 210, and the package tree hashes did not change. A temporary-copy
  save/reload retained 2,861/2,861 records.
- Focused manual-final and pending-split regressions pass. Unified regression
  passes 603 tests across 24 suites plus one syntax step in 332.064 seconds;
  `git diff --check` and production-file syntax checks pass. No network, ASR,
  LLM, synthesis, or paid request ran.

## 2026-08-09 Stable Word-Count Preview and Review UI

- Root cause: the inline word-count `valueChanged` signal rebuilt both index
  widgets. Increasing or decreasing the count therefore destroyed the active
  SpinBox and appeared to cancel boundary editing.
- Count changes now update the existing English highlights, direction capacity,
  and `confirm move N words` text in place. The same SpinBox and both row widgets
  remain active; no subtitle data changes before explicit confirmation.
- The redundant `quality report` toolbar action is hidden. Coverage artifacts,
  deterministic publication gates, table colors, tooltips, and `next review`
  navigation remain available and unchanged.
- Stable publication tests pass 24/24. Qt DPR 1.0/1.25/1.5 validation passes
  411/411 checks across 18 reviewed PNGs; repeated `1 -> 2 -> 3 -> 2` count
  changes retain widget identity with no clipping, overlap, or stale controls.
- Unified regression passes 595 tests across 24 suites plus one syntax check
  with zero failures in 337.197 seconds. `git diff --check` passes with only
  line-ending notices. No network, ASR, LLM, synthesis, or paid request ran.

## 2026-08-09 Manual Page Intermediate State

- Root cause: page-boundary editing treated grammar risk, the 900ms reading
  policy, missing page Chinese, and structural corruption as one failure. A
  newly split page therefore could not be adjusted until Chinese was filled,
  and every renderer rejection appeared as the same generic error.
- Explicit manual page movement now permits grammar-risk and sub-900ms choices
  as REVIEW evidence. Automatic planning keeps the strict behavior. Empty
  pages, non-contiguous word ownership, ID drift, an illegal word-time boundary,
  and fixed-font overflow remain hard failures.
- Page Chinese may remain empty while the user continues to adjust boundaries.
  The affected page Chinese is cleared whenever its English word ownership
  changes. Formal publication still fails with
  `manual_page_translation_required` until all page Chinese is complete.
- Repeated boundary moves use the currently confirmed page ranges as their
  baseline, including a manual 2/3/4-page split. A blocked save retains the
  hash-bound English page plan, so reopening the checkpoint keeps those pages.
- The selected row exposes upper and lower boundary entries. Direction changes
  reset the count to one word, count changes update the highlight, and only the
  confirmation action mutates the session. A compact legend identifies English,
  Chinese, timing, visual-page, and blocker review colors.
- Parent-boundary edits expose an enabled `refresh actual pages` action. It runs
  the existing page preflight and checkpoint save in the background; subsequent
  unchanged saves reuse the frozen result.
- Manual-final editor tests pass 25/25 and stable publication tests pass 23/23.
  Unified regression passes 594 tests across 24 suites plus one syntax check
  with zero failures in 335.056 seconds; `git diff --check` passes with only
  line-ending notices.
- The first intermediate-state UI run exposed stale Qt index widgets covering
  rows after a parent-model refresh. The editor now keeps direct widget
  references and hides them synchronously before detaching and deleting them.
- Final qwindows evidence under
  `E:\VideoCaptioner-e2e-runs\manual-page-intermediate-editor-20260809`
  passes 510/510 checks across DPR 1.0, 1.25, and 1.5. All 18 PNGs were
  reviewed; stale controls, clipping, and overlap are zero. No network, ASR,
  LLM, video synthesis, or paid request ran.

## 2026-08-08 Parent-Boundary Inspector and Stale-Page Safety

- Root cause: parent-boundary editing reused the compact four-column subtitle
  table and hid word movement behind a row context menu plus numeric dialog.
  The user could not see both complete neighboring cues while deciding which
  word owned the boundary.
- Parent mode now uses a vertical splitter with an inline boundary inspector.
  Selecting a parent row shows the complete English and Chinese for the cue on
  each side of the boundary, their IDs and times, highlights the candidate head
  and tail words, and exposes a bounded word-count stepper with direct left and
  right movement commands. The existing word-ledger-backed movement methods
  remain the only mutation owner.
- Undo is permanently visible inside the inspector. Every move and merge keeps
  the existing session history; boundary undo restores the prior cues while
  still requiring another save before synthesis. Page-Chinese undo remains in
  page view and does not incorrectly jump to a parent boundary.
- Any parent boundary, merge, or parent-row text change invalidates the old
  whole-episode display plan. The editor immediately returns to parent mode,
  labels actual pages as waiting for refresh, and disables formal and draft
  synthesis. Saving the manual final runs the existing background page
  preflight; only the reloaded saved package can expose the new actual pages
  and synthesis actions.
- This is an editor-state and interaction change only. It does not alter frozen
  subtitle IDs, ledger words or times, English segmentation, Chinese allocation,
  page-planning rules, font rules, or rendering.
- Focused publication/editor tests pass 13/13. The page-translation contract
  passes 35/35. Unified regression passes 25/25 in 310.535 seconds and
  `git diff --check` passes. A 1400x850 qwindows render of the real inspector is
  under `E:\VideoCaptioner-e2e-runs\manual-boundary-inspector-20260808` and has
  no clipped or overlapping text or controls. The runtime has no Qt offscreen
  plugin, so the visual smoke used the production qwindows platform with a
  hidden window.

## 2026-08-08 Article Page Contract v16 and Frozen-Plan Authority

- Root cause: the whole-episode sequence planner produced a validated frozen
  page plan, but the renderer later invoked the per-cue planner again. The
  replacement spans and font could no longer match the page-ID-bound Chinese,
  which caused `missing_or_invalid_display_page_translations` even though the
  complete page artifact was valid.
- `article-fixed-font-pages-v16` makes every validated `frozen_*` plan
  renderer-authoritative. Rendering, editor preview, and manual-final save
  consume the same page IDs, word spans, times, line layout, and font; no
  downstream per-cue replanning is allowed.
- The whole-episode planner compares feasible cue-local plans while penalizing
  adjacent dense pages. It retains the 56/54/52/50px English sequence, allows
  three English lines only at 50px after two-line plans fail, and treats
  medium-risk boundaries as scored review evidence instead of an absolute
  rejection. Frozen parent IDs, English, word ownership, and cue timing do not
  change.
- Page Chinese is reusable only when ordered page text reconstructs the
  current parent Chinese exactly. An older artifact whose English page
  identity still matches cannot be reused after parent-level Chinese polish.
  Manual-final recovery exposes valid pages from a blocked artifact and marks
  failed parents for review; it never proportionally slices Chinese.
- A zero-network replay of the existing `中国年轻人为何不爱留学了？`
  checkpoint published a PASS package under
  `E:\VideoCaptioner-e2e-runs\study-abroad-page-contract-v16-final-r1-20260808`:
  261 frozen parents, 2,862 ledger words, 303 display pages, and 37 multipage
  parents. Page counts are 224x1, 33x2, 3x3, and 1x4; font counts are
  56px=277, 54px=1, 52px=7, and 50px=18. Eight 50px pages use the controlled
  three-line fallback. `render_blocked=false` and the display artifact is
  `PASS`.
- Offline validation reused 907 existing PNGs: 303 page midpoints and 604
  before/after transition frames. Parent coverage is 261/261, page and
  transition errors are zero, and no blank, crop, bilingual overlap, or
  page-induced flash was found. Fifteen sub-900ms items are inherited
  single-page source cues and remain warnings rather than pagination errors.
- Seven parents (`S0118`, `S0158`, `S0196`, `S0214`, `S0238`, `S0240`, and
  `S0247`) retain low-confidence Chinese page semantics because natural
  Chinese word order crosses an English page boundary. Their page text is
  token-safe and aggregates exactly, but editor review is still recommended.
- Stable caption smoke tests pass 377/377. Unified regression passes 25/25 in
  313.799 seconds. The replay and validation made zero ASR, LLM, FFmpeg,
  synthesis, or paid external requests; no complete video was generated.

## 2026-08-08 Flat Actual-Page Editing and Source Exports

- Root cause: the editor kept one parent cue per row and repeated only a page
  count in a separate `actual pages` column. That column did not expose the
  final page text or timing where users already edit subtitles, so it consumed
  table width without making the rendered sequence directly editable.
- When a complete frozen page artifact exists, the default editor model is now
  flat: one visible table row is one real rendered page. The table remains the
  original four columns (start, end, English, Chinese); the repeated page-count
  column has been removed. Each row still carries its hidden deterministic page
  ID, parent subtitle ID, continuous word range, page time, and selected font
  size.
- Page English is read-only because it is derived from the frozen word range.
  Page Chinese is directly editable. `查看父字幕` retains the original
  word-ledger-backed view for formal English boundary work.
- Saving from page view validates page identity, parent ownership, word ranges,
  and times. A no-op save or Chinese-only page edit reuses the same hash-bound
  page artifact and does not invoke the planner again. Any page drift blocks
  publication instead of silently changing the previewed pagination.
- Stable publication and manual-final save write
  `<media-stem>-实际分页双语字幕.srt` and
  `<media-stem>-实际分页映射.json` beside the original source audio. The map
  preserves the parent/page relationship, so importing an authoritative page
  SRT can recover the frozen package rather than treating pages as new fixed
  subtitle IDs.
- Focused manual-editor and publication tests pass. Unified regression passes
  25/25 in 494.303 seconds, and the final documentation-only
  `git diff --check` passes. No ASR, LLM, FFmpeg, video synthesis, or paid
  external request ran for this change.

## 2026-08-07 Article Correction Span Ownership and Complete QA Queue

- Root cause: fuzzy multi-token entity matching could collapse two ASR tokens
  into one glossary token even when one source token contributed no matched
  character. The real `.S., Japan, -> Japan,` candidate therefore consumed the
  `S.` portion of `U.S.` despite a failed entity/grammar gate.
- Every source token in a collapsed entity window must now contribute to the
  canonical match. Lossless forms such as `A Drift -> Adrift` remain eligible,
  but a failed entity gate can no longer be bypassed by downstream similarity.
- The human QA SRT/JSON queue now retains every distinct `BLOCKER` and `REVIEW`
  item produced by the existing classifier. The former default total cap of 12
  is removed; `INFO` evidence remains outside the playable queue and duplicate
  code/ID entries remain collapsed.
- A read-only rebuild of the v10 artifacts finds 51 timed `REVIEW` items and
  zero omitted items. The existing on-disk queue still contains the old 12/22
  metadata because validation deliberately did not overwrite that E2E run.
- English segmentation, word limits, fixed subtitle IDs, Chinese allocation,
  display pagination, timing, and rendering are unchanged. Focused article
  correction and QA queue scripts, unified regression, and `git diff --check`
  pass. The real v10 deletion candidate is rejected as
  `candidate_would_delete_non_entity_token`.

## 2026-08-07 Article Page Contract v10 and Frozen-Contract E2E

- Root cause: eight real 203-cue checkpoint items had no strict 50px-or-larger
  page partition because every otherwise feasible transition carried a
  cue-level syntax warning. Blocking all of them made the full result unusable;
  weakening those warnings globally would have permitted unrelated bad cuts.
- `article-fixed-font-pages-v10` still exhausts strict 56/54/52/50px layouts
  first, then permits only a complete visible continuation phrase/clause as a
  high-risk reviewed fallback. It supports up to four pages, preserves atomic
  lexical protections and the 900ms minimum, and never changes the frozen
  parent ID, English, word range, cue time, or word ledger.
- The selected fallback risk now survives dynamic-program reconstruction.
  Layout/score memoization reduced the eight hardest fixture plans from about
  142 seconds to 71.631 seconds. All 203 frozen render plans and the complete
  global display-boundary evidence are published and SHA-bound for manual save.
- Manual-final export now writes both `人工终稿分页双语字幕.srt` and its exact
  page map. Invalid page Chinese saves a render-blocked checkpoint instead of
  crashing or silently slicing Chinese characters.
- Fresh E2E output is under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-page-contract-v10-e2e-20260807-r1`.
  It has 203 fixed parent IDs, 2,548 words, 252 display pages, 49 transitions,
  38 multipage parents, a 50px minimum font, and a 1,051ms minimum timed page.
  Final timing is `PASS` under `whisperx-time-only`, with no missing source
  audio or overall backend fallback. The run made 15 external requests: 14
  full/fixed-ID translation requests and one page-translation request.
- The prior 16:36 checkpoint is not a valid byte-for-byte source-ledger
  baseline: despite sharing the input SRT, it omitted or rewrote four source
  words around `of/an/by/of American`, causing cascading word-index drift. The
  current run retains those source words and passes its frozen ID-addressable
  contracts; the E2E runner's old-checkpoint equality assertion was therefore
  rejected rather than weakened.
- Independent export validation passed 252/252 SRT/map pages, all 2,548 word
  IDs, page continuity/envelopes, Chinese token boundaries, artifact hashes,
  and 47 rendered midpoint/transition frames with zero blank, crop, or bilingual
  overlap failures. Nine reviewed English page boundaries and one non-blocking
  S0202 Chinese continuation remain explicit review items.
- Focused page/manual suites, unified regression, and `git diff --check` pass.
  The comparison SRT and validation report are below `editor-comparison/` in
  the E2E directory. No video was synthesized for v10.

## 2026-08-07 Non-Blocking Manual-Final Save

- Root cause: `save_manual_final_output()` called the complete deterministic
  article page preflight synchronously on the Qt GUI thread. A real 203-cue
  blocked checkpoint spent 188.384 seconds in page-blueprint construction,
  so Windows correctly reported the application as not responding even though
  the package eventually saved.
- Saving now snapshots the complete manual session and runs package generation
  on a background worker. The subtitle table, save, undo, and synthesis actions
  are disabled until that exact snapshot completes; completion returns to the
  GUI through a Qt signal. Duplicate save clicks cannot start a second writer,
  concurrent session saves are serialized, and the main window refuses to exit
  until the active package publication finishes.
- English, Chinese, fixed IDs, word ownership, timing, page planning, render
  gates, and package schemas are unchanged. A blocked package remains blocked.
- Focused publication regression passes. Delegated real-checkpoint profiling
  completed normally in 188.806 seconds with zero network, ASR, LLM, or FFmpeg
  calls and no production-source modification. The remaining performance cost
  is 690,471 font-width measurements; the fix restores responsiveness but does
  not claim faster planning.
- Evidence is under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-manual-save-profile-20260807-r2`.

## 2026-08-07 Article Page Contract v9 and Cache-First Subtitle E2E

- Root cause: candidate plans were ranked by visual cost before structural
  confidence. A medium/high-risk page turn at 56px could therefore beat a
  readable 50px static page, while treating every uncertain boundary as hard
  would over-shrink ordinary long cues.
- The planner now compares all feasible 56/54/52/50px and one-to-three-page
  plans with categorical priority: high-confidence structural risk, then
  medium-confidence review risk, then measured readability/visual cost, then
  low-confidence hints and font/page tie-breakers. Hard lexical dependencies
  remain ineligible. Frozen English, parent IDs, word ownership, cue timing,
  parent Chinese, SRT, and ASS are unchanged.
- The page contract is `article-fixed-font-pages-v9`. Only page planning and
  page-translation caches are invalidated; unchanged ASR artifacts, complete
  translations, and fixed-ID Chinese allocation retain independent cache
  identities.
- Offline replay planned 259/259 `China AI Why Cheaper?` cues and 207/207
  `How to Identify AI Writing Style` cues with zero structural failures and
  zero external requests. The runs changed 302 -> 299 / 43 -> 40 pages and
  transitions for the first sample, and 236 -> 232 / 29 -> 25 for the second.
- Delegated representative validation rendered 10 China and four AI-writing
  v9 page/transition frames. Word loss/duplication, hard boundaries, crop,
  bilingual overlap, font below 50px, page below 900ms, and transition
  failures were all zero. One offline China page used token-safe preview
  Chinese and was layout evidence only, not a production translation claim.
- Cache-first subtitle E2E reused the verified ASR SRT for the same source
  audio and reran current English boundaries, fixed-ID writeback, local
  WhisperX, page planning, and publication. It completed with 207 cues and
  1,993 ledger words; final timing is `PASS` under
  `whisperx-time-only`, with no `source_audio_missing` or overall backend
  fallback. Three local expansion/compression protections remain recorded.
- All 12 full-translation batches, two normal allocation batches, and three
  fragment retries were cache hits. Page contract v9 required one external
  page-translation request, which is now cached. The published artifact is
  `PASS`, contains 233 pages / 26 transitions, and has one non-blocking
  `unnatural_chinese_fragment` review at S0082.
- Evidence is under
  `E:\VideoCaptioner-e2e-runs\ai-writing-style-page-contract-v9-e2e-20260807-r1`.
  Pre-synthesis production-artifact validation passed for all 207 IDs, 1,993
  words, 233 pages, and 26 transitions. Seventeen representative page and
  transition frames had zero crop, overlap, blank, font-floor, content, or
  transition failures.
- Final synthesis consumed the hash-bound stable manifest and the original
  source audio directly, with unrelated AI vocabulary cards disabled. It made
  zero external requests and produced `final-video.mp4` (30,157,031 bytes) in
  about 6 minutes 49 seconds.
- The actual MP4 fully decoded 16,684 frames over 667.341497 seconds with zero
  decode errors, duplicate frames, or dropped frames. Validation extracted
  291 unique frames covering all 233 page midpoints, both sides of all 26
  transitions, the 64.8/65.6/66.5-second timing probes, and S0082. Crop,
  bilingual overlap, blank subtitle, wrong-page/content, transition,
  word-envelope, and alignment-probe failures were all zero. The report is at
  `video-validation-v9\video-validation-report.json` below the run directory.
- S0082 remains a non-blocking language-quality review: its page transition is
  mechanically correct, but P01 closes Chinese with a full stop while the
  English continues after a comma, and P02 is understandable but slightly
  stiff. This was reported rather than hidden by another automatic rewrite.

## 2026-08-06 WhisperX Expansion-Sensitive Timing Acceptance Gate

- Root cause: compact written tokens such as numerals, currency values, years,
  and acronyms can represent several spoken words. WhisperX documents that
  numeral/currency forms may be absent from the alignment-model dictionary.
  A matched compact token could therefore receive only a fraction of its
  spoken duration and pull later matched words forward until the next reliable
  acoustic anchor.
- Final `whisperx-time-only` mapping now rejects only a local update run when
  an expansion-sensitive token is severely compressed relative to the frozen
  stable-ts ledger. The run keeps baseline word times until WhisperX drift
  returns to the pre-trigger anchor. The recovery word and every unrelated
  WhisperX update remain unchanged; the local search is bounded to 24 words.
- Each rejected run is recorded as
  `whisperx_expansion_compression_fallback` with trigger word ID, affected word
  IDs, baseline range, and rejected WhisperX range. This is a local word-time
  fallback under `applied_backend=whisperx-time-only`, not an overall backend
  fallback.
- The gate is disabled for the experimental full-WhisperX path, so it cannot
  alter pre-ID English segmentation. English text/order, frozen subtitle IDs,
  word ownership, Chinese allocation, visual pagination, and render style are
  unchanged.
- Regression uses the exact production drift shape: `53` through `2028` retain
  their frozen `412.600-417.020s` span, while recovered `Now` keeps its
  WhisperX `417.580-417.720s` timing. Unified regression and
  `git diff --check` pass; no ASR/LLM request or video synthesis was run.

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
  density is about one card per minute, capped at 22; low-priority candidates
  and duplicate words are not rendered. Eligible candidates are first selected
  across equal timeline strata, then any remaining budget is filled by priority
  and distance. Empty strata do not admit basic words merely to meet the target.
  A card starts with the subtitle that contains its word, not at the start of the
  earlier semantic group.
- Smart vocabulary cards preserve the selected expression exactly as it appears
  in its triggering subtitle. The regular card shows only that expression and
  one compact Chinese contextual gloss. A concept card may add one short
  Chinese explanation for a non-transparent technical, cultural, or economic
  concept; the plan caps such expanded cards at three per episode.
- Vocabulary cards omit phonetics, part-of-speech labels, exam labels, English
  dictionary definitions, and `IN CONTEXT` blocks. A new card uses the full
  learning panel from its triggering subtitle until a newer card replaces it.
  The last full card remains in place for the rest of the rendered video.
- Before the first vocabulary card, the article template keeps the right panel
  occupied with the episode title rather than a vocabulary preview. It requires
  no vocabulary-model output. The first complete card replaces the title at its
  triggering page start; the container remains fixed and no partially blended
  state is cached across the subtitle.
- When a vocabulary expression is highlighted in an English subtitle, directly
  attached punctuation and closing quotation marks or brackets use the same
  highlight color; following whitespace and text remain unhighlighted.
- Regression smoke tests exist in `tests/test_stable_caption_rules.py`.
- Generated subtitle audits exist in `tests/audit_stable_outputs.py`.
- A single regression entry exists: `runtime\python.exe scripts\run_regression.py`.
- Stable runs now write a time-addressable `字幕质检队列.srt` beside the source
  audio. It is built from the current coverage report's sibling artifact
  directory, contains every distinct `BLOCKER` and `REVIEW` item, and preserves
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

## 2026-08-06 Readability and Manual-Final Checkpoint

- Article English now defaults to 56px. The renderer treats 16 words as a soft
  page budget, so a pixel-fitting, grammatically safer page is not rejected
  merely for exceeding a word count. When no safe 56px layout exists, the
  controlled 54/52/50px fallback sequence is available and its use is
  recorded in the render plan.
- Manual review marks now come from existing stable audit artifacts and retain
  only actionable high-confidence English, Chinese, timing-edge, and visual
  boundary issues. The editor does not rerun a second parser when a completed
  English boundary audit already exists.
- Saving from the editor creates a separate `人工终稿字幕包/` with a bilingual
  SRT, exact word ledger, final cue timeline, page translations, edit history,
  source-media path, and SHA-256 manifest. The original stable package remains
  unchanged.
- A verified package can be selected or dragged into the synthesis page. The
  source audio is filled automatically when its recorded path still exists;
  synthesis then consumes the package directly without rerunning ASR,
  translation, or visual planning. A package with unresolved page-level Chinese
  ownership is saved as an editable checkpoint but remains render-blocked.
- Focused manual-package and synthesis-safety regressions pass. No external
  ASR/LLM request or video synthesis has been run.
- The page planner contract is now `article-fixed-font-pages-v7`. Verified
  clause-level pauses of at least 600ms may convert a subject/predicate or
  `that` + `-ing` visual boundary from hard failure to high-confidence review;
  lexical dependencies remain hard. The real 28-word `S0120` regression now
  plans successfully without changing its frozen parent cue or shrinking below
  the configured fallback sequence.
- Offline replay of the 262-cue `中国AI为何更省钱？` stable artifact now plans
  262/262 cues with zero structural failures. The English font distribution is
  56px=247, 54px=2, 52px=8, and 50px=5; the renderer never selects 48px or
  46px. Nineteen pages exceed the 16-word soft budget because a shorter
  partition would be worse. All 10 previously known bad visual cuts are absent.
- `S0120` uses three 56px pages at its real comma/coordinator boundary and
  800ms `gear | is` pause. Its parent ID, 28 English words, Chinese mapping,
  cue time, and word ledger remain unchanged.
- The v6 audit under `...page-contract-r10-offline-audit` is superseded because
  it still allowed 48px and 46px. The final v7 audit and 29 representative
  frames are under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r11-offline-audit`.
  All frames are 1920x1080 and nonblank, with zero crop, bilingual overlap,
  page-time mismatch, or transition failure. Every paginated page lasts at
  least 1351ms.
- Four high-risk and twelve medium-risk semantic page boundaries remain review
  candidates in the editor; they are not structural failures and are not
  hidden by font shrinking. Stable caption tests, unified regression, and
  `git diff --check` pass. This offline validation made zero network, ASR, LLM,
  FFmpeg, or paid external requests.

## 2026-08-07 Article Page Contract v8 and Fresh E2E

- The article planner contract is now `article-fixed-font-pages-v8`. It uses a
  1260px comfortable English line width and retains 1455/1498px only as
  controlled fit profiles. Page selection balances measured pixels, spoken
  duration, word load, and short-page cost while preserving the 56/54/52/50px
  font floor and the frozen cue contract.
- Renderer page boundaries consume the pre-ID syntax evidence by confidence.
  Atomic lexical dependencies remain hard; clause-level review evidence is a
  cost, not an unconditional merge or split. Parser-supported `-ing/-ed`
  complements are hard only when their measured pause is at most 200ms. The
  regression distinguishes a 40/160ms attachment from a 400ms audible pause.
- Page-level Chinese validation shares the vendored tokenizer boundary ledger.
  A response that cuts a Chinese token such as `software` between display
  pages fails with `page_translation_chinese_token_split`; the renderer never
  repairs it with raw character slicing.
- A fresh run of `China AI Why Cheaper?` produced 259 fixed cues and 2,897
  ledger words. Relative to the older 262-cue artifact, only seven formal word
  boundaries changed (five removed and two added); the apparent later ID drift
  is cascading renumbering. The new boundaries remove fragment cuts such as
  `center | might` and `U.S. | right now`.
- The fresh final timeline is `PASS` with
  `applied_backend=whisperx-time-only`, no `source_audio_missing`, and no
  overall backend fallback. Ten expansion-sensitive local timing protections
  remain recorded separately. IDs, English, Chinese ownership, and word spans
  agree across subtitle spans, translations, and the final timeline.
- The published page artifact contains 259 frozen render plans, 302 pages, 40
  multi-page parents, and 43 transitions. Full frozen-artifact validation
  rendered 388 frames (302 page midpoints plus 86 transition frames): missing
  or duplicate words, hard selected boundaries, Chinese token splits, crop,
  panel overflow, bilingual overlap, page-time mismatch, and transition
  failures are all zero. The minimum paginated page is 1080ms and the minimum
  English font is 50px.
- The fresh subtitle run made 22 external requests: 14 full translations,
  seven fixed-ID allocation/review requests, and one page translation request.
  The older cache missed because the improved formal boundaries changed the
  semantic payload contract. No ASR API request or vocabulary-card request ran.
- Final video synthesis ran once and wrote
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260807-page-contract-v8-r1\final-video.mp4`
  (45,540,482 bytes). The actual MP4 validation report is stored beside the
  run under `video-validation/`.
- Actual MP4 validation extracted and checked 391/391 frames: 302 page
  midpoints, 86 before/after transition frames, and 64.8/65.6/66.5-second
  anchors. All 43 transitions match the frozen page artifact; blank subtitle,
  crop, bilingual overlap, frozen-pixel mismatch, and transition failure counts
  are zero. The validation made zero network, ASR, or LLM requests.
- An offline audit that reconstructs syntax evidence instead of loading the
  published artifact computes 303 pages and 44 transitions. This reconstructed
  result is not used by synthesis; the hash-bound 302-page artifact is the
  renderer authority. The audit-input mismatch remains a tooling follow-up.

## 2026-08-08 Manual Draft and Actual Page Preview

- The manual-final editor now exposes each saved frozen render plan as an
  `actual pages` column with page count, English font size, exact bilingual
  page text, and page start/end times. Editing English or Chinese clears the
  stale row preview until the package is saved and replanned.
- Saving a package now chooses between two commands. A formally valid package
  keeps `go to video synthesis`; a package blocked only by one of the three
  page-quality reasons exposes an explicit `synthesize draft` confirmation.
- Draft authorization is carried by `SynthesisConfig.manual_draft_mode`; it is
  cleared when the user imports or edits a different subtitle path. The draft
  output uses the isolated `【人工草稿】` prefix and cannot overwrite a formal
  article or learning-template video.
- The draft path keeps the normal fail-closed checks for package ownership,
  SRT SHA-256, final timeline and word-ledger SHA-256, fixed subtitle IDs,
  contiguous word ownership, English text, and cue-time agreement. Only page
  overflow or missing/invalid page-level Chinese may use a token-safe,
  REVIEW-labelled best-effort page plan.
- Draft mode is restricted to the `文章单词` renderer. Other templates cannot
  consume the page-only authorization.
- Read-only replay of the frozen v10 artifact exposes actual pages for 203/203
  editor rows and all 252 pages; `S0202` exposes its four pages and no ID is
  missing. The preview uses the page artifact's authoritative
  `aggregate_chinese`, not a stale Chinese copy in an older render-plan field.
- Focused manual-editor, synthesis-safety, and publication tests pass. Unified
  regression passes in 223.132 seconds, and `git diff --check` passes with only
  existing line-ending notices. No network, ASR, LLM, FFmpeg, or paid external
  request was made for this change.

## 2026-08-08 Discoverable Subtitle Package Link

- Root cause: the user-facing bilingual SRT copied beside the source audio was
  detached from its manual package. Importing it into the editor disabled the
  draft action, while importing it into the article synthesis page reached the
  renderer without a manifest and failed with
  `missing_or_mismatched_word_ledger`.
- Manual-final save now writes `<media-stem>-原文在上双语字幕.srt` and records
  it in the package manifest. If that source-folder SRT is saved directly, the
  portable package uses the collision-safe sibling name
  `<media-stem>-人工终稿字幕包/`. Stable success publication writes the same
  media-named SRT while retaining the three compatibility subtitle files.
- Editor and synthesis imports recover a manifest only through exact path or
  full-file SHA-256 equality. Exact source-path ownership outranks hash-only
  matches; for a renamed byte copy, a saved manual package outranks an earlier
  blocked checkpoint. Renderer word-ledger and timeline hashes remain mandatory.
- A linked package blocked only by an allowed page-quality reason enters the
  existing isolated manual-draft route. Formal rendering stays blocked, and an
  unrelated standalone SRT cannot inherit another package's timing ledger.

## 2026-08-08 Persisted Manual Draft Page Authority

- Root cause: editor review-mark updates emitted only background/tooltip roles,
  but the editor treated every `dataChanged` signal across text columns as a
  real subtitle edit. The saved package path was cleared and both synthesis
  actions became disabled. Only `EditRole` text changes now invalidate the
  saved package.
- A page-blocked manual save now writes a separate
  `manual-draft-page-plan.json`. Both the manifest and manual override bind its
  owned path and SHA-256. Every page records its fixed ID, English, explicit
  Chinese, word range, time range, font layout, and boundary evidence.
- The editor preview and manual-draft renderer consume that exact persisted
  artifact. Missing, tampered, or cross-package artifacts fail before ffmpeg;
  synthesis no longer calls a page planner or divides Chinese at render time.
- Reloaded manual sessions now use their package-owned artifact directory and
  publish `translations.json`, while older packages without that complete
  owned set retain the source-artifact fallback until they are saved again.
- Read-only replay of the current 203-cue desktop package preserved all 203
  frozen plans and 252 pages, with a 50px minimum English font and explicit
  non-empty Chinese on every page. No desktop artifact was changed.
- Manual-final, page-contract, publication, synthesis-safety, and unified
  regressions pass. Unified regression completed in 284.672 seconds;
  `git diff --check` passes with line-ending notices only. No ASR, LLM,
  FFmpeg, video render, or paid external request ran.

## 2026-08-08 V10-Only Boundary and Page-Count Rebalance

- The sole behavioral baseline for this iteration is
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-page-contract-v10-e2e-20260807-r1`.
  Later 6-7 and 12-13 examples were excluded from rule design and acceptance.
- Formal pre-ID English now rebalances high-confidence dependent tails and a
  short misplaced adjunct before IDs freeze. A complete terminal parallel
  prepositional continuation such as `for anyone ...` remains eligible, while
  short or unfinished preposition-led fragments remain blocked.
- Article planning chooses the page count from measured English pixels, the
  16-word soft load, Chinese load, and cue duration before selecting a cut.
  Cut rewards cannot create an extra page. Low-confidence page turns may keep
  56px instead of forcing the deepest 50px fallback; a valid 54/52px static
  layout still wins, and medium/high-risk turns never win on font size.
- V10 regressions cover the reviewed formal boundaries, approved 37-38 and
  57-58 boundaries, approved 20-21 pagination, and the 174-176 reduction from
  three visual pages to two parent pages (`S0148=1`, `S0149=1`).
- Final offline v10 replay plans 203/203 frozen parents and 250 pages. Font
  counts are 56px=181, 54px=9, 52px=6, and 50px=7. The shortest page within a
  multipage parent is 1015ms; pages below 900ms, hard page boundaries, hard
  line breaks, and English coverage mismatches are all zero.
- Twenty-one parents changed relative to the v10 page artifact and therefore
  require fresh page-level Chinese translation before formal synthesis.
  `S0169` remains an explicit REVIEW because `talks | to` uses the
  forced-complete-continuation fallback when no strict partition exists.
- Unified regression passes 24/24 in 256.214 seconds and `git diff --check`
  passes. The final reports are under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-v10-page-rebalance-offline-audit-final`.
  External requests and FFmpeg runs are zero; no video was synthesized.

## 2026-08-08 Inline Manual Page-Boundary Editing

- The editor no longer uses a detached bottom boundary panel. Selecting a row
  embeds the complete neighboring English and the relevant controls directly
  in the two English cells. The movable words are highlighted; the word count,
  bidirectional move, and undo controls stay beside the affected rows.
- A boundary between two pages of the same parent is presentation-only. The
  session stores absolute subsequent-page start `word_id` values in
  `display_page_boundary_overrides`; parent IDs, English, word ownership, and
  parent timing remain frozen. Layout, page timing, lines, and boundary evidence
  are re-derived for that parent before save.
- A boundary between different parents still uses the formal word-ledger cue
  transfer. It invalidates all old page edits and requires a new whole-episode
  page plan; the editor never presents the old pages as current.
- Manual-final save runs in the background, changes the action text to
  `正在保存终稿...`, shows an indeterminate progress bar plus stage text, and
  restores the table and action when complete. An unchanged parent view now
  reuses the hash-bound frozen blueprint instead of invoking the planner.
- Focused publication tests pass 16/16 and the article display readability
  contract passes. Qt visual validation covers same-parent, cross-parent,
  long-English, save-busy, and save-restored states at DPR 1.0/1.25/1.5 and
  419px, 509px, and 569px English widths. All twelve screenshots pass with no
  crop, overlap, or legacy panel. Evidence:
  `E:\VideoCaptioner-e2e-runs\manual-row-boundary-editor-20260808-dpi-r2`.
- Manual-final editor and video-synthesis safety tests pass. Unified regression
  passes 25/25 in 327.980 seconds; `git diff --check` passes with existing
  line-ending notices only. No external request or video synthesis ran.

## 2026-08-09 Article Terms and Manual Structural Editing

- Article-assisted ASR correction no longer excludes every `technical_terms`
  item. Only article-evidenced, distinctive or aliased domain terms can enter
  fuzzy matching, and automatic replacement additionally requires high
  spelling and phonetic similarity. A real cached replay corrected three
  phonetic variants of `haigui` without changing word times; source ASR and
  glossary files were not modified.
- Row selection is now separate from boundary editing. A selected row exposes
  one explicit boundary entry; direction selection highlights only the source
  words, and confirmation is the sole mutating action. Cancel and undo remain
  non-mutating/restorative.
- Users can rebuild one frozen parent's display projection as two, three, or
  four pages. The shared article planner enforces syntax, pauses, word timing,
  fixed 56/54/52/50px fonts, continuous word ownership, and a 900ms page floor.
  The parent cue stays frozen. New page Chinese is blank and blocks formal
  publication until explicitly reviewed.
- Parent view now supports previewing and deleting a subtitle suffix. Save
  creates a non-destructive AAC derivative and binds it through
  `tail-trim.json` plus manifest hashes. The retained ledger/timeline is a fixed
  prefix, the source audio hash stays unchanged, and identical decisions reuse
  the existing derivative. The first release limits these packages to the
  static podcast-template synthesis path.
- The first UI capture exposed a separate rendering defect: the embedded entry
  widget was transparent, so the table delegate painted a second English copy
  below it. Entry and direction widgets now paint an opaque theme background.
  The old captures remain labelled FAIL rather than being silently replaced.
- Focused suites pass: article correction 29/29, stable publication 20/20,
  manual-final editor 23/23, and video-synthesis safety 24/24. Unified
  regression passes 589 tests across 24 suites plus one syntax check with zero
  failures in 338.622 seconds. `git diff --check` passes with only existing
  line-ending notices.
- Final qwindows evidence under
  `E:\VideoCaptioner-e2e-runs\manual-structural-editor-20260809-final-ui`
  passes 195/195 checks across DPR 1.0, 1.25, and 1.5. Twelve fixed PNGs were
  opened and reviewed; no duplicate English, clipping, overlap, overflow, or
  menu truncation remains.
- A real two-second FFmpeg fixture produced a 1003ms derivative for a 1000ms
  cut, preserved the source SHA-256, and reused the derivative on a second
  save. No network, ASR, LLM, paid request, fresh arbitrary-audio E2E, or full
  video synthesis ran.

## 2026-08-09 Manual Review Page Proposal

- Root cause: the manual `split into N pages` action reused the automatic page
  filter end to end. A boundary already classified as REVIEW could still be
  discarded by automatic continuation guards, leaving an editable long cue
  with the misleading result that no safe page plan existed.
- The strict automatic result remains first and unchanged. Only an explicit
  manual split may fall back to the lowest-risk REVIEW boundary. HARD syntax
  cuts, page timing below 900ms, non-contiguous word ownership, and fixed-font
  overflow remain blocking.
- The 17-word study-abroad cue now proposes `ability | to fit...` as two editable
  pages while preserving fixed parent ID `S0114`, English, word span, cue time,
  and word timing. Page Chinese remains empty until reviewed.
- Focused and full manual-editor tests pass. The current desktop package was
  checked read-only: S0114 becomes word ranges `1129..1137 | 1138..1145`, all
  frozen parent fields remain unchanged, and all 11 package files retain their
  size, mtime, and SHA-256. Unified regression passes 24 suites plus one syntax
  step in 338.772 seconds; `git diff --check` passes.

## 2026-08-09 Stale Actual-Page Import Recovery

- Root cause: saving a newer manual final correctly revoked the previous page
  artifact in the manifest, but the old source-folder actual-page SRT and map
  remained discoverable. Re-importing that file therefore appeared to lose its
  stable package even though the user's save sequence was valid.
- Import now verifies the stale page against its adjacent mapping, follows the
  recorded parent subtitle, and opens the latest matching manual manifest. It
  does not adopt any obsolete page content and explicitly asks the user to
  refresh actual pages.
- The focused stale-import regression passes 1/1 and the full manual-final
  editor suite passes 30/30. A read-only replay of the real desktop file opens
  the latest 261-cue parent package; all 32 files and 42,933,689 bytes retain
  their full-tree SHA-256 before and after the operation.
- Unified regression passes 658 test items across 24 suites plus one syntax
  check in 338.800 seconds. `git diff --check` passes with line-ending warnings
  only. No network, ASR, LLM, FFmpeg, synthesis, or paid request ran.

## 2026-08-09 Visible Stale Page-Chinese Drafts

- Root cause: a newer parent translation could invalidate an older page-level
  translation. ERROR checkpoints deliberately blanked that page Chinese, while
  stale source-folder imports opened only the current parent package. The old
  Chinese therefore still existed in the imported SRT but disappeared from 79
  actual-page rows.
- A hash-verified stale page SRT now contributes only identity-matched Chinese
  review drafts. Page ID, parent ID, word range, English, Chinese, and page time
  must match the companion map, and the same frozen page identity must still
  exist in the current package. Mismatched pages are not recovered.
- Recovered Chinese is visible and marked unconfirmed; it is never aggregated
  into the current parent or accepted as authoritative page Chinese. Formal
  publication explicitly rejects stale-unconfirmed entries. Single-page cues
  use current parent Chinese because no page allocation decision exists.
- The non-authoritative drafts are hash-bound inside the manual edit artifact
  and survive both zero-confirmation and partial-confirmation save/reload.
- Read-only desktop replay now shows 303/303 rows with Chinese, including 79
  stale drafts and zero blanks; all 261 parent cues retain Chinese, and the
  imported SRT SHA-256 and mtime remain unchanged. Focused manual-editor and
  stable-publication suites pass. Final unified regression passes 25/25 stages
  in 356.408 seconds and `git diff --check` passes. No network, ASR, LLM,
  FFmpeg, synthesis, or paid request ran.

## 2026-08-09 Empty Intermediate Page Edit Recovery

- A later 309-page manual checkpoint reproduced the remaining GUI defect: 89
  page rows were blank even though the imported stale page SRT still supplied
  79 exact page-identity Chinese drafts. Persisted empty intermediate edits were
  incorrectly taking precedence over those recovered drafts.
- Preview now treats an exact recovered draft as visible, stale, and
  unconfirmed when the current page edit is empty. The authoritative edit and
  parent Chinese remain unchanged, and formal publication remains blocked.
- Page-boundary or page-count work on another parent preserves this stale
  ownership instead of silently converting the displayed draft into confirmed
  Chinese. Pages whose word ranges actually changed receive no old draft.
- Read-only replay of the current desktop import exposes 309 rows, 79 recovered
  drafts, and 10 intentionally blank changed-span pages. The source SRT hash and
  mtime remain unchanged. Manual-editor tests pass 44/44, stable-publication UI
  tests pass 43/43, and unified regression passes 25/25 stages in 339.2 seconds.
  `git diff --check` passes; external requests remain zero.

## 2026-08-09 Vocabulary Batch Cache Recovery

- Root cause: vocabulary selection wrote any usable subset into the ordinary
  cache after a request timeout or the 240-second generation budget. That cache
  did not record batch completion, so later renders treated a front-loaded
  partial result as a complete episode plan.
- Vocabulary cache schema v2 now records stable content-derived chunk IDs,
  `chunk_order`, `completed_chunk_ids`, per-chunk cards, and `complete`. A
  successful empty array completes its chunk; only completion of every current
  semantic-group chunk completes the cache.
- Request order is timeline-balanced (opening, ending, middle, then intervening
  ranges). Every successful chunk is atomically saved to a separate v2 progress
  cache. A later render merges valid local/global progress and requests only
  missing chunks.
- A legacy prompt-v16 cache is not overwritten while v2 progress is partial.
  Its candidates are merged with every completed v2 batch and the combined set
  is rescheduled for the current render, so a recovered late-episode candidate
  is not hidden behind the legacy plan. The ordinary per-subtitle and global
  cache files are atomically replaced only after the v2 contract is complete.
  Card content, trigger time, full-card persistence, subtitle data, and layout
  are unchanged.
- Offline replay of the 199-cue `中国AI为何更省钱？` production subtitle used its
  existing nine-card cache across seven real request chunks: the first pass
  completed 3/7 without changing the legacy cache, and the second pass requested
  only the remaining four and reached 7/7. The final scheduled plan remained at
  eight cards.
- Seven focused cache tests and the unified 25-stage regression pass. The latter
  exited `0` in 368.3 seconds; unrelated log-rotation file-lock warnings did not
  fail a stage. The checkable 1920x1080 frame is
  `tests/caption_audit/out/vocab-cache-recovery-sample.png`, with replay facts in
  `tests/caption_audit/out/vocab-cache-recovery-replay.json`. No external model,
  ASR, FFmpeg, or synthesis request ran.

## 2026-08-09 Vocabulary Timeline Distribution

- `中国AI为何更省钱？` is 912.8 seconds long, so the current density target is
  15 cards. Its legacy cache contains nine raw candidates; eight pass the local
  scheduler. The last legacy card, `physical bottlenecks`, begins at 409.5
  seconds and therefore remains visible for 503.6 seconds when no later
  candidate is available.
- Root cause of the excessive tail hold was twofold: the old incomplete cache
  contained no later candidate, and the recovery path used `legacy or partial`,
  which hid completed v2 candidates until all batches finished. Recovery now
  merges legacy and completed-v2 candidates before the common quality and
  timeline scheduler runs.
- The scheduler targets one card per minute and spreads eligible candidates
  across equal time strata. It retains the existing priority >= 3 quality gate,
  exact-source-phrase rule, duplicate removal, 15-second minimum interval, and
  three-concept cap. It does not use ordinary vocabulary to force 15 cards.
- Syntax compilation and seven focused vocabulary tests pass. Both full
  regressions passed the vocabulary smoke stage but were blocked by unrelated
  dirty-worktree test instability: one `stable subtitle publication` failure
  passed 46/46 in isolation; the later `video synthesis publication safety`
  failure reproduces in a `SimpleNamespace` UI fixture missing
  `_set_manual_editor_mode`.
- The current 1920x1080 real-data frame is
  `tests/caption_audit/out/vocab-card-schedule-sample-20260809.png`; schedule
  evidence is in
  `tests/caption_audit/out/vocab-card-schedule-report-20260809.json`, and the
  labeled target-versus-legacy diagram is
  `tests/caption_audit/out/vocab-card-timeline-comparison-20260809.png`. No
  external model, ASR, FFmpeg, or synthesis request ran for this validation.

## 2026-08-09 Missing Manual-Page Chinese Proposals

- Root cause: exact old page identities recovered Chinese for 79 of 89 blank
  manual-page edits, but five re-paged parents had ten new word ranges with no
  page-level Chinese. Their parent cues still contained complete Chinese.
- For a manual page override only, the editor now uses the existing strict
  Chinese token-boundary splitter and each English page's word count to propose
  a complete local allocation. It returns no proposal when a safe Chinese
  boundary cannot be found. It does not call an LLM or change parent cues,
  frozen English, word ranges, word times, or renderer-authoritative data.
- Source priority is explicit: confirmed manual Chinese, exact identity-matched
  recovered draft, current local parent-split proposal, saved stale draft,
  stale artifact text, then blank. Every non-authoritative value stays marked
  unconfirmed and formal publication remains blocked.
- Repeating the same manual page count is now a no-op only when page IDs, word
  ranges, and frozen English all match. Confirmed page Chinese, history, and
  overrides are preserved. A real page-count or boundary change still clears
  the affected authoritative page Chinese and requires review.
- Read-only replay of the current desktop import reports 309/309 non-empty
  Chinese rows: 220 authoritative, 79 recovered drafts, and 10 local proposals
  across `S0016`, `S0034`, `S0095`, `S0137`, and `S0166`. Each proposal group
  concatenates exactly to its current parent Chinese. The source SRT SHA-256,
  length, and mtime are unchanged.
- Manual-editor tests pass 45/45 and stable-publication/UI tests pass 43/43.
  Unified regression passes 25/25 stages in about 345 seconds, and
  `git diff --check` passes. Network, ASR, LLM, FFmpeg, synthesis, and paid
  requests are zero.

## 2026-08-09 Existing-Page Expansion With Manual Review Boundaries

- Root cause: explicit manual page-count planning allowed the lowest-risk
  REVIEW boundary, but the following frozen-plan rebuild omitted
  `allow_manual_review=True`. Existing two-page parents could therefore report
  `manual_page_boundary_is_hard` when the user asked for a third page.
- The manual split path now carries the same review authorization through the
  rebuild. Automatic page planning remains strict. Continuous word ownership,
  fixed parent IDs/text/timing, minimum page duration, fixed-font layout fit,
  and structural-overflow checks remain mandatory.
- The actual-page menu treats an existing page count as its baseline: a
  two-page parent offers three or four total pages rather than repeating a
  no-op two-page request. A true no-op no longer dirties editor state, revokes
  synthesis authorization, refreshes the table, or reports false success.
- Read-only real-package replay passes for `S0196` and `S0216`: each changes
  from two to three pages, 309 to 310 visible rows, with continuous word
  ranges, unchanged frozen parent cues and word ledger, and all other 307 rows
  unchanged. All 11 package files retain their size, mtime, and SHA-256.
- The focused regression passes, the manual-final editor script passes,
  stable-publication/UI passes 49 tests, video-synthesis safety passes, and the
  unified regression completes 25/25 stages with no failure summary.
  `git diff --check` passes. Network, ASR, LLM, FFmpeg, synthesis, and paid
  requests are zero.

## 2026-08-09 Manual File Menu And Format Export

- Root cause: the custom `RoundMenu` keeps an already-added action in its own
  list widget when `QAction.setVisible(False)` is called, so compatibility
  correction and document prompt remained visible as disabled rows in
  manual-final mode. That mode also hid the complete format-export button,
  including the existing bilingual TXT output.
- Manual-final mode now removes the two upstream-only actions from the menu
  through `RoundMenu.removeAction`. Ordinary processing mode inserts them back
  before subtitle settings in their original order, and repeated mode changes
  do not duplicate entries.
- The existing format dropdown remains available as `导出字幕` in manual-final
  mode. It continues to use the current visible table, selected bilingual
  layout, and existing format choices including TXT; subtitle IDs, page plans,
  timing, manifests, and synthesis authorization are unchanged.
- Three focused menu/export tests pass, stable-publication/UI passes 51/51,
  and the unified regression passes all 25/25 stages (about 653 test items) in
  343.325 seconds. `git diff --check` passes. No network, ASR, LLM, FFmpeg,
  synthesis, or paid request ran. A separate offscreen menu screenshot attempt
  crashed in the Qt platform plugin and is not claimed as visual acceptance.

## 2026-08-09 Interactive Review Gate And Organized Media Outputs

- Root cause of automatic synthesis: the interactive subtitle task reused
  `need_next_task`, and `SubtitleInterface` emitted the Home synthesis signal
  immediately after loading the completed manual session. `SubtitleTask` now
  carries an explicit `require_manual_review_before_synthesis` contract. Home
  sets it, so a completed interactive run stays in the editor; batch tasks keep
  their existing automatic chain.
- Root cause of scattered files: stable exports, QA files, manual packages,
  compatibility SRT, and videos independently derived paths from the media
  parent. `media_result_dir` now owns one
  `<output-anchor-parent>/<source-media-stem>-处理结果/` directory. Normal Home
  runs therefore place all user-facing outputs beside the audio in that one
  folder; E2E report anchors remain isolated. Internal work-dir artifacts and
  source media are unchanged, and existing loose files are not moved or deleted.
- Focused task-context tests pass 5/5, stable-publication/UI tests pass 53/53,
  the manual-final editor script and video-synthesis safety script pass, and
  the unified regression passes all 25/25 stages in 330.3 seconds. The first
  two unified attempts exposed and then fixed output-anchor/name test-contract
  mismatches; the final run exits 0. Network, ASR, LLM, FFmpeg synthesis, and
  paid requests are zero.

## 2026-08-09 Podcast English-Only Synthesis Toggle

- The synthesis command bar now exposes `仅英文字幕` whenever the English
  learning template is enabled. Enabling it also enables video synthesis and
  the learning template; its persisted value is frozen into the synthesis task
  so a queued render cannot change when the UI is edited later.
- The selected simple workflow is two explicit runs: leave the toggle off for
  the bilingual video, then turn it on and synthesize again for the English-only
  video. One-click generation of both variants is intentionally not included.
- English-only mode suppresses only the bottom Chinese subtitle draw call. It
  does not erase `Cue.zh`, recalculate English wrapping or article pages, or
  remove Chinese vocabulary-card glosses. Both templates therefore retain the
  same English and vocabulary-card regions for the same frozen inputs.
- Output names are isolated: `【文章单词模板】标题.mp4` and
  `【文章单词模板-英文字幕版】标题.mp4` for the article template, with the
  equivalent `【英语学习模板】` names for the dark-podcast template. Manual draft
  output follows the same `-英文字幕版` suffix rule.
- A formal smart-card render still requires a complete vocabulary plan before
  encoding. The language toggle is not part of the vocabulary cache key, so two
  runs over the same source, prompt version, model configuration, and completed
  cache reuse the same plan.
- Syntax checks, the video-synthesis safety script, the task-context contract,
  and focused two-template pixel-region tests pass. The unified regression
  passes all 25 stages in 362.9 seconds. Checkable 1920x1080 frames are
  `tests/caption_audit/out/article-template-english-only-sample-20260809.png`
  and `tests/caption_audit/out/podcast-template-english-only-sample-20260809.png`;
  the checked 1400x850 command-bar capture is
  `tests/caption_audit/out/synthesis-english-only-toggle-ui-20260809.png`.
  No real FFmpeg pair, ASR, external model, or paid request ran.

## 2026-08-09 Local Manual Page Reflow And Exact Chinese Recovery

- Root cause: a formal English boundary move cleared the entire
  `display_page_edits` and `display_page_boundary_overrides` state. One stale
  parent therefore replaced the full actual-page table, and an all-or-nothing
  page reuse path could make unrelated Chinese pages disappear after refresh.
- Formal boundary moves now snapshot the complete visible page model, rebuild
  only the two affected parents, and freeze every unaffected page by page ID,
  parent ID, word range, English, Chinese, and timing. Affected Chinese remains
  visible as an explicitly unconfirmed draft; publication stays fail-closed.
- Saved packages that already contain blank page Chinese can recover text from
  their hash-verified undo history only when page ID, parent ID, word range,
  and normalized English all match. Recovered text is never authoritative until
  manually confirmed. Ordinary one-page parent Chinese remains authoritative;
  only pages created by formal-boundary reflow retain the stale-draft marker.
- The manual table vertical header now shows `Sxxxx` or `Sxxxx.Pxx` instead of
  a drifting visual row number, with enough manual-mode width to read the ID.
- Read-only replay of the current `中国年轻人为何不爱留学了？` manual package
  restored all 77 blank Chinese pages: 303 rows, zero blank Chinese, zero
  unavailable pages. Moving `right?` from `S0080` to `S0079` in memory kept 303
  page rows and changed zero unaffected pages; both affected pages remained
  visible and unconfirmed.
- Manual-editor tests pass, stable-publication/UI passes 54/54, and the unified
  regression passes 25/25 stages in 359.2 seconds. `git diff --check` passes.
  No network, ASR, LLM, FFmpeg synthesis, paid request, or production artifact
  write ran.

## 2026-08-10 Actual-Page Merge, Row-Scoped Undo, And Stable Focus

- Actual-page editing now distinguishes two operations. Merging adjacent pages
  inside one parent removes only that visual page boundary; selecting pages
  from adjacent parents performs the existing formal parent-cue merge. The
  first operation leaves the parent subtitle ID, English, word range, timeline,
  and word ledger unchanged.
- A formal parent merge remaps and rebuilds only the selected parents' page
  state. If the merged parent cannot satisfy the frozen ledger, timeline, or
  fixed-layout contract, the cue merge, page edits, boundary overrides, and
  history entry are rolled back together.
- The global undo control is hidden. Each subtitle inspector exposes undo only
  when the latest linear-history operation affects that parent. The editor
  refuses an older row-scoped rollback when a later operation exists, because
  out-of-order boundary rollback would invalidate later word ownership.
- Split, display-boundary, formal-boundary, merge, and undo refreshes restore
  selection by display-page ID, parent subtitle ID, and word ID instead of by
  the old visual row number.
- Focused session checks pass 3/3, focused UI checks pass 6/6,
  `tests.test_stable_publication` passes 57/57, and the complete manual-editor
  script passes. The unified regression passes all 25 stages in 353.4 seconds.
- Read-only replay of the current 303-page production package merges
  `S0001.P01` with its next page, changes zero fields in the 300 unrelated
  pages, leaves all parent cues and the word ledger unchanged, and restores all
  303 pages after undo. The production package was not written. Network, ASR,
  LLM, FFmpeg, synthesis, and paid requests are zero.

## 2026-08-10 Actual-Page Tail Trim And Source-Media Recovery

- Tail deletion is now available from the actual-page context menu. The cut is
  owned by the selected page's first word ID. Selecting a later page inside one
  parent keeps the preceding pages, truncates that parent to the preceding word,
  and removes all following words and cues without renumbering the retained ID.
- Source media resolution still prefers the manifest contract. When an imported
  subtitle has no usable media path, the editor now derives the exact source
  stem from `<media-stem>-处理结果/` and accepts only one same-stem supported
  media sibling outside that directory. Multiple candidates remain an error;
  the editor does not guess.
- The delete action changes the in-memory subtitle and word-ledger suffix. The
  explicit manual-final save materializes a separate `*-尾部裁剪.m4a` through
  FFmpeg, binds its hash into the manifest, and makes synthesis prefer it even
  when the UI still holds the original media path. The original file remains
  unchanged.
- Focused manual-editor tests and 57/57 publication/UI tests pass. The unified
  regression passes all 25 stages in 459.5 seconds.
- Read-only replay of the current 303-page package trims from `S0254.P02` at
  969.689 seconds, retains `S0254.P01`, resolves the original desktop `.m4a`,
  and restores the complete cue/ledger state after undo. All nine package files
  retain their size, timestamp, and SHA-256. No production write, external
  request, ASR, LLM, synthesis, or paid request occurred.

## 2026-08-10 Manual Checkpoint Identity And Per-Page Font Ownership

- Root cause: the manual save path could overwrite the discoverable original
  parent subtitle, while a failed formal-boundary reflow could clear the whole
  in-memory page table and its boundary overrides. This made original, page
  snapshot, and manual-final imports behave like ambiguous reset points.
- `人工终稿字幕.srt` now continues the current manual package;
  `原文在上双语字幕.srt` opens the immutable stable parent checkpoint; and
  `实际分页双语字幕.srt` remains a page snapshot that resolves to the latest
  matching manual package when one exists. Manual save no longer overwrites the
  original parent or original actual-page exports.
- Formal parent-boundary changes are atomic with their local page reflow. A
  failed reflow restores cues, page edits, overrides, and history. Save rejects
  the specific corruption pattern where history recorded manual pages but both
  current page state and boundary overrides unexpectedly became empty.
- Automatic and manual pagination now recompute typography after final page
  word spans are selected. Each page chooses its own largest legal
  56/54/52/50px size; the parent `english_font_size` is the minimum child size
  only as a compatibility summary. The renderer consumes the page value.
- The planner contract is `article-fixed-font-pages-v17`; older page-layout
  caches are invalidated without invalidating ASR, fixed English, parent
  Chinese, or word-timing caches.
- Read-only replay of the existing 262-parent, 303-page study-abroad package
  found six pages whose font can increase and zero pages whose font decreases;
  all nine package files retained their SHA-256. The unified 25-stage
  regression passes in 374.5 seconds and `git diff --check` exits zero. No
  network, ASR, LLM, production FFmpeg, synthesis, or paid request ran.

## 2026-08-10 High-Pressure Page Review And Person Context Correction

- `article-fixed-font-pages-v18` adds a bounded second review only for a static
  page over 16 words or requiring 52/50px. It promotes a reviewed partition
  only when every page has at least six words, at least 900ms, and a legal 56px
  layout, while every boundary has a complete clause restart or a verified
  pause of at least 500ms. Incomplete modifier/head, subject/predicate,
  verb/object, and infinitive boundaries remain rejected.
- Read-only replay of the 262-parent study-abroad checkpoint found 17
  high-pressure single pages averaging 16.06 words. Only `S0044`, `S0076`, and
  `S0257` changed page boundaries; the other 259 parent page projections did
  not change. Parent IDs, English, Chinese, word ranges, and coverage had zero
  mismatches.
- Low-similarity titled person names may now use article evidence only when the
  title matches, the surname keeps its initial and minimum similarity, and the
  nearby ASR description overlaps the article person description. This is a
  general evidence gate, not a name replacement table. Real-ledger replay
  corrected both `Ms. Howe` occurrences to `Ms Hao`, retained all three
  `haigui` surfaces, and covered all 2860 original word ranges.
- Interrupted runs reuse article correction output only when its explicit
  `article-asr-correction-v2` policy matches. An old correction artifact is
  recomputed without invalidating the article-context or raw-ASR cache.
- Article-context tests pass 33/33, the complete article display readability
  contract passes, and the unified regression passes all 25 stages in 375.0
  seconds. The validation was offline: no network, ASR, LLM, FFmpeg synthesis,
  paid request, or production artifact write ran.

## 2026-08-10 Frozen-Page Same-Screen Line Layout

- `article-fixed-font-pages-v19` adds one renderer-only English line-layout
  pass after page spans, page IDs, Chinese assignments, and page timing are
  frozen. It compares 56/54/52/50px one- or two-line layouts without authority
  to change page count, page boundaries, word ownership, English, Chinese,
  subtitle IDs, or timing.
- The previous layout remains the baseline. A smaller font is accepted only
  when it produces a strictly better legal line break; equal layouts and equal
  scores retain the larger font. If any valid size above 50px exists, 50px is
  excluded from selection. Lexical atoms remain hard line-break protections;
  only explicit non-atomic subject/predicate evidence is treated as a soft
  same-screen score.
- Read-only replay of the current study-abroad manual package checked 253
  parents and 311 pages. Twenty-seven pages changed only their recorded line
  layout. Page IDs, parent IDs, page count, English, Chinese, frozen word
  ranges, start/end times, and source word coverage had zero changes. All 15
  source-package files retained their SHA-256.
- The initial offline layout comparison appeared to move font counts from
  56/54/52/50 = 303/1/6/1 to 299/6/6/0, but renderer revalidation exposed
  three retained v18 wraps that were not valid v19 layouts. The accepted
  manual-save result is 297/6/5/3. `S0065.P01`, `S0185.P01`, and `S0223.P01`
  use the 50px last resort; retaining their old 56/56/52px records makes the
  renderer reject the artifact.
- The complete article display readability contract and the 25-stage unified
  regression pass. The final unified run completed in 407 seconds. Visual
  before/after inspection found no overflow, overlap, or unexpected third
  line. No network, ASR, LLM, FFmpeg synthesis, paid request, or production
  artifact write ran.
- Manual-final save now upgrades an older frozen page artifact through the same
  v19 same-screen pass before writing its new contract. The upgrade copies page
  count, page IDs, word spans, English, Chinese, page times, and boundary
  evidence unchanged and rewrites only English lines, font size, and measured
  width. This prevents a v18 manual package from being mislabeled as v19 or
  rejected later by the renderer.
- A read-only replay through the actual manual-save blueprint path checked all
  253 parents, 311 pages, and 311 saved page edits. Twenty-three page layouts
  changed and the complete structural projection had zero changes. The full
  article-layout and manual-editor scripts pass, and the post-integration
  25-stage unified regression passes in 393.2 seconds.
- A real synthesis attempt then exposed the invalid retained legacy layouts at
  `S0065.P01`, `S0185.P01`, and `S0223.P01`. Baseline retention now requires
  the old lines to pass the current v19 validator; an invalid legacy wrap can
  no longer be relabeled as v19. A temporary full manual-save package with 253
  parents and 311 pages is accepted by the renderer, and the final 25-stage
  unified regression passes in 375.9 seconds. No production package was
  overwritten during this repair.

## 2026-08-10 Silent Tail Duplicate Guard And Release-Gate Tiers

- The failed `如何停止拖延` run contained a high-confidence Faster-Whisper
  tail hallucination. The legitimate final sentence ended at 18:18.920; a
  14-word paraphrase then occupied only 260ms and overlapped itself. Its
  longest repeated phrase covered 10 of 14 words, and FFmpeg measured the
  exact candidate interval at -46.4dB maximum volume.
- Faster-Whisper word-timestamp results now remove an end-of-file candidate
  only when all independent signals agree: a sentence boundary, 6-24 words,
  at least 12 words/second, at least 30 percent overlapping word times, a
  repeated contiguous phrase covering at least 60 percent and five words, and
  an audio maximum no louder than -45dB. Missing FFmpeg, missing audio, audible
  speech, non-repeated text, or any ambiguous evidence preserves the text.
- The real failed SRT replay removes only the final 14-word silent duplicate,
  reducing 3,135 ASR word entries to 3,121 and retaining the legitimate final
  `... begin with.` sentence. Filtering occurs while cached or fresh
  Faster-Whisper output is parsed, before article correction, stable English
  boundaries, fixed IDs, or the authoritative word ledger are frozen.
- Stable release now uses the review tier attached to each top-level validation
  error. A `reading_speed_error` classified as `REVIEW` remains visible but
  does not alone block publication. A `BLOCKER`, an unclassified error, or a
  legacy ERROR without review evidence remains fail-closed. Allocation review
  entries that are not top-level validation errors do not silently become a
  new production gate.
- ASR trust tests pass 22/22, including silent-repeat removal and audible or
  non-repeated retention. Four focused validation-publication checks pass. The
  complete 25-stage regression exits zero in 406.2 seconds. The existing
  287-cue failed production artifact was not published because it still owns
  the hallucinated final cue; the open application must be restarted and the
  audio rerun so its ASR cache passes through the new pre-freeze guard.

## 2026-08-10 Manual Checkpoint Actual-Page Recovery

- A blocked `如何停止拖延` manual save retained all 353 ID-bound page edits but
  its derived display artifact contained no render plans. Loading therefore
  showed only parent rows even though the user's 92 edit-history operations,
  38 page-boundary overrides, and tail-trim decision were still on disk.
- When a derived page artifact is missing or unusable, the editor can now
  rebuild an editor-only page model from the complete saved page-edit table.
  Recovery requires exact page and parent IDs, continuous frozen word ranges,
  ledger-derived English, complete cue coverage, and a valid boundary-evidence
  ledger. Any mismatch remains fail-closed.
- Recovery does not confirm stale Chinese or authorize synthesis. The real
  checkpoint restores 353/353 page identities and keeps all 19 unconfirmed
  Chinese drafts visible with zero blank rows. Formal synthesis remains blocked
  by `manual_page_translation_required` until those pages are confirmed.
- The complete manual-final editor script, syntax compilation, and 58
  publication/UI tests pass. The production package was read only during
  replay. The required 25-stage regression also passes in 361 seconds. No ASR,
  LLM, FFmpeg synthesis, paid request, or output overwrite ran.

## 2026-08-10 Manual Editor State Integrity And Interaction Latency

- Re-audited the manual editor as one state machine after reproducing long
  pauses in split and page-boundary operations. One 353-page production
  session rebuilt 38 manually overridden render plans on every model read;
  one model derivation took 0.9-1.6 seconds and a single UI command requested
  it several times.
- Added content- and file-version-bound session caches for the complete page
  model and each parent preview. Subtitle cues, page edits, boundary overrides,
  recovered drafts/evidence, manifest, display artifact, draft plan, or boundary
  evidence changes invalidate the relevant cache. Returned model rows are deep
  copies so table edits cannot mutate cached authority.
- A visual page-boundary move now marks only its two affected page translations
  as visible unconfirmed drafts. Other pages in the same parent retain their
  exact Chinese text and confirmation state. English, parent/page IDs, word
  ranges, word times, and synthesis gates remain unchanged.
- Manual save now disables editing before dispatch and copies the potentially
  large session snapshot inside the worker. A completed package that cannot be
  reloaded no longer replaces the live session or switches the table to parent
  rows; the actual-page view remains editable and synthesis stays disabled.
  Concurrent mutations are rejected while the snapshot is being saved.
- Read-only replay of the 283-parent/353-page `如何停止拖延` package reduced
  repeated model reads to 0.012-0.014 seconds. One real split measured 0.159
  seconds plus 0.122 seconds refresh; one legal page-boundary move measured
  0.136 seconds plus 0.129 seconds refresh, with zero drift across 351
  unaffected pages. One legal cross-parent formal-boundary move measured 0.940
  seconds plus 0.143 seconds refresh, with zero drift across 349 unaffected
  pages.
- The manual-editor script passes, stable publication/UI passes 60/60, syntax
  compilation passes, and the required 25-stage regression exits zero in 381.4
  seconds. Production artifacts were not written during the replay.

## 2026-08-11 Internal ASR Gap Recovery And Word-Timing Trust

- The `如何停止拖延` source exposed two independent upstream defects. Faster
  Whisper skipped 23 spoken words around 08:51 between `Wow.` and `You are
  borrowing...`; stable-ts separately compressed six words near subtitle 281
  into one 120ms interval, leaving the eight-word cue with only a 741ms
  envelope. Neither defect originated in English cutting, Chinese allocation,
  display pagination, or rendering.
- Faster-Whisper now audits internal word gaps before stable IDs freeze. A
  1.8-15 second gap must contain FFmpeg-confirmed activity, and a temporary
  local transcription runs with `condition_on_previous_text=False`. Only an
  exact left-and-right anchored insertion can change the transcript. An
  unanchored local result is recorded and skipped, so background sound cannot
  silently add words or fail the whole task. A successful repair overwrites
  the raw ASR cache entry with the repaired word SRT.
- Native Faster-Whisper compression now has a separate pre-freeze recovery
  path. Millisecond zero-width normalization cannot move a word past a later
  emitted word with the same timestamp. When the shared detector still finds
  a compressed run, one bounded context-free retranscription may update that
  run only if unique exact anchors surround the same word multiset. This can
  restore a cache whose timestamp sort inverted adjacent words, but cannot
  add, delete, substitute, or freely rewrite English. The repaired word SRT
  replaces the stale cache; unresolved or text-changing candidates still fail
  the normal timing gate.
- A shared word-timing trust detector now guards transcript handoff, stable-ts,
  WhisperX time-only updates, and final ledger reconciliation. Implausible
  aligner updates fall back only to a timing-trusted upstream ledger. Residual
  compression blocks the run instead of being converted into chains of 1ms
  words by final boundary reconciliation.
- Read-only audit parsed 99 historical word ledgers. The thresholds found 33
  files with 50 anomalous regions and no credible normal-speed false positive.
  `8 words / 741ms` remains a failure, while `8 / 800ms` and `7 / 600ms` do not.
  The earlier detector could chain overlapping windows into a 40-word repair;
  it now selects one minimum core per connected region, expands only adjacent
  words inside the same collapsed time envelope, and detects again after each
  local fallback.
- The real local 08:51 experiment recovered the exact missing 23 words in
  about nine seconds while retaining both surrounding anchors. Focused ASR
  trust tests pass 33/33, final-cue timeline tests pass, syntax compilation
  passes, and the complete stable-caption rule script passes. The required
  25-stage unified regression also passes in 362.2 seconds. No production
  artifact, translation, pagination result, or video was written.

## 2026-08-11 Manual Numeric Boundary Comma Fix

- Manual boundary movement no longer treats a trailing comma, semicolon, or
  colon after a numeric token as an unfinished numeric phrase. This allows
  `early 2026, / the global market` to move only `the` while preserving the
  existing protection for phrases such as `740 billion` and `3 months`.
- The change is limited to manual boundary expansion. It does not change
  frozen English cue ownership, word timing, display-page planning, Chinese
  allocation, or synthesis subtitle resolution.
- Manual-editor tests and the complete 25-stage unified regression pass.

## 2026-08-12 Manual English Surface Correction And Display Suppression

- The article-assisted correction candidate for `only as -> OnlyFans` was a
  false entity match: the article contains a later genuine `OnlyFans`, but the
  earlier ASR words are the ordinary phrase `only as`. A fuzzy one-token entity
  can no longer consume a multi-token source phrase containing function words
  unless the normalized source is an exact orthographic join. The real later
  `OnlyFans` remains unchanged.
- The manual editor can now correct the display surface owned by exactly one
  frozen word ID from either parent or actual-page view. Word IDs, word order,
  word times, cue/page ranges, and timing stay fixed; multi-ID free rewriting
  remains rejected. The affected Chinese is marked for confirmation.
- Because the QFluentWidgets row-selecting table does not reliably open its
  inline editor on every double-click, the single-row context menu now provides
  `修正当前英文（保持时间轴）`. Its large text dialog validates and applies the
  edit immediately through the same frozen-word contract, restores the current
  page selection, and reports invalid multi-ID edits before manual-final save.
- A cue may be hidden from the visible subtitle without deleting its audio.
  `display_suppressed` removes it from visible SRT and page rendering while the
  final cue timeline retains its original subtitle ID, word envelope, and time.
  Undo and restore-display operations preserve the complete ledger.
- Focused verification passes: article correction 34/34, manual-editor direct
  suite, stable publication/UI 61/61, and video-synthesis safety. The required
  25-stage unified regression passes in 390.3 seconds after the explicit
  English-edit dialog integration.
- Read-only replay of the real 258-parent/311-page `好莱坞最新热潮：姐弟恋`
  manual package preserved all 88 prior history entries, then added only the
  two requested operations in memory. Only word ID 353 changed from the false
  `OnlyFans` surface to `only as`; the later genuine `OnlyFans` at word ID 828,
  all word IDs/times, and every unrelated page remained exact. The production
  package was not overwritten.

## 2026-08-12 Suppressed-Cue Page-State And Multi-Token Surface Repair

- A suppressed cue remains visible in the editor as a restore entry with no
  display-page ID. Page completeness, review, split, merge, boundary-move, and
  formal-boundary reflow now evaluate only non-suppressed rows. The restore
  entry remains part of the full cue timeline but cannot clear valid visible
  page edits or make the whole page model incomplete.
- Renderer page planning now treats each authoritative timed-word record as
  one boundary unit. One manually corrected record may therefore display a
  whitespace phrase such as `only as` without inventing another timestamp or
  making `len(cue.en.split())` the timing authority. Page IDs, word ranges, and
  times remain unchanged; the display text still has to equal the joined timed
  surfaces exactly.
- Read-only replay of the real 258-parent package retained the hidden `S0021`
  restore row, all 310 visible pages, and both `S0028.P01/P02` after correcting
  word ID 353. Word ID 828 remained `OnlyFans`, and every word ID/time stayed
  exact. A temporary formal render contract passed with 257 visible parent
  plans; no production artifact was written.
- Manual-editor, stable publication/UI 61/61, article-readability, and syntax
  checks pass. The complete 25-stage regression passes in 372.9 seconds.

## 2026-08-12 Actual-Page Local Split, Atomic Merge, And Explicit Editing

- `仅将当前屏拆为 2 屏` now plans a cut only inside the selected display
  page. Every other page in the parent keeps its word range, Chinese text,
  confirmation state, and timing; only page IDs after the inserted page may
  be renumbered to preserve deterministic `Sxxxx.Pxx` order.
- Merging two adjacent actual pages from different parents is now one atomic
  operation. It merges the parent cues and removes the selected visual page
  boundary in the same command. Any failure restores cues, page edits,
  boundary overrides, history, and tail-trim state, and one undo restores the
  complete pre-merge state.
- Model refresh, split, and merge keep the editor in actual-page view but do
  not automatically expose boundary controls. A subtitle row must be clicked
  explicitly before its adjustment entry appears; clicking the empty table
  viewport clears the selection and exits boundary-edit mode.
- These changes do not alter automatic English segmentation, Chinese
  allocation, the authoritative word ledger, cue timing, page rendering, or
  synthesis subtitle resolution.
- Focused manual-editor tests pass, stable publication/UI passes 63/63, syntax
  compilation passes, and the complete 25-stage regression passes in 391.8
  seconds. No production subtitle, audio, or video artifact was written.

## 2026-08-12 Preferred-Font Same-Screen Reflow

- Root cause: the renderer-only same-screen scorer could lower a page from
  56px to 54px solely to replace a valid two-line layout with one line. This
  made a manually or automatically split page retain an unnecessarily small
  font even though the preferred size fit safely within the two-line limit.
- Same-screen reflow now checks the existing 56/54/52/50px sequence in order
  and retains the first size with a legal one- or two-line layout. Smaller
  sizes remain available only when every larger size fails layout validation;
  page count, page IDs, word ranges, English, Chinese, timing, and boundary
  evidence remain frozen.
- Read-only replay of the rendered `好莱坞最新热潮：姐弟恋` manual-final package
  found 310 display pages. The rendered distribution was 56px=299, 54px=6,
  52px=2, and 50px=3. Current-code reflow changes only `S0033.P01`,
  `S0219.P01`, and `S0234.P01` from 54px to valid 56px two-line layouts; the
  other 307 pages and every non-typography field remain unchanged. The new
  distribution is 56px=302, 54px=3, 52px=2, and 50px=3.
- Article readability, manual-final editor, and stable publication/UI 63/63
  tests pass. The complete 25-stage unified regression passes in 459.2
  seconds. No production subtitle, audio, or video artifact was overwritten.

## 2026-08-12 WhisperX Numeric Pause Preservation

- The rendered `S0001 -> S0002` delay was upstream timing drift, not a renderer
  defect. Native timing placed `73%` at 1.560s after a 480ms pause, while
  WhisperX stretched `field,` to 2.001s and moved `73%` to 2.041s. The final
  cue therefore appeared about 461ms after the spoken onset.
- The WhisperX frozen-ledger handoff now preserves a trusted 200ms-or-longer
  pause before numbers, percentages, currency forms, and acronyms when the
  aligner substantially erases that pause and would delay the effective token
  onset by at least 150ms without matching drift in the preceding word start.
  Only the two words owning the boundary can fall back; word text, IDs, order,
  cue ownership, and every unrelated time remain unchanged.
- Exact regressions cover `field, / 73%` and the unmatched `move. / 72%.`
  boundary, plus a shared-local-shift counterexample. Stable caption rules,
  ASR trust 38/38, final-cue timeline tests, and `git diff --check` pass. The
  complete 25-stage unified regression also passes in 367.4 seconds.

## 2026-08-12 Manual Package Relocation And Save Snapshot Cost

- Root cause: a manual-final package recorded absolute Desktop paths for its
  subtitle, edit journal, artifact directory, word ledger, and page subtitle.
  Moving the complete result folder to `D:` therefore made the otherwise valid
  package fail with `稳定终稿字幕文件不存在`.
- The loader now resolves only the recorded file name and one recorded artifact
  subdirectory under the manifest-owned package. Subtitle, edit-journal, page,
  and ledger SHA-256 values remain authoritative; a mismatch still fails closed
  and cannot fall back to an unrelated stable package.
- A moved package can be reopened from its manifest, parent bilingual SRT, or
  actual-page bilingual SRT. The original absolute paths are not rewritten as a
  side effect of loading.
- Background save no longer deep-copies the append-only history payload. It
  freezes the mutable ledger, cues, pages, overrides, recovered drafts, and trim
  state while the disabled UI prevents concurrent edits. The real 258-cue,
  311-row Hollywood package improved from about 404ms to 22ms for snapshot
  creation; cross-parent merge improved from about 1.15s to 0.82s by avoiding a
  second full-history copy.
- Direct manual-editor tests, stable publication/UI 63/63, syntax compilation,
  `git diff --check`, and the complete 25-stage regression pass; the unified
  regression took 425.6 seconds. Publication remains file-by-file, and delta
  history, redo, crash recovery, and real GUI workflow validation are not yet
  complete.

## 2026-08-12 Authoritative Parent-Chinese Replay Gate

- Stable production now writes `authoritative-parent-chinese.json`, binding each
  fixed parent subtitle ID to its frozen English hash, word span, Chinese hash,
  provenance, and record hash. Parent SRT, translations, and display-page
  Chinese must reference the same record; conflicting copies fail closed.
- The two requested moved production packages are older schema-v2 artifacts and
  do not contain that new file. Compatibility loading reconstructs an in-memory
  authority record only after the existing parent, translation, and page data
  agree; it does not rewrite or upgrade the package during replay.
- Read-only replay passed for `如何停止拖延-处理结果` (283 cues, 3126 ledger
  words, 97 history entries) and `中国已成为世界石油强国-处理结果` (170 cues,
  1676 ledger words, 66 history entries). Undo then redo restored the exact
  in-memory cue projection for both packages. A recursive mtime, size, and
  SHA-256 snapshot before and after replay was identical.
- Focused authority regressions pass. This gate performed no ASR, LLM,
  translation, synthesis, network request, cache write, or production artifact
  write.

## 2026-08-12 Legacy Blocked-Checkpoint Compatibility

- The first full regression after the authority contract exposed one real
  compatibility boundary: a render-blocked editable checkpoint may contain the
  frozen parent Chinese but no `translations.json`, because display-page
  translation failed before that artifact was published. Treating that as a
  corrupt published package broke checkpoint reopening and the renamed-subtitle
  synthesis path.
- The loader now permits this missing file only when the manifest explicitly
  marks `editable_checkpoint` or `render_blocked`. It reconstructs a temporary
  in-memory authority record from the frozen parent cues; the next successful
  manual save writes the complete authority and translation artifacts. Published
  packages and schema-4 manual finals remain fail-closed.
- `tests/test_video_synthesis_safety.py` and `tests/test_stable_publication.py`
  pass after the fix. The subsequent full regression reports no failed stage and
  ends with `Regression command completed.`; `git diff --check` passes.

## 2026-08-13 User Result Directory Layout

- Newly generated `<media-stem>-处理结果/` directories are separated into
  `字幕文件/`, `质检报告/`, `视频成片/`, and `人工终稿字幕包/`. Subtitle text,
  IDs, page plans, word timing, font selection, and rendered content are
  unchanged; only user-facing output locations changed.
- Existing flat result directories are neither migrated nor deleted and retain
  their legacy read paths. New subtitles can find a sibling manual-final
  manifest only when the selected path or SHA-256 is explicitly recorded by
  that manifest, so an unrelated SRT cannot acquire a package word ledger.
- Normal `打开输出文件夹` opens the result root. An active manual-final editor
  retains its separate `打开终稿文件夹` behavior and opens the manifest-owned
  package. No extra loose copy of `人工终稿字幕.srt` is created.
- A temporary copy of the real `AI竞赛：中美殊途-处理结果` schema-4 package
  reopened 226 parent cues and 265 display pages from its manifest. Both legacy
  root subtitle entry points resolved the same package, synthesis input
  resolution passed, and all 21 source files retained their original size.
- Focused task-context tests pass 8/8, stable publication/UI tests pass 70/70,
  syntax checks and `git diff --check` pass, and the complete 25-stage
  regression passes in 354.6 seconds.

## 2026-08-13 Recoverable Failure And Short-Timing Hardening

- An optional Chinese allocation quality retry can no longer turn a complete
  original fixed-ID allocation into a global `translation_id_unknown`
  failure. A malformed candidate is retained as attempt evidence and an
  unresolved review item; initial allocation and final fixed-ID errors still
  block publication.
- The frozen-ledger final timeline is now the only owner of short subtitle
  display repair. It borrows only non-word time, keeps every word timestamp,
  ID, English text, word span, and order unchanged, targets 700ms, and blocks
  export if even a 150ms display cannot be represented safely.
- Offline replay of the failed `AI竞赛：中美殊途` artifacts passed for all 226
  cues with unchanged ID/word ranges and no timeline errors. `S0105` changed
  from 120ms to 700ms and `S0198` from 120ms to 360ms; the resulting minimum
  cue duration was 360ms.
- Failed results are no longer made editable by an error-code whitelist. A
  checkpoint requires complete ordered spans, a complete word ledger, Chinese
  for every frozen parent ID, and a PASS final cue timeline. The written
  manifest must also reopen through `ManualFinalSubtitleSession`; damaged
  authority remains fail-closed.
- A temporary replay of the same 226-cue artifacts produced a render-blocked
  checkpoint which reopened all cues through the real manual editor loader;
  no source production artifact was changed.
- Focused retry, timeline, checkpoint, syntax, and real-loader tests pass. The
  final complete 25-stage regression passes in 405.4 seconds without network
  calls.

## 2026-08-13 Chinese Validation Prompts

- Stable English error codes remain unchanged in JSON artifacts, manifests,
  caches, and validation contracts. A single presentation helper now converts
  those codes and English diagnostic reasons into concise Chinese text at the
  manual-editor boundary.
- Table tooltips, manual page-boundary warnings, manual-final render blockers,
  and blocking optimization messages now explain what happened, what the user
  should check, and the affected subtitle/page ID when available. Legacy
  artifacts receive the same conversion when reopened.
- Unknown future codes display a generic Chinese review instruction instead of
  leaking an unexplained internal identifier. This is presentation-only: mark
  severity, review counts, subtitle data, timing, page plans, and publication
  gates are unchanged.
- Focused prompt, review-mark, and stable-publication tests pass; the complete
  26-stage regression passes in 405.5 seconds, and `git diff --check` passes.

## 2026-08-13 Manual Review Dialog Theme And Queue Focus

- The long-caption review queue and parent-local candidate dialog now apply an
  explicit light/dark palette to their native Qt dialog, list, selection, and
  button surfaces. This is presentation-only and does not change candidate
  generation, page boundaries, subtitle text, timing, or render contracts.
- The long-caption queue remembers the selected frozen parent subtitle ID for
  the current editor session. Reopening selects the same item; if an edit
  removes that parent from the risk queue, selection stays at the nearest
  remaining row instead of returning to the first item. Loading another
  subtitle session clears this remembered identity.

## 2026-08-14 Evidence-Bound Recovery And Review

- Display-page Chinese recovery keeps every validated parent from the first
  response and retries only the complete page set of failed parent IDs. A
  successful local retry is merged by page ID and revalidated against the
  original full contract before writeback. The `S0187` failure in
  `心理治疗，中国社会的奢侈品` no longer sends all 26 multi-page parents through
  a second request.
- Article ASR correction policy v3 adds conservative evidence paths for
  one-word Chinese/local/transliterated terms and adjacent person titles.
  Canonical and alias article evidence plus local context must agree; ordinary
  technical terms and already-correct canonical surfaces remain protected.
- The semantic review queue now detects exact numeric currency-unit conflicts
  supported by article evidence. It writes an ID-bound manual suggestion and
  never silently changes authoritative Chinese; bare numbers receive no
  guessed currency.
- Read-only production replay applied only three `fudaoke` corrections and one
  `Yuan Chengmei` correction through the new paths, and produced the `S0053`
  suggestion `每次75美元`. It wrote no production artifact. The complete
  26-stage regression passes in 408.1 seconds.

## 2026-08-14 Fixed-ID Review And Page-Boundary Completion

- High-signal semantic-review items can now request optional Chinese polish in
  a background worker. Results are cached by fixed IDs, exact English, current
  Chinese hash, context, protected anchors, model, and prompt version. They are
  never applied automatically.
- Manual application first commits the active table editor, then validates the
  complete selected suggestion set again. A stale Chinese hash, source echo,
  number, explicit currency unit, negation, person, or terminology mismatch
  rejects the result before any row changes.
- Loading another subtitle package invalidates the previous review worker. A
  completed worker merges only into the same unchanged review-queue item; it
  cannot overwrite a regenerated or reordered queue.
- Nearby actual-page cuts are now presented as `recommended`, `review`, or
  `blocked`. Soft grammar risks such as a coordinated-constituent split remain
  manually selectable but are no longer described as safe; hard grammar,
  sub-900ms, and too-short-page candidates stay blocked.
- The final English-boundary audit schema is v2 and projects parent cue edges,
  final display-page edges, and unresolved pre-ID evidence. Display-page and
  frozen fallback risks become high-confidence editor review marks without
  changing publication or renderer authority.
- Parent-local undo restores only the chosen parent and survives recovery while
  preserving unrelated later edits. Cross-parent edits, word-ledger changes,
  and tail trimming remain whole-document undo because partial restoration
  would desynchronize subtitles or audio.
- Read-only replay of the existing psychology episode preserved 195 parent
  IDs, cue spans, 2,088 words, English, and timing. Current code projects 208
  audited boundaries: 187 allow and 21 review. No production artifact or paid
  service was used.
- Focused UI, suggestion, queue, boundary, publication, and manual-editor tests
  pass. The complete 26-stage regression passes in 372.3 seconds and
  `git diff --check` passes.

## 2026-08-14 Article ASR Correction Scope V4

- Production logs reproduced two article-assisted false rewrites:
  `Red Sea -> Russia` and three `network(s) -> New York` replacements.
  The first collapsed an already entity-shaped multiword source using only
  phonetic similarity; the second treated an ordinary lowercase word as a
  complete multiword entity.
- Policy v4 rejects weak lowercase one-token expansion and unrelated
  multiword-entity contraction before fuzzy article correction. An evidenced
  exact canonical name or alias is also protected from a different glossary
  owner. Valid compact/split corrections such as
  `MixueBingcheng -> Mixue Bingcheng` and `A Drift -> Adrift` remain
  covered by regression tests.
- Candidates below the automatic threshold are not applied. Only high-signal,
  entity-shaped review candidates are deduplicated, mapped by timestamp to
  frozen subtitle IDs, and written as
  `article-asr-correction-review.json`. The editor loads them as read-only
  English review marks only when the artifact word-ledger hash matches the
  current package.
- Read-only replay of `石油市场，现在中国说了算？` and
  `蜜雪冰城为何卖起了啤酒` preserved `Red Sea` and all three
  `network(s)` surfaces. `Felugia/Fallugia -> Fulujia` remains review-only.
  The correction policy version bump invalidates reusable v3 correction output
  while preserving raw-ASR and article-analysis caches.
- All 48 focused article/thread correction tests, focused review-mark tests, syntax checks,
  `git diff --check`, and the complete 26-stage regression pass. The unified
  run took 352.6 seconds. No ASR, LLM, translation, synthesis, paid request, or
  production artifact write was performed.

## 2026-08-17 Manual Final Boundary, Page, ASR, And Media-Mute Hardening

- The last visible row now resolves to its upper fixed or display-page boundary;
  a single parent with multiple pages can also adjust its internal boundary.
- Context-menu split, repage, and merge mutations are queued out of the native
  menu callback and capture stable parent/page IDs instead of `QModelIndex` or
  stale row numbers, removing the known model-reset re-entry path behind the
  Windows last-row split crash.
- Automatic pagination remains capped at four pages. Explicit manual actions may
  create up to six pages, and the on-demand manual candidate workspace can
  inspect two-to-six-page alternatives. Both preserve fixed English, IDs, word
  coverage, timing, and the existing validation contract.
- Article ASR correction policy v5 can collapse an article-evidenced two-token
  work title only when phonetic and local article context both agree. The real
  `new lie -> Niulai` spans correct before IDs freeze; high-signal `Yulai`
  remains review-only instead of being silently rewritten.
- The editor now offers `隐藏整条字幕并静音这段`. Saving creates a SHA-256-bound,
  duration-preserving derived AAC with the exact parent cue intervals muted.
  It preserves the original media, subtitle/word timeline, and video duration,
  supports whole-document undo/redo, is mutually exclusive with tail trim, and
  is resolved again inside `VideoSynthesisThread` before rendering.
- Focused ASR, editor, publication/UI, synthesis-safety, real FFmpeg mute, and
  manual candidate tests pass. The final complete regression command and
  `git diff --check` both exit zero.

## 2026-08-17 Multiword Surface, Combined Media Derivation, And English Copy

- The manual editor now owns a presentation-only `english_surface_overrides`
  projection. A continuous raw-word span such as `New Ally` can display as
  `Niulai` without changing the raw ledger, word IDs, word times, subtitle IDs,
  or cue/page ownership. Ordinary one-word edits, parent merges, boundary
  moves, tail deletion, save/reload, undo, and redo rebuild through the same
  display projection instead of silently restoring raw surfaces.
- Tail deletion rejects a cut inside a display override, preserves a complete
  retained override, and removes a complete suffix override. Old mute-only
  packages recover their hash-bound original media before a later tail cut.
- Schema-v2 media derivation permits ordered mute intervals plus an optional
  suffix cut in one FFmpeg filter chain. The original media remains the only
  derivation source; synthesis resolves the manifest-owned derivative.
- The subtitle table supports ordered multi-row English copy through `Ctrl+C`
  and `复制英文`. Copying does not mutate the table, edit session, history,
  page contract, or timeline.
- Focused manual-editor, publication/UI, synthesis-safety, page-translation,
  and display-readability contracts pass before the final unified regression.
