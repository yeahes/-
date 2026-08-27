## 2026-08-10 Manual Import Semantics And Per-Page Font Recalculation

- Reproduced the damaged manual package without modifying it. Its history kept
  21 edits, but one failed formal-boundary move reduced 310 page rows and seven
  boundary overrides to zero; the old save also made the discoverable original
  parent SRT byte-identical to the manual-final SRT.
- Manual imports now have one meaning each: manual-final continues, original-top
  restarts from the stable checkpoint, and actual-page remains a snapshot that
  resolves to the latest matching manual package. Save preserves the immutable
  original parent and original actual-page exports.
- Formal-boundary reflow is transactional. Any local rebuild failure restores
  cues, pages, overrides, and history; publication detects and blocks a silent
  collapse of previously recorded manual page state.
- `article-fixed-font-pages-v17` selects 56/54/52/50px independently for every
  final page after automatic or manual page spans are frozen. The parent font is
  the minimum page size only as a summary. The focused fixture changes a
  two-page result from 52/52 to 52/56 without changing text, IDs, word spans,
  page boundaries, or timing.
- Read-only real-package replay checked 262 parents and 303 pages. Six pages
  increase in size, none decrease, and all nine package files remain
  SHA-256-identical. The unified regression passes all 25 stages in 374.5
  seconds; `git diff --check` exits zero. External and paid requests are zero.

