# Testing

## Main Regression Entry

Run:

```powershell
runtime\python.exe scripts\run_regression.py
```

This runs:

- stable caption rule smoke tests
- rule regression library cases
- golden subtitle evaluation contract
- Python syntax checks for core modified modules
- generated subtitle audit for known local samples when available

## Focused Tests

Rule regression library:

```powershell
runtime\python.exe tests\test_rule_regression_library.py
```

Add representative cases to:

```text
tests\fixtures\rule_regression_cases.json
```

Use this fixture for repeated, generic failure patterns from run reviews. Do not
add sample-specific text patches here unless the same failure class is expected
to recur across unrelated audio.

Stable caption rules:

```powershell
runtime\python.exe tests\test_stable_caption_rules.py
```

Durable run state and progress/resume contract:

```powershell
runtime\python.exe tests\test_stable_run_state.py
```

Generated output audit:

```powershell
runtime\python.exe tests\audit_stable_outputs.py <work-dir sample>
```

This command audits an explicitly named `work-dir\<sample>\subtitle` output.
Use a newly generated sample when judging current code; it is deliberately not
run by `scripts\run_regression.py`.

Fixture audit:

```powershell
runtime\python.exe -m tests.caption_audit.run_all
```

Golden evaluation:

```powershell
runtime\python.exe scripts\evaluate_golden_subtitles.py --reference <golden-reference.json> --run <artifact-dir>
```

This is an offline comparison against manually curated English, entity,
boundary, timing, and Chinese fact references. See `docs\GOLDEN_EVALUATION.md`.

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
