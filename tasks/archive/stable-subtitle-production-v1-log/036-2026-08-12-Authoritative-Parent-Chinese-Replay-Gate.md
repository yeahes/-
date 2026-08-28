## 2026-08-12 Authoritative Parent-Chinese Replay Gate

- Added and tested the fixed-ID authoritative Chinese record contract. New
  stable runs publish `authoritative-parent-chinese.json`; legacy schema-v2
  packages are accepted only through an agreement-checked compatibility path.
- Replayed only the two requested real packages in read-only mode:
  `D:\经济学人\2026-08-08\如何停止拖延\如何停止拖延-处理结果` and
  `D:\经济学人\2026-08-15\中国已成为世界石油强国\中国已成为世界石油强国-处理结果`.
- Both loaded successfully and passed an in-memory undo/redo round trip. File
  mtime, byte size, and SHA-256 snapshots were identical before and after.
- No production subtitle, audio, video, cache, or manifest was written.

### Legacy blocked-checkpoint compatibility

- The first complete regression exposed that render-blocked editable checkpoints
  can legitimately lack `translations.json` when page translation failed before
  publication. The authority loader now permits that exact manifest state and
  builds an in-memory legacy record from frozen parent cues; published packages
  still require the translation artifact.
- Video-synthesis safety and stable-publication tests pass after the fix. The
  following full regression completes all stages without a failure line.

