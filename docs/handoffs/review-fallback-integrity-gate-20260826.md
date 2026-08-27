# Review 回落候选完整性门禁报告

时间：2026-08-26 10:46:02

## 数字

| cue | 候选数 | `(incomplete_review_count, relaxed_raw_hard_count)` |
|---|---:|---|
| S9513 | 33 | 31 个 `(0,0)`，2 个 `(1,0)` |
| S0038 | 7 | `(1,0),(2,0),(1,0),(2,0),(1,0),(1,0),(2,0)` |
| `test_no_safe_normal_font_partition...` 的 cue | 7 | 与 S0038 相同：`(1,0),(2,0),(1,0),(2,0),(1,0),(1,0),(2,0)` |

## 三条直接测试

| 测试 | 结果 | 证据 |
|---|---|---|
| `test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries` | FAIL | `tests/test_article_display_readability_contract.py:3248`，S9513 仍未失败关闭 |
| `test_renderable_review_fallback_is_degraded_without_blocking_the_blueprint` | PASS | S0038 蓝图仍为 PASS/degraded |
| `test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` | FAIL | `tests/test_article_display_readability_contract.py:1694`，`bundle["status"]` 仍为 `candidate_bundle` |

## 结论

只加入 `incomplete_review_count == 0` 的 `fallback_pool` 后，三条测试没有同时通过，不能运行收尾回归，也不能提交；§46.22 中“该过滤即可恢复 S9513、S0038 候选全部不完整”的判断与当前代码实测不一致。S9513 实测有 31 个完整候选，S0038 的降级测试仍依赖回落候选，继续放宽门禁会改变既有分页契约，属于未授权设计决策。

## 本轮改动

- `app/core/utils/podcast_learning_video.py`：只在 6360-6388 增加 `fallback_pool` 完整性过滤，约 14 行新增/调整。
- 恢复 `test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` 的原始 bundle 失败关闭断言；未修改其他既有断言。
- 未修改 `screen_editor.py`，未运行整文件收尾回归，未提交。

## 发现但没动

- S9513 的问题不由“所有回落候选均不完整”解释；需要重新定位候选最终选择路径。
- 测试仍产生 `app.log` 轮转 `WinError 32` 噪音；本轮不改日志配置。

## 提交

提交哈希：无。当前仅保留工作树改动，未执行 `git add`、提交、回退或清理。
