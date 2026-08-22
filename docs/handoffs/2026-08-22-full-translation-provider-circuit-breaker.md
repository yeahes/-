# Full-Translation Provider Circuit Breaker

Status: complete
Last verified: 2026-08-22 22:33:04 Asia/Shanghai
Branch: main
Base HEAD: 8bd57b0

## Outcome

- Complete semantic translation now uses rolling batches of at most eight
  groups and at most two in-flight requests.
- Each initial batch gets one HTTP attempt. A valid response is checked and
  committed immediately to the existing per-group resumable cache.
- Two consecutive retryable provider errors open a circuit. No later batch is
  admitted; already in-flight valid responses are still cached.
- One isolated provider error followed by success continues normally. Request
  budget exhaustion and non-retryable failures stop immediately.
- The explicit failure is `semantic_full_translation_provider_unavailable`,
  with missing semantic group IDs and retry guidance.
- A failed HTTP attempt produces exactly one request-ledger record.

## Preserved Contracts

- No English segmentation, English text, subtitle ID, word span, word timing,
  final cue timing, translation prompt, allocation rule, or page-planning rule
  changed.
- No paid API call or production artifact write was used for verification.

## Verification

- Focused scheduler and ledger tests: 5 passed.
- `tests/test_stable_caption_rules.py`: 530 passed in 156.03 seconds.
- Full regression: 29/30 passed initially; the sole failure was two stale
  renamed calls in the stable-caption `__main__` harness. After correcting the
  harness, the failed check passed in 138.77 seconds, for 30/30 verified checks.
- `git diff --check`: passes; only Git line-ending conversion warnings remain.

## Remaining Live Check

The working-copy GUI was started as PID 9252. Retry the White House audio there.
Provider health is external and remains unknown, but persistent
`500`/`503`/timeout responses should now fail early while retaining completed
translation caches.
