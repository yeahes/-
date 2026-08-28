## 2026-08-04 Article Renderer Word-Timeline Gate

- The article renderer now fails closed when the stable manifest, final cue
  timeline, or word ledger is missing or mismatched, even when all cues would
  otherwise fit on one page. This prevents unverified timing from reaching
  synthesis.
- Fixed 58px English / 46px Chinese pagination remains renderer-only. Page
  switches require ledger word gaps and 900ms minimum page duration; no font
  shrinking or cue/ID mutation is used as a fallback.
- Full-artifact preflight found 212/215 plans valid. `S0188`, `S0202`, and
  `S0208` remain blocked because no grammar-safe word-gap schedule satisfies
  the minimum page duration. Evidence:
  `E:\VideoCaptioner-e2e-runs\renderer-word-timeline-validation\preflight-short-cues.md`.

