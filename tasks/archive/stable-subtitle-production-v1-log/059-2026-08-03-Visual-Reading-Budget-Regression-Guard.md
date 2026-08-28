## 2026-08-03 Visual Reading Budget Regression Guard

- Root cause: the pre-ID visual reading-budget pass accepted a candidate when
  its cut point had no hard syntax issue, but did not require both newly
  created cues to be independently readable on screen. This could split a
  complete sentence into a short connector-led, comma-ended, or
  preposition-led fragment.
- Added a visual-only display-unit gate to
  `ScreenSubtitleEditor._safe_item_split_for_budget`. The 16-word structural
  overflow path is unchanged; only the optional 12-word/68-character visual
  pass opts into the stricter gate.
- Candidate audits now include `visual_display_issues`. A rejected visual-only
  split keeps the existing complete cue and records `visual_budget_unresolved`
  as REVIEW evidence rather than a structural error.
- Added regression coverage for short comma-ended phrases, connector-led noun
  phrase fragments, preposition-led tails, and preservation of word order,
  ranges, and timestamp ownership.
- Validation passed:
  `runtime\\python.exe -X utf8 tests\\test_stable_caption_rules.py`,
  `tests\\test_stable_boundary_finalization.py`,
  `tests\\test_article_context.py`, and
  `runtime\\python.exe -X utf8 scripts\\run_regression.py`.

