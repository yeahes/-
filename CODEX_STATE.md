# Project State
Status: complete
Last verified: 2026-08-17 20:30:42 Asia/Shanghai
Branch: main
Verified HEAD: 55974cc99542d36559ad2f063247f1997cf1497d
Working tree: modified; pre-existing work plus current manual-editor changes

## Current Goal
Verify multiword English correction, combined mute-plus-tail deletion, and read-only English copy end to end.

## Confirmed Facts
- Contiguous raw word IDs can map to one display surface without changing raw IDs or word times.
- Display overrides survive separate one-word edits, parent merge, save/reload, undo, and redo.
- A tail cut cannot split a display override; complete retained/removed spans stay atomic.
- Media derivation schema v2 supports ordered mute intervals plus an optional suffix cut from original media.
- Selected English rows copy in display order through `Ctrl+C` or `复制英文` without session mutation.
- Focused suites and the complete unified regression pass.

## Approved Decisions
- Preserve fixed subtitle IDs, raw word ledger, word times, cue timing, and automatic pagination policy.
- Treat multiword correction as presentation-only many-to-one projection, not free English rewriting.
- Always derive edited audio once from the hash-bound original media.

## Relevant Paths
- `app/core/subtitle_processor/manual_final_subtitle_editor.py`
- `app/view/subtitle_interface.py`
- `tests/test_manual_final_subtitle_editor.py`

## Last Verification
- `runtime\python.exe scripts\run_regression.py` and `git diff --check` exit zero.

## Next Action
Restart the GUI and smoke-test copy, multiword correction, and mute-plus-tail deletion on a duplicate package.

## Do Not Regress
- Do not mutate original media, frozen IDs, raw word times, or automatic English segmentation.

## Unknowns
- Fresh mouse-driven GUI smoke remains pending after automated verification.
