## 2026-08-20 - Terminal ASR Compression Boundary

- Root cause: a completed Faster-Whisper run produced a non-repeated,
  non-silent 25-word hallucination inside the final 462ms. Existing tail
  cleanup only covered short repeated silent tails, while double-anchored
  compressed-timing repair cannot have a right anchor at end of media.
- Fix owner: Faster-Whisper native ASR validation, before the authoritative
  word ledger is published. A terminal burst is removed only with impossible
  timing plus a unique exact left anchor whose context-free local
  retranscription emits no later word.
- Regression protects both outcomes: verified omission removes the tail;
  locally audible following text is preserved and remains fail-closed.
- Production cache replay keeps 2,443 authoritative words through the real
  final question, removes 25 unconfirmed terminal records, and reports zero
  implausible timing runs. ASR trust tests pass 40/40; full offline regression
  passes 29/29 in 893.21 seconds.

