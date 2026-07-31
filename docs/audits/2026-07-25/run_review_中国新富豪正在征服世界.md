# Run Review: 中国新富豪正在征服世界

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-25T17:09:26
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\中国新富豪正在征服世界`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\中国新富豪正在征服世界\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\中国新富豪正在征服世界\subtitle\stable-final-manifest.json`
- SRT SHA-256: `0d9d4d0188fa41190a19190e930c7c94ae8074abe026fa844f2806356b320041`
- Subtitle count: 395
- Validation status: passed
- Validation summary: OK
- Render blocked: False
- Timeline backend: not recorded

## Score

- Automated overall score: 83
- English max words: 14
- English average words: 7.82
- Average subtitle duration: 2560.1 ms

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

- S0108 `00:04:31,160 --> 00:04:31,520` dur=0.36s words=2 wps=5.56 zh=8 cps=22.22 | They did. || 他们确实这么做了。
- S0199 `00:09:03,320 --> 00:09:03,940` dur=0.62s words=4 wps=6.45 zh=4 cps=6.45 | What do you mean? || 什么意思？
- S0219 `00:09:53,660 --> 00:09:54,940` dur=1.28s words=8 wps=6.25 zh=11 cps=8.59 | Let me see if I have this right. || 我来看看我的理解对不对。
- S0292 `00:13:14,180 --> 00:13:15,080` dur=0.9s words=3 wps=3.33 zh=11 cps=12.22 | Hobbies that parents || 那些曾让全世界的父母们
- S0317 `00:14:32,160 --> 00:14:33,320` dur=1.16s words=7 wps=6.03 zh=5 cps=4.31 | the ones who are used to operating || 习惯了运作
- S0345 `00:15:57,640 --> 00:15:58,920` dur=1.28s words=8 wps=6.25 zh=15 cps=11.72 | In fact, none of them would even speak || 事实上，他们中没有一个人愿意开口
- S0363 `00:16:38,420 --> 00:16:39,600` dur=1.18s words=10 wps=8.47 zh=14 cps=11.86 | if the public doesn't even know what you look like. || 如果公众甚至不知道你长什么样

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
