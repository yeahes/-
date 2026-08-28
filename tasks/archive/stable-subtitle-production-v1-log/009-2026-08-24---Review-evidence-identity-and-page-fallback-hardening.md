## 2026-08-24 - Review evidence identity and page fallback hardening

- Completed the run-identity binding change for copied semantic/QA review
  evidence. A queue must match the current code revision, stable run, attempt,
  artifact directory, frozen word ledger, and subtitle spans; missing identity
  fields are rejected once the current manifest declares them.
- Added the non-strict Chinese pagination safety guard: best-effort fallback
  cannot create a page beginning with punctuation or split a glued ASCII/number
  token, and returns a recoverable failure when no safe boundary exists.
- Focused regression passes 584 tests after the final identity test; only the
  existing SQLAlchemy/spaCy deprecation warnings and bundled Windows DLL
  access-violation diagnostic were observed. The identity commit is
  `3925520`; the pagination commit follows separately.

