## 2026-08-09 Empty Intermediate Page Edit Recovery

- The current desktop package had advanced from 303 to 309 display pages after
  six manual page-structure overrides. Its saved intermediate edit journal
  contained 89 blank page-Chinese records while the imported old page SRT still
  provided 79 exact identity-matched drafts.
- Root cause was ownership priority in `_display_page_previews`: the presence
  of a blank edit record hid the recovered draft unless the parent translation
  had also changed. Exact recovered drafts now remain visible and unconfirmed;
  changed word spans remain blank.
- Unrelated structural edits now preserve stale/unconfirmed draft metadata so
  visible old Chinese cannot be silently promoted to authoritative Chinese.
- Read-only real-package replay reports 309 rows, 79 recovered drafts, and 10
  legitimate blank changed-span pages. Source SRT SHA-256 and mtime are
  unchanged. Manual-editor tests pass 44/44, stable-publication UI tests pass
  43/43, and unified regression passes 25/25 stages in 339.2 seconds.
  `git diff --check` passes. Network, ASR, LLM, synthesis, and paid requests are
  zero.

