## 2026-08-09 Article-Term Correction and Manual Structural Operations

- Root cause for domain-term misses: every `technical_terms` glossary item was
  excluded from ASR correction even when the article explicitly defined a
  distinctive term and supplied alias evidence. Eligibility is now narrow and
  evidence-based; ordinary technical vocabulary remains protected.
- Root cause for surprising adjacent-row changes: row selection and boundary
  editing shared one activation path. Selection now installs only an explicit
  entry action. Direction choice previews source words; only confirmation moves
  a word-ledger boundary.
- Added a constrained two/three/four-page operation for one frozen parent cue.
  It reuses the production syntax, pause, layout, and scheduling planner instead
  of averaging characters or time. The parent contract is unchanged and every
  new page requires explicit Chinese review.
- Added reversible suffix deletion and non-destructive audio derivation. The
  shortened word ledger and final cue timeline remain ID-addressable prefixes;
  the original audio is hash-checked and never overwritten. Manifest resolution
  makes the derived audio authoritative, including callers that still pass the
  old source path. The first version is restricted to static podcast synthesis.
- The first qwindows capture found a transparent embedded entry widget: the
  table delegate English remained visible underneath the widget English. Entry
  and direction widgets now paint an opaque theme background, and a render
  assertion prevents this double-draw regression.
- Focused tests pass: article correction 29/29, stable publication 20/20,
  manual-final editor 23/23, and video-synthesis safety 24/24. Unified
  regression passes 589 tests across 24 suites plus one syntax check with zero
  failures in 338.622 seconds; `git diff --check` passes with existing
  line-ending notices only.
- Final UI evidence is under
  `E:\VideoCaptioner-e2e-runs\manual-structural-editor-20260809-final-ui`.
  The fixed DPR 1.0/1.25/1.5 captures pass 195/195 deterministic checks and
  visual review across 12 PNGs. The older transparent captures are retained and
  explicitly classified as FAIL evidence.
- The real FFmpeg fixture cut 1000ms to 1003ms, preserved the source hash, and
  proved identical-save reuse. External network, ASR, LLM, paid, and full-video
  calls are zero. No fresh arbitrary-audio E2E was run.

