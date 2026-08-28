## 2026-08-24 Complete-parent timeline deletion

- Added a reversible, parent-scoped editor operation that marks one or more
  complete parent cues for deletion from the derived presentation timeline.
  Multipage parents require all page rows; page-only deletion, mixed states,
  and deleting every parent are blocked.
- Manual-final save emits schema-v3 source-bound media derivation. Retained
  source slices are concatenated from the original audio, and later cue/page/
  word-card times use the compacted presentation clock. Source audio, frozen
  IDs, English, the authoritative word ledger, and source word timestamps are
  unchanged.
- Focused regression passes 262 tests. The full 30-check run passes 29 checks;
  the unrelated existing `S9522` article readability assertion remains
  failing (`into` expected, `in` selected). No pagination strategy change was
  included in this feature.

