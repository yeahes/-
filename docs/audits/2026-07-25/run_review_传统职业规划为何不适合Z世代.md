# Run Review: 传统职业规划为何不适合Z世代

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-25T13:49:05
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\传统职业规划为何不适合Z世代`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\传统职业规划为何不适合Z世代\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\传统职业规划为何不适合Z世代\subtitle\stable-final-manifest.json`
- SRT SHA-256: `3c34ace583de2052ef5d339c31e165431538d40c5137cda6df023943337bc0de`
- Subtitle count: 345
- Validation status: passed
- Validation summary: OK
- Render blocked: False
- Timeline backend: not recorded

## Score

- Automated overall score: 81
- English max words: 14
- English average words: 8.38
- Average subtitle duration: 2618.41 ms

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

- S0071 `00:03:12,920 --> 00:03:14,220` dur=1.3s words=9 wps=6.92 zh=8 cps=6.15 | That's actually a really good way to put it. || 这说法其实很精辟。
- S0107 `00:04:48,080 --> 00:04:49,020` dur=0.94s words=6 wps=6.38 zh=5 cps=5.32 | Yeah, so Todd is the founder || 是的，托德是
- S0198 `00:08:55,780 --> 00:08:56,940` dur=1.16s words=8 wps=6.9 zh=11 cps=9.48 | Let me see if I have this straight. || 我来看看我理解对了没有。
- S0204 `00:09:13,020 --> 00:09:14,120` dur=1.1s words=3 wps=2.73 zh=19 cps=17.27 | doing the job? || 来完成工作时，为什么还要雇用更多的人类呢？
- S0317 `00:14:52,140 --> 00:14:52,980` dur=0.84s words=7 wps=8.33 zh=6 cps=7.14 | You don't have to have it figured || 你不必把一切
- S0329 `00:15:29,760 --> 00:15:31,440` dur=1.68s words=8 wps=4.76 zh=22 cps=13.1 | at and where you can gain some leverage. || 什么，在哪里能获得一些杠杆，这是完全正常且必要的。

### Leading Punctuation Candidates

- S0021 `00:00:59,140 --> 00:01:01,240` | that 40% of recent American graduates || ，40%的美国应届毕业生
- S0031 `00:01:26,060 --> 00:01:29,600` | when AI is threatening to make entire professions extinct. || ，当人工智能威胁要让整个职业消亡时。

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
