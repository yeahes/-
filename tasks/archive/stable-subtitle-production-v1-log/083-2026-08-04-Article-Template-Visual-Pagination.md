## 2026-08-04 Article Template Visual Pagination

- The prior no-truncation repair was necessary but not sufficient: S0004 still
  showed its entire 37-word English/77-character Chinese cue in one screen.
  This preserved text but was not readable.
- Long article-template cues now paginate deterministically inside their
  existing frozen cue envelope. The page budget is at most 16 English words or
  30 Chinese characters; page transitions use equal fractions of the original
  cue duration. English, Chinese, IDs, word spans, cue times, allocation, SRT,
  ASS, and manifest output do not change.
- The render cache now includes the page index. The real S0004 at 13.5s,
  17.5s, and 21.5s produced three PNGs, each with two English lines and one
  Chinese line, no clip, zero visible English/Chinese overlap, and exact
  full-text reconstruction across pages. Evidence is under
  `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\visual-pagination-validation`.
- Delegated `tests\test_stable_caption_rules.py`, unified regression, and
  `git diff --check` passed. No external request or full video synthesis ran.

