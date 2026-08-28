## 2026-08-05 Chinese Visual Page Word-Boundary Guard

- Root cause: renderer-only Chinese page allocation used raw character offsets
  proportional to English word counts, so `大陆` could be cut as `大 | 陆`.
- Added the required MIT `jieba` 0.42.1 runtime subset under `app/_vendor`.
  Strict article page planning uses its deterministic word-end offsets plus
  punctuation/phrase evidence. It fails closed with
  `chinese_no_safe_visual_boundary` when no safe split exists; no character
  slicing, font shrinking, cue mutation, or translation rerun is used.
- The real 273-cue `china-ai-cheaper-e2e-20260805` artifact replays with
  273/273 valid plans. S0055 now ends page one at `大陆` and starts page two
  at `那么`. Updated PNG evidence is under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805\visual-pagination-fixed-20260805`.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`,
  `runtime\python.exe -X utf8 scripts\run_regression.py`, and
  `git diff --check` passed. No external request or full-video synthesis ran.

