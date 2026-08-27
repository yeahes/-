## 2026-08-06 Fixed-ID Display-Page Contract E2E

- Replaced proportional parent-Chinese slicing with a post-timing display-page
  contract. Page IDs are deterministic children of the frozen subtitle ID;
  parent English, ID, word span, cue timing, SRT, and ASS structure stay fixed.
- Page responses are checked for exact ID/cardinality, semantic ownership,
  fixed-font fit, reading speed, cache fingerprint, contract hash, and artifact
  digest. Writes are atomic and failures block before synthesis.
- Added focused fixtures for reordered `S0078`, monotonic `S0252`, stale or
  tampered artifacts, write failure, cache invalidation, and parent-contract
  drift. Added generic page-boundary regressions for non-finite complements and
  numeric compound heads.
- Real E2E passed at
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r1`:
  262 frozen cues, 2,897 words, 46 multipage parents / 94 pages, final timeline
  `PASS`, `whisperx-time-only`, no overall fallback, no
  `source_audio_missing`, and unchanged frozen signature.
- Final synthesis produced `final-video.mp4` (46,217,829 bytes, 1003.66s,
  1920x1080 H.264/AAC). Production ffmpeg fully decoded it with zero errors;
  ffprobe was unavailable. Total external requests across four attempts: 11;
  the successful attempt used one and synthesis used zero.
- Targeted visual validation passed 22/22 sampled frames for `S0062`, `S0078`,
  `S0111`, `S0252`, all associated +/-80ms page transitions, and the
  64.8/65.6/66.4s speech interval. No sampled shrink, crop, overlap, blank, or
  page reversal was observed. The report does not claim full-video frame-by-
  frame manual review.
- Remaining risk: a separate unseen audio has not yet established a 90% blind
  reliability claim. Manual-final multipage Chinese overrides remain
  fail-closed until a page-aware editor exists.

