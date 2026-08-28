## 2026-08-04 Fixed-ID Allocation Audit And Imperative Boundary Integration

- Allocation attempts that violate fixed-ID structure before a successful
  retry now remain auditable as `retry_required` evidence without becoming
  final render-blocking structure errors. Regression covers a missing ID
  followed by an ID-correct retry and verifies frozen English fields remain
  unchanged.
- The conservative visual pre-ID gate can now recognize a complete terminal
  imperative as a display unit. It preserves all existing pause, duration,
  continuity, grammar, and write-gate requirements; an infinitive beginning
  with `To` remains unsplittable by this rule.
- Both feature branches were reviewed and merged to main. The unified
  regression and `git diff --check` passed; unseen-audio production and
  article-template visual validation remain the next verification step.
