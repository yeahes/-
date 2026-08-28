## 2026-08-03 Temporal Boundaries Versus Renderer Wrapping

- Audited the completed `如何识别人工智能写作` run from its frozen
  `stable-boundary-snapshots.json` and word ledger. The former visual
  12-word/68-character pass created 49 additional temporal subtitle
  boundaries: 31 are locally incomplete display units, 17 are unnecessary
  without a supporting 450ms pause, and 1 is only potentially semantic.
- Root cause: a renderer reading target had authority to create English cue
  boundaries before IDs. That fragmented Chinese allocation even when the
  stable syntax cutter had already produced a complete 13-16 word cue.
- `_apply_visual_reading_budget()` is now a deliberately narrow pre-ID visual
  temporal stage. It considers only a sentence terminal, two complete
  punctuated clauses, or a punctuated non-finite introduction followed by a
  complete main clause, and only with a recorded pause plus safe display
  duration on both sides. Structural overflow remains owned by the existing
  syntax cutter; every other long cue stays intact for renderer wrapping.
- The renderer now strongly avoids a new visual line before a preposition,
  infinitive marker, connector, or clause introducer, after a determiner,
  function word, or auxiliary, and inside a hyphenated compound. It may reduce
  font size only when needed to find a phrase-safe two-line layout.
- Added `scripts/audit_visual_temporal_splits.py` for repeatable historical
  snapshot review. It writes a complete JSON and Markdown table for every
  visual time boundary without using an LLM or changing a subtitle.
- Validation passed: `tests/test_stable_caption_rules.py`,
  `tests/test_article_context.py`, and `scripts/run_regression.py`.
- A final-boundary audit also found and removed a generic QC false positive:
  an unambiguous sentence terminal now wins over token-only determiner and
  modifier guesses, while title and initial abbreviations before names remain
  protected as non-terminal boundaries.

