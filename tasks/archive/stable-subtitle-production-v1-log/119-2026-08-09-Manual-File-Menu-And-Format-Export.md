## 2026-08-09 Manual File Menu And Format Export

- The manual-final file menu no longer relies on action visibility for
  `兼容字幕校正` and `文稿提示`. The installed `RoundMenu` keeps hidden actions
  in its custom list, so manual mode now removes them and ordinary mode restores
  them before settings without duplicate entries.
- Restored the existing format-export dropdown in manual-final mode under the
  explicit `导出字幕` label. TXT export remains available and preserves the
  selected bilingual layout; no subtitle, page, timing, manifest, or synthesis
  contract changed.
- Focused tests pass 3/3, stable publication passes 51/51, the unified
  regression passes 25/25 stages (about 653 items) in 343.325 seconds, and
  `git diff --check` passes. No external request or media pipeline ran. An
  offscreen menu capture crashed before creating an image, so production GUI
  visual confirmation remains the next action.

