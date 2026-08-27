## 2026-08-17 Last-Row Editing, Manual Six-Page, Niulai, And Media Mute

- Removed the last-row boundary pre-rejection and reused the existing upper-edge
  mapping. A single fixed cue with multiple display pages can now adjust its
  internal edge; invalid rows still fail closed.
- Queued split/repage/merge actions with `QTimer.singleShot(0, ...)` after the
  context menu callback and captured stable IDs only, preventing a synchronous
  Qt model reset inside the native menu event loop.
- Kept automatic planning at four pages and added a separate explicit-manual
  maximum of six pages. The on-demand candidate workspace now searches up to
  that manual limit; automatic runs still never enumerate five/six-page output.
- Upgraded article ASR correction to v5. Article-evidenced, locally anchored
  `new lie -> Niulai` spans may merge before IDs freeze while ordinary phrases
  remain protected; high-signal scope-rejected `Yulai` is projected for review.
- Added parent-level `media_muted`, which implies `display_suppressed`. Manual
  save materializes exact cue intervals with FFmpeg `volume`, binds original
  media/cue/timing/ledger/decision/derived hashes, preserves total duration,
  and rejects tail-trim coexistence or tampering. Synthesis now resolves the
  manifest-owned derived media inside the worker before rendering.
- Focused manual-editor, real FFmpeg mute, stable-publication/UI, and synthesis
  safety tests pass. A follow-up audit also closed direct-SRT derived-media
  bypass, restored the mute media contract through undo/redo, and queued all
  context-menu merge paths by stable IDs. The final complete regression and
  `git diff --check` both exit zero.

