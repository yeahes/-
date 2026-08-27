## 2026-08-08 V16 Frozen Whole-Episode Page Plan

- Root cause: a validated whole-episode page sequence was later replanned by
  the per-cue renderer. The replacement page identity no longer matched the
  fixed page-Chinese artifact, producing
  `missing_or_invalid_display_page_translations` downstream.
- `article-fixed-font-pages-v16` makes an applied `frozen_*` plan authoritative
  for renderer, editor preview, and manual-final save. It also removes
  `medium_risk_count` as an absolute whole-sequence rejection, protects tight
  complements/modifiers, and prevents a finite verb such as `and` from being
  misclassified as a modifier boundary.
- The planner now compares whole-episode combinations of already valid
  cue-local plans and penalizes adjacent dense pages. It preserves fixed parent
  IDs, English, word ranges, cue timing, and the 56/54/52/50px font floor; only
  a 50px last-resort page may use three English lines.
- Old page Chinese is not reused after parent-level Chinese polish unless its
  ordered aggregate exactly equals the current parent Chinese. Error artifacts
  may expose identity-validated pages for editing, but cannot authorize formal
  synthesis.
- Offline rebuild output:
  `E:\VideoCaptioner-e2e-runs\study-abroad-page-contract-v16-final-r1-20260808`.
  It contains 261 parent cues, 2,862 words, 303 pages, 37 multipage parents,
  50px minimum English, eight controlled three-line pages,
  `render_blocked=false`, and a PASS display artifact. External requests: 0.
- Frame validation reused 907 existing PNGs and reports PASS: 303 midpoints,
  302 transition pairs, 261/261 parent matches, and zero crop, overlap, blank,
  transition, or page-induced flash errors. Fifteen short source-owned
  single-page cues remain warnings. No new rendering or video synthesis ran.
- Seven low-confidence cross-page Chinese mappings remain explicit editor
  review points: `S0118`, `S0158`, `S0196`, `S0214`, `S0238`, `S0240`, and
  `S0247`.
- `tests/test_stable_caption_rules.py` passes 377/377. Unified regression passes
  25/25 in 313.799 seconds.

