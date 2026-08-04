# E2E Caption Regression Handoff

## Scope

This branch repairs a stable pre-ID English boundary that left a relative
clause in one cue and its finite predicate in the next cue. The change is
limited to local deterministic English segmentation before subtitle IDs freeze.

## Root Cause And Invariant

The final pre-ID evaluator only considered the left cue's display fragment.
It did not reject a right cue whose spaCy root was a finite predicate with no
subject. The ordinary repair-window pause rule then skipped the 480 ms boundary
from the real sample.

The repaired invariant is: a final pre-ID display cue must not begin with a
non-imperative finite predicate without its subject. A direct merge across that
specific boundary remains limited to the existing complete 17-19 word
structural-overflow exception. No generic pause threshold is relaxed.

## Verification

- `runtime\\python.exe -X utf8 tests\\test_stable_caption_rules.py`: PASS.
- `runtime\\python.exe -X utf8 scripts\\run_regression.py`: PASS.
- `git diff --check`: PASS; LF/CRLF notices only.
- The first E2E subtitle-only run deliberately remains at
  `E:\VideoCaptioner-e2e-runs\ai-writing-relative-predicate-fixed` as a
  failure witness: it retained `yet ... spot it` and `are completely
  contradicted ...` as separate cues.
- The corrected E2E run at
  `E:\VideoCaptioner-e2e-runs\ai-writing-relative-predicate-fixed-r2` passed:
  276 cues, no render block, zero final-timeline errors, all Chinese IDs
  present, and delegated 7/10/15/18 second PNG inspection passed.

## Cost And Limits

- Both runs used an E2E-local copy of settings and cache. Production runtime
  settings/cache remained read-only.
- Runtime cache statistics record 5 LLM cache misses in the first run and 13
  in the corrected run, 18 recorded external LLM requests total. No ASR,
  WhisperX alignment, or video synthesis was run.
- The subtitle-only runner intentionally used stable-ts fallback timing because
  it received an existing SRT rather than source audio.
- A fresh unseen-audio ASR-to-render blind run remains outstanding.
