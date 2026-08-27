# G1'-verify-commit-r2 验证报告

时间：2026-08-26 13:50:08 Asia/Shanghai

## 数字

| 指标 | 基线 B | 工作树 A |
|---|---:|---:|
| contract 函数总数 | `107` | `110` |
| PASS | `106` | `108` |
| FAIL | `1` | `2` |
| 运行耗时 | `408.93s` | `485.57s` |

失败集合：

```text
F_base = {test_three_line_fallback_promotes_complete_two_page_alternative}
F_wt   = {
  test_three_line_fallback_promotes_complete_two_page_alternative,
  test_tight_clause_entries_need_explicit_review_before_page_selection
}
F_base - F_wt = {}
F_wt - F_base = {test_tight_clause_entries_need_explicit_review_before_page_selection}
```

被 G1/G1' 修绿的函数：`0`。S9513 和 S0038 在基线与工作树均为 PASS，不属于本次 A/B 的修绿差集。

## 完整逐函数清单

- 工作树 A：[g1-verify-wt-r2-functions.txt](/E:/VideoCaptioner-screen-subtitle/output/g1-verify-wt-r2-functions.txt)
- 基线 B：[g1-verify-base-r2-functions.txt](/E:/VideoCaptioner-screen-subtitle/output/g1-verify-base-r2-functions.txt)
- 机器计算差集：[g1-verify-r2-diff.json](/E:/VideoCaptioner-screen-subtitle/output/g1-verify-r2-diff.json)

两份清单均由 pytest `-rA` 对同一个 `tests/test_article_display_readability_contract.py` 生成，逐行格式为 `PASS/FAIL test_function_name`。正式 runtime 加载的是本地 `runtime/Lib/site-packages/en_core_web_sm`，没有下载模型、ASR、视频合成或音频管线重跑。

## 失败详情

- 两树共同失败 `test_three_line_fallback_promotes_complete_two_page_alternative`：S9522 第二页实际为 `in the modern food and beverage industry.`，断言期望从 `into the most aggressive expansion engine...` 开始。
- 工作树额外失败 `test_tight_clause_entries_need_explicit_review_before_page_selection`：`tests/test_article_display_readability_contract.py:2171` 读取不存在的 `relative_clause_has_trailing_predicate` 键，基线没有这个测试函数。
- 工作树比基线多 3 个测试函数，其中以上 `tight_clause...` 是唯一失败的新增函数；另两个新增 G1 降级/候选测试均 PASS。

## 判定

**不通过，停止提交。** 按本单原始集合判据，`F_wt - F_base` 非空；同时两棵树的测试函数集合并不相同，不能把新增失败安全解释成基线已有欠账。未执行任何暂存或提交。

## 发现但没动

- `test_tight_clause_entries_need_explicit_review_before_page_selection` 是工作树新增测试，但依赖已撤掉的 G7 字段；本轮不改测试断言、不补兼容字段。
- S9522 在正式 runtime + spaCy 环境下两树都失败；本轮不改页面选择逻辑。
- 工作树仍有多轮历史 `.py`、测试、文档和生成文件改动；本轮未清理、未回退。

## 安全边界

本轮未执行 `git add`、`git commit`、`git push`、`git stash`、`git restore`、`git checkout` 或 worktree 删除/prune；未修改 stable-runs。
