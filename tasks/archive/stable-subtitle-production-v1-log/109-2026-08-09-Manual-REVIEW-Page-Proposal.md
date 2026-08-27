## 2026-08-09 Manual REVIEW Page Proposal

- Reproduced the desktop row 113 long cue as fixed parent `S0114`. Its best
  two-page boundary, `ability | to fit...`, is REVIEW rather than HARD, but the
  automatic continuation filter removed it after boundary classification.
- Kept automatic pagination strict and added a manual-only fallback that ranks
  REVIEW candidates after strict planning fails. The 900ms page floor, fixed
  fonts, layout fit, continuous word coverage, and HARD boundary rejection are
  unchanged.
- Added a regression for the exact 17-word sentence. Focused and full manual
  editor tests pass. The current desktop package proposes
  `1129..1137 | 1138..1145`, preserves every frozen parent field, and retains
  all 11 package file hashes. Unified regression passes 24 suites plus one
  syntax step in 338.772 seconds; `git diff --check` passes. External requests,
  ASR, LLM, synthesis, and paid requests are zero.

