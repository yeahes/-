## 2026-08-20 Three-Stage Reliability And Golden V2

- Stage 1 added per-unit translation/allocation checkpoints, minimal cache
  invalidation, duplicate-cache migration, and resumable run state. A changed
  semantic group no longer invalidates every verified group.
- Stage 2 made application code the single retry owner, bounded external
  concurrency at two, recorded request attempts/usage, and enforced request
  budgets and explicit failure instead of unbounded paid retries.
- Stage 3 added schema-v2 Golden evaluation with four weighted components,
  90% overall and 85% per-component thresholds, plus timeline, ID, word-ledger,
  parent-Chinese, and display-page hard contracts. Modern and legacy artifact
  evidence are distinguished explicitly.
- Curated Dreamcore and animation references are loaded by offline regression.
  Dreamcore passes at 95.36%. The old animation output remains at 90.84% with
  only the English component below threshold because of
  `specifically | because`.
- A parser-owned clause-scope rule fixes that boundary generically. Full-ledger
  replay covers all 1,836 animation words and yields
  `... box office | specifically because ...` without changing text, order,
  timing, Chinese, or any production artifact.
- No paid API was called during stage 3. Focused Golden/parser tests, the
  20-check pipeline regression, and the final 29-check full regression pass.
  The full run completed in 867.38 seconds.

