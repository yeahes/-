## 2026-08-25 - Article vocabulary meaning size

- Raised the article vocabulary Chinese-meaning starting size to an actual
  rendered `45px`. The existing two-line fitter still measures actual glyph
  width and lowers the size only when needed, down to the unchanged `29px`
  rendered floor.
- Horizontal alignment does not participate in line breaking; it only changes
  the drawing origin after wrapping is selected.
- Added a focused regression for the short-meaning `45px` rendered size.

