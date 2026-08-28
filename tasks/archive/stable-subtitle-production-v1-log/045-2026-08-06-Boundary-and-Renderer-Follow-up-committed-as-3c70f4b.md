## 2026-08-06 Boundary and Renderer Follow-up (committed as 3c70f4b)

- Corrected the renderer's grammar gate so a complete phrase such as
  `from human feedback` may begin a static line/page with a soft preference
  penalty, while lexical dependencies remain hard-blocked. Regression cases
  cover `according | to`, `completely | out`, and `far more | than`.
- Added parser-confirmed guards for zero-relative clause entrances and
  post-noun participial modifiers in the pre-ID English boundary stage.
- Extracted deterministic word-span page planning into
  `stable_display_planner.py`; the planner is presentation-only and cannot
  mutate frozen cue IDs, text, or timings.
- `tests/test_english_boundary_rules.py`,
  `tests/test_stable_caption_rules.py`, `scripts/run_regression.py`, and
  `git diff --check` pass. Real-audio E2E and synthesis remain the next gate;
  no external request was made by this follow-up.

