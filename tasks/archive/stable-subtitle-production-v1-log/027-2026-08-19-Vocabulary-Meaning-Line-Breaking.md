## 2026-08-19 Vocabulary Meaning Line Breaking

- Added an article-card-only Chinese meaning wrapper over the shared
  deterministic token boundary owner. It preserves complete lexical units,
  rejects attached particles at line edges, and prefers a slightly longer but
  visually balanced second line.
- Replaced the generic two-line `[:2]` fallback with a fail-closed meaning
  fitter. A meaning that cannot fit at the 24px floor reports overflow instead
  of silently discarding content.
- Focused balance, lexical-boundary, no-truncation, card-content, compile, and
  extreme-render checks pass.

