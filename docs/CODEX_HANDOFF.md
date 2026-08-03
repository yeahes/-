# VideoCaptioner Screen Subtitle Handoff

Last verified: 2026-08-04 Asia/Shanghai

## Repository State

- Active working copy: `E:\VideoCaptioner-screen-subtitle`.
- Branch: `main`.
- Verified HEAD: `bafd5d72b9b3ed406f4f632ed3153c3f14768df3`.
- Working tree: modified, with substantial tracked and untracked implementation,
  test, script, and documentation changes. Do not reset, clean, or discard
  them. Inspect `git status --short`, relevant untracked files, and `git diff`
  before editing.
- The original project under `D:\软件缓存\VideoCaptioner` is not the active
  working copy and must not be modified.

## Active Production Contract

```text
ASR word timestamps
-> local stable English cutting
-> frozen English text, word spans, global subtitle IDs, and cue order
-> LLM full Chinese translation by semantic group
-> LLM Chinese allocation by existing subtitle_id only
-> local validation and artifact writing
-> final cue timeline derived from frozen word spans
-> SRT/ASS export and video synthesis
```

The stable path treats English as immutable data after the cutting phase. The
LLM may write Chinese only; it must not change English text, subtitle IDs,
order, count, word ownership, or timing. All final cue times are derived from
the authoritative word ledger and frozen cue word spans, not from a later text
match or list position.

## Confirmed Decisions

- Keep stable mode as the normal production path. Do not use LLM English
  segmentation in that path.
- Do not use dynamic programming for English cutting.
- Do not add rules tied to the text of a particular audio sample. New rules
  must express a general grammar, word-ledger, or invariant condition and have
  a regression test at the originating layer.
- English target length is 16 words. A structurally inseparable cue may reach
  17-19 words; a short but grammatically broken cue is not preferable.
- spaCy syntax evidence, local word timestamps, punctuation, and pause data
  guide English cuts. A long pause cannot legalize a hard grammar split.
- Preserve spoken backchannels in stable mode. Do not globally delete `Right`,
  `Yeah`, `Okay`, and similar responses.
- Chinese allocation is ID-addressed. Missing, duplicate, or unknown returned
  subtitle IDs are structural errors; positional `zip` writeback is forbidden.
- ERROR blocks renderable stable output. WARNING/INFO remain diagnostic only.
- Candidate quality check remains off for normal production. Optional Chinese
  polish is selective and must not be expanded into a full-video rewrite.
- Default timing backend remains `stable-ts`. `whisperx-time-only` is the
  lower-risk experimental mode when only final timing should change; full
  WhisperX is allowed only when changed English boundaries are acceptable.
- Source audio folders receive three exports: bilingual SRT with English on
  top, Chinese-only SRT, and English-only SRT.

## Completed Work

### Stable English, IDs, and timing

- Stable English boundaries are finalized before global IDs are assigned.
- Final cue timeline ownership is implemented through the frozen
  `subtitle_id -> word_start/word_end` mapping. Final cues must cover their
  own first and final ledger words before export.
- `whisperx-time-only` maps timing to frozen ledger words and falls back to
  stable-ts timing when mapping is incomplete or unavailable. It does not use
  final cue text as the alignment source.
- Final display reconciliation is bounded: it may bridge only a short adjacent
  gap inside continuous source-word coverage and cannot change word ownership,
  English text, IDs, or word timestamps.
- Stable processing now produces ID-addressable artifacts including final cue
  timeline, manifest, coverage diagnostics, and a timed subtitle review queue.

### English cut quality

- Local deterministic cutting has parser-backed protections for subject/verb,
  verb/object, verb/preposition complement, clause introducer, phrasal verb,
  noun phrase, number/unit, time-range, and fragment boundaries.
- The pre-ID visual reading pass may choose an independently safe boundary; it
  does not change the frozen 16-word structural contract or manufacture a
  structural split when no safe boundary exists.
- The spaCy-to-word-ledger mapper now handles split compound tokens without
  consuming later ledger words. This covers cases where spaCy tokenizes an ASR
  word such as `six-fold` or `52%` into multiple tokens.
- A general `verb + numeric result (+ from/to/by/at baseline)` protection was
  added. It rejects cuts such as `crashing | 52%` when the numeric result is
  syntactically attached to the verb. It does not hardcode any audio text.
- Replaying the frozen `韩国股市的繁荣正轰然崩塌` ledger now cuts the relevant
  sentence as an 8-word cue and a 14-word cue; the former `crashing | 52%`
  boundary is rejected.

### Chinese translation and allocation

- The two-stage design is present: full semantic-group Chinese translation,
  then allocation to existing subtitle IDs.
- Allocation and post-allocation candidates are validated before writeback for
  ID structure, entity, number, negation, duplication, fragments, semantic
  loss, and reading pressure. A rejected candidate restores the prior
  ID-bound Chinese allocation.
- Chinese display budgets are advisory inputs derived from fixed cue duration;
  they do not allow omission or timing changes.
- Compression and same-group reallocation now accept `subtitle_id` output.
  Index-based cached output is compatibility-only and is locally mapped before
  writeback.
- Optional Chinese polish is capped at eight selected semantic groups and can
  target complex comparison/enumeration groups. It is applied only when the
  returned fixed-ID allocation passes non-regression validation.
- Real replay evidence: polish improved some comparison/list allocations, made
  no change to an already acceptable short-response group, and did not modify
  English, IDs, or timing. It did not make every cross-cue Chinese phrase
  fully natural; therefore it remains optional rather than a default full
  retranslation pass.

### Operations and UI

- Stable runs record `run-state.json` with input/configuration fingerprints,
  stage progress, artifact digests, cache/batch/retry state, elapsed time, and
  bounded ETA.
- The subtitle editor supports a local manual-final mode for adjacent merge or
  word-ledger-backed boundary transfer when matching artifacts exist. It writes
  an explicit manual final SRT and edit log; synthesis can prefer that override.
- Article assistance, entity correction safeguards, and smart vocabulary cards
  are optional enhancements. They are not allowed to modify stable English
  boundary/timing ownership.

## Verification Already Performed

- `runtime\python.exe scripts\run_regression.py` passed after the latest
  numeric-result and split-compound mapping changes.
- Targeted tests cover both the numeric-result protection and the hyphenated
  ledger-token mapping.
- `git diff --check` exited successfully; current messages about LF/CRLF are
  repository line-ending notices.
- Earlier complete runs documented in `docs/CURRENT_STATE.md` include passed
  stable outputs with exact Chinese-ID coverage, zero translation-structure
  errors, and successful render. Generated outputs remain historical evidence,
  not proof that a later code change has been end-to-end validated.
- The regression audit references local `222`, `777`, and `999` samples that
  are absent in this checkout; `MISSING` is expected and is not a test pass for
  subtitle quality.

## Unfinished Work and Known Limits

- A fresh full production run has not yet been completed specifically after
  the latest split-compound/numeric-result syntax change. The next quality
  decision must use a newly generated output, not an old SRT or video.
- Chinese cross-cue naturalness still has an inherent limit when a frozen
  English cue boundary divides a tight semantic structure. Optional polish can
  improve some groups but cannot merge IDs, alter English, or move timing.
- ASR errors and inaccurate word timestamps remain upstream limits. They are
  not safely repairable by changing final SRT text or padding individual cues.
- `screen_editor.py` remains large and coupled. New boundary, allocation, and
  timing changes should go through the existing extracted contract/timeline/
  artifact modules when possible; avoid broad rewrites.
- Existing artifacts and rendered media under `work-dir` can be stale. Verify
  manifest hashes, run state, and output timestamps before using them as a
  baseline.
- Cache behavior after changing API endpoint or model must not be assumed.
  Re-run or inspect the active run state and artifacts; do not treat an old
  cache as a quality baseline.

## Immediate Next Action

Run one previously unseen audio through the normal stable production flow with
the intended API configuration. Before any additional rule change, verify:

1. English word coverage/order, subtitle IDs, and final cue timing remain
   frozen and valid.
2. No translation-ID structural error or render blocker occurs.
3. The new English syntax protection avoids bad numeric-result cuts without
   producing over-19-word cues or new fragments.
4. Chinese polish, if enabled, changes only selected semantic groups and
   records an accepted fixed-ID validation result.

## Required Read Order for a New API/Agent

1. `AGENTS.md`
2. This file
3. `docs/CURRENT_STATE.md`
4. `docs/ARCHITECTURE.md`, `docs/PIPELINE.md`, `docs/SUBTITLE_RULES.md`, and
   `docs/TESTING.md`
5. `git status --short`, relevant untracked files, `git diff`, and current
   source/tests before deciding on any edit

Do not rely on historical chat messages or API cache for project state. When a
document conflicts with reproducible output, current code/configuration, or
Git state, use the latter and update the document at the next verified
checkpoint.
