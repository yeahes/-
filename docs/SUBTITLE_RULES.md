# Subtitle Rules

## English

- English subtitle text must match the audio transcript.
- Article-assisted entity correction may change only the entity-owned source
  span. It must preserve a neighbouring discourse word or title when the full
  canonical entity already exists in the local source window.
- A titled person-name correction below the normal similarity threshold is
  eligible only when the article contains that person, the title matches, the
  surname keeps its initial and minimum spelling similarity, and nearby ASR
  description terms overlap the article evidence. Article presence alone is
  never enough to lower the threshold.
- Stable mode must not rewrite English for style.
- Stable mode must not delete filler or backchannel words by default.
- If a short backchannel is visually too brief, merge or extend display timing instead of deleting it.
- Preferred visual target is 6-12 English words per subtitle.
- Normal hard maximum is 16 English words. A rare 17-19 word structural exception is allowed only when every shorter cut would create a parser-confirmed grammar error; report the exception. If an otherwise complete terminal source sentence has no legal normal-limit temporal cut, preserve that complete cue for renderer wrapping and report its structural overflow rather than force a fragment at 19 words.
- The 12-word / 68-character reading target belongs only to the renderer.
  A complete 13-16 word English cue remains one temporal subtitle with one ID
  and one Chinese allocation. A visual word/character budget, renderer, or
  template must never create or move a formal subtitle boundary.
- Rendering may paginate a frozen cue for readability, but that projection
  cannot alter English text, subtitle IDs, word spans, cue times, Chinese
  allocation, SRT, or ASS output.
- A visual page prefers 12 words and treats 16 words as a soft budget. A page
  that exceeds 16 words remains legal when its measured selected-font layout
  fits and a shorter partition would create a worse grammar or timing boundary.
- A single page over 16 words, or one that needs 52/50px, receives one
  conservative secondary review. A reviewed two-or-more-page plan may replace
  it only when every page has at least six words, lasts at least 900ms, fits at
  56px, and every new boundary starts a complete clause or has a verified
  500ms pause. Modifier/head, subject/predicate, verb/object, infinitive, and
  other incomplete lexical boundaries remain rejected.
- A word-level lexical dependency remains a hard visual boundary. A balanced
  subject/predicate restart may become medium review at a verified pause of at
  least 180ms only when both pages contain at least four words and the right
  page is complete. A clause-level restart at 600ms remains high-confidence
  review; the strong acoustic evidence lowers its selection cost without
  changing its audit label. A `that`-introduced `-ing` clause receives the
  strong-pause treatment when the pause shows an actual spoken restart. The
  parent cue, ID, text, and timing remain unchanged.
- A middle visual page may start with a coordinating conjunction after visible
  punctuation. This remains a review candidate with a planning penalty; the
  renderer prefers a more complete boundary whenever one is feasible.
- Article English uses 56px by default. The planner evaluates the explicit
  56/54/52/50px sequence together with one-to-four-page layouts. A smaller
  static layout may beat a page turn only when that page turn carries stronger
  structural risk; low-confidence hints remain soft and cannot by themselves
  force major font reduction. The selected size and reason must be recorded in
  the page artifact; no unreported font shrinking is allowed.
- Page spans, page IDs, page timing, and page Chinese are frozen before the
  renderer optimizes a same-screen English line break. Subject/predicate and
  ordinary clause warnings may rank two visible lines without becoming page
  boundaries; names, numeric units, modifier/head, determiner/head,
  auxiliary/predicate, preposition/object, and other lexical atoms remain
  hard. A smaller font may replace the frozen page layout only when its
  line-break score is strictly
  better. An unchanged or equally ranked break must retain the existing larger
  font. This final line reflow cannot change parent English, page count, page
  word spans, Chinese allocation, subtitle IDs, or any timing field.
- A 50px page may use three English lines only after every grammar-safe two-line
  layout at 56/54/52/50px has failed. Other font sizes remain limited to two
  lines. The renderer must never reduce English below 50px.
- The planner first exhausts strict layouts. Only when none can fit may a
  complete visible continuation phrase or clause use a reviewed page boundary.
  The fallback cannot split a lexical atom, silently become an allowed
  boundary, or change the parent cue; it is recorded as a high-risk editor
  review. This is preferable to blocking an otherwise renderable long cue or
  shrinking below 50px.
- Page count is chosen first from measured English/Chinese load, the soft word
  budget, and duration. Break rewards cannot create another page. Within the
  selected count, display boundaries retain separate allowed, low, medium,
  high, and forced risk levels; measured reading and visual cost resolve equal
  risk. A tight unpunctuated complete-phrase start is low review, while clear
  punctuation plus a complete following clause remains eligible. Hard lexical
  dependencies remain ineligible except for an explicit reviewed fallback
  after strict planning fails. This ordering applies only inside one frozen
  cue and cannot change English text, subtitle IDs, word ownership, parent
  Chinese, or cue timing.
- A multipage cue uses deterministic display-page IDs below the frozen parent
  subtitle ID. Chinese page meaning must be assigned to those IDs explicitly;
  proportional character slicing is forbidden.
- A verified whole-episode page sequence is authoritative. Per-cue rendering,
  editor preview, manual save, and synthesis must consume that frozen sequence;
  they cannot invoke another planner and replace its page spans, font size, or
  page IDs.
- Page Chinese is an independent display projection of the authoritative
  parent translation. It may reorder or restate the same meaning for natural
  page-local reading and therefore is not required to concatenate back to the
  parent's exact surface text. Every new page artifact must carry the exact
  source-parent Chinese text/hash that created it, and it must never overwrite
  that parent translation. A legacy artifact without this source reference is
  readable only when its ordered page Chinese still reconstructs the current
  authoritative parent Chinese exactly.
- A short comma-terminated non-finite condition at the start of a cue may move
  back to the immediately preceding clause only when local parsing confirms it
  has a clause marker but no subject or finite predicate, the following text is
  a complete main clause, the pause is under 450ms, and both repaired cues stay
  within the English word limit. A finite conditional introduction remains in
  its own cue. The audit records any narrowly accepted syntax exception.

## English Cutting

Good cut points:

- Sentence punctuation.
- Natural clause boundary.
- Before or after contrast markers when the previous part is complete.
- Around examples or appositives.
- After a complete subject-verb-object unit.

Bad cut points:

- After `of`, `for`, `with`, `by`, `to` when the object follows.
- Between article and noun.
- Between adjective and noun.
- Between auxiliary and main verb.
- Between number and unit.
- Inside names, institutions, or fixed terms.
- Immediately after `because`, `which`, or `that` when the dependent content follows.

## Chinese

- Chinese should be natural Simplified Chinese.
- Preferred style: concise magazine, documentary, finance/explainer narration.
- Do not translate word-for-word in English order when Chinese would become stiff.
- Preserve facts, numbers, names, negation, modality, contrast, condition, and speaker stance.
- Do not move information earlier than the corresponding English audio.

## Timing

- Final display timing may extend subtitles for readability.
- Final timing must not overlap adjacent subtitles.
- Short spoken beats can be bridged to the next subtitle when the gap is small.
- A large blank gap must be treated as a possible ASR/timing issue and reported.

## Validation Policy

Blocking errors:

- Missing Chinese for an English subtitle.
- Severe continuous subtitle coverage gap.
- Time order corruption.
- Overlong English that violates configured hard limits.
- A residual `hard` English boundary: an atomic structural split without
  sentence-terminal, long-pause, speaker-change, or discontinuous-ledger
  evidence. Pre-ID repair owns automatic resolution; final residuals block
  export rather than silently merging fixed IDs.
- Missing, stale, mismatched, or tampered display-page translations for a cue
  that requires timed pagination.

Warnings:

- Suspicious cuts.
- `review` English boundaries: plausible but ambiguous fragments or atomic
  shapes contradicted by pause/speaker evidence. They are recorded for human
  review, not auto-merged.
- Very short display duration.
- Small timing gaps.

Editor review marks:

- Show only issues with actionable evidence: hard or high-confidence reviewed
  English boundaries, final-timeline fallback on a cue edge, high-confidence
  Chinese semantic/allocation loss, or a visual page boundary that may split a
  tight grammatical unit.
- Do not mark every short cue, fast cue, stable-ts fallback in the middle of a
  cue, low-confidence parser guess, or generic warning. These remain in audit
  artifacts without becoming manual-editor noise.

Manual editor operations:

- Manual editing is batch-oriented: text, parent-boundary, page-count, and page
  boundary changes update one reversible in-memory draft. Do not run full page
  publication after each operation. One explicit save validates and publishes
  the complete snapshot.
- Before rebuilding the model or deciding whether unsaved work may be
  discarded, commit the active cell editor. A value still inside a Qt delegate
  is part of the user's draft even if focus has not changed.
- Parent-row writeback requires the same fixed cue ID, frozen English, word
  range, and time envelope. Row position alone is never sufficient identity.
- Artifact review marks cease to be authoritative for an identity once that
  identity is edited. Current manual Chinese flags and display-page
  REVIEW/unavailable metadata must still enter table highlighting and review
  navigation.

- Ordinary row selection never changes the current or next subtitle. Boundary
  movement requires an explicit adjust command, a direction preview, and a
  separate confirmation; cancel is non-mutating and the operation is undoable.
- A selected middle row exposes both its upper and lower boundary. Choosing a
  direction resets the movable count to one word, and changing the count updates
  the highlighted source words before confirmation.
- Automatic planning remains capped at four pages. An explicit manual action
  may create two through six pages through the shared syntax/timing planner.
  It must preserve the parent subtitle ID, English, word span, parent timing,
  and complete word coverage.
- After that initial safe partition, an explicit manual boundary move may accept
  a grammar-risk boundary or a page below the normal 900ms policy floor. The
  frozen plan records `manual_override`, the original issue codes, and a REVIEW
  classification. Automatic planning remains strict.
- Empty pages, lost/duplicated/reordered words, missing IDs, a boundary outside
  the parent, no legal shared word-time boundary, or fixed-font layout overflow
  remain non-overridable structural errors.
- `display_suppressed` hides a complete parent cue while preserving its audio,
  fixed ID, word coverage, and final timeline. `media_muted` is a separate
  explicit operation and implies `display_suppressed`; restoring visible text
  alone while its audio remains muted is invalid.
- Parent-level media mute and suffix-only tail deletion share one schema-v2
  derivation contract. Save applies ordered fixed-cue mute intervals and an
  optional final cut to the hash-bound original media in one FFmpeg pass. It
  must never derive again from an older muted or trimmed file. Retained word
  IDs, word times, cue IDs, cue order, and cue envelopes do not shift.
  Page-only mute remains unsupported.
- Manual English correction may replace one raw word surface or collapse one
  continuous raw-word range to one presentation-only surface. The raw word
  ledger, IDs, order, and timing remain authoritative. Display spans may not
  cross cue or page boundaries and may not be split by a later boundary move
  or tail cut; complete retained or removed spans remain atomic through
  merge, save/reload, undo, and redo.
- Copying one or more selected English rows is read-only and must not enter the
  manual edit, pagination, history, or timing paths.
- A new or moved manual display page has no authoritative Chinese allocation.
  Empty page Chinese is an allowed editor intermediate state so the user can keep
  adjusting boundaries. `manual_page_translation_required` still blocks save as
  a formal publication until every page translation is supplied.
- A non-empty page Chinese edit acknowledges that exact page Chinese. An
  explicit boundary move acknowledges the resulting page boundary. Unchanged
  text or boundaries may be acknowledged individually or through the explicit
  bulk action for non-blocking reviews.
- Acknowledgement is keyed by display-page ID, parent subtitle ID, frozen
  English, and continuous word range. Re-pagination, a word-range change, or a
  different page identity invalidates it. HARD layout, timing, coverage, or
  lexical-structure failures are never cleared by acknowledgement.
- A translation-only ERROR or REVIEW status does not invalidate frozen page
  geometry. A strict manual checkpoint must reuse the hash-bound saved page
  plan instead of silently invoking automatic pagination.
- A formal parent-boundary change hides the stale page artifact. The visible
  `refresh actual pages` action runs the existing page preflight and checkpoint
  save in the background. Reopening or saving the resulting hash-bound package
  reuses that frozen result instead of planning it again.
- Boundary evidence belongs to the authoritative word ledger, not the current
  cue partition. A saved package contains every adjacent word boundary. A
  legacy package may recover an omitted boundary only when current or undo
  history proves it was an accepted frozen cue edge; arbitrary internal gaps
  remain blocking. Choosing `split into N pages` while parent pages are stale
  queues one refresh and applies that split only after the matching package
  reloads successfully.
- `Split into N pages` first uses the strict automatic partition. If that has no
  result, an explicit manual request may choose the lowest-risk REVIEW boundary
  as an editable proposal. If neither strict nor REVIEW planning can satisfy the
  requested page count, the editor must ask for a second explicit confirmation.
  Only after that confirmation may it create a high-risk editable proposal from
  timed-word boundaries, ranked by page pixel load, duration balance, pause, and
  syntax evidence. The original HARD classification remains recorded as REVIEW
  evidence; automatic planning is not relaxed. Non-contiguous ownership,
  missing word-time boundaries, lost/duplicated/reordered words, and fixed-font
  overflow remain non-overridable. Every proposed page still requires explicit
  page-Chinese review before publication.
- Tail deletion is suffix-only and must retain at least the first parent cue.
  The cut lies between retained and removed word envelopes. Retained fixed IDs,
  English, Chinese, word times, and cue order cannot be renumbered or shifted.
- Tail deletion never edits the source media. The package records the source
  hash, cut decision hash, removed IDs, derived-media path, and derived-media
  hash; synthesis must use the recorded derivative and reject a stale or
  tampered file.

Manual draft synthesis:

- A manual draft is an explicit preview of a saved, render-blocked checkpoint;
  it is never equivalent to formal validation success.
- Only page-layout overflow or missing/invalid page-level Chinese allocation
  may be accepted for a draft. Missing media, invalid package ownership,
  changed SRT hash, final timeline/word-ledger mismatch, lost IDs, changed
  English, word-range drift, or cue-time drift remain blocking.
- Draft pagination may use a REVIEW-labelled relaxed phrase/clause boundary
  only after the strict planner fails, but that choice must be made and
  persisted when the manual package is saved. It still uses token-safe Chinese
  boundaries and the 56/54/52/50px English font set; raw character splitting
  and silent font reduction remain forbidden.
- The editor and draft renderer must consume the same SHA-256-bound draft page
  artifact. Runtime synthesis cannot create a replacement page plan. Missing,
  tampered, or cross-package page artifacts block before ffmpeg.
- Draft authorization applies only to the `文章单词` template. Switching to a
  different template must fail instead of reusing the page-only waiver.
- The normal editor view projects each frozen display page as one row while
  retaining the parent subtitle ID and continuous word range. Chinese may be
  edited per page and aggregated back to that parent. English page text is
  read-only in this view; formal English boundary edits remain parent-level,
  word-ledger-backed operations.
- A page-only Chinese edit must reuse the exact existing page IDs, English word
  spans, page times, and layout artifact. Saving cannot silently replan pages.
  If the page identity or span no longer matches, the package remains blocked.
- An ERROR page artifact does not hide the entire subtitle file. The editor may
  recover identity-validated pages as read-only-English review rows and expose
  failed parents as unresolved parent rows. Only a complete PASS artifact may
  authorize formal synthesis.
- A recoverable page-Chinese error must keep every frozen English render plan.
  Independently valid parent-page translations remain available; invalid-page
  Chinese stays unauthoritative and is shown as an explicit editor review item.
- A stale source-folder actual-page SRT is not current page authority. Its
  companion mapping and file hash must match before the editor may resolve the
  latest parent manual package. If page ID, parent ID, word range, English,
  Chinese, and timing also match, its Chinese may be exposed only as a
  separately stored, unconfirmed review draft. It must not overwrite current
  parent Chinese, populate authoritative page Chinese, or pass formal
  publication until the user explicitly confirms or reallocates every page.
- New user-facing files are published under
  `<output-anchor-parent>/<source-media-stem>-处理结果/`; the interactive Home
  workflow uses the source media as that anchor. This output organization must
  not change the internal stable-run path, source media, frozen subtitle IDs,
  English text, word ledger, cue timing, page identity, or manifest authority.
- An empty intermediate page edit is not evidence that the user rejected a
  separately recovered, identity-matched Chinese draft. The editor must keep
  the recovered text visible and unconfirmed. It must not aggregate that text
  into the parent or publish it until explicit confirmation. If the page word
  range changed, no old draft may be substituted and the page remains blank.

Allowed boundaries:

- Independently readable cues supported by sentence punctuation, a pause,
  speaker change, or local context. A cue starting with `But`, `Because`,
  `In`, or a finite verb is not invalid by word class alone.

## Avoided Approaches

- LLM jointly deciding English segmentation and Chinese translation.
- Deleting `Right`, `Yeah`, `Exactly`, etc. to make subtitles cleaner.
- Fixing every sample by adding one-off text-specific rules.
