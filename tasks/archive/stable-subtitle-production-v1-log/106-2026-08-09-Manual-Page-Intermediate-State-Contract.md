## 2026-08-09 Manual Page Intermediate-State Contract

- Split and moved display pages now use an editor intermediate state. Page
  Chinese may be empty while boundaries are adjusted; formal publication still
  reports `manual_page_translation_required` until all pages are filled.
- Explicit manual confirmation may downgrade grammar-risk and sub-900ms page
  choices to REVIEW. Automatic planning remains strict. Non-contiguous word
  ownership, empty English pages, ID/range drift, impossible shared timing, and
  fixed-font overflow remain hard failures.
- Repeated moves rebuild from the currently confirmed page ranges instead of the
  original one-page artifact. A blocked checkpoint retains the hash-bound English
  page plan and restores it on reload even when no draft artifact can be built.
- The editor exposes upper/lower boundary entry points, one-word direction reset,
  live word highlighting, explicit confirm text, review-color legend, and an
  enabled background `refresh actual pages` path after formal boundary changes.
- Manual-final editor tests pass 25/25 and stable publication tests pass 23/23.
  Unified regression passes 594 tests across 24 suites plus one syntax check
  with zero failures in 335.056 seconds; final `git diff --check` passes with
  line-ending notices only.
- The first DPR run found stale Qt index widgets covering the refreshed parent
  model. The cleanup path now retains widget references, hides each widget
  synchronously, detaches it from the table index, and schedules deletion.
- Final qwindows validation under
  `E:\VideoCaptioner-e2e-runs\manual-page-intermediate-editor-20260809`
  passes 510/510 checks across DPR 1.0/1.25/1.5. All 18 PNGs were reviewed;
  stale controls, clipping, and overlap are zero. External network, ASR, LLM,
  video synthesis, and paid requests are zero.

