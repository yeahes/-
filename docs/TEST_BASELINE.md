# Test Baseline

Last updated: 2026-07-26

## Commands

```powershell
runtime\python.exe scripts\run_regression.py
runtime\python.exe tests\test_stable_caption_rules.py
runtime\python.exe tests\audit_stable_outputs.py 222 777 999
runtime\python.exe -m py_compile app\thread\subtitle_thread.py app\thread\video_synthesis_thread.py app\core\subtitle_processor\screen_editor.py
```

## Observed On 2026-07-26

- `scripts\run_regression.py`: pass.
- `tests\test_stable_caption_rules.py`: pass.
- `py_compile`: pass.
- `tests\audit_stable_outputs.py 222 777 999`: pass with all requested samples reported as `MISSING`.

## Interpretation

- `MISSING` means the local `work-dir` sample output is unavailable.
- It does not prove subtitle quality for that sample.
- Fresh subtitle outputs should be regenerated before judging video quality.

