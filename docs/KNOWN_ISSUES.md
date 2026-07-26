# Known Issues

Last updated: 2026-07-26

## Code Structure

- `app/core/subtitle_processor/screen_editor.py` is still highly coupled.
- Segmentation, translation allocation, validation, timing repair, and artifact writing share one large module.
- Do not perform broad refactors until fixture coverage is stronger.

## Validation

- Translation-structure errors are explicitly blocking.
- Other validation errors should be checked for blocking consistency before relying on automatic synthesis behavior.

## Local Samples

- `tests\audit_stable_outputs.py 222 777 999` depends on local `work-dir` outputs.
- In this checkout, those sample folders are absent, so the audit reports `MISSING`.
- Historical fixture samples exist under `tests\fixtures\caption_audit_2026_07_22`.

## Generated Outputs

- Existing outputs under `work-dir` may be stale.
- Do not judge a code change from old rendered videos or old SRT/ASS files.

## ASR and Timing

- Word-level timestamps are useful but not authoritative.
- Very short word timings and gaps can still produce display issues.

