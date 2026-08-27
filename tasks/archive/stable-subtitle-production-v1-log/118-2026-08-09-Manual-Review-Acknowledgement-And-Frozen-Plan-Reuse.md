## 2026-08-09 Manual Review Acknowledgement And Frozen-Plan Reuse

- Added identity-bound acknowledgement for actual-page Chinese and REVIEW
  boundaries. Non-empty Chinese edits and explicit boundary moves acknowledge
  the resulting page automatically; current-item and bulk non-blocking actions
  cover unchanged content. HARD errors remain non-overridable.
- Fixed a state-ownership defect where a translation-blocked three-page manual
  checkpoint discarded its frozen plan and fell back to a new four-page
  automatic plan. Strict checkpoints now reuse their hash-bound PASS, REVIEW,
  or translation-blocked render plan.
- Save results now return the manual draft path and SHA-256 that are written to
  the manifest and override, preventing callers from treating a boolean as the
  complete draft contract.
- Six focused confirmation/recovery tests pass. The manual editor passes 50/50,
  stable publication passes 51/51, synthesis safety passes, and the unified
  regression passes all 25/25 stages (653 test items) in 403.562 seconds.
  `git diff --check` passes.
- Isolated replay of the current desktop package confirms 79 Chinese and 20
  REVIEW boundaries to 0/0/0, publishes formally, and preserves all 261 fixed
  cue identities/times plus the 2,862-word ledger. Evidence is stored at
  `E:\VideoCaptioner-e2e-runs\manual-review-confirmation-postcheck-20260809`.
  Desktop source-package and audio hashes are unchanged. Network, ASR, LLM,
  and real video synthesis calls are zero.

