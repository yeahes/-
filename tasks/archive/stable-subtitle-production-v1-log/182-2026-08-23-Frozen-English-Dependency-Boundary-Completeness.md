## 2026-08-23 Frozen English Dependency Boundary Completeness

- Reproduced six legal-but-invalid formal boundaries in the newest White House
  checkpoint. The defects covered attached clause entrances, a separable
  particle/preposition predicate, a leading subjectless passive predicate,
  and a compound noun hidden after spaCy split `cannot` into `can + not`.
- Replaced substring/cursor token alignment with exact character-interval
  overlap against the immutable ledger surfaces. Added general dependency
  guards and negative coverage for sentence restarts, passive questions,
  inverted conditions, non-finite introductions, purpose restarts, and
  punctuated time adjuncts.
- Full current-code replay preserves 2,586/2,586 ordered words and removes all
  6/6 target boundaries. A page-level replay initially exposed an incompatible
  new issue code; reusing the established cross-stage dependency-entrance code
  restores the historical 56px three-page plan without weakening formal cue
  cutting.
- Boundary-focused verification passes 105/105. The complete
  `tests/test_stable_caption_rules.py` suite passes 538/538 in 157.81 seconds.
  Production artifacts, API caches, audio, and `output/` were not modified.

