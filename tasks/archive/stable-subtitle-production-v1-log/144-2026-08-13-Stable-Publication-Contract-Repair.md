## 2026-08-13 Stable Publication Contract Repair

- Reproduced `authoritative_parent_chinese_ledger_mismatch` as a semantic hash
  ownership conflict: stable production and manual loading described the same
  word ledger with different payloads.
- Added `canonical-word-ledger-v1` as the shared ordered identity over surface,
  normalized, start-ms, and end-ms fields. Stable production, manual loading,
  manual save, and formal boundary evidence now use the same helper. Legacy
  manual schema below version 4 retains a narrow compatibility path.
- Made display-page export a required publication step. Export failure raises
  `stable_display_page_export_failed`, and the discoverable root success
  manifest is written only after display artifacts succeed.
- Added cross-owner hash and publication-failure regression coverage. Cached
  replay of `AI竞赛：中美殊途` succeeded from its immutable run-local subtitle
  with 226 cues and 2,596 words.
- Removed the abandoned pause-insensitive stranded-complement tests and false
  completion record. That approach replaced one poor cut with another and is
  not production behavior.

