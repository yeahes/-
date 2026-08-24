# Project State

Status: active
Last verified: 2026-08-25 00:31:04 Asia/Shanghai
Branch: main
Verified HEAD: 5d22606
Working tree: modified (pre-existing audit artifacts plus this read-only measurement)

## Current Goal
Improve stable subtitle review coverage without changing frozen English, IDs, timing, or production defaults without evidence.

## Confirmed Facts
- Two production fixes are committed: `3925520` run-bound review evidence and `5d22606` punctuation-safe Chinese fallback.
- Immutable `测试音频` run has 120 parents, 156 pages, 32 multipage parents, zero empty Chinese pages, and `render_blocked=false`.
- Manual-final history modifies 24 parents; the editor ledger hits 14 and misses 10: S0062/S0063/S0093/S0094/S0103/S0104/S0105/S0107/S0117/S0118.
- Proposed short-chain signal marks 26/120, hits 4/24 (16.7% recall), and false-marks 22; it is rejected for production.
- Full regression: 31/32 checks passed. The only failure is the existing S9522 article page-start fixture (`into` expected, `in` selected).

## Approved Decisions
- Keep short-chain and backchannel work offline until a stronger, reproducible signal passes its own gate.
- Do not rerun or mutate manually reviewed audio results.

## Relevant Paths
- Measurement: `scripts/audit_short_chain_and_backchannel.py`
- Current run: `work-dir/测试音频-当前代码/subtitle/stable-runs/20260824T201840.701773-2290bd40`
- Progress: `执行进展-给用户.md`
- Task log: `tasks/active/stable-subtitle-production-v1-log.md`

## Last Verification
- Measurement script: `py_compile` passed; read-only output reproduced C1 numbers.
- `runtime\\python.exe scripts\\run_regression.py`: 31/32; stable publication, page translation, boundaries, review evidence, manual-final, synthesis safety, and syntax checks passed.
- `git diff --check`: only existing line-ending warnings.

## Next Action
Design a boundary-aware offline signal from the ten missed IDs; do not wire the rejected lexical signal or change translation prompts.

## Do Not Regress
- Preserve one authoritative word ledger, frozen English/IDs/timing, current page contracts, run identity isolation, and no writes to `D:\\软件缓存\\VideoCaptioner`.

## Unknowns
- Whether a boundary-aware signal can improve recall without making the review queue exceed the user's practical reading budget.
- Whether the existing S9522 fixture should be separately updated; it is unrelated to this measurement.
