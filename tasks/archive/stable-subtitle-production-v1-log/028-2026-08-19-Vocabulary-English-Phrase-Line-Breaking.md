## 2026-08-19 Vocabulary English Phrase Line Breaking

- Root cause: the current article-card renderer owned only a single English
  line and reduced the complete expression as far as 20px to satisfy width.
  The vocabulary data and selection stages were not responsible.
- Added an article-card-only phrase fitter. Normal short expressions remain on
  one line; longer multi-word expressions wrap at whitespace into two balanced
  lines with a 32px floor. The 20px fallback is now reserved for an indivisible
  single word.
- Oversized multi-word input fails explicitly instead of rendering as tiny
  text. Four phrase-layout regression tests, card-content tests, compilation,
  and the updated extreme-case contact sheet pass.
- The complete regression reaches the same two known unrelated failures in
  stable-caption structural overflow and article reference wrapping; no
  vocabulary phrase test fails.

