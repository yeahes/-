## 2026-08-04 Baseline Contract Reconciliation

- Unified the standalone caption audit's Chinese CPS error boundary with the
  runtime and synthesis threshold at `12.25`; values from `9.0` through
  `12.25` remain review warnings.
- Added a regression for a `12.09` CPS cue to ensure the audit and runtime do
  not disagree at the discrete near-threshold boundary.
- Refreshed `CODEX_STATE.md` to the actual verified HEAD and recorded the next
  action and remaining unknowns. Marked the resolved cross-module allocation
  issue as a retained root-cause/regression record.
- Focused stable-caption tests, unified regression, and `git diff --check`
  passed after the reconciliation.

