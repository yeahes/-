# Current State

Last verified: 2026-08-25 22:05 Asia/Shanghai

## Current Goal

Keep the stable subtitle pipeline from publishing incomplete English when ASR
misses an active speech span, while preserving frozen English IDs, word spans,
timing, page contracts, translation cache identity, and recoverable checkpoints.

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

## Verified Results

- ASR active-gap repair: the confirmed White House gap was repaired by a
  bounded local retranscription with exact left/right text anchors and timing
  fitted back into the authoritative gap. Unanchored results do not mutate the
  transcript and are reported as blockers.
- ASR trust contract: `tests/test_asr_trust_contract.py` passed 45 tests.
- Stable publication contract: `tests/test_stable_publication.py` passed 101
  tests. Final cue timeline tests pass.
- Full regression currently reports 30/32 checks passing. The remaining two
  failures are known legacy expectation mismatches in article readability and
  manual-editor blocking behavior; neither reproduces the ASR repair path.
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
- Manual-final save handles proven orphan display plans after parent merges;
  unexplained orphan plans remain hard failures.

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

## Historical Archive

The former append-only state log is preserved at
`docs/archive/2026-08-25/CURRENT_STATE-history.md`. Superseded unreferenced
planning/baseline notes from the same cleanup are in that directory as well.

## Next Action

Return to the mainline subtitle-quality work. Do not rerun manually reviewed
audio packages; use a new, unreviewed audio for any production experiment.
