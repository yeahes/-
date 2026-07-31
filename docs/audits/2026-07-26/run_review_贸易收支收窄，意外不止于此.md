# Run Review: 贸易收支收窄，意外不止于此

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-26T09:45:37
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\贸易收支收窄，意外不止于此`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\贸易收支收窄，意外不止于此\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\贸易收支收窄，意外不止于此\subtitle\stable-final-manifest.json`
- SRT SHA-256: `c7b2c2c109750f4c25bb49e40af7dd9563addfcf1443baa6d05f26985d6d9619`
- Subtitle count: 286
- Validation status: passed
- Validation summary: OK
- Render blocked: False
- Timeline backend: not recorded

## Score

- Automated overall score: 83
- English max words: 14
- English average words: 8.13
- Average subtitle duration: 2860.31 ms

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

- S0020 `00:00:51,120 --> 00:00:51,520` dur=0.4s words=3 wps=7.5 zh=6 cps=15.0 | There's a lot || 要处理的内容
- S0036 `00:01:35,100 --> 00:01:35,380` dur=0.28s words=2 wps=7.14 zh=4 cps=14.29 | Okay. Well, || 好的。那么，
- S0110 `00:05:07,460 --> 00:05:08,500` dur=1.04s words=5 wps=4.81 zh=16 cps=15.38 | You would expect that, yes. || 你可能会预料到这样的做法，确实如此。
- S0133 `00:06:12,460 --> 00:06:12,940` dur=0.48s words=2 wps=4.17 zh=5 cps=10.42 | Right. Oh, || 没错。哦，还有，
- S0221 `00:10:44,540 --> 00:10:44,960` dur=0.42s words=1 wps=2.38 zh=3 cps=7.14 | Really? || 真的吗？
- S0247 `00:12:03,280 --> 00:12:03,680` dur=0.4s words=3 wps=7.5 zh=3 cps=7.5 | Not at all. || 绝不是。
- S0267 `00:13:08,060 --> 00:13:08,860` dur=0.8s words=7 wps=8.75 zh=8 cps=10.0 | And yet, I want to leave you || 然而，我想留给你们

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
