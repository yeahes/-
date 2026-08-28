## 2026-08-25 Short-Chain And Backchannel Offline Measurement

- Added `scripts/audit_short_chain_and_backchannel.py`. The script reads one
  immutable stable run plus its manual-final history and emits measurements
  without changing any run artifact or production detector.
- The current test audio has 24 manually modified parents. The bound editor
  ledger hits 14 and misses `S0062`, `S0063`, `S0093`, `S0094`, `S0103`,
  `S0104`, `S0105`, `S0107`, `S0117`, and `S0118`.
- The proposed `<3.5s + boundary-word` signal marks 26/120 parents, hits only
  4/24 (16.7% recall), and adds 22 false parent reviews. It is rejected for
  production; the missed groups show that this is not the owning invariant.
- Of 13 modified parents containing a spoken marker, three manual finals add
  marker evidence absent from automatic Chinese and one removes it. This is a
  prompt hypothesis, not a provider A/B result, so no translation prompt was
  changed.

