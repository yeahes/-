## 2026-08-24 - Structural arm F scope correction

- Kept the shared open-prefix and finite-predicate helpers at their shipped
  contracts, including the finite helper's classmethod shape required by the
  read-only external measurement scripts.
- Isolated the finite-predicate-plus-comma exemption in a private structural
  boundary predicate used only before subtitle IDs freeze. It caches by joined
  token text and falls back to the legacy lexical result when spaCy is not
  available.
- Connected the second `open_subordinate_prefix_fragment` emission through the
  single final-boundary consumer, without changing the shared display helper.
  The external stage-2 replay now reports 452/5180 illegal boundaries and
  37 open-prefix cases; reverse enumeration reports 69 newly legal and 0
  newly illegal candidates. The complete offline regression remains 28/30:
  only the known 1260px pagination experiment's line-rendering and
  fallback-page expectations fail.

