# Project State
Status: complete
Last verified: 2026-08-10 08:14:02 Asia/Shanghai
Branch: main
Verified HEAD: 6b6a1e9da8725c2e51dec27c9639209d529b6249
Working tree: clean after the stable bilingual workflow checkpoint commit

## Current Goal
Improve same-screen English line breaks and font selection without changing any frozen subtitle or page contract.

## Confirmed Facts
- Contract v19 runs only after page spans, IDs, Chinese, and timing are frozen.
- Read-only replay checked 253 parents, 311 pages, and 311 saved page edits; every structural field had zero changes.
- Exact renderer validation exposed three invalid retained v18 wraps at S0065.P01, S0185.P01, and S0223.P01.
- The accepted v19 font counts are 56/54/52/50 = 297/6/5/3. Invalid legacy wraps cannot be retained merely to preserve a larger font.
- All 15 source-package files retained their SHA-256; no production package or video was regenerated.

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
Review the current encoded video, then decide whether unsafe 50px line wraps should trigger upstream visual replanning before page contracts are frozen.

## Do Not Regress
- Never let same-screen line reflow change page count, page boundaries, parent or page IDs, English, Chinese, word spans, cue timing, or word timing.
- Never shrink a valid layout for an equal line break or retain an invalid legacy layout as v19.
- Never reuse an older page-layout cache as v19.

## Unknowns
- No fresh GUI run or video encode has validated the v19 page artifact.
- Reliability on a completely unrelated blind audio remains unmeasured.
