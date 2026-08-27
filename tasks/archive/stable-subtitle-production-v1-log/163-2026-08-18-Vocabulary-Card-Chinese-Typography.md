## 2026-08-18 Vocabulary Card Chinese Typography

- Confirmed the active simplified card renders directly at 1920x1080; the
  observed softness came from thin Regular 400 Chinese strokes and a low-
  contrast concept-note gray, not from an obsolete preview or bitmap scaling.
- Switched the Chinese gloss and concept note to Medium 500. Increased concept
  notes from 26px/20px to 28px/22px design sizes and darkened their color from
  `RGB(122,132,147)` to `RGB(96,108,124)`.
- Kept the two-line width fitter and overflow fallback. All ten concept cards
  in the complete local cache fit at the new maximum size.
- Three focused tests and the complete regression pass. The inspected
  before/after render is
  `output/current-vocab-font-audit/article-vocab-typography-comparison-20260818.png`.
- No vocabulary data, selection, timing, subtitle, ID, SRT/ASS, manifest, or
  encoding contract changed.

