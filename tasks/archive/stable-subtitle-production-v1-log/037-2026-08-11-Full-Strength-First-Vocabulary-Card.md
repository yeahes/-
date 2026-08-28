## 2026-08-11 Full-Strength First Vocabulary Card

- Reproduced the reported pale first card as a renderer-cache interaction. The
  title-to-card transition depended on frame time, while the cached frame key
  contained only card identity and subtitle state. A partially blended first
  frame could therefore remain unchanged until the following subtitle.
- Removed the first-card fade and its time-dependent rendering branch. The
  right panel still shows the episode title before the first eligible card; at
  the card's exact final-page start it switches directly to the complete card,
  which remains until replacement.
- Added a focused regression that checks both the first and a later card at
  their exact trigger times, verifies full card drawing, and rejects image
  blending. Vocabulary selection, timing, subtitles, IDs, SRT/ASS, manifest,
  and synthesis routing are unchanged.
- Two focused tests and Python syntax compilation pass. A pixel comparison
  confirms that the trigger frame's card area is identical to the settled card
  0.2 seconds later, while the preceding title frame differs. The complete
  25-stage regression exits zero in 380.5 seconds. Visual evidence:
  `tests/caption_audit/out/article-vocab-full-strength-first-card-20260811.png`.

