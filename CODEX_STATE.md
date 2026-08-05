# Project State

Status: complete
Last verified: 2026-08-05 23:17:35 Asia/Shanghai
Branch: codex/e2e-caption-regression
Verified HEAD: d90c5ab
Working tree: clean

## Current Goal
Complete and verify the current-code boundary/allocation/renderer E2E regression.

## Confirmed Facts
- Current-code E2E completed with 271 fixed IDs and 2,897 ledger words under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805-r3`.
- `final-cue-timeline.json` is `PASS`, applied backend is
  `whisperx-time-only`, overall fallback is false, and `source_audio_missing`
  is absent. ID, English, and Chinese mapping sets are complete.
- The 64.8-66.5s speech interval remains covered through 67.975s.
- The final video is 62,239,995 bytes and 16:43.66 at the E2E path.

## Approved Decisions
- The original `.m4a` remains read-only; E2E report sidecars remain under `E:\VideoCaptioner-e2e-runs`.
- Do not bypass the hard boundary by changing English text, boundaries, fixed IDs, Chinese allocation, or rendering.

## Next action
Hand off the three commits and the verified E2E artifact paths to the main window.

## Unknowns
- Subtitle cache statistics recorded 21 misses: 13 full translations, one style
  retry, four allocations, and three fragment retries.
- Vocabulary generation timed out after 319.1 seconds and was skipped; its
  per-attempt provider count is not instrumented.
- QA has zero structural blockers and three unresolved Chinese
  allocation-quality reviews; ordinary reading/timing warnings remain.

## Last Verification

- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS.
- Final timeline: PASS; no `source_audio_missing`; no overall stable-ts fallback.
- MP4 metadata: 16:43.66, 1920x1080, H.264/AAC.
- `git diff --check`: PASS.

## Relevant Paths
- `app/core/utils/podcast_learning_video.py`
- `tests/test_stable_caption_rules.py`
- `app/_vendor/jieba/NOTICE.txt`
- `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805\visual-pagination-fixed-20260805`
