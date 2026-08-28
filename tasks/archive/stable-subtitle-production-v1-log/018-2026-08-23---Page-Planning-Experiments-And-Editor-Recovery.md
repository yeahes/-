## 2026-08-23 - Page Planning Experiments And Editor Recovery

- Completed the fixed-parent bilingual page A/B. It changes four parents on
  the newest White House checkpoint, passes page-Chinese validation, and leaves
  four historical/cross-case guards unchanged. It remains experiment-only
  until the actual four-page sequences receive user acceptance.
- Completed the variable-parent-count `3 -> 2/4` experiment. It examined
  18,457 partitions across the requested 14 targets and found no feasible
  candidate, so no translation request was made and the design is rejected.
- Added `Restore Recent Subtitles` for direct manifest-based reopening from the
  configured work directory. Normal close persists a hash-bound dirty draft;
  reopening restores it without running the subtitle pipeline or using API
  quota.
- Real `work-dir` discovery loaded the newest five packages in 0.528 seconds.
  Focused verification passes 2/2 fixed-parent experiment, 7/7
  variable-parent experiment, 120/120 editor, and 93/93 publication/UI tests.
- The complete offline regression passes 30/30 in 902.68 seconds. `py_compile`
  passes, and `git diff --check` reports only existing line-ending warnings.
- Complete evidence is recorded in
  `docs/handoffs/2026-08-23-page-planning-experiments-and-editor-recovery.md`.

