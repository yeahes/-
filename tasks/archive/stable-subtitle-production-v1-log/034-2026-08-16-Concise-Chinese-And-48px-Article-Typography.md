## 2026-08-16 Concise Chinese And 48px Article Typography

- Fresh production A/B compared oil v6 run
  `20260816T195901.871590-95b43f33` with v5 run
  `20260816T180732.415118-413818b4`. Both retained the same 140 frozen parent
  IDs, English, and word spans. Parent Chinese fell 2674 -> 2380 CJK
  characters, actual-page Chinese 2687 -> 2440, pages above 28 characters
  7 -> 2, and longest page 39 -> 30. Page translation passed in both runs.
- Residual quality defects now concentrate in page-level re-expansion or fact
  duplication and a few overcompressed parent translations. Further global
  compression is not justified; the next root owner is page projection and
  semantic QA.
- Upgraded the Pro complete-translation owner from v5 to v6 after the first
  production comparison showed only about 4.6% whole-episode Chinese
  reduction. Each semantic group now carries fixed subtitle IDs, exact
  English, word-ledger display durations, advisory per-ID character budgets,
  and the summed group budget. The prompt treats an existing Chinese
  translation only as terminology/fact reference and gives general idiomatic
  compression patterns instead of sample-specific substitutions.
- The budget remains a soft writing target. Facts, names, numbers, negation,
  causality, modality, reactions, hedges, and stance cannot be removed to meet
  it. No second LLM request, local character deletion, English change, ID
  change, timing change, or page-authority change was introduced. The v6 cache
  task intentionally prevents reuse of v5 translations generated without the
  duration contract.
- Audited the first three minutes of the reference video
  `我们正进入一个普遍“性压抑”的时代。.mp4`. Its compact Chinese comes mainly
  from idiomatic clause rewriting and removing empty spoken scaffolding, not
  character truncation or a smaller font.
- Updated the Pro complete-translation owner to v5. The prompt now asks for
  one-glance documentary Chinese while explicitly protecting facts, entities,
  numbers, negation, modality, reactions, hedges, and speaker stance. Existing
  fixed-ID allocation and page projection contracts remain unchanged.
- Raised article-template Chinese from 46px to 48px and bumped the display
  planner to v22. The two-line and safe-width limits remain fixed.
- Read-only replay of the latest 140-parent oil run kept every frozen parent
  field and produced 157 pages. Only `S0134` changed from one 50px three-line
  page to two pages (50px/56px); total three-line pages fell from three to two.
- Focused prompt, renderer, page-mapping, and full article-readability tests
  pass. The complete `runtime\python.exe scripts\run_regression.py` command
  also exits zero.

