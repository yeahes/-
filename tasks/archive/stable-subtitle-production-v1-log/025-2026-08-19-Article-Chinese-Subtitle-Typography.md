## 2026-08-19 Article Chinese Subtitle Typography

- Article-template Chinese subtitles are rendered at 50px with zero extra
  letter spacing. The article-only measurement, wrapping, and per-glyph
  drawing paths share the same spacing metric, so layout cannot silently
  disagree with the rendered line.
- Ordinary subtitles, concept-card detail text, frozen IDs, timing, and page
  Chinese contracts are unchanged. Visual verification:
  `output/article-subtitle-zh-spacing-audit/article-subtitle-zh-50px-zero-spacing-20260820.png`.
- Direct typography and page-mapping checks pass. The complete regression
  passes all 29 checks.

