## 2026-08-09 English-Only Podcast Template Output

- Added the user-selected manual toggle workflow to the synthesis command bar:
  unchecked renders bilingual subtitles; checked renders English subtitles
  only. The action appears only with the English learning template and persists
  through the existing configuration system.
- Froze the value into `SynthesisConfig` and passed it explicitly through the
  synthesis thread to both static podcast renderers. Rendering omits only the
  bottom Chinese subtitle; English positioning, article pagination, vocabulary
  selection, card timing, and card Chinese content are unchanged.
- Added separate `-英文字幕版` output prefixes for article-word, dark-podcast,
  and manual-draft output, so the second run cannot overwrite the bilingual
  file. One-click dual output remains intentionally out of scope.
- Added regressions for default bilingual behavior, frozen task propagation,
  both output-name families, the UI handler, and pixel equality above the
  Chinese subtitle region in both templates. Syntax checks and focused scripts
  pass; the unified regression passes 25/25 stages in 362.9 seconds.
- Opened and checked the two 1920x1080 English-only template samples plus the
  1400x850 synthesis-page screenshot in `tests/caption_audit/out/`. No real
  encoded pair, ASR, external model, or paid request ran.

