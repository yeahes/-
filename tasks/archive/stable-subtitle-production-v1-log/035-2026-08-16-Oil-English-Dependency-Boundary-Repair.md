## 2026-08-16 Oil English Dependency Boundary Repair

- Reproduced eight hard parent-caption boundaries from the frozen
  `石油市场，现在中国说了算？` word ledger, including `April 30 th |
  intraday high`, `oil supply | is suddenly trapped`, `window | the strait
  was shut`, `how long | they can withstand`, and `acting | as if`.
- Added parser-backed pre-ID guards for the shared dependency classes rather
  than matching episode text. The pre-ID repair owner now tries another legal
  timestamp cut first and may keep one complete structural-overflow parent only
  when the same final contract proves that no normal-limit temporal cut exists.
- Kept the renderer's exception narrower: only a complete, timed clause restart
  can remain REVIEW-eligible; lexical atoms still cannot be relaxed. Added a
  rendered-result regression that rejects `the strait was shut.` as an
  isolated display page.
- Frozen replay preserved all 1,537 ordered words and their complete coverage,
  reduced parent cues from 147 to 140, and reduced hard English boundaries from
  eight to zero. The long conditional is repartitioned as 17+8 words instead
  of being retained as one 25-word parent.
- Focused stable-caption and article-readability suites pass. The complete
  `runtime\python.exe scripts\run_regression.py` command exits zero. Replay
  evidence is
  `E:\VideoCaptioner-e2e-runs\oil-market-english-boundary-fix-20260816\frozen-mainline-report.json`;
  production outputs were not changed.

