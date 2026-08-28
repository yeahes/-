## 2026-08-21 - Article Cover Date Control

- Restored the article-template `模板日期` input over the existing
  `podcast_template_date` task field. It is visible only for the article-word
  template, persists on edit and task creation, and accepts an empty value to
  suppress the overlay.
- Replaced the removed fixed date block with a borderless top-right gradient
  scrim. It uses `#1B2F4A`, automatically strengthens until the actual glyph
  footprint reaches at least 4.5:1 contrast, and fades only outside the text
  footprint toward the left and bottom. `#FBF6ED` date text uses the bundled
  `resource/podcast_template/fonts/AlimamaShuHeiTi-Bold.ttf`. The cover mask
  owns the outside corner, and no independent pill radius remains.
- Static logo/date decoration is composed once before the frame loop. The
  formal renderer generated the current real-cover preview under
  `output/article-date-gradient-preview-20260821/`.
- Focused render and synthesis safety tests pass. Real and light-cover visual
  checks are stored under `output/article-date-reenabled-20260821/`.

