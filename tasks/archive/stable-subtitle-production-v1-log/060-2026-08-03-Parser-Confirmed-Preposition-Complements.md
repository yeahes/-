## 2026-08-03 Parser-Confirmed Preposition Complements

- Root cause: a noun-attached example phrase can be parsed as
  `NOUN -> ADP/prep -> NOUN/pobj`; the former visual split gate did not assign
  ownership to the `prep -> pobj` boundary. It could therefore strand the
  example introducer in the preceding temporal cue.
- Added a parser-backed preposition-complement protection in the shared word
  ledger syntax hints. It is used by stable cutting, visual budget splitting,
  and final pre-ID validation. A safe visual split may move the entire example
  phrase to the next cue, but cannot strand its introducer above the
  complement. No audio-specific text condition was added.

