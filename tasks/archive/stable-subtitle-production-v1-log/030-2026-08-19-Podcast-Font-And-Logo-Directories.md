## 2026-08-19 Podcast Font And Logo Directories

- Moved all bundled podcast `.ttf`/`.otf` files into
  `resource/podcast_template/fonts/`, including the new Source Han Serif CN
  SemiBold meaning face and Adobe Source Serif Pro SemiBold. Image assets
  remain outside the font directory; the Source Serif Pro license is under the
  font directory's `licenses/` subdirectory.
- Added `resource/podcast_template/article_vocab/logos/` as the fixed user Logo
  directory. The synthesis-page picker always starts there instead of making
  the user navigate from the process working directory or a previous external
  file location.
- Font ownership/path checks, opening-title isolation, meaning-card rendering,
  Logo initial-directory behavior, and syntax checks pass.

