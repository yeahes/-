## 2026-08-03 Stage Progress And Safe Resume

- Added a durable `run-state.json` state machine outside subtitle processing.
- The bottom status label now receives stage-aware messages with completed
  batch count, cache hits, retries, elapsed time, and a bounded ETA.
- Resume is intentionally narrow: only article-context and corrected-ASR
  artifacts with matching input/configuration hashes and verified file digests
  are reused. Existing ID-bound LLM batch cache continues to avoid duplicate
  completed translation/allocation calls.
- No English, subtitle ID, word ledger, final timing, Chinese allocation, or
  export writer is restored from an incomplete in-memory pipeline stage.

