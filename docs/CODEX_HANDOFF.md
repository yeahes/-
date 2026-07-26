# Codex Handoff

Last updated: 2026-07-26

## Active Goal

Stabilize the English-learning subtitle production path without broad rewrites.

Production flow:

```text
word timestamps
-> deterministic English subtitle cutting
-> frozen global subtitle IDs
-> LLM full Chinese translation
-> LLM Chinese allocation by subtitle_id
-> validation and artifacts
-> stable-final SRT/ASS
-> video synthesis from stable-final-manifest.json
```

## Current Branch State

- Branch: `main`.
- The branch is ahead of `origin/main`.
- No `checkpoint-2026-07-23` tag or branch exists in this checkout.
- Use Git history directly instead of assuming that checkpoint name exists.

## Current Constraints

- Do not modify the original project under `D:\软件缓存\VideoCaptioner`.
- Work only in `E:\VideoCaptioner-screen-subtitle`.
- Do not let the LLM rewrite English subtitle text, order, IDs, or timing in stable mode.
- Do not re-enable candidate quality check for stable mode without a regression test.
- Do not delete spoken backchannels in stable mode.
- Avoid broad edits to `screen_editor.py`.

## Current Priority

The highest-priority production risk is structural consistency:

- English IDs and timing must remain frozen.
- Chinese must be written back by global `subtitle_id`.
- Missing, duplicate, unknown, or mismatched IDs must be surfaced as validation errors.
- Failed validation should preserve diagnostic artifacts and block renderable output.

