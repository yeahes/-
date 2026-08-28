# G1'-verify-commit 验证中止报告

时间：2026-08-26 13:27:26 Asia/Shanghai

## 数字

| 指标 | 当前值 |
|---|---:|
| A 前提核验通过数 | `3 / 3` |
| 工作树契约运行时长 | `>= 60 秒，未完成` |
| 基线契约运行时长 | `>= 60 秒，未完成` |
| 工作树完整用例清单 | `0`（捕获文件为空） |
| 基线完整用例清单 | `0`（仅有 15 条 spaCy 加载日志，无汇总） |
| `F_base` | 未定义（运行未完成） |
| `F_wt` | 未定义（运行未完成） |
| 暂存文件数 | `0` |
| 提交数 | `0` |

## 开工前核验

1. HEAD=`fdd9d83`，分支=`main`。
2. `git worktree list` 包含 `E:/vc-head-baseline fdd9d83 (detached HEAD)`。
3. 工作树仍有 `app/core/utils/podcast_learning_video.py`、`app/core/subtitle_processor/screen_editor.py` 及相关 G1/G1' 未提交改动。

三项均成立，验证开始。

## 验证过程

两树分别启动了同一命令：

```text
runtime\python.exe scripts\run_regression.py --only article-display-readability-contract
```

基线使用：

```text
E:\VideoCaptioner-screen-subtitle\runtime\python.exe E:\vc-head-baseline\scripts\run_regression.py --only article-display-readability-contract
```

正式 runtime 的 spaCy 模型确认存在且可加载：

```text
runtime\Lib\site-packages\en_core_web_sm
spacy.util.is_package('en_core_web_sm') == True
```

两次运行在 60 秒仍未结束。按 §46.13 和本工单“单次超一分钟就是跑错了”的硬限制，分别以 Ctrl+C 中止，退出码均为 `1`。因此没有合法的逐函数 PASS/FAIL 清单，不能计算 `F_base`、`F_wt` 或无回归子集关系。

捕获文件：

- 工作树：`output/g1-verify-wt-20260826.txt`，`0` 字节。
- 基线：`output/g1-verify-base-20260826.txt`，`1776` 字节，仅包含 spaCy 模型加载日志，没有测试汇总。

中止期间没有执行 ASR、faster-whisper、网络调用、视频合成或音频管线重跑。中止留下的临时 `sitecustomize.py` 已删除；它只是回归脚本用于禁用 app.log 轮转的测试文件。

## 判定

**不通过，停止提交。** 验证没有在规定时间内完成，失败集合未知，不能满足 `F_wt ⊆ F_base` 的提交门槛。

## 发现但没动

- `tests/test_article_display_readability_contract.py` 的逐函数清单导出仍需要一个能在一分钟内完成的测试入口；本轮未新增包装脚本或改变测试。
- 工作树中存在多轮历史代码、测试、文档和生成文件改动；本轮未清理、未回退、未归因。
- 没有执行 `git add`、`git commit`、`git push`、`git stash`、`git restore`、`git checkout` 或 worktree 删除/prune。
