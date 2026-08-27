## 2026-08-12 Preferred-Font Same-Screen Reflow

- The v19 same-screen score could prefer 54px single-line text over a valid
  56px two-line layout. The final typography owner now keeps the largest legal
  size and falls back through 54/52/50px only after a larger size fails.
- A read-only replay of the 310-page `好莱坞最新热潮：姐弟恋` manual package
  changes only `S0033.P01`, `S0219.P01`, and `S0234.P01` from 54px to 56px.
  Page IDs, word ownership, English, Chinese, timing, and all other 307 pages
  remain unchanged. The distribution changes from 299/6/2/3 to 302/3/2/3 for
  56/54/52/50px.
- Article readability, manual-editor, stable-publication/UI 63/63, and all 25
  unified regression stages pass. The full run completed in 459.2 seconds.

