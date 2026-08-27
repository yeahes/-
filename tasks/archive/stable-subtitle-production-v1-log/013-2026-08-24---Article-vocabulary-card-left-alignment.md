## 2026-08-24 - Article vocabulary card left alignment

- The detailed article vocabulary card now uses a `64` design-pixel left safe
  edge and a `40` design-pixel right inset. Its available width is derived from
  the card rectangle, reducing unnecessary font shrinking while preserving the
  existing two-line overflow guards.
- No subtitle, vocabulary-plan, timing, SRT/ASS, or synthesis behavior changed.
- Added a focused regression for shared left origins and left anchors.
- Vocabulary expressions now capitalize their first Latin letter for display;
  the `1.14x` Latin size multiplier applies only to all-English explanations.
  Embedded Latin text in a Chinese explanation keeps the normal mixed-script
  size, and the Chinese font and wrapping policy stay unchanged.

