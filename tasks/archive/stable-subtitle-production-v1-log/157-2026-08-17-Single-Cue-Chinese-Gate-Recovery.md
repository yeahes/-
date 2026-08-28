## 2026-08-17 Single-Cue Chinese Gate Recovery

- Reproduced the 84% stable-artifact failure from the immutable run state and
  cached LLM responses for `肠道菌群，能人为操控吗？`.
- Identified `G0163 / S0194`: a valid `...不等于...` translation of
  `Just because ... does not mean ...` was falsely labelled `semantic_loss`.
- Added general negative-entailment recognition and preserved any non-empty
  one-cue authoritative translation when a heuristic quality finding remains;
  unresolved evidence stays reviewable instead of becoming missing Chinese.
- Read-only cache replay covers 180 groups and 217 fixed IDs with zero empty
  allocation. Focused regressions, the stable-caption suite, the complete
  regression command, and diff checks pass.

