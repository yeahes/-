## 2026-08-26 - Relative-clause pagination boundary guard

- Replayed the newest unreviewed output offline: 203 fixed parents, 34
  multipage parents, 73 pages, and final timeline validation passed. English
  quality coverage remains partial at 83/203; no reviewed audio was rerun.
- Root cause for the observed `person | who` page turn was not the word
  `who` itself. Frozen syntax evidence showed a relative-clause subject/verb
  boundary followed by another finite-predicate boundary, so the right page
  still depended on the antecedent noun on the previous page.
- Added a deterministic page-boundary invariant in
  `app/core/utils/podcast_learning_video.py`: this structure is excluded from
  automatic page plans but remains available to explicit manual review. Valid
  `professors | who have ...` and `understand | how ...` boundaries retain
  their existing behavior.
- Added regression coverage for both the rejected and accepted relative-clause
  cases. Focused checks pass; the full article readability contract is 108/109
  because the pre-existing S9522 fixture still expects `into` while the
  current planner selects `in`.

