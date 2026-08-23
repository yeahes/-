# 外部只读审计报告 — 2026-08-24

审计者：Claude（Opus 5），以**只读**方式介入。
分支：`main`，审计时 HEAD = `db46f68`（2026-08-24, "Improve manual subtitle editor responsiveness"）。

## 0. 给接手模型的阅读说明（请先读这一节）

**本次审计没有修改本仓库任何一个既有文件。**本报告与 `docs/audits/2026-08-24/external-claude-measurement/`
下的脚本、原始 JSON 是本次唯一新增内容。所有反事实实验都是在**仓库外的独立进程内**用
monkeypatch 完成的，磁盘上的代码始终是 `db46f68` 的原样。

本报告刻意把结论分成三种，请勿混用：

| 标记 | 含义 |
| --- | --- |
| **【实测】** | 有脚本、有原始 JSON、可复现的数字 |
| **【已核实】** | 一手读代码确认的事实（含 file:line） |
| **【推断】** | 由前两类推出的判断，未直接测量 |
| **【已推翻】** | 审计者自己先前的假设，被自己的数据否掉，保留以防重复踩坑 |

> **⚠ 2026-08-24 第二轮追加（发布后新增）**
> 本文档发布后又做了一轮只读核实，结果全部集中在 **§10**，其中包含对
> **§3.3 与 §4.1 的更正**，以及一条**新发现**（§10.2：占矛盾最大头的
> `open_subordinate_prefix_fragment` 病灶不在有限谓语词表，而在一条正则）。
> **前文若与 §10 冲突，以 §10 为准。**
> 第二轮同样没有修改本仓库任何既有文件。
>
> **⚠ 2026-08-24 第三轮追加：§11（有实测数字，且推翻了 §10.2 的处方）**
> §11 把上面那条"新发现"从**推断**做成了**实测**：七个 arm、5,180 条已发布边界、
> 49,678 个候选切点全枚举，并逐条人工复核了被放宽出来的新切点。
> 结果有三件事必须先看：
> **(a)** §10.2 我提的"依存祖先判据"处方**只值 15 条且靠 spaCy 标注偏差碰对**，已作废；
> **(b)** 正确判据是"从句自身有没有有限谓语"，配上"须以逗号结尾"这道闸
> （§11 的 arm F），可消掉 64 条矛盾、新增非法 0 条、只多开 69 个候选切点且质量良好；
> **(c)** 数字最漂亮的 arm 不是最该采纳的 arm ——
> "消掉的矛盾条数"不能当优化目标，理由见 §11.5。
> **§10 与 §11 冲突处一律以 §11 为准。**
>
> **⚠ 关于"未修改既有文件"这句话，请配合 `git status` 一起读（免得你以为我在撒谎）**
> 你在工作树里会看到 **119 个 M**。经 `git diff --ignore-cr-at-eol --numstat` 剥离后，
> **其中 113 个是 CRLF 假阳性**（仓库 `core.autocrlf` 未设置；`app/_vendor/jieba/dict.txt`
> 一个文件就 109,749 增 / 109,749 删）。**真实内容改动只有 6 个文件**：
> `app/components/article_context_panel.py`、`app/core/subtitle_processor/manual_final_subtitle_editor.py`、
> 对应两个测试、`CODEX_STATE.md`、`docs/CURRENT_STATE.md` ——
> 这一簇是**并发的 Codex 会话**在做"frozen-page refresh reuse / article-analysis dialog isolation"，
> 与本报告的切分/分页议题无交集。
> **本报告涉及的两个文件都没被我碰过**：`screen_editor.py` 完全不在 M 列表里；
> `podcast_learning_video.py` 是 M 但 `--ignore-cr-at-eol` 下真实改动为 0（纯 CRLF）。
> 我的全部反事实都是**仓库外独立进程内的 monkeypatch**，新增文件只有
> `EXTERNAL-AUDIT-2026-08-24.md` 与 `docs/audits/2026-08-24/`。

复现方式：脚本在 `docs/audits/2026-08-24/external-claude-measurement/`，依赖 `spacy>=3.8` 与
`en_core_web_sm`（仓库已自带于 `runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0`）。
数据源是 `work-dir/*/subtitle/*artifacts/` 下已冻结的 `word-ledger.json` +
`final-cue-timeline.json` + `english-boundary-audit.json`，覆盖 23 个产物集。
脚本只读，不写入仓库。

---

## 1.【已推翻】"放宽两条 HARD 判定即可解锁切点"——此处方作废

审计者最初的假设是：`_cross_item_structural_boundary_issues`
（`app/core/subtitle_processor/screen_editor.py:6259-6346`）里唯一两条 HARD 判定过严，
补上同函数其它三条已有的证据检查即可解锁一批切点。该函数确实存在不对称
（见 §4.3），但**收益假设被实测否掉**：

| 指标 | 值 |
| --- | --- |
| 覆盖 | 15 集 / 5,219 条冻结父字幕 / 54,897 词 |
| 枚举的内部候选切点 | 49,678 |
| 现规则下已合法但未被选中（纯代价决策） | 2,122 |
| 现规则下被判非法 | 47,471 |
| **仅**因 `relative_clause_entrance_split` 或 `dependent_clause_entrance_split` 被判非法 | **98** |
| ↳ 仅 relative / 仅 dependent / 两者兼有 | 41 / 57 / 0 |
| 这两条 + 其它 code 共同判非法 | 1,079 |
| 98 条涉及的不同父字幕 | 97 |
| ↳ 其中 ≥17 词的父字幕 | 17 |
| 98 条命中 S0123 / S0132 / S0192 | **0** |

【实测】`boundary_flip_measurement.json` / `boundary_flip_stage2.json`。

更重要的是**逐条人工检视这 98 条，多数本来就应当被挡**，属限定性关系从句：

```
…they're going to buy the mine            ┃ that extracts the silicon.
…their chocolate with Chinese flavors     ┃ that the mass-market foreign brands just…
…a nation of 1.4 billion people           ┃ who historically ate only 1% of…
…And well, what it means                  ┃ when these high level models break loose…
```

**结论：给这两条加笼统豁免会让输出变差。不要按此方向改。**
若要改，只能针对 §4.3 与 §4.4 两个精确缺陷，不能整体放宽。

---

## 2.【实测】生产自证矛盾：9.96%

把每一对**相邻且词号连续**的冻结父字幕（即生产当初实际做出的切分决策，且已经通过
校验、已经参与合成）重新喂回今天的 `_evaluate_item_pair_for_final_boundary`：

| 指标 | 值 |
| --- | --- |
| 生产已接受的父间边界 | 5,180 |
| 被今天的规则判为非法 | **516** |
| 占比 | **9.96%** |
| 分布 | 23 个产物集**全部**命中，2.5% – 20.0% |

按 rule code（可多重命中）：

| code | 条数 |
| --- | --- |
| `open_subordinate_prefix_fragment` | 110 |
| `dependency_phrase_entrance_split` | 64 |
| `right_orphaned_finite_predicate` | 64 |
| `predicate_attached_continuation_split` | 62 |
| `coordinated_constituent_split` | 52 |
| `short_open_prefix_fragment` | 47 |
| `relative_clause_entrance_split` | 40 |
| `weak_subject_fragment` | 37 |
| `dependent_clause_entrance_split` | 32 |
| `incomplete_short_fragment` | 23 |
| `post_noun_participial_modifier_split` | 14 |
| `subject_finite_verb_split` | 12 |
| `incomplete_interrogative_fragment` / `unfinished_wh_complement_fragment` / `object_attached_modifier_split` | 各 10 |
| 其余 5 个 code | 共 23 |

**这 516 条是混合体，必须分开看，不要整体解读：**

一类是规则确实过严，边界本身没问题。典型：

```
…Yeah. Let's unpack that divergence  ┃  because the US and China are playing…   pause=200ms
…The quality is globally recognized, ┃  which proves this domestic wave is…      pause=80ms
```

左侧都是完整主句，右侧另起从句，且这类切点**已经在成品中播出**。

另一类是当年确实切错了、规则变严后才抓到。典型：

```
…Because instead of hiring traditional film crews, ┃ production companies started…  pause=441ms
```

左侧无主句，`open_subordinate_prefix_fragment` 命中正确。

**【推断】真正的问题不在某一条规则，而在回归防线：**
仓库中不存在任何"现规则必须仍然接受历史已发布输出"的不变量测试。
规则一路收紧，但从未回头验证收紧是否否掉了过去做对的判断。
同一病灶的另一个表现：S9522 在 30 项回归中失败已持续 8 天，仓库无 xfail/skip 机制，
`29/30` 被事实上当作通过。

**建议（低风险、可先做）**：把这 5,180 个边界固化为快照测试。任何"收紧"改动若使
非法数从 516 上升，即为回归信号；若下降，即为收益证据。这条不依赖本报告其余任何结论。

---

## 3.【实测】地基缺陷：`_fragment_has_finite_predicate` 单向漏判 42%

`screen_editor.py:6697-6715`。实现是**一张硬编码词表**：45 个助动词/情态词
+ 10 个实义动词（`changed / worked / reported / started / ended / matters / matter /
happened / became / felt / seemed`）+ `endswith("n't")`。无形态分析，**未使用 spaCy**
——尽管同一个类在 `_load_syntax_nlp`（12233-12262）中已经加载了 `en_core_web_sm`。

在本仓库自己的 5,219 条冻结父字幕上，与 spaCy 的有限动词标注对比：

| 指标 | 值 |
| --- | --- |
| 双方都判"有谓语" | 2,509 |
| 双方都判"无谓语" | 869 |
| **词表判"无"、spaCy 判"有"（过严方向）** | **1,827** |
| ↳ 占全部父字幕 | **35.01%** |
| ↳ 占"确实含有限动词"的父字幕 | **42.14%** |
| 词表判"有"、spaCy 判"无"（过宽方向） | **14** |

即：**几乎纯单向过严**。那 14 条经检视均为词表命中 `be`/`being` 而实际是非限定形式
（`being built in America`、`only to be forced to use it`），属可接受噪声。

漏判最多的动词（lemma/tag）：

| 漏判 | 次数 | 说明 |
| --- | --- | --- |
| `be/VBZ` | 230 | **`'s`** |
| `be/VBP` | 98 | **`'re` / `'m`** |
| `know/VBP` | 44 | |
| `mean/VBP` | 42 | |
| `make/VBZ` | 34 | |
| `see/VBP` | 29 | |
| `look/VBP` | 22 | |
| `get/VBP` | 18 | |
| `bring/VBZ` | 17 | |
| `can/MD` | 17 | 情态词漏判 |

**头号成因是缩写未入表**：词表写了 `is / are / am`，没写 `'s / 're / 'm / 've / 'll / 'd`
（`_word_tokens` 的正则 `[A-Za-z]+(?:'[A-Za-z]+)?` 会把 `it's` 保留为单 token）。
播客口语中缩写高频，于是：

```
It's really about how distinct market environments        →  判为"无谓语碎片"
They're optimizing the trade-offs between the cost…      →  判为"无谓语碎片"
I'm just stuck on the physical reality of this.          →  判为"无谓语碎片"
And that fear gets magnified tenfold                     →  判为"无谓语碎片"
Let's track that panic                                   →  判为"无谓语碎片"
```

**需要覆盖的动词 lemma 共 649 个，补丁表里只有 10 个。**这 10 个词的构成
（`changed / worked / reported / …`）本身就是"撞到误判就贴一个词"的证据，
该路径不可能通过继续补表收敛。

### 3.1 正确实现已经在仓库里，只是没被生产链路使用

`scripts/audit_visual_temporal_splits.py:45-67`：

```python
def _has_finite_predicate(text: str) -> bool:
    tokens = _tokens(text)
    if any(token in FINITE_AUXILIARIES for token in tokens):
        return True
    ...  # 惰性加载 en_core_web_sm，缓存在函数属性上
    return any(
        token.pos_ in {"VERB", "AUX"}
        and token.tag_ not in {"VB", "VBG", "VBN"}
        for token in nlp(text)
    )
```

**词表优先 + spaCy 回落**，23 行，语义正确（排除 VB/VBG/VBN 即排除不定式、动名词、
过去分词，剩下的就是有限形式）。生产链路走的是 6697 那份。

### 3.2 影响面

直接调用点：`6318` / `6319`（WH 分支）、`6366`（存入 fragment 字典的
`has_finite_predicate` 键）、`6646`、`6759`、`14468`。

经 `6366` 的字典键间接门控（`not has_finite_predicate` 即触发）：
`5963` `visual_preposition_led_fragment`、`5965-5971` `visual_open_phrase_fragment` /
`visual_short_subject_or_connector_fragment` / `visual_open_clause_fragment`、
`5977-5983` `visual_connector_led_noun_phrase_fragment`、`6383` / `6430` / `6445`，
以及 `6466` 的派生标志 `has_independent_meaning = has_finite_predicate and word_count >= 4`。

### 3.3【实测】把它换成 §3.1 那份之后的反事实

在独立进程内 monkeypatch（**磁盘代码未改**），对 §2 的 5,180 个生产已接受边界重测：

| 指标 | 值 |
| --- | --- |
| 修复前判非法 | 516 |
| 修复后判非法 | 484 |
| **消解的矛盾** | **32** |
| **新增非法** | **0** |
| 非法率 | 9.96% → 9.34% |

分 code：`weak_subject_fragment` 37→20（−17）、`short_open_prefix_fragment` 47→31（−16）、
`unfinished_wh_complement_fragment` 10→7（−3）。

**诚实说明收益边界**：`open_subordinate_prefix_fragment`(110) 与
`right_orphaned_finite_predicate`(64) 在此次反事实中**完全没有变化**，说明它们不经过这个
helper，各有独立实现。因此"修这一个函数"在**父间边界这一个闸门**上只值 32 条。

**未测部分（不夸大）**：§3.2 列出的 5 条 `visual_*` 判定走显示层路径，不在
`_evaluate_item_pair_for_final_boundary` 内，本次未测量。该 helper 的真实作用面很可能
显著大于 32，但**目前没有数字支撑，请勿引用为已证事实**。

**风险评级：极低。**函数是 `@classmethod`，签名纯净 `(words) -> bool`，
反事实中新增非法为 0，且替换目标是仓库内已存在、已在审计脚本中运行的实现。

---

## 4.【已核实】其余具体缺陷（一手读代码，含 file:line）

### 4.1 `_auditable_atomic_boundary_issues` 可静默全失效

`screen_editor.py:9570-9586`。9573-9574 只取 `entries[left].get("token")`，
缺少 `or surface` 回退；对比 `9045-9050` 的同类取值**有**回退。
若 `_active_word_entries` 条目缺 `token` 键，该函数 5 条判定**全部静默变成 no-op**，
不报错、不告警。

### 4.2 8 份互相竞争的坏切点判定，且同名 rule code 语义冲突

| 位置 | 说明 |
| --- | --- |
| `6259` `_cross_item_structural_boundary_issues` | 唯一持 cue 对级子句状态，**不应合并** |
| `7894` `_boundary_bad_cut_reasons` | 纯透传，零逻辑，**可删** |
| `9038` `_hard_stable_cut_issues` | 唯一基于词账本 + spaCy 的真闸门，**应作唯一真源**；`9126` 有 `pause_ms >= 450` 安全阀 |
| `9570` `_auditable_atomic_boundary_issues` | 是 `9038` 的真子集，**应改为 `atomic=True` 过滤视图** |
| `9974` `_is_bad_boundary_pair` | 53 个硬编码词对，仅 +160 软代价 |
| `14053` `_bad_cut_issues` | |
| `14472` `_syntax_boundary_reasons` | 保留为 `word_continuity == False` 降级路径，但规则体须与 `9038` 同源 |
| `14596` `_bad_cut_reasons` | 返回**中文句子**而非稳定 rule code；`bad_end` 58 项无标点上下文 |

**同名 code 语义冲突（已确认 2 处）：**

- `auxiliary_predicate_split`：`9589` 判 `predicate_starts` / `-ed` / `-ing`；`14527` 只判 `-ing`。
- `possessive_head_split`：`9691-9694` 豁免右侧并列连词；`14545` 无此豁免。

另有第三份独立副本在仓库外的测试侧：`tests/caption_audit/metrics.py:769`，
已腐化至 15 个 reason code 只剩 13，**缺失的正好是新测试覆盖的那 2 个**
——即应用侧改动无法被该路径捕获。

### 4.3 `_cross_item_structural_boundary_issues` 内部判据不对称

同函数 5 条判定，唯二 HARD 的恰是唯二**不带证据检查**的：

- `6297-6298` `relative_clause_entrance_split`：右侧首词 ∈ `{that, which, who, whom, whose}`
  → **无条件 HARD**。不看前置逗号、不看停顿、不看左侧是否已构成完整主句。
- `6304-6305` `dependent_clause_entrance_split`：右侧首词 ∈ 9 个从属连词且 `len(left_words) <= 10`
  → HARD。**不调用** `_fragment_has_finite_predicate(left_words)`，而同函数
  `6316-6321` 的 WH 分支两侧都验。

对比同函数另三条：WH 补语（`6316-6321`）两侧验有限谓语；
`leading_prepositional_fragment`（`6327-6332`）有 2 个豁免且仅 REVIEW；
`coordinated_continuation_fragment`（`6334-6338`）验左侧标点且仅 REVIEW。

**该函数全域无停顿豁免**（`6259-6346` 内 `pause_ms` 零出现），
对比 `_hard_stable_cut_issues` 在 `9126` 有 `pause_ms >= 450` 安全阀。
`_is_unambiguous_sentence_terminal`（`9265-9304`）只认 `.!?`，逗号不豁免。

**自相矛盾**：`_cut_boundary_score`（`8926`）在 `8973` 对 `which/who/that` 的处理是
"前面**没有**逗号才 +20"，且 `8977-8979` 的 `_dangerous_segment_start_tokens`
明确对"逗号 + which/who/that"开洞——作者在打分层写明逗号后的关系从句合法，
但 `6297` 的无条件 HARD 在 cue 对层把它覆盖了。

**这不是审计标记，是真在删候选**（调用链已核实）：
`_stable_global_ranges.edge_cost`（`10004`）→ `10024` `_stable_candidate_display_safe`（`10060`）
→ `10070` `_evaluate_item_pair_for_final_boundary`（`6198`）→ `6222-6226` 合并 HARD
→ `6256` `legal=False` → `edge_cost` 返回 `None` → **该边从 DP 搜索图消失**。

### 4.4 `relative_clause_entrance_split` 不做词性判别

对 `that` 一律视为关系代词，把指示限定词与指示代词也一并否决：

```
…shifting its economy away from basic manufacturing, ┃ that historical overinvestment in…   ← that = DET
…if people are watching their wallets,               ┃ that just doesn't seem like enough.  ← that = 指示代词
```

同一个类已加载 spaCy，DET vs PRON/relativizer 判别成本近乎为零。
**这是纯精度 bug，与 §1 的"放宽"是两件事**：修它不会放开限定性关系从句。

---

## 5.【已核实 + 推断】架构缺口：切分层对分页可行性完全盲

**【已核实】** `screen_editor.py` 全文 grep `font_size|pixel|chars_per_line|max_lines|line_width`
→ **0 命中**；import 区无 `stable_display_planner`。
切分层唯一的下游代理量是硬编码的 16 词上限
（`_stable_word_ranges_for_span` `8916` 行 `min(..., 16)`；`emergency = 19` 同样硬编码，配置改不动）。

**【已核实】** 分页层的真实约束是**像素**：每页须在 ≤2 行 × 四档宽度 profile
（1100 / 1260 / 1455 / 1498 设计像素）内排下，且每页 ≥900ms
（`ARTICLE_PAGE_MIN_DURATION_MS`）、每页 ≥4 词（`ARTICLE_VISUAL_PAGE_MIN_WORDS`）、
总页数 ≤4（`ARTICLE_VISUAL_PAGE_MAX_PAGES`）；字号档位仅 56/54/52（50 为 legacy 只读校验）。

**【推断】** 这就是"语法合法但无法分页"父字幕的产生机制：切分层在一个对真实约束
不可见的空间里做决策，分页层只能事后枚举、枚举到失败。**机制不堵，每一集都会新生成
这类父字幕**，人工标黄量不会随时间下降。

### 5.1 另一处未对齐：平局裁决策略不一致

**【已核实】** `stable_english_optimizer.plan_english_cue_ranges` 的 `_path_key`
= `(cost, tuple(ends))`，代价相同时按切点索引字典序 → **更靠左的切点胜出**，
这是元组比较的副作用而非显式设计。全仓 grep `equal_risk|tie_break|prefer_pause`
在 `screen_editor.py` **0 命中**。
对比分页层 `stable_display_planner.py:68-71` 有显式 `(risk_tier, score)` 二元组分层排序。
切分层的 `boundary_score` 是单一 float，停顿只是 −28 / −12 的连续分量，
被其它加分抵平后即失效。

### 5.2【推断】对 2026-08-23 17:12 那次结论的补充

先前结论为："固定父字幕优化有效但只改善 4 条；局部移动英文切点净改善 0 条；
改变相邻父字幕数量 18,457 个候选中可行结果为 0。"

**审计者认同这三个实验的数据，但认为其解释需要修正。**
三个实验的搜索空间**全部位于切分层内部**，而 §5 表明真实可行性约束位于**像素层**，
且切分层对该约束完全不可见。在对目标函数不可见的空间内做局部搜索，
18,457 个候选产出 0 个可行是**结构性必然，而非实验运气**。

因此这批数据支持的结论是"**沿切分层内部局部搜索这个方向没有收益**"，
而不足以支持"当前架构下无法进一步自动化"。二者不等价。

### 5.3【已核实】S0123 / S0132 / S0192 维持"放弃、标黄"判断

三条同属白宫集，checkpoint `20260823T063436.783343-e950e557`：

| ID | 词号 | 词数 | 时长 | 文本 |
| --- | --- | --- | --- | --- |
| S0123 | 1433-1454 | 22 | ≈10.2s | `Now, the source notes that 303 billion would represent an improbable 56% of all of America's imports from China back in 2018.` |
| S0132 | 1530-1543 | 14 | ≈7.1s | `They argue Navarro is deliberately conflating legal, rules-compliant supply chain restructuring with outright smuggling.` |
| S0192 | 2185-2203 | 19 | ≈7.9s | `They point out that what Navarro just described is literally just the normal, everyday infrastructure of modern global trade.` |

三条 reason 完全相同：`no_complete_normal_font_page_partition`；
attempted 含 `fixed_font_span_unreadable` / `hard_page_boundary` /
`page_boundary_timing_invalid` / `no_complete_legal_page_partition`。

**`cue_duration_below_page_minimum` 三条均缺席 → 不是时间受限。**
真因是原子链不可切：`303 billion` 数字量级、
`legal, rules-compliant supply chain restructuring` 修饰-中心链、
`of all of America's imports` / `of modern global trade` of-补语。
S0132 枚举 61 个 partition 全灭。§1 那 98 个新增切点命中这三条 = 0。

**同意维持"放弃、标黄给人工"。**但这是对**这三条**的处置，不是对§5 机制问题的处置。

**文档冲突提示**：`docs/audits/2026-08-23/recent-actual-page-quality-audit.md:83`
写作 S0123/S0133/S0193，与同文件 `:258` 及全部产物冲突，`:258` 与产物一致。

---

## 6.【已核实】上下文成本：哪些冗余在拖累模型

按"误导代价"排序，不按体积排序。

**最贵：完整的假闭环（检测 → 上报 → 无人消费）。**
模型读到检测逻辑存在，就会假设该检测生效，从而在错误前提上继续推理。
`_detect_cross_id_anchor_misplacement`（16 个死键）、
`_validation_review_reason`（12 个死键）是完整链条。
全仓合计 **238 个死键 / 323 个写入点**。

**其次：能打开但指向错误位置的引用**，比断链更危险。
`docs/audits/core-workflow-audit-2026-08-16.md` 的 **7/7** 个符号级行号
全部指向无关函数（该文档引用的 P2-2 实际对应 `_bad_cut_reasons` `14596`，
文中所标 12091 已过期，且编号误作 P2-3）。

**文档层：**
- `docs/CURRENT_STATUS.md` 与必读的 `docs/CURRENT_STATE.md` **仅一字母之差**，
  内容冲突，且违反 `AGENTS.md:41`。
- `docs/CURRENT_STATE.md` 在 160 个相邻小节转换中有 **16 处日期倒序**
  → 读头部或读尾部都不可靠（审计者先前认为它严格新在前，此判断已推翻）。
- 该孤儿文档中一个 4 周前的开放问题，其答案就在 `screen_editor.py:12819`。

**规则层：** `AGENTS.md:96` 正在保护一个死函数 `_quality_check_candidate_segments`；
`AGENTS.md:97` 被一个 158 行的死 backchannel 簇直接违反。
死方法合计 11 个 / 188 行。

**版本漂移：** 必读文档中存在 v31 / v32 并存
（代码真值为 `article-fixed-font-pages-v32`）；测试 fixture 中残留 v27 / v28
——后者使回归保持绿色但不再反映实际契约。

**测量：** 必读量 **370,744 B**（含任务日志 **592,355 B**）→ 可压至 **138,088 B**，
降幅 **63% / 77%**。

---

## 7.【已推翻】审计者自己被数据否掉的假设（保留以防重复踩坑）

| 假设 | 实际 |
| --- | --- |
| 存在零引用的模块级常量 | **0 个** |
| 交接文档之间存在逐字复制粘贴 | **0 对**，是独立撰写 |
| `_allocate_semantic_group_translations_concurrent` 是死码 | **不是**。`screen_editor.py:20511-20517` 在 `allocation_max_concurrency > 1 and len(payload_chunks) > 1` 时条件调用 |
| `tests/` 有被 skip/xfail 掩盖的失败 | **0 个** skip / **0 个** xfail / **0 处**注释掉的断言 |
| 测试体积构成上下文税 | 测试冗余 **< 250 行（0.5%）**，**不构成**上下文税 |
| `docs/CURRENT_STATE.md` 严格新在前 | 有 **16 处**日期倒序 |
| 放宽 §4.3 两条 HARD 即可解锁切点 | 见 §1，仅 98 条且多数应当被挡 |

---

## 8. 建议的下手顺序（仅为判断，审计者未执行任何改动）

按"风险 / 收益确定性"排序，前三项互不依赖，可独立进行。

**第 1 步｜风险：极低。收益：确定（防回归）。**
把 §2 的 5,180 个生产已接受边界固化为快照测试，并给 S9522 建立
xfail/skip 机制以使 `29/30` 不再被当作通过。此步不改变任何行为，只建立度量。
没有它，后续任何"收紧"或"放宽"都无法判断是收益还是回归。

**第 2 步｜风险：极低。收益：已测 32 条 + 未测的显示层作用面。**
让 `screen_editor.py:6697` 改用 `scripts/audit_visual_temporal_splits.py:45-67`
已有的"词表优先 + spaCy 回落"实现（建议提取为单一真源供两处共用）。
反事实新增非法为 0。做完应重测 §3.2 列出的 5 条 `visual_*` 判定以补上未测部分。

**第 3 步｜风险：低。收益：精度修正，不放开限定性从句。**
给 `6297` 的 `relative_clause_entrance_split` 加 spaCy 词性判别，
区分 `that` 作 DET / 指示代词 / 关系化标记；并修 §4.1 的
`or surface` 回退缺失。同时消解 §4.2 的两处同名 code 语义冲突，
并清理 `tests/caption_audit/metrics.py:769` 的第三份副本。

**第 4 步｜风险：高。收益：唯一能触达 90-95% 的方向。**
把分页可行性反馈进切分层——最小形式不是重构，而是给切分层的
`edge_cost` 增加一个"该候选跨度在 56/54/52 三档字号下是否存在可行分页"的
可行性探针，替代当前硬编码的 16 词代理量。
这一步必须在第 1 步的度量基线建立之后进行。

---

## 9. 本次审计的偏差与置信度声明

- **样本**：23 个产物集、每集单次运行的冻结产物。未覆盖不同 ASR 质量、
  不同说话人数、非播客素材。
- **测量哈钦构造**：为规避 `__init__`（`698` 行 `CacheManager` 写 AppData、
  `699` 行 `_init_client()`）的副作用，脚本用 `ScreenSubtitleEditor.__new__`
  + 显式属性设置构造实例，复制 `scripts/audit_pre_id_joint_page_feasibility.py`
  `_make_editor`（`173+`）的既有做法。构造保真度的上界由 §2 的 9.96% 界定
  ——其中含哈钦误差与真实规则漂移，二者未分离。
- **旧版哈钦校验**：对 `english-boundary-audit.json` 的 `rule_codes` 逐条比对，
  2,438 / 2,585 = **94.31%** 一致。不一致主要来自该 JSON 的 `rule_codes`
  混入了其它 predicate 的 code，非哈钦缺陷；§2 已改用与反事实同一个函数以消除此偏差。
- **spaCy 一致性**：模型直接从 `runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0`
  按绝对路径加载，与仓库自带版本完全相同；注入方式为 `ed._syntax_nlp = nlp`
  （`_load_syntax_nlp` `12234` 行对非 None 短路返回），故不存在
  "spaCy 缺失导致 hint 缺失、进而少判"的方向性偏差。
- **spaCy 不是外部标尺**：§3 用 spaCy 作对照，是因为本仓库已经依赖并已在
  `_load_syntax_nlp` 与 `audit_visual_temporal_splits.py` 中使用它。
  这是"与项目自己已信任的信号对照"，不是引入新标准。
- **§3 的显示层作用面未测**，§5 的机制结论为推断，二者请勿当作已证事实引用。

---

## 10. 第二轮只读核实（2026-08-24 追加，动手前的前置检查）

本节缘起：接手模型已依据本报告 §8 给出四步计划——①建立历史边界回归基线
②修有限谓语检测 ③修 `that` 词性与重复规则 ④做切分层与分页层联合可行性实验，
并正确地把第 4 步标为"最值得验证"而非"已证结果"。
审计者认同该计划与其顺序。本节是**动手前**补做的核实，包含两处对前文的更正
和一条新发现。**本节同样未修改任何既有文件。**

### 10.1【已更正】§4.1 的严重性被说重了——它是潜伏缺陷，不是现行缺陷

前文 §4.1 称 `_auditable_atomic_boundary_issues`（`screen_editor.py:9570-9586`）
因缺少 `or surface` 回退而"可静默全失效"。二次核实后必须收窄这个说法：

- `_word_time_entries`（`17912-17941`）是生产链路**唯一**的 `_active_word_entries`
  构造入口（赋值点仅 `851` / `861` / `866`），它在 `17935` 行**无条件**写入 `"token"` 键。
- 两个审计哈钦也都写：`scripts/audit_pre_id_joint_page_feasibility.py:182`、
  `scripts/run_allocation_only_replay.py:66`。
- `8097-8099` 只是就地补写 `start_time` / `end_time` / `alignment_source`，不新建条目。

**结论：今天不存在任何使 `token` 缺失的代码路径，那 5 条原子判定并没有在静默失效。**
补上 `or surface`（与 `9045-9050` 对齐）今天**零行为变化**——
所以它是零风险的一致性修补，**既不要算作收益，也不要担心它会一次性点亮 5 条休眠规则**。
前文措辞暗示过后者，此处撤回。

### 10.2【已核实·新发现】矛盾最大头 `open_subordinate_prefix_fragment` 的病灶是一条正则，与有限谓语词表无关

§2 的 516 条自证矛盾里，`open_subordinate_prefix_fragment` 占 **110 条，为最大单一 code**。
它的判定源是 `_is_open_subordinate_prefix`（`screen_editor.py:6575-6591`），实现如下：

```python
def _is_open_subordinate_prefix(self, item: ScreenSubtitleItem) -> bool:
    """Detect a non-terminal dependent introduction awaiting a main clause."""
    text = self._normalize_text(item.original)
    if re.search(r"[.!?][\"')\]]*\s*$", text):
        return False
    normalized = text.casefold()
    normalized = re.sub(r"^(?:(?:yes|yeah|right|exactly|absolutely|definitely|sure|okay|ok)[.!?]\s*)+", "", normalized)
    return bool(re.match(
        r"^(?:because\s+)?(?:because|if|when|while|although|though|unless|until|once|whereas)\b",
        normalized))
```

**三点已核实的事实：**

1. **它从不检查主句是否已经出现。**判据只有两条：开头是否为 10 个从属连词之一、
   结尾是否有终止标点。唯一的逃生口是句末 `.!?`。因此像
   `When the US did that, China responded immediately`
   这种**主句已在同一条 cue 内出现、只是整句尚未结束**的情形，一律被判 HARD。
2. **它压根不调用 `_fragment_has_finite_predicate`。**这正是 §3.3 反事实中这 110 条
   "完全没有变化"的原因——第 2 步无论怎么修有限谓语检测，都碰不到这一块。
3. **同名 code 有两个发射源**：`6291`（经本函数）与 `6439`（经 `_fragment_issues`
   路径的 `open_subordinate_prefix` 局部变量）。§4.2 的"同名 code 语义冲突"清单应补上这一条。
   此外正则里的 `^(?:because\s+)?` 前缀在后续分支已包含 `because`，属冗余（可匹配 "because because"），
   疑为残留。
4. 本函数全域**无停顿豁免**（`6575-6591` 内 `pause_ms` 零出现），与 §4.3 记录的
   `_cross_item_structural_boundary_issues` 同病。

**同一文件内已有正确工具，但不能直接替换。**
`_visual_temporal_clause_shape`（`5568-5644`）是基于 spaCy 依存树的"完整主句"判定器：
取 `dep_ == "ROOT"`，判 `root_is_finite`（`5583-5586`：`pos_ in {VERB,AUX}` 且
`tag_ not in {VB,VBG,VBN}`）、`root_has_finite_auxiliary`（`5587-5595`）、
`root_is_imperative`（`5607-5623`），并在 `5638-5644` 返回 `complete_main_clause`。
**但它的定义是：**

```python
"complete_main_clause": bool(
    (root_is_finite or root_has_finite_auxiliary or root_is_imperative)
    and not leading_subordinator          # ← 5641
),
```

而 `leading_subordinator`（`5596-5600`）用的是**位置代理**：

```python
leading_subordinator = any(
    token.i < root.i and (token.dep_ == "mark" or token.pos_ == "SCONJ")
    for token in doc
)
```

任何"前置从句 + 主句"的句子都满足"ROOT 之前存在 mark/SCONJ"，
所以 `complete_main_clause` 对 `When the US did that, China responded immediately`
**同样返回 False**。直接拿它替换正则不会解决问题。

**【推断】正确判据应是依存祖先关系，而非词序位置：**
"从属连词是否支配 ROOT"，而不是"从属连词是否出现在 ROOT 之前"。即

- ROOT 为有限形式（沿用 `5583-5595` 的既有定义），**且**
- 该从属连词不是 ROOT 祖先链上的 `mark`（等价地：它所标记的从句是 ROOT 的
  `advcl` / `ccomp` 等**子节点**，而非 ROOT 本身所在的从句）。

对照两个例子：
`When the US did that, China responded immediately` → `When` 是 `did` 的 `mark`，
`did` 是 ROOT `responded` 的 `advcl` 子节点 → 从句已闭合，主句在，**应放行**；
`Because instead of hiring traditional film crews,` → 从句之外不存在有限 ROOT
→ 确实悬空，**应继续挡**（此例正是 §2 中"规则抓对了"的那一类）。

**这是 §2 那 516 条里最大的单点可救空间，但收益尚未测量，请勿当作已证事实。**
测量方案见 §11。

### 10.3【已核实】§3.3 中"那 64 条不动"的机制已确认

§3.3 曾指出 `right_orphaned_finite_predicate`（64 条）在有限谓语反事实中完全没有变化，
但未给出原因。现已确认：该 code 发射于 `5826`，所属函数为
`_right_orphaned_finite_predicate_issues`（`5746-5830`），
其 `5760` 行走 `self._load_syntax_nlp()`、`5823` 行遍历 `doc` ——
**它本来就在用 spaCy，不经过那张硬编码词表**。

因此第 2 步（修有限谓语检测）的收益边界现在是完整的：
516 条里最大的两块——`open_subordinate_prefix_fragment` 110 条（§10.2，走正则）
与 `right_orphaned_finite_predicate` 64 条（走 spaCy）——**合计 174 条都不在其作用面内**。
第 2 步的盘子 = 已测的 32 条 + §3.2 列出的 5 条 `visual_*` 显示层判定（仍未测）。

### 10.4【已核实】第 2 步的性能约束，以及仓库内已有的正确缓存写法

**约束**：`screen_editor.py` 全文 grep `lru_cache|functools.cache|@cache`
→ **0 命中**。而 `_fragment_has_finite_predicate` 位于 DP 的
`edge_cost` 调用链上（`10004` → `10060` → `6198` → `6259` → `6318`/`6319`），
接入 spaCy 等价于"每评估一条候选边即 parse 一次"。
审计者自己的反事实脚本必须挂 `lru_cache(maxsize=200_000)` 才能在可接受时间内跑完。

**仓库已有正确写法可直接沿用** —— `_right_orphaned_finite_predicate_issues`
（`5752-5759`）：

```python
cache = getattr(self, "_orphaned_finite_predicate_cache", None)
if cache is None:
    cache = {}
    self._orphaned_finite_predicate_cache = cache
cache_key = (item.word_start, item.word_end, text)
cached = cache.get(cache_key)
if cached is not None:
    return list(cached)
nlp = self._load_syntax_nlp()
if not nlp:
    return []            # ← 优雅降级，spaCy 缺失时不报错
```

配套：缓存属性在 `__init__:706` 声明，在 `_prepare_syntax_cut_hints`
（`10094-10098`）每轮开头清空。**建议照此实现，不要引入 `lru_cache`**
（`lru_cache` 挂在类方法上会跨 run 泄漏，与 `10094-10098` 的每轮清空语义冲突）。

**一处改进**：上述缓存键为 `(word_start, word_end, text)`，含词号。
新 helper 建议**只用拼接后的 token 串作键**——DP 中同一段文字会在不同跨度上反复出现，
去掉词号可显著提高命中率。

### 10.5 第 1 步（回归基线）的两个做废风险

**风险一：哈钦不可中途更换。**§2 的 9.96% 是用 `ScreenSubtitleEditor.__new__`
构造的哈钦测得，构造保真度误差与真实规则漂移**未分离**（见 §9）。
这不妨碍它作为基线——只要"改前"与"改后"使用**同一个哈钦**，该误差即可对消。
但因此有两条硬要求：基线须在第 2 步之前冻结为 golden 文件，且须记录
**每条边界的 rule code 集合**而非仅总数；中途更换构造方式将使前后数字不可比。

**风险二：不要把"516 下降"当作唯一的好信号。**§2 已说明这 516 条是混合体：
一部分是规则过严而边界本身正确（`Let's unpack that divergence ┃ because…`，
左侧为完整主句且已合成播出），另一部分是当年确实切错、规则收紧后才抓到
（`Because instead of hiring traditional film crews, ┃ …`，左侧无主句）。
若把"总数下降"当作优化目标，将系统性地把规则推向放松——
**那正是 §1 已被自身数据推翻的方向**。
建议：测试输出**变化清单（delta）**，人工只复核发生变化的那几条，而不追踪总数。

### 10.6 第 4 步（分页可行性探针）的两条方向性要求

**要求一：探针必须是软代价，不得返回 `None`。**
当前病根正是 `edge_cost`（`10004-10028`）返回 `None` 会把该边从 DP 搜索图中删除
（调用链见 §4.3 末段）。探针若同样删边，一旦判错即不可恢复。
应先实现为代价项，使 DP 仍能选择"略差但排得下"的切点；
取得数据后再讨论是否收紧为硬闸门。

**要求二：探针误差必须偏向"可行"。**
误判为"不可行"会删掉好边——与现有过严缺陷同病；
误判为"可行"最坏只是分页层照旧枚举失败，**不比今天更差**。故宁可放过，不可错杀。

**实现提示（已核实）**：不要用 `app/core/utils/ass_auto_wrap.py:70` 的
`estimate_text_width`（CJK 计 `font_size`、其余一律 `font_size * 0.5`）作为英文探针——
英文字符步进宽度差异极大，该估计器对英文不可用。
真实渲染路径是 `podcast_learning_video.py:916` 的
`text_w(draw, text, fnt) = draw.textbbox(...)`，字体为
`article_subtitle_en_font`（`855-862`）→ `RobotoSlab-SemiBold.ttf`，字号经 `acx()` 缩放。
建议一次性导出 56/54/52 三档的字符步进宽度表并落盘，探针查表，
再在全部 5,219 条父字幕上验证"探针判不可行 ⇒ 渲染器同意"的单边保守性，然后才接线。

**落点建议**：`app/core/subtitle_processor/text_metrics.py`
（52 行、零重依赖、已被 `screen_editor.py:70` 与 `app/core/article_context.py:16` 引用，
且 `HARD_ENGLISH_WORD_LIMIT = 16` 本就定义于此）。
即这一步是**把容量模型搬到已有的共享叶子接缝**，不是重建。

### 10.7 本节的未测项（请勿引用为已证）

- §10.2 的依存祖先判据能救回 110 条中的多少、是否产生新增非法 —— **已于 §11 实测，
  且结论是该处方作废（只值 15 条）。本条已解除未测状态，请直接读 §11。**
- 单行页 vs 现行双行页的可行率对比 —— **仍未测**，见 §12（尚未产出）。
- §3.2 列出的 5 条 `visual_*` 显示层判定作用面 —— 仍**未测**（与第一轮相同）。


---

## 11. 第三轮：`open_subordinate_prefix_fragment` 反事实实测（2026-08-24 追加）

> **本节结论优先于 §10.2。** §10.2 提出的"依存祖先判据是 516 条里最大单点可救空间"
> 这句话**已被我自己的测量推翻**，正确判据是另一条（见 11.2）。
> 本轮仍未修改本仓库任何既有文件；全部改动都是进程内 monkeypatch。
>
> **给动手的模型的一句话摘要**：请采用 **arm F**（不是我上一轮暗示的方向，
> 也不是本轮数字最漂亮的 arm E）。理由是 11.5 的双向权衡，不是 11.1 的单向计数。

### 11.1 七个 arm 的实测结果

同一测量面：**23 个 work-dir，每个取 1 个产物集，覆盖约 15 个不同源集**
（改名重跑的同一集会被算两次，比例不受影响但那几集被双倍加权）/
**5,180 个"生产已接受并已合成"的父间边界**，
全部重新喂回 `_evaluate_item_pair_for_final_boundary`。

| arm | 改了什么 | 判非法 | 占比 | 相对现网**消掉** | 相对现网**新增非法** | `open_sub` 码命中 |
|---|---|---|---|---|---|---|
| **A** | 现网代码（基线） | 516 | 9.96% | 0 | 0 | 110 |
| **B** | 只修有限谓语词表（§3.3） | 484 | 9.34% | 32 | **0** | 110【推导】 |
| **C** | 只换依存祖先判据（§10.2 的处方） | 501 | 9.67% | 15 | **0** | 92 |
| **D** | B + C | 469 | 9.05% | 47 | **0** | 92 |
| **E** | 只在"从句自身无有限谓语"时才发火 | 440 | 8.49% | 76 | **0** | 12 |
| **F** | E + 追加要求"以逗号结尾"才豁免 | 452 | 8.73% | 64 | **0** | 37 |
| **G** | E + 有限谓语词表修复 | **405** | **7.82%** | **111** | **0** | 12 |

注：arm B 的 `open_sub` 命中 110 **是推导值，不在任何 JSON 里**（v1 的 per-code 表只有 A/C/D 列）。
依据是 E=12 且 G(E+词表修复)=12，即词表修复不改变该 code 的命中，故 B=A=110。
其余每一格都可在归档 JSON 中直接读到。

三点可直接使用的事实：

**（1）两个修复互不干扰、效果可加。** B 消 32、E 消 76、G 消 111 ≈ 32+76+3。
说明 §3.3 的词表修复和本节的 `open_sub` 修复落在几乎不重叠的边界集合上，
可以分两个 PR 独立上，不必担心相互抵消或叠加爆炸。

**（2）七个 arm 全部"新增非法 = 0"。** 在"生产已发布边界"这个面上，
这些改动是纯单向放宽，没有任何一条已发布边界因此变得非法。
**但这条性质本身不足以下结论**——§1 的处方就是死在这里，见 11.4。

**（3）F 比 E 差 12 条，但这 12 条不是损失。** 见 11.5。

### 11.2 【已推翻·我自己的假设】依存祖先判据只值 15 条，而且它"对得很偶然"

§10.2 我写的处方是：`ROOT 有限 且 从属连词不在 ROOT 的 mark 子节点上`
（即"从句已闭合 ⇒ 不该判碎片"）。arm C 实测**只消掉 15 条**，
远不如单纯修词表的 32 条，更谈不上"最大单点可救空间"。**这句话请从 §10.2 划掉。**

用 spaCy 直接探针查原因，发现一个必须写进项目笔记的事实：

> **spaCy 把作从属连词的 `when` 标成 `advmod` / `WRB`，而不是 `mark`。**
> `while` / `if` / `because` 才稳定标 `mark`。

所以"ROOT 的子节点里有 `mark`"这个测试对**每一条 `when` 开头的句子都无条件放行**——
不管结构是否真的闭合。arm C 消掉的那 15 条里绝大多数是 `when` 开头，
**它是靠一个词性标注的偏差碰对的，不是靠语法判据对的。**
任何后续基于 `dep_ == "mark"` 的判据都会继承这个坑；
若要走依存路线，从属连词集合必须同时接受 `mark` 与 `advmod/WRB`，并显式列举 `when/where/whenever`。

顺带更正一处措辞：§10.2 说 `_visual_temporal_clause_shape`（5568-5644）
"用位置代理 `token.i < root.i`"是对的，但我当时把它描述成主要缺陷；
真正更致命的是它和 arm C 共用的 `mark` 假设。两者都别直接搬。

### 11.3 【已核实】真正的判据是"从句自身有没有谓语"，不是"主句来了没有"

读 arm C 消掉的 15 条时诊断被改正了。它们**全部**是同一形状：
前置从句 + 逗号 + 主句落在下一条。例如

```
When you refine a barrel of crude, ┃ you only get a tiny percentage of jet fuel
If you look at all the chocolate eaten worldwide, ┃ only a microscopic 2% of it ...
While balancing safety and innovation is a global challenge, ┃ Chinese leaders are willing ...
```

这是英语里最安全的断点之一，而且生产**已经这么切并合成了**。
对照现网规则唯一抓对的那类：

```
Because instead of hiring traditional film crews, ┃ production companies started ...
Because for the last hundred years, ┃ the momentum of the workforce was ...
If a neocloud company ┃ defaults on a billion dollar loan in year three,
```

左半**根本没有有限动词**——`Because` / `If` 什么都没管住，是真碎片。

**所以过严的不是"主句是否已出现"，而是"这个从句自身是否成句"。**
arm E 就是这一条：`从句无有限谓语 → 判碎片；有 → 放行`。
它把 `open_sub` 码命中从 110 压到 12，剩下的 12 条抽查全部是真碎片
（另有 2 条属于 spaCy 把 `help` 标成 `VB` 之类的标注误差，量级可忽略）。

判据只需 3 行，且**复用仓库已有写法**：
`pos_ in {VERB, AUX} and tag_ not in {VB, VBG, VBN}`
（与 `scripts/audit_visual_temporal_splits.py:45-67` 和 `screen_editor.py:5583-5586` 完全一致，
不引入新概念）。缓存请照 §10.4 的 5752-5759 模式，键用拼接后的 token 串。

### 11.4 补测：只看"已发布边界"会重犯 §1 的错，所以做了互补枚举

"新增非法 = 0"只证明**已经切过的地方**没变坏，
不能证明**没切过的地方**不会因为放宽而多出坏切点。§1 的处方正是死在这一步：
那 98 条被解锁的边界逐条看下来多数**本来就该挡**。所以对 arm E / F 补了反方向的一次枚举：

> 遍历 5,219 条冻结父字幕的**全部内部候选切点**，
> 找出"现网判非法、放宽后判合法"的切点，逐条人工看。

| 指标 | 数值 |
|---|---|
| 枚举候选切点总数 | 49,678 |
| 其中左半命中现网 gate 入口条件（唯一可能产生差异的子集） | 3,537 |
| **arm E 新增合法** | **105**（去重后 98 = 64 + 34，由两个互斥样本池相加得出，非直接读数） |
| **arm F 新增合法** | **69**（去重后 64） |
| arm E / arm F 新增非法 | **0 / 0**（`measure_open_subordinate_v4.py:139` 用 Counter 计数，键在 JSON 中缺失即从未自增 = 真 0；v3 的 JSON 另有显式 `newly_illegal_under_arm_E: 0`） |

（重复共 7 对，**全部来自"巧克力"那一集在两个 work-dir 下的重跑副本**——
同一位置被两个产物集各计一次。我最初解释成"一处在一个集里是父间边界、在另一个里是父内候选点"，
**那个机制是错的**：本节两个数出自同一次枚举，重复纯粹来自跨 work-dir 的同集重跑。）

### 11.5 【决定性】逐条看这 105 条 → 推荐 F，不推荐 E

**arm F 新增的那 69 条（去重 64 条）几乎全是教科书级好切点。** 全量看过，摘录：

```
While balancing safety and innovation is a global challenge, ┃ Chinese leaders are willing ...
If you scroll through these videos on social media, ┃ there is a recurring title that keeps ...
When you wake up the next day, ┃ your executive function is running on fumes.
Once you miss the entrance at the top, ┃ you can't just jump in halfway down.
Because their pensions are microscopic, ┃ they can't afford to buy property, so they are forced to rent.
Right. If the audience controls what's valuable, ┃ the gatekeepers have no power.
```

64 条里判为"平庸/略差"的约 5-6 条，且集中在一种形状：右半是极短尾巴
（`┃ right?`、`┃ maybe`、`┃ you...`）。这类应由"两侧最少词数"约束兜住，
**而不是靠 `open_sub` 这条语法规则兜**——用语法规则兜长度问题正是现网这堆缺陷的成因。
（现网切分层是否已有最小词数下限、下限是多少 —— **本轮未测**。）

**arm E 比 F 多开的那 36 条（去重 34 条）多数是本来就不该断的地方。** 全量列出后判定，
约 20-24 条明确有害，典型形状是把不可分的短语劈开：

```
Because buyers are usually just way ┃ too fragmented.
because the scale of this is hard ┃ to wrap my head around.
if they don't know what the final picture is supposed ┃ to look like?
Because the hyperscalers are no longer content ┃ just buying Adidas chips,
When she dates a man ┃ her own age or older,
If you feed a machine ┃ a massive diet of New York Times reporting ...
... store on Main Street 50 years ┃ ago,
... stuck at like one bar ┃ a year, ...
... and then ┃ everyone else just learns how to do it.
... in an anti-American scam, then ┃ America isn't just fighting a trade war ...
When a downturn hits, irregular workers are the first ones ┃ let go because ...
... a franchising model that only costs 8 300 ┃ to buy into, ...
```

**这就是 §1 的坑，位置一模一样。** 差别只在这次先看了才下结论。

**那么 F 相对 E "少消掉的 12 条"是不是损失？** 抽查这 12 条对应的生产已发布边界
（左半有有限谓语但不以逗号结尾），**约一半本身就是坏切点，生产切错了**：

```
because her visa status made it ┃ almost impossible for her to switch employers   ← 劈开 made it | impossible
If you are a company and a single client ┃ makes up nearly half of your premium   ← 主谓分离
... drains that battery, maybe ┃ the real trick is designing ...                  ← 断在 maybe 后
Because every two years, oil field depletion physically costs the world ┃ one Saudi Arabia's worth  ← 动宾分离
```

另一半（`... willing to pay millions of dollars ┃ just to experience something ...`）确实还行。
**所以 F 放弃的 12 条里有一半是"本该挡住的"，代价远小于 E 多开的 34 条坏切点。**

**这也顺带更正 §2 的一个隐含框架**：`生产已接受` 不等于 `切得好`。
既然已发布边界里 9.96% 自证非法、且抽查中确有真错切，
那么"消掉的矛盾条数"就**不能当作优化目标**——
最大化这个数会把规则一路放宽到把生产的错切也一并合法化。
§10.5 已经写过"不要把 516 下降当目标"，本节给出了它的具体反例。

### 11.6 给动手模型的落地形状

```
在 _is_open_subordinate_prefix (screen_editor.py:6575-6591) 现有正则全部命中之后，
追加一道豁免：若该 cue 自身含有限谓语（spaCy: pos_ ∈ {VERB,AUX} 且 tag_ ∉ {VB,VBG,VBN}）
           且 该 cue 以逗号结尾
   → 不再判 open_subordinate_prefix_fragment。
其余一切不变（终止标点逃生口、backchannel 前缀剥离、正则词表都别动）。
```

三条工程约束（均已核实，理由见 §10.4 / §10.6）：

1. **必须缓存**，键用拼接 token 串，照 5752-5759 的实例字典 + `getattr` 防御初始化写法；
   本文件全文 0 个 `lru_cache`，而这个 helper 在 DP 的 `edge_cost` 路径上
   （10004→10060→6198→6259→6291）。
2. **spaCy 不可用时必须降级为"按现网行为"**（`if not nlp: 走原正则`），不能降级成"放行"。
3. **同名 code 有两个发射点**：6291 与 6439（后者走 `_fragment_issues`）。
   只改 helper 两处同时生效；若只想改一处，请先确认另一处的语义是否也需要同步。

回归基线要求：把 arm A 的 516 条（含每条边界的 rule-code 集合）写成 golden 文件，
改动后断言 **新增非法 = 0**、且 **新增合法候选点数 ≤ 69**。
第二条断言比第一条重要——它才是防止重蹈 §1 的那道闸。

### 11.7 本节的证据分级与未测项

**【已实测】** 表 11.1 全部数字；11.4 的枚举全部数字；11.5 引用的所有例句
（均来自 `word-ledger.json` + `final-cue-timeline.json` 冻结产物，非构造）。

**【已推翻】** §10.2 的"依存祖先判据是最大单点可救空间"；`dep_ == "mark"` 可用于识别从属连词。

**【人工判断】** 11.5 里"好切点 / 坏切点"的分类是我逐条读英文下的判断，
不是任何指标算出来的。34 条与 64 条我都全量列出在测量产物里，
**请自行复核后再采纳结论**，不要只引用比例。

**【未测】**

- arm **F + 有限谓语词表修复** 的联合值。按 11.1 的可加性外推约为消掉 96 条
  （64+32），但**这是推断，未实测**。
- 改动对**最终选中的切点**的影响。本节全部结论都停在"候选点合法性"层面；
  合法 ≠ 会被 DP 选中（软代价仍在）。真实输出差异需要重跑切分才知道。
- 切分层是否已有"两侧最少词数"下限（关系到 11.5 那 5-6 条短尾巴是否已被兜住）。
- 单行页 vs 现行双行页的可行率对比 —— 仍未测，见 §12（下一节，尚未产出）。
- §3.2 那 5 条 `visual_*` 显示层判定的作用面 —— 三轮均未测。

**测量脚本**（在仓库外，未落盘到本项目源码树）：
`measure_open_subordinate.py`（arms A-D）、`_v2.py`（arms A/E/F/G）、
`_v3.py`（互补枚举）、`_v4.py`（E/F 双臂互补枚举），
产物 `open_subordinate_counterfactual*.json`、`open_subordinate_new_candidates*.json`。
已随本文件一并归档到 `docs/audits/2026-08-24/external-claude-measurement/`。

---

## 12. 第三轮：单行页 vs 现行双行页可行性实测（2026-08-24 追加）

> 这一节回答 GPT 第 4 步（"切分层与分页层联合可行性实验"）里关于**分页层**的那一半，
> 也回答"单行分页是不是更好"。**结论与我先前的口头倾向不同**：
> 不要改成单行分页；真正该动的是 `podcast_learning_video.py:3591` 的**一个常数**。
> 全部数字用项目自己的字体度量（`article_subtitle_en_font` + `text_w` + `acx`，
> 即真实 PIL RobotoSlab-SemiBold 步进宽度），未修改本仓库任何既有文件。

### 12.1 测量面与保真度

数据源：22 个产物集的 `display-page-translations.json` 的 `render_plans`
（**这是冻结的生产分页结果本身**，不是我复算的）+ 同目录 `word-ledger.json` 的逐词时间戳。
**4,656 条父字幕 / 5,352 个显示页。**

**测量面披露**：这 22 个产物集只覆盖 **20 个 work-dir** —— `中式梦核`（202+202 父）与
`无论怎么衡量，就业市场都很疲软`（260+260 父）各有 `【字幕】` 与 `【样式字幕】` 两份产物，
即 **462/4,656 = 9.9% 的测量面是这 2 集的重复计数**，它们被双倍加权（比例结论基本不受影响，
但 §12.3 的 `hard_examples` 里 S0062/S0064/S0218 各出现两次就是这个原因）。

保真度检查：把词账本 `surface` 用空格拼接后与 `render_plans[i].english` 逐条比对 ——
**4,656 / 4,656 完全相同，0 条不一致**。所以本节的分词与词-时间对齐是精确的，
不像 §9 那样带哈钦误差。

先记录一组描述性事实（直接读冻结产物，无推断）：

| 事实 | 数值 |
|---|---|
| 每父页数分布 | 1 页 **4,024（86.4%）**、2 页 575、3 页 50、4 页 7 |
| 每页行数分布 | 1 行 1,950（36.4%）、**2 行 3,343（62.5%）**、3 行 44、0 行 15 |
| 实际用到的宽度档 | 1260 → 82.1%、1455 → 13.4%、1498 → 4.5% |
| 父级选用字号 | 56 → 4,369、54 → 69、52 → 113、50 → 105；触发回退 272（5.8%） |
| 单行渲染宽度（渲染 px，上限 1798） | 中位 1,741、p75 2,301、p90 2,821、max 5,571 |

**第一个可用结论：多页机制只服务 13.6% 的父字幕，而双行机制服务 62.5% 的页。**
真正天天在用的是"行内换行"，不是"多页"。

### 12.2 【已核实】单行路径被一个 1100 的常数卡住，而面板宽 1260/1455/1498

`podcast_learning_video.py:3591` 的早退条件用的是
`ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH = 1100`（194 行），
而同文件 `_article_english_layout_width`（3703-3717）挑选面板宽度的阶梯是
**1260 / 1455 / 1498**——1100 **不在**阶梯里，它只是单行早退的门槛。
换句话说：**一段文字明明能在 1455 的面板上一行放下，但因为超过 1100，就被强行拆成两行。**

把 5,352 个生产页的文本按**单行**在 56 号字下量一遍：

| 单行门槛 | 全部页能单行装下 | **现网 3,343 个双行页里能改成单行的** |
|---|---|---|
| **1100（现状）** | 1,621（30.3%） | **17（0.5%）** |
| 1260 | 2,116（39.5%） | 303（9.1%） |
| **1455** | 2,695（50.4%） | **785（23.5%）** |
| 1498 | 2,828（52.8%） | 903（27.0%） |

**把 3591 的门槛从 1100 抬到 1455，有 785 个页（占全部页 14.7%、占双行页 23.5%）
从两行变一行**——**页数不变、切分不变、翻译不变、约束压力不变**，
因为这一层只决定"同一页内怎么折行"。这是本次审计里性价比最高的单点改动。

**代价必须一起说**：行会变长（最长可到 1746 渲染 px），
一行扫视距离变大；这是可读性取舍，不是免费收益。
建议先只抬到 1260（+303 页）观察，再决定是否到 1455。
另外此表按 56 号字统一测量，对那 272 个用了更小字号的父字幕**偏保守**
（字号更小 → 更容易单行装下），所以真实收益不低于上表。

### 12.3 【已实测】改成"只用单行页"在联合约束下会破功

问题必须连着三条约束一起问，单看页数会得出错误结论。
用可行性 DP 逐父穷举分页方案，要求每页同时满足：
**① 在 56 号字下单行装进给定宽度 ② ≥ `ARTICLE_VISUAL_PAGE_MIN_WORDS`(4) 词
③ ≥ `ARTICLE_PAGE_MIN_DURATION_MS`(900ms) ④ 总页数 ≤ `ARTICLE_VISUAL_PAGE_MAX_PAGES`(4)**。

先剔除"本身就够不到地板"的父字幕：整条不足 4 词或不足 900ms 的有
**457 条（占 4,656 的 9.8%）**——这些无论怎么排版都违约，不该记在单行头上。
剩余 **4,199 条**为计算面。

| 单行门槛 | **可行（≤4 页且全页合规）** | 需要 >4 页 | **完全无可行方案** |
|---|---|---|---|
| 1100（现状门槛） | 3,613（86.04%） | 95 | 491 |
| 1260 | 3,990（95.02%） | 45 | 164 |
| 1455 | 4,145（98.71%） | 20 | 34 |
| 1498 | 4,162（99.12%） | 15 | 22 |
| **对照：现行双行页（任一宽度）** | **4,199（100.00%）** | **0** | **0** |

**双行设计在四档宽度下全部 100% 可行；单行设计即使用最宽的 1498 也有 37 条（0.88%）做不到。**

**卡点不是页数上限。** 只有 15-20 条父字幕需要超过 4 页 ——
这条**推翻了我先前的口头担忧**（我说过单行"可能需要放宽 `ARTICLE_VISUAL_PAGE_MAX_PAGES`"，
实测不需要）。真正的卡点是 **≥4 词与 ≥900ms 这两条地板**：
单行页装的词少 → 页变多 → 每页停留时间变短 → 撞 900ms 地板。
无可行方案的样本正是这个形状：

```
S0190  11词 5664ms  →  无解
  The overarching policy stance still heavily emphasizes high-quality employment and self-reliance.
    （词都长，11 词无论 4+7 / 5+6 / 6+5 / 7+4 都有一半超宽）
S0102   8词 3242ms  →  无解
  Right. But when you're constrained, every single parameter,
    （只能 4+4，但前 4 词语速太快，不足 900ms）
S0215  39词 13168ms →  需 5 页
```

### 12.4 结论：抬门槛，不要换成单行分页

| 方案 | 收益 | 代价 | 判断 |
|---|---|---|---|
| **抬高 3591 的单行门槛（1100 → 1260 或 1455）** | 303 / 785 个双行页变单行 | 行更长；无结构风险 | **推荐，先到 1260** |
| 改成只用单行页 | 版面最干净 | 4,199 条里 37-586 条无解（取决于宽度）；页数翻约 1.6 倍（1260 档 8,780/5,352 = 1.64×；1455 档 1.48×；1100 档 1.83×）；需重做页级中文分配 | **不推荐** |
| 保持现状 | — | 双行页停在 62.5% | — |

单行的干净版面，**八成可以靠抬门槛拿到，而不必承担换布局的可行性风险**。

### 12.5 【新发现】三条声明约束在冻结产物里的实际成立情况

顺手把 `layout_profile` 声明的约束与产物实际内容逐版本对齐，
这是 §2"缺不变量测试"在**分页层**的同类证据。按 `planner_version` 分组：

| planner | 页数 | `>2 行` | `0 行` | `<900ms` | `<4 词` |
|---|---|---|---|---|---|
| v18 | 306 | 8 | 0 | 15 | 24 |
| v19 | 1,755 | 23 | 0 | 59 | 95 |
| v23 | 409 | 6 | 0 | 19 | 26 |
| v24 | 251 | 2 | 0 | 17 | 24 |
| v26 | 485 | 5 | 0 | 19 | 33 |
| v27 | 492 | **0** | 0 | 20 | 43 |
| v28 | 574 | **0** | **8** | 22 | 40 |
| v29 | 813 | **0** | **4** | 47 | 70 |
| **v32（最新）** | **267** | **0** | **3** | **16** | **27** |

三种不同性质，请分开处理：

1. **`>2 行` 已经修好了。** v18-v26 每集都有几条，**v27 起为 0**。
   `layout_profile.max_lines = 2` 现在成立。**不要再把它当待修缺陷**
   （我如果只看全量 44 条就会误报，这是分版本看才拿到的结论）。
2. **`0 行` 是 v28 引入的新回归，且 v32 仍在。** v18-v27 全为 0，
   v28=8、v29=4、v32=3，共 15 页 `english_lines == []`。
   页有 `english` 文本但 `english_lines` 是空数组 → **建议优先查这条**，
   它是三条里唯一"越新越有、且此前没有"的。
3. **`<900ms`(4.4%) 与 `<4 词`(7.1%) 每个版本都有，v32 也有（6.0% / 10.1%）。**
   但**这两条不宜直接判为 bug**：§12.3 测出有 457 条父字幕（9.8%）
   整条就不足 4 词或 900ms，地板对它们物理上不可达。
   **这不是分页层的错，是切分层交下来的东西已经低于地板**——
   正是 §5"切分层对分页可行性完全盲"的直接后果。
   真正该做的是让切分层知道这两条地板，而不是在分页层放宽它们。

### 12.6 本节的证据分级与未测项

**【已实测】** 12.1 全部描述性数字（读冻结产物）；12.2 的四档命中数；
12.3 的 DP 可行率与对照；12.5 的逐版本计数。
保真度 4,656/4,656 精确匹配，本节不含 §9 那类哈钦误差。

**【已推翻】** 我先前说单行分页"可能需要放宽 `ARTICLE_VISUAL_PAGE_MAX_PAGES`"——
实测只有 15-20 条父字幕需要 >4 页，页数上限不是卡点；卡点是 ≥4 词与 ≥900ms。

**【方向性偏差，必须知道】**

- 12.3 的**双行对照偏乐观**：我只建模了"页内贪心折行 ≤2 行"，
  **没有**建模项目实际的每行 ≥3 词、行间平衡、`ARTICLE_AVOID_LINE_START_WORDS`（264 行起）
  等规则。所以"100% 可行"是双行可行性的**上界**。
  不过冻结产物本身最多只用到 4 页、无一超限，与该上界一致。
- 12.3 的**单行可行率也偏乐观**：DP 只管宽度/词数/时长，
  **不管断点是否语法合法**（即 §11 那一整套 HARD 判定）。接上合法性后只会更低，
  所以"单行不推荐"这个方向的结论是**保守安全**的。
- 12.2 按 56 号字统一测量，对 272 个用了更小字号的父字幕偏保守，收益是下界。

**【未测】**

- 抬高 3591 门槛后，**页级中文分配**是否还能对齐（`display-page-translation-v9` 合同）。
  英文行数变化不改页边界，理论上不影响分配，但**未验证**。
- 那 15 条 `0 行` 页的成因（v28 的哪次改动引入）—— 未查。
- 单行页方案下的页级中文重分配成本 —— 未测。
- 把 §11 的边界合法性接入本节 DP 的联合可行率 —— 未测，这才是 GPT 第 4 步的完整形态。

**测量脚本**：`measure_single_line_pages.py`（描述性 + 门槛命中）、
`measure_single_line_feasibility_dp.py`（联合约束可行性 DP），
产物 `single_line_pagination_feasibility.json`、`single_line_feasibility_dp.json`，
已归档到 `docs/audits/2026-08-24/external-claude-measurement/`。
