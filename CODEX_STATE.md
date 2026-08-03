# CODEX State

Status: stable English boundary routing and renderer-owned structural-overflow
checkpoint verified by focused regression; fresh end-to-end production and
article-template visual validation are pending.

Last verified: 2026-08-04 03:47:18 Asia/Shanghai

Branch: main

Verified HEAD: b5fe576345fbd82b3accc57b5d61fe40f597bd52
The current working-tree checkpoint was verified against this HEAD; all
implementation, test, and documentation changes listed below remain unstaged.

Working tree: modified in tracked implementation, documentation, and test
files listed by `git status --short`, plus the active cross-module issue list.
The auxiliary vocabulary handoff is committed at
`docs/handoffs/2026-08-04-vocabulary-cards.md`; `docs/CODEX_STATE.md` is a
compatibility pointer to this canonical root file.

Next action: rerun the focused and unified regression after the baseline fixes,
then wait for explicit confirmation before committing.

Unknowns: no fresh unseen-audio production render has been completed after the
latest stable boundary and fixed-ID allocation changes.

## Verified Contract

```text
ASR word timestamps
-> deterministic local English boundaries
-> freeze English text, word spans, order, and subtitle IDs
-> LLM Chinese full translation and fixed-ID allocation
-> local validation and artifacts
-> final cue timeline derived from the frozen word ledger
-> SRT/ASS export and synthesis
```

- Stable-mode LLM work is restricted to Chinese. It must not alter English,
  subtitle IDs, order, cue count, word ownership, or cue timing.
- Stable screen mode rejects an absent or incomplete source-to-word mapping;
  it cannot fall back to the legacy LLM screen-editor path. Likewise, its
  legacy `need_optimize` setting cannot activate `SubtitleOptimizer`.
- Final cue timing is ID-addressable and derived from frozen cue word ranges in
  the authoritative word ledger. Final-timeline validation blocks synthesis on
  structural errors.
- English boundary finalization is local and deterministic. Its production
  stages are ordered by `stable_english_boundaries.py`; no dynamic programming
  or audio-specific text rules are permitted.
- If a complete terminal source sentence has no legal normal-limit pre-ID
  boundary, it remains renderer-owned and is audited as a structural overflow;
  the cutter never creates an incomplete 17-19 word cue merely to satisfy the
  normal word limit.
- Allocation retry/compression/polish candidates are accepted only by the
  fixed-ID local quality comparator. A candidate with no high-confidence repair
  or with a detected regression keeps the original allocation.
- `stable-ts` is the default alignment backend. `whisperx-time-only` updates
  frozen word timing only and falls back to stable timing when the frozen-ledger
  mapping is incomplete or unavailable.

## Verified Implementation

- Stable artifacts, frozen pipeline hashes, final cue timeline, allocation
  quality policy, English-boundary stage facade, durable run state, review
  marks, and manual-final subtitle editing are present as separate modules.
- The subtitle editor remains the orchestration layer. It is still large and
  coupled; future work should extend the extracted contract/artifact/timeline
  modules where possible rather than broadly refactoring the editor.
- Run-state reuse is intentionally narrow: only verified article context and
  corrected-ASR artifacts with matching fingerprints and digests may be reused.
  Incomplete in-memory translation/allocation/final-output state is not resumed.

## Optional Article Vocabulary Cards

- The `文章单词` template is presentation-only. Its phrase selection, scheduling,
  cache handling, frame rendering, and English highlight logic are confined to
  the video-template path and do not write stable English boundaries, IDs,
  cue order, word ownership, or final timing.
- Current code keeps the active full card until a later card replaces it; before
  the first card it displays the episode-title panel. Cache validity includes
  source hash, model, and `VOCAB_PROMPT_VERSION`.
- Focused card behavior is exercised by the unified regression. Legacy review
  bar, overview, and placeholder drawing helpers remain in the renderer but
  are not evidence of the active card state.

## Verification Evidence

- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS on the current
  implementation checkpoint. It ran final timeline, stable-cut, boundary,
  allocation, artifact, frozen-run, golden-evaluation, manual-editor, review
  queue, run-state, and syntax checks.
- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS after the
  renderer-owned structural-overflow change.
- `git diff --check`: PASS after the implementation checkpoint. The observed
  LF/CRLF messages are line-ending notices, not whitespace errors.
- `tests/test_stable_caption_rules.py`: PASS after the renderer-owned
  structural-overflow regression and frozen-ledger replay.
- Generated-output auditing is intentionally excluded from the unified
  regression. It requires an explicit, fresh `work-dir` sample and is not a
  substitute for the fixture-backed contract checks.

## Unknowns

- No fresh full ASR -> alignment -> translation/allocation -> export -> render
  run has been completed after the latest pre-ID candidate-write gate, parser
  mapping, and numeric-result boundary changes.
- Existing `work-dir` SRT/ASS/video artifacts may predate the current code;
  use their manifest hashes and timestamps before treating them as evidence.
- Automated checks establish contracts, not general ASR accuracy, Chinese
  fluency, or timing quality on unseen audio.
- External LLM/API availability and WhisperX runtime behavior require a real
  run in the active environment to validate cache, fallback, and latency.
- The article-card renderer has no fresh visual render evidence after its latest
  UI changes. Typography, perceived density, and first-card transition require
  review from a newly rendered article-template video.

## Next Action

Run one previously unseen audio through the normal stable production path using
the intended API and alignment configuration, with the article template and
smart vocabulary cards enabled when that optional feature is under review.
Before adding any rule, inspect the new manifest, frozen word ledger, final cue
timeline, validation summary, review queue, SRT/ASS, and rendered video.

## Source Priority

This file consolidates the handoff documents, active task log, current code,
Git state, and the regression run above. When they disagree, reproducible test
output and current code/configuration take precedence. Historical chat claims,
stale `work-dir` outputs, and unverified plans are not treated as facts here.
