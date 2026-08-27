## 2026-08-04 Whole-File English Boundary Evidence Audit

- Root cause: the prior syntax audit examined only selected text pairs and
  could not distinguish an unresolved atomic split from a legitimate boundary
  supported by word timing, punctuation, or a speaker change.
- Fix: `english-boundary-audit.json` now records every final English boundary
  as `hard`, `review`, or `allow`. The scanner combines existing deterministic
  syntax rules with frozen word ranges, actual word pause, sentence terminal,
  continuity, and speaker evidence. It never mutates a final ID, translation,
  timing, SRT, or ASS cue.
- A residual `hard` record is now a blocking validation error. `review` records
  remain timed human-review entries; `allow` records remain only in the full
  machine artifact. Start-word part of speech alone cannot produce an error.
- Added screenshot-derived fixture cases for `three long | em-dashes`,
  `far more | than`, `completely | out`, `according | to`, and numeric
  magnitudes, plus allowed terminal-clause counterexamples and the long-pause
  review downgrade.
- Delegated validation passed:
  `tests\test_english_boundary_rules.py`,
  `tests\test_stable_caption_rules.py`, `scripts\run_regression.py`, and
  `git diff --check`. No ASR, LLM request, or synthesis ran.

