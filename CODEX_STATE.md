# CODEX State

Status: English continuation-boundary repair and E2E subtitle-stage validation complete.

Last verified: 2026-08-04 16:51:41 Asia/Shanghai

Branch: codex/e2e-caption-regression

Verified HEAD: a45da1e6df443422dd626e884a470bd32237ce7d

Working tree: modified by the verified English repair and its documentation.

## Current Goal

Commit the verified English continuation-boundary repair and E2E evidence as separate commits.

## Confirmed Facts

- A final pre-ID boundary now rejects a right cue whose spaCy root is a finite
  predicate without a subject. The narrow repair may cross that target
  boundary's recorded pause, but still requires the existing 17-19-word
  structural-overflow proof before merging.
- The regression explicitly covers the real relative-clause shape with a
  480 ms pause.
- `ai-writing-relative-predicate-fixed-r2` passed subtitle-stage validation:
  276 cues, no render block, fixed-ID timeline `PASS` with zero errors, and
  the 14.240-20.320s relative clause is one readable cue.
- The second run used only copied E2E settings/cache and no ASR, WhisperX
  alignment, or video synthesis.

## Last Verification

- `runtime\\python.exe -X utf8 tests\\test_stable_caption_rules.py`: PASS.
- `runtime\\python.exe -X utf8 scripts\\run_regression.py`: PASS.
- `git diff --check`: PASS; LF/CRLF notices only.
- Four delegated PNG frame checks: PASS.

## Next Action

Commit the English code/test change, then the E2E state and documentation change.

## Unknowns

- No fresh unseen-audio ASR-to-render blind run has completed on this repair.
