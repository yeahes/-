# Project State
Status: verified, uncommitted
Last verified: 2026-08-10 16:55:00 Asia/Shanghai
Branch: main
Verified HEAD: 6bb5ba8aee8d1542e0d965ee2d288c69cb2856b9
Working tree: modified by the single-page Chinese fit, exact failure attribution, numeric manual-boundary, test, and documentation changes

## Current Goal
Prevent false batch review marks and let manual numeric boundary edits move complete number phrases without changing frozen subtitle identity or timing.

## Confirmed Facts
- The observed pale-red batch came from one single-page Chinese fit failure at S0199 plus ID-less error fallback, not 39 independent subtitle failures.
- S0199 now plans two pages at `down / might`; simulated apply failure attribution returns only S0199.
- Manual numeric moves expand the selected count for complete numeric phrases in both directions; sentence-final numbers remain independent.
- Unified regression passes all stages in 374.9 seconds. External requests and production writes are zero.

## Approved Decisions
- Same-screen reflow has no authority over page count, page boundaries, IDs, English, Chinese, word ownership, or timing.
- A valid existing layout is the baseline; an invalid legacy layout must be replaced by the current legal fallback.
- Lexical atoms remain hard protected. Explicit non-atomic subject/predicate evidence is soft only because both lines remain on screen together.
- If a legal layout above 50px exists, 50px cannot compete.

## Relevant Paths
- `app/core/utils/podcast_learning_video.py`
- `app/core/subtitle_processor/stable_display_page_contract.py`
- `tests/test_article_display_readability_contract.py`
- `E:\VideoCaptioner-e2e-runs\same-screen-line-layout-v19-audit-20260810`

## Last Verification
- The complete article display readability contract passes.
- Complete article-layout and manual-editor scripts pass.
- A temporary complete manual-save artifact is accepted by the renderer.
- Final unified regression passes all 25 stages in 375.9 seconds.
- Visual before/after inspection found no overflow, overlap, or unexpected third line.
- External requests and production writes are zero.

## Next Action
Run one normal application flow or resume the failed checkpoint so the new S0199 page receives fixed-ID page Chinese, then inspect S0198 and S0199 in the editor before synthesis.

## Do Not Regress
- Never let same-screen line reflow change page count, page boundaries, parent or page IDs, English, Chinese, word spans, cue timing, or word timing.
- Never shrink a valid layout for an equal line break or retain an invalid legacy layout as v19.
- Never reuse an older page-layout cache as v19.

## Unknowns
- No fresh GUI run or video encode has validated the repaired checkpoint.
- The existing sequence planner changes adjacent S0198 from four pages to a denser three-page projection when S0199 becomes two pages; visual acceptance is not yet proven.
