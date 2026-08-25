# Pipeline

## Stage 1: Transcription

Input:

- Audio file.

Output:

- Original ASR subtitle file.
- Word-level timestamp data when enabled.

Important rules:

- CUDA should be preferred when available.
- ASR may miss speech or create overly short word timings.
- Word-level timestamps are useful but not perfectly reliable.
- Faster-Whisper word-timestamp output is checked for internal 1.8-15 second
  gaps before any English boundary or ID is frozen. A gap is locally
  retranscribed without previous-text conditioning only when FFmpeg confirms
  audio activity. New words are inserted only when exact text anchors match on
  both sides; an unanchored local result cannot mutate the transcript and now
  hard-blocks the stable word-timestamp pipeline. Empty and short local
  retries are blockers too, so confirmed speech cannot silently disappear
  from the frozen English ledger.
- Native Faster-Whisper word timing is also checked for implausibly compressed
  local runs before it becomes cache or ledger authority. A bounded
  context-free retranscription may restore only the timing and acoustic order
  of the same word multiset between unique exact anchors; it cannot add,
  remove, or rewrite words. Millisecond zero-width repair preserves emitted
  word order. Unanchored, text-changing, or still-compressed results remain
  blocked, while a successful repair replaces the stale raw ASR cache value.
- A physically impossible terminal word burst has one narrower recovery path.
  It must begin after a sentence boundary, remain inside the existing
  compressed-timing limits, and a context-free local retranscription must end
  at a unique exact left text anchor without emitting any candidate-tail word.
  Only then is the unconfirmed terminal burst quarantined as an ASR
  hallucination. If local ASR hears any following word, or the anchor is
  absent or ambiguous, the transcript remains unchanged and the timing gate
  still blocks publication.
- Article-assisted ASR correction runs before stable English boundaries freeze.
  Fresh, cached, and UI-supplied article analysis must all be enriched with
  source evidence in memory before either ASR correction or the translation
  glossary consumes it; writing an enriched artifact alone is not sufficient.
  A `technical_terms` entry is eligible only when the canonical form is
  evidenced in the article and the term is distinctive or has an evidenced
  alias. Automatic replacement still requires high spelling and phonetic
  similarity; an ordinary technical word is not a fuzzy rewrite authority.
  Correction changes token surface text only and preserves the original word
  times.
  A multi-token source phrase containing ordinary function words cannot be
  collapsed into a one-token named entity by fuzzy similarity alone. Exact
  orthographic joins remain eligible, and a genuine occurrence of the same
  named entity elsewhere remains unchanged.
  A one-token Chinese/local/transliterated term has one narrower exception: a
  two- or three-token phonetic ASR surface may be corrected only when the
  article evidences the canonical term and an explanatory alias, and local
  definition or article-description context agrees. General technical words
  and a window already containing the canonical term are excluded. A person
  title may come from the immediately preceding word only when an
  article-supported title alias and descriptive context agree.
  A fuzzy correction may replace only its entity-owned source span. When the
  complete canonical entity already exists inside or immediately beside a
  candidate window, the candidate cannot consume a neighbouring discourse
  word, title, or other source token.

## Stage 2: Stable English Segmentation

Input:

- Word-level timestamp sequence.

Output:

- Stable English subtitle segments.

Rules:

- English text is restored locally from word ranges.
- LLM must not rewrite, delete, reorder, or invent English.
- Preferred visual target is 6-12 words; the normal hard maximum is 16. A 17-19 word exception requires an audited parser-confirmed grammar constraint. When an otherwise complete terminal source sentence has no legal normal-limit temporal cut, it remains one renderer-owned cue and is reported as a structural reading warning rather than being cut into a fragment.
- Preserve source order and token coverage.
- Prefer clause, punctuation, discourse, and phrase boundaries.
- Avoid cutting after prepositions, articles, auxiliaries, or connectors.
- The 12-word/68-character visual reading target never creates a formal cue
  boundary. A long, grammatically complete cue remains one fixed English item
  until renderer-only pagination projects it into readable pages. That display
  projection cannot change fixed IDs, Chinese allocation, SRT/ASS, or timing.
- The same pre-ID finalizer may rebalance a short, parser-confirmed non-finite
  conditional prefix from the start of one cue to the preceding incomplete
  clause. It requires continuity, one speaker, a sub-450ms pause, a complete
  following main clause, and both resulting cues within the hard word limit.

## Stage 3: Semantic Chinese Translation

Input:

- Fixed English subtitle segments.
- Semantic groups built from adjacent English parts.

Output:

- Chinese subtitle per fixed English part.

Rules:

- Full group translation comes first.
- Full translation v6 writes compact one-glance documentary Chinese at the
  semantic owner. Its request includes fixed subtitle IDs, exact English,
  word-ledger display durations, advisory per-ID budgets, and their summed
  semantic-group budget. It may remove meaning-free conversational or written
  scaffolding and redundant explicit subjects, but it must preserve facts,
  entities, numbers, negation, causal/contrast relations, modality, reactions,
  hedges, and speaker stance. The target budget is soft; this is concise
  translation, not summarization or character truncation.
- Allocation maps the full Chinese meaning back to fixed global subtitle IDs.
- Under the configured two-model role policy (supported by DeepSeek and
  OpenCode Go), complete semantic-group translation uses the configured
  full-translation model. DeepSeek official currently uses Pro for this role
  and Flash for ordinary allocation/page translation; OpenCode Go currently
  uses Flash for every translation role. A deterministic high-risk quality
  retry still uses the configured full-translation model for the affected
  group.
- A full-translation batch may publish a validated subset when the provider
  omits other group IDs. Valid ID/source-echo/translation records are cached as
  a resumable checkpoint; duplicate, unknown, empty, or source-mismatched
  records are discarded. Only missing groups enter bounded `8 -> 4 -> 2 -> 1`
  repair batches, with at most 12 repair requests per run.
- Initial full-translation work uses rolling batches of at most eight semantic
  groups and at most two in-flight requests. Each initial batch gets one HTTP
  attempt; every valid completion is validated and written to its unit cache
  before another batch is admitted.
- Full-translation unit cache v2 follows semantic content rather than sequence
  position. Its identity includes the complete English, current translation,
  translation budget, bounded previous/next semantic context, article context,
  prompt policy, and request model. It excludes semantic-group numbers, frozen
  subtitle IDs, and internal cue boundaries. A shifted but semantically
  identical group can therefore reuse its verified translation, while any
  wording, budget, context, model, or prompt change invalidates it. Valid v1
  unit entries remain readable once and are migrated to v2 on reuse.
- Two consecutive retryable provider failures open the full-translation
  circuit and prevent unstarted batches from being submitted. Already in-flight
  requests may finish and valid results are still cached. One successful batch
  resets an earlier isolated failure; a non-retryable error or exhausted request
  budget stops admission immediately. Missing groups are reported as
  `semantic_full_translation_provider_unavailable` and a rerun resumes from the
  completed unit caches.
- The screen editor disables OpenAI SDK retries. Application code is the only
  retry owner, so one recorded external attempt equals one provider request.
- English IDs, timing, and order are immutable during Chinese translation.
- Missing Chinese is a validation issue.
- LLM allocation responses must include `subtitle_id` for each returned Chinese line.
- Returned, missing, duplicate, and unknown subtitle IDs are recorded as structure errors.
- After allocation, every frozen subtitle ID must own non-empty Chinese before
  the authority/artifact stage begins. A provider failure therefore stops as
  `semantic_chinese_incomplete`, reports the exact missing IDs and provider
  reason, and leaves completed unit caches reusable; it cannot continue and be
  misreported as an authoritative-parent artifact failure.
- Chinese cache identity includes the model that owns the current request, not
  unrelated model roles. A Flash allocation-model change therefore does not
  invalidate verified Pro full translations.

## Stage 4: Timing and Display Stabilization

Input:

- Fixed English/Chinese subtitle segments.

Output:

- Final display-timed subtitle segments.

Rules:

- The final word ledger is the only timing authority after English boundaries
  and IDs are frozen.
- Each final cue is derived from its own `subtitle_id -> [word_start, word_end]`
  envelope. WhisperX may update ledger word times but cannot map final cue text
  to a separate time range.
- Stable-ts and WhisperX updates are rejected locally when four words occupy no
  more than 250ms, or eight words occupy no more than 750ms at ten or more
  words per second. The detector selects the smallest anomalous core, expands
  only words collapsed inside that same time envelope, restores their trusted
  upstream times, and reruns detection. An implausible upstream ledger cannot
  authorize a fallback and blocks final timeline export.
- WhisperX may not erase a trusted pause before an expansion-sensitive written
  token such as a number, percentage, currency form, or acronym. When the
  aligner stretches the preceding word across a 200ms-or-longer upstream pause
  and would delay the token onset by at least 150ms without a corroborating
  local shift, only the two words owning that boundary revert to their trusted
  upstream times.
- A padding overlap may be reconciled only at a shared boundary that stays
  between the adjacent word envelopes.
- The same final cue timeline owns parent-cue chaining. When adjacent frozen
  word envelopes have a positive pause below 1000ms and the padded display
  ranges still leave a visible gap, the outgoing cue receives roughly 75% of
  that pause and the incoming cue may start early by at most 200ms. Both cues
  meet at one shared display boundary. A word pause of 1000ms or more remains
  visible; word timestamps and word envelopes never move.
- The final cue timeline also owns short display-range repair. It first
  preserves a 150ms hard minimum for every internal cue, then uses only
  non-word time between adjacent word envelopes to approach a 700ms soft
  target. Word timestamps never change; if the hard minimum cannot be met
  without overlap or cutting speech, final export fails with an explicit
  timeline error.
- Do not change English text, Chinese text, subtitle ID, word range, or order.
- Later stabilization stages may audit display coverage but must not retime a
  cue already published by the final timeline.
- Missing, duplicate, unknown, or synthetic final timeline IDs are ERRORs and
  block export.

After the final word ledger and cue timeline pass, the article renderer may
enumerate multipage display spans. Every span receives a deterministic child
ID such as `S0078.P01`. Chinese for those spans is returned by exact child ID,
validated, and attached as an independent display projection. The unchanged
parent cue remains the semantic authority; page-local Chinese may use more
natural word order and does not write back into it. Every new page projection
is bound to the exact source-parent Chinese text/hash that created it. A legacy
projection without that reference is accepted only when its ordered page
Chinese exactly reconstructs the current parent Chinese. Missing, stale,
tampered, semantically invalid, or unschedulable page data blocks rendering;
there is no proportional-character fallback.
If deterministic page-Chinese validation fails, only the complete page set of
the affected parent IDs is retried. Already validated parents remain frozen;
the local result must pass its sub-contract and the merged response must pass
the original full contract before the page projection is attached. Under the
configured two-model role policy the ordinary page request uses the
allocation/review model
and a naturalness or semantic retry uses the full-translation model. A residual
non-blocking continuation after that retry stays explicit REVIEW evidence and
cannot replace the authoritative parent translation.
Each validated parent page set also has an independent content-bound unit
cache. Its identity includes parent English and authoritative Chinese, every
page English span, page duration and Chinese budget, article context, prompt,
algorithm, and model, but not parent/page IDs or absolute word-number offsets.
A hit is rebound to current `Sxxxx.Pxx` IDs and must pass the complete current
page contract and quality validation before use. Parent Chinese, page English,
timing budget, or policy changes invalidate the unit.
Missing, duplicate, or cardinality-mismatched page IDs are scoped to the
affected parent whenever the page IDs identify that parent. Unknown IDs or
otherwise unscoped malformed responses still retry the complete contract.
The validator retains independently complete parents as review-only evidence
while the full artifact remains `ERROR`; only a complete merged contract can
update authoritative parent Chinese. A retry request failure preserves the
accepted parents and records its exact parent scope for manual review.

## Stage 5: Validation and Artifacts

Outputs:

- `*-coverage-report.txt`
- `*-artifacts/`
- `validation-report.json`
- `translations.json`
- `subtitle-spans.json`
- `word-ledger.json`
- `semantic-groups.json`
- `allocation-inputs.json`
- `allocation-raw-returns.json`
- `allocation-validation.json`
- `allocation-retry-log.json`
- `allocation-final.json`
- `allocation-unresolved.json`
- `translation-structure-errors.json`
- `final-cue-timeline.json`
- `display-page-translations.json`
- `english-boundary-audit.json`
- `translation-quality-audit.json`
- `editor-review-ledger.json`
- `llm-request-ledger.json`
- `run-state.json`

Run-state rules:

- It is a progress/recovery record, never a subtitle source of truth.
- It hashes the input subtitle, article state, relevant stable configuration,
  model/prompt values, and selected timing backend.
- A stage artifact is reusable only when its recorded digest and full input
  fingerprint match; otherwise the normal stage executes.
- Existing LLM batch caches may be reused under their current cache keys, but
  completion order never controls translation or subtitle writeback order.
- Display-page Chinese requests are bounded to at most six parent subtitles
  and twelve actual pages per batch. Each valid batch is cached independently,
  so a later timeout does not discard earlier completed work and a rerun asks
  only for batches that are still missing. A valid legacy whole-contract cache
  remains reusable; all batch rows are merged and validated once against the
  original complete display-page contract before publication.
- Page batches use a bounded completion-order scheduler with at most two active
  external requests. Every completed batch is validated and cached immediately,
  and batch completion, cache hits, retries, active requests, failures, and
  elapsed time are emitted to the run-state/GUI progress channel. Final merge
  order still follows the frozen contract rather than completion order.
- When a page batch exhausts its bounded attempts, no later batch is admitted.
  An already active request is allowed to settle because an in-flight HTTP call
  cannot be safely revoked, but every not-yet-started batch remains cancelled.
  The page artifact records the explicit failure and any independently valid
  completed parents for checkpoint recovery.
- The configured request budget is enforced independently for
  `screen_subtitle_edit` and `display_page_translation`. Translation/allocation
  attempts therefore cannot consume the later page-stage allowance. The
  manifest records attempts used and remaining allowance by stage.
- `llm-request-ledger.json` is atomically updated after each cache lookup or
  external request. It records task, model, attempt, latency, provider token
  usage, prompt-cache tokens, and reasoning tokens when returned by the API;
  it never stores prompts or API credentials.
- A malformed optional allocation-quality retry is rejected locally. The
  original complete fixed-ID allocation remains authoritative, while the
  failed candidate and unresolved quality issue remain review evidence. This
  does not relax initial allocation or final fixed-ID validation.
- After actual display pages freeze, OpenCode Flash runs three independent,
  read-only audits: accuracy/ASR, Chinese fluency/page load, and adjacent
  mapping/continuity. Each cached request owns at most 40 target IDs plus one
  adjacent context row on each side. Every target ID must be acknowledged in
  all three passes; otherwise the stable run remains incomplete and retry
  reuses completed batches.
- If display-page translation has already failed, the quality audit is marked
  `SKIPPED` and makes no external request. The pipeline publishes the recoverable
  checkpoint and page-stage evidence first instead of spending more time and
  request allowance on an output that cannot yet be finalized.
- Model findings cannot mutate English, Chinese, IDs, word ownership, timing,
  or page geometry. Semantic, mapping, number, negation, and ASR findings must
  quote an exact English source span; the local validator rejects ungrounded
  evidence and optional discourse-marker omissions. Cross-row coherence
  evidence must bind exactly two adjacent fixed IDs, including a batch-edge
  context ID when needed. A model length finding enters the editor only when
  local actual-page character count or reading speed also exceeds its limit.
- `editor-review-ledger.json` is generated after all evidence owners finish.
  It groups multiple evidence records that require the same human action and
  is the editor's primary frozen review queue.

Validation checks:

- English coverage gaps.
- Whole-file English boundary audit v2 projects parent cue edges, selected
  display-page edges, and unresolved pre-ID evidence from the same frozen word
  ledger. Parent `hard` atomic splits with no contrary timing/speaker evidence
  must be repaired before IDs and block export. Final display-page fallback
  risks remain `review` evidence for the editor; independently supported
  `allow` boundaries remain untouched.
- Missing Chinese.
- Overlong English.
- Translation ID mismatch, missing ID, duplicate ID, unknown ID, or group cardinality mismatch.
- Suspicious cuts.
- Exact numeric currency-unit conflicts supported by article evidence are
  emitted as ID-bound semantic review suggestions only for a unique number in
  explicit money context with one complete unit occurrence. Repeated values,
  count nouns, and ambiguous compound units remain manual review. Suggestions
  never auto-mutate authoritative Chinese; parent-ID suggestions are applied
  in parent view, not to an arbitrary child page.
- Timing gaps and very short displays through audit scripts.

## Stage 6: Stable Final Subtitle Outputs

Output files:

- `stable-final-original-top.srt`
- `stable-final-translation-top.srt`
- `stable-final-only-original.srt`
- `stable-final-only-translation.srt`
- `stable-final-manifest.json`

Rule:

- Video synthesis should use the manifest path first.
- Do not rely on fuzzy localized file-name search when a manifest exists.
- A render-blocked result is exposed as an editable checkpoint only when its
  complete frozen ID order, subtitle spans, word ledger, Chinese parents, and
  final cue timeline pass the same structural contracts used by the editor.
  The newly written checkpoint is opened once by the real loader before its
  path is published. Corrupt or incomplete authority remains unavailable.
- A checkpoint snapshot retains `semantic-review-queue.json` only when the
  queue binds to the copied word ledger and complete frozen English spans.
  An identity-mismatched copied queue is removed from the new checkpoint while
  the historical source directory remains unchanged.

### Manual final checkpoint

- The subtitle editor loads the stable SRT together with its frozen word
  ledger, final cue timeline, fixed-ID Chinese mapping, page contract, and
  existing audit artifacts. Existing artifacts are the checkpoint; reopening
  them does not rerun ASR, translation, or English segmentation.
- The editor's `More` menu can discover recent stable runs, editable failure
  checkpoints, and manual packages below the configured work directory. It
  also checks the deterministic manual-package directory beside each declared
  source media file. It loads the selected manifest directly and never starts
  ASR, translation, allocation, or pagination. Live aliases are deduplicated,
  then all historical runs for one episode title are collapsed to one current
  entry. An unsaved draft wins; otherwise the newest result wins.
- Closing a dirty editor session writes an atomic working draft bound to the
  exact base manifest and subtitle hashes. Reopening that result restores the
  draft automatically. A clean close writes nothing, and a draft-write failure
  requires an explicit exit-with-loss decision rather than silently discarding
  edits.
- Review highlighting is intentionally narrow: structural blockers, genuine
  parent/page boundary risks, abnormal cue-edge alignment fallback, locally
  verified actual-page Chinese load, high-confidence ASR findings, and
  model-confirmed Chinese meaning/fluency/coherence problems. Routine fallback
  provenance, normal conversational fragments, duplicate evidence, and
  low-confidence parser guesses are not separate editor tasks.
- High-signal Chinese review items may start an optional background model
  request. The response is suggestion-only and bound to fixed IDs, exact
  English source echo, current-Chinese hash, and protected fact/term anchors.
  The active table editor is committed before the hash is revalidated, and the
  complete selected suggestion set applies atomically or not at all. Loading a
  different package or changing the review queue invalidates an in-flight
  result; a stale worker cannot overwrite current rows or queue items.
- The table, pending page edits, and published package have separate ownership.
  Table text is committed into one in-memory session before any structural
  action. Repeated page splits and page-Chinese edits remain in that session;
  only the explicit manual-final save snapshots, validates, and publishes it.
- An empty page translation is a legal editing checkpoint, not a formal final.
  It may be persisted for later continuation while the manifest remains
  render-blocked. Formal and draft synthesis capabilities are derived only from
  the saved manifest after the existing gates run.
- Page review acknowledgement is explicit state, not a parser verdict. Editing
  non-empty page Chinese acknowledges that exact page; moving a page boundary
  acknowledges the resulting boundary. The user may also acknowledge one
  unchanged item or all non-blocking items. Acknowledgement is valid only for
  the same page ID, parent ID, frozen English, and word range.
- Unacknowledged Chinese and REVIEW boundaries block formal publication but do
  not become structural corruption. When every fixed-ID, ledger, timeline,
  page-identity, layout, and media invariant is valid, the saved manifest may
  authorize the isolated manual-draft path.
- A translation-blocked manual checkpoint retains its frozen page geometry.
  Saving or reopening it must not call the automatic planner merely because
  Chinese remains unconfirmed; page-count or word-range changes require an
  explicit manual operation.
- Artifact review evidence is immutable input, not the current edit state.
  Marks for an edited fixed subtitle identity are filtered, while current
  manual Chinese flags, REVIEW page-boundary metadata, and unavailable pages
  are projected directly into table highlighting and next-review navigation.
- Saving writes a separate `人工终稿字幕包/` containing the edited bilingual
  SRT, word ledger, final cue timeline, page translations, edit history, and a
  SHA-256-bound `stable-final-manifest.json`. It never overwrites the original
  stable package.
- Before media derivation or subtitle export, manual-final save rebuilds every
  current parent display range from its continuous frozen-word span through the
  same final-cue timeline as normal production. Derived mute intervals, parent
  SRT, page plans/maps, and `final-cue-timeline.json` therefore consume one
  authoritative timing result after a formal parent-boundary move.
- A manual English correction may replace the surface of one frozen word ID,
  or map one continuous range of two or more frozen word IDs to one
  presentation-only surface. The raw ledger text, word IDs, order, word times,
  cue/page spans, and subtitle IDs remain unchanged. A many-to-one override
  cannot cross a cue or page boundary and that override remains bound through
  later merge, boundary, tail-trim, save/reload, undo, and redo operations.
  Arbitrary multi-ID free rewriting remains rejected and affected Chinese is
  marked for confirmation. The parent/actual-page context menu exposes an
  explicit `修正当前英文（保持时间轴）` dialog so this operation does not depend
  on the table delegate's unreliable inline double-click editor.
- Selected visible English rows can be copied through `Ctrl+C` or the
  `复制英文` context-menu action. Copying is read-only: it does not write the
  table model, session, edit history, page state, or timeline.
- A parent cue may be marked `display_suppressed`. Its visible SRT and page
  plan entries are omitted, but its fixed subtitle ID, word range, word times,
  and final-timeline record remain authoritative. This operation never trims
  or rewrites source media.
- A separate parent-level operation may set both `display_suppressed` and
  `media_muted`. Saving uses one schema-v2 media derivation whose optional
  mute intervals run before its optional suffix-only `atrim`, followed by
  `asetpts`. It always derives once from the hash-bound original media, never
  from an older derivative. The decision binds the original-media SHA-256,
  cue IDs and times, current word-ledger hash, optional cut, decision hash,
  and derived-media SHA-256. Subtitle IDs and retained word/cue times do not
  shift. Page-only mute remains unsupported; legacy one-operation packages
  remain readable and are upgraded on the next save.
- A complete-parent timeline deletion is separate from hiding or muting. The
  editor requires every display-page row for a selected parent, rejects
  page-only deletion, mixed delete states, and deleting every parent, and
  records `timeline_deleted` without changing source authority. On save,
  schema-v3 `media_derivation` stores canonical deleted intervals and retained
  source slices. FFmpeg concatenates those slices from the original source;
  subsequent cue, page, and word-card times are mapped to the compacted clock
  by subtracting deleted duration before each source timestamp. Deleted cues
  remain provenance records but are omitted from rendered SRT/ASS. The
  manifest binds the derived audio and presentation timeline by hash, and
  synthesis fails closed on stale, tampered, incomplete, or all-deleted
  contracts. Restoring the parents returns the normal source timeline.
- Manual-final imports have explicit checkpoint semantics. Importing
  `*-人工终稿字幕.srt` continues the latest hash-bound manual package. Importing
  `*-原文在上双语字幕.srt` starts again from the immutable stable parent
  checkpoint. Importing `*-实际分页双语字幕.srt` is a page snapshot, not a reset
  command; when a matching manual package exists, it resolves to that latest
  package and can recover only exact identity-matched page Chinese as an
  unconfirmed draft.
- The manual override binds the edit journal by SHA-256. Reload verifies that
  journal, its embedded ledger, and the package ledger agree before accepting
  edits, preventing a journal from being reused with another checkpoint.
- A source-folder `*-实际分页双语字幕.srt` may outlive the page plan that created
  it. On import, the editor verifies the adjacent page-map hash, resolves that
  map's parent subtitle to the latest matching manual manifest, and opens the
  current parent package. Obsolete page structure is never reused as current
  authority. Chinese from an exactly identity-matched old page may be shown
  only as an unconfirmed review draft; changed page spans stay empty.
- The full deterministic page preflight runs in a background worker when the
  user saves. The editor table and manual-final actions stay locked until the
  snapshot finishes, so a long page plan cannot freeze the Qt event loop or
  race with later edits. The main window refuses to exit while that worker is
  publishing the package. This changes execution ownership only; it does not
  weaken the render gate or change page selection.
- When a complete frozen page artifact is available, the editor defaults to a
  flat `one display page = one row` view. The table remains four columns
  (start, end, English, Chinese); it does not add a repeated page-count column.
  Every visible row retains its deterministic page ID, parent subtitle ID,
  continuous word span, page time, and selected font size in the model.
- Page-view Chinese can be edited directly and is aggregated back to its
  unchanged parent subtitle ID. Page-view English remains frozen. A parent
  view toggle retains the existing word-ledger-backed formal-boundary tools.
  Saving page-only Chinese edits reuses the same hash-bound page artifact and
  never invokes a new page plan; page-ID or word-span drift blocks the save.
- A formal parent-boundary edit owns only the two affected parent cues. If its
  local page rebuild fails, cue state, page rows, boundary overrides, and edit
  history roll back together. Publication also rejects a session whose edit
  history proves manual page state existed but whose pages and overrides have
  silently collapsed to zero.
- A page-blocked manual package persists a separate
  `manual-draft-page-plan.json` during save. The manifest and manual override
  bind that artifact by path and SHA-256. It contains explicit English,
  Chinese, word ranges, page times, font layout, and boundary evidence for
  every page; the editor preview and draft renderer consume that same file.
- A page-Chinese validation failure retains the complete frozen English render
  plan and independently valid translated parents. The failed parent's page
  Chinese is not authoritative; its actual English pages remain visible and
  marked for manual completion. This recoverability never clears the formal
  render block.
- If an edit cannot preserve a verified page-level Chinese mapping, progress is
  still saved but the package remains render-blocked. The user can continue
  editing that checkpoint without rerunning the audio pipeline.
- User-facing outputs are owned by one deterministic directory:
  `<output-anchor-parent>/<source-media-stem>-处理结果/`. In the interactive
  Home workflow the output anchor is the source media itself, so this is a
  sibling of the original audio. Isolated E2E callers may keep their separate
  report anchor while retaining the original media name. New publications use
  four explicit child directories:

  ```text
  <source-media-stem>-处理结果/
    字幕文件/            # bilingual, language-only, actual-page, map, compatibility SRT
    质检报告/            # summary, QA queue, semantic-review queue
    视频成片/            # formal and manual-draft rendered videos
    人工终稿字幕包/      # root manifest and immutable generations
  ```

  For example, saving a source media file at
  `C:/Users/.../Desktop/Episode/Episode.m4a` publishes the root manual manifest
  under `C:/Users/.../Desktop/Episode/Episode-处理结果/人工终稿字幕包/`.

  Internal work directories, immutable stable-run artifacts, and source media
  stay in place. Existing loose legacy files are not moved or deleted. Legacy
  flat result directories remain readable. A subtitle under `字幕文件/` may
  discover the sibling manual-final package only when its exact path or SHA-256
  is declared by that package manifest; an unrelated SRT cannot inherit the
  package word ledger or synthesis authority.
- The manifest binds the discoverable output paths and SHA-256 digests; the
  page map binds every page ID to its parent ID, continuous word span, time
  range, English, and Chinese. Legacy source-folder subtitles remain readable
  through the existing exact-path/hash discovery rules.

Stale actual-page Chinese recovery is evidence-only. The editor first verifies
the imported SRT hash against its companion map, then verifies every page ID,
parent ID, word range, English text, Chinese text, and page time. A recovered
Chinese line is shown only when that same page identity still exists in the
current package. It is stored in the manual edit artifact as a separate
non-authoritative draft, never as current parent or page Chinese. Zero-confirm
and partial-confirm saves retain the draft for later review; any unconfirmed
draft keeps formal synthesis blocked.
- A persisted empty intermediate page edit does not suppress an identity-matched
  recovered draft. Preview shows that recovered Chinese as stale/unconfirmed,
  while the authoritative edit remains empty. Rebuilding another parent's page
  structure must preserve this stale ownership instead of silently confirming
  the displayed draft.
- Importing that discoverable SRT into either the subtitle editor or synthesis
  page resolves a package only by an exact path or SHA-256 match inside the
  configured work directory or sibling portable package. A matching blocked
  manual package may enter explicit isolated draft mode; an unmatched plain SRT
  never receives synthetic word timing.
- Selecting a parent or display-page row is non-mutating. Boundary controls are
  installed only after an explicit upper/lower boundary command; selecting a
  direction resets the count to one word and previews the exact source words.
  Only `confirm move` changes the ledger-backed boundary. Cancel and undo do not
  create a second timing implementation.
- The actual-page boundary inspector shows nearby word-ledger cuts as
  `recommended`, `review`, or `blocked`. Soft grammar-risk cuts remain an
  explicit human choice; hard syntax, insufficient duration, and too-short
  pages cannot be applied as automatic recommendations. Candidate preview
  never changes page state.
- A display-page row may request two, three, or four pages. The normal syntax,
  pause, word-time, fixed-font, and 900ms minimum-page planner must find the
  complete partition. Parent subtitle ID, English, word range, and parent timing
  remain frozen. A later explicit manual move may override only grammar and
  minimum-duration policy risks; those decisions stay REVIEW-labelled with their
  issue codes. Word coverage/order, IDs, legal shared timing, and fixed-font fit
  remain hard constraints.
- New page Chinese is intentionally empty. The editor accepts that incomplete
  state during additional boundary moves, but formal save remains blocked until
  every page has been reviewed and filled. A blocked checkpoint preserves the
  hash-bound English page plan so reopening it does not lose the user's split.
- A formal parent-boundary move invalidates old pages and exposes `refresh actual
  pages`. Refresh uses the existing background save worker. Its saved page
  artifact is the authority for preview and later saves, so an unchanged second
  save does not invoke the planner again.
- Manual-final boundary evidence is ledger-wide: the package writes one record
  for every adjacent word ID rather than only boundaries inside the current cue
  partition. Legacy filtered packages may restore omitted accepted cue edges
  from frozen current/history spans, while an unexplained internal gap remains
  a structural failure. A page-split command issued against stale parent pages
  is resumed once after the matching background refresh reloads.
- `delete from this parent to end` is a suffix-only edit. The cut is chosen in
  the word-time gap between the last retained word and the first removed word;
  retained IDs and times do not move. Save writes a derived AAC `.m4a`,
  `tail-trim.json`, hashes, and the shortened ledger/timeline into the manual
  package. It never overwrites the source audio, and an identical saved decision
  reuses the derived file.
- Row-scoped undo restores only one parent and can skip unrelated later parent
  edits without overwriting them. Operations that change multiple parents, the
  authoritative word ledger, or tail-trimmed audio remain whole-document undo;
  partial row restoration is rejected rather than desynchronizing media.

## Stage 7: Video Synthesis

Input:

- Audio/video media.
- Stable final SRT from manifest.

Output:

- Podcast learning video.

Rule:

- If rendered subtitles are wrong, first verify the resolved subtitle path.
- The interactive Home workflow stops in the subtitle editor after successful
  subtitle generation. It opens synthesis only after the user explicitly uses
  `前往视频合成` or `合成草稿`. Batch full-process tasks retain their explicit
  automatic subtitle-to-synthesis chain.
- The synthesis page accepts either a subtitle file or
  `stable-final-manifest.json`. A valid manual package restores its recorded
  source-media path when that file still exists, allowing direct synthesis
  without ASR, translation, or pagination reruns.
- A manifest carrying `tail_trim` owns its SHA-256-bound derived audio even when
  the caller still holds the original media path. The first tail-trim release is
  accepted only by the static podcast-template path; other renderers fail closed.
- A manifest carrying `media_mute` likewise owns its SHA-256-bound derived
  audio. `VideoSynthesisThread` always resolves manifest inputs before rendering,
  so a stale original-media path cannot bypass interval mute. Missing, tampered,
  or decision-mismatched media fails before rendering; the first release is
  accepted only by the static podcast-template path.
- A saved manual package that is blocked only by
  `render_structural_overflow`, `manual_page_translation_required`, or
  `manual_page_translation_invalid` may be opened through the explicit
  `manual draft` command. This command does not clear the formal render gate.
  It revalidates the schema-v2 package, owned SRT and SHA-256, final cue
  timeline, word ledger, fixed IDs, word ranges, text, and cue times before a
  previously saved REVIEW page plan is loaded. A missing, tampered, stale, or
  cross-package draft plan fails before ffmpeg; synthesis never recalculates
  pages or proportionally slices Chinese at render time. Any other blocker
  still fails closed.
  Draft authorization is valid only for the `文章单词` podcast template; it
  cannot be reused by the ordinary ASS or other podcast renderers.
  The output is `【人工草稿】<media-stem>.mp4`, so it cannot overwrite the
  formal video.
- The article-template renderer must verify the stable manifest, final cue
  timeline, word ledger, and any required display-page translation artifact
  before synthesis. The manifest binds the page artifact by SHA-256 and page
  contract hash. It plans 56px English and 48px Chinese pages inside each
  frozen cue. The complete whole-episode plan is frozen before page Chinese is
  accepted. Once validated, that plan is the only renderer authority; a
  per-cue renderer call cannot replace its page spans, font, or page IDs.
  It first keeps a whole cue on one
  static page using measured pixels: the normal 1455px English panel, then the
  1498px safe-width profile, with at most two English and two Chinese lines.
  Chinese load and a 16-word target are soft page-count signals. Measured
  English pixels, Chinese pixels, word load, and cue duration choose candidate
  page counts before any break reward is considered. A bounded cue-local
  frontier retains several distinct partitions for each page count and
  strict/review/forced fallback tier. The whole-episode dynamic program first
  selects within the locally preferred page count and may penalize adjacent
  dense pages. A final bounded dominance pass may then choose another page
  count only when it objectively improves the selected baseline: every page
  keeps at least six words and 900ms, reaches 56px, lowers measured pressure or
  removes a short tail, and introduces no severe, atomic, numeric-rate, or
  incomplete attached boundary. Within each candidate, allowed, low-, medium-,
  and high-risk transitions are graded before final-font line balance and
  visual cost.
  A complete sentence that fits a static two-line layout may remain one page
  when every requested page turn is only reviewable or the only extra signal is
  duration. Duration may request high-pressure alternatives, but it cannot by
  itself force a readable 56px two-line cue to paginate.
  A high-pressure static or multipage baseline (over 14 words on a page,
  longer than 5.2 seconds, or below 56px) receives a bounded secondary review.
  A complete all-56px partition takes precedence over smaller-font options.
  Automatic planning then permits only 54px and 52px as smaller normal sizes.
  If no complete 56/54/52px plan exists, it emits an explicit
  `render_structural_overflow` editable seed instead of regenerating a 50px or
  three-line page. Every promoted page keeps at least six words and 900ms.
  Complete `to ...` and `from + gerund` restarts are reviewed fallbacks;
  incomplete lexical, noun-attached, clause-introducer, and modifier boundaries
  remain ineligible regardless of density.
  Strict candidates retain priority, but high-pressure cues also enumerate
  bounded reviewed and forced alternatives so an early strict partition cannot
  hide a complete, materially more readable plan. Atomic lexical splits remain
  forbidden and the editor retains review evidence.
  The selected fallback is recorded in the page artifact. Timed transitions
  switch only at ledger word gaps and require at least 900ms per page.
  A balanced subject/predicate restart with at least four words on each side,
  a complete right page, and at least 180ms of verified pause may enter the
  medium-review tier. A restart at 600ms remains high-confidence audit
  evidence, but its acoustic support lowers its selection cost. Lexical
  dependencies remain hard. New automatic pages are limited to two English
  lines and 56/54/52px. A legacy 50px artifact may be reopened and validated
  for compatibility, but is never produced by the current planner. Missing or
  mismatched timing, minimum-font overflow, or an unschedulable page raises
  `render_structural_overflow` before ffmpeg starts.
  Every selected final page independently chooses the largest automatic size
  from 56/54/52px after its word span is frozen. The parent font field is only a
  summary equal to the smallest child-page size; it cannot force a short child
  page to inherit the smaller size needed by another page. Automatic planning,
  manual page splitting, frozen-artifact validation, editor preview, and final
  rendering consume the same per-page font value.
  After those page spans, IDs, Chinese assignments, and page times are frozen,
  a renderer-only pass compares every legal width profile for the same page at
  56/54/52px and selects its same-screen one- or two-line English layout.
  Pixel-width balance is scored after lexical and frozen syntax protection, so
  punctuation cannot win merely by leaving an extreme short line. A warning
  that only means `unsupported_tight_page_transition` is ignored here because
  both lines remain visible simultaneously; the real page planner still keeps
  that timing risk. Lexical atoms remain hard. The previously selected layout
  is retained as a baseline: reducing the font is legal only for a strictly
  better layout, never to reproduce the same break at a smaller size. This pass
  has no write authority over page count, word ownership, ID, English, Chinese,
  or timing.
  Article-template Chinese uses a fixed 48px font, at most two lines, and the
  existing 1455-design-pixel safe width.
  A terminal five-word prepositional page is a REVIEW fallback rather
  than a structural error when no complete single-page normal-font layout
  exists and the short page is sentence-complete, fits at 56px, receives at
  least 900ms, and preserves every lexical dependency. Six words remains the
  promotion preference for otherwise optional page-count changes; four-word
  tails remain ineligible.
  Compatible dependency and participial evidence may describe the same
  complete renderer-only continuation without becoming two independent
  blockers. Likewise, an adverb/preposition predicate boundary may enter the
  forced complete-predicate REVIEW tier only when the entire right page is a
  complete phrase and no unrelated atomic issue remains. Formal English cue
  cutting stays HARD at both boundary types.
  The page contract version is `article-fixed-font-pages-v31`, so page-layout
  and page-translation caches from earlier planner versions cannot be reused;
  unchanged ASR, full-translation, and fixed-ID allocation caches remain
  independently reusable under their own fingerprints.
  Raw hard/atomic syntax evidence remains attached when an acoustic or
  continuation fallback makes a boundary reviewable. Candidates without such
  relaxed atomic evidence are selected first. If no normal-font candidate is
  renderable, the failed parent remains visible to the editor as an editable
  seed; it is not hidden or silently forced into an emergency three-line page.
  Page Chinese uses `fixed-parent-page-allocation-v9`. Its aggregate projection
  is checked against the authoritative parent Chinese for repeated meaning and
  significant expansion before the existing parent-local retry is accepted.
  One-character Chinese grammar markers may attach to source-owned wording
  without becoming added meaning. A page boundary rejected only by HMM's
  invented token join is accepted when dictionary tokenization independently
  proves that exact boundary; a lexical word kept whole by both tokenizers
  remains unsplittable. Genuine split errors include the exact Chinese token
  in the parent-local retry constraint.
  Whole-episode selection adds a renderer-only continuity preference across
  already legal candidates: adjacent pressure changes are penalized after a
  free band, while font and line-count changes are weaker tie-breakers. The
  selector first minimizes forced and severe boundaries and charges an explicit
  incomplete-review penalty, so visual continuity alone cannot create a less
  complete English page edge. A
  54px static page may request the existing complete 56px secondary partition;
  an ordinary 56px two-line page is not split solely for density continuity.
- Interrupted-run resume records the article-ASR-correction policy version.
  A policy change recomputes only `asr_corrected.json`; the verified article
  context and raw transcription remain independently reusable.
- Manual display suppression does not delete a cue from the authoritative word
  ledger or final cue timeline. Its empty-ID restore row is excluded from
  visible page completeness and page-edit operations. Renderer page boundaries
  are indexed by authoritative timed-word records, so a one-record surface
  correction containing whitespace remains one timed boundary unit while its
  full display text is rendered normally.
