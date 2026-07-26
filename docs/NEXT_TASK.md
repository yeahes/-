# Next Task

Last updated: 2026-07-26

## Objective

Make validation blocking consistent before changing subtitle quality rules.

## Minimal Implementation Plan

1. Add or adjust tests so any final validation summary with `status == "ERROR"` blocks renderable ASS output.
2. Preserve diagnostic artifacts on failure:
   - stable SRT files
   - coverage report
   - manifest
   - allocation artifacts
3. Confirm successful validation still writes the normal stable final outputs.
4. Run:

```powershell
runtime\python.exe scripts\run_regression.py
```

## Out Of Scope

- No English cutting rule changes.
- No ASR changes.
- No prompt rewrite.
- No broad `screen_editor.py` refactor.
- No sample-specific fixes.

