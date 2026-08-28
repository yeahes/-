# F1 alignment probe

时间：2026-08-27 16:32:00 +08:00

## 数字

| 项目 | 结果 |
| --- | --- |
| PASS 主样本 | 30 个父句，来自 2 个 PASS run |
| 机器人 PASS run | 43 个多页父句，91/91 页有中文 |
| 白宫 PASS run | 34 个多页父句，73/73 页有中文 |
| 供应链诊断项 | S0136、S0260；ERROR checkpoint，53/55 页有中文，不能计入 PASS 分母 |
| 离线假响应测试 | 4/4 PASS |
| OpenCode 简单连通性请求 | 1 次成功，约 1.4 秒 |
| 完整对齐请求（S0100） | 首次 30 秒超时，重试 30 秒超时 |
| 完整对齐请求（S0100，单次 120 秒复核） | 超时 |
| 有效对齐响应 | 0/1 个已尝试父句 |
| 合规率、逐字拼接率 | 未形成有效分母，不能判定 |
| 人工分页命中 | 未测；无有效对齐结果 |
| S0136 / S0260 | 未测；批量探针因服务无响应停止 |
| API 总请求 | 仅做了上述诊断请求；未启动 30+2 正式批次 |
| 官方 DeepSeek `deepseek-v4-flash` | 连通性成功，但真实对齐响应 `finish_reason=length`，1024/4096 token 全用于 `reasoning_content`，`content` 为空；未继续批量消耗 |
| 官方 DeepSeek `deepseek-chat` 主样本 | 30 个父句：首次合规 18/30（60%），重试后 18/30（60%），逐字拼接同为 18/30；12 个失败均为 `range_not_monotonic` |
| 官方 DeepSeek `deepseek-chat` 诊断项 | S0136、S0260 均失败（`range_not_monotonic`），0/2 合规 |
| 官方 DeepSeek 人工分页命中 | 0/5 个可对照父句；人工终稿与当前 PASS run 词账本不同，不能作严格回归结论 |

## 结论

脚本的数据读取、硬门校验、确定性投影和重试逻辑已通过离线验证。官方 DeepSeek API 本身可用：当前配置的 `deepseek-v4-flash` 在该请求上只产出思考内容，换用官方默认 `deepseek-chat` 后可完成批量，但主样本合规率仅 60%，且 12 个失败均未被一次重试救回。因此这条“中文短语→英文词区间”探针暂不进入生产分页逻辑；应先解决模型调用模式/输出约束，再重新做低成本验证。输入产物未被修改。

## 发现但没动

- 当前机器人 PASS 运行没有 `S0104`，所以该 ground-truth 父句无法进入自动样本。
- 供应链 `S0136` 在 `display-page-translations.json` 的 `parents[]` 缺失，只能从同一 checkpoint 的 `render_plans[]` 读取英文范围；该项仅作诊断，不计 PASS 分母。
- 人工终稿的词账本 hash 与当前机器人 PASS run 不同；本探针只按父 ID 和人工分页记录做对照，不宣称跨账本回归。

## 文件与验证

- 新增只读脚本：`scripts/probe_alignment_emission.py`
- 新增离线单测：`tests/test_probe_alignment_emission.py`
- 未修改 `app/`、checkpoint、stable run、人工终稿或任何既有测试断言。
- 验证命令：`runtime\\python.exe -m pytest -q tests\\test_probe_alignment_emission.py`，结果 `4 passed`。

## 追加等价调用诊断

在得到明确授权后，对 PASS run 的 `S0100` 做了 3 次只读请求：1 次原探针
参数，2 次生产适配器形式；模型固定为官方 DeepSeek `deepseek-chat`，没有
触发音频、视频或生产字幕流程。三次响应完全相同，均为 `finish_reason=stop`，
约 124 个 completion tokens，且均在本地硬校验处失败为
`range_not_monotonic`。原始响应保存在
`output/f1-alignment-probe/alignment-equivalence-latest.json`。

该响应把“但如果能直接模仿一个本能就懂得如何应对重力的人”映射到英文
`23..32`，再把“学习速度会呈指数级提升”映射回英文 `15..17`。这是自然
中文相对英文的从句重排，不是 token 预算耗尽或随机重试问题；单调区间契约
无法同时保持自然中文和英文词序。

## 决策更新

- “中文短语到英文单调词区间”继续保持诊断状态，不进入生产分页。
- 不继续推进仅返回 `word_end` 或 strict schema 作为主修复；它们不能解决
  中英语序重排。
- 生产继续复用固定英文页和现有按 `display_page_id` 绑定的页级翻译契约。
- 聚焦验证：`test_s0078_reordered_chinese_is_bound_by_page_id` 通过，固定父句
  双语页实验 2 个用例通过。
