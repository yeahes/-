# Project State
Status: active
Last verified: 2026-08-23 11:14:38 Asia/Shanghai
Branch: main
Verified HEAD: 10b8ff3
Working tree: unrelated untracked output/ only

## Current Goal
Improve difficult long subtitles without destabilizing frozen English ownership.

## Confirmed Facts
- Content-bound full-translation cache identity can reuse 182/188 unchanged White House semantic groups while invalidating six changed groups.
- Parent-level page-Chinese units rebind shifted IDs only after full current-contract validation.
- New checkpoint snapshots exclude identity-mismatched copied semantic review queues.
- The offline same-count joint-boundary experiment examined 2,686 combinations for 14 targets and produced zero net improvements.
- S0123/S0132/S0192 have no legal same-count, three-parent solution within an eight-word boundary radius.
- The other ten difficult targets remain inside-parent page-selection problems; moving formal parent boundaries did not help.
- Historical White House guard replay is 217/217 PASS with zero page-range or font-signature changes.
- Inside-parent material ordering leaves the historical 217/217 guard unchanged.
- On the newest White House run it proposes four changes: S0072/S0201/S0205 clear improvements and S0097 modest improvement.
- S0051's false 16+5 fragment is rejected by requiring zero unsupported REVIEW boundaries in every promoted candidate.
- S0123/S0132/S0192 remain structural failures; four requested targets have no alternate page candidate.

## Approved Decisions
- Do not integrate the tested same-count joint precheck into production.
- Do not integrate material page ordering until changed boundaries pass page-Chinese A/B.
- Preserve exact word coverage, timestamps, frozen-contract policy, and passing non-target page signatures.

## Relevant Paths
- Joint feasibility audit: `scripts/audit_pre_id_joint_page_feasibility.py`
- English boundary owner: `app/core/subtitle_processor/screen_editor.py`
- Page planner: `app/core/utils/podcast_learning_video.py`
- Experiment report: `output/offline-pre-id-joint-page-feasibility-20260823.json`
- Material ordering audit: `scripts/audit_article_page_candidate_frontier.py`
- Material ordering tests: `tests/test_article_page_candidate_frontier.py`

## Last Verification
- Material selector tests: 6/6 PASS. Historical White House guard: 217/217 with zero material changes. Full regression: 30/30 PASS in 948.16s.

## Next Action
Run page-Chinese A/B for the four changed boundaries before any production integration.

## Do Not Regress
- Do not mutate production artifacts or relax word coverage, timing, font, semantic ownership, or lexical-word split checks.

## Unknowns
- Whether changed English page boundaries preserve page-Chinese meaning and continuity.
- Whether a higher-risk variable-parent-count experiment can solve S0123/S0132/S0192 with speaker and Chinese A/B evidence.
