## 2026-08-09 Cached Article Evidence Handoff

- A fresh production run still retained `Higee` although article analysis was
  enabled. Its run state proved article correction ran without resume, while
  the saved context proved `haigui` and its source sentences were available.
- The in-memory analysis object lacked the evidence fields that
  `save_article_artifacts()` added only to its output copy. ASR correction and
  translation prompting therefore did not consume the same context shown in
  `article_context.json`.
- `SubtitleThread._resolve_article_context()` now enriches the context before
  save and downstream use. Existing cache entries remain reusable, and ASR
  replacement thresholds, stable English boundaries, word times, fixed IDs,
  Chinese allocation, and rendering are unchanged.
- A cross-stage cached-context regression covers both a person name and a
  domain term: `Li Yang Wenfing -> Liang Wenfeng` and `Higee -> haigui`, with
  preserved time envelopes and the expected Chinese glossary names. Task
  context passes 6/6, article correction passes 29/29, and the unified
  regression passes all 25 stages in 362.3 seconds. External requests are zero.

