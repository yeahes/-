## 2026-08-02 Structural Migration

- Consolidated stable English cutting into
  `ScreenSubtitleEditor._finalize_stable_english_boundaries()`.
- Removed the article-template layout recut from the pre-ID path. This removes
  a template-dependent writer of English subtitle boundaries while retaining
  the renderer's existing text wrapping.
- Added `stable_pipeline_contracts.py` as the shared serialization and hash
  contract for allocation-isolation checks. This is the first extraction from
  `screen_editor.py`; it preserves the existing artifact schema.
- Unified the word-limit contract: 6-12 words is the visual target, 16 is the
  normal stable-cut maximum, and 17-19 requires an audited parser-confirmed
  grammar exception. Allocation-only replay now uses the same 16-word fallback
  when reading older manifests.
- Moved selective Chinese polish onto the allocation candidate comparator used
  by allocation retry. Retry still requires a proven high-confidence repair;
  polish only requires an ID-valid, non-regressive candidate and records the
  same comparison evidence.
- Moved post-allocation Chinese compression and same-group reallocation onto
  that same evidence contract. A candidate must reduce local reading pressure
  and cannot add a semantic, entity, number, negation, duplicate, fragment, or
  adjacent-naturalness regression. Rejected candidates restore the original
  fixed-ID Chinese values.

