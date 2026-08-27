## 2026-08-14 Review Workflow Completion

- Completed optional fixed-ID Chinese polish generation and manual application.
  Suggestions run in a background worker, use atomic cache files, and cannot
  overwrite an intervening cell edit, switched subtitle package, or regenerated
  semantic-review queue. Explicit source currency units are now protected in
  addition to numbers, negation, and article-matched terminology.
- Added nearby display-page boundary suggestions using the authoritative word
  ledger and frozen grammar evidence. The editor distinguishes recommended,
  review, and blocked cuts; preview does not mutate subtitles.
- Extended the final boundary audit to schema v2 so selected display-page edges
  and unresolved pre-ID evidence reach the same ID-bound review layer as parent
  cue edges. Display fallback risks stay review-only and do not become a new
  publication blocker.
- Added parent-scoped persistent undo/redo. A parent can be undone without
  overwriting a later edit to another parent; cross-parent, ledger, and audio
  tail-trim operations still require whole-document undo.
- Read-only psychology replay preserved all 195 IDs, cue spans, 2,088 words,
  English, and timing while current code exposed 21 review boundaries. Focused
  tests and the complete 26-stage regression pass; the unified run took 372.3
  seconds and `git diff --check` passes. No production output or paid request
  was made.

