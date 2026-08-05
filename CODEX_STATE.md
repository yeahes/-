# Project State

Status: in_progress
Last verified: 2026-08-06 03:06:06 Asia/Shanghai
Branch: codex/e2e-caption-regression
Verified HEAD: 47ae5f8
Working tree: modified boundary/renderer code and tests; no staged files

## Current Goal
Complete the current-code boundary/allocation/renderer E2E regression and hand
off the verified artifacts, while preserving the renderer's fail-closed gate.

## Confirmed Facts
- Cache-first real-audio E2E completed its subtitle stage under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-followup` with 266
  fixed IDs and 2,897 ledger words.
- `final-cue-timeline.json` is `PASS`, applied backend is
  `whisperx-time-only`, overall fallback is false, and `source_audio_missing`
  is absent. ID, English, and Chinese mapping sets are complete.
- The 64.8-66.5s speech interval remains covered by `S0017` through 67.975s.
- Video synthesis was blocked before ffmpeg for four fixed-font structural
  overflow cues (`S0052`, `S0176`, `S0196`, `S0258`); no new video exists.

## Approved Decisions
- The original `.m4a` remains read-only; E2E report sidecars remain under `E:\VideoCaptioner-e2e-runs`.
- Do not bypass the hard boundary by changing English text, boundaries, fixed IDs, Chinese allocation, or rendering.

## Next action
Main window reviews the committed E2E artifacts and decides whether the four
renderer structural-overflow cues warrant a separate renderer task.

## Unknowns
- The four renderer-blocked cues need a separate fixed-font layout decision;
  this task intentionally did not change their text, timing, or style.
- QA artifacts retain ordinary review/warning items even though the final cue
  timeline structural gate passed.

## Follow-up Facts

- Complete phrase starts receive a soft renderer penalty; stranded lexical
  dependencies remain hard-blocked.
- Focused tests, `scripts/run_regression.py`, and `git diff --check` pass at the
  current working tree.
- External LLM request count for the real-audio follow-up was 0 because the
  isolated E2E cache supplied every translation/allocation response.

## Last Verification

- `runtime\python.exe scripts\run_regression.py`: PASS.
- Final timeline: PASS; applied backend `whisperx-time-only`; no
  `source_audio_missing`; no overall stable-ts fallback.
- `git diff --check`: PASS.
- Synthesis stopped at the structural renderer gate; no MP4 metadata is
  available for the follow-up run.

## Relevant Paths
- `app/core/utils/podcast_learning_video.py`
- `tests/test_stable_caption_rules.py`
- `app/_vendor/jieba/NOTICE.txt`
- `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805\visual-pagination-fixed-20260805`
