## 2026-08-04 Chinese Allocation Quality And Near-Threshold Rendering

- Root cause: allocation validation returned success for a terminal Chinese
  modifier whenever it carried closing punctuation. This bypassed the existing
  fragment retry and allowed a phrase without its governed noun or predicate
  to reach final subtitles. The generic allocation retry also reused the
  ordinary prompt despite knowing that the failure was grammatical.
- Final modifier fragments now fail fixed-ID validation after permitted
  non-final continuations are considered. They use the existing one-group
  retry with a grammar-focused fixed-ID prompt and a distinct cache key; no
  extra retry or English/timing mutation is introduced.
- Root cause: the same `12.0` Chinese-CPS threshold classified a 15-character
  subtitle over 1241ms as a render error at `12.09` CPS. It was a discrete
  character-count boundary case rather than a sustained reading overload.
  The explicit error boundary is now `12.25` CPS; `9.0-12.25` CPS remains
  review evidence. Structural translation/timeline errors are unchanged.
- The Chinese semantic audit no longer applies fragment rules to a fully
  punctuated single-cue sentence, eliminating a known class of false positives
  without weakening multi-cue allocation checks.
- Added focused regression coverage for terminal modifiers, specialized retry
  selection, single-cue audit false positives, the 12.09-CPS near-threshold
  case, and final allocation artifact coverage.

