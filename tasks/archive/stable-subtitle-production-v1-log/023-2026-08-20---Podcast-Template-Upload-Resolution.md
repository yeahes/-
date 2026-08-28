## 2026-08-20 - Podcast Template Upload Resolution

- Added one `1440p平台上传` switch to the synthesis page for both podcast
  templates. Off persists `1080p`; on persists `1440p平台上传`, and each synthesis
  task snapshots the selected mode.
- The standard path remains 1920x1080. Upload mode applies Lanczos scaling to
  2560x1440 and keeps 25fps, H.264 High Profile, yuv420p, libx264 slow/CRF 15,
  two B-frames, closed GOPs, AAC 48kHz, and fast-start metadata.
- The smoke output at
  `output/platform-upload-audit/article-template-1440p-smoke-20260820.mp4`
  was decoded and verified as 2560x1440, 25fps, H.264 High, yuv420p, and AAC
  48kHz. The complete 29-check regression passes in 958.44 seconds.

