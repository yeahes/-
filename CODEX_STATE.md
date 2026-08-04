# Project State
Status: in_progress
Last verified: 2026-08-04 23:43:20 Asia/Shanghai
Branch: codex/e2e-caption-regression
Verified HEAD: b1324b4
Working tree: modified: renderer regression tests, documentation, task log, and state record

## Current Goal
Finish the renderer static-layout correction, verify its representative frames, then commit it on this branch.

## Confirmed Facts
- Formal stable English boundaries no longer invoke the visual word/character budget.
- A regression injects a failing visual-budget method and proves the formal finalizer cannot call it.
- The whole-file audit classifies every final English boundary as hard, review, or allow with word-ledger, pause, terminal, and speaker evidence.
- A residual hard boundary is an export blocker; a review boundary remains an ID-addressable human-review item.
- Fixed-ID Chinese allocation cache entries include the frozen English, span, prompt, and allocation fingerprints.
- Article rendering verifies the stable manifest, final cue timeline, and word ledger before ffmpeg. It first uses one static fixed-font page with up to two lines, then paginates only at safe word gaps when static layout fails.
- The 215-cue offline replay now produces valid page plans for every cue, including the former `S0188`, `S0202`, `S0208`, and `S0110` structural-overflow cases.

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
- `E:\VideoCaptioner-e2e-runs\renderer-word-timeline-validation\preflight-short-cues.md`

## Last Verification
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`: PASS.
- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS.
- `git diff --check`: PASS.

## Next Action
Review the delegated visual report, then commit the renderer and documentation changes. Do not synthesize a full video.

## Do Not Regress
- Keep fixed English text, word ranges, subtitle IDs, Chinese allocation, SRT/ASS timing, and manifest resolution unchanged by rendering.
- Do not treat a cue beginning with a subordinator, preposition, or finite verb as automatically invalid.

## Unknowns
- A fresh production ASR and full-video synthesis run remains intentionally unperformed; the validated scope is frozen-artifact replay and representative-frame rendering.
