# Current State

Last verified: 2026-08-28 19:17:31 Asia/Shanghai

## Current Goal

Keep only low-risk, high-payoff work: use the committed local retry for the
current page blocker, then measure one fresh unreviewed audio run. A retry must
resume from the failed display-page
stage without rebuilding frozen English, parent Chinese, fixed IDs, the word
ledger, WhisperX alignment, or the final cue timeline.

## Current Production Contracts

- Stable English text, subtitle IDs, word ownership, and final timing are local
  and deterministic. An LLM cannot rewrite them.
- There is one authoritative word ledger. Final cue timing must cover its word
  envelope and remain ID-addressable through SRT, ASS, page artifacts, and
  synthesis.
- Chinese translation may use an LLM, but it maps to frozen parent IDs and,
  after final timing, to deterministic display-page IDs.
- A failed provider request, missing page Chinese, invalid page contract, or
  unresolved active ASR gap remains blocked and produces a recoverable
  checkpoint. Incomplete output is not publishable.
- Manual-final packages and immutable stable runs are isolated. A new run must
  not inherit review queues, caches, or manual edits by numeric subtitle ID.
- Automatic pagination may reject a relative-clause entrance when frozen syntax
  evidence shows a later finite predicate still depends on the previous-page
  noun. Complete relative clauses such as `professors | who have ...` remain
  reviewable and selectable; English text, IDs, word timing, and parent Chinese
  are unchanged.

## Verified Results

- ASR active-gap repair: the confirmed White House gap was repaired by a
  bounded local retranscription with exact left/right text anchors and timing
  fitted back into the authoritative gap. Unanchored results do not mutate the
  transcript and are reported as blockers.
- ASR trust contract: `tests/test_asr_trust_contract.py` passed 45 tests.
- Stable publication contract: `tests/test_stable_publication.py` passed 101
  tests. Final cue timeline tests pass.
- Focused mechanism verification is green: frozen-parent resume/publication 111
  tests, selected-service translation audit 14 tests, parent translation rules
  561 tests, display-page translation 76 tests, and offline measurements 3
  tests. Full regression is intentionally not rerun during this cleanup.
- Direct CUDA Faster-Whisper probe of the current desktop audio completed with
  return code 0 and produced an SRT. The same SRT produced zero unresolved
  internal-gap candidates under the current gap detector.
- User completed a full GUI run after the ASR repair and reported no failure.
  This is a real-workflow confirmation of the ASR path, separate from the
  focused automated tests.
- Translation prompt identities are `semantic-full-translation-v8`,
  `semantic-allocation-v5`, and `display-page-translation-v10`. Old caches are
  not silently reused under these identities.
- Failed stable checkpoints retain a visible retry entry. Retry restores the
  original input/context and preserves completed cache entries.
- Stable retry now records a hash-verified `frozen_parent_timeline` checkpoint
  immediately before display-page translation. A compatible retry validates
  the frozen English, IDs, word spans, word ledger, parent Chinese, semantic
  groups, source-segment coverage, boundary evidence, and final timeline before
  skipping stable editing and WhisperX. Display-page artifacts are deliberately
  excluded so only the failed downstream stage is retried.
- The existing unreviewed `中国职场女性为何悄然掉队？` failure was restored
  read-only from its editable checkpoint: 271 fixed IDs, 2855 words, 245
  semantic groups, 2845 source segments, and 271 PASS timeline records. All 44
  checkpoint file hashes were unchanged after restore.
- Retry UI reset now clears both the progress value and the qfluentwidgets error
  state. The frozen-checkpoint stage remains at 96% so downstream page and audit
  progress can still advance normally.
- `恢复最近字幕` now follows hash-verified subtitle paths from a stable run to
  the owning `*-处理结果/人工终稿字幕包`, so a newer saved manual final is not
  hidden by an older work-dir draft. A draft still wins when it is genuinely
  newer. The real White House package loaded 199 cues directly without ASR,
  translation, pagination, or writes to the package.
- Focused page-retry verification passes 11 tests. The committed local retry
  caches each valid parent independently, so a later retry requests only the
  failed parent and merges the successful pages unchanged. The current unreviewed
  `中国企业正把供应链铺满全球` checkpoint remains `ERROR` at 53/55 pages:
  `S0136.P01/P02` are missing and `S0260` places the negation on P02. Four
  OpenCode retries were rejected by existing semantic/lexical validators. A
  read-only 55-page candidate passes renderer application but leaves the
  S0260 page meaning for manual confirmation; the checkpoint is unchanged.
- Manual-final save handles proven orphan display plans after parent merges;
  unexplained orphan plans remain hard failures.
- Offline readability verification: 108/109 article display contract tests pass.
  The remaining S9522 fixture still expects `into` while the current planner
  selects `in`; this predates the relative-clause boundary fix and remains a
  separate pagination-quality item.
- Vocabulary card production update: prompt version is 17, the per-episode
  concept-detail cap is 6, candidate normalization records rejection reasons,
  and article cards use semantic two-line detail wrapping plus the title-card
  blue vertical accent. Focused vocabulary tests pass; old prompt-version 16
  caches are intentionally invalidated.
- Vocabulary card visual follow-up: the accent is now 6px wide, sits farther
  from the content, and is vertically inset from the text block. Mixed Chinese
  explanations rank balanced lines with a slightly longer second line before
  semantic tie-breakers. Focused card/layout tests pass; a 1920x1080 sample is
  `output/current-production-vocab-render-20260826/fixed-accent-and-detail-wrap-card.png`.
- The next accent pass uses a 45px container-to-line gap, a 9px rendered line,
  and a 45px line-to-content gap at 1080p. The line is square-ended and its
  vertical span follows visible glyph bounds rather than layout-group bounds.
  Sample: `output/current-production-vocab-render-20260826/fixed-accent-45px-glyph-aligned-card.png`.
- Opening title cards now use the same accent geometry and visible-glyph height
  rule. Chinese detail wrapping keeps deterministic lexical boundaries; visual
  balance is optimized only among legal breaks, so a word such as `造成` is not
  split merely to make two lines equal. Samples:
  `output/current-production-vocab-render-20260826/fixed-title-accent-45px-glyph-aligned.png`
  and `output/current-production-vocab-render-20260826/fixed-accent-45px-glyph-aligned-card.png`.
- The active article card content width now uses the same actual `45px` inset
  on both the left-side content rule and the right container edge at 1080p.
  Chinese explanations remain one line when they fit; when they overflow and a
  comma/semicolon boundary is available, that punctuation boundary is preferred
  before other legal lexical breaks.
- The article cover, vocabulary-card, and subtitle panels now composite their
  bundled container textures (`封面容器.png`, `单词卡容器.png`, and `字幕区背景.png`)
  at 40% opacity inside their existing rounded 1080p frames. The fallback flat
  panels remain underneath, and each asset is clipped before foreground content
  is drawn. The shared panel shadow uses `alpha=22` and a 16px Gaussian blur to
  retain edge contrast against the light textures. Focused background/layout tests
  pass; sample: `output/current-hd-render-20260828/current-layout-neutral-texture-40.png`.
- The production changes are split into mechanism-scoped commits through
  `b1ae687`; the unverified page-selection experiment was removed. Remaining
  uncommitted changes are historical audit/state updates and generated evidence.

## Known Risks And Unknowns

- The ASR repair has now passed a user-run full GUI workflow. Future failures
  should be diagnosed from their exact stage and error text rather than
  reopening the already-confirmed S0141 gap fix.
- The direct ASR probe succeeded; if the GUI still fails, inspect the detailed
  error for word alignment, stable publication, provider, or cache-contract
  failure rather than assuming the ASR executable failed.
- The current working tree contains many pre-existing source, audit, and
  generated-artifact modifications. Do not restore or clean them blindly.
- The 90–95% automation target is not verified by the existing stressed runs;
  old manually corrected packages are evidence for offline comparison only.
- The latest 73-page replay remains historical evidence only. The active
  unreviewed checkpoint has 55 expected pages and the two page-local issues
  recorded above; Chinese fluency and long-caption quality still require a
  fresh unreviewed run after the blocker is handled.
- The S9522 readability fixture now matches the current planner: the balanced
  two-page projection keeps `into ... engine` on P01 and starts P02 at `in`.
  Its focused regression passes; no production pagination code changed.
- G1 failure localization is implemented. A renderable review fallback is now
  recorded as `degraded_page_count` instead of an episode-level error; a real
  non-renderable parent or an exceeded degraded threshold still blocks.
- The G1 blueprint now reports `total_parent_count`,
  `degraded_parent_ratio`, and a named 2% threshold on both PASS and ERROR
  artifacts. The threshold uses `floor(total_parent_count * 0.02)` with a
  minimum of one reviewable degraded parent for small unit inputs.
- Before synthesis, each degraded parent is written as one JSONL row under the
  stable artifact directory at `degraded-review-checklist.jsonl`, including
  page IDs, page English/Chinese, and the degradation reason.
- Read-only replay of checkpoint
  `20260826T040659.244182-79951e43` produced `status=PASS`,
  `degraded_page_count=1`, and only `S0089` degraded. It preserved all 306
  page plans outside S0089 byte-for-byte at the page-signature level. The
  translated page cache validated `PASS` with 0 errors; a temporary QA replay
  produced 76 review items and 9 semantic-review items.
- Translation quality audit now follows the selected LLM service configuration
  instead of always using OpenCode Go. Audit cache entries are stored under a
  service-scoped namespace, and the audit manifest records the service/model
  used. The audit remains read-only and does not change subtitles, IDs, or
  timing. When display-page projection fails, the production failure path now
  explicitly opts into auditing the fixed parent English/Chinese rows instead
  of silently skipping the audit; the page failure remains a render blocker.
- OpenCode Zen/Go and TokenRhythm requests now pass through
  `app/core/llm_client.py`. The adapter disables their default hidden
  reasoning (`reasoning_effort=none` for OpenCode,
  `thinking.type=disabled` for TokenRhythm) and supplies a reliable
  `max_completion_tokens=8192` when a stage omitted an output budget or used
  legacy `max_tokens`. DeepSeek and other providers keep their original request
  parameters. Live replays of the 6,717-character humanoid-robot article
  returned valid analysis JSON in about 10 seconds (OpenCode) and 19 seconds
  (TokenRhythm); the same request previously timed out or returned an empty
  length-limited completion on those gateways.
- §46.48 whole-parent-Chinese display flag is wired at the article renderer's
  page-text selection point. `PODCAST_ARTICLE_WHOLE_PARENT_CHINESE` defaults to
  `False`, so stable output remains unchanged unless explicitly enabled. With
  the flag enabled, only multi-page parents display their complete parent
  Chinese on each frozen English page; English, IDs, word spans, timing,
  page plans, and subtitle artifacts remain unchanged. Read-only validation
  against stable run `20260828T032249.733500-9602f073` covered 17 multi-page
  parents and 37 pages; focused tests passed.
- Same-screen line wrapping now rejects a severe two-line width imbalance when
  the measured shorter/longer line pixel ratio is below `0.48`. The caller
  receives no layout so the frozen-page planner can select another
  already-enumerated projection or emit an explicit structural-overflow review
  seed. This preserves parent English, IDs, word spans, timing, and page
  Chinese. Regression coverage for the originating cases `S0006`, `S0063`, and
  `S0088` passes; the same-layer focused set passes 18 tests.
- A read-only stressed audit of the fresh checkpoint
  `work-dir/人工智能会产生自我意识吗？/subtitle/stable-checkpoints/20260828T124923.879908-6e68f0d2`
  is identity-bound (`content=PASS`) but formally `ERROR` and not publishable:
  187 parents, 219 actual pages, 32 multipage parents, and 43 selected stressed
  parents covering 75 pages. `S0098` and `S0116` have no complete normal-font
  page partition; `S0100` is missing `S0100.P01/P02` page translations. These
  are display-stage blockers, not evidence to change the frozen timeline.
- Offline re-planning of the current v33 word ledger removes the three severe
  imbalance pages observed in the prior manual package (`S0006.P01`,
  `S0088.P02`, `S0063.P02`) for the tested inputs. The old artifact itself was
  not rewritten: it remains 219 pages with 3 severe pages, 24 pages below the
  `0.60` ratio, and 58 below `0.72`. Historical v19 automatic results show the
  same class of defect (16 and 21 severe pages in two episodes), so this is a
  general display-layer issue rather than an ID-specific exception. The
  evidence is targeted/offline and does not establish a new end-to-end rate.
- Manual-final synthesis now applies the frozen-page same-screen reflow to both
  `PASS` display-page artifacts and `REVIEW` manual-draft artifacts when
  `allow_manual_draft=True`. It can update only page-local English lines,
  rendered font size, and measured width; page word ranges, page IDs, page
  Chinese, parent English/Chinese, and page timing remain unchanged. The
  default stable path keeps the reflow opt-in.
- A local synthesis of the latest manual-final package completed after the
  `ea226cc` source checkpoint. The 1920x1080 MP4 is 11:46.10 and four sampled
  pages (`S0006`, `S0013`, `S0063`, `S0088`) show the expected balanced English
  wraps; AI vocabulary cards were disabled, so no API call was made.
- Manual-final reload now falls back to the existing same-screen typography
  reflow when an unchanged user-owned page range is rejected only by the newer
  imbalance guard. The fallback preserves page IDs, word ranges, page Chinese,
  and timing. The desktop package reloads `S0006.P01/P02` as usable pages and
  its render contract saves successfully; focused editor tests pass.

## Merged Status And Handoff

The former `docs/CURRENT_STATUS.md` and `docs/CODEX_HANDOFF.md` are preserved
under `docs/archive/2026-08-26/d1-merged/`; their current, non-conflicting
conclusions are merged here.

- Stable production flows from ASR word timestamps through deterministic English
  cuts, frozen IDs and word spans, ID-addressed Chinese translation/allocation,
  local validation, final cue timing, SRT/ASS export, and synthesis.
- Stable English, subtitle IDs, order, word ownership, and final timing remain
  immutable after freezing. Chinese may use an LLM only within fixed IDs.
- ERROR blocks publishable stable output; WARNING/INFO remain diagnostic. Manual
  finals and immutable stable runs remain isolated from one another.
- Current state is the newer 2026-08-26 retry/replay state above. Historical
  handoff decisions remain evidence, not authority over current code or output.

## Superseded Archived Conclusions

- `docs/CURRENT_STATUS.md` reported only 2026-07-26 smoke/syntax results and
  unresolved validation questions; the newer 2026-08-26 state supersedes them.
- `docs/CODEX_HANDOFF.md` recorded verified HEAD `bafd5d72...` and an older
  regression baseline; the current root state records `f00edc4` and supersedes
  that identity and baseline.
- `docs/CODEX_STATE.md` was only a compatibility pointer to the root state; the
  root `CODEX_STATE.md` remains the single retained same-name entry.

## Historical Archive

The former append-only state log is preserved at
`docs/archive/2026-08-25/CURRENT_STATE-history.md`. Superseded unreferenced
planning/baseline notes from the same cleanup are in that directory as well.
Historical task rounds are preserved one per file under
`tasks/archive/stable-subtitle-production-v1-log/`; `tasks/active/` keeps the
newest round and the short current-state summary.

## Next Action

Keep the new same-screen imbalance guard and the whole-parent-Chinese flag
disabled by default. Do not publish checkpoint
`20260828T124923.879908-6e68f0d2`; the next action is to reopen the current
desktop manual package, verify the corrected page-mode editor visually, and
save or synthesize from that package if the UI is clean. No audio rerun or API
call is needed for this fix.
