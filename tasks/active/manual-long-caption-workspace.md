# Task: Manual Long-Caption Workspace

Status: in_progress
Last reviewed: 2026-08-12 04:21:11 Asia/Shanghai

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

## Planned Stages

### 1. Read-only candidate API

- Expose the existing article planner candidate bundle for one frozen parent
  and requested page count.
- Return the top bounded alternatives with word ranges, page text, final font,
  line layout, timing, pause evidence, and grammar-risk evidence.
- Do not change the candidate selected by the automatic production planner.
- Add focused fixtures derived from accepted and rejected real boundaries;
  do not commit private production journals.

### 2. Parent-local workspace

- Add a focused queue for dense, low-font, overflow, review, or unconfirmed
  captions rather than showing routine warnings.
- Show two to four page candidates, word chips, pause markers, page durations,
  final font and line layout, and an exact article-frame preview.
- Keep split, merge, and boundary experiments in a parent-local draft.
- Allow undo/redo inside that draft and commit the parent as one atomic edit.
- Preserve selection and scroll position when applying or rejecting a draft.

### 3. ID-bound page-Chinese suggestions

- Request Chinese only after the user settles on page word ranges.
- Bind every response to deterministic `Sxxxx.Pxx` IDs and frozen page English.
- Require source echo validation; missing, duplicate, unknown, or mismatched
  pages fail locally without affecting other pages.
- Include bounded neighboring context and retry only failed pages.
- Cache by word-ledger hash, parent ID, page ranges, English, parent Chinese,
  model, and prompt version.
- Suggestions remain visibly unconfirmed until edited or accepted by the user.

### 4. Delta journal and recovery

- Introduce a backward-compatible edit-journal schema that records affected
  parent/page deltas instead of repeated whole-document snapshots.
- Keep schema-v2 packages readable.
- Atomically auto-save the working draft without publishing a formal manifest.
- Offer recovery after close or crash and keep formal publication as the
  existing explicit manual-final save.

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
