# Run Review: 埃隆·马斯克眼中的未来

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-26T14:00:56
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\埃隆·马斯克眼中的未来`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\埃隆·马斯克眼中的未来\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\埃隆·马斯克眼中的未来\subtitle\stable-final-manifest.json`
- SRT SHA-256: `036498895d4ccfcc53ee7d8249a1f6d5d6dddd05ca8e8af617ab15fd2153dad4`
- Subtitle count: 345
- Validation status: passed
- Validation summary: OK
- Render blocked: False
- Timeline backend: not recorded

## Score

- Automated overall score: 84
- English max words: 14
- English average words: 8.34
- Average subtitle duration: 2794.06 ms

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

- S0019 `00:00:49,520 --> 00:00:50,260` dur=0.74s words=5 wps=6.76 zh=9 cps=12.16 | And our mission for you || 我们为你设定的任务
- S0047 `00:02:05,320 --> 00:02:05,940` dur=0.62s words=2 wps=3.23 zh=8 cps=12.9 | We're combined. || 我们所有人的总和。
- S0056 `00:02:29,280 --> 00:02:29,980` dur=0.7s words=5 wps=7.14 zh=6 cps=8.57 | I want to break down || 我想拆解一下
- S0260 `00:12:31,280 --> 00:12:31,620` dur=0.34s words=2 wps=5.88 zh=3 cps=8.82 | That's funny. || 真有趣。
- S0265 `00:12:43,180 --> 00:12:43,840` dur=0.66s words=4 wps=6.06 zh=5 cps=7.58 | No, not at all. || 不，完全没有。

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
