# Project State
Status: active
Last verified: 2026-08-04 21:18:46 Asia/Shanghai
Branch: codex/e2e-caption-regression
Verified HEAD: 036080ec82cc41a4c47fa74a8721276d1bd6b7ba
Working tree: modified; phase-one boundary ownership change is verified.

## Current Goal
Implement the approved four-stage subtitle-boundary, cache, and renderer correction as separate commits.

## Confirmed Facts
- Formal stable English boundaries no longer invoke the visual word/character budget.
- A regression injects a failing visual-budget method and proves the formal finalizer cannot call it.
- The existing renderer pagination remains a presentation-only projection and was not changed.

## Approved Decisions
- Formal English boundaries are owned only by deterministic language and timing stages before fixed IDs.
- The 12-word/68-character visual target is renderer-only; it may never create a cue, subtitle ID, or Chinese allocation boundary.

## Relevant Paths
- `app/core/subtitle_processor/stable_english_boundaries.py`
- `app/core/subtitle_processor/screen_editor.py`
- `tests/test_stable_boundary_finalization.py`
- `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\visual-pagination-validation\validation-report.md`

## Last Verification
- `runtime\python.exe -X utf8 tests\test_stable_boundary_finalization.py`: PASS.
- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS.
- `git diff --check`: PASS.

## Next Action
Add the whole-file English boundary scanner with hard/review/allow evidence grades.

## Do Not Regress
- Keep fixed English text, word ranges, subtitle IDs, Chinese allocation, SRT/ASS timing, and manifest resolution unchanged by rendering.
- Do not treat a cue beginning with a subordinator, preposition, or finite verb as automatically invalid.

## Unknowns
- The full-file boundary scan, cache fingerprint migration, and word-timed renderer pagination remain unimplemented.
