## 2026-08-10 Article Vocabulary Page Timing And Title Readability

- Reproduced early vocabulary cards when a selected phrase belonged to a later
  article display page but inherited the parent cue start. Article scheduling
  now binds each card to the final page containing its exact phrase and drops
  cross-page or ambiguous matches; dark-template timing is unchanged.
- Reproduced `中国年轻人为 / 何不爱留学了？`. The article opening title now
  chooses balanced breaks only from deterministic Chinese token or punctuation
  boundaries, preserves explicit newlines, and uses the bundled Heavy CJK face.
- Five focused card-timing checks, four focused title checks, the complete
  stable-caption script, and the 25-stage unified regression pass. The unified
  run completed in 395.1 seconds.
- Visual evidence:
  `tests/caption_audit/out/article-vocab-page-alignment-after-20260810.png` and
  `tests/caption_audit/out/study-abroad-title-wrap-heavy-20260810.png`.
- No prompt/cache schema, model selection, ASR, English segmentation, Chinese
  translation, fixed ID, final timeline, export, manifest, or synthesis-entry
  contract changed. No fresh full video was encoded.

