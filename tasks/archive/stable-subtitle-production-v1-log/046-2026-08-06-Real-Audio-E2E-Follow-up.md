## 2026-08-06 Real-Audio E2E Follow-up

- Replayed the same read-only `中国AI为何更省钱？.m4a` through the current
  stable pipeline with `SubtitleTask.source_audio_path` pointing at the
  original audio and all run output isolated under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-followup`.
- Subtitle gate passed: 266/266 fixed IDs, 2,897 ledger words, complete English
  and Chinese mappings, final timeline `PASS`, applied backend
  `whisperx-time-only`, no overall fallback, and no `source_audio_missing`.
  The 64.8-66.5s interval remains covered by `S0017` through 67.975s.
- External request count was 0 because all translation/allocation work came
  from the isolated E2E cache. WhisperX had eight per-word stable-ledger
  timing retentions, but did not trigger an overall fallback.
- Synthesis did not reach ffmpeg: the renderer's fixed-font structural gate
  rejected `S0052`, `S0176`, `S0196`, and `S0258` with
  `render_structural_overflow / no_fixed_font_page_partition`. No video was
  created. This was recorded as a blocking renderer risk instead of bypassed
  by altering English, IDs, timing, font size, or visual pagination.

