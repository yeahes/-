## 2026-08-15 Final Parent Chinese State Ownership Fix

- Traced the oil sample's `display_page_translation_invalid` failure to two
  diverging in-memory projections of the same fixed-ID parent Chinese. Final
  punctuation alignment changed `ASRDataSeg.translated_text`, while
  `_last_subtitle_items` still held the pre-alignment values.
- Added `_sync_fixed_id_parent_chinese_state()` after final display coverage,
  punctuation handling, and optional Chinese compression. It validates count,
  ordered IDs, English, and word spans before updating only `translated`.
- Kept the downstream `fixed-ID parent Chinese drifted` check unchanged and
  added coverage proving a later real Chinese mutation still fails closed.
- Focused tests, both owning full test scripts, and the complete 26-stage
  regression pass. The failed 147-cue oil checkpoint replayed read-only with
  three pre-sync differences and zero post-sync differences.

