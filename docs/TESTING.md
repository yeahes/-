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

This command audits existing `work-dir\<sample>\subtitle` outputs. If those local
outputs are absent, the sample status is `MISSING`; that is an environment/sample
availability result, not a code failure.

Fixture audit:

```powershell
runtime\python.exe -m tests.caption_audit.run_all
```

By default this checks fixture-backed samples `000`, `222`, and `888` when the
fixture files are available.

Syntax check:

```powershell
runtime\python.exe -m py_compile app\thread\subtitle_thread.py app\thread\video_synthesis_thread.py app\core\subtitle_processor\screen_editor.py
```

## Audit Interpretation

- `ERROR`: must be fixed before relying on the output.
- `WARNING`: inspect manually, but it may be acceptable.
- `MISSING`: the requested local sample was not found.
- `PASS`: no known structural issue detected by the current audit.

The audit is not a replacement for watching the final video. It is a guard against known failures: missing Chinese, overlong English, long blank gaps, and very short subtitles.
