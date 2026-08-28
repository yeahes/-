# Test Baseline

Last updated: 2026-07-26

## Commands

```powershell
runtime\python.exe scripts\run_regression.py
runtime\python.exe tests\test_stable_caption_rules.py
runtime\python.exe -m py_compile app\thread\subtitle_thread.py app\thread\video_synthesis_thread.py app\core\subtitle_processor\screen_editor.py
```

## Observed On 2026-07-26

- `scripts\run_regression.py`: pass.
- `tests\test_stable_caption_rules.py`: pass.
- `py_compile`: pass.
- Generated-output auditing requires an explicit fresh `work-dir` sample and is
  intentionally excluded from this baseline.

## Interpretation

- Run `tests\audit_stable_outputs.py <work-dir sample>` only against a fresh
  output. It does not replace a visual quality review of the rendered video.
