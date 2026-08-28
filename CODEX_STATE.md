# Project State

Status: complete
Last verified: 2026-08-28 21:11:24 Asia/Shanghai
Branch: codex/backup-20260828
Verified HEAD: ea84999
Working tree: clean; local generated media remains ignored

## Current Goal
Prepare a recoverable GitHub backup branch containing source, tests, state,
handoffs, and reproducible audit material without generated media.

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
- Focused page-retry tests pass 11/11. The committed local retry freezes each
  valid parent in a mixed batch as an independent cache unit, so a later retry
  requests only the failed parent. The offline candidate remains a review aid
  only because S0260 still needs a human semantic confirmation.
- Committed mechanism groups are independently verified: frozen-parent resume
  (111 tests), selected-service translation audit (14), parent translation and
  backchannel rules (561), display-page translation (76), retry progress UI
  (102), and offline measurements (3 plus script self-test).
- §46.48 is wired as a default-off article-renderer display flag. With it off,
  page-local Chinese is unchanged; with it on, the 17 machine multi-page
  parents display their complete parent Chinese on each frozen English page.
- Fresh unreviewed run `人工智能会产生自我意识吗？`
  (`20260828T124923.879908-6e68f0d2`) is bound to the current `06df6585`
  commit and word ledger, but is `ERROR`/`render_blocked=true`: S0098 and
  S0116 have no complete normal-font page partition, and S0100 is missing
  `S0100.P01/P02` page translations. Its stressed audit covers 43 parents and
  75 pages; 32 parents are multi-page and 24 page boundaries are REVIEW.
  The run used `deepseek-v4-flash`, with 6 external attempts and 201 cache hits.
- Same-screen wrapping now rejects a measured shorter/longer line pixel ratio
  below `0.48`; regression coverage for the three originating cases passes.
  Offline v33 re-planning removes the three severe imbalance pages from the
  tested inputs, but the saved manual artifact and fresh checkpoint are not
  rewritten.
- Explicit manual-final synthesis now invokes frozen-page reflow for both PASS
  display artifacts and REVIEW draft artifacts. It changes only page-local
  English typography and preserves all frozen structural fields.
- Manual-final reload now retries same-screen typography reflow when an
  unchanged user-owned page range is rejected only by the legacy imbalance
  guard. The fallback preserves page IDs, word ranges, page Chinese, and
  timing; the desktop package now exposes S0006.P01/P02 and saves a render
  contract successfully.
- The latest manual-final package was synthesized locally with the committed
  reflow code and article template at 1920x1080. The MP4 is 11:46.10 with both
  H.264 video and AAC audio; representative frames for S0006, S0013, S0063,
  and S0088 show balanced two-line English layouts. The formal package path now
  detects this hash-bound manual final automatically.

## Approved Decisions
- Do not rerun or mutate manually reviewed audio packages for retry verification.
- Do not restore failed display-page output as authority; retry only that downstream stage and reuse independently validated batch caches.

## Relevant Paths
- Source: `app/core/subtitle_processor/stable_run_state.py`, `app/core/subtitle_processor/screen_editor.py`, `app/thread/subtitle_thread.py`, `app/view/subtitle_interface.py`
- Tests: `tests/test_stable_run_state.py`, `tests/test_stable_publication.py`
- State: `docs/CURRENT_STATE.md`, `docs/PIPELINE.md`

## Last Verification
- Real checkpoint restore: 271 IDs, 2855 words, source coverage equal, final timeline PASS, 44/44 files unchanged.
- `runtime\\python.exe -m pytest tests\\test_stable_run_state.py tests\\test_stable_publication.py -q`: 111 passed.
- `runtime\\python.exe -m pytest tests\\test_translation_quality_audit.py -q`: 14 passed.
- `runtime\\python.exe -m pytest tests\\test_stable_caption_rules.py -q`: 561 passed.
- `runtime\\python.exe -m pytest tests\\test_stable_page_translation_contract.py -q`: 76 passed.
- `runtime\\python.exe -m pytest tests\\test_stable_publication.py -q`: 102 passed.
- `runtime\\python.exe -m pytest tests\\test_measure_g6_manual_diff.py tests\\test_measure_page_number_anchors.py -q`: 3 passed; number-anchor script self-test PASS.
- Article readability contract: 109 passed, 1 failed (`test_three_line_fallback_promotes_complete_two_page_alternative`, S9522 expects `into` but current uncommitted planner selects `in`).
- G1 checkpoint replay: PASS, degraded=1 (S0089), 306 pages total, 0 page-signature changes outside S0089, page-translation cache validation PASS, QA queue=76, semantic queue=9.
- Latest page-blocker probe: OpenCode Go retries rejected; offline candidate
  validated `status=PASS`, 55 pages, 27 multi-page parents, and renderer
  application `True` without changing the source checkpoint.
- §46.48 read-only stable check: 17 multi-page parents, 37 pages, all complete
  parent Chinese returned under the enabled flag; default flag is `False`.
- Same-screen focused verification (`same_screen or severe or line_wrap`):
  18 passed, 94 deselected; `git diff --check` passed with only known
  LF/CRLF conversion warnings.
- Manual/display reflow verification: article display `20 passed, 94
  deselected`; full manual editor `137 passed`; the new affected-case test
  passes and the render contract remains unblocked.
- Local synthesis verification: MP4 decode completed at 1920x1080 / 11:46.10;
  four representative subtitle-page frames were visually inspected and were
  nonblank with the expected reflowed lines.

## Next Action
Review the local backup checkpoint, then push branch `codex/backup-20260828` to
the configured GitHub remote when ready.

## Do Not Regress
- Preserve frozen English/IDs/word ownership/final timing, reject inconsistent checkpoints, keep successful page-batch caches, and never write `D:\\软件缓存\\VideoCaptioner`.

## Unknowns
- Live GUI retry after application restart has not yet confirmed the new 96%-stage resume display; the offline checkpoint replay is complete.
- It is not yet decided whether the three fresh-run blocking parents will be
  handled by manual final-editor bypass or by a targeted display-stage retry.
- The 90-95% automation target still has no fresh blind-run measurement.
