## 2026-08-24 Manual-final frozen page checkpoint reuse

- Saving an unrelated manual edit no longer discards an `ERROR` display-page
  artifact when its render plans are structurally valid. The original page
  IDs and word ranges remain authoritative; genuine semantic page errors stay
  blocking.
- ID-bound page translation cache hits are retained independently. Missing or
  blank sibling pages are left for exact contract validation instead of
  converting the complete result into a broad pending queue.
- Source-scoped semantic errors remain blocking only for their recorded parent
  or page IDs. The real Japanese X-generation replay now reports only
  `S0136.P01/P02` after deleting `S0001-S0006`.
- Manual-editor tests pass `128/128`; full regression remains `29/30` with the
  pre-existing `S9522` article readability failure.

