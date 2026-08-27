## 2026-08-09 Interactive Review Gate And Organized Media Outputs

- Added a dedicated interactive review contract to `SubtitleTask`. Home-created
  full-process subtitle tasks set it, and `SubtitleInterface` no longer emits
  the automatic synthesis signal for those tasks after subtitle completion.
  Batch tasks keep the default automatic chain.
- Added one shared media result-directory helper. Stable subtitle exports,
  actual-page files, QA queue, summary, compatibility SRT, manual-final package,
  and formal/draft videos now use
  `<output-anchor-parent>/<source-media-stem>-处理结果/`. Normal Home output is
  beside the audio; isolated E2E report anchors remain isolated. No source or
  legacy loose file is moved or deleted.
- Task-context tests pass 5/5, stable-publication/UI tests pass 53/53, the
  manual-final editor and video-synthesis safety scripts pass, and the final
  unified regression passes 25/25 stages in 330.3 seconds. Two earlier unified
  runs identified stale path expectations and were corrected before the final
  pass. External requests, ASR, LLM, real synthesis, and paid requests are zero.

