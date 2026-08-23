# Project State
Status: complete
Last verified: 2026-08-23 17:57:52 Asia/Shanghai
Branch: main
Verified HEAD: 815c497
Working tree: clean except unrelated untracked `output/`

## Current Goal
Fixed-parent page selection and episode-scoped, output-aware, themed recovery are integrated.

## Confirmed Facts
- Fixed-parent bilingual A/B changes four newest White House parents; three clear improvements and one REVIEW improvement pass page-Chinese contracts.
- Historical White House, Chocolate v27/v29, and Employment guards have zero fixed-parent changes.
- Variable-parent `3 -> 2/4` checked 18,457 partitions for 14 targets and found zero feasible candidates; it made zero API calls.
- `More -> Restore Recent Subtitles` loads manifests directly and normal close retains dirty edits in a hash-bound draft.
- Real `work-dir` discovery returns 20 episode entries in 0.367 seconds; newest White House is one entry backed by five historical runs.

## Approved Decisions
- Integrate only the fixed-parent material-improvement selector; reject the tested variable-parent design.
- Group recovery entries per audio while preserving unsaved drafts and discovering source-adjacent manual packages.
- The user will run the complete regression; Codex runs focused tests and real read-only replays.

## Relevant Paths
- Evidence: `docs/handoffs/2026-08-23-fixed-parent-production-and-recovery-list.md`
- Recovery: `app/core/subtitle_processor/manual_final_subtitle_editor.py`, `app/view/subtitle_interface.py`
- Experiments: `scripts/experiment_fixed_parent_bilingual_pages.py`, `scripts/audit_variable_parent_count_joint_planning.py`
- Commits: production selector `bb9d98d`; consolidated recovery `815c497`.

## Last Verification
- Focused selector/editor/publication tests: 223 passed. Syntax and diff checks pass. The current stage intentionally did not run the complete regression.

## Next Action
User runs `runtime\python.exe scripts\run_regression.py`, then verifies planner v32 and `More -> Restore Recent Subtitles` in the GUI.

## Do Not Regress
- Do not mutate production artifacts, frozen English/IDs/timing, caches, audio, checkpoints, or untracked `output/`.

## Unknowns
- Complete-regression and GUI acceptance results are pending user verification.
