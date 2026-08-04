# CODEX State
Status: Article-template structural-overflow rendering fix verified; awaiting main-window review.
Last verified: 2026-08-04 18:29:14 Asia/Shanghai
Branch: codex/e2e-caption-regression
Verified HEAD: 55850c4a520b09c23aba095b3bb4f16074faf1f8
Working tree: clean after this documentation checkpoint commits.

## Current Goal
Record the verified renderer fix without rerunning the full 11-minute production video.

## Confirmed Facts
- The article template previously discarded Chinese wrapped lines after the second line.
- Long structural-overflow cue S0004 now reduces Chinese display scale and renders all source characters.
- Offline real-cue PNG verification found no crop and zero English/Chinese alpha-mask overlap.

## Relevant Paths
- `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\overflow-fix-frame\S0004-fixed.png`
- `E:\VideoCaptioner-e2e-runs\ai-writing-style-full-e2e-20260804\overflow-fix-frame\validation-report.md`

## Last Verification
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`: PASS.
- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS.
- `git diff --check`: PASS.

## Next Action
Await main-window review before any further production rendering.

## Do Not Regress
- Keep structural English-overflow cue text, timing, IDs, and Chinese allocation frozen.
- Never silently truncate wrapped subtitle text in the article template.

## Unknowns
- The full 11-minute video has not been rerendered after this renderer-only fix.
