## 2026-08-13 Failed AI Competition Boundary Follow-up

- The fresh cached rerun failed only at `S0211 | S0212`: alignment changed the
  trusted pause and the final gate still saw `most likely, | to manage`.
- The first attempted fix was rejected during review because it moved the bad
  cut to `most | likely, to manage`. The retained fix is narrower: spaCy must
  confirm an adjacent modified predicate scope followed by a `to` auxiliary
  headed by a bare verb. This protects `most likely, to manage` without making
  every comma-plus-purpose-infinitive boundary a blocker.
- Added regression coverage for the real repair, the no-parser degree-modifier
  fallback, and an ordinary paused purpose clause. Complete stable-caption
  tests and immutable production replay pass.
- Direct replay of the failed checkpoint moves only boundary `2380 | 2381` to
  `2378 | 2379`, keeps all 2,596 words and 226 cue IDs, and reduces hard
  English boundaries from one to zero. The final 25-stage regression passes in
  359.5 seconds; validation was offline and made no ASR, LLM, synthesis, or
  paid request.
