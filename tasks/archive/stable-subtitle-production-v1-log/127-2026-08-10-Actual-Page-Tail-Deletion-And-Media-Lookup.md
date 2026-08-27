## 2026-08-10 Actual-Page Tail Deletion And Media Lookup

- Added actual-page menu entries for tail-cut preview and deletion. The session
  maps the selected page ID to its first frozen word ID; a cut inside one parent
  retains earlier pages and truncates only that parent's suffix before removing
  all later cues.
- Added exact inverse lookup for the organized result-directory contract. A
  subtitle under `<stem>-处理结果/` may recover one same-stem supported media
  sibling from the outer directory when the manifest media path is absent or
  stale. Ambiguous candidates fail closed.
- Manual-final save continues to create a non-destructive derived M4A, records
  its path and SHA-256, and makes synthesis override a stale original-media UI
  selection with that derived file.
- Manual-editor tests pass, stable-publication/UI passes 57/57, and the unified
  regression passes 25/25 stages in 459.5 seconds. A read-only 303-page replay
  trims `S0254.P02` at 969.689 seconds, keeps its first page, restores exactly on
  undo, and changes zero of nine package files. External and paid requests are
  zero.

