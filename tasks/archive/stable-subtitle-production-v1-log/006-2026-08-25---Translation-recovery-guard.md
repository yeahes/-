## 2026-08-25 - Translation recovery guard

- A page projection is recoverable without another API call only when its
  identity, English, and word range still match the visible source projection.
  If a manual boundary override exists, the exact page boundary must also be
  acknowledged; otherwise the checkpoint remains render-blocked.
- The manual-final editor suite passes after this guard. The full regression
  still reports the pre-existing display-readability expectation mismatch plus
  the now-obsolete stale-checkpoint expectation; neither is a translation
  prompt or cache failure.

