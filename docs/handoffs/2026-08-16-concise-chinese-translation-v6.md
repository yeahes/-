# Concise Chinese Translation V6

## Outcome

- Complete semantic-group translation remains owned by the configured Pro
  model and now uses `semantic-full-translation-v6`.
- Each target group includes fixed subtitle IDs, exact English, word-ledger
  display durations, advisory per-ID Chinese budgets, and a summed group
  budget.
- The prompt requests fresh idiomatic subtitle Chinese rather than inheriting
  the wording or length of an existing translation.
- Reading budgets are soft. Facts, names, numbers, negation, causal and
  contrast relations, modality, reactions, hedges, and stance remain required.

## Preserved Contracts

- No second LLM request was added.
- English text/order, subtitle IDs, word spans, word timestamps, cue timing,
  fixed-ID allocation, display-page projection, and synthesis resolution are
  unchanged.
- The v6 cache task intentionally does not reuse v5 complete translations
  generated without duration budgets.

## Verification

- Focused v6 prompt, payload, source-echo, context, retry, and chunking tests
  pass.
- `runtime\python.exe tests\test_stable_caption_rules.py` passes.
- `runtime\python.exe scripts\run_regression.py` completes all 26 stages.
- Python syntax compilation and `git diff --check` pass.
- No paid model request or production artifact write was made during
  implementation.

## Production A/B

- Compared fresh v6 run `20260816T195901.871590-95b43f33` with v5 run
  `20260816T180732.415118-413818b4` for the same oil episode.
- Both contain the same 140 frozen parent IDs, English text, and word spans;
  frozen-field drift is zero.
- Parent Chinese fell from 2674 to 2380 CJK characters (-11.0%). Actual-page
  Chinese fell from 2687 to 2440 (-9.2%).
- Pages above 28 CJK characters fell from 7 to 2; the longest page fell from
  39 to 30 characters. Both page contracts pass.
- Remaining defects are concentrated in page projection re-expansion,
  duplicated page facts, and a few overcompressed or semantically awkward
  parent translations. The next owner is page projection and semantic QA, not
  stronger unconditional Pro compression.
