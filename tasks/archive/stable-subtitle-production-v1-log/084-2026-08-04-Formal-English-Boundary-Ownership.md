## 2026-08-04 Formal English Boundary Ownership

- Root cause: the formal pre-ID stage list still called the visual
  12-word/68-character budget pass. A display preference could therefore
  create frozen English IDs and fragment the downstream Chinese allocation.
- Fix: removed `_apply_visual_reading_budget` from the production stage list.
  It remains an offline historical diagnostic, while renderer-only pagination
  owns visual page breaks after formal English, IDs, and Chinese are frozen.
- Regression injects a raising visual-budget method and proves the finalizer
  does not invoke it; a 14-word grammatical cue stays one formal item.
- Delegated validation passed:
  `tests\test_stable_boundary_finalization.py`,
  `tests\test_stable_caption_rules.py`, `scripts\run_regression.py`, and
  `git diff --check`. No ASR, LLM request, or synthesis ran.

