## 2026-08-22 Full-Translation Provider Circuit Breaker

- Audited the latest White House request ledger. The run stopped at 55% after
  40 complete-translation attempts dominated by provider `500`, `503`, and
  90-second timeouts. The prior eager scheduler submitted every batch and
  delayed all unit-cache commits until all futures settled.
- Reused the page stage's bounded scheduling pattern for complete semantic
  translation: maximum eight groups per initial batch, maximum two in-flight
  requests, one initial attempt per batch, completion-order validation/cache
  commits, and progress after every settled batch.
- Added a two-consecutive-failure circuit breaker for retryable provider errors.
  Unstarted batches remain untouched; already in-flight valid responses are
  cached. One isolated failure followed by success continues normally, while a
  non-retryable error or exhausted request budget stops immediately.
- Added `semantic_full_translation_provider_unavailable` with missing group IDs
  and resumable-cache guidance. Removed the duplicate aggregate ledger entry so
  one recorded external attempt again equals one provider request.
- Scheduler and ledger regressions pass 5/5. The complete
  `tests/test_stable_caption_rules.py` suite passes 530/530 in 156.03 seconds.
  Full regression passed 29/30; its only failure was a stale renamed function
  in the stable-caption `__main__` harness. Static comparison found and fixed
  both stale names, and the failed check then passed in 138.77 seconds. The
  resulting verification is 30/30 checks. No paid request or production
  artifact was used or changed.
- Started the working-copy `VideoCaptioner.exe` after verification as PID 9252,
  so the next GUI retry loads this scheduler implementation.

