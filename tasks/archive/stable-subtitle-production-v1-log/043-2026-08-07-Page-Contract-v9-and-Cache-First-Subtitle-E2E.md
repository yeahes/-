## 2026-08-07 Page Contract v9 and Cache-First Subtitle E2E

- Reordered display-plan selection so high-confidence structural risk and
  medium-confidence review risk are considered before measured visual cost;
  low-confidence hints remain soft. This lets a readable 50px static page
  beat a risky page turn without making uncertain ordinary cues shrink.
- Bumped only the page planner contract to
  `article-fixed-font-pages-v9`. ASR, complete-translation, and fixed-ID
  allocation caches retain their independent fingerprints.
- Focused page suites and the unified regression pass. Offline replay planned
  both real-audio samples completely with zero external requests; delegated
  representative frame checks reported zero structural, word-coverage,
  hard-boundary, font-floor, minimum-duration, blank, crop, overlap, or
  transition failures.
- The cache-first `How to Identify AI Writing Style` subtitle E2E completed at
  `E:\VideoCaptioner-e2e-runs\ai-writing-style-page-contract-v9-e2e-20260807-r1`.
  It reran current boundaries, WhisperX time-only, v9 planning, page Chinese,
  and publication from the same-audio ASR artifact: 207 cues, 1,993 words,
  final timeline `PASS`, no `source_audio_missing`, and no overall backend
  fallback. Three local expansion/compression protections are recorded.
- Full translation/allocation reused 17 cached batches. One v9 page-translation
  cache miss produced one external request and is now cached. The production
  page artifact is `PASS` with 233 pages, 26 transitions, and one non-blocking
  S0082 Chinese-fragment review.
- Delegated pre-synthesis validation passed all 207 IDs, 1,993 words, 233
  pages, 26 transitions, and 17 representative page/transition frames with
  zero structural, content, crop, overlap, blank, font-floor, or transition
  failures.
- Final synthesis consumed the stable manifest and original audio directly,
  disabled unrelated AI vocabulary cards, and made zero external requests. It
  completed in about 6 minutes 49 seconds and wrote `final-video.mp4`
  (30,157,031 bytes) under the E2E run.
- The actual MP4 fully decoded 16,684 frames over 667.341497 seconds. The final
  validator extracted 291 unique frames covering every page midpoint, every
  transition before/after pair, three timing probes, and S0082. Decode, crop,
  bilingual overlap, blank, wrong-page/content, transition, word-envelope,
  and alignment-probe failure counts were all zero. S0082 remains only a
  non-blocking Chinese continuation punctuation/fluency review; no automatic
  rewrite or repeat synthesis was performed.

