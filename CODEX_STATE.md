# Project State
Status: active
Last verified: 2026-08-24 04:08:06 Asia/Shanghai
Branch: main
Verified HEAD: 946585c
Working tree: clean for tracked project files; unrelated generated `output/`
  directories remain untracked and preserved

## Current Goal
Prevent manual-final saves after timeline deletion from discarding valid frozen
display pages or expanding one page error into a whole-episode pending queue.

## Confirmed Facts
- Fixed-parent bilingual A/B changes four newest White House parents; three clear improvements and one REVIEW improvement pass page-Chinese contracts.
- Historical White House, Chocolate v27/v29, and Employment guards have zero fixed-parent changes.
- Variable-parent `3 -> 2/4` checked 18,457 partitions for 14 targets and found zero feasible candidates; it made zero API calls.
- `More -> Restore Recent Subtitles` loads manifests directly and normal close retains dirty edits in a hash-bound draft.
- Real `work-dir` discovery returns 20 episode entries in 0.367 seconds; newest White House is one entry backed by five historical runs.
- Complete-parent deletion now uses schema-v3 media derivation and a pure
  source-to-presentation time map; source authority remains immutable.
- An `ERROR` display-page artifact with render plans remains a usable frozen
  geometry checkpoint; semantic errors still block publication.
- ID-bound page translation reuse preserves valid sibling pages and leaves
  exact missing/blank pages for formal contract validation.
- Source-scoped page errors remain blocking for their recorded parent/page;
  the Japanese X-generation replay reports only `S0136.P01/P02` after the
  six-parent deletion.
- Focused deletion/editor/publication/synthesis regression: 262 passed.
- Full regression: 29/30 checks passed. The isolated failure is the existing
  `S9522` article page-start assertion (`into` expected, `in` selected), with
  no production pagination diff in this task.

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
- `runtime\\python.exe -m pytest tests/test_manual_final_subtitle_editor.py -q`:
  130 passed.
- `runtime\\python.exe -m pytest tests/test_stable_publication.py -q`: 96
  passed after isolating internal Qt model publication from user edits.
- Read-only original Japanese X-generation checkpoint replay keeps 241 frozen
  plans (235 after deleting S0001-S0006) and reuses all 296 remaining pages.
- Full `scripts/run_regression.py` completed 29/30 checks; the only failure is
  the unrelated existing article-display readability assertion.

## Next Action
Measure text edit, split, merge, boundary, and page-confirm actions in the
restarted source GUI (PID 31388).

## Do Not Regress
- Do not mutate production artifacts, frozen English/IDs/timing, caches, audio, checkpoints, or untracked `output/`.

## Unknowns
- GUI acceptance of the editor latency fix is still pending; source GUI PID
  31388 is running for manual interaction.
- The pre-existing S9522 article readability assertion needs a separately
  scoped pagination decision.
