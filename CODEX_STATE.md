# Project State
Status: complete
Last verified: 2026-08-22 22:33:04 Asia/Shanghai
Branch: main
Verified HEAD: 8bd57b0 (base; modified working tree verified)
Working tree: verified checkpoint ready to commit; untracked output preserved

## Current Goal
Bound complete-Chinese-translation failure latency during persistent provider errors while preserving resumable work.

## Confirmed Facts
- Initial full translation uses batches of at most 8 and at most 2 in-flight requests.
- Two consecutive retryable provider failures stop new admission; in-flight valid results still cache.
- One isolated failure may recover; budget exhaustion or non-retryable failure stops immediately.
- One HTTP attempt creates one ledger record; completed unit caches survive retry.
- English, IDs, timing, prompts, allocation, and display-page rules are unchanged.

## Approved Decisions
- Reuse the bounded page-stage scheduler pattern; do not change subtitle-content contracts.
- Commit each tested logical change before a real GUI/audio comparison; do not commit exploratory edits or generated output.

## Relevant Paths
- Handoff: `docs/handoffs/2026-08-22-full-translation-provider-circuit-breaker.md`
- Source: `app/core/subtitle_processor/screen_editor.py`
- Tests: `tests/test_stable_caption_rules.py`

## Last Verification
- Focused 5/5; stable-caption pytest 530/530; full regression checks 30/30 after harness-name repair; diff check passes; working-copy GUI PID 9252 started.

## Next Action
Retry White House in the running working-copy GUI to verify live provider behavior and cache resume.

## Do Not Regress
- Do not modify frozen English/ID/word/timing/page contracts or production work-dir artifacts.

## Unknowns
- Current OpenCode Go provider health and fresh GUI end-to-end result.
