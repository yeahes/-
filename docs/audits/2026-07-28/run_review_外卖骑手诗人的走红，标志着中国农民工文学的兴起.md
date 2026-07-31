# Run Review: 外卖骑手诗人的走红，标志着中国农民工文学的兴起

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-28T01:32:35
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\外卖骑手诗人的走红，标志着中国农民工文学的兴起`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\外卖骑手诗人的走红，标志着中国农民工文学的兴起\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\外卖骑手诗人的走红，标志着中国农民工文学的兴起\subtitle\stable-final-manifest.json`
- SRT SHA-256: `7345c843b25abb5969e5434df73075283ebe58b6656525860686adf119af8bc3`
- Subtitle count: 310
- Validation status: passed
- Validation summary: OK
- Render blocked: False
- Timeline backend: whisperx-time-only

## Score

- Automated overall score: 84
- English max words: 14
- English average words: 8.46
- Average subtitle duration: 2865.05 ms

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

- S0032 `00:01:24,280 --> 00:01:24,860` dur=0.58s words=5 wps=8.62 zh=8 cps=13.79 | we really have to look || 我们确实需要审视
- S0065 `00:02:58,882 --> 00:02:59,322` dur=0.44s words=2 wps=4.55 zh=4 cps=9.09 | right? Yeah. || 对吧？是的。
- S0078 `00:03:32,123 --> 00:03:32,844` dur=0.72s words=5 wps=6.93 zh=4 cps=5.55 | right in front of him. || 就在眼前。
- S0193 `00:09:32,322 --> 00:09:32,442` dur=0.12s words=1 wps=8.33 zh=3 cps=25.0 | And || 另一位
- S0268 `00:13:06,194 --> 00:13:06,654` dur=0.46s words=3 wps=6.52 zh=5 cps=10.87 | Oh, I see. || 哦，我明白了。

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
