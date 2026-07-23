# Current State

Last updated: 2026-07-23

## Working

- E-drive working copy is the active project.
- Stable mode uses local English segmentation from word-level timestamps.
- LLM translation is limited to Chinese generation/allocation.
- Podcast template can resolve subtitles from `stable-final-manifest.json`.
- Regression smoke tests exist in `tests/test_stable_caption_rules.py`.
- Generated subtitle audits exist in `tests/audit_stable_outputs.py`.
- A single regression entry exists: `runtime\python.exe scripts\run_regression.py`.
- Current known local samples `222`, `777`, and `999` audit as `WARNING`, not `ERROR`.

## In Progress

- Reducing coupling in `screen_editor.py`.
- Making final SRT/ASS output and video synthesis use the same stable subtitle.
- Converting discussion-derived rules into tests and docs.

## Known Issues

- `screen_editor.py` remains highly coupled.
- Current tests are smoke/regression tests, not full fixture coverage.
- Existing generated outputs under `work-dir` may be stale unless regenerated after code changes.
- Some ASR/stable-ts word timings can be too short or contain gaps.
- Chinese translation quality still depends on LLM output and prompt stability.

## Current Production Recommendation

Use:

- Stable mode on.
- stable-ts/time alignment on when available.
- Candidate quality check off.
- Preserve backchannels.
- Use `stable-final-manifest.json` for podcast template synthesis.
- After code changes, regenerate subtitle outputs before judging a newly rendered video.

Avoid:

- LLM-based English segmentation in production stable flow.
- Broad edits to `screen_editor.py` without tests.
- Judging fixes from old rendered videos or stale subtitle files.

## Next Recommended Task

Create fixture-based regression samples for the stable subtitle engine:

- long clause
- because/which/that clause
- short backchannel
- missing Chinese
- large blank gap
- overlong English
- old subtitle selection by synthesis

Then reduce `screen_editor.py` coupling only after fixture coverage exists.
