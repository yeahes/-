## 2026-08-14 Psychology Episode Failure Reduction

- Reproduced the `S0187.P01` Chinese-token split, `food of oak` / `food oak`,
  `Yuan Qingmai`, and `75元` defects from immutable production artifacts.
- Added failed-parent-only page retry with full-contract merge validation; no
  English, ID, word span, time, or page geometry may change.
- Bumped article ASR correction policy to v3 and added evidence-bound local
  term and adjacent-title person correction paths with negative regressions.
- Added article-backed currency-unit review and an editor-compatible fixed-ID
  Chinese suggestion. No automatic Chinese rewrite was introduced.
- Temporary real-artifact replay changed only three `fudaoke` spans and one
  person name through the new paths, and exposed `S0053` as a `75美元`
  suggestion. No paid request or production artifact write ran.
- Focused suites and `runtime\python.exe scripts\run_regression.py` pass; the
  complete 26-stage run took 408.1 seconds.
- Follow-up risk audit tightened the new behavior before handoff: structural
  page ID/cardinality failures now force a full-contract retry, while a local
  retry exception preserves initial accepted parents and exact failed-parent
  scope. Initial and retry diagnostics are retained together.
- Person correction now rejects generic shared mental-health descriptions;
  the positive titled-person and local-term cases plus three adversarial
  negatives pass all 41 article correction tests.
- Currency review now requires local money context, a unique value occurrence,
  and an atomic unit phrase. Count nouns, repeated values, and ambiguous
  compound units are excluded. Parent suggestions are rejected in child-page
  rows instead of silently applying to the first page.
- A read-only replay of the psychology episode preserved the expected four
  `fudaoke` surfaces, one `Yuan Chengmei`, and only the `S0053` currency review.
  No production artifacts or paid service were used. The final complete
  26-stage regression passed in 363.9 seconds; the subsequent retry-scope
  evidence and user-facing label pass their owning focused suites.

