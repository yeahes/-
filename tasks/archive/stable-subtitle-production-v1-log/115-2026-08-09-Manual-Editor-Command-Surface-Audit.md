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

