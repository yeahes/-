## 2026-08-22 Semantic Allocation Failure Boundary

- Reproduced the Japanese-generation failure twice. Its only uncached multi-cue
  allocation request exhausted three attempts (`500`, timeout, `500`); the GUI
  process remained responsive and the apparent `0/1` stall was external request
  latency rather than a local deadlock.
- Root cause after the request failure was local: fixed-ID completeness only
  recorded an error and allowed the incomplete Chinese set to reach authority
  artifact construction. That downstream contract then obscured the provider
  failure with `authoritative_parent_chinese_record_invalid`.
- The translation owner now stops immediately with
  `semantic_chinese_incomplete`, exact missing IDs, retained-cache guidance,
  and the last provider error. Non-missing ID corruption stops under the
  separate `semantic_chinese_id_contract_invalid` code.
- Three focused regressions pass for owner-stage blocking, provider-error
  retention, and empty-middle-ID handling. Raw pytest over the stable-caption
  file passes 511 tests; its 14 failures are pre-existing assertions outside
  this change, including the known strict-16-word expectation and stale test
  constructors/encoding cases.
# 2026-08-22 - Equal-Risk Page Boundary Ordering

- Reproduced a deterministic page-selection regression where equal structural
  risk allowed visual balance to choose `set | a strict` over the pause-backed
  `objections | would` restart.
- The final candidate ordering now uses verified strong-pause restart count as
  a tie-breaker before line-wrap, font, and visual-quality costs. Candidate
  generation and every frozen parent/timing/translation contract are unchanged.

