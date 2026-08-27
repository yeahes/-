## 2026-08-08 Persisted Manual-Draft Pages

- Fixed the false invalidation that disabled synthesis after review marks were
  painted: background/tooltip `dataChanged` roles no longer count as text
  edits; English/Chinese `EditRole` updates still invalidate the saved package.
- Page-blocked saves now materialize `manual-draft-page-plan.json` with an
  explicit Chinese mapping for every frozen page and bind it by SHA-256 in the
  manifest and manual override. The editor and renderer read the same file.
- Manual-draft preflight now rejects missing, tampered, or cross-package page
  artifacts. It never recalculates pages during synthesis.
- Saved sessions own their package artifact directory and publish the current
  `translations.json`; incomplete legacy packages keep their source-artifact
  fallback until the next save.
- The current desktop package replayed as 203 plans / 252 pages, minimum 50px,
  with non-empty explicit Chinese on every page. No artifact was written back.
- Focused suites and unified regression pass; unified runtime was 284.672s and
  `git diff --check` returned zero. External requests and FFmpeg runs: zero.

