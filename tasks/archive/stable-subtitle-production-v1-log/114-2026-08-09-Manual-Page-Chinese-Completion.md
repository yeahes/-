## 2026-08-09 Manual Page Chinese Completion

- Replayed the current 309-page desktop manual package. The remaining ten blank
  pages belonged to five re-paged parents whose complete parent Chinese still
  existed, while no page-level Chinese matched the new word ranges.
- Added a strict local proposal path for manual overrides. It allocates current
  parent Chinese in English page-word proportions only at existing safe Chinese
  token boundaries. The proposal is visible and hash-persistable as an
  unconfirmed draft, but cannot become authoritative or pass publication until
  explicitly edited or confirmed.
- Preserved the source priority of confirmed manual Chinese and exact recovered
  drafts. A local proposal outranks stale artifact text, and failure to find a
  safe split remains blank and blocked rather than cutting a Chinese word.
- Fixed repeated `N pages -> N pages` requests so identical page identities are
  a no-op. Confirmed page Chinese, history, and boundary overrides remain
  unchanged; true page-count or word-range changes still invalidate page
  Chinese for review.
- Real read-only replay reports 309/309 rows with Chinese: 220 authoritative,
  79 recovered identity drafts, and 10 local proposals. The five affected
  parent groups all concatenate exactly to current parent Chinese. Source SRT
  SHA-256, length, and mtime did not change.
- Manual-editor tests pass 45/45, stable-publication/UI tests pass 43/43, and
  unified regression passes 25/25 stages in about 345 seconds. `git diff
  --check` passes. No external, ASR, LLM, FFmpeg, synthesis, or paid request ran.

