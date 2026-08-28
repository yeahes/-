## 2026-08-10 Multiline Title Input On Synthesis Page

- Replaced the one-line podcast title control with a 76px-high plain-text
  editor. Enter creates a real line boundary; Tab still moves focus instead of
  inserting a tab character.
- The UI saves `toPlainText()` and `TaskFactory` preserves internal newlines in
  `SynthesisConfig.podcast_template_title`. Automatic lexical wrapping remains
  available for titles entered on one line.
- The focused persistence/task test, complete video-synthesis safety script,
  syntax compilation, and 25-stage unified regression pass. The unified run
  completed in 412 seconds.
- A hidden-widget render confirmed a 1137x76 title control containing both
  requested lines without overlap. Evidence:
  `tests/caption_audit/out/synthesis-multiline-title-input-20260810.png`.
- No renderer, vocabulary, subtitle, cache, output-name, or manifest contract
  changed in this UI-only follow-up.

