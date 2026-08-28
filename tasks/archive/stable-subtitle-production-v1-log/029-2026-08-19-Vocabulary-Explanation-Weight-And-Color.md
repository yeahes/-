## 2026-08-19 Vocabulary Explanation Weight And Color

- Kept the article-card Chinese explanation on the existing static 500 Medium
  face. The meaning uses 600 SemiBold, so the explanation remains readable
  without competing with the meaning.
- Chinese meanings now use `#2A3F5D`, matching ordinary English subtitles.
  Explanation text and article Chinese subtitles share the `#556780` color
  owner. Meaning typography, text values, selection, timing, and subtitle
  contracts are unchanged.
- Font-role, detail wrapping, card-content, compilation, and refreshed visual
  checks pass. Sample:
  `output/article-vocab-serif-extreme-audit/03-long-concept-detail.png`.
- The final full regression reproduces only the two known unrelated subtitle
  layout failures; no vocabulary-card typography or color target fails.

