# Vocabulary Cards And Article Template: Main-Only Handoff

Status: ready_for_handoff
Last verified: 2026-08-28 03:21:24 Asia/Shanghai
Branch: main
Verified HEAD: 38aa4667f9a66c6fff3337006272cbecfbe90286
Working tree: modified, but the vocabulary renderer source and its main regression file are clean relative to HEAD
Next action: continue only in `E:\VideoCaptioner-screen-subtitle` on `main`; recheck Git status and the focused vocabulary diff before the next edit
Unknowns: no fresh end-to-end article-template video has been rendered after HEAD `38aa466`; current visual evidence is still the 2026-08-26 frame set

## Authoritative Workspace

- Use only `E:\VideoCaptioner-screen-subtitle`.
- The authoritative branch is `main`.
- Ignore old Codex/detached worktrees and the detached commit `b5dde66`.
- Do not reset, clean, stash, delete, or modify another worktree.
- The current `main` worktree contains unrelated audit/evidence changes and untracked probe files. Preserve them.
- At verification time, `app/core/utils/podcast_learning_video.py` and
  `tests/test_stable_caption_rules.py` were clean relative to `main@38aa466`.

## Scope

This owner is responsible for vocabulary-card selection data, scheduling,
article-template layout, text wrapping, title/card accents, rendering failures,
focused tests, and visual samples.

Do not change ASR, word timestamps, English subtitle segmentation, Chinese
translation, fixed subtitle IDs, final SRT/ASS/manifest ownership, or the video
synthesis entry point. In particular, do not modify the A1 pagination/degraded
render path in `podcast_learning_video.py`. Read its stable output only.

## Current Main Behavior

- `VOCAB_PROMPT_VERSION = 17`.
- Target density is `1.0` card per minute, clamped to 3-22 cards.
- Concept-detail cards are capped at 6 per episode.
- Candidate normalization records rejection reasons through
  `_reset_vocab_diagnostics()` and related helpers.
- `schedule_vocab_card_plan()` keeps priority 1-2 candidates off screen,
  deduplicates exact expressions, enforces the minimum interval, and distributes
  accepted cards across the timeline.
- A card starts only when its exact phrase is visible in the final article page.
  It remains until the next card; the final card remains through video end.
- The active article card is left aligned. At 1920x1080, the vertical rule has
  a 45px container gap, a 9px rendered width, and a 45px rule-to-content gap.
  The right content inset is also 45px.
- Card and opening-title rules are square-ended and follow visible glyph bounds.
- Chinese meaning/detail wrapping uses legal lexical boundaries. One-line text
  stays on one line; overflowing text prefers comma/semicolon boundaries when
  they fit and avoids stranding a very short tail.
- The old `docs/handoffs/2026-08-04-vocabulary-cards.md` contains stale values
  such as prompt version 16 and concept cap 3. Do not use those values over
  current code or `docs/CURRENT_STATE.md`.

## Entry Points

- Core: `app/core/utils/podcast_learning_video.py`
- Main functions: `_reset_vocab_diagnostics`, `normalize_vocab_plan`,
  `schedule_vocab_card_plan`, `wrap_article_vocab_meaning`,
  `wrap_article_vocab_detail_mixed_text`, `draw_article_vocab_card`,
  `draw_article_opening_topic_panel`
- Focused regression: `tests/test_stable_caption_rules.py`
- Current state: `docs/CURRENT_STATE.md`

## Current Visual Evidence

- `output/current-production-vocab-render-20260826/fixed-accent-and-detail-wrap-card.png`
- `output/current-production-vocab-render-20260826/fixed-accent-45px-glyph-aligned-card.png`
- `output/current-production-vocab-render-20260826/fixed-title-accent-45px-glyph-aligned.png`
- `output/current-production-vocab-render-20260826/right-margin-45px-long-detail-card.png`
- `output/current-production-vocab-render-20260826/right-margin-45px-title-card.png`

All five files existed at handoff time.

## Verification State

- `docs/CURRENT_STATE.md` records focused vocabulary/card-layout tests as passing.
- The broader stable-caption regression previously recorded 561 passing tests.
- The article readability contract currently records 109 passed and 1 unrelated
  S9522 fixture failure.
- No new full regression was run for this handoff because no source behavior was
  changed.

For the next vocabulary change, run the narrowest relevant tests first, render
at least one 1920x1080 sample from the current production renderer, then run
`git diff --check`. Run the full regression only when the change affects shared
subtitle/rendering contracts or another high-risk path.

## Important Git History

- `bb6ead1 Improve vocabulary card selection and wrapping` is already in main.
- `bd81005 chore: drop unverified manual pagination ranking experiment` is a
  later main commit and is outside vocabulary ownership.
- `38aa466 docs: update state after repository cleanup` is the verified handoff
  HEAD.
- Do not cherry-pick detached commit `b5dde66`; it was made from an obsolete
  detached baseline and is not the production continuation point.
