## 2026-08-22 Page-Stage Liveness And Bounded Failure Recovery

- Reproduced the `日本X世代的困境：被反复诅咒的一代人` run at the page stage:
  11 batches / 115 pages, concurrency two, exhausted 40-attempt shared budget,
  and a stale 96% GUI. After page failure it could start about 21 serial quality-
  audit requests with a 180-second timeout.
- Replaced eager submission with a bounded `FIRST_COMPLETED` scheduler. At most
  two batches are active; every valid completion is cached and reported before
  another batch is admitted. A terminal failure stops later admission while the
  frozen contract remains the only final merge order.
- Split request accounting into `screen_subtitle_edit` and
  `display_page_translation` scopes. Manifest metadata records per-stage use.
  Page-stage failure now writes quality audit status `SKIPPED` and preserves the
  editable checkpoint without starting audit requests.
- GUI/run-state progress now owns page translation 96-98%, audit 98-99%, and
  final save 99-100%. Page events include completion, total, cache hits, retries,
  active/failed batches, and elapsed seconds.
- Focused syntax and changed-layer suites pass. Full regression finished in
  788.30 seconds with 29/30 checks passing. Page translation (361.86s), article
  readability (357.90s), manual-final, review marks, quality audit, run state,
  and syntax all pass. The only failure is the unrelated legacy strict-16-word
  assertion `test_preposition_phrase_is_not_stranded`; the production policy
  now keeps that complete unsafe-to-split clause for renderer wrapping.
- The Chocolate manual-final package was successfully published at 04:44:55
  with `render_blocked=false` and zero pending Chinese, boundary-review, or hard
  page counts. The old GUI was then closed cleanly; generated/manual artifacts
  were not touched by implementation or tests.

