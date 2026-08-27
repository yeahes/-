# 外部只读测量 — 2026-08-24（Claude / Opus 5）

本目录是根目录 `EXTERNAL-AUDIT-2026-08-24.md` 的原始数据与可复现脚本。
**本目录内所有脚本只读取仓库，不写入仓库任何既有文件。**

## 脚本

| 文件 | 产出 | 作用 |
| --- | --- | --- |
| `measure_boundary_flips.py` | `boundary_flip_measurement.json` | 哈钦校验（对比 `english-boundary-audit.json` 的 `rule_codes`，94.31% 一致）+ 反事实：枚举每条冻结父字幕的每个内部候选切点，统计仅因 `relative_clause_entrance_split` / `dependent_clause_entrance_split` 被判非法的数量 |
| `measure_stage2.py` | `boundary_flip_stage2.json` | 伪证测试：把生产**已接受并已合成**的父间边界喂回现规则，统计被判非法的比例（516 / 5,180 = 9.96%）；并按父字幕长度、逗号、有限谓语、停顿刻画那 98 个新增切点 |
| `measure_finite_predicate.py` | `finite_predicate_audit.json` | 在本仓库 5,219 条冻结父字幕上，对比 `_fragment_has_finite_predicate`（`screen_editor.py:6697`）与 spaCy 的有限动词标注 |
| `measure_finite_counterfactual.py` | `finite_predicate_counterfactual.json` | 在**独立进程内** monkeypatch 上述 helper 为 `scripts/audit_visual_temporal_splits.py:45-67` 的实现，重测 9.96% 那批边界（516 → 484，新增非法 0） |

### 第三轮追加（报告 §11）

| 文件 | 产出 | 作用 |
| --- | --- | --- |
| `measure_open_subordinate.py` | `open_subordinate_counterfactual.json` | arms A/B/C/D。测报告 §10.2 提出的"依存祖先判据"。**结论：该处方作废**（只消 15 条，且靠 spaCy 把 `when` 标成 `advmod` 碰对） |
| `measure_open_subordinate_v2.py` | `open_subordinate_counterfactual_v2.json` | arms A/E/F/G。改判据为"从句自身是否含有限谓语"。E=440、F=452、G=405（基线 516），三者新增非法均为 0。注意：JSON 里 `samples.F_still_blocked` 是**误名**，实际过滤的是 arm E（`hE`），即 arm E 下仍被该 code 挡住的 12 条 |
| `measure_open_subordinate_v3.py` | `open_subordinate_new_candidates.json` | 互补枚举：遍历 49,678 个内部候选切点，找 arm E "现网非法→放宽后合法"的新切点（105 条，新增非法 0）。这是 §1 处方作废时缺的那一半证据 |
| `measure_open_subordinate_v4.py` | `open_subordinate_new_candidates_EF.json` | 同上枚举，但 E / F 双臂并测且不靠推断：**F 新增合法 69（去重 64）、E 额外多开 36（去重 34）、两臂新增非法均为 0**。`samples.F` 与 `samples.E_only` 是报告 §11.5 逐条复核用的原文 |

**采纳建议以 arm F 为准，理由是 §11.5 的双向权衡，不是 arm G 的数字。**

### 分页层（报告 §12）

| 文件 | 产出 | 作用 |
| --- | --- | --- |
| `measure_single_line_pages.py` | `single_line_pagination_feasibility.json` | 读冻结的 `display-page-translations.json` 的 `render_plans`（22 集 / 4,656 父 / 5,352 页），用项目自己的 `article_subtitle_en_font`+`text_w`+`acx` 量单行宽度。核心结论：**把 3591 的单行门槛 1100 抬到 1260 / 1455，分别有 303 / 785 个现网双行页可改为单行**，页数与切分不变 |
| `measure_single_line_feasibility_dp.py` | `single_line_feasibility_dp.json` | 可行性 DP：每页须单行装下 + ≥4 词 + ≥900ms + ≤4 页。剔除整条即低于地板的 457 父后，单行可行率 86.0 / 95.0 / 98.7 / 99.1%（四档宽度），**现行双行四档全部 100%**。卡点是两条地板，不是页数上限 |

这两个脚本额外依赖 `Pillow`，并需要 `resource/podcast_template/fonts/RobotoSlab-SemiBold.ttf`
（仓库自带）。它们 `import app.core.utils.podcast_learning_video`，
用的是项目真实度量函数，不是任何近似估计器。

**测量面重复计数（引用比例时请知道）**：那 22 个产物集只来自 **20 个 work-dir** ——
`中式梦核` 与 `无论怎么衡量，就业市场都很疲软` 各有 `【字幕】`/`【样式字幕】` 两份产物，
即 **462 / 4,656 = 9.9% 的父字幕是这 2 集被算了两遍**（比例结论基本不受影响，
但 `hard_examples_at_1455` 里 S0062/S0064/S0218 各出现两次就是这个原因）。
§11 那批（23 个产物集）同理：覆盖约 15 个不同源集，改名重跑的会被算两次。

## 复核记录

2026-08-24 用独立 subagent 对报告 §11/§12 的每个数字做过一次对账：
**与本目录 JSON 零差异，百分比可复算，file:line 引用全部准确**，
并独立复现了 5,219 父 / 49,678 候选切点。它同时挑出 8 处**标注问题**（不影响任何数字），
已在报告里逐条改掉，其中值得在这里重复的两条：

- arm B 的 `open_sub` 命中 110 **不在任何 JSON 里**，是由 E=12 且 G=12 推导的（词表修复不动这个 code）；
- §11.4 的"去重后 98"= 64 + 34 相加得出，不是直接读数；`newly_illegal_*` 键在
  `open_subordinate_new_candidates_EF.json` 中**缺失即为真 0**（`measure_open_subordinate_v4.py:139` 用 Counter 计数）。

## 怎么跑（无需改任何路径）

全部 10 个脚本的 `PROJ` 现在**由脚本自身位置自动推导**
（`Path(__file__).resolve().parents[3]`），产物写回**脚本所在目录**，
跨脚本 import 也走 `_HERE`。所以在 Windows 上直接：

```
python docs\audits\2026-08-24\external-claude-measurement\measure_stage2.py
```

从任意工作目录运行都可以，不必 `cd` 进来。仓库若被移动或改名，
可用环境变量 `VC_REPO` 覆盖仓库根。
已验证：从与仓库无关的目录运行 `measure_stage2.py`，
复现 **5,180 边界 / 516 非法 / open_sub 110**（= GPT 当前工作树的状态）。

`MODEL` 指向 `runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0`，
随 `PROJ` 自动定位，无需改动。
`measure_stage2.py` / `measure_finite_counterfactual.py` 会从
`measure_boundary_flips.py` 导入 `build_editor` / `find_episodes`，四个文件需放在同一目录。

依赖：`spacy>=3.8`（仓库 `runtime` 已自带模型数据，模型按绝对路径加载，不依赖
`spacy.load("en_core_web_sm")` 的注册表）。为绕过 `ScreenSubtitleEditor.__init__`
中 `CacheManager` 写盘与 `_init_client()` 的副作用，脚本用 `__new__` + 显式属性设置构造实例，
做法沿用 `scripts/audit_pre_id_joint_page_feasibility.py` 的 `_make_editor`。

## 数据源

`work-dir/*/subtitle/*artifacts/` 下已冻结的 `word-ledger.json`、
`final-cue-timeline.json`、`english-boundary-audit.json`，共 23 个产物集。
脚本自动发现，不需要参数。

## 置信度

见根目录报告 §9。要点：`__new__` 构造保真度的上界由 9.96% 界定，
其中哈钦误差与真实规则漂移**未分离**；`visual_*` 显示层作用面**未测**；
§5 的机制结论为推断而非实测。
