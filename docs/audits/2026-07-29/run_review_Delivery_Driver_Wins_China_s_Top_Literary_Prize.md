# Run Review: Delivery_Driver_Wins_China_s_Top_Literary_Prize

## Basic Info

- Review time: 2026-07-29 01:23:38 +08:00
- Git commit: ab23db8
- Created at: 2026-07-29T01:01:02
- Work dir: `E:\VideoCaptioner-screen-subtitle\work-dir\Delivery_Driver_Wins_China_s_Top_Literary_Prize`
- Final bilingual SRT: `E:\VideoCaptioner-screen-subtitle\work-dir\Delivery_Driver_Wins_China_s_Top_Literary_Prize\subtitle\stable-final-original-top.srt`
- Manifest: `E:\VideoCaptioner-screen-subtitle\work-dir\Delivery_Driver_Wins_China_s_Top_Literary_Prize\subtitle\stable-final-manifest.json`
- SRT SHA-256: `66a370b61c2ead07cb7fef0b47f62784fde4a802504e72db62b6a6e88b55f1d9`
- Subtitle count: 114
- Validation status: passed
- Validation summary: WARNING
- Render blocked: False
- Timeline backend: whisperx-time-only

## Score

- Automated overall score: 82
- English max words: 16
- English average words: 8.78
- Average subtitle duration: 2749.56 ms

This note is based on static inspection of manifest, final SRT, and generated audit data. It is not a full manual audio listening pass.

## ERROR Codes

- None

## WARNING Codes

- suspicious_cut: 1
- reading_speed_warning: 1
- subtitle_duration_short_warning: 1
- syntax_boundary_audit: 1
- chinese_semantic_group_warning: 1

## Positive Findings

- Stable final SRT exists: yes
- Manifest exists: yes
- No hard ERROR: yes
- No continuous English-Chinese left-shift detected by static heuristics.

## Detected Problems

### Timing/Reading-Speed Candidates

- S0022 `00:01:09,220 --> 00:01:09,920` dur=0.7s words=4 wps=5.71 zh=11 cps=15.71 | Okay, so let's unpack || 好的，那么我们来深入分析
- S0083 `00:04:10,380 --> 00:04:10,820` dur=0.44s words=3 wps=6.82 zh=5 cps=11.36 | Oh, I see. || 哦，我明白了。
- S0084 `00:04:10,860 --> 00:04:11,740` dur=0.88s words=4 wps=4.55 zh=12 cps=13.64 | So they spin it. || 所以他们是在引导叙事方向。
- S0091 `00:04:34,060 --> 00:04:35,370` dur=1.31s words=15 wps=11.45 zh=12 cps=9.16 | everyday people can still produce high culture, which implies the system still works for everyone. || 这暗示系统对所有人仍有效

### Leading Punctuation Candidates

- S0011 `00:00:32,700 --> 00:00:35,780` | your dinner also happened to be one of the country's most celebrated poets. || ，竟然也是这个国家最受赞誉的诗人之一。

### Adjacent Duplicate Candidates

- None

## Warning Examples

- suspicious_cut: 存在 7 处疑似机器感切点。 | sample={"start": "00:01:54.500", "end": "00:01:58.280", "reason": "上一条结尾不适合作为字幕终点", "previous": "Really?", "current": "How so? Well, let's look at his award-winning 2024 collection.", "suggestion": "人工检查是否应合并，或把切点移动到更完整的意群边界。"}
- reading_speed_warning: 存在 13 条字幕阅读速度偏快。 | sample={"level": "WARNING", "index": 1, "start": "00:00:00.360", "end": "00:00:01.380", "duration_ms": 1020, "zh_chars": 10, "cps": 9.8, "reason": "中文字幕阅读速度 9.80 字/秒，超过 9.0 字/秒建议值", "original": "Welcome to this deep dive.", "translated": "欢迎来到本次深度解读。"}
- subtitle_duration_short_warning: 存在 2 条字幕显示时间低于 500ms。 | sample={"code": "subtitle_duration_too_short", "level": "WARNING", "index": 40, "start": "00:01:54.500", "end": "00:01:54.880", "duration_ms": 380, "threshold_ms": 500, "reason": "字幕显示时间 380ms，低于 500ms 阈值", "simple_response": true, "text_load": 4, "original": "Really?", "translated": "真的吗？"}
- syntax_boundary_audit: 存在 1 处英文句法边界疑似坏切点。 | sample={"index": 108, "left_subtitle_id": "S0107", "right_subtitle_id": "S0108", "start": "00:05:17.080", "end": "00:05:25.560", "reason": "preposition_object_split", "rule_codes": ["preposition_object_split"], "confidence": "high", "confidence_score": 0.77, "evidence": "left_last=with; right_first=if; left_tokens=['delivery', 'we', 'started', 'with']; ri
- chinese_semantic_group_warning: 存在 4 处中文语义组疑似病句或语义不完整。 | sample={"group_index": 17, "semantic_group_id": "G0017", "subtitle_ids": ["S0020", "S0021"], "start_index": 20, "end_index": 21, "start": "00:01:00.720", "end": "00:01:09.220", "reason": "dangling_preposition; modifier_head_split", "rule_codes": ["dangling_preposition", "modifier_head_split"], "findings": [{"code": "dangling_preposition", "message": "第 [1

## Root-Cause Notes

- If many timing candidates appear with very short durations, prioritize word timestamp quality checks before prompt changes.
- If leading punctuation appears, use the generic leading punctuation repair rather than sample-specific text rules.
- If duplicate adjacent subtitles appear, check ASR duplicate emission before changing Chinese allocation.
- If WARNING exists but SRT is usable, keep it as review guidance unless it becomes a repeat pattern across multiple runs.

## Next Action

- Review the listed candidate lines in video/audio if this run will be used for publishing.
- Do not add sample-specific rules from this note alone.
- Prefer low-risk generic validators for repeated patterns across multiple notes.
