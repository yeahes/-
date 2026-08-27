## 2026-08-04 Relative-Clause Predicate Boundary E2E

- Root cause: the final pre-ID validator did not inspect a right cue for a
  finite predicate without a subject. The 480 ms pause at that invalid
  production boundary caused the generic repair window to skip it.
- Fix: `right_orphaned_finite_predicate` is now a final-boundary hard issue.
  The repair loop may cross only that target boundary's pause and only for a
  direct merge that passes the pre-existing structural-overflow proof. It does
  not relax the pause rule for generic repartitioning.
- Added a 480 ms regression for `yet ... are completely contradicted ...`.
  `tests/test_stable_caption_rules.py`, `scripts/run_regression.py`, and
  `git diff --check` passed.
- The first isolated E2E artifact remains preserved as a failing regression
  witness. The second E2E subtitle-only rerun passed with 276 fixed IDs,
  `render_blocked=false`, zero final-timeline errors, and delegated 7/10/15/18
  second PNG review. No video was synthesized.

