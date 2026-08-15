# Project State
Status: complete
Last verified: 2026-08-15 00:38:38 Asia/Shanghai
Branch: main
Verified HEAD: 167514dcbe0cc14fdb56b38a499b00190e241f02
Working tree: modified by verified editor, translation, recovery, ASR-correction, and review increments; `.workbuddy/` remains untracked and excluded

## Current Goal
Remove high-frequency manual-editor stalls without changing subtitle, timing, translation, or rendering behavior.

## Confirmed Facts
- Parent-local edit history stores only one parent state; legacy full snapshots compact in memory without rewriting source packages.
- English word-surface undo stores changed frozen words plus the prior formal-ledger hash; IDs, times, cue spans, and boundary validation are preserved.
- Recovery drafts remain atomic and complete but use compact JSON. The real 119-operation draft fell from 32.8 MB to 3.1 MB; hash/write fell from about 222/1299 ms to 31/138 ms.
- Local table changes use row updates/inserts/removals; imports and parent/page view switches still use a full reset.
- Read-only replay of two real packages preserved all unrelated parents through Chinese edit, split, undo, and redo.
- The final complete regression passed in 346.3 seconds; focused manual-editor, publication, review-mark, artifact, syntax, and diff checks pass.

## Approved Decisions
- Preserve fixed English IDs, word order, authoritative word ledger, timing, and render geometry.
- Keep cross-parent, formal-boundary, and audio-tail operations whole-document transactions.
- Do not include `.workbuddy/` in a project commit.

## Relevant Paths
- `app/core/subtitle_processor/manual_final_subtitle_editor.py`
- `app/core/subtitle_processor/stable_artifacts.py`; `app/view/subtitle_interface.py`
- `tasks/active/manual-long-caption-workspace.md`

## Last Verification
- Focused suites and `runtime\python.exe scripts\run_regression.py` pass; two real artifact replays were read only and wrote no production artifact.

## Next Action
Restart the GUI, reopen an existing manual-final subtitle, and verify split, boundary move, Chinese edit, undo, and automatic draft recovery feel responsive.

## Do Not Regress
- Keep English text/IDs/timing deterministic; never trade crash recovery or undo correctness for UI speed.

## Unknowns
- A mouse-driven GUI pass is still required to measure perceived latency with the user's normal editing cadence.
