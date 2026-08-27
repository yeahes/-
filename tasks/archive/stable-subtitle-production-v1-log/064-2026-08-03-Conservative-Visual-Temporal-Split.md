## 2026-08-03 Conservative Visual Temporal Split

- Restored visual temporal splitting only as a pre-ID, syntax-owned stage.
  The soft 12-word/68-character budget merely starts candidate evaluation; it
  cannot independently create a cue boundary.
- Accepted generic categories are `sentence_terminal`,
  `complete_clause_boundary`, and `fronted_introduction_boundary`. Every
  accepted boundary is recorded with category, word ranges, recorded pause,
  candidate display durations, and preservation checks.
- Immutable replay of `如何识别人工智能写作` selected six boundaries from 216
  frozen English cues, producing 222 pre-ID cues. All six preserve word order
  and word coverage; 57 remaining soft-budget cues have no safe split and stay
  renderer-owned.
- Confirmed that `You know, this robotic vocabulary actually connects ...`
  remains unsplit: the potential cut separates the subject from its finite
  verb, which is still a parser-confirmed hard grammar boundary.

