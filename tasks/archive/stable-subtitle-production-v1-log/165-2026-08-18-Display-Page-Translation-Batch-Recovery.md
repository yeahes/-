## 2026-08-18 Display-Page Translation Batch Recovery

- Reproduced the latest 96% failure as a display-page Chinese timeout after the
  final word timeline had already passed. The compared runs had the same 256
  frozen parents, 282 display pages, and 25 multipage parents; the recent page
  planner was not the cause.
- Replaced the one-shot request for all 25 affected parents / 51 pages with
  deterministic batches capped at six parents and twelve pages. The real
  contract partitions into `6/12`, `6/12`, `5/11`, `6/12`, and `2/4`.
- Every validated batch is cached independently. A timeout still blocks the
  current publication, but it no longer erases completed paid work; rerunning
  resumes from the first uncached batch. Existing valid whole-contract caches
  remain compatible.
- Added a regression that forces a later batch to time out three times, verifies
  the earlier batch cache survives, resumes only the missing batch, validates
  the merged full contract, and reuses both batch and legacy whole caches.
- English segmentation, display-page planning, font selection, the final word
  ledger, cue timing, and synthesis inputs are unchanged.

