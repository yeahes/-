## 2026-08-08 Manual Draft and Actual Page Preview

- Root cause: `保存人工终稿` persisted a blocked checkpoint but exposed no
  user-authorized preview path. The UI hid the synthesis action and every
  downstream synthesis layer correctly rejected `render_blocked`, so users
  could not inspect a draft even when the only remaining risk was pagination.
- Added an explicit manual-draft capability from editor to home, synthesis
  input, task factory, synthesis thread, and article renderer. It is limited to
  three page-quality blockers, only applies to the `文章单词` template, and
  writes `【人工草稿】<media-stem>.mp4`.
- The capability does not weaken formal synthesis. SRT ownership/hash, manual
  package schema, final timeline and word-ledger hashes, fixed IDs, word spans,
  English text, and cue times are revalidated before draft page planning.
- The editor model now displays the saved renderer projection per cue and
  opens exact page detail. Any text edit removes the stale preview and clears
  both synthesis actions until another background save completes.
- The first v10 read-only replay exposed only 171/203 rows because the preview
  compared current Chinese with a stale `render_plans[].chinese` copy. It now
  uses `parents[].aggregate_chinese`; the replay returns 203/203 rows, 252
  pages, `S0202=4`, and zero missing IDs.
- Manual-editor, synthesis-safety, and publication tests pass. Unified
  regression passes in 223.132 seconds; `git diff --check` passes with only
  existing line-ending notices. External request count is zero; no synthesis
  has run.

