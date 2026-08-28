# Article Smart Vocabulary Cards Handoff

Last verified: 2026-08-09 13:58:37 Asia/Shanghai

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
- Target count is `round(duration_minutes * 1.0)`, clamped to 3-22. A 15:12.8
  episode therefore targets 15 cards, and a sixteen-minute episode targets 16.
  This is a quality-preserving target, not permission to admit priority 1-2
  candidates.
- Eligible candidates are divided into equal timeline strata. The scheduler
  first chooses the strongest valid candidate in each occupied stratum, then
  fills any remaining budget by priority and distance. Empty strata remain
  empty rather than using a basic word to meet the target. A generated run with
  fewer cards is still valid when not enough candidates pass the model, local
  quality, duplicate, and interval filters.

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
- Resumable v2 progress is stored beside each formal cache as
  `<cache-stem>.v2.progress.json`. It records the English source hash,
  `VOCAB_PROMPT_VERSION` (currently `16`), configured model, stable request
  chunk order, completed chunk IDs, per-chunk cards, and a derived `complete`
  flag. Scheduling is always recalculated locally.
- Each request chunk has a content-derived stable ID. Chunks are requested in a
  timeline-balanced order: opening, ending, middle, then the intervening ranges.
  On resume, valid local and global progress is merged and only unfinished
  chunks are requested.
- A request has a 90-second timeout, no SDK retries, and two explicit attempts
  per chunk. There is no shorter global generation cutoff. Every successful
  chunk is atomically persisted, including a valid empty array. A cache is
  complete only when every current semantic-group chunk has been processed.
- Legacy prompt-v16 caches have no completion evidence and cannot authorize
  rendering while v2 progress is incomplete. Failed chunks raise
  `VocabularyPlanIncompleteError` after all successful chunks are saved; the
  next synthesis attempt requests only unfinished chunks. A complete v2 payload
  atomically replaces the per-subtitle and global formal caches. A complete
  zero-card result remains valid and does not add lower-quality words.
- When investigating stale or surprising choices, inspect both formal and v2
  progress caches. Do not delete them as a first-line repair and do not conclude
  that a prompt change ran merely because a video was rendered.

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
- `docs/CURRENT_STATE.md` now matches the active full-card-until-replacement
  behavior.

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
- Resilience: partial model-batch failure retains successful chunks but blocks
  rendering; later runs request only unfinished chunks; empty successful chunks
  count as complete; legacy caches cannot authorize an incomplete render;
  missing model configuration fails closed; FFmpeg is not started; atomic
  replacement failure preserves the prior file; and empty legacy caches
  regenerate.

Verification recorded for the completion gate: syntax compilation and all 29
focused vocabulary/cache/display tests passed on 2026-08-09; six directly cover
completion, resume, and the render gate. The unified
regression ran for 365.6 seconds and passed every stage except `stable caption
smoke tests`; its vocabulary smoke and video-synthesis safety stages passed.
The sole failing assertion was the unrelated, order-dependent
`test_whisperx_time_only_uses_explicit_source_audio_from_complete_task`, which
passed immediately in isolation. This handoff therefore does not claim a full
suite pass for the current dirty-worktree checkpoint.
Generated-output auditing now requires an explicit fresh `work-dir` sample and
is excluded from the project regression. Run the project-required regression
command again after any behavior change:

```powershell
E:\VideoCaptioner-screen-subtitle\runtime\python.exe scripts\run_regression.py
```

Run it with working directory `E:\VideoCaptioner-screen-subtitle`, then run
`git diff --check`. The current checkable frame is
`tests/caption_audit/out/vocab-complete-gate-sample-20260809.png`; its source
data is the production `中国AI为何更省钱？` subtitle, cover, and frozen legacy card
payload. The earlier offline
real-data schedule report is
`tests/caption_audit/out/vocab-card-schedule-report-20260809.json`. The explicitly
labeled target-versus-legacy timing diagram is
`tests/caption_audit/out/vocab-card-timeline-comparison-20260809.png`.

## Next Recommended Work

1. Run the regression and commit the current checkpoint only if it passes.
2. Render a fresh article-template sample with the smart-card switch enabled.
   Record selected card count, cache status, timestamps, screenshots, and
   whether all highlights match the visible source phrase.
3. Correct the stale review-bar phrase in the selection prompt only with an
   explicit prompt-version bump; the current display behavior is already
   documented accurately.
4. If the user wants a firm 8-15 limit for every episode, change the scheduler
   contract and test it explicitly; do not rely on the current density formula.
5. Do not reactivate the overview or compact review bar without a new user
   decision and visual acceptance test.

## 2026-08-09 English-Only Synthesis Variant

- The synthesis page adds a persisted `仅英文字幕` action beside the smart-card
  action. It is visible only while the English learning template is active.
- `SynthesisConfig.podcast_template_english_only` freezes the selection at task
  creation. The renderer receives it as an explicit `english_only` argument;
  style and data ownership remain separate.
- The renderer skips only the bottom Chinese subtitle. It preserves `Cue.zh`
  for article-page measurement and preserves every vocabulary-card field,
  including the Chinese gloss and concept explanation.
- Bilingual and English-only jobs use distinct output names for article-word,
  dark-podcast, and manual-draft variants, preventing the second manual run from
  overwriting the first.
- Both variants use the existing completed vocabulary cache contract. The
  toggle does not alter vocabulary selection or the cache key, and an incomplete
  plan still blocks before FFmpeg.
- Focused configuration, filename, UI-handler, renderer-region, and frozen-task
  tests pass. The 25-stage unified regression also passes. Visual evidence is in
  `tests/caption_audit/out/*english-only*20260809.png`.

## 2026-08-10 Final-Page Card Alignment And Opening Title

- The synthesis page title control is now a two-line plain-text editor. A user
  can insert the desired title break directly; the exact newline is persisted
  and frozen into the synthesis task. Single-line titles still use automatic
  tokenizer-backed wrapping.
- Article-template card timing is resolved after the frozen display-page plan.
  The card starts at the first instant of the one final page containing its
  exact source phrase, rather than at the parent cue start. Cross-page and
  ambiguous matches are dropped. The dark template remains cue-aligned.
- Card selection, density, cache identity, prompt version, and last-card hold
  behavior are unchanged.
- The opening title uses tokenizer-backed lexical boundaries and balanced line
  widths. Explicit newlines are retained. The observed title now renders as
  `中国年轻人为何 / 不爱留学了？`, never `中国年轻人为 / 何不爱留学了？`.
- Chinese title weight moves from bundled Bold to bundled Heavy without
  changing the title panel's maximum size, maximum three lines, or safe width.
- Focused alignment and title tests, the complete stable-caption script, and
  all 25 unified regression stages pass. Checkable output:
  `tests/caption_audit/out/study-abroad-title-wrap-heavy-20260810.png`. The
  synthesis-page input sample is
  `tests/caption_audit/out/synthesis-multiline-title-input-20260810.png`.
