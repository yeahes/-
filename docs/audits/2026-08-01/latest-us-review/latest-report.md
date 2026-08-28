# 字幕稳定模式审计报告

生成时间：2026-08-01 22:46:30

| 样本 | 状态 | 字幕数 | ERROR | WARNING | 文件 |
|---|---:|---:|---:|---:|---|
| 美国已成为 | WARNING | 102 | 0 | 16 | E:\VideoCaptioner-screen-subtitle\work-dir\美国已成为\subtitle\stable-final-original-top.srt |

## 问题明细

### 美国已成为

#### ERRORS：0
无

#### WARNINGS：16
- ID 1：英文阅读速度 5.10 词/秒，可能偏快
  英文：Have you ever sat at your desk and thought, like,
  中文：你有没有坐在办公桌前想过，比如，
- ID 8：中文阅读速度 9.64 字/秒，建议压缩
  英文：Wait, is he the one projecting eight-figure sales this year?
  中文：等等，他就是那个预计今年销售额达到八位数的人吗？
- ID 12：字幕显示时长 760ms，低于 900ms
  英文：No, not at all.
  中文：不，完全不是。
- ID 12：英文阅读速度 5.26 词/秒，可能偏快
  英文：No, not at all.
  中文：不，完全不是。
- ID 16：字幕显示时长 801ms，低于 900ms
  英文：America were,
  中文：美国人
- ID 30：字幕显示时长 860ms，低于 900ms
  英文：It really is.
  中文：确实如此。
- ID 47：字幕显示时长 780ms，低于 900ms
  英文：Oh, absolutely.
  中文：哦，绝对是这样。
- ID 53：字幕显示时长 781ms，低于 900ms
  英文：Activation potential?
  中文：活化能？
- ID 54：字幕显示时长 840ms，低于 900ms
  英文：Like in chemistry?
  中文：就像化学里的那种？
- ID 54：中文阅读速度 9.52 字/秒，建议压缩
  英文：Like in chemistry?
  中文：就像化学里的那种？
- ID 77：字幕显示时长 420ms，低于 500ms
  英文：No.
  中文：不是。
- ID 77：字幕显示时长 420ms，低于 900ms
  英文：No.
  中文：不是。
- ID 98：字幕显示时长 761ms，低于 900ms
  英文：Oh, really? Yeah.
  中文：哦，真的吗？没错
- ID 102：英文阅读速度 5.66 词/秒，可能偏快
  英文：when there is no one left who wants to be their worker?
  中文：当再也没有人愿意为他们工作时
- ID 13：?????????????????????? ASR ??
  置信度：medium
  依据：similar capitalized variants in nearby subtitles
  可疑文本：So our mission for this deep dive is unpacking this sudden, massive boom in America entrepreneurship.
- ID 28：英文句法边界疑似坏切点: preposition_object_split
  边界：S0027 -> S0028
  规则：preposition_object_split
  置信度：high
  依据：left_last=about; right_first=finding; left_tokens=['to', '34', 'year-olds', 'about']; right_tokens=['finding', 'a', 'good', 'job']
  英文：I mean, Gallup data shows optimism among 15 to 34 year-olds about | finding a good job plummeted from 75% to just 43% recently.
  中文：盖洛普的数据显示，15至34岁人群对找到好工作的乐观情绪最近从75%骤降至仅43%。

#### INFO：0
无
