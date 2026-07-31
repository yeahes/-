# Run Review: 为何女性养家还是这么少见？

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-28T20:59:56
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\为何女性养家还是这么少见？`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\为何女性养家还是这么少见？\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\为何女性养家还是这么少见？\subtitle\stable-final-manifest.json`
- SRT SHA-256: `fc4866e5a06f81f522420c99d915ab33f0781870264bec71514d0ce0d3c59287`
- Subtitle count: 358
- Validation status: passed
- Validation summary: WARNING
- Render blocked: False
- Timeline backend: whisperx-time-only

## Score

- Automated overall score: 76
- English max words: 17
- English average words: 9.04
- Average subtitle duration: 2818.24 ms

This note is based on static inspection of manifest, final SRT, and generated audit data. It is not a full manual audio listening pass.

## ERROR Codes

- None

## WARNING Codes

- suspicious_cut: 1
- reading_speed_warning: 1
- duplicate_chinese: 1
- asr_suspicious: 1
- chinese_semantic_group_warning: 1

## Positive Findings

- Stable final SRT exists: yes
- Manifest exists: yes
- No hard ERROR: yes
- No continuous English-Chinese left-shift detected by static heuristics.

## Detected Problems

### Timing/Reading-Speed Candidates

- S0040 `00:02:10,000 --> 00:02:10,940` dur=0.94s words=6 wps=6.38 zh=6 cps=6.38 | Yeah, and they also make up || 是的，她们还占
- S0106 `00:05:22,740 --> 00:05:23,660` dur=0.92s words=7 wps=7.61 zh=10 cps=10.87 | Hold on. I really have to push || 等等。我在这里真的必须
- S0186 `00:09:39,900 --> 00:09:47,160` dur=7.26s words=17 wps=2.34 zh=24 cps=3.31 | that risk of the husband experiencing serious psychological distress doesn't just stay at 1.5 times higher. || 那么丈夫遭受严重心理困扰的风险就不再仅仅是高出1.5倍。
- S0225 `00:11:29,860 --> 00:11:30,560` dur=0.7s words=5 wps=7.14 zh=5 cps=7.14 | They looked at the years || 他们研究了
- S0325 `00:16:39,160 --> 00:16:40,300` dur=1.14s words=7 wps=6.14 zh=7 cps=6.14 | That's a great way to put it. || 这个比喻很贴切。
- S0357 `00:18:20,160 --> 00:18:21,400` dur=1.24s words=9 wps=7.26 zh=12 cps=9.68 | Thank you for joining us for this deep dive. || 感谢您参加我们的深度探讨。
- S0358 `00:18:21,440 --> 00:18:22,290` dur=0.85s words=9 wps=10.59 zh=12 cps=14.12 | Thank you for joining us for this deep dive. || 感谢您参加我们的深度探讨。

### Leading Punctuation Candidates

- S0243 `00:12:31,260 --> 00:12:32,500` | takes much, much longer. || ，则需要长得多得多的时间。

### Adjacent Duplicate Candidates

- S0357-S0358 | Thank you for joining us for this deep dive. / Thank you for joining us for this deep dive. || 感谢您参加我们的深度探讨。 / 感谢您参加我们的深度探讨。

## Warning Examples

- suspicious_cut: 存在 22 处疑似机器感切点。 | sample={"start": "00:00:20.860", "end": "00:00:24.840", "reason": "上一条结尾不适合作为字幕终点", "previous": "It really does.", "current": "Like, Travis Kelce makes around 50 million a year.", "suggestion": "人工检查是否应合并，或把切点移动到更完整的意群边界。"}
- reading_speed_warning: 存在 25 条字幕阅读速度偏快。 | sample={"level": "WARNING", "index": 32, "start": "00:01:51.300", "end": "00:01:52.480", "duration_ms": 1180, "word_count": 6, "wps": 5.08, "reason": "英文字幕阅读速度 5.08 词/秒，可能偏快", "original": "Yeah, it's a lot to unpack.", "translated": "是啊，要解读的东西很多。"}
- duplicate_chinese: 存在 1 处相邻中文字幕疑似重复。 | sample={"previous_index": 357, "current_index": 358, "similarity": 1.0, "previous": "感谢您参加我们的深度探讨", "current": "感谢您参加我们的深度探讨"}
- asr_suspicious: 存在 4 处 ASR 可疑文本。 | sample={"index": 57, "subtitle_id": "S0057", "start": "00:02:55.460", "end": "00:02:57.900", "time_range": "00:02:55.460 --> 00:02:57.900", "rule_code": "asr_adjective_form_suspicious", "confidence": "medium", "reason": "疑似国家名形容词形式错误：常见表达应接近 American respondents", "suspicious_text": "Only 10% of America respondents said yes.", "recommended_review_window":
- chinese_semantic_group_warning: 存在 17 处中文语义组疑似病句或语义不完整。 | sample={"reason": "semantic_group_identity_mismatch", "rule_codes": ["audit_mapping_invalid"], "semantic_group_id": "G0192", "subtitle_ids": ["S0291", "S0292", "S0293", "S0294"], "mapping_valid": false, "english": "She earns the million-dollar salary, but she also makes sure to bake the cupcakes for the school bake sale and do his laundry, as if to signal

## Root-Cause Notes

- If many timing candidates appear with very short durations, prioritize word timestamp quality checks before prompt changes.
- If leading punctuation appears, use the generic leading punctuation repair rather than sample-specific text rules.
- If duplicate adjacent subtitles appear, check ASR duplicate emission before changing Chinese allocation.
- If WARNING exists but SRT is usable, keep it as review guidance unless it becomes a repeat pattern across multiple runs.

## Next Action

- Review the listed candidate lines in video/audio if this run will be used for publishing.
- Do not add sample-specific rules from this note alone.
- Prefer low-risk generic validators for repeated patterns across multiple notes.
