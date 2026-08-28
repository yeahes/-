# Interactive Review And Result Directory Handoff

Status: complete
Last verified: 2026-08-09 18:43:45 Asia/Shanghai
Branch: main
Verified HEAD: 6b6a1e9da8725c2e51dec27c9639209d529b6249
Working tree: modified with substantial pre-existing and concurrent changes

## Outcome

- Interactive Home processing stops in the subtitle editor after subtitle
  generation. Synthesis starts only from the explicit formal or draft action.
- Batch full-process tasks retain automatic subtitle-to-synthesis chaining.
- New user-facing subtitle exports, QA files, summaries, manual-final packages,
  compatibility SRT, and formal/draft videos share
  `<output-anchor-parent>/<source-media-stem>-处理结果/`.
- Existing loose files, source media, internal work-dir artifacts, stable IDs,
  English, Chinese, page geometry, and timing are not changed by this contract.

## Verification

- Task context: 5/5 passed.
- Stable publication/UI: 53/53 passed.
- Manual-final editor and video-synthesis safety scripts passed.
- Unified regression: 25/25 stages passed in 330.3 seconds, exit code 0.
- External requests, ASR, LLM, real synthesis, and paid requests: zero.

## Remaining Check

Restart the production app and observe one fresh interactive run. The current
code path is regression-verified, but no fresh production GUI run was started.
