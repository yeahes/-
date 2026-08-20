# Project State
Status: complete
Last verified: 2026-08-20 06:16:50 Asia/Shanghai
Branch: main
Verified HEAD: ab6ea58035ddbab1afe4a3631c28de8886f29332
Working tree: modified source/test/documentation files plus existing unrelated output/font changes

## Current Goal
Keep a tail-trimmed manual-final package valid from editor save through synthesis reload.

## Confirmed Facts
- The failed package had a valid manifest but three final ends: S0201 SRT
  `755009ms`, S0201.P02 `755064ms`, and media cut `754959ms`.
- Tail deletion now caps the last final cue at the media cut while preserving
  its retained word envelope.
- Frozen page reuse preserves IDs, text, word ranges, internal boundaries,
  Chinese, and layout; only the first/last parent edges are reconciled.
- The saved package reloads through the production synthesis page-artifact
  loader with one shared final cue/page/media end.

## Approved Decisions
- Do not relax ordinary page validation or change normal pagination/timing.

## Relevant Paths
- `docs/handoffs/2026-08-20-tail-trim-page-timing.md`

## Last Verification
- Focused timeline and complete manual-editor suites pass.
- `runtime\python.exe scripts\run_regression.py` completed all stages offline.
- `git diff --check` passes; no external model request was made.

## Next Action
Restart the GUI, reopen the current manual-final subtitle package, save it once, then synthesize again.

## Do Not Regress
- Preserve fixed English, IDs, word ledger, word envelopes, page text, and fail-closed publication.

## Unknowns
- The user's current unsaved GUI state cannot be migrated automatically; save must run once under the fixed code.
