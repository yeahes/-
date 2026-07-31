# Run Review: 中国能统治全球AI市场吗？

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-26T09:37:11
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\中国能统治全球AI市场吗？`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\中国能统治全球AI市场吗？\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\中国能统治全球AI市场吗？\subtitle\stable-final-manifest.json`
- SRT SHA-256: `190f430bb39ca61d0bbe7a281323353a6b5ffef612f20cf0d69162a8c71ccfa7`
- Subtitle count: 295
- Validation status: passed
- Validation summary: OK
- Render blocked: False
- Timeline backend: not recorded

## Score

- Automated overall score: 86
- English max words: 14
- English average words: 8.74
- Average subtitle duration: 2915.12 ms

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

- S0026 `00:01:15,320 --> 00:01:16,020` dur=0.7s words=5 wps=7.14 zh=8 cps=11.43 | this. Because on the surface, || 一下。因为表面上看，
- S0028 `00:01:19,820 --> 00:01:20,700` dur=0.88s words=6 wps=6.82 zh=9 cps=10.23 | Sure. It does look like that. || 当然。看起来确实如此。
- S0136 `00:06:41,980 --> 00:06:42,700` dur=0.72s words=5 wps=6.94 zh=8 cps=11.11 | I mean, in the West, || 我的意思是，在西方，

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
