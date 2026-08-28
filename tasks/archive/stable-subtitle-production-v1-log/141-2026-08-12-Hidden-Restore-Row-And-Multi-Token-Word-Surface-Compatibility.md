## 2026-08-12 Hidden Restore Row And Multi-Token Word-Surface Compatibility

- Reproduced the post-edit parent-view fallback against the real `好莱坞最新热潮：姐弟恋`
  manual package. Two independent invalid assumptions were involved: the
  hidden `S0021` restore row had no display-page ID and was counted as a missing
  page, while the renderer required the number of whitespace tokens to equal
  the number of timed-word records after `OnlyFans -> only as`.
- Page operations now share one non-suppressed-row projection. Hidden restore
  rows remain recoverable but do not participate in completeness, review,
  split, merge, boundary movement, or saved page edits.
- Article page planning, frozen-plan reflow, and frozen-artifact validation now
  derive boundary units from verified timed-word surfaces. The joined surfaces
  must still equal the cue English, and no word ID, range, time, or page ID can
  change.
- The combined regression hides one cue, applies a two-token display surface to
  one frozen word ID in another multipage cue, moves the visible page boundary,
  and restores the hidden cue. Manual-editor, stable publication/UI, article
  readability, syntax compilation, and real-package temporary render-contract
  checks pass. The real package was read only.
- The required 25-stage unified regression exits zero in 372.9 seconds.

