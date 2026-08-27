## 2026-08-09 Entity-Span Guard And Recoverable Page Failure

- The 19:54 production failure was isolated to one
  `page_translation_chinese_token_split` at `S0001.P02`. Deterministic planning
  had already produced 262 parent plans and 303 actual pages, but the validator
  discarded those plans when it returned `ERROR`.
- Page-validation errors now retain the full frozen render-plan list and all
  independently valid translated parents. The manual editor shows the failed
  parent's actual English pages with blank, unconfirmed Chinese and the exact
  validation issue. Formal publication and synthesis remain fail-closed.
- Fuzzy article correction now detects a complete canonical entity inside or
  adjacent to a non-expanding candidate window. It rejects the consuming
  candidate, preserving `Like,` and `President`, while existing phonetic and
  spelling corrections remain eligible.
- Read-only real-checkpoint replay produced 303/303 visible page rows, with all
  three `S0001` pages marked for review. Cached article replay retained both
  protected phrases and corrected all three `Higee/Higgies` forms to `haigui`.
  Focused article, page-contract, manual-editor, and syntax checks pass. The
  unified regression completes all 25 stages in 342.9 seconds and `git diff
  --check` exits zero. No network, ASR, LLM, FFmpeg, video synthesis, or
  production artifact write ran.

