## 2026-08-10 High-Pressure Single-Page Secondary Review

- Audited all 17 remaining high-pressure single pages in the current
  study-abroad manual package: mean 16.06 words, median 16, range 12-22.
- Added a bounded secondary review for pages over 16 words or at 52/50px. A
  promoted plan must keep at least six words and 900ms per page, fit at 56px,
  and use a complete-clause or 500ms-pause boundary. Lexically incomplete
  boundaries remain rejected.
- Offline 262-parent replay changes page boundaries only for `S0044`, `S0076`,
  and `S0257`. It continues to reject `going | abroad`, `drastically | higher`,
  and the unbalanced `S0167` candidate. Parent ID, English, Chinese, word-range,
  and page-coverage checks report zero mismatches.
- Added article-person context support for low-similarity titled names. Real
  replay corrects two `Ms. Howe` spans to `Ms Hao`, preserves all three
  `haigui` spans, and retains complete coverage of the 2860-word ledger.
- Added `article-asr-correction-v2` to interrupted-run stage details. Old
  correction output is recalculated while the article context and raw ASR stay
  reusable.
- Focused article-context tests pass 33/33, the article display contract passes,
  and the unified regression passes all 25 stages in 375.0 seconds. External
  requests and production writes are zero.

