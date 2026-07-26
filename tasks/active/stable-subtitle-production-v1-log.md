# Progress Log

## Current Objective

Stabilize the production subtitle path and make the project recoverable for future Codex sessions.

## Completed

- Added root `AGENTS.md`.
- Added project docs under `docs/`.
- Added active task file.
- Added this task log.
- Existing tests already cover stable segmentation and output audit basics.
- Added `scripts/run_regression.py`.
- Verified the unified regression command exits successfully.
- Current known local samples audit as WARNING only, with no ERROR.

## Latest Test Results

Command:

```powershell
runtime\python.exe scripts\run_regression.py
```

Result:

- stable caption smoke tests: pass
- syntax check: pass
- known output audit: completed
- 2026-07-26 recheck: stable caption smoke tests pass; syntax check passes.
- 2026-07-26 recheck: local samples `222`, `777`, and `999` are currently `MISSING` in `work-dir`, so their current quality is not verified by `tests\audit_stable_outputs.py`.

## Current Decisions

- Stable mode should skip old LLM segmentation.
- Stable mode should skip candidate quality check.
- Backchannels should be preserved by default.
- Synthesis should resolve subtitles through `stable-final-manifest.json`.

## Current Risk

- Existing `work-dir` outputs may be stale after code changes.
- `screen_editor.py` remains too coupled for large changes without fixture tests.
- Local sample availability is not stable; prefer fixture-backed tests for repeatable validation.

## Next Action

First make validation blocking consistent for every final `ERROR` status, then add fixture-based tests so future changes do not rely on existing `work-dir` samples only.

## Files Changed

- `AGENTS.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/ARCHITECTURE.md`
- `docs/PIPELINE.md`
- `docs/SUBTITLE_RULES.md`
- `docs/DECISIONS.md`
- `docs/CURRENT_STATE.md`
- `docs/TESTING.md`
- `tasks/active/stable-subtitle-production-v1.md`
- `tasks/active/stable-subtitle-production-v1-log.md`
- `scripts/run_regression.py`
