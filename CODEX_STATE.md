# Project State
Status: complete
Last verified: 2026-08-23 13:08:01 Asia/Shanghai
Branch: main
Verified HEAD: 253d783
Working tree: clean except unrelated untracked `output/`

## Current Goal
Complete two long-caption experiments and preserve generated subtitles across editor restarts.

## Confirmed Facts
- Fixed-parent bilingual A/B changes four newest White House parents; three clear improvements and one REVIEW improvement pass page-Chinese contracts.
- Historical White House, Chocolate v27/v29, and Employment guards have zero fixed-parent changes.
- Variable-parent `3 -> 2/4` checked 18,457 partitions for 14 targets and found zero feasible candidates; it made zero API calls.
- `More -> Restore Recent Subtitles` loads manifests directly and normal close retains dirty edits in a hash-bound draft.
- Real `work-dir` discovery loaded five recent packages in 0.528 seconds without pipeline execution.

## Approved Decisions
- Keep both page strategies outside production pending acceptance; reject the tested variable-parent design.
- Commit independently verified logical changes; do not add `output/` artifacts.

## Relevant Paths
- Evidence: `docs/handoffs/2026-08-23-page-planning-experiments-and-editor-recovery.md`
- Recovery: `app/core/subtitle_processor/manual_final_subtitle_editor.py`, `app/view/subtitle_interface.py`
- Experiments: `scripts/experiment_fixed_parent_bilingual_pages.py`, `scripts/audit_variable_parent_count_joint_planning.py`
- Commits: experiments `42a7b75`; editor recovery `253d783`.

## Last Verification
- Fixed-parent 2/2, variable-parent 7/7, manual editor 120/120, stable publication 93/93 PASS; full regression 30/30 PASS in 902.68s.

## Next Action
Obtain user acceptance of the four fixed-parent bilingual page sequences before any production integration.

## Do Not Regress
- Do not mutate production artifacts, frozen English/IDs/timing, caches, audio, checkpoints, or untracked `output/`.

## Unknowns
- User acceptance of the four fixed-parent bilingual page changes.
