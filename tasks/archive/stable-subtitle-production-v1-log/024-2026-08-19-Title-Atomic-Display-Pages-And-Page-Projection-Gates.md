## 2026-08-19 Title-Atomic Display Pages And Page-Projection Gates

- Added general surface rules for multi-word work titles, named entities,
  numeric title forms, and independent titles joined by `and`/`or`. These
  rules protect boundaries by structure and surface form; they are not
  subtitle-ID exceptions. A complete title can end at a controlled review
  boundary so the next independent idea can still become its own page.
- Added page-level translation contract checks for repeated fact content on
  adjacent pages and a condition appearing after a completed question. These
  checks reject only the affected parent and preserve valid page mappings for
  the rest of the run.
- Read-only replay against the saved Dreamcore corrected ASR: 202 parents,
  2,198/2,198 ordered ledger words, 247 planned pages, font distribution
  238/4/5 at 56/54/52px, zero 50px pages, and zero three-line English pages.
  `S0111` keeps `Journey to the West` and `Escape from the 21 st Century`
  atomic; the next culture phrase is no longer attached to the title page.
- The existing checkpoint is correctly blocked because its cached `S0111`
  page Chinese fails the new projection contract. This is a stale affected
  page-translation artifact, not a failure of the new English planner. A
  rerun can reuse ASR, full translation, alignment, IDs, and timing, and only
  refresh affected page-translation batches.
- `tests/test_article_display_readability_contract.py` and
  `tests/test_stable_page_translation_contract.py` pass. The complete offline
  regression command and `git diff --check` pass.

