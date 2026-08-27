# Project State

Status: in_progress
Last verified: 2026-08-27 12:54:20 Asia/Shanghai
Branch: main
Verified HEAD: 11398c6
Working tree: modified (151 entries; source, tests, docs, scripts, and generated evidence remain mixed)

## Current Goal
Resolve the current unreviewed pagination blocker, then separate the mixed
working tree into reviewable source, test, documentation, and evidence groups.

## Confirmed Facts
- A completed `frozen_parent_timeline` stage is reusable only under the same input fingerprint and valid file digests.
- Restore cross-checks frozen English, IDs, word ranges, the word ledger, source coverage, parent Chinese, semantic groups, boundary evidence, and final timing.
- A restored retry skips `screen_editor.edit()` and WhisperX, then enters display-page translation; successful page batches keep their existing unit caches.
- The real unreviewed `中国职场女性为何悄然掉队？` checkpoint restored read-only with 271 IDs, 2855 words, 245 semantic groups, 2845 source segments, and a PASS final timeline. All 44 checkpoint files were unchanged.
- Its only current blocker is deterministic pagination for S0089 (`no_complete_normal_font_page_partition`), not an API failure.
- G1 is implemented: renderable review fallbacks are degraded parent records, not episode errors; a read-only replay of the 04:06 checkpoint produced PASS with one degraded parent (S0089).
- The latest unreviewed `中国企业正把供应链铺满全球` checkpoint is still `ERROR`
  at 53/55 display pages: S0136 is missing two page rows and S0260 has a
  misplaced negation. Four OpenCode Go retries did not pass lexical/semantic
  validation. A separate offline candidate restores 55 pages and passes the
  renderer apply check, but has not been written back to the checkpoint.
- Focused page-retry tests pass 10/10; the offline candidate remains a review
  aid only because S0260 still needs a human semantic confirmation.

## Approved Decisions
- Do not rerun or mutate manually reviewed audio packages for retry verification.
- Do not restore failed display-page output as authority; retry only that downstream stage and reuse independently validated batch caches.

## Relevant Paths
- Source: `app/core/subtitle_processor/stable_run_state.py`, `app/core/subtitle_processor/screen_editor.py`, `app/thread/subtitle_thread.py`, `app/view/subtitle_interface.py`
- Tests: `tests/test_stable_run_state.py`, `tests/test_stable_publication.py`
- State: `docs/CURRENT_STATE.md`, `docs/PIPELINE.md`

## Last Verification
- Real checkpoint restore: 271 IDs, 2855 words, source coverage equal, final timeline PASS, 44/44 files unchanged.
- `runtime\\python.exe -m pytest tests\\test_stable_run_state.py -q`: 9 passed.
- `runtime\\python.exe -m pytest tests\\test_stable_publication.py -q`: 102 passed.
- G1 checkpoint replay: PASS, degraded=1 (S0089), 306 pages total, 0 page-signature changes outside S0089, page-translation cache validation PASS, QA queue=76, semantic queue=9.
- Latest page-blocker probe: OpenCode Go retries rejected; offline candidate
  validated `status=PASS`, 55 pages, 27 multi-page parents, and renderer
  application `True` without changing the source checkpoint.

## Next Action
Keep the validated page candidate out of source commits; finish the documentation
archive and prepare small, mechanism-scoped source/test commit groups.

## Do Not Regress
- Preserve frozen English/IDs/word ownership/final timing, reject inconsistent checkpoints, keep successful page-batch caches, and never write `D:\\软件缓存\\VideoCaptioner`.

## Unknowns
- Live GUI retry after application restart has not yet confirmed the new 96%-stage resume display; the offline checkpoint replay is complete.
- It is not yet decided whether the two current page failures will be handled
  by manual final-editor bypass or by a general production fallback.
