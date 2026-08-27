## 2026-08-10 Semantic Two-Line Vocabulary Notes

- Replaced the article concept-note card's generic character wrapper with a
  dedicated two-line layout path. It uses the existing deterministic Chinese
  token boundaries, avoids attached punctuation and weak line starts, and
  prioritizes the semantic boundary after a short explanatory lead-in.
- The production note now renders as `本句用数学隐喻说明 / 留学回报的旧有优势已随市场变化而消失。`.
  Short notes remain one line; long notes remain capped at two lines.
- Two focused regressions and the existing card-content test pass. A read-only
  replay of 70 unique cached concept notes found zero content loss, overflow,
  non-token breaks, or invalid second-line starts.
- The checked 1920x1080 frame is
  `tests/caption_audit/out/article-vocab-semantic-wrap-20260810.png`.
- The unified regression completed 23/25 stages. Stable-caption smoke and the
  display-page translation contract fail on pre-existing English layout/font
  expectations that reproduce without the concept-note path. No English page
  behavior was changed here.
- No vocabulary prompt/cache schema, selection, timing, ASR, English or Chinese
  subtitle, fixed ID, timeline, SRT/ASS, manifest, or synthesis-entry contract
  changed. No full video or external model request ran.

