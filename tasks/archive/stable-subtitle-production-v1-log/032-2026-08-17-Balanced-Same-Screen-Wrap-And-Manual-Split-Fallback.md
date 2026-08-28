## 2026-08-17 Balanced Same-Screen Wrap And Manual Split Fallback

- Replaced first-fit article English wrapping with all-profile comparison using
  measured pixel-width balance. Page-turn-only tight-pause evidence no longer
  distorts a same-screen line break; lexical, entity, numeric, and other atomic
  protections remain unchanged.
- Added a user-confirmed high-risk fallback for `split into N pages`. Strict and
  REVIEW planning still run first. If both fail, the confirmed proposal uses
  only authoritative timed-word boundaries and records the original HARD
  evidence for manual review; it does not change parent English, IDs, timing, or
  audio.
- Added the separate three-English-line/one-Chinese-line vertical origin and
  bumped the display planner to v24 so stale page layout caches are not reused.
- Read-only oil replay kept 163 pages and two three-line pages, reduced pages
  below a 0.60 two-line balance ratio from 23 to 18, and reduced extreme ratios
  below 0.45 from eight to two. Focused layout, manual-editor, and GUI tests pass;
  the complete regression command also passes.

