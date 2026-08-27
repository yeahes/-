## 2026-08-07 Article-Correction Ownership and Full Review Queue

- The real v10 article-correction log showed `.S., Japan, -> Japan,` applied
  even though its entity gate failed with
  `candidate_would_delete_non_entity_token`. The fuzzy two-source-token collapse
  considered the whole window similar to `Japan` without proving that `S.`
  contributed to the canonical entity.
- Collapsed entity matching now requires character contribution from every
  source token. A lossless split form such as `A Drift -> Adrift` is promoted
  through the entity gate, while a failed gate cannot be overridden later.
- The playable QA queue no longer truncates `REVIEW` entries after the first
  12. It still excludes `INFO`, deduplicates identical code/ID findings, and
  preserves severity ordering from the QA summary.
- Direct article-correction tests pass 25/25, the QA queue script passes, and
  the saved v10 `.S., Japan,` candidate now returns
  `candidate_would_delete_non_entity_token` with `should_apply=False`.
- A read-only rebuild of the v10 QA data returns 0 blockers, 51 reviews, 12
  info items, and 51 default queue entries with zero omitted. The old queue's
  12 visible / 22 omitted metadata was not overwritten.
- Unified regression completed in 218.6 seconds with no failed suite;
  `git diff --check` exited 0 with only repository line-ending notices.
- This change does not alter English segmentation or word budgets, Chinese
  allocation, display pagination, timing, or rendering.

