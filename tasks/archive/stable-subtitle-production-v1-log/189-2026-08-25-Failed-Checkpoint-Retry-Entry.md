## 2026-08-25 Failed-Checkpoint Retry Entry

- Fixed the editor workflow that hid the processing entry after a failed stable
  checkpoint was loaded. The top button now shows `重试` in that state and
  protects unsaved manual edits before restarting the same task.
- Normal manual editing still hides the processing entry; successful runs and
  new imports restore the ordinary `开始` state. This change does not mutate
  subtitle artifacts or timing contracts.
- Verification: `tests/test_stable_publication.py` passes 97/97.
- The recent-results recovery path also distinguishes a matching failed
  checkpoint from an ordinary stable package, so restarting the app does not
  turn a retryable failure into a read-only manual preview. The original raw
  subtitle and media paths are retained only for rebuilding the retry task.
- Early provider failures without a stable checkpoint now keep the same generic
  `重试` action while retaining the failure status; this covers API 500 errors
  during full translation without allowing an incomplete run into synthesis.

