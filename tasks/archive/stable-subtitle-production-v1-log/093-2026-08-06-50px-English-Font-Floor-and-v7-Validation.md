## 2026-08-06 50px English Font Floor and v7 Validation

- The v6 `54/52/50/48/46px` fallback sequence is superseded. Article English
  now defaults to 56px and may fall back only through 54px, 52px, and 50px.
  A cue that cannot satisfy the fixed two-line, legal-boundary, and timing
  contracts at 50px fails with `render_structural_overflow`; it cannot silently
  shrink further.
- The page planner contract is `article-fixed-font-pages-v7`, which invalidates
  render plans and page-translation caches created under the lower font floor.
  The change does not alter frozen English, subtitle IDs, Chinese ownership,
  word spans, or cue timing.
- Final offline replay under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r11-offline-audit`
  plans 262/262 cues and 289 pages with zero structural failures. Font
  distribution is 56px=247, 54px=2, 52px=8, and 50px=5. No page uses a font
  below 50px; all paginated pages last at least 1351ms.
- Twenty-nine representative 1920x1080 frames and six before/after transition
  pairs have zero blank frame, crop, bilingual overlap, page-time mismatch, or
  transition failure. Missing, duplicate, reordered, and uncovered word IDs
  are all zero.
- Four high-risk and twelve medium-risk semantic page boundaries remain for
  editor review. They are reported instead of being hidden by extra font
  reduction or sample-specific rules. Nineteen pages exceed the 16-word soft
  budget because a safer shorter partition was unavailable.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py`, the four
  focused manual/package/page-contract suites, unified regression, and
  `git diff --check` pass. Validation used zero network, ASR, LLM, FFmpeg, or
  paid external requests.

