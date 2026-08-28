## 2026-08-08 Flat Actual-Page Editor Contract

- Replaced the parent-row `actual pages` count/detail column with the normal
  four-column table projected as one real display page per row. This exposes
  the exact page timing and bilingual text where editing already happens and
  restores the full English/Chinese table width.
- Every page row retains its deterministic page ID, unchanged parent subtitle
  ID, continuous word range, page time, and selected font size. English remains
  frozen in page view; Chinese is directly editable. The user can switch to
  `查看父字幕` for word-ledger-backed formal English boundary operations.
- Page-view save validates all page identities and reuses the existing
  SHA-256-bound page artifact for no-op or Chinese-only edits. It never invokes
  a replacement page plan; identity, span, or time drift blocks the save.
- Stable publication and manual-final save now emit a discoverable
  `<media-stem>-实际分页双语字幕.srt` plus
  `<media-stem>-实际分页映射.json` next to the source audio. Authoritative page
  SRT import recovers parent/page ownership instead of minting new fixed IDs.
- Focused manual-editor and publication suites pass. The second full unified
  regression completed naturally with 25/25 suites passing, exit code 0, in
  494.303 seconds. Final `git diff --check` passes with only existing line-ending
  notices. No network, ASR, LLM, FFmpeg, synthesis, or paid request ran.

