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
  both sides; an unanchored local result is diagnostic evidence and cannot
  mutate the transcript.
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
- Allocation maps the full Chinese meaning back to fixed global subtitle IDs.
- English IDs, timing, and order are immutable during Chinese translation.
- Missing Chinese is a validation issue.
- LLM allocation responses must include `subtitle_id` for each returned Chinese line.
- Returned, missing, duplicate, and unknown subtitle IDs are recorded as structure errors.

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
- A padding overlap may be reconciled only at a shared boundary that stays
  between the adjacent word envelopes.
- Do not change English text, Chinese text, subtitle ID, word range, or order.
- Missing, duplicate, unknown, or synthetic final timeline IDs are ERRORs and
  block export.

After the final word ledger and cue timeline pass, the article renderer may
enumerate multipage display spans. Every span receives a deterministic child
ID such as `S0078.P01`. Chinese for those spans is returned by exact child ID,
validated, and aggregated back into the unchanged parent cue. Missing, stale,
tampered, semantically invalid, or unschedulable page data blocks rendering;
there is no proportional-character fallback.

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
- `run-state.json`

Run-state rules:

- It is a progress/recovery record, never a subtitle source of truth.
- It hashes the input subtitle, article state, relevant stable configuration,
  model/prompt values, and selected timing backend.
- A stage artifact is reusable only when its recorded digest and full input
  fingerprint match; otherwise the normal stage executes.
- Existing LLM batch caches may be reused under their current cache keys, but
  completion order never controls translation or subtitle writeback order.

Validation checks:

- English coverage gaps.
- Whole-file English boundary audit: `hard` atomic splits with no contrary
  timing/speaker evidence must be repaired before IDs; residual `hard` items
  block export. Ambiguous `review` items are retained for human verification;
  independently supported `allow` boundaries remain untouched.
- Missing Chinese.
- Overlong English.
- Translation ID mismatch, missing ID, duplicate ID, unknown ID, or group cardinality mismatch.
- Suspicious cuts.
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

### Manual final checkpoint

- The subtitle editor loads the stable SRT together with its frozen word
  ledger, final cue timeline, fixed-ID Chinese mapping, page contract, and
  existing audit artifacts. Existing artifacts are the checkpoint; reopening
  them does not rerun ASR, translation, or English segmentation.
- Review highlighting is intentionally narrow: unresolved hard/high-confidence
  English boundaries, cue-edge alignment fallback, high-confidence Chinese
  semantic loss, unresolved fixed-ID allocation, and high-risk visual page
  boundaries. Routine reading-speed warnings and low-confidence parser guesses
  are not editor marks.
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
  report anchor while retaining the original media name. Stable publication writes the
  bilingual, English-only, Chinese-only, actual-page, page-map, QA queue,
  summary, and compatibility SRT files there. Manual-final save writes
  `人工终稿字幕包/` inside that same directory, while formal and manual-draft
  videos use distinct names in the directory root. Internal work directories,
  immutable stable-run artifacts, and source media stay in place. Existing
  loose legacy files are not moved or deleted.
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
  contract hash. It plans 56px English and 46px Chinese pages inside each
  frozen cue. The complete whole-episode plan is frozen before page Chinese is
  accepted. Once validated, that plan is the only renderer authority; a
  per-cue renderer call cannot replace its page spans, font, or page IDs.
  It first keeps a whole cue on one
  static page using measured pixels: the normal 1455px English panel, then the
  1498px safe-width profile, with at most two English and two Chinese lines.
  Chinese load and a 16-word target are soft page-count signals. Measured
  English pixels, Chinese pixels, word load, and cue duration choose candidate
  page counts before any break reward is considered. A bounded whole-episode
  dynamic program then compares the feasible 56/54/52/50px cue-local plans and
  adds a penalty for adjacent dense pages. Within each candidate, allowed,
  low-, medium-, and high-risk transitions are graded before measured balance
  and visual cost.
  A complete sentence that fits a static two-line layout may remain one page
  when every requested page turn is only reviewable.
  A static page over 16 words or requiring 52/50px receives a bounded secondary
  review. It may be replaced by a 56px reviewed partition only when every page
  has at least six words and 900ms, and each boundary is supported by a
  complete clause restart or at least 500ms of verified pause. Incomplete
  lexical dependencies remain ineligible regardless of density.
  Strict candidates are exhausted first. Only an otherwise unrenderable cue may
  use a complete continuation phrase or clause as a high-risk reviewed page
  transition; atomic lexical splits remain forbidden and the editor retains the
  review evidence.
  The selected fallback is recorded in the page artifact. Timed transitions
  switch only at ledger word gaps and require at least 900ms per page.
  A balanced subject/predicate restart with at least four words on each side,
  a complete right page, and at least 180ms of verified pause may enter the
  medium-review tier. A restart at 600ms remains high-confidence audit
  evidence, but its acoustic support lowers its selection cost. Lexical
  dependencies remain hard. Three English lines are permitted only at 50px
  after every two-line layout at 56/54/52/50px fails. Missing or mismatched
  timing, minimum-font overflow, or an unschedulable page raises
  `render_structural_overflow` before ffmpeg starts.
  Every selected final page independently chooses the largest legal size from
  56/54/52/50px after its word span is frozen. The parent font field is only a
  summary equal to the smallest child-page size; it cannot force a short child
  page to inherit the smaller size needed by another page. Automatic planning,
  manual page splitting, frozen-artifact validation, editor preview, and final
  rendering consume the same per-page font value.
  After those page spans, IDs, Chinese assignments, and page times are frozen,
  a renderer-only pass compares the same page at 56/54/52/50px and selects its
  same-screen one- or two-line English layout. It may treat broad clause and
  subject/predicate evidence as a soft line-break score because both lines stay
  visible, while lexical atoms remain hard. The previously selected layout is
  retained as a baseline: reducing the font is legal only for a strictly better
  line break, never to reproduce the same break at a smaller size. This pass
  has no write authority over page count, word ownership, ID, English, Chinese,
  or timing.
  The page contract version is `article-fixed-font-pages-v19`, so page-layout
  and page-translation caches from earlier planner versions cannot be reused;
  unchanged ASR, full-translation, and fixed-ID allocation caches remain
  independently reusable under their own fingerprints.
- Interrupted-run resume records the article-ASR-correction policy version.
  A policy change recomputes only `asr_corrected.json`; the verified article
  context and raw transcription remain independently reusable.
