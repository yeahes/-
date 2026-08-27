## 2026-08-15 Renderer Page Visual Stability v20

- Compared the existing renderer plan with the Netflix English timed-text
  guide and TED subtitling tips. Both support two ordinary lines, linguistic
  unit preservation, balanced line length, and controlled reading load; neither
  publishes an adjacent-page density-delta threshold.
- Added renderer-only sequence scoring for adjacent pressure, font, and line
  count while preserving the existing candidate set, frozen IDs, English,
  word ledger, and timing. Pressure continuity is subordinate to consecutive
  overload, and typography continuity is a weak cross-parent tie-breaker only.
- Added `incomplete_review_count` to sequence cost with an explicit review
  penalty. A complete coordinated restart such as `investment, | and it
  works...` remains eligible, while a modifier/predicate break such as
  `officially | overtook...` cannot win from visual continuity alone.
- Extended secondary safe-page review to 54px static pages. Replacement pages
  still require 56px, six words, 900ms, and a complete supported boundary.
  Ordinary 56px two-line pages do not enter this escalation solely for above-
  average density.
- Bumped the page planner to `article-fixed-font-pages-v20`; page projection
  caches must be regenerated while ASR and translation caches remain reusable.
- Focused readability contracts pass. Read-only old/new replay changed one
  plan in the 147-parent oil package and one in the 211-parent Mixue package;
  both changes merged unnecessary short-tail pages into 56px two-line pages.
  English coverage, ID order, word ranges, and timing remained exact, and no
  production output or paid request was made. Existing v19 manual-final
  packages reopened with 147/211 cues, 168/256 saved pages, and unchanged
  recursive size, mtime, and SHA-256 snapshots. The complete 26-stage
  regression exits zero.

