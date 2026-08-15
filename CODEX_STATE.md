# Project State
Status: complete
Last verified: 2026-08-15 19:53:09 Asia/Shanghai
Branch: main
Verified HEAD: fe3d2832831a7d75a0a6f1b220644f1ac6a4103b
Working tree: only untracked `.workbuddy/`, intentionally excluded

## Current Goal
Harden Pro/Flash translation ownership and keep parent Chinese separate from display-page Chinese.

## Confirmed Facts
- Full semantic-group translation uses Pro; ordinary fixed-ID and page allocation use Flash; quality retry sends only the affected complete scope to Pro.
- Cache contract v2 binds the actual request model, with a validated one-release read path for older full-translation caches.
- Parent Chinese is authoritative; page Chinese is an independent display projection and cannot overwrite it.
- Legacy schema-v2 pages load only when aggregate Chinese equals current parent authority; stale authority refs fail closed.
- Two-parent integration coverage proves unaffected page projections remain byte-equivalent through a scoped Pro retry.
- The complete 26-stage regression passes at `fe3d283`; focused caption/page suites and `git diff --check` pass.
- Read-only replay reopened the 147-cue oil and 213-cue Mixue packages with identical recursive size, mtime, and SHA-256 snapshots.

## Approved Decisions
- Preserve fixed English, subtitle IDs, word spans, timing, page geometry, and the current rendering path.
- Keep `.workbuddy/` untracked and out of commits.

## Relevant Paths
- `app/core/subtitle_processor/screen_editor.py`
- `app/core/subtitle_processor/authoritative_parent_chinese.py`
- `app/thread/subtitle_thread.py`
- `docs/CURRENT_STATE.md`

## Last Verification
- Commit `fe3d283`; full regression, focused suites, syntax, diff, and two real-package read-only replays pass.

## Next Action
Restart the GUI and run one fresh article-assisted audio to measure real Pro/Flash translation quality and latency.

## Do Not Regress
- Page Chinese must never write back into parent Chinese; LLM output must never change English, IDs, word spans, timing, or page geometry.

## Unknowns
- No paid Pro/Flash blind run was made during this offline verification.
