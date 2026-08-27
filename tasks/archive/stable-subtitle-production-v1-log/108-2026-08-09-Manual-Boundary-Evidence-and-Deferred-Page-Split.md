## 2026-08-09 Manual Boundary Evidence and Deferred Page Split

- Root cause: manual-final publication wrote back only the evidence keys needed
  inside the current cue partition. Undo or a later formal boundary move could
  make an omitted cue edge internal and trigger
  `manual_page_boundary_evidence_required`.
- Publication now preserves all adjacent word-ledger boundary evidence. Legacy
  packages recover only accepted cue-edge boundaries proven by current cues or
  undo history and mark them as REVIEW; unexplained internal evidence gaps still
  fail closed.
- Parent rows retain two/three/four-page commands while pages are stale. A
  requested split starts one background refresh and runs once after the matching
  package reload; save/reload failure clears the request without changing cues.
- The real desktop study-abroad package passed a read-only full-undo check with
  2,861/2,861 boundaries and no package hash changes. A temporary-copy save and
  reload retained the same coverage. The remaining
  `manual_page_translation_required` result correctly requests new page Chinese
  after boundary ownership changes.
- Focused tests and syntax checks pass. Unified regression passes 603 tests
  across 24 suites plus one syntax step in 332.064 seconds. `git diff --check`
  passes. External requests, ASR, LLM, synthesis, and paid requests are zero.

