## 2026-08-23 Actual-Page Audit Method And Skill

- Audited the immutable newest White House checkpoint against all 221 parent
  rows and 271 actual display pages, including neighboring parent context,
  authoritative parent Chinese, page-local Chinese, layout/timing evidence,
  and editor marks. The detailed evidence is recorded under
  `docs/audits/2026-08-23/`.
- Confirmed that similarly titled White House runs have different word ledgers
  and are not a same-input regression. Confirmed a real same-input stability
  comparison with Chocolate v27/v29: the ledger hash is identical, while v27
  passes and v29 changes parent/page plans and blocks publication.
- Added the local `audit-caption-results` Codex skill. Its standard-library
  collector is read-only, validates immutable-run and final-manifest identity,
  exposes every actual bilingual display page in chunks, detects stale review
  context, and permits A/B regression language only for matching ledgers.
- The skill validator passes. Real artifact checks reproduce the White House
  221/271/42 shape, five missing page-Chinese IDs, valid final-manifest hashes,
  and stale semantic queue; Chocolate comparison reports the expected same
  ledger and incomplete commit-only runtime identity.
- No production code, subtitle, audio, cache, checkpoint, or `work-dir`
  artifact was changed. Full pipeline regression was not run because this was
  documentation plus an external read-only skill.

