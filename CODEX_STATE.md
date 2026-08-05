# Project State

Status: active
Last verified: 2026-08-05 12:04:26 Asia/Shanghai
Branch: codex/e2e-caption-regression
Verified HEAD: 32a1124
Working tree: clean

## Current Goal
Complete the current-code E2E verification after the boundary-audit false-positive fix.

## Confirmed Facts
- The E2E report anchor did not exist, so time-only alignment recorded `source_audio_missing` before WhisperX.
- `SubtitleTask.source_audio_path` now owns the alignment input; the factory defaults it to legacy `video_path`.
- The task-level time-only regression and unified regression pass.
- Production-model ASR preflight reproduced the historical transcript byte-for-byte.
- Boundary audit now classifies the comma-scoped `forced to, | so it...` case as `review`.
- Current-code E2E completed with 273 fixed IDs, `applied_backend=whisperx-time-only`, no `source_audio_missing`, and a synthesized video under `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805`.

## Approved Decisions
- The original `.m4a` remains read-only; E2E report sidecars remain under `E:\VideoCaptioner-e2e-runs`.
- Do not bypass the hard boundary by changing English text, boundaries, fixed IDs, Chinese allocation, or rendering.

## Next action
Hand off the two current-branch commit SHAs and the verified E2E artifacts for review.

## Unknowns
- Vocabulary-card generation timed out after 301.7 seconds and was skipped; no subtitle LLM requests were made.
- The QA queue retains 40 review items and two unresolved allocation-quality items; final timeline integrity is nevertheless PASS.

## Relevant Paths
- `app/core/entities.py`
- `app/core/task_factory.py`
- `app/thread/subtitle_thread.py`
- `tests/test_stable_caption_rules.py`
- `E:\VideoCaptioner-e2e-runs\ai-writing-whisperx-time-only-asr-preflight-r2\subtitle\original-transcript.srt`
- `E:\VideoCaptioner-e2e-runs\ai-writing-whisperx-time-only-e2e-20260805-r2\run-summary.json`

## Last Verification
- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS.
- `git diff --check`: PASS.
- ASR preflight SHA-256 matches `ai-writing-style-full-e2e-20260804`.

## Next Action
Commit the source-audio contract, then hand off the E2E hard-boundary blocker without another paid run.

## Do Not Regress
- Do not use `video_path` as the only time-only alignment input when an explicit source path is available.

## Unknowns
- Final `whisperx-time-only` acceptance and video synthesis are unverified because the E2E blocks before final alignment.
