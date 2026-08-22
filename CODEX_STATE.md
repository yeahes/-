# Project State
Status: active
Last verified: 2026-08-23 02:13:53 Asia/Shanghai
Branch: main
Verified HEAD: 65c10cb (base; review-identity change verified)
Working tree: review-identity source/tests/docs modified; unrelated output preserved

## Current Goal
Repair the verified causes of reduced automatic subtitle quality in independently tested commits.

## Confirmed Facts
- The newest White House raw checkpoint has 221 parents, 271 actual pages, 42 multipage parents, 5 missing page-Chinese IDs, and 5 formal error parents.
- Its semantic review queue is stale: all 25 saved context rows mismatch the current English spans.
- Chocolate v27/v29 share word-ledger hash `85ba0f98...9199a`; v27 is PASS and v29 is ERROR with different parent/page plans.
- Local skill `audit-caption-results` collects immutable-run identity, parent/neighbour context, actual pages, page Chinese, marks, and same-ledger A/B evidence without writes.
- Review queues now require current word-ledger and frozen ID/English/span identity; real White House replay has zero stale semantic-queue marks.

## Approved Decisions
- A routine new-run audit checks one raw automatic result; regression claims require the same word ledger.
- Skill qualification uses the current result, one same-ledger A/B, and later one historical good-result guard instead of re-auditing every recent case.
- Keep identity, pagination, parent-boundary, and page-Chinese fixes in separate commits.

## Relevant Paths
- Audit: `docs/audits/2026-08-23/recent-actual-page-quality-audit.md`
- Skill: `C:\Users\19379\.codex\skills\audit-caption-results\SKILL.md`
- Collector: `C:\Users\19379\.codex\skills\audit-caption-results\scripts\collect_caption_evidence.py`
- Review identity: `app/core/subtitle_processor/review_evidence_identity.py`

## Last Verification
- Review marks 24/24; QA queue 6/6; editor queue action 1/1; real White House stale semantic marks 0.

## Next Action
Separate soft page-style preferences from hard renderability failures using the Chocolate same-ledger replay.

## Do Not Regress
- Do not mutate production artifacts or relax word coverage, timing, font, or semantic page ownership.

## Unknowns
- Exact uncommitted source delta between Chocolate planner v27 and v29 is unavailable.
