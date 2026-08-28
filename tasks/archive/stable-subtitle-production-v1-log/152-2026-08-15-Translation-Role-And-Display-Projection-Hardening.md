## 2026-08-15 Translation Role And Display Projection Hardening

- Complete semantic-group translation remains a Pro-owned request. Ordinary
  fixed-ID and display-page allocation use Flash; deterministic quality retry
  sends only the affected complete group or parent page set to Pro.
- Chinese cache contract v2 binds the actual request model and no unrelated
  model role. Verified role-coupled v1 full-translation caches retain a narrow
  migration path, so changing Flash does not invalidate a valid Pro result.
- Parent Chinese remains the fixed-ID semantic authority. Page Chinese is a
  separate display projection and cannot write back into the parent. New page
  projections carry their exact source-parent Chinese text and hash.
- Legacy schema-v2 projections without source-parent text load only when their
  aggregate Chinese exactly equals current parent authority. Existing stale
  authority refs and conflicting aggregate Chinese fail closed.
- A two-parent client-mock regression proves the initial Flash request carries
  both parents, the Pro retry carries only all pages of the reviewed parent,
  the unaffected parent projection is byte-equivalent after merge, residual
  naturalness remains REVIEW, and parent Chinese/English/ID/word/timing fields
  remain unchanged.
- Focused role, cache, page, caption, syntax, and diff checks pass. The full
  26-stage regression completes successfully. Read-only loading of the 147-cue
  oil and 213-cue Mixue packages changed no file size, mtime, or SHA-256 and
  made no ASR, LLM, synthesis, network, or paid request.

