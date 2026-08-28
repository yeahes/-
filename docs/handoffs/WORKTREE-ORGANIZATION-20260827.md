# 工作树整理记录

时间：2026-08-27 12:59:00 +08:00

## 本次已整理

- 保留根目录 `CODEX_STATE.md` 作为当前入口，并把旧的同名兼容文件、旧状态文件和旧进展文档移到 `docs/archive/2026-08-26/d1-merged/`。
- 把原 `tasks/active/stable-subtitle-production-v1-log.md` 的历史轮次拆到 `tasks/archive/stable-subtitle-production-v1-log/`；active 只保留最近一轮和不超过 50 行的 `current-state-summary.md`。
- `docs/CURRENT_STATE.md` 保留为可读的长期状态，补充了当前未审阅音频的分页阻断和离线候选结论。

## 数字

| 项目 | 结果 |
| --- | ---: |
| 整理前状态条目 | 151 |
| 任务历史归档文件 | 190 |
| 原 active 任务日志 | 3,699 行 |
| 当前 active 任务日志 | 26 行 |
| 归档任务文本 | 3,810 行（只搬迁，未删除历史正文） |
| 本次暂存文件 | 200 |
| 暂存 Python 文件 | 0 |
| 生成的 `output/` 文件 | 未暂存、未移动 |

## 当前分页阻断

`中国企业正把供应链铺满全球` 的现成 checkpoint 仍为 53/55 页：
`S0136.P01/P02` 缺失，`S0260` 的“并不重要”落在 P02。四次 OpenCode
重试都被现有语义/词面校验拒绝。离线候选可生成 55 页并通过渲染器应用校验，
但 S0260 仍需人工确认，因此没有写回 checkpoint。

## 尚未提交的源码组

- 分页重试与冻结父句续跑：`screen_editor.py`、`subtitle_thread.py`、`stable_run_state.py` 及对应测试。
- 翻译提示词/语气词与分页翻译重试：`screen_editor.py` 及对应测试。
- G1/G7 相关分页选择和降级实现：`podcast_learning_video.py` 及对应测试，暂不与其他组混提。
- 手工终稿时间映射、最终时间轴阈值、回归输出压缩：分别按各自测试验证后再拆分。

本次没有重跑音频、没有调用 API、没有改 `work-dir` 或 `stable-runs`，也没有合成视频。
