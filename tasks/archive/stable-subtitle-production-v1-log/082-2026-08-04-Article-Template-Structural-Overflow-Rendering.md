## 2026-08-04 Article Template Structural-Overflow Rendering

- Root cause: the article-template renderer sliced Chinese wrapping to two
  lines, silently dropping all remaining translated characters for a long,
  structurally protected English cue.
- Fix: the renderer now selects the largest Chinese font that fits the complete
  translation in two lines and draws every wrapped line. It does not change
  English boundaries, text, IDs, word ledger, Chinese allocation, or timing.
- Real S0004 offline frame validation confirmed the full 77-character Chinese
  text, zero English/Chinese alpha-mask overlap, and no crop. The evidence is
  under `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\overflow-fix-frame`.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`,
  `runtime\python.exe -X utf8 scripts\run_regression.py`, and
  `git diff --check` passed. No long production video was rerendered.

