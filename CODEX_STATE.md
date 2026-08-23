# Project State
Status: active
Last verified: 2026-08-23 09:10:54 Asia/Shanghai
Branch: main
Verified HEAD: 4f68993
Working tree: documentation updates plus unrelated untracked output/

## Current Goal
Evaluate a pre-ID English-boundary and display-page feasibility joint planner offline.

## Confirmed Facts
- Content-bound full-translation cache identity can reuse 182/188 unchanged White House semantic groups while invalidating six changed groups.
- Parent-level page-Chinese units rebind shifted IDs only after full current-contract validation.
- New checkpoint snapshots exclude identity-mismatched copied semantic review queues.
- The 14-ID page frontier has 11 frozen-parent solutions; S0123/S0132/S0192 require an upstream boundary change.

## Approved Decisions
- Test the joint planner offline before changing production segmentation.
- Preserve exact word coverage, timestamps, frozen-contract policy, and passing non-target page signatures.

## Relevant Paths
- Existing frontier audit: `scripts/audit_article_page_candidate_frontier.py`
- English boundary owner: `app/core/subtitle_processor/screen_editor.py`
- Page planner: `app/core/utils/podcast_learning_video.py`
- Target report: `output/white-house-14-id-frontier-20260823-v2.json`

## Last Verification
- Affected pytest files: 705/705 PASS. Full regression: 30/30 PASS in 908.59s.

## Next Action
Estimate and implement a read-only local joint-boundary/page-feasibility experiment.

## Do Not Regress
- Do not mutate production artifacts or relax word coverage, timing, font, semantic ownership, or lexical-word split checks.

## Unknowns
- Whether local boundary movement solves the three frozen-parent failures without regressing passing cues.
