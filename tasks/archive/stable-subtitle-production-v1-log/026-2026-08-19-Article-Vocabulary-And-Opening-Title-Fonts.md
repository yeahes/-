## 2026-08-19 Article Vocabulary And Opening Title Fonts

- Bundled Source Han Serif CN SemiBold now owns Chinese meanings on article
  vocabulary cards, while Source Han Serif CN Bold remains the independent
  opening-title face. Meaning/detail values are unchanged.
- Article vocabulary English phrases and overview words now use Source Serif
  Pro SemiBold. English and numeric runs embedded in Chinese explanations use
  Roboto Slab Regular, while Chinese runs stay on Chill Yunmo Gothic Medium.
  The mixed-script width owner is shared by wrapping and final drawing. The
  combined render is saved under
  `output/article-vocab-common-audit/all-vocab-typography-color-updates.png`.
  The earlier contact-sheet render is saved under
  `output/article-vocab-serif-audit/title-and-vocab-contact-sheet-20260819.png`.
- Font-path, title-wrap, card-content, and visual checks pass.
- Nine focused vocabulary typography/layout tests and the mixed-script
  compatibility check pass. The complete regression still fails only in the
  existing `stable caption smoke tests` English-boundary assertion and the
  existing `article display readability contract` reference-wrap assertion;
  no vocabulary typography, color, or rendering target fails.

