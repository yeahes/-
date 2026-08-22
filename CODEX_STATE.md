# Project State
Status: complete
Last verified: 2026-08-23 01:52:08 Asia/Shanghai
Branch: main
Verified HEAD: 6104934 (documentation-only working tree changes)
Working tree: untracked audit documentation; unrelated output preserved

## Current Goal
Standardize a read-only, actual-display-page audit for every new automatic subtitle result.

## Confirmed Facts
- The newest White House raw checkpoint has 221 parents, 271 actual pages, 42 multipage parents, 5 missing page-Chinese IDs, and 5 formal error parents.
- Its semantic review queue is stale: all 25 saved context rows mismatch the current English spans.
- Chocolate v27/v29 share word-ledger hash `85ba0f98...9199a`; v27 is PASS and v29 is ERROR with different parent/page plans.
- Local skill `audit-caption-results` collects immutable-run identity, parent/neighbour context, actual pages, page Chinese, marks, and same-ledger A/B evidence without writes.

## Approved Decisions
- A routine new-run audit checks one raw automatic result; regression claims require the same word ledger.
- Skill qualification uses the current result, one same-ledger A/B, and later one historical good-result guard instead of re-auditing every recent case.

## Relevant Paths
- Audit: `docs/audits/2026-08-23/recent-actual-page-quality-audit.md`
- Skill: `C:\Users\19379\.codex\skills\audit-caption-results\SKILL.md`
- Collector: `C:\Users\19379\.codex\skills\audit-caption-results\scripts\collect_caption_evidence.py`

## Last Verification
- Skill validator passes; collector reproduces White House counts/identity failure and Chocolate same-ledger A/B; UTF-8 output passes.

## Next Action
Invoke `$audit-caption-results` on the next unseen automatic run and complete one full page-level audit.

## Do Not Regress
- Keep audits read-only and separate raw automatic checkpoints from manual finals.

## Unknowns
- No manually labelled corpus yet proves review precision/recall across unseen audio.
