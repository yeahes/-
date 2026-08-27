## 2026-08-04 Renderer-Owned Unsplittable English Sentence

- Root cause: `_stable_greedy_ranges()` forced a 19-word cue when no legal
  normal-limit cut existed. It also accepted a grammatically incomplete
  17-19-word emergency candidate merely because its local boundary was legal.
  The final validator correctly rejected both incomplete cues as overlong,
  producing a stable pipeline contradiction before subtitle IDs were assigned.
- Fix: an emergency 17-19-word cut is eligible only when it is a complete
  terminal cue or parser-confirmed comma subordinate clause. Otherwise the
  pre-ID cutter preserves the remaining complete source sentence for renderer
  wrapping. It is an audited structural-overflow warning, not an export error.
- Invariant: pre-ID stable cutting must not manufacture a cue which the final
  English validator is guaranteed to reject. English text/order, the word
  ledger, IDs, Chinese allocation, and final cue timing remain outside this
  change.
- Regression and frozen-ledger replay cover both prior production shapes:
  a protected `synthetic text` phrase and the terminal `websites on the
  internet` preposition phrase. The replay uses no ASR or LLM request.

