# G1'-orphan-test 差异报告

时间：2026-08-26 22:34:06 Asia/Shanghai

## 前提核验

| 前提 | 结果 | 证据 |
|---|---|---|
| HEAD / 分支 | 成立 | `git rev-parse --short HEAD`=`fdd9d83`；`git branch --show-current`=`main` |
| 孤儿测试存在 | 成立 | `tests/test_article_display_readability_contract.py:2138` 定义 `test_tight_clause_entries_need_explicit_review_before_page_selection`；`2171` 引用 `relative_clause_has_trailing_predicate` |
| app/ 已无 G7 字段 | 成立 | `rg` 在 `app/` 无命中；全仓（排除 runtime/output/work-dir）只剩该测试、审计文档、`scripts/measure_g1_blueprint_diff.py` 等非生产引用 |

## Q1：甩谓语的关系从句入口是否仍被拒绝

不成立。

对第一例：

```text
You kind of have to assume the person who put it there wasn't just wasting wood, you know.
split = person | who
```

当前工作树直接调用 `_article_page_break_score(...)` 的结果：

```text
decision.issue_codes = ['dependency_phrase_entrance_split']
decision.classification = 'review'
page_break_score = 3120
plan_status = ok
page_starts = {8}
```

也就是说当前代码允许该边界评分并进入分页起点；它没有返回 `None`。这不是孤儿测试的字段引用问题，而是工单所描述的“拒绝甩掉后续谓语”诉求在当前生产代码里已经不成立。按工单情形 C，必须停止，不能通过删除或改写测试掩盖。

## Q2：现存测试覆盖情况

没有找到与第一例等价的现存覆盖。契约文件中有以下相关但不等价的用例：

- `test_actual_plans_do_not_select_the_tight_complement_boundaries`（:2092）：覆盖若干依存/动词补语紧边界，不是 `person | who` 甩谓语。
- `test_high_pressure_single_pages_promote_only_complete_review_partitions`（:3135）：包含 `professors | who have ...` 的完整关系从句入口，覆盖允许的第二类边界。
- `test_zero_relative_tail_does_not_become_an_isolated_display_page`（:520）：覆盖相对尾句不单独成页，不是关系从句入口判定。
- `test_complete_infinitive_page_can_relax_relative_subject_evidence`（:3496）：覆盖关系从句主语/动词证据放宽，不是当前第一例。

## Q3：不甩谓语的关系从句入口是否允许

成立。

第二例：

```text
and two extra years of networking with local professors who have direct ties to local industry.
split = professors | who
```

当前结果：

```text
decision.issue_codes = ['dependency_phrase_entrance_split']
decision.classification = 'review'
page_break_score = 3120
plan_status = ok
page_starts = {9}
```

该边界允许上屏并进入分页起点。

## 判定

**不通过，停止本单。** Q1 属于情形 C：生产代码当前不再拒绝第一例。未修改任何 `.py`、测试断言或分页逻辑；未跑回归、未暂存、未提交。

## 发现但没动

- `_article_display_boundary_decision` 当前返回不含 `relative_clause_has_trailing_predicate`，这是 G7 撤除后的预期字段状态；没有加回该字段。
- 第一例的完整性判据可能需要另立生产逻辑工单；本单明确禁止动 `app/`，未处理。
- 工作树仍有多轮未提交改动；本单未清理、未回退。

## 安全边界

未执行 `git add`、`git commit`、`git push`、`git stash`、`git restore`、`git checkout` 或 worktree 删除/prune；未修改 stable-runs，也未触发 ASR、模型下载、合成或音频管线。
