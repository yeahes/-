# Project State
Status: complete
Last verified: 2026-08-22 20:45:58 Asia/Shanghai
Branch: main
Verified HEAD: 04a8000 (tested subtitle-pipeline baseline); 0500b33 records the experiment entry state
Working tree: comparison documentation pending commit; local output remains untracked

## Current Goal
Determine through a read-only offline comparison whether pre-ID page feasibility has proven net benefit.

## Confirmed Facts
- White House replays 217/217 parents with zero page-count changes on the baseline.
- Employment `S0029` now replays at 56px; its saved v28 failure is stale and does not require joint planning.
- Of four current structural targets, local joint search found geometry solutions for two: Chocolate `S0160` and Employment `S0247`; it found none for Chocolate `S0026` or Employment `S0223`.
- The `S0247` candidates strand `And eventually,` on the preceding parent even though current boundary gates accept them.
- The `S0160` candidates move `Wow.` or `It is.` across parent boundaries, but the saved artifacts contain no speaker identity needed to prove that move safe.
- Japanese `S0136` retains its page split and is a page-Chinese/number-anchor issue, not evidence for parent resegmentation.

## Approved Decisions
- Do not implement pre-ID joint page feasibility unless a read-only experiment proves acceptable net improvement.
- English, IDs, word ledger, order, and timing remain local and deterministic.

## Relevant Paths
- Result: `docs/handoffs/2026-08-22-offline-joint-planning-comparison.md`
- Raw ignored output: `output/offline-joint-planning-comparison-20260822/comparison-result.json`
- Baseline context: `docs/handoffs/2026-08-22-independent-diagnostic-brief.md`

## Last Verification
- Core affected tests: 699 passed, 0 failed; focused selector regression passes; syntax and diff checks pass.
- Offline comparison: 0 API calls, 217 White House parents plus 1,364 local boundary combinations, completed in 215.772s.

## Next Action
Do not add the joint gate; first close unfinished-transition validation and speaker-turn ownership, then repeat the same falsifiable comparison.

## Do Not Regress
- Do not modify `D:/软件缓存/VideoCaptioner`, existing work-dir artifacts, manual finals, or frozen English/ID/timing contracts.

## Unknowns
- A wider search may find more geometry solutions, but no current evidence shows they are linguistically safe or beneficial on unseen audio.
