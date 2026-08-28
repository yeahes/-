## 2026-08-25 - Failed-run retry keeps the original translation context

- Root cause: reopening a blocked checkpoint kept only subtitle/media paths.
  Recreating the task therefore dropped article assistance and terminology
  context, invalidating otherwise reusable semantic translation cache keys.
- Retry now restores the source article, cached article context, and both
  article feature flags from the checkpoint manifest. Early provider failures
  use the same run's `run-state.json` and source-adjacent article artifacts.
- The cache contract itself was not relaxed, so a translation is reused only
  when its source, prompt, model, and validated context still match.
- Focused publication/retry tests: 101 passed. The latest real run remains
  blocked by DeepSeek HTTP 500/timeouts and must be retried after service recovery.

