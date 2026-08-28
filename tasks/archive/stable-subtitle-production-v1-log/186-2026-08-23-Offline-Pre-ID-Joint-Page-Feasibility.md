## 2026-08-23 Offline Pre-ID Joint Page Feasibility

- Built a generic read-only experiment around the current pre-ID grammar gate
  and the production fixed-font page planner. It enumerates bounded neighboring
  parent cuts without assigning IDs or changing the source word ledger.
- Scanned 2,686 combinations for the 14 requested White House targets. Only one
  changed-boundary alternative remained feasible; it improved `S0183` by
  worsening its left neighbor. No candidate produced a net improvement, and
  the three frozen-parent failures remained unsolved.
- Corrected the experiment guard after an initial per-cue replay produced two
  false signature changes. The final guard uses production whole-episode
  sequence selection and same-screen finalization: 217/217 pass with zero
  page-range/font changes.
- The experiment made no API request and did not alter production code,
  subtitles, audio, caches, checkpoints, or `work-dir`. The tested same-count
  joint precheck is not recommended for production.
- Verification: `tests/test_pre_id_joint_page_feasibility.py` passes 9/9 and
  `runtime\\python.exe scripts\\run_regression.py` passes 30/30 in 904.05
  seconds. Repeated `WinError 32` messages came from GUI-held log rotation and
  did not fail the run.

