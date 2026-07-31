# Run Review: 在中国，连健身都是一场内卷

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-28T02:06:00
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\在中国，连健身都是一场内卷`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\在中国，连健身都是一场内卷\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\在中国，连健身都是一场内卷\subtitle\stable-final-manifest.json`
- SRT SHA-256: `4829adeab02808a5c0544ed3a5b49f027855e00796b359fc2757993c89006fff`
- Subtitle count: 372
- Validation status: passed
- Validation summary: OK
- Render blocked: False
- Timeline backend: whisperx-time-only

## Score

- Automated overall score: 85
- English max words: 14
- English average words: 8.58
- Average subtitle duration: 2883.19 ms

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

- S0158 `00:07:42,569 --> 00:07:42,949` dur=0.38s words=1 wps=2.63 zh=2 cps=5.26 | No. || 不是。
- S0164 `00:08:02,543 --> 00:08:04,004` dur=1.46s words=10 wps=6.84 zh=12 cps=8.21 | I kind of look at him as a human shock || 我有点把他看作一个人力减
- S0166 `00:08:05,605 --> 00:08:06,746` dur=1.14s words=7 wps=6.13 zh=7 cps=6.13 | That's a good way to put it. || 这个比喻很贴切。
- S0245 `00:11:53,326 --> 00:11:54,126` dur=0.8s words=6 wps=7.5 zh=3 cps=3.75 | You have to look at it || 你得从

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
