# Current Subtitle Segmentation, Translation, And Pagination Context

Status: verified background reference
Last verified: 2026-08-22 03:07:28 Asia/Shanghai
Verified HEAD: bb6b4be8a88ab013d0275609c81ef5c539d2a478
Working tree: includes uncommitted production, test, and documentation changes

## Purpose

Use this file as the short entry point before revisiting historical subtitle
cutting, Chinese translation, or display pagination. It records the currently
effective contracts, not every chronological implementation detail. Current
code, reproducible artifacts, and tests override this reference if they drift.

## Authoritative Data Flow

```text
authoritative word ledger
-> local deterministic parent-English segmentation
-> frozen parent subtitle IDs and word spans
-> complete semantic-group Chinese translation
-> Chinese allocation to exact frozen parent IDs
-> deterministic final display-page plan
-> Chinese projection to exact display-page IDs
-> editor review and frozen publication
-> renderer consumes the frozen plan
```

## Parent-English Segmentation

- Stable English segmentation is local, deterministic, timestamp-based, and
  completed before subtitle IDs are assigned. An LLM cannot own English text,
  order, boundaries, IDs, word ownership, or timing.
- The normal parent-cue maximum is 16 words. A 17-19 word exception is valid
  only when parser-backed evidence proves that every normal-limit cut creates
  an incomplete grammatical unit. A complete sentence with no legal temporal
  cut remains intact for renderer pagination instead of being forced apart.
- The 12-word/68-character visual target and final rendered width are renderer
  concerns. They must not create or move a formal parent-subtitle boundary.
- Pauses support a boundary but do not legalize a split complement, dangling
  auxiliary, unfinished subordinate clause, relative-clause entrance, or
  subject/predicate fragment by themselves.
- Historical visual-budget temporal splitting created many bad formal cuts and
  was removed from the production path on 2026-08-04. Reintroducing a 56px
  capacity trigger at the parent-segmentation layer would repeat that failure.

## Chinese Translation And Fixed-ID Allocation

- Current complete-translation contract:
  `semantic-full-translation-v7`. It translates a complete semantic group,
  receives up to two preceding and two following groups as read-only context,
  and receives duration-derived soft Chinese reading budgets.
- The complete group translation is the authoritative parent meaning. It must
  preserve facts, entities, numbers, negation, contrast, condition, modality,
  causality, reactions, hedges, and speaker stance while removing only
  meaning-free spoken scaffolding and English-shaped wording.
- Current parent allocation contract: `semantic-allocation-v4`. It maps the
  authoritative group translation to the exact frozen subtitle-ID set. It may
  lightly adapt Chinese order for natural reading, but cannot move later facts
  earlier, duplicate information, omit IDs, or replace the English partition.
- A one-cue semantic group writes its authoritative full translation directly
  to its sole ID. Multi-ID groups must pass ID-set, source, information,
  entity, number, negation, continuity, and fragment validation.
- Model selection is provider-specific. OpenCode Go currently defaults all
  three Chinese stages to `deepseek-v4-flash`; other providers may keep a
  stronger complete-translation model and use Flash for allocation. Model and
  prompt versions are part of cache identity.

## Display Pagination And Page Chinese

- Current page planner: `article-fixed-font-pages-v29`. It only partitions one
  frozen parent word span; it cannot change parent English, ID, timing, word
  ownership, or authoritative parent Chinese.
- New automatic pages use 56/54/52px, at most two English lines, measured pixel
  width, word load, duration, pause, syntax risk, balance, and neighboring-page
  pressure. A legacy frozen 50px page remains compatibility-only.
- Word counts are planning signals, not authority: 12 words is preferred, up
  to 14 is comfortable, 15 triggers observation, and over 16 increases pressure.
  A measured page can remain longer when it fits and safer alternatives would
  create worse boundaries.
- Page count is selected from visual and reading load before boundary rewards
  rank cuts within that count. A bounded cross-page-count pass may replace the
  baseline only with an already-enumerated, validated, objectively dominant
  candidate. It cannot invent a cut or relax non-overridable lexical atoms.
- If no complete normal-font partition exists, the planner fails closed with
  an editable seed. Manual review may then choose a timed-word proposal; it may
  not lose, duplicate, reorder, or synthesize words.
- Current page-Chinese contract: `display-page-translation-v8`. Page Chinese is
  a display-only projection of the authoritative parent Chinese, mapped to
  exact `Sxxxx.Pxx` IDs after page spans freeze. It may minimally reorder the
  existing parent meaning for synchronization, but cannot retranslate from
  English, add concepts, reveal later-page information early, duplicate facts,
  split a Chinese token, or overwrite the parent translation.
- The renderer, editor, manual save, and synthesis must consume the same frozen
  whole-episode page plan. Runtime replanning is a contract violation.

## Current Engineering Conclusion

- The three-stage ownership model is structurally correct and should not be
  redesigned. Remaining quality loss is concentrated in candidate ranking,
  incomplete parser evidence, Chinese allocation/projection quality, and noisy
  review classification rather than missing layer separation.
- A yellow mark is useful when it identifies a genuinely ambiguous long-cue
  boundary or mapping. Merely non-optimal but watchable pages should not be
  forced to change or promoted into review noise.
- `S0018`-class subject/predicate breaks are high-value defects. `S0001`-class
  awkward continuation starts deserve candidate comparison. `S0004`-class
  boundaries may justify review but are not automatically errors. `S0058` and
  `S0062` are accepted as usable but non-optimal and should remain unchanged
  unless an equal-page-count, 56px, lower-risk candidate is objectively better.
- The next quality investigation should compare all long-parent selected plans
  against their same-page-count and bounded frontier alternatives. It should
  adjust shared ranking or review evidence only when multiple real examples
  prove one invariant; sample IDs and audio titles must never enter production
  rules.

## Mature Standards And Reference-Video Comparison

The percentages below are engineering similarity estimates, not a vendor
benchmark. The burned reference reveals output style but not its authoring tool
or internal workflow.

- Netflix's current U.S. English timed-text guide specifies 42 characters per
  line, at most two lines, adult reading speed up to 20 characters per second,
  and linguistic line breaks. It explicitly avoids separating article+noun,
  adjective+noun, first+last name, subject pronoun+verb, prepositional
  verb+preposition, and auxiliary/negation+verb units.
- TED's current subtitling tips require subtitles over 42 characters to break
  into two lines, never more than two lines, balanced line lengths, preserved
  linguistic wholes, and at most 21 characters per second.
- Subtitle Edit's current long-line workflow exposes configurable maximum
  length and line count with live preview. Its implementation ranks punctuation,
  language-specific legal breaks, pixel width, line balance, and whole-sentence
  redistribution. It remains a human-in-the-loop editor rather than claiming a
  universally correct automatic semantic split.
- These mature baselines and this project's policy are approximately 85%-90%
  similar in principle: two-line maximum, measured reading load, punctuation
  preference, protected linguistic units, explicit review, and human correction
  for ambiguous cases. The project is more specialized because it must preserve
  bilingual fixed IDs, a word ledger, parent/page Chinese ownership, editable
  checkpoints, and one synthesis authority.
- The first three minutes of `sexual repression` contain 60 observed burned
  pages: 5-14 words, 9.28 mean words, one or two English lines, and nine pages
  under two seconds. It closely matches mature manual subtitle presentation,
  but contains a few hanging cuts and short pages, so it is a strong style
  reference rather than a perfect formal boundary reference.
- Latest v29 Chocolate has 254 pages, 9.15 mean words, at most two lines, and
  247 pages at 56px. It has 21 pages over 14 words, five over 16, 64 under two
  seconds, and 19 under 900ms; the artifact is blocked by two unrenderable
  parents and two missing page translations.
- Latest v29 White House passes its page contract with 261 pages, 9.36 mean
  words, at most two lines, and 257 pages at 56px. It has 18 pages over 14
  words, three over 16, 57 under two seconds, and 11 under 900ms.
- Current v29 output is therefore about 90% similar to the reference in average
  visual density and typography, but about 75%-85% similar overall after long
  tails, rapid source-owned reaction cues, page-boundary quality, Chinese
  compression, and review noise are included. The main gap is consistency at
  the tail, not the average page.

External evidence checked on 2026-08-22:

- https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide
- https://www.ted.com/participate/translate/subtitling-tips
- https://github.com/SubtitleEdit/subtitleedit/blob/main/docs/features/split-break-long-lines.md
- https://github.com/SubtitleEdit/subtitleedit/blob/main/src/libse/Common/TextSplit.cs

## Primary Evidence

- `docs/SUBTITLE_RULES.md`
- `docs/PIPELINE.md`
- `docs/CURRENT_STATE.md`
- `tasks/active/stable-subtitle-production-v1-log.md`
- `tasks/active/manual-long-caption-workspace.md`
- `app/core/subtitle_processor/screen_editor.py`
- `app/core/subtitle_processor/stable_display_page_contract.py`
- `app/core/utils/podcast_learning_video.py`
- `tests/test_stable_caption_rules.py`
- `tests/test_stable_page_translation_contract.py`
- `tests/test_article_display_readability_contract.py`
