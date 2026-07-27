# Current State

Last updated: 2026-07-28

## Working

- E-drive working copy is the active project.
- Stable mode uses local English segmentation from word-level timestamps.
- Timeline alignment now supports selectable backends: `stable-ts` (default), experimental `whisperx`, and `whisperx-time-only`.
- WhisperX runs through the isolated `whisperx-runtime` environment and falls back to stable-ts/original timing if unavailable.
- `whisperx-time-only` keeps stable-ts as the cutting timestamp backend, then applies WhisperX only to final subtitle start/end times.
- LLM translation is limited to Chinese generation/allocation.
- Podcast template can resolve subtitles from `stable-final-manifest.json`.
- Regression smoke tests exist in `tests/test_stable_caption_rules.py`.
- Generated subtitle audits exist in `tests/audit_stable_outputs.py`.
- A single regression entry exists: `runtime\python.exe scripts\run_regression.py`.
- Allocation now uses global subtitle IDs (`S0001`, `S0002`, ...), not positional lists, for Chinese writeback.
- Allocation artifacts record inputs, raw returns, validation, retry logs, final mappings, unresolved groups, and structure errors.
- The current local `work-dir` samples `222`, `777`, and `999` are not present in this checkout, so `tests\audit_stable_outputs.py 222 777 999` reports `MISSING`.

## In Progress

- Reducing coupling in `screen_editor.py`.
- Making final SRT/ASS output and video synthesis use the same stable subtitle.
- Converting discussion-derived rules into tests and docs.
- Verifying long-audio Chinese allocation drift with fresh generated outputs.

## Known Issues

- `screen_editor.py` remains highly coupled.
- Current tests are smoke/regression tests, not full fixture coverage.
- Existing generated outputs under `work-dir` may be stale unless regenerated after code changes.
- Some ASR/stable-ts word timings can be too short or contain gaps.
- Full `whisperx` backend changes word timestamp alignment before stable cutting, so English boundaries and downstream Chinese can change.
- `whisperx-time-only` is the lower-risk WhisperX mode for samples where timing improves but existing cutting/translation should remain stable.
- Chinese translation quality still depends on LLM output and prompt stability.
- Validation blocking is strongest for translation-structure errors; confirm any new ERROR class is wired to synthesis blocking before relying on it.
- Git has no `checkpoint-2026-07-23` tag or branch in this checkout.

## Current Production Recommendation

Use:

- Stable mode on.
- stable-ts/time alignment on when available.
- Keep `stable-ts` as the default alignment backend.
- Prefer `whisperx-time-only` when WhisperX timing is better but stable-ts cutting/translation should be preserved.
- Use full `whisperx` only as an experimental backend when boundary changes are acceptable.
- Candidate quality check off.
- Preserve backchannels.
- Use `stable-final-manifest.json` for podcast template synthesis.
- After code changes, regenerate subtitle outputs before judging a newly rendered video.

Avoid:

- LLM-based English segmentation in production stable flow.
- Broad edits to `screen_editor.py` without tests.
- Judging fixes from old rendered videos or stale subtitle files.

## Latest WhisperX Full-Flow Check

Sample:

- `C:\Users\19379\Desktop\外卖骑手诗人的走红，标志着中国农民工文学的兴起\外卖骑手诗人的走红，标志着中国农民工文学的兴起.m4a`

Result:

- FasterWhisper ASR plus WhisperX CUDA alignment completed.
- WhisperX mapping: `source=2616`, `aligned=2616`, `matched=2616`, `zeroish=0`, alignment elapsed about `17s`.
- Stable subtitle output passed validation: `subtitle_count=303`, `translation_structure_errors=[]`, `render_blocked=false`.
- Final SRT timing audit: `overlap_count=0`, `gap_gt800=1`, `gap_gt1000=0`, `empty_chinese=0`.
- Podcast learning template video rendered successfully to the source audio folder.

## Latest WhisperX Time-Only Change

- Added `whisperx-time-only` backend.
- In transcript alignment, this mode still uses stable-ts word timestamps for stable cutting.
- After screen subtitle editing, it runs WhisperX against the final subtitle text and only updates `start_time`/`end_time`.
- The application rejects the time-only result if subtitle count, English text, or Chinese text changes.
- Regression coverage verifies that final text and translation are preserved while timing is retimed.

## Next Recommended Task

First, add a regression test for validation blocking consistency:

- if final validation summary is `ERROR`, stable outputs should preserve failure artifacts and block rendering;
- failed outputs should not silently write a renderable final ASS.

Then create fixture-based regression samples for the stable subtitle engine:

- long clause
- because/which/that clause
- short backchannel
- missing Chinese
- large blank gap
- overlong English
- old subtitle selection by synthesis

Then reduce `screen_editor.py` coupling only after fixture coverage exists.
