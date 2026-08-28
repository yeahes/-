## 2026-08-18 Article Brand Logo Selection

- Added an article-template-only `品牌 Logo` picker to the synthesis page. The
  chosen image path is persisted and frozen into the synthesis task; clearing
  the field restores the explicit no-Logo state.
- Removed the article cover's implicit Economist branding. Custom assets are
  loaded once, kept at their original aspect ratio, and centered inside the
  existing 100x50 design safe area without crop or stretch.
- Missing or unreadable selected files now fail before FFmpeg starts. Focused
  tests cover the empty default, UI persistence, task forwarding, wide and
  square asset geometry, centering, and invalid-file errors.
- `runtime\python.exe scripts\run_regression.py` and `git diff --check` pass.
  A 1920x1080 inspection frame is saved at
  `output/logo-switch-samples/article-template-custom-logo.png`.
- This change does not modify ASR, English segmentation, Chinese translation,
  fixed IDs, subtitle timing, page planning, vocabulary selection, SRT/ASS,
  manifest contracts, or the synthesis entry point.

