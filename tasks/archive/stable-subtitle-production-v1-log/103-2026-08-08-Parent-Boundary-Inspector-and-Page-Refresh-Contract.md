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

