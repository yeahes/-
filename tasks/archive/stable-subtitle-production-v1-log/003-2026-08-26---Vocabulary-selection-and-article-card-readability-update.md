## 2026-08-26 - Vocabulary selection and article-card readability update

- Production vocabulary prompt version is now `17`; concept cards may retain
  their detailed explanation for up to six scheduled cards per episode instead
  of silently downgrading after the first three.
- Selection guidance now rejects transparent topic compounds and prefers
  non-transparent idioms, metaphors, irony, and low-frequency phrasal verbs.
  Subtitle-surface matching remains authoritative, so the prompt does not
  rewrite frozen English into dictionary lemmas.
- Normalization records invalid payloads, missing cues/meanings, phrase misses,
  length and common-word rejections in the vocabulary cache diagnostics.
- Article vocabulary details prefer semantic/punctuation boundaries and reject
  very short Chinese tail lines. The card now shares the opening title card's
  blue left vertical accent. Focused vocabulary checks pass 18/18; the 1920x1080
  sample is `output/current-production-vocab-render-20260826/current-optimized-production-vocab-card.png`.

