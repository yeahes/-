## 2026-08-10 Manual Editor State And Latency Hardening

- Audited split, visual-boundary move, save, reload, and page/parent view
  transitions against the real 353-page procrastination package. Repeated full
  derivation of 38 overridden plans, GUI-thread session copying, destructive
  boundary-Chinese invalidation, and reload-failure parent fallback were the
  four root causes.
- Added state- and artifact-bound complete-model caching plus parent-level
  preview reuse. The cache fails closed on any cue, edit, override, recovered
  evidence/draft, manifest, page artifact, draft artifact, or boundary-evidence
  file change, and callers receive isolated row copies.
- A page-boundary move preserves existing Chinese visibly as an unconfirmed
  draft on only the two changed pages and leaves every unaffected page exact.
  Save snapshot copying now runs after the table is disabled and inside the
  worker; mutation during save is rejected.
- A save/reload verification failure keeps the current in-memory session and
  actual-page view instead of forcing parent rows. It clears synthesis authority
  and asks for another save without requiring import or audio rerun.
- Real read-only timings: cached full model 0.012-0.014s, split 0.159s plus
  0.122s refresh, boundary move 0.136s plus 0.129s refresh; 351 unaffected pages
  have zero identity/text/timing drift. A cross-parent formal-boundary move took
  0.940s plus 0.143s refresh with zero drift across 349 unaffected pages.
  Manual editor, 60 UI/publication tests, syntax compilation, `git diff --check`,
  and all 25 regression stages pass; the final unified run took 381.4 seconds.

