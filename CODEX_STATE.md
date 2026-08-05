# Project State

Status: active
Last verified: 2026-08-05 15:12:18 Asia/Shanghai
Branch: codex/e2e-caption-regression
Verified HEAD: e6b9b99
Working tree: modified (visual-page word-boundary fix and vendored tokenizer)

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
Review the visual-page diff, stage the focused renderer/test/docs commit, and re-check the final artifact paths.

## Unknowns
- Vocabulary-card generation timed out after 301.7 seconds and was skipped; no subtitle LLM requests were made.
- The QA queue retains 40 review items and two unresolved allocation-quality items; final timeline integrity is nevertheless PASS.

## Last Verification

- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`: PASS.
- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS.
- `prepare_article_visual_page_plans` on the 273-cue current-code artifact: PASS, 273/273 cues.
- `git diff --check`: PASS.

## Relevant Paths
- `app/core/utils/podcast_learning_video.py`
- `tests/test_stable_caption_rules.py`
- `app/_vendor/jieba/NOTICE.txt`
- `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260805\visual-pagination-fixed-20260805`
