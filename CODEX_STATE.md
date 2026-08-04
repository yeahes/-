# Project State
Status: active
Last verified: 2026-08-04 21:33:55 Asia/Shanghai
Branch: codex/e2e-caption-regression
Verified HEAD: b2b02379225118e34e0fbb140608bbb2b6f8f827
Working tree: modified; phase-two boundary audit and gate are verified.

## Current Goal
Implement the approved four-stage subtitle-boundary, cache, and renderer correction as separate commits.

## Confirmed Facts
- Formal stable English boundaries no longer invoke the visual word/character budget.
- A regression injects a failing visual-budget method and proves the formal finalizer cannot call it.
- The whole-file audit classifies every final English boundary as hard, review, or allow with word-ledger, pause, terminal, and speaker evidence.
- A residual hard boundary is an export blocker; a review boundary remains an ID-addressable human-review item.

## Approved Decisions
- Formal English boundaries are owned only by deterministic language and timing stages before fixed IDs.
- The 12-word/68-character visual target is renderer-only; it may never create a cue, subtitle ID, or Chinese allocation boundary.
- A preposition, subordinator, or finite verb at a cue start is not an error without atomic structure evidence and no contrary timing/speaker evidence.

## Relevant Paths
- `app/core/subtitle_processor/stable_english_boundaries.py`
- `app/core/subtitle_processor/screen_editor.py`
- `tests/test_stable_boundary_finalization.py`
- `tests/fixtures/stable_boundaries/boundary_audit_contract.json`
- `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\visual-pagination-validation\validation-report.md`

## Last Verification
- `runtime\python.exe -X utf8 tests\test_english_boundary_rules.py`: PASS.
- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS.
- `git diff --check`: PASS.

## Next Action
Add boundary/input/version fingerprints to fixed-ID Chinese allocation caches.

## Do Not Regress
- Keep fixed English text, word ranges, subtitle IDs, Chinese allocation, SRT/ASS timing, and manifest resolution unchanged by rendering.
- Do not treat a cue beginning with a subordinator, preposition, or finite verb as automatically invalid.

## Unknowns
- The cache fingerprint migration and word-timed renderer pagination remain unimplemented.
