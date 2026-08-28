# Repository Backup Handoff

时间：2026-08-28 21:06:22 +08:00

## 目的

为工作目录建立一个可推送到 GitHub 的本地备份分支，保护源码、测试、状态记录、交接记录和可复现审计材料。

## 分支

- `codex/backup-20260828`
- 基于现有稳定源码 checkpoint `4959be4`

## 纳入范围

- `app/`、`resource/`、`scripts/`、`tests/` 等源码和测试（既有提交保持不变）
- `CODEX_STATE.md`、`docs/CURRENT_STATE.md`、`tasks/active/` 状态记录
- `docs/audits/`、`docs/handoffs/` 中的审计证据和交接材料
- 本轮新增的离线探针脚本及其测试

## 排除范围

- 音频、视频、字幕、缓存和运行目录
- `tmp/` 临时日志、抽帧和中间文件（已加入 `.gitignore`）
- `output/` 下的生成视觉预览；已跟踪的三张 PNG 停止跟踪，但本地文件保留

## 验证

- 未调用 API、未重跑音频、未合成视频
- 备份提交前运行聚焦测试和 `git diff --check`
- 用户自行执行 `git push -u origin codex/backup-20260828`
