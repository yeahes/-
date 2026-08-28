## 2026-08-04 Static Fixed-Width Renderer Layout

- Root cause: a same-page visual wrap and a timed visual page were treated as
  the same operation. The renderer then required a word-gap transition for
  text that already fit in two fixed-font lines. Chinese layout also used a
  30-character cutoff instead of the rendered 46px width.
- The planner now uses actual pixels: normal 1455px English width, then a
  1498px safe-width profile, with up to two static English lines. Chinese uses
  up to two 46px lines without a character-count gate. Only a cue that fails
  both static layouts is eligible for word-timed pagination and its 900ms gate.
- Offline replay of `ai-writing-style-full-e2e-20260804` now gives 215/215
  valid plans. `S0188`, `S0202`, `S0208`, and the former residual `S0110` stay
  on one static page with unchanged frozen cue data. Representative PNG/report:
  `E:\VideoCaptioner-e2e-runs\renderer-layout-profile-validation`.
- Delegated regression passed: `tests\test_stable_caption_rules.py`,
  `scripts\run_regression.py`, and `git diff --check`. No ASR, LLM request,
  or full-video synthesis ran.

