# Project State
Status: active
Last verified: 2026-08-23 03:40:10 Asia/Shanghai
Branch: main
Verified HEAD: 3e2f2b7 (base; English boundary delta verified in working tree)
Working tree: English boundary source/tests/docs modified; unrelated output preserved

## Current Goal
Repair the verified causes of reduced automatic subtitle quality in independently tested commits.

## Confirmed Facts
- The newest White House raw checkpoint has 221 parents, 271 actual pages, 42 multipage parents, 5 missing page-Chinese IDs, and 5 formal error parents.
- Local skill `audit-caption-results` collects immutable-run identity, parent/neighbour context, actual pages, page Chinese, marks, and same-ledger A/B evidence without writes.
- Chocolate real-timing replay restores its complete 11+5 page plan; passing White House replay changes 0/217 frozen page/font signatures.
- New White House replay removes 6/6 confirmed English defects with 2,586/2,586 ordered words preserved.
- The stable-caption rule suite passes 538/538; the newly exposed 24-word cue retains its historical 56px three-page plan.

## Approved Decisions
- A routine new-run audit checks one raw automatic result; regression claims require the same word ledger.
- Skill qualification uses the current result, one same-ledger A/B, and later one historical good-result guard instead of re-auditing every recent case.
- Keep identity, pagination, parent-boundary, and page-Chinese fixes in separate commits.

## Relevant Paths
- Audit: `docs/audits/2026-08-23/recent-actual-page-quality-audit.md`
- Skill: `C:\Users\19379\.codex\skills\audit-caption-results\SKILL.md`
- Collector: `C:\Users\19379\.codex\skills\audit-caption-results\scripts\collect_caption_evidence.py`
- Review identity: `app/core/subtitle_processor/review_evidence_identity.py`
- Page planner: `app/core/utils/podcast_learning_video.py`

## Last Verification
- Stable-caption rules 538/538; White House 2,586/2,586 words and historical three-page guard pass.

## Next Action
Commit the verified English boundary fix, then repair page-Chinese completeness and continuity.

## Do Not Regress
- Do not mutate production artifacts or relax word coverage, timing, font, or semantic page ownership.

## Unknowns
- Exact uncommitted source delta between Chocolate planner v27 and v29 is unavailable.
