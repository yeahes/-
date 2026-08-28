## 2026-08-14 Article ASR False-Rewrite And Review Projection

- Replayed the raw ASR plus article context for `石油市场，现在中国说了算？`
  and `蜜雪冰城为何卖起了啤酒` in temporary directories. Existing policy
  reproduced `Red Sea -> Russia` and three `network(s) -> New York`
  replacements.
- Added root-layer entity-shape and exact-article-surface invariants. Ordinary
  lowercase words cannot weakly expand into multiword entities, unrelated
  capitalized multiword entities cannot collapse through phonetic similarity,
  and an evidenced article entity cannot be overwritten by another glossary
  owner.
- Bumped the article ASR policy to v4 so run-state resume cannot reuse affected
  v3 corrected ASR. Raw ASR and article-analysis caches remain reusable.
- Added a high-signal review projection for below-threshold entity-shaped
  candidates. It chooses one minimal-token-change suggestion per source range,
  maps it to real frozen subtitle IDs by time overlap, records source and word
  ledger hashes, and never changes English automatically. The editor ignores
  stale-ledger review artifacts.
- Real replay now rejects all four false replacements while retaining normal
  automatic corrections and `Felugia/Fallugia -> Fulujia` review evidence.
  Focused article/thread correction tests pass 48/48; focused review-mark and
  syntax tests pass; the complete 26-stage regression exits zero in 352.6 seconds.
- No production output was modified and no ASR, LLM, translation, synthesis,
  paid request, or network-dependent operation ran.

