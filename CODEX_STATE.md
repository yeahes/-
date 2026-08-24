# Project State

Status: active
Last verified: 2026-08-25 01:14:30 Asia/Shanghai
Branch: main
Verified HEAD: 305a96a
Working tree: modified (pre-existing audit artifacts plus the offline cross-parent measurement script)

## Current Goal
Improve stable subtitle review coverage without changing frozen English, IDs, timing, or production defaults without evidence.

## Confirmed Facts
- Two production fixes are committed: `3925520` run-bound review evidence and `5d22606` punctuation-safe Chinese fallback.
- Immutable `测试音频` run has 120 parents, 156 pages, 32 multipage parents, zero empty Chinese pages, and `render_blocked=false`.
- Manual-final history modifies 24 parents; the editor ledger hits 14 and misses 10: S0062/S0063/S0093/S0094/S0103/S0104/S0105/S0107/S0117/S0118.
- Proposed short-chain signal marks 26/120, hits 4/24 (16.7% recall), and false-marks 22; it is rejected for production.
- Cross-parent dependency experiment: conservative candidate marks 12/120 and hits 9/24; merged with the current ledger it reaches 22/24 but reads 40/120, above the current 29/120 baseline.
- Full regression: 31/32 checks passed. The only failure is the existing S9522 article page-start fixture (`into` expected, `in` selected).

## Approved Decisions
- Keep short-chain and backchannel work offline until a stronger, reproducible signal passes its own gate.
- Do not rerun or mutate manually reviewed audio results.

## Relevant Paths
- Measurement: `scripts/audit_short_chain_and_backchannel.py`
- Measurement: `scripts/audit_cross_parent_semantics.py`
- Current run: `work-dir/测试音频-当前代码/subtitle/stable-runs/20260824T201840.701773-2290bd40`
- Progress: `执行进展-给用户.md`
- Task log: `tasks/active/stable-subtitle-production-v1-log.md`

## Last Verification
- Measurement scripts: `py_compile` passed; the cross-parent read-only experiment reproduced 9/24 candidate hits and did not modify production artifacts.
- `runtime\\python.exe scripts\\run_regression.py`: 31/32; stable publication, page translation, boundaries, review evidence, manual-final, synthesis safety, and syntax checks passed.
- `git diff --check`: only existing line-ending warnings.

## Next Action
Keep the cross-parent signal offline and investigate the two missed parents without changing production defaults or translation prompts.

## Do Not Regress
- Preserve one authoritative word ledger, frozen English/IDs/timing, current page contracts, run identity isolation, and no writes to `D:\\软件缓存\\VideoCaptioner`.

## Unknowns
- Whether a boundary-aware signal can improve recall without making the review queue exceed the user's practical reading budget.
- Whether the existing S9522 fixture should be separately updated; it is unrelated to this measurement.
