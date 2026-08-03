# CODEX State

Status: implementation checkpoint verified by the unified automated regression;
fresh end-to-end production validation on a newly generated audio run is still pending.

Last verified: 2026-08-04 00:17:32 Asia/Shanghai

Branch: main

Verified HEAD: 6713185a9ff3af96a26d44bec15b2391ee2acd46

Working tree: clean immediately after the verified implementation checkpoint.
This state record contains no executable change and is committed separately.

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
- Final cue timing is ID-addressable and derived from frozen cue word ranges in
  the authoritative word ledger. Final-timeline validation blocks synthesis on
  structural errors.
- English boundary finalization is local and deterministic. Its production
  stages are ordered by `stable_english_boundaries.py`; no dynamic programming
  or audio-specific text rules are permitted.
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

## Verification Evidence

- `runtime\python.exe -X utf8 scripts\run_regression.py`: PASS on the current
  implementation checkpoint. It ran final timeline, stable-cut, boundary,
  allocation, artifact, frozen-run, golden-evaluation, manual-editor, review
  queue, run-state, and syntax checks.
- `git diff --check`: PASS before the implementation checkpoint. The observed
  LF/CRLF messages are line-ending notices, not whitespace errors.
- The known-output audit reported `MISSING` for local samples `222`, `777`, and
  `999`. This is neither a subtitle-quality pass nor a failure of the code.

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

## Next Action

Run one previously unseen audio through the normal stable production path with
the intended API and alignment configuration. Before adding any rule, inspect
the new manifest, frozen word ledger, final cue timeline, validation summary,
and user-facing review queue; then compare the produced SRT/ASS and rendered
video against those artifacts.

## Source Priority

This file consolidates the handoff documents, active task log, current code,
Git state, and the regression run above. When they disagree, reproducible test
output and current code/configuration take precedence. Historical chat claims,
stale `work-dir` outputs, and unverified plans are not treated as facts here.
