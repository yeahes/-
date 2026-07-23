# Testing

## Main Regression Entry

Run:

```powershell
runtime\python.exe scripts\run_regression.py
```

This runs:

- stable caption rule smoke tests
- Python syntax checks for core modified modules
- generated subtitle audit for known local samples when available

## Focused Tests

Stable caption rules:

```powershell
runtime\python.exe tests\test_stable_caption_rules.py
```

Generated output audit:

```powershell
runtime\python.exe tests\audit_stable_outputs.py 222 777 999
```

Syntax check:

```powershell
runtime\python.exe -m py_compile app\thread\subtitle_thread.py app\thread\video_synthesis_thread.py app\core\subtitle_processor\screen_editor.py
```

## Audit Interpretation

- `ERROR`: must be fixed before relying on the output.
- `WARNING`: inspect manually, but it may be acceptable.
- `PASS`: no known structural issue detected by the current audit.

The audit is not a replacement for watching the final video. It is a guard against known failures: missing Chinese, overlong English, long blank gaps, and very short subtitles.
