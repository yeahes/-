## 2026-08-17 Display-Page Chinese Candidate Fallback Recovery

- Reproduced the subsequent 96% failure from the saved
  `work-dir\肠道菌群，能人为操控吗？` artifacts without making a model request or
  rewriting production output.
- Confirmed the failure owner was page-Chinese candidate selection: 217 fixed
  IDs and 33 paginated parent contracts were complete. The Flash result had
  zero hard errors and six REVIEW findings; the optional Pro retry introduced
  expansion or repetition in several parents and was incorrectly promoted to
  an episode-wide blocker.
- Reclassified page-local continuation/fluency findings as REVIEW while keeping
  structural, semantic, identity, token-boundary, and hard speed errors
  blocking. Added a candidate fallback so a failed or worse optional Pro retry
  retains the complete initial projection and records the rejected evidence.
- Added regressions for REVIEW-vs-semantic blocking and for preserving a usable
  Flash projection after a worse Pro candidate. Real artifact replay passes
  33/33 parents with zero hard errors and six REVIEW findings. The complete
  regression command and `git diff --check` exit zero.

