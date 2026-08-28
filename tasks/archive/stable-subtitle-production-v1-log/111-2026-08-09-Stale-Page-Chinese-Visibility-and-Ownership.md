## 2026-08-09 Stale Page-Chinese Visibility and Ownership

- Real desktop replay found 79 blank Chinese actual-page rows while every one
  of the 261 parent cues still had Chinese. The missing text existed only in
  the imported, older actual-page SRT; the current ERROR artifact had no page
  Chinese to display.
- Recovery now accepts old Chinese only after SRT hash, companion-map content,
  page ID, parent ID, word range, English, Chinese, and timing checks, followed
  by an exact match against the current frozen page identity.
- Recovered Chinese is an unconfirmed, non-authoritative draft. It is persisted
  separately through zero-confirmation and partial-confirmation checkpoints;
  it cannot update parent Chinese or pass formal publication.
- Read-only real replay passes with 303 rows, 79 stale drafts, zero blank
  Chinese rows, and 261/261 non-empty parents. Source SRT hash and mtime are
  unchanged. Focused editor/publication suites pass. Final unified regression
  passes 25/25 stages in 356.408 seconds and `git diff --check` passes;
  external and paid calls remain zero.

