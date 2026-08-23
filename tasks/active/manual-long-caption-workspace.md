# Task: Manual Long-Caption Workspace

Status: in_progress
Last reviewed: 2026-08-19 07:14:07 Asia/Shanghai

## 2026-08-24 Complete-parent media deletion

- Added a parent-scoped, reversible context-menu operation that marks one or
  more complete parent cues for timeline deletion. All rows of a multipage
  parent must be selected together; page-only deletion, mixed delete states,
  and deleting every parent are rejected.
- Save publishes a schema-v3 source-bound media derivation and presentation
  timeline. Retained source slices are concatenated into a new derived audio;
  later cue, page, and word-card times are projected onto the compacted clock.
  The original source timeline and word ledger remain immutable, so restore,
  undo, redo, reload, and synthesis validate the same fixed IDs.
- Focused automated coverage is complete. A real GUI mouse walkthrough and
  full regression remain acceptance work. The captured full regression
  completed 29/30 checks; its sole failure is the existing `S9522` article
  readability expectation (`into` versus the current `in` page start), which
  is outside this media-timeline change.

## 2026-08-24 Frozen page reuse during manual-final save

- Manual-final save now keeps an `ERROR` page artifact's valid frozen render
  plans. Semantic page errors remain blocking, but they no longer cause an
  unrelated deletion edit to replan the entire episode.
- Page translation cache reuse is ID-bound and partial: valid pages survive a
  sibling cache miss, while the formal contract reports only the missing page
  ID. Legacy page artifacts keep their previous strict range checks.
- Semantic errors keep their source parent/page scope, so a known bad parent
  cannot be silently promoted to a valid page projection or poison unrelated
  page caches.
- Regression: `tests/test_manual_final_subtitle_editor.py` passes `128/128`.

## 2026-08-19 Failed Page-Plan Parent-Chinese Preview

- A failed fixed-font display-page plan no longer becomes an empty actual-page
  view. The editor keeps each frozen English page and shows the parent Chinese
  as an explicit `parent_chinese_fallback` draft.
- Fallback text is review-only: single-page and bulk confirmation cannot mark
  it as page-local Chinese. The user must edit each page or provide a validated
  page translation before publication; the formal synthesis gate is unchanged.
- Recovery logic treats this preview as blank for exact identity-matched undo
  drafts, so existing manual history recovery remains lossless.

## Goal

Reduce the repeated manual workflow for dense bilingual captions:

```text
find a dense parent cue
-> choose two to four display pages
-> compare boundary candidates
-> adjust one candidate locally
-> review ID-bound page Chinese
-> confirm the parent and continue
```

The workspace must preserve frozen parent subtitle IDs, English text and order,
the authoritative word ledger, parent cue spans, word timestamps, and the
manifest-owned synthesis path.

## Production Evidence

Read-only audit of two schema-v2 manual edit journals found:

- 453 final parent cues and 552 final display pages.
- 163 recorded operations.
- 49 split operations across 48 distinct parent cues (10.6% of parents).
- 79 page-Chinese edit operations and 126 distinct edited pages.
- 126 empty-to-filled page-Chinese transitions after structural editing.
- In `如何停止拖延`, 12 of 28 manually split parents (42.9%) were later
  corrected with a display-boundary move or page merge.
- The journals are 11 MB and 29 MB because history stores repeated whole-state
  snapshots rather than parent-scoped command deltas.

These measurements make page-boundary choice, page-Chinese recovery, and local
edit-state ownership the primary scope. General parent-subtitle editing and a
new automatic English segmentation pipeline are not the primary scope.

## Implemented Increment: Local Page Ownership

- A selected display page can be split in two without replanning sibling pages
  in the same parent.
- Two adjacent display pages from different parents merge as one atomic,
  single-undo command instead of requiring a parent merge followed by a page
  merge.
- Boundary controls start disarmed, appear only after an explicit subtitle-row
  click, and disappear when the empty table viewport is clicked.
- The full parent-local candidate comparison workspace, draft recovery, redo,
  and ID-bound Chinese suggestion stages below remain planned.

## 2026-08-12 Engineering Stabilization Increment

- Manual-final packages can now be moved as one directory and reopened from
  either `stable-final-manifest.json`, `人工终稿字幕.srt`, or
  `人工终稿分页双语字幕.srt`. Relocation is restricted to the manifest-owned
  package directory, and every file with a recorded SHA-256 must still match.
- A tampered subtitle, edit journal, or word ledger still fails closed instead
  of falling back to the original stable package.
- Background save now deep-copies current cues, ledger, pages, overrides, and
  trim state, but reuses append-only history entries read-only. On the real
  258-cue Hollywood package, snapshot time fell from about 404ms to 22ms.
- Cross-parent merge no longer deep-copies the entire existing history before
  its atomic transaction. The same real-package operation fell from about
  1.15s to 0.82s; it remains above the desired interactive threshold.
- Direct manual-editor tests, stable publication/UI 63/63, and the complete
  25-stage regression pass. Read-only load succeeds for two packages moved
  from Desktop to `D:\经济学人`.
- Package-level atomic generation, delta history, redo, crash recovery, and a
  real mouse/keyboard GUI walkthrough remain required before this phase closes.

## Adapted External Patterns

SmartSub patterns to adapt rather than copy:

- Parent/range-scoped command history with undo and redo instead of whole-file
  history snapshots.
- A focused failed-item list with previous/next navigation.
- WYSIWYG subtitle preview.
- Exact response keys, source echo validation, and per-entry retry for page
  translation suggestions.
- Its verbatim `<br>` protocol may be used only for an optional human-visible
  fallback suggestion. It must never own stable English boundaries.

Subtitle Edit patterns to adapt:

- Live comparison of multiple long-line split/rebalance proposals.
- Inspectable history and explicit rollback.
- Recoverable local auto-backups.

## 2026-08-13 Translation Review Increment

- Article terminology uses hit-only injection in the current translation source
  window; the full glossary is no longer repeated for unrelated batches.
- The stable QA summary writes a separate semantic-review queue for high-signal
  Chinese semantic and fluency findings. This is read-only evidence and does
  not mutate the production package.

## Planned Stages

### 1. Read-only candidate API

- Expose the existing article planner candidate bundle for one frozen parent
  and requested page count.
- Return the top bounded alternatives with word ranges, page text, final font,
  line layout, timing, pause evidence, and grammar-risk evidence.
- Do not change the candidate selected by the automatic production planner.
- Add focused fixtures derived from accepted and rejected real boundaries;
  do not commit private production journals.

Status: completed. The core helper returns bounded candidates and global
word-ledger ranges without mutating production state.

### 2. Parent-local workspace

- Add a focused queue for dense, low-font, overflow, review, or unconfirmed
  captions rather than showing routine warnings.
- Show two to four page candidates, word chips, pause markers, page durations,
  final font and line layout, and an exact article-frame preview.
- Keep split, merge, and boundary experiments in a parent-local draft.
- Allow undo/redo inside that draft and commit the parent as one atomic edit.
- Preserve selection and scroll position when applying or rejecting a draft.

Status: partially completed. The actual-page context menu now opens a local
candidate dialog and applies one selected candidate to only the current parent,
preserving matching page Chinese. Exact rendered previews, word chips, and
delta-journal recovery remain follow-up work.

2026-08-14 increment: the row-level boundary inspector now previews nearby
word-ledger cuts and distinguishes recommended, manual-review, and blocked
options. Soft subject/predicate or coordination risks remain visible instead
of being labelled safe; hard grammar, duration, and minimum-page constraints
remain blocked. Preview is read-only.

2026-08-13 increment: the actual-page editor now exposes a read-only parent
risk queue and candidate rows show word count, duration, and pause evidence.
The queue does not mutate page plans or apply candidates automatically.

Real-package acceptance: a temporary byte-identical copy of the 283-parent,
353-page `如何停止拖延` manual-final package completed local page split,
boundary move, page merge, undo, redo, exact initial-state restoration,
single-page Chinese edit, save, manifest reload, parent/actual-page projection,
and synthesis-manifest resolution. All 15 source-package files retained their
original size and SHA-256. This validates the core session workflow without
claiming a full mouse-driven Qt walkthrough.

Queue responsiveness follow-up: opening the queue no longer runs the renderer
candidate planner for every risk parent. The real package now builds 34
high-signal queue items in 0.020 seconds instead of 45.89 seconds; candidate
planning is deferred until the user opens one parent's focused workspace.

Queue continuity follow-up: native long-caption and candidate dialogs now use
the current application light/dark palette. The queue also restores focus by
frozen parent ID after the user edits an item and reopens the queue; when that
item is no longer risky it selects the nearest remaining row. This state is
session-local and is reset when another subtitle package is loaded.

### 3. ID-bound page-Chinese suggestions

- Request Chinese only after the user settles on page word ranges.
- Bind every response to deterministic `Sxxxx.Pxx` IDs and frozen page English.
- Require source echo validation; missing, duplicate, unknown, or mismatched
  pages fail locally without affecting other pages.
- Include bounded neighboring context and retry only failed pages.
- Cache by word-ledger hash, parent ID, page ranges, English, parent Chinese,
  model, and prompt version.
- Suggestions remain visibly unconfirmed until edited or accepted by the user.

2026-08-14 increment: the semantic-review queue can generate cached suggestions
in a background worker and manually apply them by exact fixed parent ID. Source
echo, current-Chinese hash, numbers, explicit currency units, negation, and
article-matched terms are validated before atomic writeback. Session switches,
queue changes, and intervening Chinese edits invalidate stale results. Page-ID
suggestions and exact rendered preview remain follow-up scope.

### 4. Delta journal and recovery

- Introduce a backward-compatible edit-journal schema that records affected
  parent/page deltas instead of repeated whole-document snapshots.
- Keep schema-v2 packages readable.
- Atomically auto-save the working draft without publishing a formal manifest.
- Offer recovery after close or crash and keep formal publication as the
  existing explicit manual-final save.

Status: completed for the high-frequency local editor path. Parent-scoped
undo/redo now persists only the affected parent, survives recovery-draft
reload, and skips unrelated later parent edits. Legacy full snapshots migrate
in memory when loaded. English surface history stores changed frozen-word
records instead of a complete word ledger, and recovery drafts use compact
atomic JSON. Cross-parent, formal cue-boundary, and audio-tail operations
remain whole-document transactions by design.

2026-08-15 performance acceptance: the real 119-operation Mixue manual-final
history fell from 20.7 MB to 2.5 MB and its recovery draft from 32.8 MB to
3.1 MB. Draft hash/write time fell from roughly 222/1299 ms to 31/138 ms.
Local Qt edits now emit data-row changes or row insertion/removal rather than a
model reset; full reset remains reserved for imports and view-mode switches.
Read-only replay on two real packages preserved unrelated parents across edit,
split, undo, and redo. The final complete regression passed in 346.3 seconds.

2026-08-17 automatic-planner increment: the production planner now exposes a
bounded cross-page-count shadow frontier and applies a conservative dominance
selector only after the existing whole-episode sequence pass. It may promote
an already valid 56px partition or merge a short tail, but it cannot invent a
cut, relax an atomic/numeric-rate boundary, accept an incomplete attached
phrase, or change frozen IDs, English, word ownership, timing, or parent
Chinese. The 140-cue oil replay changed three parents, reduced over-14-word and
low-font pages without adding three-line pages, and passed the focused page,
page-Chinese, and complete regression suites.

2026-08-18 automatic-planner increment: planner v26 uses a 14-word comfortable
target, measures 15-word cues before changing page count, and prioritizes a
natural multi-page plan from 16 words. Normal automatic typography is limited
to 56/54/52px; 50px remains a compatibility path for already-frozen legacy
artifacts only. A general pronoun-boundary fix restores punctuated main-clause
starts such as `this, | you ...` without weakening genuine determiner+noun
protection. On the 184-parent animation replay, pages over 16 words fell from
7 to 4, pages below 56px from 19 to 14, and three-line pages from 3 to 2;
total pages increased from 201 to 203 and review boundaries from 9 to 11. The
complete unified regression passes.

2026-08-19 automatic-planner increment: planner v27 makes the 56/54/52px
normal-font floor authoritative for new automatic pages. A complete parent
that cannot be partitioned into grammar-safe, two-line pages at those sizes is
not forced into a 50px or three-line page. The stable artifact keeps the
parent's English, ID, word ledger, timing, and Chinese while recording an
`editable_seed` with `renderable: false`; the editor can then create an
explicit two-to-six-page, timed-word manual proposal and fill page Chinese.
Legacy 50px pages remain readable only through compatibility validation. The
page contract is `article-fixed-font-pages-v27`; focused page, manual-editor,
stable-caption, and complete regression suites pass.

2026-08-18 manual-final timing increment: manual save now rebuilds current
parent cues through the sole frozen-ledger final timeline before creating mute
audio, SRT, actual-page maps, or timeline artifacts. A real 174-parent replay
closed the three short gaps reintroduced by formal word-boundary moves while
preserving the 1040ms long word pause, all fixed IDs, word ranges, word times,
text, hidden/muted state, and zero overlap. Existing manual packages can obtain
the correction by reopening and saving; no ASR or translation rerun is needed.

### 5. Optional AI boundary fallback

- Offer only when deterministic candidates remain high risk.
- Accept only verbatim English with inserted boundary markers.
- Verify normalized equality and map markers to existing word IDs.
- Never apply automatically and never alter English, IDs, or timestamps.

## Rejected Approaches

- Replacing stable local English segmentation with LLM segmentation.
- Mapping translations by timestamp or list position instead of fixed IDs.
- Clearing all page Chinese whenever one display boundary moves.
- Making grammar warnings equivalent to ledger, timing, or layout corruption.
- Adding sample-specific phrase exceptions to the production planner.
- Rebuilding the full page model or saving the complete manual package after
  every exploratory click.

## Acceptance

- Replay both audited manual packages without modifying their source files.
- All 48 historically split parents can be opened in the focused workspace.
- Candidate preview cannot mutate cues, IDs, word ownership, or timing.
- Applying one parent changes no unrelated page.
- A page-boundary change never silently loses visible Chinese.
- Normal local candidate selection and boundary edits remain interactive; API
  latency is isolated to background page-Chinese suggestion work.
- Closing and reopening restores the same parent draft and command cursor.
- Old schema-v2 manual packages remain importable.
- Focused editor and display-page tests, `scripts/run_regression.py`, and
  `git diff --check` pass.
- One cached production replay and one fresh audio E2E verify final manifest,
  final cue timeline, rendered pages, and synthesis input authority.

## Primary Files

- `app/core/utils/podcast_learning_video.py`
- `app/core/subtitle_processor/manual_final_subtitle_editor.py`
- `app/core/subtitle_processor/stable_display_page_contract.py`
- `app/view/subtitle_interface.py`
- `tests/test_article_display_readability_contract.py`
- `tests/test_manual_final_subtitle_editor.py`

## References

The complete cross-project quality-ceiling and SmartSub adaptation record is
`docs/QUALITY_CEILING_ROADMAP.md`. Read it before repeating external source
research. This task remains limited to the manual long-caption workspace.

- https://github.com/buxuku/SmartSub/blob/main/renderer/hooks/useSubtitleHistory.ts
- https://github.com/buxuku/SmartSub/blob/main/renderer/components/subtitle/SubtitleList.tsx
- https://github.com/buxuku/SmartSub/blob/main/openspec/specs/ai-subtitle-segmentation/spec.md
- https://github.com/buxuku/SmartSub/blob/main/openspec/specs/ai-translation-alignment/spec.md
- https://github.com/SubtitleEdit/subtitleedit/blob/main/docs/features/split-break-long-lines.md
- https://github.com/SubtitleEdit/subtitleedit/blob/main/src/ui/Features/Edit/ShowHistory/ShowHistoryViewModel.cs
- https://github.com/SubtitleEdit/subtitleedit/blob/main/src/ui/Features/Files/RestoreAutoBackup/RestoreAutoBackupViewModel.cs
