# Tail-Trim Page Timing Handoff

Status: complete
Last verified: 2026-08-20 06:16:50 Asia/Shanghai
Branch: main
Verified HEAD: ab6ea58035ddbab1afe4a3631c28de8886f29332

## Outcome

Tail deletion now publishes one authoritative final end for the last SRT cue,
last frozen display page, and derived media cut. The synthesis loader accepts
the saved multipage artifact.

## Root Cause

The manual editor rebuilt parent cue timing after deleting the tail but reused
the old frozen display-page edge. Editor validation and synthesis reload then
observed different timelines.

## Contract

- The media cut may cap only the last cue's ordinary tail padding.
- The retained final word envelope must remain fully covered.
- Frozen page IDs, English, word ranges, internal boundaries, Chinese, and
  layout remain unchanged; only the first and last parent edges are synced.
- Ordinary subtitle and pagination validation remain unchanged.

## Verification

- `runtime\python.exe tests\test_final_cue_timeline.py`
- `runtime\python.exe tests\test_manual_final_subtitle_editor.py`
- `runtime\python.exe scripts\run_regression.py`
- `git diff --check`

All passed offline. No external model request or production output write was
used.

## Next Action

Restart the GUI, reopen the current manual-final package, save it once under
the fixed code, and synthesize again. ASR and translation do not need rerunning.
