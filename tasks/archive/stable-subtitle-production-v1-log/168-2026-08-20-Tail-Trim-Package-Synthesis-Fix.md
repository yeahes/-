## 2026-08-20 Tail-Trim Package Synthesis Fix

- Root cause: tail deletion rebuilt the parent cue timeline but reused the old
  frozen page end. The saved package could pass editor validation and later be
  rejected by synthesis because its final SRT cue, final page, and media cut
  had three different end times.
- The final cue timeline now accepts an explicit tail-cut end cap while still
  requiring coverage of the retained word envelope. Frozen page reuse syncs
  only the first/last page edges for a tail-trimmed package.
- A regression saves and reloads the package through the production display-
  page artifact loader. The final cue, final page, and media cut are equal.
- `tests/test_final_cue_timeline.py`, the complete manual-final editor suite,
  `scripts/run_regression.py`, and `git diff --check` pass offline.

