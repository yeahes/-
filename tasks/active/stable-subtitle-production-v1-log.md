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
- 222: WARNING, no gap errors, no overlong English, no missing Chinese
- 777: WARNING, no gap errors, no overlong English, no missing Chinese
- 999: WARNING, one 1400 ms gap warning, no gap errors, no overlong English, no missing Chinese

## Current Decisions

- Stable mode should skip old LLM segmentation.
- Stable mode should skip candidate quality check.
- Backchannels should be preserved by default.
- Synthesis should resolve subtitles through `stable-final-manifest.json`.

## Current Risk

- Existing `work-dir` outputs may be stale after code changes.
- `screen_editor.py` remains too coupled for large changes without fixture tests.

## Next Action

Add fixture-based tests so future changes do not rely on existing `work-dir` samples only.

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
