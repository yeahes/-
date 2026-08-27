## 2026-08-25 Translation Prompt A/B Preparation

- Read-only audit of the immutable `测试音频` run confirmed the stable identity,
  word coverage, page coverage, and page-Chinese completeness. It also exposed
  one false semantic-loss finding for the valid Chinese purpose construction
  `要……得……`, plus recurring page projections that end on a bare governed
  head when the fixed English page is already a fragment.
- Updated the full-translation, fixed-ID allocation, and display-page prompts
  with explicit fact/logic preservation and continuous-readability rules. The
  changes remain translation-only and cannot mutate English, IDs, timing, the
  word ledger, or parent meaning.
- Bumped prompt identities to `semantic-full-translation-v8`,
  `semantic-allocation-v5`, and `display-page-translation-v10`, so old cached
  responses do not masquerade as output from the new contract. No API call or
  old artifact write was made during this edit.
- Focused tests passed, including the new `because to ... have to ...` semantic
  equivalence regression. Next verification is a fresh, same-input provider A/B
  on an unreviewed run; do not re-run the four manually corrected episodes.

