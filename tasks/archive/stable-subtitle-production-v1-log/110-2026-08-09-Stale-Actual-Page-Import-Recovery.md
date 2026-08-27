## 2026-08-09 Stale Actual-Page Import Recovery

- Reproduced the real desktop state: the actual-page SRT was generated before
  a later manual-final save. The later manifest correctly cleared page
  authority, but the source-folder page SRT remained and could still be chosen
  by the user.
- Import now treats that page SRT only as a hash-verified recovery pointer. Its
  companion map identifies the parent subtitle; manifest discovery then opens
  the latest parent manual package without copying stale page rows.
- The stale-import regression passes 1/1 and the full manual editor script
  passes 30/30. Real desktop replay resolves 261 current parent cues and leaves
  all 32 files / 42,933,689 bytes hash-identical.
- Unified regression passes 658 test items across 24 suites plus one syntax
  step in 338.800 seconds. `git diff --check` passes. External requests, ASR,
  LLM, FFmpeg, synthesis, and paid requests are zero.

