# Current Status

Last updated: 2026-07-26

## Working

- Stable mode performs local English cutting from word-level timestamps.
- Chinese allocation is ID-driven through global subtitle IDs such as `S0001`.
- The podcast learning video path resolves subtitles from `stable-final-manifest.json`.
- Regression command:

```powershell
runtime\python.exe scripts\run_regression.py
```

Current observed result on 2026-07-26:

- stable caption smoke tests: passed
- syntax check: passed
- `tests\audit_stable_outputs.py 222 777 999`: exits successfully, but all three local samples are `MISSING` in this checkout

## Not Yet Proven

- Current long-audio behavior on fresh outputs after the latest ID-driven allocation changes.
- Whether every validation `ERROR` class blocks renderable ASS output, not only translation-structure errors.
- Whether existing `work-dir` outputs are fresh enough to judge current code.

