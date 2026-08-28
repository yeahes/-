## 2026-08-08 Inline Boundary Controls and Responsive Manual Save

- Replaced the detached boundary inspector with temporary controls embedded in
  the two affected English cells. The controls distinguish same-parent visual
  page moves from cross-parent formal cue moves and highlight the exact words
  that will transfer.
- Added responsive row sizing from the actual English-column width. The table
  completes both row resizes before installing index widgets, then constrains
  each widget to its final cell geometry. This prevents long English clipping
  and adjacent control overlap at narrow window sizes.
- Same-parent page moves persist absolute next-page start word IDs rather than
  deltas or a copied render plan. Save and reload validate those boundaries,
  rebuild only affected parent-derived layout/timing fields, preserve page IDs,
  and reject hard syntax cuts, empty pages, sub-900ms pages, or overflow.
- Unchanged parent cues reuse the SHA-bound frozen blueprint even when the user
  has not edited page Chinese. Formal parent-boundary edits continue to invoke
  full planning and invalidate stale page translation ownership.
- Saving is asynchronous and exposes action text, progress animation, and stage
  messages. It no longer appears frozen while page validation runs.
- Focused publication tests pass 16/16; the article display readability contract
  passes. Twelve qwindows screenshots at DPR 1.0/1.25/1.5 and 419px, 509px,
  and 569px English widths pass with zero crop, overlap, child overflow, or
  legacy-panel visibility. Evidence is under
  `E:\VideoCaptioner-e2e-runs\manual-row-boundary-editor-20260808-dpi-r2`.
  External requests, ASR, LLM, FFmpeg, and video synthesis: zero.
- Manual-final editor and video-synthesis safety suites pass. Unified regression
  passes 25/25 in 327.980 seconds; final `git diff --check` passes with existing
  line-ending notices only.

