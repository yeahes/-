# Article Smart Vocabulary Cards Handoff

Last verified: 2026-08-04 00:10:44 Asia/Shanghai

## Scope And Entry Points

This handoff covers the optional smart vocabulary-card feature of the `文章单词`
podcast template. It is presentation-only: it must not modify the stable
subtitle pipeline's English text, IDs, cue order, word ledger, or timings.

| Responsibility | Current location |
| --- | --- |
| Video-template settings and title input | `app/view/video_synthesis_interface.py` |
| Persistent settings | `app/common/config.py` |
| Synthesis-task snapshot | `app/core/entities.py`, `app/core/task_factory.py` |
| Pass options into renderer | `app/thread/video_synthesis_thread.py` |
| Selection, scheduling, rendering, highlight logic | `app/core/utils/podcast_learning_video.py` |
| Regression coverage | `tests/test_stable_caption_rules.py` |

Enable `英语学习模板`, select `文章单词`, provide an optional template title and
cover, then enable `智能单词卡`. The task factory snapshots the choice into
`SynthesisConfig`, so an already created task does not change when the GUI
setting changes later.

## Confirmed Current Behavior

### Selection And Scheduling

- The renderer builds local semantic groups without changing subtitles. A group
  ends at terminal punctuation, a `0.7s` pause, six cues, or eighteen seconds.
- The model may select at most one exact source phrase per group. The phrase
  must be contiguous text from its triggering subtitle, contain at most eight
  English words, be at most 56 characters, and have a compact contextual
  Chinese gloss.
- Candidate priority `1-2` is discarded. The scheduler removes duplicate
  phrases, enforces a 15-second minimum interval, and caps concept cards at
  three. A card starts at the start time of the subtitle containing its phrase.
- Target count is `round(duration_minutes * 1.25)`, clamped to 3-22. This gives
  about 10 cards for eight minutes and 15 for twelve minutes; it is not a hard
  global 8-15 cap. The focused test expects 20 for a sixteen-minute episode.
- Cards are selected globally by priority, not in subtitle order. A generated
  run containing only three cards can be valid when only three candidates pass
  model and local filters, or when interval/deduplication filtering removes the
  rest.

### Card Content And Visual State

- The active article card renders the exact English phrase, a compact Chinese
  contextual gloss, and only for a `concept` card, one short Chinese concept
  explanation. It ignores phonetic, exam-level, part-of-speech, dictionary,
  and old `IN CONTEXT` fields.
- Standard-card `detail` is still technically supported as one short English
  collocation line when the model supplies it. Do not add an English dictionary
  definition. Audit real output before deciding whether all standard details
  should be suppressed.
- Before the first selected card, the right panel shows the episode title, not
  a word preview. The title scales/wraps to at most three lines and the left
  accent bar matches the rendered title block height.
- Only the first transition is animated: title panel -> brief empty container
  -> first full card over `0.25s`. Later cards replace the current full card
  directly. There is no active transition into a small review card.
- A full card remains visible from its trigger time until the next card starts;
  the last one remains visible through the end of the video. It is not limited
  to the duration of one subtitle or to 3.1 seconds.
- The article cover panel and active card panel share `#FBF6ED`
  (`ARTICLE_CARD_CONTAINER`). Subtitle and tip areas must not be recolored as a
  side effect.

### Subtitle Highlighting And Layout

- The selected phrase is highlighted in `ARTICLE_BLUE` in the English subtitle.
  Directly attached punctuation and closing brackets/quotes use the same color;
  following whitespace and later text do not.
- Highlighting works when the phrase crosses two display lines and does not add
  an underline. Renderer line wrapping is visual only and cannot change frozen
  subtitle boundaries.
- The article English subtitle area uses pixel-width wrapping and a second
  highlight-preserving wrap pass when two lines are needed. The Chinese article
  subtitle is rendered at 46px and may use two lines.

## Caching And Failure Behavior

- Per-subtitle cache: `<subtitle>.vocab_cards.json`; global cache:
  `CACHE_PATH/podcast_vocab_cards/<source_hash>.json`.
- A cache is accepted only when English source hash, `VOCAB_PROMPT_VERSION`
  (currently `16`), and configured model match. Scheduling is recalculated
  locally after a cache hit.
- A request has a 90-second timeout, no SDK retries, two explicit attempts per
  chunk, and a total generation budget of 240 seconds. Successful chunks survive
  a later chunk failure. An empty/invalid plan is not cached.
- When investigating stale or surprising choices, inspect or remove the two
  cache files for that subtitle before re-rendering; do not conclude that a
  prompt change ran merely because a video was rendered.

## Important Code/Documentation Mismatch

Current source and focused tests are authoritative over old descriptions:

- `vocab_card_display_state()` returns only `hidden` or `full`; it never emits
  a review state.
- `draw_article_frame()` calls the title panel before the first card and
  `draw_article_vocab_card()` thereafter. It does not call
  `draw_article_vocab_review_bar()`, `draw_article_vocab_overview()`, or
  `draw_article_vocab_placeholder()`.
- `podcast_learning_video.py` retains legacy review-bar, overview, placeholder,
  and old `IN CONTEXT` drawing helpers. They are not proof of active UI and
  should be deleted only with targeted tests and a visual render check.
- `build_vocab_selection_prompt()` still contains the stale phrase “随后缩为
  复习条”; remove or correct it before changing prompt semantics.
- `docs/CURRENT_STATE.md` still says a full card becomes a compact review state.
  Update it to match the active full-card-until-replacement behavior after the
  checkpoint is verified.

## Focused Regression Coverage

The following tests live in `tests/test_stable_caption_rules.py`:

- Selection integrity: exact source phrase, no larger-word match, no low-priority
  candidates, 15-second spacing, concept cap, frozen-group ownership, and
  duration-aware card target.
- Display integrity: full card survives until replacement, title panel before
  first card, first-card-only crossfade, and cached full-card frames remain
  stable.
- Content integrity: no rendered phonetic/level/POS/`IN CONTEXT`/dictionary
  definition, compact Chinese gloss normalization, and bounded concept detail.
- Highlight integrity: attached punctuation, no whitespace spill, cross-line
  phrase coverage, and no underline.
- Resilience: partial model-batch failure retains successful cards; empty cache
  regenerates instead of silently rendering no cards.

Verification recorded for this checkpoint: `runtime\python.exe
scripts\run_regression.py` and `git diff --check` both passed on 2026-08-04.
The audit's `222`, `777`, and `999` entries reported `MISSING` because those
local samples are absent, not because a test failed. Run the project-required
regression command again after any behavior change:

```powershell
E:\VideoCaptioner-screen-subtitle\runtime\python.exe scripts\run_regression.py
```

Run it with working directory `E:\VideoCaptioner-screen-subtitle`, then run
`git diff --check`. A fresh article-template render is still required to verify
actual typography, card density, and visual transitions for a real subtitle
file.

## Next Recommended Work

1. Run the regression and commit the current checkpoint only if it passes.
2. Render a fresh article-template sample with the smart-card switch enabled.
   Record selected card count, cache status, timestamps, screenshots, and
   whether all highlights match the visible source phrase.
3. Resolve the stale prompt and `docs/CURRENT_STATE.md` review-bar statements.
4. If the user wants a firm 8-15 limit for every episode, change the scheduler
   contract and test it explicitly; do not rely on the current density formula.
5. Do not reactivate the overview or compact review bar without a new user
   decision and visual acceptance test.
