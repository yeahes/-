## 2026-08-07 Page Contract v8 and Current-Code E2E

- Replaced the single-width page objective with a measured display objective:
  1260px comfortable width, 1455/1498px controlled fit widths, 56/54/52/50px
  fonts, and a global cost over pixel load, word load, spoken duration, short
  pages, syntax confidence, and balance. The display layer still cannot change
  formal English, IDs, word ownership, cue timing, SRT, or ASS boundaries.
- Added shared vendored Chinese token boundaries to the page allocation
  contract and reject page responses that split a Chinese token. Page-level
  Chinese is validated by exact page ID and aggregate parent content.
- Removed a duplicate unconditional `-ing/-ed + complement` prohibition. The
  authoritative rule is now pause-aware: attachments at or below 200ms remain
  hard, while a 400ms pause may enter the scored candidate set. Focused tests
  preserve `locked | in` at its real 80ms pause and allow the separate 400ms
  control case.
- `tests/test_article_display_readability_contract.py` passes 7/7, the page
  contract suite passes, the complete unified regression exits 0, and
  `git diff --check` reports no whitespace errors.
- Fresh E2E output is under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260807-page-contract-v8-r1`.
  It contains 259 fixed cues, 2,897 words, complete English/Chinese ID mapping,
  final timeline `PASS`, `whisperx-time-only`, no missing source audio, and no
  overall stable-ts backend fallback. Ten local numeral/acronym timing
  protections are recorded separately.
- Relative to the prior 262-cue artifact, the current pre-ID finalizer changes
  seven actual boundaries (five removed, two added). It removes known fragment
  boundaries such as `center | might` and `U.S. | right now`; the remaining
  244 positional differences are downstream ID renumbering, not 244 rewritten
  English cues.
- Page translation is `PASS`: 40 multi-page parents and 83 translated display
  pages. The frozen renderer artifact has 259 plans, 302 total pages, and 43
  transitions. Two continuation reviews remain non-blocking; the fixed-ID
  editor artifact contains one high-confidence allocation review.
- Frozen-artifact validation rendered 388 frames and reports zero mechanical or
  pixel failures. The authoritative report is
  `full-page-validation/frozen-artifact-full-validation.json`. A separate
  reconstructed offline replay yields 303 pages because it regenerates syntax
  evidence; synthesis loads the published hash-bound 302-page plan instead.
- The run made 22 DeepSeek requests: 14 full translation batches, three normal
  allocation batches, three fragment retries, one allocation retry, and one
  page translation batch. ASR requests were zero. Final synthesis ran once,
  with vocabulary cards disabled, and produced `final-video.mp4` (45,540,482
  bytes).
- The encoded MP4 then passed a separate zero-network validation. It extracted
  391/391 frames: 302 page midpoints, 86 before/after frames for all 43 page
  transitions, plus 64.8/65.6/66.5-second anchors. Every frame matched the
  published frozen artifact, and blank subtitle, crop, bilingual overlap,
  frozen-pixel mismatch, and transition failure counts were all zero.

