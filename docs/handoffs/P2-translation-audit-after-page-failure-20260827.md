# P2：分页失败时仍运行父级翻译质量审计（2026-08-27）

## 目标

分页中文失败仍然必须阻止出片，但不能因此让父级中英文质量审计变成 `SKIPPED`。父级英文、父级中文、字幕 ID 和时间轴已经冻结，审计可以独立运行并只生成质量证据。

## 实现

在 `E:\VideoCaptioner-screen-subtitle\app\thread\subtitle_thread.py`：

- `_run_translation_quality_audit` 新增显式参数 `allow_page_projection_failure`，默认 `False`，保持普通直接调用的旧行为。
- 只有 display-page 翻译异常捕获路径明确传入 `True`，才允许继续调用审计服务。
- 分页失败仍保留原有 `display_page_translation_invalid` 错误和渲染阻断，不会因为审计通过而放行视频。
- 捕获路径保存审计结果和审计文件路径，使失败 checkpoint 仍能看到父级审计证据。
- 不修改英文、中文、字幕 ID、词账本、时间轴、分页选择或页面中文。

## 验证

- `tests/test_translation_quality_audit.py`：14 passed。
- 原有兼容测试 `test_failed_display_page_translation_skips_network_quality_audit`：1 passed；未修改既有断言。
- 新增假响应测试：分页状态为 `ERROR` 且显式 opt-in 时，审计函数被调用并返回 `PASS`。
- `py_compile`：`subtitle_thread.py` 与翻译审计测试通过。
- 未联网、未调用模型、未运行 ASR、未合成视频、未读取或写入任何 stable run。

## 当前配置注意事项

当前本机解析到的配置是 `OpenCode Go` 服务 + `deepseek-v4-flash` 模型。模型名包含 DeepSeek 不代表使用官方 DeepSeek API；要使用官方服务，必须先把 LLM 服务切换为 `DeepSeek`，确认其 `https://api.deepseek.com/v1` 配置后再运行真实审计。

## 下一步（需要用户确认服务后再做）

对现有供应链失败 checkpoint 只运行父级翻译审计，目标是拿到 297 条固定 ID 的质量结果；不要重跑 ASR、父级翻译、WhisperX、最终时间轴或整集分页。分页阻断 `S0136` / `S0260` 仍单独处理。

## 发现但没动

- `S0136` 的分页中文 ID 缺失和 `S0260` 的否定归属错误仍然存在，属于分页翻译层，不在本次审计解耦改动内。
- 普通直接调用 `_run_translation_quality_audit` 默认仍会跳过无效分页；只有生产失败路径显式 opt-in。这是为保持既有调用契约和测试兼容而保留的边界。
