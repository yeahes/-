## 2026-08-26 - Right safe edge and punctuation-first detail wrapping

- Kept the article vocabulary card's right content inset at the explicit
  1080p-equivalent of `45px`, matching the left-side safe margin used by the
  content rule.
- Chinese explanations remain on one line when they fit. Once the full text
  exceeds the content width, a legal comma/semicolon break is preferred over a
  closer-looking lexical cut; the existing bounded fallback remains for text
  whose punctuation segments cannot fit.
- Added focused coverage for short comma notes and overflowing comma-separated
  explanations.

