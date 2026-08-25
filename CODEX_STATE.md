# Project State

Status: active
Last verified: 2026-08-25 07:40:18 Asia/Shanghai
Branch: main
Verified HEAD: 25bbf33
Working tree: modified (save-fix source/tests plus pre-existing audit artifacts)

## Current Goal
Allow the Japanese X-Generation manual final draft to save and synthesize without re-running audio or translation.

## Confirmed Facts
- Manual-final save fix: orphaned pre-merge display plans are skipped only when append-only history proves the parent was removed and no current edit references it; manual boundary overrides discard stale blueprint-geometry errors but retain real translation errors.
- Focused verification passed: `tests/test_manual_final_subtitle_editor.py` 132/132 and `tests/test_stable_publication.py` 101/101.
- The newly started full regression was stopped at the user's request; its output showed the existing Windows `app.log` rollover `PermissionError` noise.
- Two production fixes are committed: `3925520` run-bound review evidence and `5d22606` punctuation-safe Chinese fallback.
- Immutable `测试音频` run has 120 parents, 156 pages, 32 multipage parents, zero empty Chinese pages, and `render_blocked=false`.
- Manual-final history modifies 24 parents; the editor ledger hits 14 and misses 10: S0062/S0063/S0093/S0094/S0103/S0104/S0105/S0107/S0117/S0118.
- Proposed short-chain signal marks 26/120, hits 4/24 (16.7% recall), and false-marks 22; it is rejected for production.
- Cross-parent dependency experiment: conservative candidate marks 12/120 and hits 9/24; merged with the current ledger it reaches 22/24 but reads 40/120, above the current 29/120 baseline.
- Full regression: 31/32 checks passed. The only failure is the known article display-readability experiment fixture (`test_three_line_fallback_promotes_complete_two_page_alternative`); it is unrelated to retry context preservation.
- Failed stable checkpoints now retain a visible `重试` entry in the editor, including after reopening through “恢复最近字幕”; ordinary manual-final packages remain read-only with respect to processing.
- Retry now restores the original run's article source/context and feature flags, so verified semantic translation cache entries remain eligible after reopening a blocked checkpoint. It does not relax cache identity or mix review queues.
- The latest observed retry was executed by the editor process started before the retry fix was loaded: it reached full translation and stopped at 6/29 batches after repeated provider HTTP 500 errors, with article-assist flags false and cache hits 0. No new stable checkpoint was published.

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
- `runtime\\python.exe scripts\\run_regression.py`: 31/32; stable publication, page translation, boundaries, review evidence, manual-final, synthesis safety, and syntax checks passed. The known article display-readability experiment fixture remains the only failure.
- `runtime\\python.exe -X utf8 tests\\test_stable_publication.py`: 101/101 passed after retry context preservation coverage was added.
- `git diff --check`: only existing line-ending warnings.

## Next Action
Restart the editor from the current working copy, reopen the blocked Japanese X-generation checkpoint through “恢复最近字幕”, and retry saving the existing manual edits; no audio or translation rerun is required.

## Do Not Regress
- Preserve one authoritative word ledger, frozen English/IDs/timing, current page contracts, run identity isolation, and no writes to `D:\\软件缓存\\VideoCaptioner`.

## Unknowns
- GUI save/synthesis still needs one user-side confirmation after restart; full regression was intentionally left to the user.
- Whether a boundary-aware signal can improve recall without making the review queue exceed the user's practical reading budget.
- Whether the existing S9522 fixture should be separately updated; it is unrelated to this measurement.
