# Task: Stabilize Production Subtitle Flow

## Background

The project accumulated many local fixes while optimizing English-learning bilingual subtitles. Some fixes improved individual samples but made the overall flow harder to reason about.

## Goal

Make stable mode the predictable production path:

```text
word timestamps
-> local English segmentation
-> fixed English subtitle IDs
-> LLM Chinese translation/allocation
-> validation
-> stable final SRT/ASS outputs
-> synthesis from manifest
```

## Required Behavior

1. Stable mode must not run LLM English segmentation before local cutting.
2. Stable mode must not run candidate quality check.
3. Spoken backchannels must not be deleted by default.
4. Final SRT/ASS and video synthesis must use the same stable subtitle data.
5. `stable-final-manifest.json` must point synthesis to the correct final SRT.
6. Regression entry must be a single command.

## Relevant Files

- `app/thread/subtitle_thread.py`
- `app/thread/video_synthesis_thread.py`
- `app/core/subtitle_processor/screen_editor.py`
- `tests/test_stable_caption_rules.py`
- `tests/audit_stable_outputs.py`
- `scripts/run_regression.py`

## Out Of Scope

- Replacing ASR models.
- Full refactor of `screen_editor.py`.
- Visual redesign of the podcast template.
- New LLM provider integration.

## Done When

- `runtime\python.exe scripts\run_regression.py` completes.
- Stable manifest subtitle resolution is tested.
- Docs reflect current behavior.
- Known stale-output risk is documented.
