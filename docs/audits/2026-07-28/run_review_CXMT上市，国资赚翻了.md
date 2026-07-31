# Run Review: CXMT上市，国资赚翻了

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-28T08:49:45
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\CXMT上市，国资赚翻了`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\CXMT上市，国资赚翻了\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\CXMT上市，国资赚翻了\subtitle\stable-final-manifest.json`
- SRT SHA-256: `3d08e6881df5de5e95955e98b41cf4eeb049f76d47bdd41d4506e406f6830a54`
- Subtitle count: 379
- Validation status: passed
- Validation summary: OK
- Render blocked: False
- Timeline backend: whisperx-time-only

## Score

- Automated overall score: 84
- English max words: 14
- English average words: 7.89
- Average subtitle duration: 2711.2 ms

This note is based on static inspection of manifest, final SRT, and generated audit data. It is not a full manual audio listening pass.

## ERROR Codes

- None

## WARNING Codes

- None

## Positive Findings

- Stable final SRT exists: yes
- Manifest exists: yes
- No hard ERROR: yes
- No continuous English-Chinese left-shift detected by static heuristics.

## Detected Problems

### Timing/Reading-Speed Candidates

- S0023 `00:01:03,682 --> 00:01:04,923` dur=1.24s words=8 wps=6.45 zh=6 cps=4.83 | If we connect this to the bigger picture, || 从更大背景看，
- S0272 `00:12:32,748 --> 00:12:33,568` dur=0.82s words=5 wps=6.1 zh=5 cps=6.1 | But on the other hand, || 但另一方面，
- S0312 `00:14:19,632 --> 00:14:20,653` dur=1.02s words=7 wps=6.86 zh=7 cps=6.86 | That's a great way to put it. || 这个比喻很贴切。
- S0318 `00:14:34,742 --> 00:14:35,663` dur=0.92s words=6 wps=6.51 zh=5 cps=5.43 | since the start of the month, || 自本月以来，
- S0340 `00:15:29,280 --> 00:15:30,181` dur=0.9s words=6 wps=6.66 zh=6 cps=6.66 | So I have to push back || 所以我得收回

### Leading Punctuation Candidates

- None

### Adjacent Duplicate Candidates

- None

## Warning Examples

- None

## Root-Cause Notes

- If many timing candidates appear with very short durations, prioritize word timestamp quality checks before prompt changes.
- If leading punctuation appears, use the generic leading punctuation repair rather than sample-specific text rules.
- If duplicate adjacent subtitles appear, check ASR duplicate emission before changing Chinese allocation.
- If WARNING exists but SRT is usable, keep it as review guidance unless it becomes a repeat pattern across multiple runs.

## Next Action

- Review the listed candidate lines in video/audio if this run will be used for publishing.
- Do not add sample-specific rules from this note alone.
- Prefer low-risk generic validators for repeated patterns across multiple notes.
