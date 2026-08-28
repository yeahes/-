## 2026-08-23 Translation Cache Reuse And Snapshot Queue Isolation

- Full-translation unit cache v2 now follows translation-affecting content
  instead of group numbers, fixed subtitle IDs, or internal cue boundaries.
  It includes complete English/current translation, length budget, bounded
  neighboring semantic context, article context, prompt, model, and policy.
  A v1 compatibility read preserves existing verified cache value.
- Display-page Chinese now stores and loads independently validated parent
  units. A unit may rebind to current parent/page IDs after absolute ID or word
  offsets move, but parent Chinese, page English, page duration/budget, model,
  prompt, policy, or article context changes invalidate it. Every hit reruns
  the full current page and quality contracts.
- Stable checkpoint snapshots validate a copied semantic review queue against
  the copied word ledger and frozen spans. Only the invalid snapshot copy is
  removed; valid queues and the historical source directory are preserved.
- The targeted White House page-frontier audit now selects candidates in full
  episode order before filtering requested IDs and reports local structural
  failures without discarding other results. Eleven of fourteen targets are
  solvable inside their frozen parent; three require a pre-ID boundary change.
- The complete affected pytest files pass 705/705. The complete offline
  regression passes 30/30 in 908.59 seconds. `git diff --check` reports only
  line-ending warnings. No API, GUI rerun, production artifact, cache, audio,
  checkpoint, or untracked `output/` file was changed by verification.

