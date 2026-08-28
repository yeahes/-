# Three-Stage Reliability Handoff

Status: implementation and offline verification complete on 2026-08-20.

## Delivered

- Stage 1: semantic-unit checkpoints, minimal cache invalidation, duplicate-cache migration, and resumable run state.
- Stage 2: bounded two-request concurrency, application-owned retries, request ledger/budget, and explicit failure behavior.
- Stage 3: Golden v2 quality evaluation with four scored components, frozen-data hard contracts, modern/legacy evidence handling, and two curated real-sample references.
- General English fix: keep a clause-scoping modifier with its following subordinator, producing `... box office | specifically because ...` on the real animation ledger.

## Evidence

- Dreamcore historical package: 95.36%, PASS.
- Animation historical package: 90.84% overall; old English component 75% due to the pre-fix boundary. Other hard contracts pass.
- Current animation-ledger replay: 1,836/1,836 words preserved in order and the target boundary corrected.
- `runtime\python.exe scripts\run_regression.py --profile fast --fail-fast`: 8/8 PASS in 6.50s.
- `runtime\python.exe scripts\run_regression.py --profile pipeline`: 20/20 PASS in 919.52s.
- `runtime\python.exe scripts\run_regression.py --profile full`: 29/29 PASS in 867.38s.
- `git diff --check`: PASS.

## Next Validation

Restart the application and run one unseen audio from the beginning. Measure first-run duration, provider request/usage summary, cache behavior, English boundaries, parent Chinese, fixed-ID allocation, and actual pages. This real run is validation evidence, not a prerequisite for the completed offline implementation.
