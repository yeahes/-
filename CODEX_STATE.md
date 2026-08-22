# Project State
Status: active
Last verified: 2026-08-22 20:31:05 Asia/Shanghai
Branch: main
Verified HEAD: 04a8000 (tested subtitle-pipeline baseline)
Working tree: only local generated output remains untracked after state commit

## Current Goal
Run a read-only offline comparison to test whether pre-ID pagination feasibility improves English segmentation without regressing passing cases.

## Confirmed Facts
- Baseline commit `04a8000` contains the accumulated subtitle pipeline, editor, audit, recovery, documentation, and regression changes.
- A pre-commit core run initially found one deterministic equal-risk page-selection failure; the two selector layers now preserve verified pause-backed restart evidence ahead of purely visual tie-breakers.
- Focused regression after the repair passes 699 tests with zero failures; syntax compilation and `git diff --check` pass.
- Current pre-ID display safety checks syntax and fragment completeness but does not run the authoritative pixel/timing page planner.
- White House is a passing counterexample; Chocolate `S0026/S0160`, Employment `S0223/S0247`, and Japanese `S0136` represent distinct geometry and page-Chinese failure classes and must not be combined into one score.

## Approved Decisions
- Do not change production segmentation or pagination until a read-only experiment demonstrates net benefit.
- English, IDs, word ledger, order, and timing remain local and deterministic; external models remain translation or read-only audit tools.

## Relevant Paths
- Baseline evidence: `docs/handoffs/2026-08-22-independent-diagnostic-brief.md`
- Process context: `docs/handoffs/2026-08-22-subtitle-segmentation-translation-pagination-context.md`
- Owners: `app/core/subtitle_processor/screen_editor.py`, `app/core/utils/podcast_learning_video.py`

## Last Verification
- `pytest` affected core suites: 699 passed, 2 warnings, 0 failed in 908.77s.
- Focused equal-risk ordering regression: 1 passed; production syntax and cached diff checks pass.

## Next Action
Build and run a read-only targeted comparison on known failures plus White House counterexamples, reporting improvements and regressions with explicit denominators.

## Do Not Regress
- Do not modify `D:/软件缓存/VideoCaptioner`, existing work-dir artifacts, manual finals, or frozen English/ID/timing contracts.

## Unknowns
- No current evidence proves pre-ID page feasibility has positive net benefit on unseen audio.
