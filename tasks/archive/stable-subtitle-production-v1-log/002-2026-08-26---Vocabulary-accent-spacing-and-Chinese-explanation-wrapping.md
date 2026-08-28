## 2026-08-26 - Vocabulary accent spacing and Chinese explanation wrapping

- Moved the article vocabulary card's blue accent farther left from the content,
  reduced it to 6px, and added a 10px vertical inset so it tracks the text
  block without spanning the inter-section breathing room.
- Reordered mixed Chinese explanation wrapping to prefer a slightly longer
  second line and balanced widths before semantic tie-breakers. Text remains
  complete and limited to the existing two-line budget.
- Focused vocabulary/layout checks pass (`9 passed`). Render sample:
  `output/current-production-vocab-render-20260826/fixed-accent-and-detail-wrap-card.png`.
- Follow-up geometry is now explicit: 45px from the container to the accent,
  9px rendered accent width, and 45px from the accent to the text at 1080p.
  Rounded corners were removed and the accent height is measured from the
  visible glyph bboxes. Updated sample:
  `output/current-production-vocab-render-20260826/fixed-accent-45px-glyph-aligned-card.png`.
- The opening title card now shares the same square accent geometry and 45px
  spacing. Detail wrapping no longer admits arbitrary per-character fallback
  boundaries; it balances only at deterministic lexical/punctuation boundaries
  so visual optimization cannot split a Chinese word. Focused checks pass
  (`11 passed`). Title sample:
  `output/current-production-vocab-render-20260826/fixed-title-accent-45px-glyph-aligned.png`.

