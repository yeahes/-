# Project State

Status: complete
Last verified: 2026-08-06 15:06:05 Asia/Shanghai
Branch: main
Verified HEAD: 4f3bc8035f549d488ccf58b04e25020e561970ff
Working tree: clean after the documentation handoff commit

## Current Goal
Maintain the validated fixed-parent-ID display-page translation contract.

## Confirmed Facts
- Real-audio E2E `china-ai-cheaper-e2e-20260806-page-contract-r1` passed with 262 fixed IDs, 2,897 ledger words, 46 multipage parents, and 94 validated pages.
- Frozen ID order, English, and word spans match `china-ai-cheaper-e2e-20260806-global-boundaries-r2` exactly.
- Final timing is `PASS`, applied backend is `whisperx-time-only`, overall fallback is false, `source_audio_missing` is absent, and 64.8-66.5s is covered by S0017.
- Final video exists at the E2E root, is 1003.66s / 1920x1080 H.264/AAC, and fully decodes with zero ffmpeg errors. ffprobe is unavailable.
- Targeted visual validation passed 22/22 sampled frames, including four
  multipage cues, all associated +/-80ms transitions, and 64.8/65.6/66.4s.
  No sampled shrink, crop, overlap, blank, or reversed page was found.
- Total external requests across the four page-contract attempts: 11. Synthesis used zero.

## Approved Decisions
- Preserve frozen English, parent subtitle IDs, word spans, cue timing, fixed fonts, and SRT/ASS ownership.
- Add page IDs and page-level Chinese only after the final word timeline is frozen; invalid or missing page artifacts fail before ffmpeg.
- Bind page artifacts to the manifest using SHA-256 and contract hash; artifact writes fail closed.

## Relevant Paths
- `app/core/subtitle_processor/stable_display_planner.py`
- `app/core/subtitle_processor/stable_display_page_contract.py`
- `app/core/utils/podcast_learning_video.py`
- `app/core/subtitle_processor/screen_editor.py`
- `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r1`

## Last Verification
- Unified regression, focused page-contract tests, E2E subtitle gate, synthesis,
  manifest/digest checks, frozen-signature comparison, and complete ffmpeg
  decode passed. Final unified regression is 17/17 and `git diff --check`
  passes after documentation. Targeted visual validation is 22/22.

## Next Action
Run one unrelated blind audio before raising unseen-audio confidence above 85%.

## Do Not Regress
- No proportional Chinese fallback, font shrinking, English LLM segmentation, timing rewrite, or sample-specific rule.

## Unknowns
- Blind reliability on an unrelated unseen audio has not been measured.
- Manual-final multipage Chinese edits do not yet have a page-aware editor.
