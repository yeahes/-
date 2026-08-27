## 2026-08-03 Article Entity Alias Collision Guard

- A local candidate gate now rejects a high-score short alias when the same
  original ASR word range contains a conflicting discriminator token from a
  different article-supported canonical entity.
- Rejected candidates remain review-only and record the target canonical,
  conflicting canonical(s), alias evidence, word range, and discriminator in
  `correction_log.json`. The correction path does not modify English cutting,
  timing, IDs, Chinese allocation, or export.

