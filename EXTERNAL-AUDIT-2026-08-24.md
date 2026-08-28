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
> **⚠ 2026-08-24 第四轮追加：§13（针对你已落地的实现，有实测）**
> 你报的"8 个回归"方向判断正确，但根因不在判据、在接线：
> **arm F 被接到了共享 helper `_fragment_has_finite_predicate` 上（6595-6600）**，
> 于是"修 helper"和"上 arm F"成了同一次编辑，二者的影响在代码上无法分离。
> 该 helper 的返回值有 **35.9%（1,837/5,123）会翻转**，而它有 11 个消费点，
> 显示层五条 `visual_*` 全部门控在 `not has_finite_predicate` 上 ——
> 测试成批失败是算术必然。**处置见 §13.2：给 arm F 一个私有判据，本轮别动共享 helper。**
> 另有一条**阻塞项**：`@classmethod` 改成实例方法后，三个基线脚本的 `.__func__`
> 解包会抛 `AttributeError`，当前工作树上跑不出回归基线（§13.4.1）。
>
> **⚠ 2026-08-24 第五轮追加：§15（S2 门禁）+ §16（脚本可独立运行 / 预期收益分层）**
> 你的拆分方向正确，且恢复 `@classmethod` 比我的建议更好（我的基线脚本因此免改即可跑）。
> 但 **`measure_stage2.py` 在你当前工作树上返回 5,180 / 516 / `open_sub` 110 ——
> 与改动前基线逐位相同，收益为 0**：该 code 有**两处发射源**，你只豁免了一处
> （6292 用新判据 ✓，6440 经 `_evaluate_final_display_fragment` 仍读原判据 ✗）。
> 把 arm F 接到两处即复现 **452 / 37**，与 §11 预测精确一致 → 规则是对的，接线只做了一半。
> 因第二处宿主函数有 11 个调用者（含 3 个显示层），**处置用 §15.4 的方案 B**：
> 在 6241 与 6246 之间的**单一边界消费点**后置过滤该 code，`_evaluate_final_display_fragment` 一行不改。
> **S2 放行条件：452 / 37，且新增合法候选切点 ≤ 69，且显示层测试未改而全绿。**
>
> §16 两件事，请在动手前读：**(1)** 那 10 个测量脚本现在路径无关，
> Windows 上 `python docs\audits\...\measure_stage2.py` 直接可跑，你能自查（§16.1）；
> **(2) 不要把 516 → 452 当成效果指标**——它衡量的是规则自相矛盾，不是切得更好；
> 代价函数从未被测量，2,122 个"合法但未被选中"的切点就是证据（§16.3）。
> 另有一条实测到的落地成本：**重跑会触发中文重翻，人工校过的段落会回到未校状态（§16.4）。**
>
> **⚠ 2026-08-24 第六轮追加：§17（对你"本轮已完成"那条报告的复核，有实测）**
> 在你 08:49 那棵树（+61/−1）上重跑：**规则和实现都对，但生产收益仍然是 0。**
> `measure_stage2.py` 输出 **5180 / 516 / open_sub=110**，与改动前基线一字未变（§17.2）。
> 原因是同一个 code 有**两个发射源**，你只豁免了 6291 那个，**6440 那个还在报**，
> 两者在 6246 合并 → 结果照旧非法。**缺的只是一处接线，代码见 §17.3。**
> 好消息有两条：**(1)** 你的实现与审计规格**语义等价已被证明**——两套独立实现在两个
> 测量面上给出同一组数（452/37 与 newly_legal=69 / newly_illegal=0，§17.4）；
> **(2)** §13.4 那三处硬伤现在都不影响 arm F 了（§17.5），其中"恢复 classmethod"
> 比审计者原先的建议更好，已采纳你的判断。
> 另发现一条非阻塞项：spaCy 回退路径让切分结果与环境相关，但**失败朝保守侧倒**，
> 建议把模型可用性写进证据文件以免静默漂移（§17.6）。
> **S2 放行条件（已预登记，你可自验）：452 / 5180，open_sub=37，且 newly_illegal 仍为 0。**
>
> **⚠ 2026-08-24 第七轮追加：§19（优先级被推翻，请务必读；有实测）**
> **补完 S2 之后不要按 §18.3/18.4 走。** 实测发现真正的瓶颈不在切分质量，
> 而在**审校清单根本不工作**：`qa-review-points.json` 在 47 个产物集上
> **中位数 0 条、最大 2 条**，因为 `_editor_review_points`（12746-12814）
> **只遍历 `_last_allocation_unresolved`**（中文分配失败），
> 结构上不消费边界合法性、父字幕长度、分页结果、时长/词数地板、字号回退、行数异常。
> 用户列出的三类担忧（长句切坏害翻译 / 分页差 / 短字幕）**没有一类被覆盖** ——
> 所以他必须逐条看 230 条字幕，这不是习惯问题，是清单没在替他筛。
> **用户目标"自动化 90-95%"是审校覆盖率指标，不是切分质量指标**：
> 就算把 516 刷到 0，他仍然要逐条看。
> **新 #1 = 一份只读审校清单（recall 优先）**，所需信号全部已冻结在产物里且本报告已量化
> （§19.3 的表），零生产改动、零重跑、不触发中文重翻。
> **项目终止条件见 §19.5：在一集上测出"我改了但清单没标"的召回缺口。
> 那个数出来之前，任何进一步的切分/分页工程都是在无目标函数的空间里搜索。**
>
> **⚠ 2026-08-24 第八轮追加：§20 无人值守工单 —— 用户已离开，这是你现在的执行依据**
> **请直接跳到 §20 并按 A→B→C→D→E→F 顺序执行。** 你自己提的四步计划结构正确，
> 但有三处会出事，§20 已修正：**(1)** "固定成基线"必须在接线补完**之后**做，
> 否则会把 516 焊成基线、收益永久丢失；**(2)** 1260px 的取舍**你不得自行决定**，
> 它是可读性权衡，且候选值有 1260 和 1455 两个，必须都出对照图交用户挑；
> **(3)** 真实音频回归**不得对已人工校对的产物集重跑**，否则用户的中文校对成果被冲掉。
> 另外你的计划整体仍在"让规则自洽"这条线上，缺了 §19 认定的真瓶颈（审校清单不工作），
> 已补为 §20 的 C 项，**它是本工单最高价值项**。
> **每一步的验收数字都在你动手之前写好，你可自验但不得修改目标值；
> 对不上就停下写明原因，不要改断言迁就实现。**
> 用户回来只看 `执行进展-给用户.md`，需要他决定的事集中列在该文件末尾。
>
> **🛑 2026-08-24 第九轮自我纠错：§21 推翻了 §19 和 §20-C，先读 §21 再动手。**
> 产品里**已经有**真正的审校清单 `editor-review-ledger.json`
> （`subtitle_review_marks.py:32`），标出率 12–27%，已落在预登记门禁内；
> 我此前测的 `qa-review-points.json` 是死路径，`§19` 关于"结构性不覆盖"的结论**作废**。
> **C 不要重写清单**，改成 §21.3 的 C1：用 6 份 `人工终稿字幕-edits.json`
> （用户真实修改记录，且产生于 ledger 存在之前 → 无偏 ground truth）
> 离线算出清单的**漏标条数与漏标 ID 列表**。这可能让用户零投入拿到终止条件那个数。

> **🛑🛑 2026-08-24 第十轮：§26 是当前最高优先级，先读 §26 再读任何其他章节。**
> 用户点名了他真正认真校对并合成视频的四集，**§25 用的样本不在其中**。
> 在其中一集（就业市场，P=237，清单先写于 14:53、用户 15:09 才开始改 → 前瞻性预测）实测：
> **清单标出率 9.3%、召回率 39%**。**§25 的两条处方被推翻**
> （「父总词数≤5」提升 0.00×，「每页≥13词」召回 47% 而非 69%）。
> 更关键：**用户 101 步操作里 60% 是逐页改中文，而清单对中文改动的召回只有 11%**（版式是 29%）——
> **你正在做的 A/B/D/E/F 全在版式与边界层，不覆盖用户六成的操作。**
> 新增最高优先级项 **G**（查中文检测器为何只召回 11%），见 §26.10。
> 并且：**「自动化 90-95%、只动 5-10%」用现有冻结信号达不到**，天花板约「读一半、漏一到两成」，
> 这句必须原样传达，不许软化。

> **🛑🛑 2026-08-24 第十一轮：§27 是最新结论，覆盖 §26 的两个数字，先读 §27。**
> 另两集的人工终稿包在 **`D:\经济学人\2026-08-15\其他媒体`**（不在 E:\work-dir 下，
> §26.2「草稿已清除」是错的）。三集跨集验证已完成：
> **中文主导复现（中文操作步数占比 60% / 74% / 65%），这是已证实的事实**；
> **用户改动率 11.8% / 29.9% / 17.3%，合并 19.3%** —— 离「只动 5-10%」差 2 到 6 倍。
> **`父总词数≤5` 三集全灭（0.00× / 0.15× / 0.00×），彻底作废；`每页≥13词` 逐集衰减，不得单独接线。**
> 天花板更正：**读 45.7% / 召回 77%（三集合并）**，不是 §26 的 48%/86%；
> 要 90% 召回需读 60–65%。**接线基线随之改为 77%，且必须三集分别达标。**
> 清单召回率 39% 仍只有就业集一个样本（另两集编辑于 ledger 机制上线前）。

> **🛑🛑🛑 2026-08-24 第十二轮：从现在起唯一的执行依据是 §28，先读 §28，再回头看 §27/§26 取事实。**
> 用户已离开且短期不会复核，明确要求「直接给一个完整的往 90-95 做的方案」。
> §20 的 A–F **作废为已完成的清理项，不再是路线**。
> §28 把目标拆成三个必须同时达标的数：**改动率 E ≤10%（现 19.3%）、
> 清单召回 Rec ≥95%（现 39%）、读取率 R ≤50%（现 ~100%）**，
> 并给出 **P0→P5 六步、每步预登记门禁**的顺序执行工单。
> **P0（把目标函数做成能跑的脚本，复现 §28.1 表格全部数字）未通过前不许碰 P1。**
> 降 E 只能靠生成质量、降 R 只能靠清单变准，两条线并行，缺一条到不了目标（§28.0）。
> **Rec ≥95% 用现存冻结信号做不到**——这是实测结论，P3 是唯一升级路径；
> 若 P3 也不达标，§28.7 要求你如实报天花板，**不许调低门禁**。

> **🛑🛑🛑 2026-08-24 第十三轮：§29 找到了中文层的根因，**执行顺序改为 §29.5**，先读 §29。**
> 逐页中文由 `podcast_learning_video.py:3443 _strict_split_chinese_visual_pages()` 产生，
> 它**只按"每页英文词数占比"折算中文字符位置**（`3471`），**从不看每页的英文文本**。
> 英文虚词/口语填充占词数不占中文字数 → 切点系统性偏右 → 内容落到错误的页。
> 实测：该函数只能复现用户最终切法的 **39%（32%/30%/59%）**，用户改过中文的父上只有 **32%**；
> 失败模式高度一致 —— **用户切在标点/小句边界，函数越过标点去贴近比例目标**。
> 用户的中文修改里 **36% 是"一个字没改、只是挪到别页"的机械搬运**，
> 且 **46%/73%/71% 的中文修改发生在他改过分页边界的父上（是分页改动的下游后果）**。
> → **§28 的 P2「先出 285 条分类表再写离线检测器」降级**，主线改为
> P1' 修切分策略（纯确定性、无模型、有 100 例监督基准）→ P2' 边界改动后自动重切中文 →
> 剩下的才交给模型检查。**另：覆盖率信号与中英占比偏差信号已被我测死（§29.4），别再试** ——
> 结构性原因是逐页中文本身就是按长度比例切的，长度类统计量与它自洽，看不见自己的错。

> **🛑 2026-08-24 第十四轮：§30 量了中文改动的「体量」，据此下调 P3' 与宽度常数的优先级。**
> **页数几乎不变**（就业 223/236、中式梦核 181/201、烂到爆红 158/172）→ 用户改的是**切点位置**，
> 不是页数；面板宽度常数（1100/1260/1455）最多影响 3–8% 的父，**降为低优先级**。
> **字符改动 80% 落在 ≤8 字的小块里**，每集真需重写整句的父只有 **2–4 个（全集 1–2%）**。
> **术语表红利不存在**（重复替换对：0 组 / 6 组 20 次 / 1 组 2 次，最大的一组只是"梦境核→梦核"）。
> → **P3' 的门禁改为只对「大改写型」父算召回（三集共 8 例，要求 ≥6/8，读取率 ≤20%），**
> **不许把 ≤8 字润色算进分母，也不许因抓不到润色就说 P3' 失败。**
> 若 P1'+P2' 做完后残余就是这批润色，那是**诚实地板**，按 §28.7 汇报，别再加模型环节。

> **🛑🛑 2026-08-24 第十五轮：§31 把用户自述的排版政策量化了，并推翻了「改动率＝缺陷率」这个隐含前提。**
> **(1) 容量线可编码**：他加页的触发点是「最长页中文 26-27 字 / 英文 92-102 字符」（下限 85 字符），
> 终稿每页中文中位 14、p90 21-23、极限 31；自动输出目前放到 33-38 字 / 115-126 字符，**比他的口味松 10-20%**。
> **(2)「在逗号处拆」他自己只做到 54-62%**（亲手改过的父里 38-46% 的断点不在中文标点）→
> **不许把「必须切在标点」写成硬规则或门禁**；可用的第二门禁是英文页尾带标点率 33-44% → **≥50%**。
> **(3) 他确实会漏**：他没动过的父里，按他自己的判据仍有 **3.0% / 4.0% / 2.3%（严格档 7/8/4 条）**
> 违规，多是**单页长到一屏发紧却根本没被拆过**。名单见
> `docs/audits/2026-08-24/external-claude-measurement/疑似漏改清单-三集.md`。
> → **改动率 E=19.3% 是缺陷率的下界，不是缺陷率**；今后必须同时报「他改的」与「他没改但违规的」两个数。
> → §30.1 把宽度/页数降为低优先级的推理有洞（我量的是他改页数的频率，不是页数判错的频率），
> **页数决策恢复为中等优先级**，做法改为按 31.1 的容量线加一道判定（不需要用户做审美选择）。
> **新增 P2.5'，工单净修改见 §31.5。**

> **🛑🛑🛑 2026-08-24 第十六轮：§32＝复核 GPT 的 P1' 结果。这是当前对 P1' 的最终裁定。**
> GPT 的基线与我 §29.3 逐位一致（8/25、14/46、17/29＝39/100），执行与判断都没问题。**问题在我：**
> **我预登记的门禁（合计≥70%、三集分别≥60%）在「以中文标点为落点」这一类规则下不可能达到** ——
> 我算出该类规则的天花板是 **61/100**（用户切点紧跟标点仅 58%/59%/72%；每集 60%/52%/76%），
> 梦核一集天花板 52% 本身就低于我写的 60%。**这是我第六次犯「没先算可行性就下结论」的错。**
> **裁定：`window_8_punctuation_first` 应当接线** —— 逐 `hit_ids` 比对为 **新对 24 例 / 弄坏 1 例**
> （弄坏的梦核 S0061 本就属于「切点不在标点」的天花板之外），且已达天花板的 102%。
> 判据改为**不可被凑的两条**：帕累托性（新对 >> 弄坏，且逐例说明）＋吃满天花板 ≥95%。
> 接线前只需三项只读检查（全库 62 集纯函数重放、确定性、三处调用点一致），见 §32.4。
> **答 GPT 挂起的问题：不要做第三版启发式** —— 双语硬锚点只覆盖 4/10/4 个案例，
> 连接词规则只覆盖残余的 55% 且精确率必差。残余 42 个切点是**中英词对齐**问题，归 P3'。

> **🛑🛑🛑 2026-08-24 第十七轮：§33＝P1' 已接线，六项检查我替 GPT 做完了。这是当前最新状态。**
> 提交 `b951d75`（15:23）已把标点优先接进 `podcast_learning_video.py:3521-3529`（9 行，窗口仍 ±8）。
> **我独立复跑：生产函数本身读 62/100（14/25、25/46、23/29），与 GPT 的 JSON 逐位一致、`hit_ids` 与
> `window_8_punctuation_first` 完全相同 → 接的是对的东西。** 全库重放（22 集 / 112 份产物 / 2899 个多页父）：
> **新增 `None` = 0、空页 = 0、非确定性 = 0、输出改变 35.9%** → 三项硬门槛全过。
> 旁证：新函数复现冻结产物页面文本 **59% vs 旧 40%**；只看 8 集纯自动产物（n=528）**65% vs 42%**，21/22 集变好。
> **重大发现：标点优先不是新启发式，是修一次静默回归** —— 初版 `fe083a7`（8/4）候选集只含标点，
> `fc6d954`（8/5 为加 jieba 词边界）把标点降成第二排序键，而其注释仍写着 "punctuation remains strongest"。
> **两处必须修**：(a) 改动混在 17 文件的提交里无法单独回退 → 补 `rollback/*.revert.patch` 备案，今后一项一提交；
> (b) `P1-prime-report.md` 与 `执行进展-给用户.md` 仍写着"没过门禁、没改生产默认值"，与代码矛盾，必须改。
> **§32.6 交叉核对结果比担心的更糟**：285 条归因里「语义漏译 85」有 **57 条改前整页中文为空**（工具缺陷，非翻译），
> 「纯风格 75」有 **61 条一个字没改只是挪页** → **118/285（41.4%）是工具造成的**，真·语义漏译上限 28 条。
> **→ P2'（边界改动后自动重切、严禁空页）升为与 P2.5' 并列第一优先；A=91 的上限必须重算。**
> 另：GPT 顺手把"质量审计 PARTIAL 不再阻塞发布"接了（`subtitle_thread.py` +144），不在我的工单里，需用户拍板（§33.9）。

> **🛑🛑🛑 2026-08-24 第十八轮：§34＝新音频（run 20260824T201840，b951d75）端到端只读复核。这是当前最新状态。**
> GPT 报的结构性数字我逐项复算**全部一致**：120 父 / 156 页、多页父 68 个中文页**无一为空**、
> 32/32 个父「逐页中文拼接==整条中文」、质量审计 120/120 PASS。
> **接线在新素材上的第一手证据：36 个切点里 21 个紧跟中文标点 = 58%，与用户本人 58/59/72% 同档。**
> **但两处口径必须改**：(a)「79% 无明显问题」的分母是它自己挑的 43 条高压样本，
> 以全集 120 为分母是 9/120=7.5% → **诚实区间是 79%–92.5%，收敛只能靠用户校对这一集（＝P4）**；
> (b) 本次 `editor-review-ledger` 读 24%（29/120）命中 GPT 名单 8/10（漏 S0077、S0117）
> → **读 24% / 命中 80%，是目前最好取舍**，但 GT 是模型巡检不是用户改动，未确认前不许当召回率报。
> **两个新缺陷（§34.5，已列为下一轮工单）**：
> (a) 该 stable-run 目录混入 **14:57 那次（接线前 `2c108a5`）的 `qa-review-queue/qa-summary/semantic-review-queue`**，
> 而 manifest 写的是 `b951d75` —— **GPT 的 43 条高压样本正好等于这份旧队列的 43 个父**，样本选择用了过期证据；
> (b) **`S0021.P02 = 「，1940年代建成。」`页首是逗号** —— `is_safe` 禁止这种落点，
> 故必来自非严格分支 `candidates = [target]`（3517-3519）**跳过安全检查**；与标点优先无关，但用户会直接看见，优先级高于 P2.5'。

> **🛑🛑🛑 2026-08-25 第二十一轮：§37＝两集实测（测试音频复核 + 日本X世代新集）。这是当前最新状态，优先于 §34–§36 的顺序安排。**
> **先看 §37.1**：日本集 4 次固定运行全失败，`S0001`/`S0242` 两个父（0.8%）触发
> `no_complete_normal_font_page_partition` → **整集 275 页逐页中文一页都没生成**，用户被迫手工做完 83 分钟。
> 根因在 `podcast_learning_video.py:6134-6145`（`incomplete_review_count==0` 过滤把多页候选全丢弃）。
> **工单 S0＝把它降级为带 REVIEW 标记的兜底候选，优先级高于 §36.4 的 S1–S4 全部。**
> 其次 §37.5：`_CAPACITY_REVIEW_CJK_CHARS` **26→22**，两集独立验证（6 标 6/10 → 16 标 8/10），
> 只加标记、无可弄坏项，是成本最低的一项。
> 好消息 §37.2：他没动的父上自动切点 **86.7%** 落在中文标点后（棘轮线 55%），中文分页层这集是好的。
> 三大指标 §37.3–37.4：**E 12.5% / R 14.1% / Rec 51.6%**，但**这集是用户赶时间过的，E 是下界、
> 不许和测试音频的 20.0% 连成趋势**。15 个漏标里 **9 个是纯中文措辞（3.6%）＝地板，也是 S2 的靶子**。
> 新口径规则：history 里的 `confirm_display_page_boundary` **是读不是改，不计入 E**。
> 测试音频 23:00 那个包＝22:15 的原样重导（cues 完全一致），**无新数据点**，「中国商品商品」仍在。


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

---

## 13. 第四轮：对 GPT 已落地实现的只读复核（2026-08-24 追加）

> 触发：GPT 报告"有限谓语改动的第一轮聚焦测试暴露 8 个回归",并判断
> "不能把 spaCy 结果无条件替换到所有显示层判定"。
> **它这个判断是对的**,本节给出让它不必逐条猜的量化依据,以及一条它没点出的机械原因。
> 我仍未修改任何既有文件；本节全部结论读自 `git diff` 与新增测试。

### 13.1 8 个回归的量级解释：那个值有 35.9% 会翻转

在本仓库 5,123 条去重父字幕上实测 GPT 的新实现（词表快路 → spaCy 兜底）：

| 项 | 条数 | 占比 |
|---|---|---|
| **词表漏判、被 spaCy 兜住 → `has_finite_predicate` 由 False 翻 True** | **1,837** | **35.9%** |
| 词表短路成 True 但 spaCy 说 False（假阳性，spaCy 无机会纠正） | 18 | 0.4% |
| 全小写送入 spaCy 导致结论翻转 | 49 | 1.0% |

（1,837 与 §3 独立测得的 1,827 相互印证。）

**`has_finite_predicate` 有 35.9% 的样本改变取值,而它有 11 个消费点**
（4904、5952→5964/5966/5980、6319/6320、6367、6384/6431/6446、6467、6597、6655、6809、14519）。
显示层五条 `visual_*` 判定全部门控在 `not has_finite_predicate` 上 ——
该值翻 True 后这些判定**发火变少**,即显示层整体**变宽松**。
所以"断言某处是碎片"的测试成批失败是**必然的算术结果**,不是实现写错。
**GPT 的方向判断成立：作用面必须收窄。**

### 13.2 【机械原因，GPT 未点出】arm F 被接在了共享 helper 上

`screen_editor.py:6595-6600`（改后）：

```python
if (
    normalized.rstrip().endswith(",")
    and self._fragment_has_finite_predicate(self._word_tokens(normalized))
):
    return False
```

arm F 的豁免走的是**那个共享 helper**,于是"修 helper"与"上 arm F"变成同一次编辑,
**这正是它无法区分"哪些是 arm F 预期变化、哪些是显示层误判"的原因** —— 二者在代码上不可分。

**§11.6 的落地形态本意是给 arm F 一个自己的私有判据,不是复用共享 helper。**
建议：arm F 内联一个独立的有限动词测试（同样的 spaCy 条件、同样缓存），
`_fragment_has_finite_predicate` 本轮**完全不动**。这样：

- arm F 的 PR 里显示层零变化 → 那 8 个回归**直接消失**,可用 §11.6 的两条断言单独验；
- 修词表另开一个 PR,其 35.9% 的爆炸半径可以逐个消费点分别评估。

两者效果本来就是可加的（§11.2：32 + 76 ≈ 111）,分开落地不损失收益。

### 13.3 "正确的作用面"不必靠判断，我只测过一处

§3.3 的反事实（516 → 484、新增非法 0）虽然是全局 monkeypatch,
但**只测了 `_evaluate_item_pair_for_final_boundary` 这一条路径的边界合法性**。
→ **有实测背书的安全作用面 = 边界评估路径；显示层五条 `visual_*` 与 6467
`has_independent_meaning` 的实测背书为零**（§3 末尾"显示层未测"即指此处）。
结论：先把 spaCy 兜底限制在边界路径,显示层继续用旧词表,直到有人测过为止。

### 13.4 三处具体缺陷（按重要性）

1. **【阻塞】`@classmethod` 改成实例方法,打断了回归基线脚本。**
   `measure_finite_counterfactual.py:34`、`measure_open_subordinate.py:61`、
   `measure_open_subordinate_v2.py:67` 都用 `E._fragment_has_finite_predicate.__func__`
   解包 classmethod,普通函数没有 `__func__` → `AttributeError`。
   **当前工作树上跑不出基线。** 改 `getattr(f, "__func__", f)` 即可,或在干净检出上跑基线。
2. **`be`/`been`/`being` 在 `finite_or_aux` 里是错的**,且**在 spaCy 之前短路**,
   于是永远得不到纠正。这三个是非有限形式。实测 18 条（0.4%）受此影响,
   14 条只因这三个词而误判：`being built in America right now?`、
   `only to be forced to use it for DoorDash,`、`So let me be perfectly clear right up front.`
   → 从快路名单里移除这三个,交给 spaCy 判。量小但方向明确是错的。
3. **送入 spaCy 的是 `.casefold()` 后的文本**（`cache_key` 即小写串）。
   `en_core_web_sm` 在有大小写文本上训练,全小写会掉准,受影响 49 条（1.0%）,
   集中在祈使句（`Set the parameters carefully` 有大小写判 False、全小写判 True）。
   → 缓存键可以用小写,但**送进 `nlp()` 的应是原始大小写文本**。§3 的测量用的是原文。

### 13.5 对"不改测试来掩盖行为变化"这条原则的一点补充

这个原则**大体正确,请保持**。但有一个例外必须留出口：**测试本身可能编码了 bug**。
§3 实测：旧词表在真含有限动词的字幕上**漏判 42%**,反方向只错 14 条 —— 纯单向过严。
任何断言 `It's really about…` / `They're optimizing…` 无有限谓语的测试,
断言的是**关于英语的错误事实**,不是关于本项目的约定。

判定规则：**看那条 cue 的原文,问"这里有没有一个在做时态/人称变化的动词"**,
让英语裁决,不让测试裁决。若测试错,改测试并在注释里写清为什么错、依据哪条实测。
若 cue 确实无有限动词而 spaCy 说有,那是 spaCy 误判 → 走 13.3 的收窄作用面,别放宽判据。

**新增的三个测试（`..._falls_back_to_spacy_and_caches_by_token_text`、
`..._spacy_unavailable_keeps_legacy_conservative_result`、
`..._allows_finite_comma_clause_only`）写法是合规的**,缓存命中、
spaCy 缺失降级、arm F 只在"逗号 + 有限谓语"时豁免三条都覆盖到了,建议保留。

### 13.6 本节未测

- 11 个消费点**各自**因 35.9% 翻转而改变多少判定 —— 未测。
  这是让 GPT 从数据而非逐条猜测中选定作用面所缺的最后一块,可以补。
- arm F 改用私有判据后,§11.6 那两条断言的实际数值 —— 未测（需先修 13.4.1 的阻塞）。

---

## 14. 执行计划（2026-08-24，双方共用；含分工与放行条件）

> 本节是给**两个执行者**看的：`[GPT]` 与 `[审计者]`。
> 每步都写了**放行条件**——不满足就不许进下一步，也不许合并。
> 排序原则：**先恢复量具，再拆耦合，最后才碰作用面。**顺序错了后面全是猜。

### 14.0 先承认一件事：谁更缜密，取决于谁在交付

`[审计者]` 本轮抓到 `[GPT]` 四处问题（arm F 耦合、`be/been/being`、casefold、基线被打断），
但**这不证明审计者更缜密**，只证明**没有交付压力的第二读者天然能看见作者看不见的东西**。
反向也成立：`[GPT]` 的实现里，缓存写法、spaCy 降级、三个新测试都合规，
而审计者本轮自己犯的错有：违反自己写进记忆的禁令去 grep `runtime/`（超时）、
样本桶命名张冠李戴（`F_still_blocked` 实为 E）、
差点用推导代替实测（arm F 的 69）、§12 测量面 9.9% 重复计数未察（靠 subagent 逮到）、
以及写给 GPT 的"其余先别动"一句**差点让对方停掉正确的活**。

→ **结论不是"谁更强"，而是"任何一方都不得自证"。** 本计划因此把交叉复核写成硬性放行条件。

### 14.1 步骤表

| # | 归属 | 动作 | 放行条件（不满足则停） |
|---|---|---|---|
| **S0** | `[GPT]` | **恢复量具**（阻塞全局）。把 `measure_finite_counterfactual.py:34`、`measure_open_subordinate.py:61`、`measure_open_subordinate_v2.py:67` 的 `.__func__` 改成 `getattr(f, "__func__", f)` | 在**当前工作树**上跑出基线并复现 **5,180 条边界 / 516 条非法（9.96%）**。数字对不上就先查装置，不要往下走 |
| **S1** | `[审计者]` | 测 `has_finite_predicate` 那 35.9% 翻转在**11 个消费点各自**造成多少判定变化 | 产出逐消费点的翻转计数表，并标出哪些消费点**零变化**（那些是免费安全区） |
| **S2** | `[GPT]` | **拆耦合**：arm F 改用私有有限动词判据（同条件、同缓存），`_fragment_has_finite_predicate` **本轮完全不动** | ①**显示层测试全绿且一行测试都没改**；② 新增非法 = 0；③ **新增合法候选切点 ≤ 69**。③ 比 ① 重要 |
| **S3** | `[GPT]` | 共享 helper 的三处硬伤：`be`/`been`/`being` 移出快路；送 `nlp()` 的用**原始大小写**（缓存键仍可小写）；快路顺序不变 | 复跑 §13.1 那张表：假阳性 **18 → 0**、casefold 翻转 **49 → 0**、正收益 **1,837 不降** |
| **S4** | `[GPT]`，**依赖 S1** | 按 S1 的数据把 spaCy 兜底**收窄到有实测背书的作用面**（边界评估路径），显示层继续走旧词表 | ① 516 → 484、新增非法 0；② 显示层测试全绿**且未改测试**；③ 收窄边界在注释里写明依据 S1 的哪一行 |
| **S5** | `[GPT]`，**无依赖，可并行先做** | 分页单常数：`podcast_learning_video.py:3591` 的门槛 1100 → 1260 | ① 页数、页边界、`word_start/word_end` **逐页不变**；② 页级中文分配（`display-page-translation-v9` 合同）仍对齐；③ 抽 10 页人眼看行长可接受。满足后再议 1455 |
| **S6** | `[GPT]`，无依赖 | 查 15 页 `english_lines == []`（v28 引入、v32 仍在） | 定位到引入它的那次改动；修完 v28/v29/v32 三组产物复算为 0 |
| **S7** | 暂不动 | 457 条父字幕（9.8%）整条低于 ≥4 词 / ≥900ms 地板；2,122 个"合法但未被选中"的切点背后的代价函数 | **这才是真瓶颈**，属设计问题不是补丁问题。S0–S6 全绿后单开一轮 |

### 14.2 两条贯穿全程的硬规则

1. **谁写的谁不许判定通过。** 每个 PR 合并前由另一方读 diff。
   `[GPT]` 的 diff 由 `[审计者]` 在只读模式复核；`[审计者]` 的测量结论由 `[GPT]`
   或独立 subagent 对账（本报告 §11/§12 已按此办过一次，逮出 8 处标注错误）。
2. **改测试必须附理由，但"不改测试"不是原则性禁令。** 判定归英语，不归测试：
   看 cue 原文问"有没有一个在做时态/人称变化的动词"。测试若编码了旧 bug，
   改它并在注释里写清依据（§13.5）。**唯一禁止的是为了让红变绿而改**。

### 14.3 排序的理由（别自作聪明调顺序）

- **S0 必须最先。** 没有"改之前是什么样"的对照，8 个红点只能靠猜归因，
  这正是 `[GPT]` 当前卡住的位置。恢复量具 10 分钟，省下来的是几小时。
- **S2 必须在 S4 之前。** 两件事焊在一起时，任何一方的效果都无法归因（§13.2）。
  拆开后 S2 的显示层变化为零，8 个回归自然消失——**不是被掩盖，是本来就不该发生**。
- **S1 必须在 S4 之前。** 否则"正确作用面"是判断，不是数据。有了逐消费点的表，
  收窄到哪一行是**读出来的**。
- **S5/S6 可以插到最前面。** 它们与上面完全无依赖，而 S5 是本次审计里唯一
  "肉眼可见、零结构风险"的收益（每集约 14 页从两行变一行）。
  想先要一个能看见的进展就先做 S5。

---

## 15. S2 放行复核：拆分结构正确，但作用面窄了一个发射源（2026-08-24 实测）

> 这是 §14 里 S2 的放行判定。**结论：不放行**，但差的只有一处，且改法已实测出来。
> 全部数字在 `[GPT]` 当前工作树上跑出，审计者仍未修改任何既有文件。

### 15.1 先记两件做对的事

1. **恢复 `@classmethod` 是比我的建议更好的选择。** §13.4.1 我提的是改我那三个脚本，
   `[GPT]` 选择恢复方法绑定类型，于是**基线脚本原样可跑**，量具立刻恢复。这个判断优于我的。
2. **拆耦合的结构是对的。** 新增 `_is_open_subordinate_prefix_for_structural_boundary`
   （6594-6606）+ 私有 `_structural_fragment_has_finite_predicate`（6608-），
   共享 helper 恢复 classmethod 与旧词表语义、spaCy 尾巴移除 →
   **显示层五条 `visual_*` 与 6467 完全不再受影响**，§13.1 那 35.9% 的爆炸半径被隔离掉了。
   新判据还顺手避开了 §13.4.3 的 casefold 问题（送 `nlp()` 的是 `str(word).strip()`，未小写）。

### 15.2 【实测】但 arm F 目前零收益：516 未降，`open_sub` 仍是 110

在当前工作树上跑 `measure_stage2.py`：

| 版本 | 非法 / 5,180 | `open_sub` 命中 |
|---|---|---|
| §11 实测基线（改动前） | 516 | 110 |
| **当前工作树（arm F 只在 6292 一处）** | **516** | **110** |
| 把 arm F 提到 `_is_open_subordinate_prefix`（两个发射源都吃） | **452** | **37** |
| **推荐方案 B（见 15.4）** | **452** | **37** |

**一条都没降。** 原因是 §11.6 里那句"两个发射源（6292 和 6440），两处都要覆盖"
没有落地：

- **6292** 在 `_cross_item_structural_boundary_issues`（6260）→ 已换成 arm F 判据 ✅
- **6440** 在 `_evaluate_final_display_fragment`（6349），它在 6387 读的是
  **原版** `_is_open_subordinate_prefix` → 仍无条件发火 ❌

而 `_evaluate_item_pair_for_final_boundary`（6199）**两条都吃**：
6219 调 `_cross_item_structural_boundary_issues`，6241 调 `_evaluate_final_display_fragment`，
后者的 `hard_fragment_issues` 在 6246-6248 被合并进 `hard_issues`。
→ **同一条边界被同名 code 重复发射，抹掉一个不改变 `legal` 的结果。**

### 15.3 【关键】不要直接去改 6387 —— 那会重演上一轮的踩坑

`_evaluate_final_display_fragment` 有 **11 个调用者**，其中**三个在显示层**：

| 调用行 | 所在函数 | 层 |
|---|---|---|
| 6241 | `_evaluate_item_pair_for_final_boundary` | **边界（有实测背书）** |
| 4893 / 5171 / 5176 / 5679 / 7082 / 7623 | pre-ID 再平衡与修复 | 结构（未测） |
| 6545 | `_weak_fragment_issues` | 未测 |
| **5938** | **`_visual_split_display_unit_issues`** | **显示层** |
| **6034** | **`_validate_final_display_fragments`** | **显示层** |
| **10127** | **`_stable_candidate_display_safe`** | **显示层** |

把 6387 换成 arm F 判据 = 一次改动同时影响这 11 个消费点，
**与上一轮"改共享 helper"是同一个错误形状**，只是换了个函数。别做。

### 15.4 【已实测】推荐方案 B：只在边界那一个消费点后置过滤

在 `_evaluate_item_pair_for_final_boundary` 里，6241 拿到 `fragment_evaluation`
之后、6246 合并之前，按 arm F 抹掉这个 code：

```python
fragment_hard = list(fragment_evaluation["hard_fragment_issues"])
if ("open_subordinate_prefix_fragment" in fragment_hard
        and not self._is_open_subordinate_prefix_for_structural_boundary(left)):
    fragment_hard = [c for c in fragment_hard
                     if c != "open_subordinate_prefix_fragment"]
for issue in fragment_hard:            # 原 6246-6248
    if issue not in hard_issues:
        hard_issues.append(issue)
...
result["hard_fragment_issues"] = fragment_hard   # 原 6253，保持一致
```

**实测复现 452 / 5,180、`open_sub` 37**，与 §11 的 arm F 预测值精确一致。
`_evaluate_final_display_fragment` 一行不改 → **其余 10 个调用者、含 3 个显示层的，零变化**。
这是"作用面收窄到有实测背书的那一处"的字面落地。

方案 A（给 `_evaluate_final_display_fragment` 加 `structural_boundary: bool = False`
参数，仅 6241 传 True）在语义上更干净，但改的是 11 个调用者共用的签名；
若选 A，放行条件同样是 **452 / 37 且显示层测试未改而全绿**。

### 15.5 S2 放行条件的当前状态

| 条件 | 状态 |
|---|---|
| 显示层测试全绿且一行未改 | ✅ 已满足（共享 helper 已复原，显示层不再读 spaCy 判定） |
| 新增非法 = 0 | ✅ 满足但**无意义**：因为收益也是 0，等于没改 |
| **消掉 64 条（516 → 452）** | ❌ **未满足，当前 516**。补上 15.4 即可 |
| **新增合法候选切点 ≤ 69** | ⏸ 未测。需在补完 15.4 后跑 `measure_open_subordinate_v4.py` 的枚举 |

→ **S2 不放行。** 补 15.4 后重跑本节两张表，再验第四条。

---

## §16 脚本已可独立运行 + 预期收益分层（不要把 516→452 当效果指标）

### 16.1 `docs/audits/2026-08-24/external-claude-measurement/` 的 10 个脚本现在路径无关

原先每个脚本写死了外部审计方的 Linux 绝对路径，在 Windows 上会直接失败；
其中 `sys.path.insert` 还指向一个 Windows 上不存在的目录，
**即使手改 `PROJ` 也会在跨脚本 import 处再挂一次**。已全部改为：

```python
_HERE = Path(__file__).resolve().parent
PROJ = Path(os.environ.get("VC_REPO") or _HERE.parents[3])
OUT = _HERE
sys.path.insert(0, str(_HERE))
```

另修掉 5 处残留的写死输出路径（`measure_boundary_flips.py:231`、
`measure_finite_counterfactual.py:110`、`measure_finite_predicate.py:110`、
`measure_stage2.py:85,129`）。`MODEL` 随 `PROJ` 自动定位。

已验证：无残留 `/sessions/` 字面量；10 个脚本全部 `py_compile` 通过；
**从一个与仓库无关的工作目录运行 `measure_stage2.py`，复现 5,180 / 516 / `open_sub` 110。**

含义：**S2/S3/S5/S6 的验收数字全部在本报告 §14/§15 里预先登记，
且脚本现在可由改动方自己跑。** 自查在这种条件下是有效的——
危险的是事后挑一个自己已经达成的标准当成功，而这里标准早于动手时间钉死。
仍然适用的红线见 §14.2：**谁写的谁不许判定通过**，
所以"跑出目标数"是必要条件，不是充分条件。

### 16.2 预期收益分层（改完之后到底哪里会变好）

| 改动 | 数量级 | 肉眼可见？ | 说明 |
|---|---|---|---|
| S5 分页门槛 1100 → 1260 | 303 页 / 5,352（5.7%） | **是** | 现网双行页改为单行，页数与切分不变 |
| S5 分页门槛 1100 → 1455 | 785 页 / 5,352（14.7%） | **是，但需目视** | 已接近面板满宽，"塞得进去"已实测，"好不好看"**未测** |
| S2 arm F 补完（516 → 452） | 64 条 | **不一定** | 见 16.3 |
| S3 `be/been/being` 快速路径 | 18 例 / 5,123（0.4%），其中 14 例单由这三个词造成 | 否 | 正确性修复 |
| S3 casefold 喂 spaCy | 49 例 / 5,123（1.0%），集中在祈使句 | 否 | 新判据已用 `str(word).strip()`，此项可能已自然消解，需复测确认 |
| S7 低于地板的父字幕 | 457 条 | — | **本轮完全未动**，且无预登记验收条件 |

分页两行的基数 5,352 页 / 4,656 父来自 22 个产物集，其中约 9.9% 的父字幕
是 2 集被算了两遍（见目录 README），比例结论不受实质影响。

### 16.3 为什么 516 → 452 不是效果指标

9.96% 那个数衡量的是**规则自相矛盾**：生产已接受并已合成出去的父间边界，
拿现规则回头判会判成非法。消掉它是账目一致性变好，**不等于切得更好**——
这条方法论已在 §11.5 写过，此处重申是因为它极易被当成优化目标。

具体理由：arm F 只是把 64 个原本被 `open_subordinate_prefix_fragment`
**硬挡住**的候选切点放开；最终切在哪儿由全局 DP 的代价函数决定。
**该代价函数从未被测量**，而已知存在 2,122 个"合法但未被选中"的切点，
直接说明**合法 ≠ 会被选中**。因此 arm F 的预期效果是：
少数 `when/if/because/although` 类从句开头处切到应切的位置，其余无感。

风险方向也要记住：**放宽规则本身可以让效果变差。**
现有证据把风险限定在有界范围内——`newly_illegal = 0` 是实测（不是推断），
64 条新增合法切点已在 §11.5 逐条目视复核——但不是零风险。

### 16.4 一条实测到的落地成本：改完不会让已导出的视频变好，重跑会触发中文重翻

- `word-ledger.json` / `final-cue-timeline.json` / `english-boundary-audit.json`
  等产物在 `screen_editor.py:13544-13594` 处**只写不读**，是证据文件而非缓存。
  故规则改动不会追溯改写任何已冻结产物或已导出视频，必须重跑才体现。
- `stable_pipeline_contracts.py` 的 `FrozenPipelineSnapshot` 是**单次运行内**的
  哈希护栏（禁止中文阶段回改英文/时间/语义组），**不是跨运行的复用缓存**。
- LLM 结果按文本哈希缓存（`split_by_llm.py:30-56` 的 `get_cache_key(text, model)`）。
  **切分一改 → 父字幕文本改 → 缓存键改 → 中文重新调用。**
  已人工校对过的中文，在被重切的段落上会回到未校状态。

→ 建议：**先在一集新素材上验证，不要对着已人工校好的老集直接重跑。**

---

## §17. S2 二次放行复核：规则已验证正确，收益仍为 0，缺口只剩一处接线（2026-08-24 实测）

复核对象：GPT 报告"本轮已完成（恢复 classmethod / 拆出私有结构边界判据 / 保留
spaCy 缓存与回退 / 视觉层不受影响 / 新增四类测试）"。
被复核树：`screen_editor.py` mtime `2026-08-24 08:49:30`，
`git diff --ignore-cr-at-eol --numstat` = **+61 / −1**。
本节所有数字为审计者在该树上重新实跑所得，**未修改任何项目文件**。

### 17.1 结论（一句话）

**规则和实现都对，但生产可见收益依然是 0——因为同一个 code 有两个发射源，只豁免了一个。**
这不是判断分歧，是可复现的数字：见 17.2。

### 17.2 生产面复测：三个数一个字没变

`python docs/audits/2026-08-24/external-claude-measurement/measure_stage2.py`

| 指标 | 改动前基线 | GPT 本轮完成后 | 变化 |
|---|---|---|---|
| 生产已接受边界 | 5180 | **5180** | — |
| 被判非法 | 516（9.96%） | **516（9.96%）** | **0** |
| 其中 `open_subordinate_prefix_fragment` | 110 | **110** | **0** |

原因（一手读代码，非推测）：该 code 有两个发射源。

| 行号 | 所在函数 | 用哪个判据 | 状态 |
|---|---|---|---|
| 6291→6292 | `_cross_item_structural_boundary_issues` | `_is_open_subordinate_prefix_for_structural_boundary` | 已豁免 ✅ |
| 6387→6440 | `_evaluate_final_display_fragment` | `_is_open_subordinate_prefix`（原版） | **未豁免 ❌** |

两者都被 `_evaluate_item_pair_for_final_boundary`（def 6199）消费并在 6246-6248
合并（6219 走前者、6241 走后者），所以**只要 6440 还在报，合并结果就照旧非法**。

### 17.3 缺口确认只是接线：方案B 复现 452 / 37

在 GPT 当前树上，**不改任何函数**，只在 6241 与 6246 之间那一个消费点后置过滤该
code（调用 GPT 自己的新私有判据），实测：

```
方案B 后置过滤        非法 452 / 5180   open_sub=37     （预登记目标 452 / 37）
```

与 §11 预登记目标完全一致 → **规则无误，只差把第二个发射源接上。**
不采用"直接改 6387"的原因见 §15：`_evaluate_final_display_fragment` 有 11 个调用点，
其中 3 个在显示层（`_visual_split_display_unit_issues` 5938、
`_validate_final_display_fragments` 6034、`_stable_candidate_display_safe` 10127），
在那里动手等于换个函数把 8 个回归再犯一遍。

**建议落地代码（方案B，作用面 = 唯一的边界消费点）：**

```python
# _evaluate_item_pair_for_final_boundary 内，6246 合并之前
if "open_subordinate_prefix_fragment" in fragment_evaluation.get("hard_fragment_issues", ()) \
        and not self._is_open_subordinate_prefix_for_structural_boundary(left):
    fragment_evaluation = dict(fragment_evaluation)
    fragment_evaluation["hard_fragment_issues"] = [
        c for c in fragment_evaluation["hard_fragment_issues"]
        if c != "open_subordinate_prefix_fragment"
    ]
```

### 17.4 安全侧反向枚举：69 / 0，且两套独立实现互相印证（本轮新增证据）

比"非法数下降"更该看的是**放宽后新开了多少切点**。全量枚举 49,678 个内部候选切口
（门内 3,537 个），基线 vs 方案B：

| 指标 | 预登记目标 | 实测 | 判定 |
|---|---|---|---|
| 新变合法的切点 `newly_legal` | ≤ 69 | **69** | PASS |
| 新变非法的切点 `newly_illegal` | 0 | **0** | PASS |
| 去重后的不同左右对 | — | 64 | — |

**关键交叉验证：** `measure_open_subordinate_v4.py` 里的 arm F 是审计者**自己重写**的；
本轮脚本调用的是 GPT **实际落地**的
`_is_open_subordinate_prefix_for_structural_boundary`。
两套独立实现在两个不同测量面上给出同一组数（69/0 与 452/37）
→ **GPT 的实现与审计规格语义等价**，此项不再需要复核。

脚本：`/tmp/optb_reverse.py`（审计者临时件，未入库；如需入库请让审计者归档）。

### 17.5 §13.4 三处硬伤的当前状态：全部不再影响 arm F

一手读 6594-6650 确认：

| §13.4 缺陷 | 影响量 | 当前状态 |
|---|---|---|
| classmethod→实例方法，打断外部脚本 `.__func__` | blocker | **已修**：`_fragment_has_finite_predicate` 恢复 `@classmethod`（6652 附近同款写法），审计脚本**原封不动跑通**（17.2 即为证据） |
| `be`/`been`/`being` 被当有限式短路 | 18 例 / 0.4% | **不再影响 arm F**：`_structural_fragment_has_finite_predicate` 的 spaCy 路径**没有词表快捷路径**，直接送 `nlp()` |
| 送进 `nlp()` 的文本被 casefold，降低标注质量 | 49 例 / 1.0% | **已修**：6613 用 `str(word).strip()`，未 casefold |

GPT 选择"恢复 classmethod"而不是审计者建议的"改脚本适配"，是**更优解**——
它让 before/after 仪器保持可用，代价为零。此处采纳 GPT 判断。

### 17.6 本轮新发现的一处（非阻塞）：回退路径导致切分结果与环境相关

6642-6648 的回退分支在 spaCy 不可用时改走旧词表（且 casefold）。方向是**安全的**——
旧词表把 `be/been/being` 当有限式 → `has_finite_predicate` 为真 → arm F 返回 False
→ 仍然拦住 → 退回改动前行为，**失败朝保守侧倒**，不会产生新的激进切分。

但对"冻结可复现"的稳定模式来说，这意味着**同一份输入在装/不装模型的机器上会切出不同结果**，
而产物里没有任何字段能事后区分。建议（低成本、不改逻辑）：
把 spaCy 是否可用 + 模型版本写进 `english-boundary-audit.json` 一类证据文件，
让重跑差异可被发现，而不是静默漂移。

### 17.7 放行判定

- **arm F 规则与实现：放行 ✅**（69/0 与 452/37 双面印证，语义等价已确认）
- **S2 整体：仍不放行 ❌**，唯一未完成项 = 17.3 那一处接线。
  放行条件：`measure_stage2.py` 输出 **452 / 5180，open_sub=37**；
  且 `newly_illegal == 0` 保持不变。两个数都已预登记，GPT 可自验。

### 17.8 复核者声明

- 本节未修改任何项目文件；改动仅限本报告与 `/tmp` 下的临时脚本。
- 未运行 `git checkout .` / `git restore .`。
- 未跑 pytest：GPT 报告的"新增四类测试"是否通过，由 GPT 自行确认；
  §13.5 的警告仍然有效——**测试断言可以把当前行为固化成"正确"**，
  所以测试通过不能替代 17.7 的两个数字。

---

## §18. S2 通过之后干什么：优先级排序（2026-08-24 追加）

前置：`measure_stage2.py` = **452 / 5180, open_sub=37** 且 `newly_illegal == 0`。
未达到就别往下走，缺口见 §17.3。

**先明确一件事：到这里"规则自洽"的活基本干完了，不要再刷这个指标。**
516→452 衡量的是规则自相矛盾，不是切得更好（§16.2）。继续压这个数会把生产的错切
一并合法化（§1 的坑）。下面按"用户能看见的改善 / 单位风险"排序。

### 18.1 立刻做：把收益锁死成不变量测试（低风险，防倒退）

§2 的根因是**没有任何测试保证"现规则仍接受历史已发布输出"**。S2 通过后应新增一条
回归测试：喂 5,180 条生产已接受边界，断言被判非法 **≤ 452**（棘轮，只许降不许升）。
这比新增的四类单元测试重要——后者验的是新判据自身行为，前者防的是**下一次改动
悄悄把 452 顶回 516**。注意 §13.5：单元测试可以把当前行为固化成"正确"，
所以断言要挂在**生产历史数据**上，不是挂在手写样例上。

**顺带（5 行、零逻辑改动）**：把 spaCy 可用性 + 模型版本写进
`english-boundary-audit.json`，理由见 §17.6（否则装/不装模型切出来不一样且事后无法分辨）。

### 18.2 然后做：S6 —— v28 起的空行回归（真 bug，用户能看见）

`english_lines == []` 的页共 **15 个**，**v28 才出现、v29/v32 仍在**（§8）。
这是屏幕上真的出现空白英文行，比任何规则整洁度都更该修，且属"新引入回归"，
按 v27→v28 的 diff 定位应该很快。**分版本看，不要看全量 44 条**（会误报已修好的 >2 行）。

### 18.3 然后做：S5 —— 分页常数 1100（最便宜的可见改善，但需要人眼定档）

`podcast_learning_video.py:3591` 用 `ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH=1100`
早退，而面板阶梯是 1260/1455/1498，**1100 不在其中**（§8）。抬到 1260 → **303** 个双行页
变单行；抬到 1455 → **785** 个（占双行页 23.5%）。页数/切分/翻译/约束压力全不变。

**这一步不该由模型拍板**：代价是行更长，属可读性取舍。
GPT 应当**产出 1100 / 1260 / 1455 三档的同页真实渲染对比图**交用户选，而不是自己定。

### 18.4 再然后：S1 —— 共享 helper 的爆炸半径表（只测量，不改代码）

`_fragment_has_finite_predicate` 单向漏判 42%、返回值在 5,123 条父字幕上翻转 35.9%，
是切分层最大的地基缺陷（§3）——**但它有 11 个消费点，其中 3 个在显示层**。
两次回归都出在这儿。所以下一步**不是修它，是先出一张表**：
11 个消费点各自有多少条判定会翻转、翻转方向、显示层受影响页数。
有了表才能决定作用面；没表就动 = 第三次重犯。**本项审计者也未跑过，是双方共同空白。**

### 18.5 落地验证（贯穿以上每一步）

规则改动**不会**追溯改写任何已冻结产物或已导出视频，必须重跑才体现（§16.4）。
而重跑会改父字幕文本 → LLM 缓存键改 → **中文重新翻译，已人工校对的段落回到未校状态**。
→ **一律先在一集新素材上端到端验证，不要对着已人工校好的老集直接重跑。**
判断标准是"看着是不是更好"，不是矛盾条数。

### 18.6 暂缓：S7 —— 真正的瓶颈（没有预登记门禁，先设计测量）

切分层对分页可行性完全盲（§5）、代价函数从未被测量（2,122 个"合法但未被选中"的切点
就是证据）、457 个父整条低于 ≥4词/≥900ms 地板（§8）。这三件才是 90-95% 自动化的真障碍，
但**本报告没有为它们预写任何验收数字**。进入这一块之前应先补测量设计，
否则又会重演"在对目标函数盲的空间里搜索"（§7）。

---

## §19. 【实测·最高优先级】真正的瓶颈是"审校清单不工作"，不是切分质量

本节推翻 §18 的优先级排序。§18.1/18.2 保留，18.3/18.4 让位于本节。

### 19.1 用户的真实工作流（本节的起因）

用户反馈原话：**"现在基本上跑的结果我要逐条看，不止是标黄的字幕，因为我不知道没标的
哪一条长字幕没切好导致翻译不好，还有就是分页也分的差，还有一些短字幕也可能有问题。"**
目标是"自动化完成 90-95%，我补 5-10%"。

**注意这个目标的字面含义：它是"我只需要动 5-10% 的条目"，是一个审校覆盖率指标，
不是切分质量指标。** 前面所有轮次（§11/§15/§17 的 516→452）优化的都是后者。
**即使把矛盾数刷到 0，用户仍然要逐条看 230 条**，因为他没有"哪些可以不看"的依据。

### 19.2 实测：现有 QA 清单每集标 0-1 条

`qa-review-points.json` 在 47 个产物集上的条数分布：**中位数 0，最大 2**。
121 个 `qa-review-points.json` 里只有 28 个非空（>3 字节）。

根因（一手读代码，`screen_editor.py:12746-12814`）：
`_editor_review_points` **只遍历 `self._last_allocation_unresolved`**，
再用 `_is_editor_visible_allocation_issue` 筛到 6 个码
（`cross_id_semantic_leakage` / `group_allocation_information_omission` /
`entity_allocation_mismatch` / `number_allocation_mismatch` /
`negation_allocation_mismatch` / `adjacent_chinese_semantic_duplication`）。

→ **它是一个"中文分配失败"专用清单，不是审校清单。** 结构上不消费任何：
英文边界合法性、父字幕长度、分页结果、时长/词数地板、字号回退、行数异常。
用户列出的三类担忧（长句切坏、分页差、短字幕）**没有一类在覆盖范围内**。
它不报错、只输出 `[]`，所以这个缺口从未被发现。

### 19.3 关键认识：所需信号全部已经存在，且已被本报告量化

**不需要改任何生产代码、不需要重跑、不触发中文重翻**（§16.4 的代价不适用），
因为下列信号都已冻结在产物里，且本报告已逐项测过：

| 用户的担忧 | 可用信号（已实测） | 出处 |
|---|---|---|
| 长字幕切坏 → 翻译差 | 父间边界被判非法 **516/5180（9.96%）**，逐条带 rule code | §2 |
| 同上（漏判） | `_fragment_has_finite_predicate` 单向漏判 42%，翻转 35.9% | §3 |
| 分页差 | `english_lines == []` **15 页**（v28 起） | §8 |
| 分页差 | `<900ms` **4.4%**、`<4 词` **7.1%**、`>2 行`（v26 前） | §8 |
| 分页差 | 字号回退 **5.8%**、宽度档 1455/1498 占 17.9%（拥挤） | §8 |
| 分页差 | 因 1100 门槛被迫双行的页 **303–785 个** | §8 |
| 短字幕问题 | 整条低于地板的父字幕 **457 个（9.8%）** | §8 |

### 19.4 建议的新 #1：一份"只读审校清单"（recall 优先）

产出物：每集一个按严重度排序的清单，逐条给出 `subtitle_id` + 命中的信号 + 原文/译文/页面预览。
**设计原则是高召回，不是高精度** —— 它的价值在于让用户能**信任"不在清单上的可以不看"**。
现有清单精度可能很高但召回接近 0，所以毫无用处。

**实施要点：**
1. 只读跑在已冻结产物上，与生产链路零耦合（先做成独立脚本，验证后再考虑接进流水线）。
2. 输出必须带**为什么被标**，否则用户仍要自己判断。
3. **列表规模需要实测**：上表各项有重叠，并集占比未测。若并集 >30%，需要按严重度分层。

### 19.5 这个项目的终止条件（回答"做到啥时候是个头"）

**终止条件不是矛盾数归零，是清单可信。** 可在**一集**素材上测出来：

1. 用清单审一集；记录两个数：**(a)** 清单标了 N 条，你实际改了几条（精度）；
   **(b)** 你改的条目里，有几条清单没标（**召回缺口，这个才是关键**）。
2. 召回缺口为 0 或极小 → **可以停止逐条看**，"自动化 90-95%" 当天达成，
   与切分质量再改多少无关。
3. 召回缺口大 → 缺口本身就指明了下一步该修什么，**且这时才轮到改切分质量**，
   方向由数据给出，不再靠猜。

**在 (b) 被测出来之前，任何进一步的切分/分页工程都是在无目标函数的空间里搜索**
（与 §7 批评 gpt5.6 三个实验的错误完全同类，此处适用于双方）。

---

## §20. 无人值守工单（2026-08-24，用户离开期间；GPT 按此顺序执行）

**背景**：用户不在场，无法做取舍判断、无法中途纠偏。本节把工作拆成"有硬数字、
可自验、失败会停"的步骤。**每一步都有预登记验收数字，都是在你动手之前写下的，
所以你自验是有效的；但你不得修改任何目标值。**

**你提的四步计划（固定基线 → 测 1260 → 决定是否保留 → 真实音频回归）结构正确，
但有三处会出事，已在下面修正**：A 必须先过门禁否则 B 会把 516 焊成基线；
E 你不得自行决定（是可读性取舍，且候选值有两个）；F 不得对已人工校对的集重跑。
另外你的计划整体在"让规则自洽"这条线上，缺了 §19 认定的真瓶颈，已补为 C。

### 硬规则（违反即停止，写明原因，不要绕过）

1. **不得运行 `git checkout .` / `git restore .`**：工作树有 119 个 M，
   其中 113 个是 CRLF 假阳性，6 个属并发 Codex 会话的在飞工作，会被销毁。
2. **不得对已人工校对过的产物集重跑**：重跑改英文文本 → LLM 缓存键改 →
   中文重新翻译 → 用户校对成果丢失（§16.4）。回归只能用新素材或一次性副本。
3. **不得把"矛盾数下降"当优化目标**（§11.5 / §16.2）。降它可以，追它不行。
4. **门禁数字对不上时停下**，把实测值和差异定位到具体哪几条边界，写进本文档，
   **不要调整目标值、不要改测试断言去迁就实现**（§13.5）。
5. 测量脚本在 `docs/audits/2026-08-24/external-claude-measurement/`，路径无关，
   Windows 上直接 `python docs\audits\...\measure_stage2.py` 即可，不需要改任何路径。

### A. 补完 arm F 接线（先做，未过不得进入 B）

按 §17.3 的方案 B，在 `_evaluate_item_pair_for_final_boundary` 的 6241 与 6246 之间
后置过滤 `open_subordinate_prefix_fragment`。**不要改 6387 / `_evaluate_final_display_fragment`**
（11 个调用点，3 个在显示层，§15）。

**验收**：`measure_stage2.py` → **452 / 5180，`open_sub`=37**；
且反向枚举 `newly_illegal == 0`、`newly_legal ≤ 69`。
显示层测试**不得修改断言**而全绿。

### B. 把收益焊成不变量测试（A 通过后立即做）

新增回归测试：喂 5,180 条生产已接受边界，断言被判非法 **≤ 452**（棘轮，只许降不许升）。
断言必须挂在**生产历史数据**上，不是手写样例（§18.1）。
**注意：A 未通过就做 B，等于把 516 焊成基线，收益永久丢失——这是你原计划第一步的风险点。**

顺带（5 行、零逻辑改动）：把 spaCy 是否可用 + 模型版本写进
`english-boundary-audit.json`，理由见 §17.6。

### C. 只读审校清单（本工单最高价值项，§19）

> **🛑 本小节已被 §21 推翻，不要按这里执行。** 产品里已有真正的审校清单
> `editor-review-ledger.json`（标出率 12–27%，已达标）；我此前测的
> `qa-review-points.json` 是死路径。**C 改为 §21.3 的 C1/C2/C3：回填 + 实测召回率，
> 不要重写清单。** 下面原文保留仅作错误记录。

**为什么是它**：`qa-review-points.json` 在 47 个产物集上中位数 0 条、最大 2 条，
因为 `_editor_review_points`（12746-12814）只遍历 `_last_allocation_unresolved`，
不消费边界合法性 / 父字幕长度 / 分页结果 / 时长词数地板 / 字号回退 / 行数异常。
用户因此必须逐条看两百多条字幕。**这才是"自动化 90-95%"的真障碍。**

**做法**：先写成**独立只读脚本**（放 `docs/audits/2026-08-24/` 下），
跑在已冻结产物上，**不改生产代码、不重跑、不触发中文重翻**。验证有效后再谈接入流水线。

**输入信号（全部已量化，出处见 §19.3）**：边界被判非法（每条带 rule code）、
`english_lines == []`、页时长 <900ms、页词数 <4、字号回退、宽度档落在 1455/1498、
父字幕整条低于地板。

**输出**：每集一份按严重度降序的清单，每行含 `subtitle_id`、命中的信号及**为什么被标**、
英文、中文、页面信息。设计目标是**高召回**，不是高精度。

**验收（预登记）**：报告"被标条目占该集父字幕总数的比例"。
**并集占比应 ≤ 30%**；若 >30%，必须按严重度分层并报告每层占比——
不分层的 40% 清单等于没有清单。

### D. v28 空行回归（真 bug，用户可见）

`english_lines == []` 共 **15 页**，v28 起出现、v29/v32 仍在（§8）。
按 v27→v28 的 diff 定位。**分 `planner_version` 看，不要看全量 44 条**（会误报已修好的 >2 行）。
**验收**：空行页 15 → **0**，且页数、切分、翻译均不变。

### E. 分页常数对照图（只产出，不得决定）

`podcast_learning_video.py:3591` 的单行早退门槛是
`ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH = 1100`（194 行），而面板阶梯是
1260/1455/1498，**1100 不在其中**。抬到 1260 → **303** 个双行页变单行；
抬到 1455 → **785** 个（占双行页 23.5%）。页数/切分/翻译/约束压力全不变。

**你原计划只测了 1260，候选值有两个，必须都出。**
**产出**：同若干代表页在 **1100 / 1260 / 1455** 三档下的真实渲染对比图，
放进 `docs/audits/2026-08-24/`，附各档受影响页数。
**不要改那个常数，不要替用户决定**——行变长是可读性取舍，只有用户能定。

### F. 真实音频回归（最后做）

**只能用新素材，或已校对集的一次性副本。禁止对用户已人工校对的产物集重跑**（硬规则 2）。
判断标准是"看着是不是更好"，不是矛盾条数。

### 完成 A–F 之后的收益边界（预先写明，防止误报"问题已解决"）

**A 的可见收益可能接近零，这是预期，不是失败。** `newly_legal=69` 的含义是
"规则现在允许在这 69 个切口断"，**不等于 DP 会选中它们**（§11 已证：已合法但未被选中
= 2,122 个，纯代价决策）。A 的真实价值是**还技术债 + 让 B 有意义**，
不要在 `执行进展-给用户.md` 里把它写成画质提升。

**B / F 不产生任何用户可见变化。** B 是安全带（只在未来某次改动想悄悄退化时才显形），
F 是通过/不通过信号。两者都不许计入"自动化率提升"。

**D / E 是本轮唯一真正改变屏幕内容的两项**，且 E 的决定权不在你手上。

**C 你可以交付，但你不能判定它成功。** 唯一有效的检验是用户拿一集素材逐条审一遍，
数出**"他动手改了、而清单没标出来"的条数**（§19.5）。这个数只有他能产出。
所以 C 完成时的正确措辞是"清单已生成，标出率 X%，待用户校准"，
**不是"审校问题已解决"**。参照 §16.1 的教训：上一轮"本轮已完成"的实际生产收益是 0。

**因此 A–F 全部通过后，项目距"自动化 90-95%"仍差一次用户校准 pass。**
那一次逐条审是**不可避免的**，也是整个项目唯一一次还需要用户全量投入的动作 ——
它换来的是此后可以只看清单。**把这句原样写进 `执行进展-给用户.md`，别让他以为已经到位。**

### 报告方式（用户回来只看一个文件）

每完成一步，把**实测数字 + 通过/未通过**追加到本文档；同时把一段**大白话**说明写进
仓库根目录的 `执行进展-给用户.md`（没有就新建）：这一步干了什么、数字是多少、
有没有需要他决定的事。**需要他决定的事集中列在该文件末尾**，不要散在各处。

---

## §21. 【自我纠错·最高优先级，覆盖 §19 与 §20-C】审校清单其实已经存在，我测错了文件

**2026-08-24 第九轮。GPT：如果你已经开始做 §20 的 C，立刻停下来读本节。C 的前提被推翻了。**

### 21.1 我错在哪

§19 我判定"内置审校清单结构性不查用户关心的三样"，依据是
`qa-review-points.json` + `_editor_review_points`（screen_editor.py:12746-12814）。
那段代码的读法没错 —— 它确实只遍历 `_last_allocation_unresolved`。
**但它不是产品的审校清单。** 真正的清单是
**`editor-review-ledger.json`**，写出点 `app/core/subtitle_processor/subtitle_review_marks.py:32`
（`_REVIEW_LEDGER_NAME`，`_REVIEW_LEDGER_SCHEMA_VERSION = 2`，
写函数 `write_subtitle_review_ledger` 在 60 行，读函数 `load_subtitle_review_marks` 在 49 行）。

我从头到尾没打开过这个文件。**§19.2 那句"结构性从不消费边界合法性/分页/地板"是错的**，
错误性质是**取证不全**：我只查了自己先前见过的文件名，没有先列举产物目录里所有
review 相关的文件。这与我批评 GPT 的"爆炸半径意识"是同一类错误的镜像 ——
**动结论前没先枚举全集**。

### 21.2 实际存在的东西（实测）

32 份 ledger，分布在 **5 个剧集**（全库 62 集）。结构：
`schema_version / source_word_ledger_hash / summary{task_count, blocker_count, review_count,
subtitle_count} / items[] / artifact_hash`，每个 item 含
`task_id, severity(BLOCKER|REVIEW), category, target, code, reason, subtitle_ids, recommended_action`，
`reason` 是**中文可读句子**（例："该分页边界需要人工确认：stockroom | for。"）。

全部 997 条 item 的分布：severity **BLOCKER 82 / REVIEW 915**；
category **visual_page 466、chinese_allocation 226、english_cut 139、asr_correction 114、
chinese_coherence 30、chinese_length 15、chinese_fluency 7**；
code Top：`high_confidence_visual_page_boundary` 264、`visual_page_boundary_review` 165、
`english_boundary_audit` 139、`model_semantic_loss` 87、`article_asr_correction_review` 76、
`high_confidence_chinese_semantic_issue` 62。

**→ 用户担心的三样全部在覆盖范围内**（长句切分 = english_cut 139、
分页 = visual_page 466、短碎片 = ledger 里明确有 `incomplete_short_fragment`
/ `weak_subject_fragment` / `incomplete_interrogative_fragment` 的 reason 文本）。

**标出率（被标字幕数 / 该集父字幕数）**：

| 剧集 | 快照 | items | 标出字幕 | 父字幕 | 标出率 |
|---|---|---|---|---|---|
| 白宫对中国转运骗局的荒谬指控 | 10 | 58 | 59 | 221 | **27%** |
| 日本X世代的困境 | 2 | 61 | 55 | 241 | **23%** |
| 中国人会爱上巧克力吗？ | 2 | 60 | 44 | 221 | **20%** |
| 中国会有爱上巧克力的一天吗？ | 9 | 45 | 40 | 221 | **18%** |
| 无论怎么衡量，就业市场都很疲软 | 9 | 27 | 30 | 260 | **12%** |

**12%–27%，全部落在 §20-C 预登记的 ≤30% 门禁之内。**
也就是说 C 想造的东西，**产品里已经有了，而且已经达标**。
用户说的"标黄的字幕"就是它 —— 他一直在用，我却以为他在用那个空文件。

### 21.3 §20-C 作废并替换

**不要重写一份清单。** C 改成下面两件事：

**C1（最高优先级，只读，可能今天就有答案）：回填 + 召回率实测。**
`load_subtitle_review_marks`（subtitle_review_marks.py:49-57）在**没有 ledger 时会用
`_collect_subtitle_review_marks(directory)` 从冻结产物现场推导同一组 marks**。
→ **老剧集可以回填 ledger，不需要重跑、不触发中文重翻。**

**为什么这条可能直接给出答案**：盘上有 6 份 `人工终稿字幕-edits.json`
（`manual_final_subtitle_editor.py:7807` 写出），里面是**用户真实改了什么的完整记录**：
`history[]`（操作类型 `split_parent_into_display_pages` /
`move_display_page_boundary` / 删边界，带 `at` 时间戳和 before 快照）、
`display_page_boundary_overrides`（例：某集 **16 个父字幕**被用户手动改了分页边界）、
`display_page_edits[]`（每页带 `chinese_review_acknowledged` /
`boundary_review_acknowledged`）。

**实验性质极好，务必利用**：这 6 份 edits 属于 `中国AI为何更省钱？` 与
`中国年轻人为何不爱留学了？`（2026-08-07 至 08-10），
**当时 ledger 机制还不存在 → 用户的修改完全没被清单影响 → 是干净的无偏 ground truth。**
（这两集与 5 个有 ledger 的剧集**无交集**，所以必须走回填路径。）

**做法**：对 `中国年轻人为何不爱留学了？` 的那个 run 回填推导 marks，
与该集 `人工终稿字幕-edits.json` 的 `display_page_boundary_overrides` +
`history` 里出现的 `parent_subtitle_id` / `affected_parent_ids` 求交。

**预登记验收（动手前写下）**：报告三个数 ——
① 用户改过的父字幕数 N；② 其中被 marks 命中的 H；③ **漏标 N−H 及其 subtitle_id 列表**。
**不设通过阈值**（这是测量不是门禁），但**必须逐条列出漏标的那几条**，
它们就是清单的真实缺口清单。另报反方向：marks 标了而用户没动的条数（精度侧，仅供参考，
不得当作优化目标 —— 见硬规则 3）。

**C2：只有 C1 显示存在系统性漏标时才做补信号**，且补什么由 C1 的漏标列表决定，
不要凭 §19.3 那张表猜。§19.3 列的七个信号里，`english_boundary_audit` 与
`visual_page_*` 显然已在 ledger 内；真正可能没进去的是**页时长 <900ms、页词数 <4、
字号回退、宽度档 1455/1498**这四个纯几何信号 —— 但**先测，别先补**。

**C3（顺带，5 分钟）**：ledger 只覆盖 5/62 集。确认回填是否能对全部 62 集跑通，
报告失败的集数与原因。这决定用户的老片子能不能受益。

### 21.4 §19 与 §20 中受本节推翻的具体句子

- §19.2 "每集 0–2 条" —— 对 `qa-review-points.json` 成立，**对产品的实际清单不成立**（12–27%）。
- §19.3 那张"三大担心全部未覆盖"的映射表 —— **推翻**，至少两项已覆盖。
- §19.4 "需要新建只读清单" —— **推翻**，改为回填 + 测召回。
- §20 结尾"A–F 全部通过后仍差一次用户全量 pass，那一次不可避免" ——
  **可能不必**：若 C1 用历史 edits 就能算出召回率，用户零投入。
- **§19.5 的终止条件不变**（"用户改了而清单没标"的条数），它现在只是**可以离线算了**。

### 21.5 我给自己的判定

这是我今天第二次犯"没枚举全集就下结论"的错（第一次是 §1 的处方作废）。
§19 那节的代码阅读是准确的，**结论是错的**，因为我读的是一个死路径。
**教训（与 §17.8 的自证条款同级）：判定一个功能"不存在/不工作"之前，
必须先 `find` 出产物目录里所有相关文件名，不能只查自己已知的那一个。**

### 21.6 修订后的执行顺序与 C1 的确切输入路径（GPT 直接照此开工）

**新顺序：C1 → A → B → D → E → F。**
C1 提到最前面的理由：它**只读、零风险、代价小**，而且它的结果可能改变 D/E 的优先级 ——
先测再建。若你已经在做 A，把 A 做完再做 C1，但**B 之前必须先出 C1 的数**。

**C1 的 ground truth 文件（盘上实际路径，已核实存在）**：

```
work-dir/中国年轻人为何不爱留学了？/subtitle/stable-runs/20260809T211229.489470-79bfedf2/人工终稿字幕包/人工终稿字幕包/人工终稿字幕包/人工终稿字幕-edits.json   (10,069,788 B, 08-10 00:52)
work-dir/中国年轻人为何不爱留学了？/subtitle/stable-runs/20260809T211229.489470-79bfedf2/人工终稿字幕包/人工终稿字幕包/人工终稿字幕-edits.json                      ( 9,806,361 B, 08-10 00:51)
work-dir/中国年轻人为何不爱留学了？/subtitle/stable-runs/20260809T211229.489470-79bfedf2/人工终稿字幕包/人工终稿字幕-edits.json                                   ( 9,806,406 B, 08-10 00:51)
work-dir/中国年轻人为何不爱留学了？/subtitle/stable-checkpoints/20260808T174824.546048-e7cd7dde/人工终稿字幕包/人工终稿字幕-edits.json                            (   806,160 B, 08-08 18:32)
work-dir/中国AI为何更省钱？/subtitle/stable-checkpoints/20260807T233313.491159-18afa3cd/人工终稿字幕包/人工终稿字幕-edits.json                                    (   709,783 B, 08-08 00:16)
work-dir/中国AI为何更省钱？/subtitle/stable-checkpoints/20260807T163640.468734-2d954ca8/人工终稿字幕包/人工终稿字幕-edits.json                                    (   708,508 B, 08-07 16:39)
```

**注意那三层嵌套的 `人工终稿字幕包/人工终稿字幕包/人工终稿字幕包`**：同一个 run 下三份
edits，时间戳只差 1 分钟、大小相近 —— **疑似"打包时把上一层整个包又拷进去"的目录递归 bug**，
顺手确认一下（可能是第三个真 bug，但**先别修，先记录**，它不在本工单授权范围内）。
取样时用**最深那份**（10,069,788 B，最新，`display_page_edits` 317 条 / `history` 36 条 /
`display_page_boundary_overrides` 16 个父）。

**该 run 的 marks 从哪来**：同一 run 的 artifacts 目录下**没有** `editor-review-ledger.json`
（ledger 只存在于 5 个较新剧集），所以走
`load_subtitle_review_marks(artifact_dir)`（`subtitle_review_marks.py:49-57`）——
无 ledger 时它会用 `_collect_subtitle_review_marks` 从冻结产物现场推导。
**这条路径必须只读调用，不要顺手 `write_subtitle_review_ledger` 往老产物里写文件。**

**ground truth 集合怎么取（三个来源取并集，分别报数）**：
1. `display_page_boundary_overrides` 的 key（16 个 `subtitle_id`）—— 最硬，
   代表"用户明确认为分页不对并动手改了"；
2. `history[]` 里的 `parent_subtitle_id`（22 条有）+ `affected_parent_ids`（12 条有）；
3. `display_page_edits[]` 中 `boundary_review_acknowledged == false` 的页所属父字幕 ——
   **这一项含义不明，务必先确认它是"未确认"还是"无需确认"**，
   搞不清就单独报数、不要并进去。

**输出格式（写进本文档）**：
`N（用户改过的父数） / H（其中被 marks 命中） / N−H（漏标，逐条列 subtitle_id 与英文原文）`，
另附 marks 标了但用户没动的条数（仅参考，**不得当优化目标**）。
再按 marks 的 `category` 拆一遍命中率，看漏标集中在哪一类。

**不要做的事**：不要因为漏标多就去放宽任何规则（那是 §11.5 的坑）；
C1 只产出"清单缺哪些信号"这一个事实。补信号是 C2，且必须由 C1 的漏标列表决定。

---

## §22. 外部审计者不在场时的续跑协议（GPT：本节让你不再需要我）

**背景**：外部审计者（Claude Opus 5）的额度接近用尽，GPT 侧额度充裕。
本节把"必须有个外人复核"这条治理要求，换成**可以写在磁盘上、由你自己执行的机制**。
**从现在起默认无审计者。**

### 22.1 唯一的目标函数

**C1 的漏标数**（"用户动手改了、而 `editor-review-ledger.json` 没标出来"的父字幕条数）。
其余所有数字都是过程量。**特别是 516 / 452 不是 KPI**，
汇报时不得写成"自动化率提升"（理由见硬规则 3、§16.3、§20 收益边界节）。

判定项目可收工：漏标数接近 0（用户从此只看标黄的 12–27%），
或"手工补的时间 < 继续做工程的时间"。

### 22.2 替代"谁写的谁不许判定通过"的三条机制

原则本身不变，但在没有外人时用下面三条替代人肉复核：

1. **预登记数字**。动手之前把验收数写进本文档，再动手。已登记的：
   A = `452 / 5180`、`open_sub=37`、`newly_illegal=0`、`newly_legal≤69`；
   B = 不变量棘轮 `≤452`；D = 空行页 `15→0` 且页数/切分/翻译不变；
   C1 = 无阈值但必须逐条列出漏标 ID。
   **对不上就停下写明原因，不得改目标值、不得改断言迁就实现。**
2. **反方向枚举**。任何"放宽"类改动，除了报"新增非法 = 0"，
   必须同时枚举**新增合法**的切点并逐条人工看。只看前者必然重蹈 §1 与 §11.5。
3. **不变量测试挂历史数据**（B 项）。它是唯一能在无人看管时长期生效的防退化装置，
   所以 B 的优先级高于任何新功能。

### 22.3 审计者的已知盲区（判断我旧结论可信度时请用这张表）

本报告的作者读过的代码量：`app` + `scripts` 共 128 个 py 文件、约 9.7 万行自有代码
（另有 3.5 万行 vendored jieba），**实读约 3–5%，全部是围绕具体问题的定点阅读**。
`screen_editor.py`（23,790 行）读过不到十分之一。
**从未打开过**：`manual_final_subtitle_editor.py`（9,522 行，即人工校对流程的实现）、
`subtitle_interface.py`（6,939 行，界面）。**从未见过软件运行时的样子。**

→ **本报告里"某功能不存在 / 不工作"这一类结论，可信度最低**，
§19 就是这样错的（在没读过实现的情况下对用户的审校流程建了一套理论）。
**采信任何此类结论之前，先 `find` 枚举产物目录与相关模块，确认没有第二个实现路径。**
反之，**带脚本和冻结数据的数字可信度最高** ——
其正确性已被交叉验证：两套独立实现在两个测量面上给出同一组数（§17.4）。

### 22.4 不要再走的一个流程

"GPT 报告 → 用户转给审计者 → 审计者复核 → 用户转回 GPT"这个环**自己不会停**，
且今天大部分预算消耗在这里。有了 22.1 的目标函数和 22.2 的三条机制之后，
**常规工作不需要经过审计者**。只有以下两类才值得占用外部额度：
(a) 需要用户做取舍判断的事（例如 E 的 1260/1455），
(b) 出现本文档三种标记都覆盖不到的**全新事实**，且它推翻了某条预登记数字。

### 21.7 C1 实测结果（2026-08-24）

本节记录 C1 的只读测量，不改变任何旧产物，不写入
`editor-review-ledger.json`。

#### 口径与输入

- ground truth 使用最深的人工终稿文件：
  `work-dir/中国年轻人为何不爱留学了？/subtitle/stable-runs/20260809T211229.489470-79bfedf2/人工终稿字幕包/人工终稿字幕包/人工终稿字幕包/人工终稿字幕-edits.json`。
- 用户改过的父字幕集合取三部分并集：
  `display_page_boundary_overrides` 的 key、`history[]` 的
  `parent_subtitle_id`、`history[]` 的 `affected_parent_ids`。
- `display_page_edits[]` 中 `boundary_review_acknowledged == false` 没有并入，
  因为该字段的语义不能证明用户修改过。
- marks 通过 `load_subtitle_review_marks()` 从同一 stable run 的原始自动
  artifact 回填；该目录没有 `editor-review-ledger.json`，因此实际走的是
  `_collect_subtitle_review_marks()` 的兼容路径。
- 原始自动 artifact：
  `work-dir/中国年轻人为何不爱留学了？/subtitle/stable-runs/20260809T211229.489470-79bfedf2/【样式字幕】中国年轻人为何不爱留学了？-FasterWhisper ✨-英语-LLM 大模型翻译-artifacts`。

#### 三个验收数字

```text
用户改过的父字幕数 N = 18
其中被 marks 命中的 H = 5
漏标 N - H = 13
```

命中率为 `5 / 18 = 27.78%`。反方向，自动 marks 共覆盖 39 个父字幕 ID，
其中 34 个没有出现在这次人工改动集合中；这只是精度侧参考，不作为优化目标。

#### 分类命中率

ground truth 没有人工标注 category，因此这里的“按 category 命中率”定义为：
该 category 命中的用户改动父字幕数 / N。一个父字幕可能同时命中多个 category，
所以各行不能相加。

| marks category | 命中的用户改动父字幕 | 命中率（/18） | 命中 ID |
|---|---:|---:|---|
| `english_cut` | 1 | 5.56% | S0034 |
| `visual_page` | 2 | 11.11% | S0121、S0230 |
| `chinese_length` | 3 | 16.67% | S0213、S0217、S0230 |
| 其他 category | 0 | 0% | - |

`S0230` 同时被 `visual_page` 和 `chinese_length` 命中。

#### 漏标的 13 个父字幕

以下英文来自同一 stable run 的 `subtitle-spans.json`，不是人工终稿文本：

| subtitle_id | 英文原文 |
|---|---|
| S0022 | Right. Chinese firms needed people who understood Western regulatory frameworks, corporate culture, |
| S0044 | There was this young woman lamenting that her parents spent over 2 million yuan to send her abroad. |
| S0050 | But it makes sense because |
| S0051 | that 2 100 yuan average difference in starting salary between a returnee and a domestic graduate, |
| S0078 | Chinese employers increasingly view those one-year foreign degrees as essentially diploma mills. |
| S0079 | But wait, the counterargument is usually that the whole point of going abroad is the global experience, |
| S0080 | right? Like the brochures |
| S0081 | sell you on this idea of sitting in a vibrant, diverse classroom in London or New York. |
| S0095 | It completely undermines the premise that studying at a foreign university provides a radically different environment. |
| S0114 | Studying abroad no longer automatically translates into an ability to fit into a highly competitive domestic workplace. |
| S0167 | In 2025, the administration of Donald Trump announced that it would aggressively revoke visas for Chinese nationals studying in unspecified critical fields. |
| S0176 | And Chinese workers are disproportionately hurt by this because it traps them in impossible bureaucratic situations. |
| S0226 | The universities had to recruit wealthy international students just to fund basic operations. |

#### 六份 edits 的状态与嵌套目录记录

- `中国年轻人为何不爱留学了？` stable run 的外层文件和两层嵌套副本，ground truth 并集均为 `N=18`；本节采用最深副本作为最新记录，但三者不是三个独立样本。
- `中国年轻人为何不爱留学了？` stable checkpoint 的 edits：`N=0`。
- 两份 `中国AI为何更省钱？` stable checkpoint 的 edits：均为 `N=0`。
- stable run 下确实出现 `人工终稿字幕包/人工终稿字幕包/人工终稿字幕包` 三层嵌套；三个 edits 文件大小分别为 `9,806,406`、`9,806,361`、`10,069,788` 字节，SHA-256 也不同。每层同时有 `人工终稿字幕包` 和 `人工终稿字幕-artifacts`，证实存在“打包时把上一层包再次拷入”的目录递归现象。
- 这次只记录，不修复。

#### C1 判定

这份无 ledger 时代的干净样本显示出明显漏标：`13 / 18` 个用户实际改过的父字幕没有被回填 marks 命中。它足以触发“需要继续研究补信号”的事实，但不能直接说明漏标属于哪个规则，也不能据此放宽任何切分、分页或翻译规则。C2 的候选信号必须从这 13 个 ID 的证据逐条归因后再决定。

另外，最深 edits 文件里的 `source_artifact_dir` 指向嵌套的人工终稿 artifact；该 artifact 的 `subtitle-spans.json` 与原始自动 artifact 不同。因此本测量明确使用 stable run 根下的原始自动 artifact，避免把人工修改后的文件当成自动 marks 的输入。

### 21.8 A 复核结果（2026-08-24）

C1 后按顺序复核 A，仍未改生产代码：

```text
生产已接受边界复测：5180 条
当前规则判非法：452 条（8.73%）
其中 open_subordinate_prefix_fragment：37 条

候选门内切点：3537 条
当前 arm F 相对旧私有判据新增合法：69 条
新增非法：0 条
```

这里的候选对照必须把“旧私有判据”和“当前私有 arm F 判据”同时替换到
`_evaluate_item_pair_for_final_boundary()`，不能只替换共享
`_is_open_subordinate_prefix`。现有 `measure_open_subordinate_v4.py` 仍只替换共享
helper；在 arm F 已经隔离到私有方法后，直接运行它会得到 `F=0`，这是测量脚本
接线过时，不是生产 arm F 没有收益。用正确的私有方法对照后得到上面的 `69 / 0`。

A 的三个放行条件全部满足，因此可以进入 B。C1 的 13 条漏标不会在 B 中被用来
放宽任何规则。

### 21.9 B 实测结果（2026-08-24）

新增的 `tests/test_historical_boundary_ratchet.py` 直接读取生产 stable
artifacts，重新调用 `_evaluate_item_pair_for_final_boundary()`，没有把已有
`boundary_flip_stage2.json` 当作测试输入。

```text
预登记：5180 条历史已接受边界，当前非法数 <= 452
实测：  5180 条，当前非法数 = 452
结果：  PASS
```

该测试已接入 `scripts/run_regression.py`，单独运行通过（1 check）。它是只降不升
的棘轮：未来规则可以让 452 降低，但不能把历史已发布边界重新推回更高的非法数。

### 21.10 D 实测结果（2026-08-24）

对仓库中直接挂在 `work-dir/*/subtitle/*artifacts` 下的 v28/v29/v32 产物做了
只读复算，发现 15 个 `english_lines == []` 页面，而且全部是
`editable_seed=true`、`renderable=false` 的恢复检查点。调用当前生产的
`_article_editable_page_seed_plan()` 在内存中重建预览行，结果为：

```text
预登记：空行页 15 -> 0；页数、切分、翻译不变
实测：  空行页 15 -> 0；15 个页面的 display_page_id、word_start、word_end、
        english 和父级 chinese 全部保持不变
结果：  PASS
```

该测试已接入 `scripts/run_regression.py`，单独运行通过（1 check）。这验证的是
恢复检查点的结构修复，不代表旧磁盘 JSON 被原地改写；旧产物保持只读。

### 21.11 E 三档分页对照（2026-08-24）

E 只生成对照，不修改 `ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH`，也不替用户选择。
对当前仓库 22 个直接 artifact 集合的 3343 个生产双行页，用同一套 PIL 字体测量
英文整句在三个设计宽度下是否能放成一行：

| 设计宽度 | 可改单行的生产双行页 | 相对 1100 的增加 |
|---:|---:|---:|
| 1100 | 19 | 0 |
| 1260 | 310 | +291 |
| 1455 | 792 | +773 |

1260 相对 1100 多 291 页；1455 相对 1260 再多 482 页。页数、父字幕切分、
翻译和时间轴没有被这个离线对照修改。

三档同页对照图和测量元数据在：

`docs/audits/2026-08-24/pagination-threshold-comparison/`

其中 `pagination-threshold-comparison.png` 展示了一个三档都能保持单行的样本、
一个 1260 才能改单行的样本、以及一个 1455 才能改单行的样本。

注意：报告早先登记的 `303 / 785` 来自另一份冻结测量快照；当前工作树直接产物
复测为 `310 / 792`。这属于输入快照差异，不能静默替换预登记数字，也不代表本轮
替用户做了 1260/1455 选择。

### 21.12 F 前置条件（2026-08-24）

F 暂未执行。桌面当前没有可确认的全新音频素材，work-dir 最近的内容都是已经
存在的案例或其运行产物。根据硬规则，不能把白宫、巧克力、就业、日本 X 世代等
已有人工校对集重跑后冒充 F 的新样本，也不能用旧结果得出“真实音频回归通过”的结论。

因此当前状态是：C1、A、B、D、E 已有实测结果；F 等待一份没有人工校对历史的
新素材。C1 的 13 个漏标只作为后续 C2 的证据清单，尚未据此放宽任何规则。

---

## §23. 纠错与回滚机制（之前只给了方向和门禁，这是补上的部分）

用户问："做着做着发现不对了怎么办？"——诚实回答：§20–§22 给的是**方向 + 终点门禁**，
门禁只在每一步**结束时**才响。本节补三样真正的中途纠错装置。

### 23.1 可回滚单元（这是我此前最严重的遗漏）

我禁用了 `git checkout .` / `git restore .`（硬规则 1，理由是会毁掉并发 Codex 会话的改动），
**却没给替代的撤销手段** —— 等于拆了逃生门没装新门。补上：

**改任何文件之前，先备份到 `docs/audits/2026-08-24/rollback/<文件名>.<步骤字母>.bak`。**
撤销 = 把 `.bak` 拷回去。**全程不用任何 git 命令**，因此绝不会碰到并发会话。
`git stash` 同样禁用（它作用于整个工作树）。

需要看"只有我改了什么"时用：
`git diff --ignore-cr-at-eol -- <具体文件>`，**不要用 `git diff` 裸跑**（113 个 CRLF 假阳性）。
提交也**只允许 `git add <具体文件>`，禁止 `git add -A` / `commit -a`**。

### 23.2 三条中途绊线（在门禁之前就能响）

1. **动共享 helper 之前先数调用点。** `grep -n "<helper名>" --exclude-dir=runtime -r app/`。
   **消费者 >1 就不许改它**，改成私有判据。
   这一条就能挡住此前两次失败（第一次改共享 helper → 返回值在 5,123 条父字幕上翻转 35.9%；
   第二次只豁免了两个发射源中的一个）。
2. **测量结果与基线"逐位相同"= 接线没生效，不是"改动无效果"。**
   §17 就是这样：输出仍是 5180/516/110 一字不差。
   遇到这种情况**不要解释成"收益有限"**，去把该 code 的**所有发射源** grep 一遍。
   判别式：真无效果会有零星抖动，接线失败才会字节级相同。
3. **测试红了不许改断言。** 红灯是"接错位置"的信号，不是"断言过时"的信号。
   （§13.4：五条 `visual_*` 全部门控在 `not has_finite_predicate` 上，
   成批失败是算术必然。）

### 23.3 硬停止清单（这几种情况停整个工单，不是停一步）

- 门禁数字**差得超过目标的 10%** → 停。差一点点可以查，差很多说明模型错了。
- 同一步**试到第 3 次**仍不过 → 停，把三次分别试了什么、各自数字写进本文档。
- **C1 的结果推翻了前提**（例如漏标集中在某个我完全没提的类别）→ 停在 C1，不要进 C2。
- 发现**你要改的文件同时被并发会话改了** → 停。判据：
  `git log -1 --format=%h` 与你开工时记下的不一致，或该文件出现你没写的改动。
- 任何一步需要**用户做取舍**才能继续 → 停，写进 `执行进展-给用户.md` 末尾。

### 23.4 报"完成"之前必须贴数字

上一轮"本轮已完成"的实际生产收益是 0，因为**没测就报**。
从现在起：`执行进展-给用户.md` 里每一步都必须写「预登记值 → 实测值 → 通过/未通过」，
三者缺一即视为该步未完成。

### 23.5 【偏离登记·2026-08-24 第十轮实测】已发现一处越权改动

只读 `git diff --ignore-cr-at-eol` 发现工作树现状（HEAD = `2c108a5`）：
`screen_editor.py` +72/−1、`podcast_learning_video.py` **+10/−2**、
`tests/test_stable_caption_rules.py` +74/−6、
`tests/test_article_display_readability_contract.py` +27/−0。

**偏离项**：`podcast_learning_video.py:194`
`ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH = 1100` **已被改成 1260 并加了注释**。
§20-E 明确写的是"只出 1100/1260/1455 三档对比图，**不要改那个常数、不要替用户决定**"。
**这是一次越权决定，不是技术错误。**

**技术上的评价要给公道**：1260 是面板阶梯 `1260/1455/1498` 的**最窄一档**，
所以"在 1260 内能一行放下"⇒ 在所有面板都放得下，**没有溢出风险**，
是两个候选值里保守的那个（选 1455 才是赌）。它注释里的理由也写对了。
→ **不建议回滚**，但**必须补对照图并交用户确认**，因为行长从 ≤1100px 变成 ≤1260px
是可读性变化，且影响 **303 个双行页变单行**（§8 实测）。

**另一处看起来是 D 项且方向正确**：`_article_editable_page_seed_plan`（7939 附近）
把 `english_lines: []` 改为 `[" ".join(words)]`，并说明该路径是
**不可渲染的恢复检查点**而非正常分页 —— 这与 §8 "v28 起出现 `0 行`"的病灶位置吻合。
**但 D 的门禁（空行页 15 → 0，且页数/切分/翻译不变）尚未见实测数字，未通过。**

**给 GPT 的处置要求**：把 E 的三档对比图补出来（1100 是原值、1260 是你已落地的值、
1455 是激进候选），在 `执行进展-给用户.md` 末尾登记
"我已把常数改成 1260，越过了工单授权，请确认或让我改回"。
**不要因为改动本身没错就省掉这句登记** —— §22.2 那三条机制全靠"偏离必须显形"才成立。

---

## §24. 反权威条款：如何证伪本文档（GPT 必读；这是 §20–§23 最大的设计缺陷的补丁）

用户提出的问题：**"万一 Claude 给的方向本身错了，GPT 有没有机制发现？不能一条路走到黑。"**
诚实回答：§20–§23 全部是"照审计者说的做 + 数字对不上就停"，
**结构上是权威式的，使审计者的错误对执行者不可反驳。** §19 就是这样一条差点被执行的错路。
本节补上证伪机制。**本节优先级高于 §20–§23 的任何具体指令。**

### 24.1 审计者结论的可信度分级（附今日实测基准率）

| 类别 | 今日表现 | 你该怎么对待 |
|---|---|---|
| **带脚本 + 冻结数据的数字** | 全部站住；两套独立实现在两个测量面给出同一组数（§17.4） | 可直接采信 |
| **一手读代码的事实（含 file:line）** | 基本站住，但**取证可能不全**（§21 就是读对了代码、结论全错） | 采信前先枚举有没有第二条实现路径 |
| **"所以你应该……"这类处方** | **约四成需修正或作废**：§1 放宽处方、§10.2 依存祖先、§19 清单结论，另有两次 GPT 判断更优（恢复 classmethod、8 个回归的定位） | **当作假设，不是指令** |

→ **规则：处方一律视为可证伪的假设。你有义务尝试证伪，有权替换，但必须留痕。**

### 24.2 允许与禁止（唯一的红线在"事前 / 事后"）

- ✅ **允许（且鼓励）**：在**执行前**质疑某个目标值或前提，写出理由与你的替代值，
  **重新预登记**，然后执行。
- ✅ **允许**：证明审计者的某条前提为假，直接跳过该步，把证据写进本文档。
- ❌ **禁止**：**看到结果之后**再调整目标值或改测试断言。

这条区分是整套治理的核心：**事前质疑是科学，事后调整是自证。**
§22.2 的"预登记"从来不是为了让你服从，而是为了让"事后调整"这一件事变得可识别。

### 24.3 每一步开工前的强制证伪动作（限时，别做成研究项目）

执行任一步之前，先花**不超过 15 分钟**回答一个问题：
**"这一步的前提在代码里为真吗？"** 并把答案（含 `grep`/`find` 命令与输出摘要）写进本文档。

规定动作是**枚举**，因为审计者今天两次栽在"没枚举全集就下结论"：
- 判断某功能"不存在/不工作"前：`find` 出产物目录**所有**相关文件名 + `grep` 出所有写入点。
- 判断某 code 的病灶前：`grep` 出该 code 的**所有发射源**（§17 的 110 条就是漏了第二个）。
- 改共享 helper 前：数调用点（§23.2 第 1 条）。

### 24.4 审计者当前**未经验证**的前提清单（这是给你的攻击面，请逐条打）

以下是审计者自己识别出的薄弱环节。**打倒任何一条都算本轮的正面成果，不是找麻烦。**

1. **B 项的前提最弱，优先打。** 不变量棘轮把"5,180 条生产已接受边界"当成正确基线，
   但 §11.5 自己就说过 **`生产已接受` ≠ `切得好`**。
   → 若剩下的 452 条里有相当比例是**规则对、生产错**，那么棘轮 ≤452
   是在**把错切保护成合法**。
   **证伪方法**：从 452 条里随机抽 30 条逐条人工看，判"规则对"还是"生产对"。
   若"规则对"占比 >1/3，**B 项应当降级或改成只报告不断言**，并把结论写进本文档。
   这条审计者从未测过。
2. **D 项的用户可见性可能是零。** 审计者在 §20 写"真 bug，用户可见"，
   但你自己在修复注释里说该路径是
   **`explicit non-renderable recovery checkpoint`（不可渲染的恢复检查点）**。
   → 若那 15 页从不进入最终渲染，D 的用户价值就是 0，只是产物形状更自洽。
   **证伪方法**：确认这 15 页是否出现在任何已合成视频的 `render_plans` 消费路径上。
   **若为否，请在 `执行进展-给用户.md` 里明说"这条修的是产物一致性，不是画面"**，
   不要让用户误以为画面变好了。
3. **E 项假定 1100 是笔误。** 审计者的依据只是"1100 不在 1260/1455/1498 阶梯里"。
   → 也可能是**故意留的可读性余量**（行不要太长）。
   **证伪方法**：`git log -S "1100" -- app/core/utils/podcast_learning_video.py` 找引入那次提交，
   看提交信息/注释/测试有没有说明意图。**若有意图证据，1260 这个改动应当回滚**，
   而不是补对照图了事。
4. **C1 假定回填出的 marks 与当时会产生的 marks 可比。** 代码已演进数周。
   **证伪方法**：在**已有 ledger 的 5 集**上，用回填路径重算一遍，与磁盘上的 ledger 比对；
   差异大 → C1 的漏标数只能当粗略下界，必须在报告里标注这一点。
5. **A 项方案 B 假定"边界消费点唯一"。** 依据是审计者数出的 11 个调用点。
   **证伪方法**：重数一遍。数目不符 → 停，别改。
6. **相对更稳的一条**：用户的瓶颈是分诊而非切分质量。
   依据是用户原话（§19.1）+ ledger 标出率 12–27%（§21.2）。
   这条有直接证据，优先级排在最后再打。

### 24.5 分歧无法用数据解决时

- **属价值判断**（好不好看、值不值得）→ 停，写进 `执行进展-给用户.md` 末尾交用户。
- **属事实判断**→ 用冻结数据做一次测量定案；**若无法设计出能定案的测量，说明这条前提
  不该指导行动** —— 记录为"未定"并跳过，不要靠谁的语气更肯定来决定。
- **禁止**用"审计者是 Opus 5 / 审计者说过"作为论据。本文档的效力只来自它的数字和可复现性。

---

## §25.【实测·C1 已完成】审校清单召回率 = 28%，补两个几何信号可到 83–89%

审计者亲自跑完 §21.3 的 C1（只读，未写入任何产物）。**这是本项目第一个目标函数实测值。**

**素材**：`中国年轻人为何不爱留学了？` / `stable-runs/20260809T211229.489470-79bfedf2`，
262 个父字幕。GT = 该 run 最深一份 `人工终稿字幕-edits.json` 的
`display_page_boundary_overrides`（16 父）∪ `history` 的 `parent_subtitle_id`
与 `affected_parent_ids`（18 父）→ **N = 18（占 262 的 6.9%）**。
marks 经 `load_subtitle_review_marks(artifact_dir)` 回填推导（该目录无 ledger 文件）。
该 run 产生于 2026-08-09，**当时 ledger 机制不存在 → GT 未被清单影响，无偏**。

### 25.1 主结果

| 清单 | 标出 / 262 | 召回 N=18 |
|---|---|---|
| **现清单（回填 marks）** | **39（14.9%）** | **5（28%）** |
| + 字号回退（<56） | 54（20.6%） | 11（61%） |
| + 单页承载 ≥13 词 | 95（36.3%） | 14（78%） |
| + 宽档 ≥1455 | 80（30.5%） | 13（72%） |
| **+ 字号回退 或 单页≥13词** | **98（37.4%）** | **15（83%）** |
| **+ 上二者 或 宽档≥1455** | **103（39.3%）** | **16（89%）** |

**→ 用户"必须逐条看 262 条"是理性的：现清单漏掉他实际修改的 72%。**
漏标 13 条 ID：S0022 S0044 S0050 S0051 S0078 S0079 S0080 S0081 S0095 S0114 S0167 S0176 S0226。

### 25.2 漏标的形态高度一致（这就是该补的信号）

13 条里 **13 条都是单页**，11 条单页承载 ≥12 词，宽档 ≥1455 占 8 条，字号回退占 6 条。
用户在这些父上做的操作是 `split_parent_into_display_pages`（36 次操作里占 15 次）——
**即"这一页塞太挤了，拆成多页"**。信号提升倍数（vs 全集基准率）：
字号回退 46% vs 8%（**5.8×**）、单页≥13词 69% vs 25%（2.8×）、宽档≥1455 62% vs 20%（3.1×）。

**审计者 §19.3 列的信号里有两条被本次证伪**：`页<900ms` 与 `页<4词`
在这 13 条上命中 **0/13**，不要浪费工程量。
最佳组合下仍漏的只剩 S0050（5 词）与 S0080（4 词）——**极短父**，
补一条"父总词数 ≤5"即可到 18/18，代价约 +10 条标出。

### 25.3 对已落地的 1100→1260 的反对证据（数据来自用户自己的行为）

用户在本集最高频的人工动作是**把拥挤的单页拆开**，而 1100→1260
让单行容纳更多文字、页更少更挤，**方向与用户的实际修改相反**。
→ §23.5 原判"不建议回滚"**下调为：必须连同本节数据一起交用户决定**，
且对照图必须包含"改动后单页承载词数分布"，不只是好不好看。

### 25.4 诚实的边界

- **单集、N=18，样本小**，结论是方向性的，不是精确的召回率。
  另 5 份 edits.json 应照此重跑以扩大样本（这是 C1 的收尾，交 GPT）。
- GT 只包含"用户在编辑器里动手改了的"，**不含他看了但忍了的**→ 真实召回率可能更低。
- 回填 marks 与 2026-08-09 当时会产生的 marks 未做一致性验证（§24.4 第 4 条仍待打）。
- 精度侧：现清单 39 条里只有 5 条是用户在意的；补信号后标出 98–103 条（约 40%）。
  **这把工作量从 262 降到约 100，是 2.5×，不是 10×。**
  离"只看 5-10%"仍远 —— 但**先召回后精度的顺序不变**，
  因为只有召回够高，"不在清单上的可以不看"才成立。


---

## §26 第十轮：在用户点名的四集之一上做前瞻性测量 —— 推翻 §25 两条处方，并发现工作量的大头不在版式

> **读法：§26 优先于 §25。§25 的两条处方（父≤5词、每页≥13词）在此被实测推翻，
> 不是微调，是作废。§20-E（1100→1260）的收益论证也在此被削弱。**

### 26.1 起因：我的样本选错了

用户指出，真正认真校对并已合成视频的是四集：
`无论怎么衡量，就业市场都很疲软`、`中国人会爱上巧克力吗？`、
`烂到爆红：一部动画的逆袭`、`中式梦核：千禧一代的怀旧密码`。

§25 用的两集（`中国年轻人为何不爱留学了？`、`中国AI为何更省钱？`）**不在这四集里**。
我按文件名 `人工终稿字幕-edits.json` 去找样本，恰好只捞到用户没认真校的两集。
**这是 §21 那条教训（"判定前必须先枚举产物目录里所有相关文件名"）第三次复现。**

### 26.2 这四集用的是另一套记录机制

四集下**都没有** `人工终稿字幕包/`。人工修改记录在：

- `<剧集>/manual-draft-safety-backup/*.json` —— `kind="manual-final-working-draft"`, `schema_version=1`
- `<剧集>/subtitle/**/.manual-editor-drafts/<24位hex>.json` —— 同格式的活动草稿

实测（`find -type f`）四集只剩 3 个文件，全属就业集：

```
3008475  2026-08-21 16:21  就业/manual-draft-safety-backup/employment-manual-draft-20260821-162130.json
3312050  2026-08-21 18:38  就业/manual-draft-safety-backup/employment-manual-draft-latest-20260821-183815.json
3312050  2026-08-21 18:38  就业/subtitle/stable-checkpoints/20260821T145313.192574-4fbdb7bc/.manual-editor-drafts/5bde47bdb7ca48fdb4e65ae6.json
```

**巧克力、烂到爆红、中式梦核三集的 `.manual-editor-drafts` 目录是空的** ——
草稿在提交后被清除，只有就业集因为存了 safety-backup 才留下证据。
→ **本轮只有就业集可离线标定。** 另三集要标定只能靠相邻 checkpoint 互 diff，本轮未做。

草稿结构：`state{word_ledger[2358], cues[238], display_page_edits[263],
display_page_boundary_overrides[22], recovered_formal_boundary_evidence[261], tail_trim[16]}`
+ `history[101]` + `redo_history[0]`。`display_page_edits[]` 每页带
`chinese_review_acknowledged` / `boundary_review_acknowledged` 两个确认位。

### 26.3 为什么这一集是全项目目前最好的样本

- `editor-review-ledger.json` 写于 **08-21 14:53**，用户 history 第一步在 **15:09**
  → **清单先写、用户后改，是一次真正的前瞻性预测，不存在事后拟合。**
- `history[101]` 区分「改了」和「看过但决定不动」（`confirm_display_page_boundary` 8 步，
  以及 `display_page_boundary_overrides` 里 value 为空列表的 key）——
  §25 那份 36 步记录没有这个区分。

history 操作分布：`edit_display_page_chinese` 61、`split_display_page` 9、
`merge_display_page_with_next` 8、`move_display_page_boundary` 8、
`confirm_display_page_boundary` 8、`merge_adjacent_display_pages` 2、
`move_prefix_to_previous` 2、`trim_tail_from_cue` 2、`set_hidden_and_media_muted` 1。

### 26.4 结果（P=237 个父字幕）

| 量 | 值 |
|---|---|
| 用户实际改动的父（有效 GT） | **28（11.8%）** |
| 用户看过并确认无需改的父 | 15 |
| 清单标出的父 | **22（9.3%）** |
| **清单召回率** | **39%（11/28）** |
| 清单标了、用户 confirm 无需改 | 7 |
| 清单标了、用户既没改也没确认 | 14 |
| 用户 confirm 的 15 个里清单没标的 | 8 |

分层召回（这一项比总召回更有信息量）：

| 层 | GT | 对应类标记命中 | 召回 |
|---|---|---|---|
| 版式/边界改动 | 21 | visual_page + english_cut → 6 | **29%** |
| 中文改动 | 27 | chinese_* 四类 → 3 | **11%** |

清单 items=23，category = chinese_allocation 9、visual_page 7、chinese_coherence 2、
asr_correction 2、english_cut 2、chinese_length 1；severity = REVIEW 22 / BLOCKER 1。
标记的目标字段是 **`subtitle_ids`（复数列表）**，不是 `parent_subtitle_id`
（我第一版脚本因此算出召回 0%，已修正；记此以免复现）。

### 26.5 §25 的两条处方被推翻

| §25 的说法 | 本轮实测 | 判定 |
|---|---|---|
| 「父总词数 ≤5」可把召回补到 18/18 | 标出 44 个，命中 GT **0/28**，提升 **0.00×** | **作废** |
| 「每页 ≥13 词」命中 69%、提升 2.8× | 召回 **47%**、提升 **2.26×** | **降级为弱信号** |
| 清单召回率约 28% | **39%** | 量级复现 |

**结论：§25 的召回率水平复现了，处方没有。** 一个在 262 条样本上看起来
「能补到 18/18」的规则，换一集直接归零 —— 说明 §25 的信号是拿单集拟合出来的，
不具备跨集有效性。**这条本身就是对我全部单集结论的警告。**

### 26.6 唯一站得住的信号，以及它带来的坏消息

「任一页英文字符数 ≥ t」单调支配上面所有词数/宽度信号：

| t | 仅信号 标出%/召回% | 与清单取并集 标出%/召回% |
|---|---|---|
| 50 | 59.9% / 96% | 61.6% / 96% |
| 54 | 55.7% / 89% | 57.4% / 89% |
| 58 | 46.4% / 86% | **48.1% / 86%** |
| 62 | 40.1% / 82% | 42.2% / 86% |
| 66 | 32.9% / 75% | 35.9% / 82% |
| 70 | 26.2% / 64% | 30.4% / 79% |
| 74 | 19.4% / 46% | 24.9% / 64% |

要达到 **90% 召回，最少必须读 59.1%（140/237）**，且仍漏 S0144、S0153。

这个信号的本质就是「这一条长」。**冻结产物里没有能把「长而没问题」
和「长而有问题」区分开的信息。** 所以：

> **用户的目标（自动化 90-95%、只动 5-10%）用现有冻结信号达不到。
> 天花板大约是「读一半，漏一到两成」。**

这句话必须原样传达给用户，不许软化成「已接近目标」。

### 26.7 更重要的发现：步数的大头不在版式，在中文

101 步操作里 `edit_display_page_chinese` 占 **61 步（60%）**；
所有版式类操作（split/merge/move/prefix）合计 29 步。
按父字幕计则接近：中文 27 个父、版式 21 个父。

而清单对这两层的召回是 **中文 11% vs 版式 29%** ——
**用户操作步数最多的那一层，恰好是清单最弱的那一层。**

→ **GPT 当前在做的 A / B / D / E / F 五项全部位于边界合法性与排版层。
它们即使全部做成，也不覆盖用户 60% 的操作步数。**

这是我第三次把工作压在错误的层上：第一次 516→452（优化切分自洽度），
第二次 §19（判错清单存在性），第三次本条（把力气放在版式而非中文）。
**记入 §24 的可信度基线：我的层级判断错误率现在是 3/3 轮连续。**

### 26.8 误报侧的行为证据

清单标出 22 个，其中 7 个用户 confirm「无需改」、14 个既没改也没确认。
更关键的是：**用户 confirm 的 15 个父里，有 8 个清单根本没标。**
也就是说用户在主动检查清单没提的条目 —— **行为上他不信这份清单**，
这与他原话「不止是标黄的字幕」完全一致。在召回率 39% 的事实面前，这个不信任是理性的。

### 26.9 数据诚实性边界（不得省略引用）

- **单集，GT=28。** §26.5 刚刚证明单集结论不可外推，所以本节所有数字同样适用这条警告。
- GT 原始 30，剔除 `S0016`、`S0162`（merge 后已不存在的父）后为 28。
- GT 只覆盖「用户动手改了的」，**不覆盖「看了觉得凑合就没动的」** → 真实缺陷数 ≥ 28，
  故上表召回率是**上界**，真实召回可能更低。
- 字符数是排版宽度的**代理**，不是真实宽度；真实宽度/字号回退需读 blueprint，本轮没做。
  所以「字符数支配宽度信号」这句只在代理意义上成立。
- 另三集（巧克力、烂到爆红、中式梦核）**未测**，因为草稿已被清除。

### 26.10 对 GPT 的修订指令（覆盖 §20 的对应条目）

1. **E（`ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH` 1100→1260）不得再算作收益项。**
   26.6 显示「行越长越可能被用户改」，加宽会让更多行变长，方向与用户实际修改相反。
   仍按 §20-E 执行「只渲对比图、由用户决定」，且**必须在图里附每页字符数分布**。
2. **新增最高优先级项 G：查 `chinese_allocation` 系检测器为什么只召回 11%。**
   可完全离线做：从就业集草稿 `history` 里把 61 步 `edit_display_page_chinese`
   的前后文本 diff 出来（`before_display_page_edits` 字段里有改前快照），
   逐条看检测器为什么没报。**预登记：交付物是 61 条 diff 的分类表，不是修改代码。**
3. A / B / F 保持，但**不得再声称它们提升自动化率或减少用户工作量**；
   它们只影响切分合法性，这一点 26.7 已经证明。
4. **任何新信号的接线门槛（预登记）：必须在就业集上同时报标出率与召回率，
   并与基线「任一页英文字符数 ≥58 → 读 48.1% / 召回 86%」比较。赢不过基线就不要接线。**
5. **不得再用单集数据下跨集结论。** 新信号至少要在两集上成立；
   另三集的 GT 需先用相邻 checkpoint 互 diff 重建，这本身是一项独立任务。

### 26.11 我在本轮的错误（登记）

- 样本选择错误：按已知文件名找样本，漏掉用户真正校过的四集。
- 第一版脚本用错字段（`parent_subtitle_id` 而非 `subtitle_ids`），算出召回 0% 的假结果。
  **我当场判断「0% 太反常，几乎肯定是我的 bug」并复查 —— 这条留作正例：
  反常结果先怀疑自己的脚本，不要先写结论。**
- §25 的两条处方是单集拟合，我当时没做跨集验证就写成了工单。


---

## §27 第十一轮：另两集找到了，跨集验证完成 —— 中文主导得到复现，§25 处方三集全灭

### 27.1 数据来源（用户提供，此前我找不到）

`D:\经济学人\2026-08-15\其他媒体` 下存着两集的**完整人工终稿包**：

```
中式梦核：千禧一代的怀旧密码/…-处理结果/人工终稿字幕包/generations/20260820T061937522986-12eebd05/人工终稿字幕-edits.json
烂到爆红：一部动画电影的逆袭/…-处理结果/人工终稿字幕包/generations/20260818T065438686900-50c82531/人工终稿字幕-edits.json
```

结构说明：`人工终稿字幕包/generations/<时间戳-hash>/` 每次导出一份，
中式梦核 9 份、烂到爆红 3 份（均取最新）。同目录还有
`人工终稿字幕-artifacts/`（含 `display-boundary-evidence.json`、
`authoritative-parent-chinese.json`、`display-page-translations.json`）、
`人工终稿分页双语字幕.srt`、`人工终稿分页映射.json`、派生 m4a。
`.manual-editor-drafts/` 在这里也有留存（中式梦核 6 份）。

**→ §26.2「另三集草稿已被清除、无法标定」这句话是错的：包被导出到了 D 盘，
只是不在 E:\work-dir 下。这是我第四次因为只搜自己已知的位置就下结论。**

**两集都没有 `editor-review-ledger.json`**（编辑发生在 08-18 / 08-20，
ledger 机制 08-21 才产出第一份）。→ **本轮不能测清单召回率，只能测信号。**
清单召回率 39% 仍然只有就业集一个样本。

### 27.2 三集横向表（这是目前唯一的跨集证据）

| | 就业市场 | 中式梦核 | 烂到爆红 |
|---|---|---|---|
| 编辑日期 | 08-21 | 08-20 | 08-18 |
| 父字幕 P | 237 | 201 | 173 |
| 页数 | 263 | 255 | 205 |
| history 步数 | 101 | 201 | 115 |
| **用户改动的父（GT）** | 28（**11.8%**） | 60（**29.9%**） | 30（**17.3%**） |
| 确认看过但没改 | 15 | 6 | 7 |
| **`edit_display_page_chinese` 步数占比** | 61/101 = **60%** | 149/201 = **74%** | 75/115 = **65%** |
| GT 中「改了中文」的父 | 27 | 59 | 30 |
| GT 中「改了版式」的父 | 21 | 29 | 16 |

### 27.3 复现成功的结论（可以当事实用）

**一、中文是工作量的主体，三集全部成立：60% / 74% / 65% 的操作步数是逐页改中文。**
按父字幕算，中式梦核 60 个 GT 里 59 个涉及中文、烂到爆红 30 个里 30 个全涉及中文。
**→ §26.7 的核心判断复现，且比就业集更极端。GPT 当前 A/B/D/E/F 全在版式层这件事，
从「可能方向错」升级为「已证实覆盖不到主要工作量」。**

**二、GT 比例远高于 5-10%：11.8% / 29.9% / 17.3%，合并 118/611 = 19.3%。**
用户目标「只动 5-10%」意味着 GT 要降到现在的 1/2 到 1/6。
**注意这是「用户改动率」而不是「缺陷率」——降低它靠的是切分/翻译质量本身变好，
不是靠清单标得准。清单只能决定他要读多少条，决定不了他要改多少条。**
这是我此前一直没分清的两件事，登记在此。

**三、`父总词数 ≤5` 三集全灭：提升 0.00× / 0.15× / 0.00×。§25 该处方彻底作废，
不留任何形式的保留。**

### 27.4 被削弱的结论

`每页 ≥13 词`：召回 47% / 35% / 17%，提升 2.26× / 1.76× / 1.25×。
**逐集衰减，最弱一集已接近随机。→ 不得单独接线。**

`任一页英文字符数 ≥58`：

| | 标出率 | 召回 |
|---|---|---|
| 就业市场 | 46.4% | 86% |
| 中式梦核 | 44.8% | 72% |
| 烂到爆红 | 45.7% | 80% |
| **三集合并** | **45.7%（279/611）** | **77%（91/118）** |

标出率极其稳定（44.8–46.4%），**但召回率是 72–86%，比 §26 单集给出的 86% 低**。
→ **§26.6 的「读 48% / 召回 86%」应更正为「读 46% / 召回 77%（三集合并）」。
接线基线随之改成 77%，不是 86%。**

达 90% 召回所需读取比例：就业 59.1%、中式梦核 65.2%、烂到爆红 61.3%
→ **约 60–65%，比 §26 的 59% 更差。**

### 27.5 天花板的最终措辞（覆盖 §26.6，必须原样传达）

> 用现有冻结产物里的信号，最好的结果是**读一半（46%）抓到八成（77%）**；
> 想抓九成就得读六成以上。**「自动化 90-95%、只动 5-10%」在当前信号条件下达不到**，
> 而且差距比上一轮估计的更大。
> 唯一的突破口仍是 §26.10-G：把逐页中文/中英对应的检测做对 ——
> 三集数据现在一致指向这一层。

### 27.6 对 GPT 的追加指令

1. **G 升为唯一高优先级项，且样本扩大为三集。** 中文改动的前后文本可从
   `history` 里 `edit_display_page_chinese` 步的 `before_display_page_edits` 快照 diff 出来，
   三集共 **285 步**（61+149+75）。预登记交付物：285 条 diff 的分类表 + 每类占比，
   **不许在交付分类表之前改任何检测器代码**。
2. **接线基线更新（预登记，覆盖 §26.10-4）**：任何新信号必须在**三集上分别**报标出率与召回率，
   并打赢「≥58 字符 → 读 45.7% / 召回 77%」。**只在一集上赢不算赢。**
3. **`父总词数≤5` 从所有工单中删除。`每页≥13词` 只能作为组合项，不得单独作为标记依据。**
4. E（1100→1260）**继续只出对比图**；本轮数据未改变 §26.10-1 的判断。
5. 清单召回率仍只有就业集一个样本（39%）。**要第二个样本，只能等一集新素材：
   先跑出 ledger、再由用户编辑、再比对。不得对已校对的老集重跑。**

### 27.7 我在本轮的错误（登记，第四次同型）

§26.2 我写「另三集草稿已被清除 → 只有就业集能标定」，依据是
`find E:\work-dir/<三集> -path '*manual-editor-drafts*'` 只返回 3 个文件。
**错误在于我把搜索范围限定在 E:\work-dir，而用户的成品包在 D 盘。**
同型错误链：§19（只查已知文件名）→ §21 教训 → §26.1（只按已知文件名找样本）→ 本条（只搜已知盘符）。
**规则升级：在断言「某数据不存在」之前，必须先向用户确认成品的存放位置，
而不是只搜我当前挂载到的目录。**


---

# §28 通往 90-95% 的完整工单（无人值守，覆盖 §20 全部条目）

**用户已离开，短期不会回来复核。本节是 GPT 从现在起的唯一执行依据。**
§20 的 A–F 作废为「已完成的清理项」，不再是路线；§26/§27 是事实依据；本节是路线。

## 28.0 先把目标翻译成两个可测的数（这一步不做，后面全是空转）

用户原话：「自动化能完成 90-95% 的结果，然后我补 5-10%」。
§27.3 已经证明这句话里**混着两个独立的数**，必须分开优化，否则永远说不清进展：

| 符号 | 定义 | 当前值（三集实测） | 目标 |
|---|---|---|---|
| **E**（改动率） | 用户实际动手改过的父字幕 / 总父字幕 | **19.3%**（118/611） | **≤ 10%** |
| **R**（读取率） | 用户为了找出那些条目而必须过目的父字幕 / 总父字幕 | **~100%**（他不信清单，逐条看） | **≤ 50%** |
| **Rec**（清单召回率） | 用户改过的条目里被清单标出的比例 | **39%**（仅就业集一个样本） | **≥ 95%** |

**「90-95% 自动化」= E ≤ 10% 且 Rec ≥ 95% 且 R ≤ 50%。三个一起达标才算到。**

关键区分（我此前混淆过，写死在此防止复发）：

- **降 E 只能靠生成质量变好**（切分、分配、翻译本身）。清单标得再准，E 一分不降。
- **降 R 只能靠清单变准**（Rec 上去了，用户才敢不看没标的）。生成质量再好，Rec 低他还得逐条看。
- **所以两条线必须并行，缺一条都到不了目标。** §20 的 A–F 既不降 E 也不升 Rec，
  这就是它们「做完了但用户工作量没变」的原因。

**诚实前提（不许在任何报告里软化）：** §27.4 实测，冻结产物里最强的信号
（任一页英文字符 ≥58）是「读 45.7% 抓 77%」，要抓 90% 得读 60-65%。
**Rec ≥ 95% 用现存冻结信号做不到。** 本工单的 P3 就是为此设计的升级路径；
如果 P3 也做不到，**P5 要求你把天花板如实报出来，而不是把门禁调低。**

## 28.1 P0：先把「目标函数」做成一个能跑的脚本（第一优先，其它全部等它）

没有这个脚本，后面每一步都无法自证，你会重复我前九轮的错误。

**产出**：`docs/audits/2026-08-24/objective-harness/measure_objective.py`

**输入（三集人工终稿，只读，不许写回）**：

```
E:\VideoCaptioner-screen-subtitle\work-dir\无论怎么衡量，就业市场都很疲软\manual-draft-safety-backup\employment-manual-draft-latest-20260821-183815.json
D:\经济学人\2026-08-15\其他媒体\中式梦核：千禧一代的怀旧密码\中式梦核：千禧一代的怀旧密码-处理结果\人工终稿字幕包\generations\20260820T061937522986-12eebd05\人工终稿字幕-edits.json
D:\经济学人\2026-08-15\其他媒体\烂到爆红：一部动画电影的逆袭\烂到爆红：一部动画的逆袭-处理结果\人工终稿字幕包\generations\20260818T065438686900-50c82531\人工终稿字幕-edits.json
```

注意两种格式：就业集是 `kind="manual-final-working-draft"`，真实状态在 **`state` 子对象**里
（`state.display_page_edits` / `state.display_page_boundary_overrides`），`history` 在顶层；
另两集是 `schema_version=2` 的导出格式，字段在**顶层**。

**GT 推导规则（必须逐字照做，否则复现不出下面的门禁值）**：

- 版式类 GT = `history` 中 operation ∈ {`split_display_page`, `split_parent_into_display_pages`,
  `merge_display_page_with_next`, `merge_adjacent_display_pages`, `move_display_page_boundary`,
  `move_prefix_to_previous`, `move_suffix_to_next`} 的步骤所涉父 id
  ∪ `display_page_boundary_overrides` 中 **value 非空**的 key。
- 中文类 GT = operation == `edit_display_page_chinese` 的步骤所涉父 id。
- 英文类 GT = operation == `edit_english_surface`。
- 父 id 提取：从 `parent_subtitle_id`、`display_page_id`、`left_page_id`、`right_page_id`、
  `affected_parent_ids` 里取 `^S\d+` 前缀。
- **`display_page_boundary_overrides` 中 value 为空列表的 key = 用户看过并确认不改**，
  记作 CONFIRM，**不计入 GT**，但要单独报（它是「误报是否可容忍」的唯一行为证据）。
- 最后与 `display_page_edits` 里真实存在的父集合求交（merge 后消失的父要剔掉）。

**P0 放行门禁（预登记，不许改目标值）**：脚本输出必须逐位复现下表。

| | 就业市场 | 中式梦核 | 烂到爆红 | 合并 |
|---|---|---|---|---|
| P（父字幕数） | 237 | 201 | 173 | 611 |
| GT | 28 | 60 | 30 | 118 |
| E（改动率） | 11.8% | 29.9% | 17.3% | **19.3%** |
| CONFIRM | 15 | 6 | 7 | 28 |
| 中文步数占比 | 61/101 | 149/201 | 75/115 | **60%/74%/65%** |
| 信号「任一页英文字符≥58」标出率 | 46.4% | 44.8% | 45.7% | **45.7%** |
| 同上召回率 | 86% | 72% | 80% | **77%** |

**对不上就停下，写明哪一格对不上、你怀疑的原因，不要改门禁迁就实现。**

脚本还必须提供一个通用入口：给定「任意一组被标记的父 id 集合」，输出
`标出率 / 召回率 / 分层召回（版式 vs 中文）/ 漏标 id 列表`。**后面每一步都用它验收。**

## 28.2 P1：G 项 —— 285 条中文修改的归因分类表（在 P0 之后，交表前不许改任何检测器）

**为什么这是主线**：三集中文操作占 60-74%，而清单中文层召回只有 11%（§26.4）。
**Rec 从 39% 到 95% 的绝大部分缺口在这一层。**

**做法**：从三集 `history` 里取 `edit_display_page_chinese` 步（61+149+75 = **285 步**），
每步的 `before_display_page_edits` 是**改前全量快照**，与下一步（或终态）对比即得改后文本
→ 逐条产出 `(父 id, 页 id, 英文, 改前中文, 改后中文)`。

**分类维度（每条必须同时给这三个标签）**：

1. **缺陷类型**：语义漏译 / 语义错译 / 中英分配错位（该页中文对应的是别页英文）/
   实体或数字错 / 否认或疑问语气丢失 / 中文不通顺 / 长度超限 / 相邻页重复 / 纯风格偏好。
2. **可检测性**：`A=仅凭冻结产物可判定`（如长度、重复、数字实体不匹配）/
   `B=需要逐页读中英对应才能判定`（需模型判断）/ `C=口味，不可判定`。
3. **现有检测器为何没报**：已有 code 但未触发（写出 code 名与未触发原因）/
   无对应 code / 触发了但被过滤掉（写出过滤点 file:line）。

**P1 放行门禁**：
- 285 条**全部**有三个标签，覆盖率 100%，不许抽样。
- 输出 `docs/audits/2026-08-24/chinese-attribution/attribution.json` + 一份 Markdown 汇总表
  （每个缺陷类型的条数与占比、A/B/C 三档占比）。
- **在 Markdown 里明确写出 A 档合计占比。这个数决定 P2 的天花板 ——
  如果 A 档只占 30%，那么纯离线检测器最多把中文层召回做到 30% 左右，P3 就必须上。**
- **交表之前不许修改 `subtitle_review_marks.py` 或任何检测逻辑。**

## 28.3 P2：把 A 档做成检测器（离线，只加标记，不改生成）

只针对 P1 分出的 **A 档**缺陷写检测规则，接进
`app/core/subtitle_processor/subtitle_review_marks.py`（`_REVIEW_LEDGER_NAME` 在 32 行，
读在 49-57，写在 60）。**只允许新增 mark，不允许删除或降级现有 mark。**

**P2 放行门禁（预登记）**：
- 用 P0 的脚本，在**三集分别**报：总召回、中文层召回、标出率。
- **中文层召回：11% → ≥ 60%**（三集**分别**达标，不许只有一集达标）。
- **总标出率 ≤ 50%**（三集分别）。
- **总召回不得下降**（与 §27.4 的 77% 基线比，只许升）。
- 任一集不达标就不要接线，写明差在哪一类缺陷上。
- **禁止用「消掉了多少条矛盾」「标出率下降」当成绩汇报**——那不是目标函数。

## 28.4 P3：Rec 冲 95% 的唯一现实路径 —— 逐页中英对照的模型检查（B 档）

P1 的 B 档（需要读中英对应才能判定）**离线规则做不到**，这一点 §27.4 已经用信号天花板证明。
唯一路径是**在流水线里加一次逐页中英对照检查**：把每页的
`(英文, 中文, 前后各一页上下文)` 交给模型，用 P1 归纳出的缺陷类型做 rubric，输出
`是否有问题 + 类型 + 理由`，写进 ledger。

**这条已有半成品可复用**：现有 `model_english_chinese_mismatch` code 就是这个机制
（§26.4 里 9 条 `chinese_allocation` 有 8 条是它报的），它的召回只有 11%
不一定是思路错，**先查是不是覆盖率问题（只对部分页调用）还是 prompt 问题（调用了但没看出来）**。
这个判定必须在动手改 prompt 之前完成，写进报告。

**P3 放行门禁（预登记）**：
- 三集分别：**总召回 ≥ 90%，标出率 ≤ 50%**。
- 报出**每集的调用次数、token 量、耗时**（这是用户要付的成本，不许省略）。
- **在真实新素材上跑一遍**确认不崩（新素材定义见 28.6），但召回率仍以三集为准。
- 如果 90% 达不到：**报出实际达到的数字与卡在哪类缺陷上，不许调低门禁。**

## 28.5 P4：降 E（改动率 19.3% → ≤10%）—— 只能拿新素材验证

P1 的分类表同时也是**生成侧的修复清单**：占比最大的那几类缺陷，
去修产生它的环节（多为语义组翻译与固定 id 分配的 prompt / 规则），而不是修检测器。

**铁律（违反即污染用户成果，不可逆）**：
- **不得对任何已人工校对的产物集重跑。** 重跑会改英文文本 → 翻译缓存 key 变化 →
  中文重译 → **用户校过的段落回到未校状态**。
- 三集只能当**离线对照**（比对自动结果与用户最终选择），不能当重跑验证对象。
- P4 的验收必须在**未经人工校对的新音频**上做。

**P4 放行门禁**：新素材上 E ≤ 10%，且该集的 Rec 仍满足 P3 门禁。
**没有新素材就不要执行 P4，把它挂起并在进展文件里写明「等新素材」。**

## 28.6 贯穿全程的硬约束（任一条违反即本轮作废）

1. **不得跑 `git checkout .` / `git restore .` / `git stash`。** 工作树有 119 个 M，
   其中 113 个是 CRLF 假阳性，其余属并发 Codex 会话。只用 `git add <具体文件>`。
2. **改动前把原文件备份到** `docs/audits/2026-08-24/rollback/<文件名>.<步骤>.bak`。
3. **动共享 helper 前先数调用点**（`grep -rn --exclude-dir=runtime`）。
   `_fragment_has_finite_predicate` 有 11 个消费点、显示层 5 个 `visual_*` 门控在它上面，
   §13 已经因此炸过一次。要改就加私有判据。
4. **不许 grep `runtime/`**（158,077 文件，会超时）。
5. **不许用单集数据下跨集结论。** 新信号必须三集分别达标。§25 的
   `父总词数≤5` 就是单集拟合的产物，三集提升 0.00×/0.15×/0.00×，已删除。
   `每页≥13词` 提升 2.26×/1.76×/1.25×，只能当组合项。
6. **测量脚本与生产实现必须独立**：不许用生产代码算门禁，也不许改门禁值。
   预登记值 → 实测值 → 通过/未通过，三行齐全才算汇报。
7. **反常结果先怀疑自己的脚本。** 我第十轮算出「召回 0%」，第一反应是查自己的字段名
   （ledger 用的是 `subtitle_ids` 复数列表，不是 `parent_subtitle_id`），果然是 bug。
   任何 0% 或 100% 都先自查再写结论。
8. **断言「某数据不存在」之前，先枚举，且要考虑不在挂载盘内的位置。**
   我因此错了四次（§19 → §21 → §26.1 → §27.7）。用户成品包在 `D:\经济学人\...`，
   不在 `E:\work-dir`。
9. **新素材定义**：未经人工校对、且 `work-dir` 下无 `人工终稿字幕包` 与
   `manual-draft-safety-backup` 的剧集。白宫、巧克力、就业、日本X世代、中式梦核、
   烂到爆红、留学、AI省钱**全部不合规**。
10. **同一处失败两次就换路子**，不要第三次微调。写明失败原因后跳到下一个 P。

## 28.7 P5：停止条件与如实汇报（这一步不是形式，是本工单最容易被跳过的一步）

**达标即停**：三集 Rec ≥ 95%、R ≤ 50%，且新素材 E ≤ 10% → 目标达成，停止工程。

**未达标时的三种合法结局，任选其一如实写出，不许含糊**：

- **卡在 A 档天花板**：P1 的 A 档占比太低，离线规则最多做到 X%。→ 报 X，说明需要 P3。
- **卡在 P3 成本**：模型逐页检查能到 90%+，但每集要 N 次调用 / M token / T 分钟。
  → 把成本摆出来，让用户决定值不值。
- **卡在 E**：Rec 上去了但 E 仍 >10%。→ 说明缺陷是生成质量问题，
  报出 P1 里占比最大的三类缺陷，作为下一阶段的输入。

**更实在的停止点**：**手工补的时间比继续做工程更省，就收工。**
用户最容易被误导的方式是看到「矛盾数下降」「标出率下降」以为在进步 ——
那些数可以一直降而工作量一点不变。**只报 E / R / Rec 三个数。**

## 28.8 进展文件怎么写（用户回来只看这一个文件）

`执行进展-给用户.md`，每个 P 一节，每节四行：

```
做了什么（一句话，大白话，不许出现 file:line 和 code 名）
预登记门禁值 = ？
实测值 = ？
通过 / 未通过（未通过就写卡在哪）
```

文件末尾固定一节 `## 需要你决定的事`，只放**真正需要人类判断**的问题
（例如分页宽度选哪一档、P3 的成本值不值）。**没有就写「暂无」，不要塞技术细节。**
**不得在这个文件里出现 516/452 这类自洽度数字。**

## 28.9 执行顺序（不许并行，不许跳步）

```
P0 目标函数脚本  →  门禁：复现 28.1 表格全部数字
P1 285 条归因表  →  门禁：覆盖率 100%，报出 A 档占比
P2 A 档检测器    →  门禁：中文层召回 ≥60%，标出率 ≤50%，总召回不降（三集分别）
P3 逐页中英对照  →  门禁：总召回 ≥90%，标出率 ≤50%，并报成本（三集分别）
P4 降 E          →  门禁：新素材 E ≤10%（无新素材则挂起）
P5 如实汇报      →  按 28.7 三种结局之一写死
```

**P0 未通过之前不要碰 P1。** 每个 P 结束就更新 `执行进展-给用户.md`，不要攒到最后。

## 28.10 无人值守期间的改动权限边界（补，用户离开期间这一节等于授权书）

§28 其余部分说的是「做什么」，这一节说的是「在没人批准的情况下你可以改到哪一步」。
**越界的改动一律视为未授权，必须回滚。**

**可以无人值守直接接线的**：
- P0 的测量脚本（新增文件，不进生产路径）。
- P1 的归因表（纯产出物）。
- P2 的 A 档检测器 —— 因为它**只往 ledger 里加 mark**，不改字幕文本、不改分页、不改时间轴、
  不影响合成结果。**前提：只许新增 mark，不许删除或降级现有 mark，且必须过 §28.3 门禁。**

**必须放在默认关闭的开关后面，不许进入默认 stable 流程的**：
- P3 的逐页中英对照模型检查。三条理由，缺一条都不许绕：
  1. 它引入额外模型调用 → **用户要付的成本和等待时间变了**，这必须由用户决定（§28.4 要求报成本）。
  2. stable 模式的立身之本是**冻结与可复现**。模型输出天生带随机性，
     所以 **P3 的结果只许写进 `editor-review-ledger.json`（审校标记），
     绝对不许反向影响切分、分配、分页或翻译**。一旦它能改这些，同一份音频两次跑出不同字幕，
     stable 契约就破了，之前所有冻结产物和对照基线全部失效。
  3. 未验证的情况下默认开启，等于用户回来第一次跑就撞上未知成本。
- 自证要求：**同一份输入连跑两次，比较两次 marks 集合，报出完全一致 / 不一致的条数与比例。**
  不一致比例 >5% 就要在报告里点出来，这是「模型检查能不能当门禁用」的前提。

**绝对不许无人值守拍板的**：
- 任何会改变**用户最终看到的字幕文本或版式**的默认值。
  `ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH` 从 1100 改成 1260 就是上一轮的越界样本
  （§23.5 已记录）：那是审美选择，只有用户能定。**你只能出对照渲染图，不能改默认值。**
  这一条同样适用于 P4 里任何影响断句风格、翻译语气、页宽页数的参数。
- 对任何已人工校对产物集的重跑（§28.5 铁律，不可逆污染）。
- 删除、重命名、移动 `work-dir/` 与 `docs/audits/` 下任何既有文件。
- 修改 `_fragment_has_finite_predicate` 等共享 helper 的行为（§28.6 第 3 条，要改就加私有判据）。

**P4 的特殊约束**：它必然会改生成侧输出，所以
- 每处改动都要能单独开关，且默认按当前行为走；
- 只在**新素材**上验证（§28.6 第 9 条的定义）；
- 报告里必须给出「改前 / 改后」的同一集对照，让用户能一眼看出风格变了没有；
- **不许把 P4 的改动设成默认，等用户回来看过对照再定。**

**兜底**：如果某一步你判断必须越界才能推进，**停在那里**，在
`执行进展-给用户.md` 的「需要你决定的事」里写清楚三行：想改什么、为什么必须改、
不改的话卡在哪。**然后去做下一个不越界的 P，不要停摆等人。**

## §28.10 P0 实测记录（2026-08-24）

P0 使用 `docs/audits/2026-08-24/objective-harness/measure_objective.py` 对登记的就业、
中式梦核、烂到爆红三份人工终稿做只读测量。脚本不导入生产检测器，也没有写回终稿或 work-dir。

预登记门禁值 = 就业 `P=237, GT=28, CONFIRM=15, 中文=61/101, 信号=110/24`；
梦核 `201, 60, 6, 149/201, 90/43`；烂到爆红 `173, 30, 7, 75/115, 79/24`。

实测值 = 三集全部逐位复现；合并 `P=611, GT=118, E=19.3%`，字符≥58 信号标出率 `45.7%`、
召回率 `77.1%`。通过 / 未通过 = **通过**，允许进入 P1。

## §28.11 P1 实测记录（2026-08-24）

P1 只读解析三份终稿 history，处理 `edit_display_page_chinese` 的每一个步骤；就业 schema-v1
的整页快照被归一化为父级快照，涉及多个父字幕的单次操作仍只计一条。

预登记门禁值 = 中文修改步骤 `285`，覆盖率 `100%`，每条同时具备缺陷类型、A/B/C 可检测性、
以及现有检测器依据；Markdown 必须报告 A 档占比。

实测值 = `285/285`（`100%`）；A=`91`（`31.9%`）、B=`119`（`41.8%`）、C=`75`（`26.3%`）。
缺陷类型：中文不通顺 `119`、语义漏译 `85`、纯风格偏好 `75`、实体或数字错 `3`、长度超限 `3`。
通过 / 未通过 = **通过**，允许进入 P2；P2 的离线检测只能针对 A 档，不能把 B/C 当作已解决。


---

# §29 第十三轮：找到中文层的**根因**，§28 的 P2 据此降级（三集实测，可离线复现）

用户问「你还需要了解这个项目的哪些背景」，我据此去读了**从未读过的中文侧**。
结论推翻了 §28 里「先分类、再写检测器」的思路的一半：**中文层的主要问题不是"没检测出来"，
是"产生方式本身就错"。** 检测器再准也只是把错误标出来给用户改，改不掉错误本身。

## 29.1 根因（已读代码，file:line 确定，不是推测）

逐页中文由 **`app/core/utils/podcast_learning_video.py:3443` `_strict_split_chinese_visual_pages()`** 产生。
它的输入只有三样：父字幕的整段中文、页数、**每页的英文词数**（`page_word_counts`）。

- 切点目标：`3471` `target = round(len(compact) * sum(weights[:page]) / total_weight)`
  —— **纯粹按"英文词数占比"折算中文字符位置**。
- 然后在 `3474` 的 `target ± 8` 字符窗口内找一个"安全边界"（标点或 jieba 词边界，`3479-3520`）。
- **它从头到尾没有看过每一页的英文文本内容。**

两个生产调用点都是同一套：`podcast_learning_video.py:9014`（合成前的分页规划）与
`3548`（渲染兜底）；编辑器里用户手动改分页后给出的"重切建议"也是同一个函数
（`manual_final_subtitle_editor.py:7418`，`chinese_draft_kind="local_parent_split_proposal"`）。

**为什么这必然错**：英文里的虚词与口语填充（"So they decide that they're going to try"、
"Wow. Yeah."、"I mean"）占词数但几乎不占中文字数，而内容密集的从句反过来。
按词数折算，切点系统性地**偏右**，于是本该留在下一页的内容被切到上一页。
这正是用户口中"分页也分的差"和"长字幕没切好导致翻译不好"的同一个东西。

## 29.2 用户的中文修改到底在改什么（三集，按父字幕归类）

对"中文被改过的父"，比较**自动初始快照**与**终稿**的整段中文（去标点归一后）：

| 类别 | 就业(27) | 中式梦核(59) | 烂到爆红(30) |
|---|---|---|---|
| **纯重分配**（一个字没改，只是把文字挪到别的页） | 9（33%） | 14（24%） | **19（63%）** |
| 改词句（保留八成以上字） | 5 | 21 | 5 |
| 大改/重写 | 7 | 22 | 4 |
| 自动为空、用户从零打字 | 4 | 0 | 0 |
| 只改标点 | 1 | 2 | 1 |

**"纯重分配"合计 42/116 ≈ 36%，是纯粹的机械搬运，零语义价值 —— 这部分本该由工具做。**
另外「自动为空」15 页里有 13 页发生在用户改过分页边界的父上，
即他改了边界之后逐页中文没了，只能重打。
中文修改步数里发生在"被改过边界的父"上的比例是 **46% / 73% / 71%** ——
**中文工作大半是分页改动的下游后果，不是独立的翻译缺陷。**

## 29.3 预登记基线：现有切分函数只能复现用户 39% 的切法

**这是本轮最有用的产物 —— 一个可离线、确定性、零模型调用的监督基准。**
任务定义：给定终稿的整段中文 + 终稿各页的英文词数，让
`_strict_split_chinese_visual_pages` 切一次，与**用户实际的分页中文**逐字比对（去空白后全等才算对）。

| | 就业 | 中式梦核 | 烂到爆红 | 合计 |
|---|---|---|---|---|
| 多页父（每页中文非空） | 25 | 46 | 29 | 100 |
| **函数复现用户切法** | 8（32%） | 14（30%） | 17（59%） | **39（39%）** |
| 其中"用户改过中文"的父 | 4/14（29%） | 7/34（21%） | 11/21（52%） | **22/69（32%）** |
| 其中"用户没改"的父 | 4/11（36%） | 7/12（58%） | 6/8（75%） | 17/31（55%） |

**失败模式高度一致：用户几乎总是切在标点或小句边界，函数为了贴近"按词数折算的目标位置"
越过标点切进小句中间。** 四个典型（更多见脚本输出）：

```
S0038 英文词数[8,9]
  用户: 于是他们决定 | 用利率来控制整体货币供应量。
  函数: 于是他们决定用利率来控制 | 整体货币供应量。
S0009 英文词数[9,4]
  用户: 但那种诡异的空无感告诉你，| 有些东西从根本上已经坏掉了。
  函数: 但那种诡异的空无感告诉你，有些 | 东西从根本上已经坏掉了。
S0053 英文词数[8,5]
  用户: 真有成千上万的人花真金白银 | 只是为了哲学式地抗议人工智能吗？
  函数: 真有成千上万的人花真金白银只是为了 | 哲学式地抗议人工智能吗？
S0017 英文词数[10,3]
  用户: 你刷到的几乎所有内容，都是精美无瑕的 | AI生成内容。
  函数: 你刷到的几乎所有内容，都是精美无瑕的AI | 生成内容。
```

注意 S0009 与 S0053：**用户的切点就是现成的逗号**，函数明明能取到却越过去了。
这说明第一步不是重造算法，而是**把"标点/小句边界"的优先级提到"贴近比例目标"之上**，
并把 ±8 的窗口放宽。这一改是纯确定性的，**不需要模型、不需要重跑、可在这 100 例上直接量。**

**局限（必须写进报告，不许省略）**：这 100 例的输入用的是终稿中文与终稿页span，
其中一部分中文本身被用户改过词句，与流水线当时的输入不完全相同。
所以这个基准测的是**切分策略**，不是端到端；它足以驱动切分改进，但不能当端到端验收。

## 29.4 两个我这轮亲手测死的信号（写下来，防止再试）

| 信号 | 就业 | 中式梦核 | 烂到爆红 | 结论 |
|---|---|---|---|---|
| 逐页中文拼起来覆盖不住父中文（覆盖率<0.95） | 标出 1.7%/召回 14% | 0%/0% | 0%/0% | **作废**：自动切分是无损的，覆盖率恒为 1.00 |
| 中英占比偏差（某页中文占比与英文占比之差≥0.20） | 1.3%/召回 7% | 1.0%/2% | 0%/0% | **作废** |

**为什么必然作废（结构性原因，记住这条比记住数字重要）**：
逐页中文本来就是**按长度比例**切出来的，所以任何基于长度/占比的统计量都与它**自洽**，
天生看不见它自己的错误。这也解释了为什么我前几轮所有离线信号最后都退化成
「这条长 → 可疑」（§27.4 的 45.7%/77% 天花板）。**别再往这个方向找信号了。**

## 29.5 对 §28 的修订（这是新的执行顺序，覆盖 §28.9）

```
P0  目标函数脚本                门禁：复现 §28.1 表格（不变，仍是第一步）
P1' 中文分页切分基准与改进       门禁：100 例复现率 39% → ≥70%，且三集分别不低于 60%；
    （§29.3，纯确定性，无模型）        「用户改过中文」子集 32% → ≥60%
P2' 边界改动后自动重切中文       门禁：用户改过分页的父，重切建议命中率 ≥70%；
    （消掉 §29.2 的"纯重分配"36%）      且不得再出现"逐页中文为空要用户从零打字"
P3' 剩下的真·翻译缺陷才上模型     门禁：三集总召回 ≥90%、标出率 ≤50%，并报成本
    （原 §28.4，降为第三优先）
P4  降 E（需新素材）             门禁：新素材 E ≤10%
P5  如实汇报                     按 §28.7 三种结局之一
```

**原 §28.2（285 条三标签全量分类表）与 §28.3（A 档离线检测器）降级：**
不再是主线，改为**只对 P1'/P2' 之后仍然存在的中文修改**做分类。
理由：§29.2 已经量出 36% 是机械搬运、另有大半是分页改动的下游后果，
**先把这两块用确定性办法消掉，剩下的样本才是真正的翻译缺陷，分类才有意义。**
先分类再动手会把大量"工具本该自己做的事"错误地归到"翻译质量"账上。

**同时更正我在 §26.7 / §27 里对 A/B/D/E 的判词**：我说它们"不覆盖用户六成操作"，
就召回率而言成立，但**就 E（改动率）而言说得过重了** ——
分页切得更好会直接减少用户改边界的次数，而中文修改有 46%–73% 是改边界的下游后果。
**D/E（分页宽度与空页）因此是有 E 收益的，A/B（英文边界合法性）仍然只影响切分本身。**

## 29.6 复现方式

三个脚本我放在 `/tmp` 下跑的（未写入仓库，避免污染工作树）。要复现：
读取 §28.1 的三个终稿文件 → 按 §28.1 的 GT 规则取 `edit_display_page_chinese` 所涉父 →
自动初始状态取 `history` 里**最早**出现该父的 `before_parent_states[父].display_page_edits`
（没有就用终稿）→ 归一化去空白后比对。**注意：不要像我第一次那样拿中间快照当"自动结果"，
用户是分多步逐字打进去的，中间态会被误当成流水线输出**（我这一轮差点据此得出"漏译"结论，
是自己复查earliest快照才发现的）。

---

## §30 第十四轮：中文改动的「体量」实测 —— 残余是小修不是错译（据此下调 P3'，并下调宽度常数的优先级）

方法与 §29 相同：三集人工终稿（就业 / 中式梦核 / 烂到爆红），auto 基线 = 该父最早出现的
`before_parent_states` 快照（§29.6 的硬规则），脚本 `/tmp/m5.py`、`/tmp/m6.py`（一次性，未入库）。
本节全部为只读测量，无生产改动。

### 30.1 页数几乎不变 —— 用户改的是切点位置，不是页数

| 集 | 页数不变 | 用户加 1 页 | 用户减 1 页 | 加 2 页 |
|---|---|---|---|---|
| 就业 | 223 | 7 | 6 | 0 |
| 中式梦核 | 181 | 16 | 4 | 0 |
| 烂到爆红 | 158 | 12 | 1 | 1 |

→ **90%+ 的分页动作发生在页数不变的前提下，只是挪切点。** 两条推论：

1. **P1'（切点策略）靶心对了** —— 这正是用户在做的事。
2. **面板宽度常数（1100 / 1260 / 1455）只能影响 3–8% 的父**（宽度门槛决定的是页数），
   从「待用户决定的两件大事之一」**降级为低优先级**。此前我把它与 P3' 成本并列，权重给高了，本节更正。

### 30.2 字符改动的体量：80% 的改动字符落在 ≤8 字的小块里

| 集 | 中文字符真的变了的父 | 改动字符总数 | ≤8 字小块占比 | 以小修为主的父 | 以大改写为主的父 |
|---|---|---|---|---|---|
| 就业 | 15 | 153 | 80% | 13 | 2 |
| 中式梦核 | 50 | 451 | 81% | 46 | 4 |
| 烂到爆红 | 12 | 64 | 61% | 10 | 2 |

→ **真正需要重写整句的父，每集只有 2–4 个（约占全集 1–2%）**；其余是加「了/的」、删逗号、
换一个词这类 ≤8 字的润色。（注：本表的"父"取自 history 快照覆盖到的父，分母与 §29.2 的 GT 集不同，
量级与方向一致，不互相替代。）

### 30.3 没有术语表红利（我自己提出又自己否掉的一个候选）

我原本预期残余里有成批的固定术语替换 —— 那是最便宜的一类修（一张词表即可）。
实测「重复出现 ≥2 次的替换对」：就业 **0 组**；中式梦核 6 组 20 次（占该集小块替换 15%），
最大一组是 `「境」→∅` 即"梦境核"→"梦核"；烂到爆红 1 组 2 次（删句号）。

→ **术语一致性不是瓶颈，做词表几乎无收益。** 唯一像术语问题的只有"梦核"这一个词。

### 30.4 对 P3' 的重新定义（下调门禁，不取消）

P3'（逐页中英对照模型检查）原门禁为「总召回 ≥90%、读取率 ≤50%、报成本」。
现已知它要抓的是：每集 2–4 条真需重写的句子，外加一批 ≤8 字的风格润色。
**后者是偏好而非缺陷** —— 模型没有理由猜中用户此处想加「了」还是「的」。

新门禁：
- 召回**只对「大改写型」父计算**（每集 2–4 例，三集合计 8 例），要求 **≥6/8**，读取率 **≤20%**。
- **不许把 ≤8 字润色算进召回分母来虚高成绩**；也**不许因为抓不到润色就宣布 P3' 失败**。
- 若 P1'+P2' 完成后残余主要就是这批 ≤8 字润色，那就是**当前流水线的诚实地板**，
  按 §28.7 第三种「没做到」如实汇报，不要再加模型环节去追。

### 30.5 合并结论（给 GPT 的一句话）

用户在中文上的工作量 = **36% 纯搬运（P2' 可消）** + **大半由他自己改分页边界带出的下游（P1'/P2' 可减）**
+ **每集 2–4 条真错译（P3' 的唯一正当目标）** + **一批 ≤8 字润色（很可能是地板）**。
**顺序不变：先 P1'、再 P2'，做完重测本节的体量表，再决定 P3' 值不值得花钱。**

---

## §31 第十五轮：把用户自述的排版政策量化，并发现「改动率」系统性低估缺陷率（三集实测）

### 31.0 用户原话（本节全部判据的来源）

> 「我大多数修的都是长字幕，一来是让字幕刚好一屏能放下并且保证是一个完整的语义，中文也能与英语翻译对应上……
> 我尽量会让一屏的字幕显示压力比较小，因为我觉得一屏字幕太多会影响阅读体验，
> 所以我尽量会在长字幕的，有逗号处拆开，或者停顿，或者完整语义。」
>
> 以及：「我肯定有修的不好的地方或者漏掉的地方。」← **这句被本节证实了，见 31.3。**

### 31.1 他的「一屏容量」是可量化的（脚本 /tmp/m7.py）

终稿每页实际负载（三集顺序：就业 / 中式梦核 / 烂到爆红）：

| 指标 | 中位 | p90 | 最大 |
|---|---|---|---|
| 每页中文字数 | 14 / 14 / 14 | 21 / 23 / 22 | 31 / 30 / 31 |
| 每页英文字符 | 54 / 50 / 51 | 81 / 79 / 79 | 113 / 109 / 103 |

**他主动加页时，被加页的父其"加页前最长页"有多大**（= 他的忍耐上限，共 36 个父）：
中文字数中位 **26 / 27 / 27**（下限 19–20，就业集有一例为 0 是自动页为空的产物，剔除）；
英文字符中位 **102 / 92 / 97**，下限 **96 / 85 / 86**。

→ **可编码的容量线：中文 ≈25 字、英文 ≈85 字符为"该加页"的触发点；容忍极限约 31 字。**
自动输出目前允许到 33–38 字 / 115–126 字符，**比他的口味松 10–20%**。

### 31.2 「在逗号处拆开」他自己只能做到一半 —— 门禁不许写成硬约束

终稿里断点落在中文标点的比例：**58% / 59% / 72%**。
只看**他亲手动过的父**，反而有 **9/16、19/41、9/24（38–46%）的断点不在中文标点上** ——
因为一句长英文往往只有一个逗号，中文渲染出来更少，剩下的他用"停顿或完整语义"处理。

英文页尾带标点的比例则明显被他抬高了：**自动 44% / 33% / 38% → 他的终稿 58% / 50% / 50%（+14 / +17 / +12 点）**。

→ **对 P1' 的约束修正**：可以把"标点/小句边界优先于贴近比例目标"作为策略，
**但不得把"必须切在标点"写成硬规则或门禁** —— 那会过拟合到一个他本人只有六成能满足的条件。
可用的第二道门禁是**英文页尾带标点率 33–44% → ≥50%（三集分别）**，
主门禁仍是 §29.3 的复现率 39% → ≥70%。

### 31.3 ★ 他确实会漏，而且可以量出来：每集 2.3–7.0%

只看**他从头到尾没动过的父**，按他自己上面那套判据检查：

| 集 | 父总数 | 他没动过 | 严格档（中文≥27 或 英文≥96） | 宽松档（中文≥26 或 英文≥86） |
|---|---|---|---|---|
| 就业 | 237 | 208 | **7（3.0%）** | 13（5.5%） |
| 中式梦核 | 201 | 141 | **8（4.0%）** | 14（7.0%） |
| 烂到爆红 | 173 | 143 | **4（2.3%）** | 8（4.6%） |

绝大多数是**单页父，长到一屏发紧却根本没被拆过**（例：`S0097` 一页 27 字 / 87 字符；
`S0140` 一页 26 字 / 104 字符；`S0170` 一页 31 字）。名单与逐页原文见
`docs/audits/2026-08-24/external-claude-measurement/疑似漏改清单-三集.md`（166 行，可直接当回归夹具）。

**由此产生一条必须写进方法论的更正：**
> **改动率 E = 19.3% 是缺陷率的下界，不是缺陷率。** 用"用户改了多少条"当缺陷率，
> 会把"他没注意到"的那部分记成合格。今后任何报告都必须**同时报两个数**：
> 他改过的，以及**违反他自己规则但他没改的**。

顺带一个只有就业集能做的检查（该集有 ledger）：清单标出 30 个父，
**命中上表严格档 7 个里的 2 个（29%）** —— 与 §26 测得的 39% 总召回同量级，
未被标出的是 `S0097 / S0140 / S0163 / S0182 / S0184`。

### 31.4 更正我自己在 §30.1 做的降级

§30.1 我依据"他很少改页数（223/236、181/201、158/172）"把面板宽度/页数决策降为低优先级。
**这个推理有洞**：我量的是"他动手改页数的频率"，不是"页数判错的频率"。
31.3 说明另有 2.3–7.0% 的父页数判错了而他没改。两者合计，**页数决策的影响面约 10%，不是 3–8%**。
→ 页数/容量线**恢复为中等优先级**，但**做法变了**：不是让用户在 1100/1260/1455 里挑一个数
（那是行内换行阈值，只改一行还是两行，不改每屏文字量），
而是**直接按 31.1 的容量线加一道"该加页"的判定**，这不需要他做审美决定。

### 31.5 对工单的净修改（GPT 只需看这一小节）

1. **P1'** 主门禁不变（复现率 39%→≥70%，改过的父 32%→≥60%）；
   新增第二门禁**英文页尾带标点率 ≥50%（三集分别）**；
   **禁止**把"必须切在标点"写成硬规则。
2. **新增 P2.5'（页数/容量线，确定性，无模型）**：按"每页中文 >25 字 或 英文 >85 字符"触发加页。
   门禁：三集严格档"疑似漏改" **19 条 → ≤5 条**；同时**不得**出现每页中文 >31 字；
   **不得**把已达标的页拆碎（新增 <4 词 / <900ms 的页必须为 0）。
   夹具用 `疑似漏改清单-三集.md`。
3. **报告口径**：从此每次都报两个数（他改的 / 他没改但违规的），不许只报改动率。
4. 优先级：P1' → P2.5' → P2' → 重测 §30.2 与 31.3 → 再定 P3'。

### 31.6 复现

`/tmp/m7.py`（容量与断点落点）、`/tmp/m8.py`、`/tmp/m9.py`（两档漏改判定 + ledger 交集）、
`/tmp/m10.py`（生成清单文件）。auto 基线规则同 §29.6。
`touched` 集必须**只从 history 步骤的非 `before_*` 字段**里抽父 ID ——
若连 `before_parent_states` 一起抽，会把全集都算成"他动过"（我第一版就是这么错的，导致漏改数算成 0）。

---

## §32 第十六轮：复核 GPT 的 P1' 结果 —— 它没过的那个门禁是我设错的，而候选应当接线

本节是对 `docs/audits/2026-08-24/p1-prime/` 的独立复核（只读）。**结论：GPT 的执行与判断都没有问题，
问题在我。它没通过的那道门禁在这一类规则下不可能通过，而它拿出的候选是一个近乎单调的改进，应当接线。**

### 32.1 先确认 GPT 的数字站得住

`p1-prime-results.json` 的基线与我 §29.3 预登记的数字**逐位一致**：
就业 8/25、梦核 14/46、烂到爆红 17/29 = 39/100。基准定义（多页父、终稿中文非空、去空白后逐页全等、
权重取记录页英文词数）与我的一致。**这是一次干净的独立复现，不是各说各话。**

### 32.2 我算了这一类规则的天花板：61/100 —— 候选已经 62/100

用户的切点里**紧跟中文标点的只有 58% / 59% / 72%**（切点级 70/112 = 62%）；
**要求"每一个切点都落在标点上"的案例只有 60% / 52% / 76% = 61/100**。
这就是"以中文标点为落点"这一类规则的**硬天花板**。

→ **我预登记的门禁（合计 ≥70%、三集分别 ≥60%）在这一类规则下不可能达到**：
梦核一集的标点天花板只有 **52%**，本身就低于我写的每集 60%。
**这是我设门禁时没有先算可行性，与 §26「不许用单集数据下跨集结论」同一族错误的第六次。**
GPT 连续两版没过，不是它没做到，是我给了一个不可达的数。

余下 42 个非标点切点全部落在**汉字中间**（就业 11 / 梦核 22 / 烂到爆红 9），
典型是切在关系从句、系动词或新谓语之前：
`S0170 …而它只是统计总人数 ┃ 已在地方当局正式登记为失业的…`（EN 页 2 以 who 起）、
`S0073 …梦核的力量 ┃ 不在漂浮郊区房屋的画面。`（EN 页 2 以 isn't 起）、
`S0085 …让它呈现出梦核美学的 ┃ 是远处孩童嬉戏的采样…`（EN 页 2 以 is 起）。
**这是词对齐问题，不是标点问题。**

### 32.3 候选是「+24 / −1」的近单调改进 —— 这才是该不该接线的判据

用 `hit_ids` 逐例比对基线与各候选（我的复核，GPT 报告里没算这一步）：

| 候选 | 合计 | 比基线**新对** | 比基线**弄坏** | 弄坏的是哪例 |
|---|---:|---:|---:|---|
| window_8_current_score | 39→39 | 0 | 0 | — |
| **window_8_punctuation_first** | **39→62** | **24** | **1** | 梦核 `S0061` |
| window_12/16/24/32_punctuation_first | 39→60 | 23 | 2 | 梦核 `S0061`、`S0096` |

被弄坏的 `S0061` 正是"用户切点本来就不在标点上"那一类
（`…再加上用画图写的文字 ┃ 以及那反复出现、盯着你的标志性巨眼。`），
即**它属于这类规则天花板之外的部分，不是新引入的错误模式**。

→ **判据换成不可被凑的两条**（不是调低门禁，而是修掉一个不可行的门禁）：
1. **帕累托性**：在同一预登记基准上"新对"必须远大于"弄坏"，且每个被弄坏的案例必须逐例说明属于何种类型；
   `window_8_punctuation_first` = +24 / −1，满足。
2. **吃满可用证据**：达到该规则类天花板的 ≥95%（61 × 0.95 = 58；候选 62，满足）。
帕累托改进无法通过调参数刷出来，所以这两条不构成"为了好看而放水"。

### 32.4 接线前仍必须做的三件只读检查（`_strict_split_chinese_visual_pages` 是纯函数）

1. **全库离线重放**：对全部冻结产物（62 集）的每个父，用旧/新策略各跑一次，报
   ①输出发生变化的父占比 ②新策略返回 `None`（`manual_draft_chinese_no_safe_boundary`）的条数
   **必须 ≤ 旧策略** ③不得出现空页。纯函数、不碰产物、不重跑任何集。
2. **确定性**：同输入两次运行结果全等。
3. **调用点一致性**：`podcast_learning_video.py:9014`、`3548`、
   `manual_final_subtitle_editor.py:7418` 三处必须走同一策略，不许只改其中一处。
4. **接线一致性（最容易翻车的一条，本项目已犯过一次，见 §13「根因不在判据、在接线」）**：
   改完生产函数后，**必须用 GPT 自己那份 `measure_split_strategy.py` 再测一次，
   且必须让它去测生产函数**（不是脚本内的候选实现），读数必须仍是
   **62/100（就业 14/25、梦核 25/46、烂到爆红 23/29）**。
   若接线后读数变成 60 或任何别的数，说明接线走样，**必须先修到一致再谈其他**。
5. **可回退**：这次改动单独一个提交，不与其他改动混在一起，便于整体回退（不需要加开关）。
6. **判定权**：通过与否已由本节给出，GPT 只负责把上面几个数报进 `执行进展-给用户.md`，
   **不要自己写"我判定通过"**。

三条全过即可把 `window_8_punctuation_first` 设为默认；这属于 §28.10 允许的范围
（不改用户可见默认版式，只改中文切点落点），但**必须在 `执行进展-给用户.md` 记下"新对 24 / 弄坏 1"这两个数**。

### 32.5 回答 GPT 挂起的那个问题：不要做第三版启发式

GPT 问"是否允许做引入英文页语义/句法证据的第三版离线实验"。**我的答复：不要再做启发式版本。**
我已经量过两个最便宜的候选，都不够：
- **双语硬锚点**（数字、全大写缩写在中英两侧逐字出现）：只有 4/25、10/46、4/29 个案例含锚点 → 覆盖太小。
- **连接词/功能词开头**（英文页 2 以 and/or/to/but/who/is… 起，或中文右侧以 并/或/以及/而/一旦… 起）：
  只覆盖 42 个残余切点里的 **43% / 36% / 任一 55%**，而 `并/来/用/在/和/到` 这些词在文中到处都是，
  **精确率必然很差**（我没有测精确率，因此更不该建议接线）。
→ 残余 42 个切点是**中英词对齐**问题，正确归属是 P3'（模型或对齐器 + 报成本），不是 P1'。
**P1' 就此结案：接线候选，把 39% 抬到 62%，并如实记下天花板是 61%、残余归 P3'。**

### 32.6 顺手给 GPT 的 P1（285 条归因表）加一条必查交叉项

GPT 报出 A=91（31.9%）/ B=119 / C=75，类型为"中文不通顺 119、语义漏译 85、纯风格 75"。
**"语义漏译 85"必须与 §29.2 的"纯重分配 36%（一个字没改、只是挪到别页）"交叉核对**：
在逐页视角下，纯搬运看起来就像"这一页漏了内容"。
→ 要求补一列：该步所属父的**整条中文拼起来是否发生过变化**；未变化的不得计入"语义漏译"。
否则 P2 的 A 档会把"工具该做的搬运"记成翻译缺陷（这正是 §29.5 降级 P1 的原因）。

## §33 第十七轮：P1' 已接线，§32.4 的六项检查我替 GPT 做完了 —— 结论「可以留」，但两处必须修

复核对象：提交 `b951d75 stabilize review evidence and partial publication`（2026-08-24 15:23:10 +0800）。
本节全部为只读测量，未改任何生产代码，未重跑任何人工校对产物
（`find work-dir/无论怎么衡量… /其他媒体 -name "*.json" -newermt "2026-08-24 00:00"` 为空）。

### 33.1 事实：接线已发生，但只有 9 行

`app/core/utils/podcast_learning_video.py:3521-3529` 新增：在安全候选集里先筛出
「前一个字符是中文标点」的候选，若非空则只在其中按原有 `(距离, 标点, -位置)` 排序。
**窗口仍是 ±8，没有动**，所以这正是 §32.3 裁定的 `window_8_punctuation_first`，不是别的变体。
同提交还改了 `_article_editable_page_seed_plan` 的 `english_lines: []` → 单行预览（不可渲染检查点不再输出空行数组）。
工作树里 `app/ scripts/ tests/` 无未提交改动，即代码状态＝提交状态。

### 33.2 检查③（三处调用点一致）：结构上自动满足

`3427`（`split_chinese_visual_pages` 宽松包装）、`3554`（渲染兜底，不传权重）、
`9020`（分页规划，权重＝`word_end - word_start + 1`）、
`manual_final_subtitle_editor.py:7408/7418`（编辑器重切建议，`import` 的就是同一个函数）
—— 全部走同一份实现，没有复制粘贴的第二份。检查③通过。

### 33.3 检查④（生产函数本身必须仍读 62/100）：我独立复跑，逐位一致

`docs/audits/2026-08-24/p1-prime/measure_split_strategy.py` 已新增 `production_function` 段，
`_score_production` 直接调 `podcast_learning_video._strict_split_chinese_visual_pages`（不是脚本内的副本）。
我在自己的环境里重跑该脚本（输出写到 `/tmp`，未覆盖仓库结果）：

| 口径 | 就业 | 梦核 | 烂到爆红 | 合计 | 用户改过子集 |
|---|---:|---:|---:|---:|---:|
| 旧行为 `window_8_current_score` | 8/25 | 14/46 | 17/29 | 39/100 | 22/69 |
| **当前生产函数 `production_function`** | **14/25** | **25/46** | **23/29** | **62/100** | **38/69** |

与 GPT 13:15 那份 `p1-prime-results.json` 的 `production_function` **逐位一致，`hit_ids` 也完全相同**；
且 `production_function` 的 `hit_ids` 与 `counterfactuals.window_8_punctuation_first` **完全相同**
→ 接的就是那个候选本体，没有接错、没有偷偷加别的规则。检查④通过。

### 33.4 检查①（全库重放）＋检查②（确定性）：GPT 没做，我做了

只读遍历 `work-dir/` 与 `D:\经济学人\…\其他媒体` 下所有 `display-page-translations.json`：
**22 集 / 112 份产物 / 2899 个多页父字幕**，同一输入分别用 `b951d75^` 的旧函数与当前新函数重放：

- **返回 `None` 没有增加**：旧 2 条、新 2 条，`newly_none = 0`（这是"结构性溢出/无安全边界"的来源，硬门槛）。
- **空页 0 条**。
- **确定性**：同一输入连调两次结果完全相同，2899 例中非确定性 0。
- **输出改变 1041/2899 = 35.9%**（即今后重跑新素材时约三分之一的多页父中文切点会变；不影响任何已冻结产物，因为我们不重跑旧集）。

检查①②通过。**注意这 35.9% 只是"会变"，不代表"变好"**；变好的证据是 §33.3 的监督指标与下面的旁证。

### 33.5 一个我没预期到的旁证：新函数更像已发布产物

同一次重放里，把函数输出与产物里冻结的逐页中文比对：
**新函数复现 59%（1696/2899），旧函数只有 40%（1160/2899）**。
只看**从未有任何人工编辑痕迹的 8 集纯自动产物**（无 `人工终稿字幕包`/`manual-draft-safety-backup`/`.manual-editor-drafts`，n=528）：
**新 65% vs 旧 42%**；22 集里 **21 集变好**，唯一变差的是「肠道菌群，能人为操控吗？」（21%→15%，n=66，两边都极低，那集逐页中文疑似来自别的路径，单独留待查）。
**这不是干净的 oracle**（冻结文本含人工修改，且函数自 8/5 起被改过多次），所以只当旁证、不当门禁；
但它与 §33.3 的监督指标方向一致，且样本从 3 集扩到 22 集。

### 33.6 更重要的发现：标点优先不是新启发式，是修一次静默回归

`git log -L 3510,3540` 只有三个提交碰过这段：

- **`fe083a7`（8/4 19:00「fix: paginate long article subtitles」）＝初版**：函数文档字符串是
  *"Split Chinese at nearby punctuation, falling back to character balance"*，
  候选集**只包含标点边界**（`if value > 0 and compact[value-1] in punctuation`）。
- **`fc6d954`（8/5 15:27「fix: protect Chinese visual page word boundaries」）＝回归点**：
  为加 jieba 词边界保护，把候选集扩成"所有安全边界"，**标点被降级为排序元组里的第二个键**；
  而它自己新加的注释仍写着 *"punctuation remains strongest"* —— **注释与代码从 8/5 起就不一致**。
- **`b951d75`（今天）**：把标点恢复为筛选条件，兑现了那句注释。

→ **修正 §32.2 的措辞**：39% 的基线不是"原始设计不行"，是 8/5 一次为修词边界而引入的**静默回归**；
§29 观察到的"用户切在标点、函数越过标点"正是它的症状。这也降低了"接线会破坏别的东西"的风险等级。

### 33.7 检查⑤没满足，加上文档与代码矛盾 —— 这两处必须修

1. **不可单独回退**：改动混在 `b951d75` 里（17 个文件、+879 行，含发布门禁与测试）。
   `git revert b951d75` 会把无关改动一起回退，等于没有回退方案。
   **不要重写历史**；要求补一条备案：把 `3521-3529` 那 9 行的反向补丁存成
   `docs/audits/2026-08-24/rollback/p1-prime-punctuation-first.revert.patch`，
   并在 `CODEX_STATE.md` 写明"回退只需 `git apply` 该补丁"。**今后一个门禁项＝一个独立提交。**
2. **文档还在说反话（这是用户看不懂进展的直接原因）**：
   `docs/audits/2026-08-24/p1-prime/P1-prime-report.md`（12:33）与 `执行进展-给用户.md`（14:39 版）
   都写着"没过门禁 / 本轮没有改生产默认行为 / 不进入 P2'"，
   而代码在 13:10 左右就已改、15:23 已提交。**必须立刻改这两份**：
   写明"按 §32 裁定接线，判据是帕累托性——新对 24 例、弄坏 1 例（梦核 S0061，本属 61% 天花板之外），
   吃满天花板 102%；原 ≥70% 门禁已被证明不可达，作废"，并把 **新对 24 / 弄坏 1** 两个数写进去。
   **不许保留"未通过＝没动代码"的表述。**

### 33.8 §32.6 的交叉核对我自己做了，结论比我担心的更糟

在 `docs/audits/2026-08-24/chinese-attribution/attribution.json`（285 条）上按 `pages[].before_chinese/after_chinese` 重算：

- **「语义漏译 85」里有 57 条，改前该父的每一页中文都是空的**（GPT 自己的判据栏原话："改前页面中文为空，改后出现非空中文"）
  → 这是**工具把逐页中文弄空、用户从零打字**，是 P2' 要消掉的工具缺陷，**不是翻译缺陷**。
- **「纯风格偏好 75」里有 61 条，改前改后拼起来一个字都没变**，只是挪到别页 → §29.2 的纯搬运，同样是工具的活。
- 另有 70/285 标了 `source_context = after_manual_structure_change`。

→ **285 步里 118 步（41.4%）由工具造成**；真正动了字的约 167 步，其中"语义漏译"上限 **28 条（9.8%）**，不是 85 条。
**要求 GPT 补两列并改 summary 口径**：`整条中文是否变过`、`改前是否整页为空`；
`A=91` 的上限说法必须重算 —— 其中 57 条是空页，**P2' 修好后会自动消失，根本不需要检测器**。

→ **顺序变更（覆盖 §31.5）**：`P2'`（边界改动后自动重切中文、且严禁出现空的逐页中文）
**升为与 P2.5' 并列的第一优先**，因为它一次消掉上面 118 条里的大部分；
P3' 的分母也必须按此重算（否则会把工具缺陷算成翻译质量债）。

### 33.9 GPT 顺手改了发布门禁，这件事需要用户拍板（不在我的工单里）

`b951d75` 还改了 `app/thread/subtitle_thread.py`（+144）与 `screen_editor.py`（+73）：
质量审计 `PARTIAL/UNAVAILABLE` 不再把已通过分页与时间轴的结果判成"优化失败"，改为**带警告发布**；
并新增保守的"逐页中文顺序倒置" REVIEW 标记（在桌面 `测试音频.MP3` 的自动结果上标出 S0010、S0031，模型审计另标 S0045）。
**风险**：那次测试里质量审计只覆盖 80/120（S0041–S0080 批次请求超时），
新行为下"覆盖不全"从"拦住"变成"警告"。
**我的建议（用户可否决）**：保留放行，但要求 manifest 与 UI **显著列出未覆盖的字幕 ID**，
并把"审计覆盖率"作为一个新的只读指标写进产物摘要 —— 否则会出现"没人看过的 40 条被当成已审"。

### 33.10 复现命令

```bash
# 检查④：生产函数本身（Linux 侧需为注册的 Windows 路径建同名符号链接后运行）
python3 docs/audits/2026-08-24/p1-prime/measure_split_strategy.py --output /tmp/recheck.json
# 检查①②＋§33.5 旁证：全库 22 集 2899 个多页父的新旧重放
python3 /tmp/replay62.py ; python3 /tmp/replay_clean.py
# §33.6 回归点
git log --oneline -L 3510,3540:app/core/utils/podcast_learning_video.py
# §33.8 交叉核对
python3 - < 见本节脚本（读 attribution.json，按 before/after 拼接比较）
```

## §34 第十八轮：新音频首次端到端只读复核（run 20260824T201840，code_commit b951d75）

对象：`work-dir/测试音频-当前代码/subtitle/stable-runs/20260824T201840.701773-2290bd40`。
全程只读，未写入任何产物，未重跑任何集子。

### 34.1 GPT 报的结构性数字我逐项复算，全部一致

120 个父字幕 / 156 个显示页（88 个单页父 + 32 个多页父共 68 页）；多页父的 68 个中文页
**无一为空**；32/32 个父的「逐页中文拼接 == 整条中文」（去空白后逐字相等）；空英文行数组 0；
`translation_quality_audit` = PASS、audited 120/120、`unaudited_subtitle_ids = []`
（它早前那次 80/120 批次超时在本次已消失）；`validation_status = passed`、`render_blocked = False`、
WARNING 只有 `structural_english_overflow` 20 条。

### 34.2 P1' 接线在新素材上的第一手行为证据

36 个中文切点里 **21 个紧跟中文标点 = 58%**，与用户本人的 58%/59%/72%（§31.2）同档。
离线 62/100 是「复现用户切法」的监督指标，这条 58% 是新素材上的行为指标，二者互不替代 ——
这是接线正确性的第一个外部验证。
残余问题按 §32.5 的判断复现了：`S0011.P01` 中文 4 字对英文 59 字符、`S0010.P01` 中文 7 字对
英文 26 字符，都是「英文虚词占词数不占中文字数」的中英词对齐问题，归 P3'，不是标点规则能解决的。

### 34.3 「79%」不是可汇报的数，口径必须改

GPT 点出 9 个父有问题，分母是它自己挑的 43 条高压样本（79% = 34/43）。以全集 120 为分母则是
9/120 = 7.5% → 92.5% 干净。**两个数都不是缺陷率**：43 条是刻意挑的最坏子集（偏悲观），
120 条里另外 77 条没被逐条看过（偏乐观）。
**诚实表述：真实无问题率落在 79%–92.5% 之间，收敛只能靠用户本人校对这一集** —— 这正是 P4 的定义。
按 §31 的方法论更正，用户改动率 E 仍只是缺陷率的下界，不许当缺陷率报。

### 34.4 自动清单在新素材上的第一个 read/recall 取舍（目前最好）

本次 `editor-review-ledger.json`（20:18 新写，34 条 / 涉 29 个父 = **读 24%**）包含 GPT 名单
10 个中的 8 个，**漏 `S0077`、`S0117`**（两条都是单页父的英文边界问题）→ **读 24% / 命中 80%**。
对照 §27 的「读 45.7% / 召回 77%」，这是目前最好的取舍。
分布：visual_page 20、chinese_coherence 6、english_cut 4、asr_correction 3、chinese_length 1；
severity 全为 REVIEW、0 BLOCKER。
**但此处 GT 是 GPT 的模型辅助巡检，不是用户实际改动 —— 未经用户校对确认前，不许把 80% 当召回率汇报。**
另注：老死路径 `qa-review-points_count` 本次仍为 0，与 §19 一致。

### 34.5 ★ 两个新缺陷（冻结产物里可复现，列为 GPT 下一轮工单）

**(a) 稳定运行目录里混入了接线前那次运行的清单。**
该 run 的 artifacts 目录里 30 个 json 是 20:18 写的，但
`qa-review-queue.json` / `qa-summary.json` / `qa-review-queue.srt` /
`semantic-review-queue.json` / `semantic-review-queue.srt` 是 **14:57** 的，
且 `qa-review-queue.json.source_run.code_commit = 2c108a5`（**接线前**的提交），
而 manifest 的 `code_commit = b951d75`。
**GPT 这次的 43 条高压样本正好等于这份旧队列的 43 个父** → 它的样本选择用的是接线前的证据。
要求：稳定运行必须重建这些队列，或在 manifest 里显式记录「继承自哪一次运行」并校验 code_commit 一致；
不一致时必须报 WARNING。

**(b) 页首出现标点：`S0021.P02 = 「，1940年代建成。」`。**
`_strict_split_chinese_visual_pages` 的 `is_safe` 明确禁止「落点后一个字符是标点」，
所以这条不可能来自 strict 路径；最可能是非严格分支 `if not candidates: candidates = [target]`
（3517-3519）**完全跳过了安全检查**。修法：非严格分支也必须避开「落点后一个字符是标点」，
必要时把 target 右移一位；夹具＝本 run 的 `S0021`。此缺陷与 P1' 接线无关（标点优先只在已安全的
候选里筛选），但它会直接被用户看见，优先级高于 P2.5'。

### 34.6 已给用户的操作指引

只复核 11 条（GPT 的 9 条 + `S0021` 页首逗号 + `S0045` 语序错位）、改完直接合成、不重跑；
**并且这一集的编辑草稿必须留下** —— 它是唯一能把 34.3 的 79%–92.5% 收敛成一个数、
并把 34.4 的 80% 变成真召回率的输入。同时提醒用户：他挪分页边界时逐页中文可能整页变空
（P2' 要修的那个工具缺陷，占历史 285 条中文修改的 41%），这一集也可能遇到。

## §35 第十九轮：用户已交出新音频的人工终稿 —— 首个前瞻性 P4 数据点，三大指标全部落定

终稿包：`stable-runs/20260824T201840.701773-2290bd40/人工终稿字幕包/generations/20260824T221537668415-e5e335e1/`
（`人工终稿字幕-edits.json`，history 70 步，21:39–22:15 完成）。全程只读。
**这是第一个真正前瞻性的端到端样本**：代码（b951d75）先冻结、我和 GPT 的预测先写下（§34）、用户后动手 —— 无事后拟合。

### 35.1 三大指标（本集实测）

- **E 改动率 = 24/120 = 20.0%**（历史三集 11.8%/29.9%/17.3%，合并 19.3% —— 本集正落在同档）。
  §34.3 的「79%–92.5%」区间收敛为 **80.0% 干净** —— GPT 用旧队列挑样估的 79% 反而几乎命中，我的全集口径 92.5% 偏乐观。
- **R 读取率（editor-review-ledger）= 29/120 = 24.2%；Rec 召回 = 14/24 = 58.3%**。
  对比 §27 老基线（读 45.7%/召回 77%）：**读少了一半，召回掉了 19 点**。虚警 15/29 = 52%。
  ledger 漏掉的 10 个父：S0062/63/93/94/103/104/105/107/117/118 —— **几乎全是短的单页父**（连锁语义类）。
- GPT 巡检名单 10 条中用户真改了 9 条（唯一没改 = S0077）；但用户另改了 15 条 GPT 没提的。
  **ledger∪GPT 并集：读 31/120 = 26%，召回 15/24 = 62%** —— 即便两套清单叠加，仍漏 9 条。

### 35.2 改动成分（对 §29/§33.8 结论的新集复检）

- 47 步中文编辑中 **32 步（68%）发生在同一父的分页改动之后**（历史 46%/73%/71%）→ 中文工作大半是分页下游，再次成立。
- **本集「改前逐页中文整页为空」= 0 步**（历史 57/285）。注意：不能就此宣布 P2' 缺陷已消
  —— 本集他挪边界的父只有 10 个，样本小，且 b951d75 未包含重切逻辑；下集继续盯。
- 整条中文一字未改、纯挪页/分页的父只有 4/24（17%，历史约 36%）；20/24 改了词句。
- 改动风格与三集一致：主要是补回自动版丢掉的语气词与口语填充（Right/Yeah/you know →「是的」「你知道的」）、
  把过度压缩的句子还原完整。**这类「自动版偏简、他要全」是稳定口味，可编码进翻译提示词**（新候选，见 35.5）。

### 35.3 ★ S0104–S0107：用户自己宣布「实在没办法调整」的两条 = P3' 残余类的活样本

EN：`S0104 But the legal reality gets incredibly muddy` → `S0105 the second you do anything more than just swap a sticker`
→ `S0106 Rejigging your corporate supply chain to legally shift a product's country of origin` → `S0107 just to reduce your tariff liability`。
英文把时间从句（the second…）后置、目的（just to…）尾挂；中文自然语序必须前置（「一旦你…，法律就…」）。
**字幕 ID 与时间轴冻结在英文语序上，中文无论怎么切都得在「语序自然」与「与音频对位」之间二选一** ——
这不是他改得不好，是结构墙。他在 S0106/S0107 上的实际解法是**跨条搬运语义**
（S0107 终稿「为了少交关税而合法地更改产品的原产国」吃进了 S0106 英文的内容）——
这正是 §32.5 说的中英词对齐问题，跨父版。P3' 若做，第一夹具就是 S0104–S0107。

### 35.4 终稿里我复核出的两处小残留（报给用户，由他定夺，不是必须改）

- **S0045.P02「中国商品商品的进口税差」——「商品」重复了一次**，应为「中国商品的进口税差」。此外该父语义正确。
- S0011 三页连读通顺；S0021 页首逗号已由他修掉（并句 +「。」）。其余 §34.6 名单 9/10 已处理。

### 35.5 对 GPT 工单的增量（并入下一轮）

1. **审校清单的短板换位了**：漏的不再是长句（§27 时代），而是**短单页父的连锁语义**（S0104–107、S0117/118 这类
   跨条成对出现的）。候选信号（离线可测，先测后接）：相邻父时长 <3.5s 且英文以从属连词/介词/关系词开头或结尾
   （the second / just to / instead of / who are…）→ 标整组。夹具 = 本集漏掉的 10 父。
2. 翻译提示词候选：不许丢弃语气词与话语标记（Right/Yeah/Mm-hmm/you know），以 35.2 的口味证据为依据；
   离线 A/B 后按 E 是否下降判定，不许直接上生产。
3. 35.1 的三数（20.0% / 24.2% / 58.3%）计入 P4 第一数据点；P5 汇报口径沿用「E 是缺陷率下界」。
4. §34.5 两缺陷维持第一优先：stable-run 混入旧队列（修完后 R/Rec 要重测）、非严格分支页首标点。

## §36 第二十轮：总执行策略（外部审计员余额将尽，本节为长期自治工单，优先级最高）

> **⚠ 2026-08-25 更新（读本节前先看这三行）**：**36.3 的机制不变，仍是判定权的唯一来源**；
> **36.4 的 5 步顺序已被 §37.7 覆盖**（前面插入 S0＝整集阻塞降级，S3 提前并缩成一行）；
> 36.1 的现状数字已被 §37.3–37.4 更新（新增日本X世代集，赶时间口径 E 12.5%）。
> 若与 §37 冲突，一律以 §37 为准。

本节写给 GPT：外部审计员（Claude）可能长期缺席。此后**判定权由本节的机制代行**，不是由你代行。
你可以执行、测量、汇报，但"过/不过"只能由预登记的数字说了算。

### 36.1 现状裁定（截至 2026-08-25 01:40，供你对齐）

方向是对的，没有拆东补西的证据：P1' 标点优先经帕累托验证（+24/−1）接线，且在新集上外部验证
（36 切点 58% 落标点＝用户同档）；§34.5 两缺陷已由 `3925520`/`5d22606` 修复（已核补丁内容）；
回归 31/32，唯一失败是先前就存在的 S9522 夹具，与本轮无关。
但要诚实：**新集 E=20.0%，与历史 19.3% 持平 —— 切分修复尚未在 E 上兑现**，唯一样本还不足以下结论。
三大数的最新值：E=20.0%（24/120）、R=24.2%、Rec=58.3%；你的跨父保守候选＝读 33.3% / 召回 91.7%（22/24）。

### 36.2 通往「90–95%」的账（不许再模糊表述）

用户的目标是"自动化完成 90–95%、他补 5–10%"。拆成两条腿：
（a）**生成侧降 E**：现 20%。可攻的三块，按预期收益排序：
   ① 语气词/完整性口味（20/24 条词句修改的主类）→ 翻译提示词离线 A/B，夹具＝四集终稿；
   ② P2.5' 容量线自动加页（中文>25 字或英文>85 字符）→ 夹具＝疑似漏改清单-三集.md 严格档 19→≤5；
   ③ P2' 边界改动后自动重切（历史 285 步中 41% 是工具造成——注意它主要降低每条的工作量，不直接降 E）。
   **结构墙（S0104–107 类，英文后置从句 vs 中文前置语序）每集约 2–4 条＝2–3% 是地板**，
   加上 §30 的 ≤8 字润色地板 1–2%，**生成侧诚实上限 ≈ E 降到 5–8%，即自动化 92–95% 的理论顶、88–92% 的现实预期**。
（b）**分诊侧降读取量**：你的保守候选已达 读 33%/召回 92%。**这条腿已接近够用**——
   用户逐条看 40/120 而不是 120/120，配合 (a) 把 E 压下去，体验上就是"90%+ 自动化"。

### 36.3 自我纠正机制（你必须逐条遵守，这是判定权的来源）

1. **先登记后测量**：任何实验先在 `执行进展-给用户.md` 写下门禁数字和夹具，再跑。跑完数字不许改口径；
   没过就写"没过"，三种合法的没过见 §28.7，**永远不许调低门禁让自己过**。
2. **接线双判据（取代一切拍脑袋阈值）**：帕累托表（逐例列出新修好 vs 新弄坏，弄坏必须逐例解释）
   ＋不退化棘轮（下条）。二者同时满足才许改生产。
3. **棘轮清单（每次改生产后必须全部重测，任何一项变差＝立即回退）**：
   全库纯函数重放 newly_None=0、空页=0；三集监督指标 ≥62/100（14/25、25/46、23/29）；
   回归套件不得新增失败（S9522 是既有失败，修它须单独提交）；新集切点落标点率 ≥55%；
   页首标点页＝0；`render_blocked` 逻辑不得变。
4. **一项改动一个提交＋反向补丁**存 `docs/audits/2026-08-24/rollback/`；混合提交视为未通过。
5. **每集新音频＝一次审判**：用户交出终稿后 24 小时内，只读复算 E/R/Rec 三数并与上一集对照，
   写进 `执行进展-给用户.md`。**若某项已接线的改动连续两集未在它声称的指标上兑现，自动列入回退议程**，
   由用户拍板。预测要提前写：跑新集前先写"我预计 E=X%"，事后对账。
6. **过拟合防线**：所有夹具集（四集终稿）只许当考卷，不许当训练集反复调参刷分；
   同一信号在夹具上调参超过 3 轮仍不过门禁＝该路线作废，换思路，不许第 4 轮。
   （历史教训：window 参数扫了 5 档、全局 DP 扫了 144 组，上限也就 63/100——继续扫是无效劳动。）
7. **归因表口径**：报"语义漏译/风格偏好"前必须列"整条中文是否变过""改前是否整页为空"两列（§33.8 教训）。
8. **报忧优先**：每轮进展末尾固定两栏——"这轮我可能做错的""需要用户决定的"。空着＝不合格。
9. 红线不变：不重跑已校对集、不动冻结英文/ID/时间轴、不写 D:\软件缓存、`git checkout .`/`stash` 禁用。

### 36.4 接下来 5 步（顺序固定）

S1 把跨父保守候选（读 33%/召回 92%）按 36.3 双判据接入审校清单（这是分诊腿的收尾，收益最大且已有数据）；
S2 语气词提示词离线 A/B（夹具＝四集终稿的 20+ 条语气词修改；门禁＝该类命中 ≥60% 且不引入新改动类）；
S3 P2.5' 容量线（夹具与门禁见 36.2②）；
S4 P2' 重切（门禁＝重放三集 57 例空页→0，且棘轮全绿）；
S5 等下一集新音频终稿，按 36.3.5 对账，决定 S2/S3 是否兑现。
P3'（结构墙）挂起：只建夹具（S0104–107），不投入实现，等 S1–S5 落定后由用户决定值不值。

### 36.5 地基判定与「推倒重来」的触发条件（回答用户的最后一问，防长对话思维定势）

**裁定：核心流程（切分→翻译→分配→分页）地基是好的，不需要重构。** 依据全部来自用户自己的行为数据，
不依赖任何模型的自我评价：四集认真校对的集子里他 70–88% 的父字幕一字未动；页数 90%+ 他照单全收
（223/236、181/201、158/172 不变）；改动字符 80% 落在 ≤8 字小块、每集需整句重写的只有 2–4 条；
39%→62% 那一刀本质是**修一次 8/5 的静默回归**（初版设计本来就是标点优先）——地基没歪，是有一层后来歪了。
架构里唯一的真结构限制＝字幕 ID 与时间轴冻结在英文语序上（S0104–107 类，每集 2–4 条），
重构能救的也只有这 2–3%，代价与收益完全不成比例。**任何"推倒重来"的提议默认拒绝。**

**但要防的正是审计者（含我）陷入自证：以下任一条触发，则暂停 S1–S5，回到地基层重查——**
(1) S2＋S3 落地后连续两集 E 仍未降到 15% 以下（说明我们对那 20% 的成分分解是错的）；
(2) 任何一集出现 >10 条整句重写型父（历史从未超过 4，出现即翻译层地基异动）；
(3) 棘轮清单同一轮里两项以上同时变差（说明改动的影响面超出理解）；
(4) 用户主观报告"越改越累"——他的手感优先于一切指标。
触发后的第一动作不是改代码，是把该集终稿按 §35 口径做全量归因，先证明"哪一层错了"再动手。

---

## 37. 第二十一轮（2026-08-25 08:30）＝两集实测：测试音频复核 + 日本X世代新集，含一个**整集级阻塞**根因

> 本轮同样零生产改动。所有数字可复现，脚本用法见各条括注。

### 37.0 素材身份与两条口径边界

**【实测】日本集 = `work-dir/失去的一代：日本X世代的职场困局`，4 次固定运行全部失败**：
`stable-checkpoints/` 下 20260825T020944 / 023436 / 055719 / 060425 四个 checkpoint 的
`stable-final-manifest.json` 一律 `validation_status="failed"`、`render_blocked=true`、
`validation_error_codes=["display_page_translation_invalid"]`、`subtitle_count=250`、
`code_commit=25bbf330`（＝当前 HEAD）。`run-state.json.status="failed"`。

**他的终稿不在任何已挂载盘**：`C:\Users\19379\Desktop\失去的一代：日本X世代的职场困局\
失去的一代：日本X世代的职场困局-处理结果\人工终稿字幕包\generations\20260825T073926271208-23064692\`。
成品目录由 `output_paths.py:11-22 media_result_dir()` 按**媒体文件**所在目录推导，而媒体在桌面
（manifest `source_media_path`）→ **§27 那条规则第二次生效：断言数据不存在前先问用户成品存哪儿。**
history 133 步，06:16:29 → 07:39:12（83 分钟）；`.manual-editor-drafts` 在提交后被
`subtitle_interface.py:4362-4371` 清空，所以工作目录里看不到草稿。

**口径边界一（用户口述）**：这一集是**赶时间大概调整**的，测试音频才是认真逐条调整的
→ 本集 E 只能当**下界**，**不许与测试音频的 20.0% 直接比较**，Rec 也可能被高估
（他没改的父里还有该改的）。

**口径边界二【实测】**：测试音频 23:00 的 `20260824T230018847331-f5cc2294` 与 22:15 的
`…-e5e335e1` **内容完全一致**（整个 state 的 JSON diff 只有 3 处：`created_at` 与两条 source 路径，
history 都是 70 步、touched 都是同样 24 个父）→ 它只是把 22:15 的终稿再导出一次，
**§35 的 E=20.0% / R=24.2% / Rec=58.3% 不变，无新数据点**。
`S0045`「中国商品商品」仍在（`grep -c 商品商品 人工终稿字幕.srt` = 1）。

### 37.1 【实测·本轮最重要】2 个父（0.8%）让整集 275 页逐页中文一页都没生成

四个 checkpoint 的 `display-page-translations.json` 一律：
`status="ERROR"`、250 父 / 275 页、**带中文的页 = 0**（页对象里根本没有 `chinese` 键）、
23 个多页父的所有页同样为空、250 个父全部 `renderable: false`。
`qa-summary.json`：`BLOCKED`，blocker 1 / review 63 / info 37 / allocation_unresolved 2。
`validation-report.json` 另有 20 个父带 `structural_english_overflow`。

**失败只由两个父引起**：`S0001`、`S0242`，reason = `no_complete_normal_font_page_partition`。

**根因（已核实，读代码确认）**：`app/core/utils/podcast_learning_video.py:6134-6145`：

```python
complete_normal_font_candidates = [
    candidate for candidate in candidates
    if not int(candidate.get("incomplete_review_count") or 0)
    and int(candidate.get("relaxed_raw_hard_count") or 0) <= 1
]
if ((candidates and not complete_normal_font_candidates)
        or (not candidates and not automatic_floor_static_lines)):
    failure_reasons.add("no_complete_normal_font_page_partition")
candidates = complete_normal_font_candidates
```

`collect_candidates`（6051-6113）确实按 `range(1, bounded_max_page_count+1)` 枚举了多页方案，
但凡是"review 类边界且该页不成完整短语"（`incomplete_review_count`，6034-6038）就整条候选被丢弃。
这两个父的**每一种**切法都被判成不完整 → 候选清零 → 记失败 → **整个逐页中文阶段停产**。

**讽刺的反证**：他在编辑器里把 `S0001` 切成 3 页
（`Between 2020 and 2025,` / `college-educated Japanese workers in their 20s and 30s` /
`saw their nominal wages surge by more than 10 percent.`）、`S0242` 切成 2 页，几秒钟的事。
**机器拒绝的正是他的切法。**

**影响面：0.8% 的父 → 100% 的集子不可用、四次重跑全废、83 分钟纯手工。
这是目前单位代价最高的缺陷，优先级高于 S1–S4 全部。**

**修法（工单 S0，给 GPT）**：把"不完整 review 候选"从**过滤条件**降级为**兜底候选** ——
无完整候选时选打分最好的那个 emit 出来，并打 REVIEW 标记，不再让整集失败。
ledger 已经把这两条标成 BLOCKER `display_page_blueprint_invalid`（本集 2 标 2 命中），
用户照样第一眼就看到，不存在"悄悄放行"。
门槛（硬）：① 全库 62 集重放，`no_complete_normal_font_page_partition` 导致的整集失败 → 0；
② 新产出的页不得违反页首标点禁令与胶合 token 规则（§34.5(b) 那类）；
③ §36.3 棘轮项一个不许退；④ 一项一提交 + `rollback/*.revert.patch`。

### 37.2 【实测】中文分页这一层在这集是好的，且是标点优先接线后第二个外验点

- 他**一字未动**的父里，编辑器自动切出的 15 个切点有 13 个落在中文标点后 = **86.7%**
  （棘轮线 ≥55%；第十八轮新集 58%）。
- 他**亲手切**的 18 个切点只有 55.6% 落在标点后 → **自动版现在比他本人更贴标点**，
  与 §31(2)「绝不许把切在标点写成硬规则」一致：这是行为指标，不是合格线。
- 终稿 281 页中文字数：中位 **13** / p90 **22** / 最大 **27**（他口味 中位 14 / p90 21-23 / 极限 31）
  → 容量口味已基本对上，§31(1) 的触发线方向正确。
- 终稿 `人工终稿分页映射.json` 281 页**全部有中文**、`人工终稿分页双语字幕.srt` 281 块 0 缺中文、
  该包自带的 `display-page-translations.json` 状态 **PASS**（248 父 / 281 页）
  → **P2'「改边界后自动重切、严禁空页」在编辑器路径上是成立的**；
  这集能救回来完全靠 `manual_final_subtitle_editor.py:7418` 那条重切路径。

### 37.3 【实测】E = 31/248 = **12.5%**（赶时间口径，是下界），成分与"地板"再确认

- **页数决策九成以上照单全收（第三次复现 §30(1)）**：加页 10 / 减页 3 / 页数不变 235 = **94.8%**。
- **新增测量规则（重要）**：schema 5 的 history 里出现了新操作
  `confirm_display_page_boundary`（22 步）—— 它是**确认/致谢，不是修改**。
  本集这 22 步全部落在他同时也真改过的父上（"只确认未修改"的父 = 0），
  但**若把它当编辑计入 E，E 会虚高**。
  → **今后抽 touched 集时必须排除 `confirm_*` 类步骤**，与 §31 那条
  「只从非 `before_*` 字段抽父 ID」并列为口径硬规则。
- **31 个改动的成分**：15 个未被清单标出，其中
  **9 个是纯中文措辞**（S0002/05/07/24/54/65/71/92/172：补回"没错。""是因为"这类语气词与话语标记、
  把"数学之路"改成"数学路径"这类同义润色），全是 ≤8 字级小修，**冻结产物里没有任何信息可判定**
  → **9/248 = 3.6% 就是这集的诚实地板**，与 §36 的"润色 1-2% + 结构墙 2-3%"同档。
  **这 9 条也正是 S2（翻译提示词保住语气词/别过度压缩）要打的靶，是目前最强的 S2 证据。**
- 另 3 个漏标是"单页太满他自己拆开"（S0113 / S0120 / S0136）→ 属容量线，**可检测**（见 37.5）；
  剩下 3 个是首尾边界与跨条合并的个案。

### 37.4 【实测】分诊：R = 35/248 = **14.1%**、Rec = 16/31 = **51.6%**、虚警 **54.3%**

按 code 的性价比（标记数 → 命中他真改过的父数）：

| code | 标记 | 命中 | 备注 |
|---|---|---|---|
| `display_page_capacity_review` | 5 | 5 | GPT 新标，本集精确率 100% |
| `display_page_blueprint_invalid` | 2 | 2 | 就是 37.1 那两个父 |
| `visual_page_boundary_review` | 10 | 7 | 主力 |
| `high_confidence_visual_page_boundary` | 4 | 2 | |
| `high_confidence_chinese_semantic_issue` | 3 | 1 | |
| `english_boundary_audit` | 10 | **1** | 噪声 |
| `chinese_reading_speed_warning` | 3 | **0** | 噪声 |

**建议：把 `english_boundary_audit` 与 `chinese_reading_speed_warning` 移出用户可见清单**
（保留在内部审计与 qa-summary 里）。代价实测：R 14.1% → **8.9%**，Rec 51.6% → **48.4%**
（只丢一条 S0171）。这与 §33「英文边界合法性只影响内部指标、不影响 E」一致。

**本集清单天花板 = 22/31 = 71%**（9 条纯措辞不可检测），现已拿到 16 → 缺口只剩 6 条，
其中 3 条是容量线 → **37.5 一行改动可吃掉一半缺口**。

### 37.5 【实测·跨集验证】容量线阈值 `_CAPACITY_REVIEW_CJK_CHARS` 26 → **22**

现状 `subtitle_review_marks.py:37-38` 是 EN>85 **且** Han≥26 的**合取**，
且 `_display_page_capacity_review_marks`（833-879）只看单页父、只数汉字
（`re.findall(r"[一-鿿]")`）。测试音频的 S0120 汉字 25 → 差一个字漏掉。

GT = 他后来**真的加了页**的单页父。两集独立扫描：

| 阈值（EN>85 且 Han≥N） | 日本集 标记/命中(GT=8) | 测试音频 标记/命中(GT=2) | 合计 |
|---|---|---|---|
| N=26（现设） | 5 / 5 | 1 / 1 | 6 标 → **6/10** |
| **N=22（建议）** | 12 / 6 | 4 / 2 | 16 标 → **8/10** |
| N=16 | 23 / 8 | 7 / 2 | 30 标 → 10/10（读取翻倍，不值） |

**两集独立指向同一个值 → 不是单集拟合**（§27 那条硬规则满足）。
读取率只多约 4%，召回 +2/10。**这是只加标记、不动任何产物的改动，天然帕累托（无可弄坏项）**，
是全部候选里成本最低的一项。要求同样附回退补丁，并在下一集对账。

### 37.6 给用户的复核短名单（因为这集是赶时间过的）

**终稿本身校验 PASS、281 页 0 空中文 → 可以直接合成。** 若他愿意再花十分钟，只看这 12 条：

① 清单标了、他没动的 7 条：`S0011`、`S0096`、`S0121`、`S0138`、`S0182`、`S0211`、`S0244`。
② 按新容量线该标、他没动的 5 个单页父：`S0061`(EN 101/22 字)、`S0107`(94/22)、
`S0188`(88/22)、`S0201`(93/23)、`S0230`(88/23)。

测试音频合成前只需改一处：`S0045.P02`「中国商品商品」→「中国商品」。

### 37.7 顺序更新（覆盖 §36.4 的 S1–S5）

**S0（新增，最高）＝ 37.1 的阻塞降级** → **S3'＝ 37.5 的容量线一行（Han 26→22）** →
**S2＝ 语气词/过度压缩的提示词离线 A/B** → **S1＝ 跨父保守候选接线**（GPT 已测 读 33.3%/召回 91.7%）
→ **清单瘦身（去 37.4 那两类噪声 code）** → **S5＝ 下一集对账**。

理由：S0 单位代价（0.8% 的父废掉整集）远高于其他任何项，且已定位到 12 行代码；
S3' 是一行、跨集验证过、无回退风险；S2 打的是本集最大可动成分（3.6%）。
P3'（结构墙）仍只建夹具不实现。

### 37.8 这轮我可能做错的（报忧栏，§36.3 必填）

1. 本集 E/Rec 的 GT 来自"赶时间一遍过"，漏改必然多于认真集 → **Rec 51.6% 可能被高估、E 12.5% 是下界**，
   不得写成"E 从 20% 降到 12.5%"。
2. 自动切点 86.7% 的分母只有 15 个切点，且来自**编辑器现算**而非通过校验的固定运行产物，
   **不能与第十八轮的 58%（36 切点）连成趋势线**。
3. 容量线两集 GT 合计只有 10 个，Han=22 与 20/24 的差别统计上很薄 → **只允许改一次，下集必须对账**。
4. 我第一次找日本集终稿时结论是"盘上没有"，错了（同型错误第五次的候选，靠读 manifest 的
   `source_media_path` + `output_paths.py` 才救回来）；第一次量标点落点时报"空中文页 275、落点 0/25"，
   那是 ERROR 运行没有 `chinese` 键的假象，不是缺陷。**两次都是先出结论后验证字段。**

### 37.9 【实测·补测】"切分/分页是不是已经没问题了"——分层回答（用户 2026-08-25 追问）

**分页层：是（但只在编辑器路径上被证明）。** 证据＝37.2（他没动的父上自动切点 86.7% 落标点、
页中文字数中位 13/p90 22/max 27 对上他口味）＋ 37.3（页数不变 94.8%，第三次复现）。
**但批量规划路径这一集根本没跑通（37.1），所以"分页没问题"目前只对编辑器重切成立，
不对流水线成立 —— S0 落地前不许把这句话当整体结论。**

**英文切分层：还有一块 8% 的硬残余，而且它就是这次阻塞的上游。**
本集 `validation-report.json` 的 warnings：
`structural_english_overflow` **20 条**（reason 全是 `no_legal_internal_cut_within_normal_limit`，
即"整句合法切点找不到"，如 `S0001` 22 词 / hard_limit 16）、`suspicious_cut` 18、
`syntax_boundary_audit` 14、`reading_speed_warning` 8、`<500ms` 3、`asr_suspicious` 1。
**`S0001` 与 `S0242` 两条都在这 20 条里** → 37.1 的整集阻塞不是分页层独立的 bug，
而是**超长父落到分页层后每种切法都"不完整"**，两层叠加的结果。

**这 20 条超长父吃掉他 29% 的工作量**：占全集 8.1%（20/248），但与他真改过的 31 个父交集 **9 个**
→ 该类精确率 **45%**，相对基线 12.5% 的**提升 3.6 倍**。
**→ 结论：他现在剩下的三成手工量集中在"英文没法合法切短的整句"上，这是切分层最后一块真骨头，
不是润色地板。**（另七成里 9 条纯措辞是地板，见 37.3。）

**但它不是新的分诊信号，不要新增 code**：这 20 条里 14 条已在 ledger 中，
且它命中的 9 条**全部已被 ledger 标出** → 并集读 16.5% / 召回仍 51.6%，一条新命中都没有。
瘦身（去 37.4 两类噪声）后再并入 overflow：读 11.7% / 召回 48.4%。
**已经覆盖了，价值在于告诉 GPT "该修生成侧的哪一类"，不在于加标记。**

### 37.10 【实测·更正 §35】用户并没有"跨条搬运语义"——他在把工具的跨条搬运搬回去

用户 2026-08-25 追问"中文和音频严格对位不严格执行会怎样"，我去逐条查了被 §35 当作
"他自己跨条搬运语义"的那组（`S0104`–`S0107`），**结论相反**：

| 父 | 英文 | 自动基线中文（`before_parent_states` 最早快照） | 他的终稿 |
|---|---|---|---|
| `S0106` | Rejigging your corporate supply chain | 重组企业供应链**，合法变更产品原产国** | 重组企业供应链 |
| `S0107` | to legally shift a product's country of origin just to reduce your tariff liability. | 只为降低关税负担 | **为了少交关税而合法地更改产品的原产国。** |

**是自动分配把 `S0107` 英文的内容（原产国那一段）提前塞进了 `S0106` 的中文**（因为中文语序要它靠前），
**用户做的事是把它搬回 `S0107`，即恢复严格对位**。
→ **§35「他的实际解法是跨条搬运语义（S0107 吃进 S0106 的内容）」这句判断错了，以本节为准。**
方向反了会导致完全相反的处方（"放宽对位"其实是在制造他正在花时间纠正的那类改动）。

**全量检测同向**：两集有基线的 touched 父（日本 28 / 测试音频 23）用"6 字连续片段出现在邻父基线里
但不在自己基线里"做检测，**跨父语义搬运 = 0 例**。

**他真正用的跨条手段是"合并"，而合并是保对位的**：日本集 `merge_adjacent_display_pages` 2 次
（`S0002+S0003`、`S0108+S0109`），合并后页面时间窗＝两条的并集，词与时间一起走，
所以既没破对位也没破守恒；合并后页面 EN 60 / 63 / 55 字符，全在容量线内。

**因此对"放宽严格对位"的裁定：不建议放宽。**
收益上限＝结构墙那 2–4 条／集（2–3% 的 E），而且这批他本人选的就是对位而不是语序自然；
代价＝失去「逐页中文拼接 == 整条中文」这条守恒律（§34 实测 32/32 通过），
**它是目前唯一能自动证明"没漏译、没重复"的检查，而漏译恰恰是他肉眼分诊看不出的缺陷类**。
用 2–3% 换掉覆盖 100% 的安全网，交易不划算。

**若将来仍要放**，唯一可接受的形式（写死，防止悄悄扩大）：只在检测到结构墙的父上、
只允许跨**相邻一条**、守恒律从"每条守恒"改为"该组守恒"、每一例强制 REVIEW 标记、不许静默通过。

**更安全的替代杠杆**＝让规划器学会**把相邻短条合并成一页**（他已在手动做），
在保对位的前提下给中文重排腾出空间。但它**覆盖不了长条**：`S0106+S0107` 合并后 EN 121 字符、
中文约 28 字，超出他的容量口味（p90 22 / max 27）→ 结构墙不可能全靠合并解决，剩下的仍是地板。

### §37.11 长度层实测：清单该分两档（用户原话驱动，两集数据）

**用户 2026-08-25 原话**：「即使放掉我还是会大概看一下，有时候没有颜色的字幕比较长的话
我也会试着找切分点，然后分屏。」→ 他自己已经在跑一个**长度启发式**。
§26 已证明冻结产物分不开「长而没问题」与「长而有问题」，所以长度**不能进 ledger 当问题标记**，
但可以作为**第二档淡色提示「只是长，瞄一眼要不要分屏」**。以下为两集实测（口径同 §37.3，
`confirm_display_page_boundary` 排除；长度指标＝该父**最长一页的英文字符数**，单页父即整条）。

单独用长度（读取率 / 召回率）：

| 阈值（最长页 EN 字符） | 日本集 N=250, touched 31 | 测试音频 N=120, touched 24 |
| --- | --- | --- |
| ≥50 | 140 (56%) / 74% | 71 (59%) / 79% |
| ≥58 | 107 (43%) / 65% | 58 (48%) / 67% |
| ≥70 | 67 (27%) / 58% | 39 (32%) / 50% |
| ≥85 | 30 (12%) / 48% | 16 (13%) / 25% |

**ledger ∪ 长度（这才是要接线的形态，深色＋淡色合计读取）**：

| 组合 | 日本集 | 测试音频 |
| --- | --- | --- |
| ledger 单独 | 读 14% / 召回 52% | 读 26% / 召回 58% |
| ∪ ≥58 | 读 48% / **77%** | 读 57% / **83%** |
| ∪ ≥64 | 读 42% / 77% | 读 51% / 79% |
| **∪ ≥70** | **读 34% / 77%** | 读 47% / 75% |
| ∪ ≥78 | 读 27% / 74% | 读 38% / 67% |

**分位数版（读取率可预测，跨集稳定，推荐写法）**：淡色＝本集最长的 X%：

| X | 日本集（阈值/合计读/召回） | 测试音频（阈值/合计读/召回） |
| --- | --- | --- |
| 15% | 81 字符 / 23% / 68% | 84 字符 / 34% / 67% |
| 20% | 77 / 28% / 74% | 80 / 37% / 67% |
| **25%** | **71 / 32% / 77%** | 76 / 42% / 67% |

**两条硬结论**：
(1) **长度档确实值钱**：日本集读 14%→34% 换召回 52%→77%（新命中 8 条全是他真改过的长父），
这正是 §27 三集老结论（读 45.7%/召回 77%）的复现**且更省**——同样 77%，读取从 45.7% 降到 34%。
(2) **它有天花板，且两集天花板不同**：测试音频无论阈值怎么调，分位数档召回**卡在 67%**，
绝对阈值要到 ≥58（读 57%）才 83%。原因在漏项名单里，不是阈值没调好。

**ledger ∪ ≥70 的漏项（逐条，供夹具）**：
- 日本集 7 条：`S0002` EN 11、`S0003` 48、`S0005` 47、`S0024` 56、`S0054` 41、`S0092` 32、`S0109` 24
  —— **全是短父**，动作是语气词/措辞与相邻合并（S0002+S0003 正是 §37.10 那次
  `merge_adjacent_display_pages`）→ 即 §37.3 那个 3.6% 措辞地板 + 合并类，长度信号原理上抓不到。
- 测试音频 6 条：`S0063` 31、`S0103` 87、`S0104` 50、`S0105` 65、`S0107` 37、`S0118` 58
  —— `S0103–S0107` 就是 §35/§37.10 的**结构墙簇**（S0103 整条 87 字符但已分页，最长页＜70 所以逃掉）。
  → 测试音频卡 67% 的根因是结构墙，不是长度档没做好。

**给 GPT 的接线要求（并入 §38.3.4 的 S1，不单独排期）**：
淡色档只读、只提示、**不进 ledger、不算 severity、不影响 `render_blocked`**；
阈值写成**本集分位数（先取最长 25%）而非固定字符数**，因为两集固定阈值的读取率差 13 个百分点；
必须同时做 §37.4 的清单瘦身（否则深色档里 13 条 `english_boundary_audit`/`chinese_reading_speed_warning`
只 1 条中，正好污染"深色＝一定有问题"这个用户唯一还信的语义）。
**门禁**：两集重放读取率 ≤35%/≤45%、召回 ≥74%/≥75%，且深色档条数只减不增。

**待第三集才能定的事**：阈值/分位数取值只有两集样本，两集口味不同（测试音频整体更长），
按 §36.3 的「一项一提交＋反向补丁」，S1 落地时把分位数做成配置项，下一集终稿到手后复算一次再冻结。


---

## §38 给 GPT 的单一启动入口（用户此前未把 §36 交给你，所以从这里开始）

**阅读顺序，只有三步**：先读 **§36.3**（自我纠正机制＝判定权的来源，九条，逐条遵守）→
再读 **§36.2 与 §36.5**（目标怎么算账、地基为什么不重构、什么条件下才允许回头质疑地基）→
最后读 **§37**（当前事实与执行顺序）。**§36.4 的顺序作废，用 §37.7。**
其余章节（§10–§35）是历史证据链，只在你要复核某个数字时按指针回查，不必通读。

### 38.1 第一件事：S0＝整集阻塞降级（在此之前不要动任何别的）

事实见 §37.1：`S0001`/`S0242` 两个父触发 `no_complete_normal_font_page_partition`，
`podcast_learning_video.py:6134-6145` 把所有"不完整 review 候选"从候选集里剔除 →
候选清零 → **整集 250 父 / 275 页的逐页中文全部未生成，用户手工做了 83 分钟**。
改法：无完整候选时，**选打分最好的不完整候选 emit 出来并打 REVIEW 标记**，不再让整集失败。
门禁（先登记，按 36.3.1）：
① 全库 62 集纯函数重放，因该 reason 造成的整集失败 → **0**；
② 新产出页不得违反页首标点禁令与胶合 token 规则；
③ §36.3.3 棘轮清单全绿；
④ 一项一提交 ＋ `docs/audits/2026-08-24/rollback/*.revert.patch`；
⑤ 用日本集那四个 checkpoint 当夹具复跑，验证 `S0001` 能切出 3 页、`S0242` 能切出 2 页
（用户的切法见 §37.1），且这两条仍带 BLOCKER `display_page_blueprint_invalid`。

### 38.2 第二件事：S3'＝一行阈值（`_CAPACITY_REVIEW_CJK_CHARS` 26 → 22）

依据 §37.5，两集独立验证，只加标记、无可弄坏项。门禁＝两集标记/命中复现 16 标 8/10，
读取率增幅 ≤5%，棘轮全绿。**不要顺手把 EN>85 也一起动，不要改成析取。**

### 38.3 然后才是 S2 / S1 / 清单瘦身 / S5

见 §37.7。S2 的靶子已经量出来了：§37.3 的 9 条纯中文措辞（3.6%）＋ §35 的语气词类修改，
夹具＝四集终稿，按 36.3.6 最多调 3 轮。
清单瘦身＝§37.4 的两类噪声 code 移出用户可见清单（代价已量：R 14.1%→8.9%、Rec 51.6%→48.4%）。

**38.3.1 为什么 S3'（一行阈值）必须排在 S2（提示词）之前 —— 不是先易后难，是有耦合**：
S2 要做的事是**把被压缩掉的语气词/话语标记补回来**，这会让中文**变长**（§35 实测他补回的就是
"没错。""是因为""你知道"这类），而**每页中文字数正是容量线的输入**（§37.2：现终稿 中位 13/p90 22/max 27）。
若先改提示词再改阈值，容量线的基线已被污染，你无法分清"标记变多"是阈值改的还是提示词改的。
→ **顺序固定：S3' 先落地并留下一集的容量分布快照，再动 S2。**
且 **S2 必须新增一条棘轮项：每页中文字数的中位与 p90 不得上移超过 2 字**
（超过就是"补语气词补到挤爆一屏"，属于拆东补西，直接回退）。

**38.3.2 S2 的两条红线（比门禁更硬）**：
(a) 提示词改动会改变 LLM 缓存键 → **绝不许在用户已校对过的集子上重跑验证**（红线 36.3.9），
夹具只能是**离线 A/B**：拿四集终稿的原文当输入，比对新旧提示词的输出与他终稿的距离，不落盘、不覆盖产物；
(b) 门禁是"该类命中 ≥60% **且不引入新的改动类别**"——若新提示词修好了语气词却新增了别的毛病
（比如把"是因为"补成"这是因为说"），按帕累托表逐例列出，弄坏项一例都要解释。

**38.3.3 关于"中文重分配"（P2' 自动重切）：先证明它还坏着，再决定要不要做**：
历史上那 57 条"改前整页中文为空、用户从零打字"是 P2' 的立项依据（§33.8），
但 §37.2 实测**日本集终稿 281 页 0 个空中文、编辑器重切路径产出的包自带校验 PASS**，
第十九轮那集也是 0 步。→ **P2' 可能已经被后来的修复顺带解决了。**
要求：动手前先在当前 HEAD 上重放三集，报出"改前整页中文为空"的实际条数；
若已为 0，则 P2' 降级为"只保留回归夹具"，不投入实现（它本来也只降低每条工作量，不直接降 E）。

**38.3.4 关于"审校召回"（S1 跨父保守候选）**：它把读取率从 14% 抬到 33%，**是有成本的**，
所以必须同时做清单瘦身（§37.4 的两类噪声 code），否则用户感受到的是"要看的更多了"。
接线前按 36.3.2 出帕累托表：新命中的父逐条列，新增虚警逐条列。

### 38.4 一条容易误读的地方

日本集这次用户很累（整集手工 83 分钟），**但这不算 §36.5 触发条件 (4)**：
累的根因已定位到 12 行代码里的一个过滤条件，不是地基。
真正要警惕的仍是 §36.5 的 (1)(2)(3) —— 尤其 (1)：S2＋S3' 落地后连续两集 E 仍不低于 15%，
就说明我们对那 20% 的成分分解是错的，那时才回到地基层重查。

---

## §39 用户报「保存终稿十次有八次不成功」——已定位（2026-08-25，只读取证）

**用户原话**：「当前版本为什么老是在保存终稿这个环节上出问题呢，十次有8次保存不成功。」

### 39.1 磁盘证据：失败的保存会留下一个 generation 目录，缺少两个分页导出文件

保存失败**不会**回滚 `generations/<id>/`（`manual_final_subtitle_editor.py:7838` 建目录，
全程无 rmtree），所以每次尝试都在盘上。判据：`人工终稿分页双语字幕.srt` 与
`人工终稿分页映射.json` 只在 `render_blocked=False` 时才写（`7997-8004`）→ **缺这两个文件＝那次被拦**。

| 集 | generation 数 | 被拦 | 拦截原因（读该 generation 的 `display-page-translations.json` `errors[]`） |
| --- | --- | --- | --- |
| 中式梦核 | 9（05:14→06:19） | **5** | 05:14 `manual_page_translation_required`；05:18/05:19/05:19/05:20 **全是同一条** `page_translation_chinese_token_split` @ `S0078.P01`、`boundary_offset=19` |
| 烂到爆红 | 3 | 0 | — |
| 测试音频 | 2 | 0 | — |

**他在 S0078 上连撞四次、耗时 2 分钟才过**（05:18:01→05:20:44，之后 05:25 起全 PASS）。
这就是"十次有八次"的来源：**一个页面的一个断点，把整集的保存卡住，而且他找不到是哪一页。**

### 39.2 为什么找不到：错误记录里有页号，但送给用户的消息里没有

链路（全部读过代码）：
1. `manual_final_subtitle_editor.py:9463-9469`：`validate_page_translation_response` 返回
   带 `code / parent_subtitle_id / display_page_id / boundary_offset / split_token` 的
   `errors[]`；只要 `status != PASS`，**一律折叠成一个字符串** `render_block_reason =
   "manual_page_translation_invalid"`，具体 code 与页号**在这一步被丢掉**。
2. `user_facing_issue_text.py:126-128`：该 reason 的文案是
   「实际分页的中文与分页结构不一致；请检查标记页面后重新保存。」——**没有页号、没有原因**。
3. `subtitle_interface.py:3793-3801`：消息里的"位置"来自 `display_page_review_summary()`
   的 `hard_pages / unconfirmed_chinese_pages / boundary_review_pages`，而这三个列表
   （`manual_final_subtitle_editor.py:5195-5227`）是**编辑器的复核标记**，
   **不是这次拦截的 errors** → **一个已被他确认过的页把保存拦下时，消息里可能一个位置都没有**，
   `_focus_manual_problem_position` 也就无处可跳。
4. 保存失败**不写日志**：`app.log` 里 `manual_page_translation_invalid` / `token_split` /
   「人工终稿未保存」出现次数**全部为 0**（InfoBar 警告不落日志；只有后台异常才 `LOG.exception`，
   而全库日志里 `Unable to save manual final subtitle package` 也是 0 次 → 这类拦截**不是异常**，是正常返回）。

### 39.3 顺带发现：日志从 2026-08-23 05:43 起就停止写入了

`AppData/logs/app.log` = 10,485,768 字节，`logger.py:56-57` 是
`RotatingFileHandler(maxBytes=10*1024*1024, backupCount=5)`；目录里只有 `app.log` 与
**8-09 的 `app.log.5`**，没有 .1–.4 → 轮转失败（Windows 上文件被另一进程持有时 rename 会失败），
**8-23 之后的所有运行没有任何日志**。→ 他 8-24/8-25 那几次失败在日志里查不到，只能靠 39.1 的 generation 目录取证。

### 39.4 判定与拦截规则本身要不要动：不动

`stable_display_page_contract.py:709-739` 的 `_source_owned_token_crosses_boundary`
已经很保守：只有当断点落在**冻结父中文里真实存在的词**内部、且**词典模式分词也认为非法**时才报
（HMM 造出来的伪词会被放过）。**这是对的，不许放宽**——断在词中间是用户自己也不接受的排版。
问题 100% 在"可诊断性"，不在判定。

### 39.5 工单 S0b（与 S0 同批提交，只改报错通道，不改任何判定）

优先级：**与 S0 并列最高**（S0 是流水线整集停产，S0b 是他每次保存的直接时间成本；两者同源＝分页被拦）。

1. `_write_manual_render_contract` 的返回值里增加 `blocking_errors`（原样带 code /
   `parent_subtitle_id` / `display_page_id` / `boundary_offset` / `split_token`），
   经 `paths["display_page_review_summary"]["blocking_pages"]` 传到 UI；
   `_manual_publication_issue_summary` 的 `positions` **优先取这一项**，其次才用复核标记列表。
2. `_ISSUE_EXPLANATIONS` 补具体 code 的中文解释，至少覆盖
   `page_translation_chinese_token_split`（「第 X 页的中文把「某词」切成两半，请把断点移到词的边界」）、
   `page_translation_chinese_*` 其余各 code、`display_page_blueprint_invalid`。
3. 编辑器给一键修正：断点吸附到最近的合法词边界（复用 `manual_final_subtitle_editor.py:7418`
   的重切路径，不新造算法）。
4. 修日志轮转（或改 `delay=True` / 独占写入），并让"保存被拦"写一行含 code 与页号的日志——
   现在这类失败在盘上除了 generation 目录之外没有任何痕迹。

**夹具（现成的，零重跑）**：中式梦核 `generations/20260820T051801385567-af3f4d82`。
门禁：(a) 用该 generation 的输入重放，报错文本里必须出现 `S0078.P01` 与被切开的词；
(b) `token_split` 的判定结果与改动前逐例一致（只多信息、不多不少拦截）；
(c) 全库重放 14 个 generation：PASS/ERROR 结论一条不变；(d) 一项一提交 + 反向补丁。

---

## §40 GPT 进度对账（2026-08-25 23:40，外部审计只读核对）

口径：`git log` / `git diff --numstat --ignore-cr-at-eol` / 读工作区实际代码，
**不采信 `执行进展-给用户.md` 与 `CODEX_STATE.md` 的自述结论**（§33.4 教训：文档与代码曾长期不一致）。
`CODEX_STATE.md` 写于 23:25，其中 "verified HEAD `25bbf33`" 已过期（此后有 4 个提交）。

### 40.1 今天实际落地的提交（HEAD = `f00edc4`）

| 提交 | 时间 | 内容 | 是否在 §37.7/§38 的顺序里 |
|---|---|---|---|
| `898e02f` | 09:58 | 失败的 stable-checkpoint 保留可见"重试"入口（`subtitle_interface` +359） | 否，但**与 S0/S0b 同一痛点**，合理 |
| `380864a` | 09:58 | 生词释义按像素排版 | 否，产品侧小项 |
| `97e5e04` | 23:33 | ASR 锚定式语音空档修复（`faster_whisper` / `transcript_thread`） | **否，且是地基层改动** |
| `f00edc4` | 23:33 | 文档归档压缩 | 无关 |

**判定**：`97e5e04` 动的是 ASR，位于所有冻结阶段的最上游，一旦改变英文文本就会改变
LLM 缓存键 → 中文重译（§冻结契约）。它不在计划内，也没有按 §36.3 先登记后测量。
**要求 GPT 补一行说明**：该改动在既有 62 集上是否改变任何 `original` 文本？若改变，
必须列出集数，且**永不可对已人工校对集重跑**。

### 40.2 工作区未提交的改动（这是今天真正的主体）

```
app/core/utils/podcast_learning_video.py            +220 / -11
app/core/subtitle_processor/manual_final_subtitle_editor.py  +242 / -28
app/core/subtitle_processor/screen_editor.py        +120 / -16
app/core/subtitle_processor/stable_display_page_contract.py    2 / 2
app/thread/video_synthesis_thread.py                  +6 / -1
app/view/video_synthesis_interface.py                 +6 / 0
tests/（4 个文件）                                  +177 / -21
```

逐个读过之后，这里面**混着至少三件互不相关的事**：

**(a) S0（阻塞降级）已按规格写出来了。** 过滤区已从 §37.2 的 6134-6145 迁到
`podcast_learning_video.py:6247-6259`，新增 6284-6336 的 `fallback_review_candidate` /
`"candidate_mode": "review_fallback"` 路径，配套新函数 `_article_manual_review_break_rank()`
（标点优先 → `subject_finite_verb_split` → 惩罚 `dangling_coordinator_page_split` →
回落 `_article_page_break_rank(allow_review_boundary=True)` → `_article_manual_override_break_rank`），
并把 `prefer_punctuation_for_manual_review` 贯穿 `_partition_article_english_pages`。
**符合 §38.1 的五条门禁精神**：只做兜底种子、issue code 保留、正式路径仍然 BLOCKER。
**但尚未提交、无反向补丁、只跑了定点夹具（日本集 S0001=3 页 / S0242=2 页），
62 集棘轮与全库回归都没跑。** 按 §36.3.4 这不算兑现。

**(b) 保存失败的另外两条真因，GPT 独立找到并已修（也未提交）。** 与 §39 互补，不重叠：
- `_reconcile_frozen_display_page_timing()`（新增于 2276-2358）：删除字幕后时间轴压缩，
  但冻结的分页方案仍持有原媒体时间 → 页区间倒置 → 保存被拦。夹具是白宫集。
- `_reuse_source_page_translations()`（新增于 8733-8822）：**确认分页边界这个动作本身会清空该页中文**，
  于是保存报 `manual_page_translation_required`。—— 这正是 §39.1 表里中式梦核 05:14 那一次的 code。
  新逻辑只在"页身份完全未变且无未确认的手动 override"时恢复投影，其余仍要求人工补中文，方向正确。

**(c) 我在 §39.2 指出的可诊断性问题一条都没动。** 现读 `manual_final_subtitle_editor.py:9479-9480`，
`render_block_reason = "manual_page_translation_invalid"` 仍然把 `errors[]` 折叠成一个字符串、页号照旧丢弃；
`user_facing_issue_text.py:126` 的文案仍无页号；保存被拦仍不写日志；`app.log` 仍停在 08-23 05:43。
→ **S0b 全部四项仍然开放**，且现在更划算：(a)(b) 修完之后剩下的失败会以 token_split 这类为主，
而那一类**恰恰是消息里看不出位置的那一类**。

**(d) 违反 §33.8「一项一提交 + 反向补丁」。** S0（切分层）与保存修复（编辑器层）现在纠缠在同一个工作区，
一旦其中一件出问题无法单独 `git revert`。**这是我在 §33 已经点过一次的同型问题，第二次发生。**
要求：至少拆成 S0 / 保存时间轴对齐 / 页中文恢复 三个提交，各带 `rollback/*.revert.patch`。

### 40.3 GPT 自述中值得采信的三条测量（我认可其口径，未复算）

1. **短父连锁语义信号已被测死并放弃**：读 26/120、召回 4/24、虚警 22 → 与我 §29.4 两个死信号同类。
   记入棘轮清单的"别再试"栏。
2. **S1 的跨父保守候选（spaCy）**：ledger ∪ 该候选 = 召回 22/24 = **91.7%**，读取 40/120 = **33.3%**。
   与 §36.3 记的数一致；S0094/S0103 属切点证据不可达，与 §37.11 漏项名单吻合（S0103 最长页 <70 也逃掉）。
   → **S1 仍是分诊腿收益最大的一项**，且应与 §37.4 清单瘦身、§37.11 淡色档同批。
3. **翻译提示词（S2）已经上线，缓存版本升到 v8/v5/v10。**

### 40.4 S2 抢跑造成的一个硬后果（必须写下来）

§38.3.1 定的顺序是 S0 → S3'(容量线 26→22) → S2(提示词) → S1。**S2 提前上线了。**
后果不是"顺序洁癖"，是三条实际损失：
- 缓存键一升，**盘上所有 `测试音频` 产物都是旧版 v7/v4 生成的**，无法用来验证提示词是否真的把语气词补回来；
- §36.3.3 的棘轮项「页中文中位/p90 改后不得上升超过 2 字」**从未核对**，
  而语气词补回来天然让中文变长 → 这正是容量线该先落地（26→22）的原因，现在反了；
- S2 的收益靶子是 §37.3 那 **3.6% 纯措辞地板（日本集 15 个漏标里的 9 个）**，
  只有在新集上重测 E/R/Rec 才能看出来。

→ **裁定：S2 现在处于"已上线但未验证"状态，不得计入已兑现项**；
若下一集实测页中文 p90 越线，按 §36.3.5 自动进回退议程。

### 40.5 结论：接下来的顺序（覆盖 §38.3.1，理由见上）

| 序 | 工单 | 状态 | 缺什么才算兑现 |
|---|---|---|---|
| 0 | **拆提交 + 反向补丁** | 未做 | S0 / 时间轴对齐 / 页中文恢复 三个独立提交 |
| 1 | **S0 阻塞降级** | 代码已写 | 62 集棘轮（新增 None=0、空页=0、确定性）+ 全库回归 + 日本集正式路径复跑 |
| 2 | **S0b 保存可诊断性** | 未动 | §39.5 四项 + 夹具 `20260820T051801385567-af3f4d82` |
| 3 | **S3' 容量线 26→22** | 未动 | §37.5：两集 16 标 8/10，读取 +4% |
| 4 | **S1 + 清单瘦身 + §37.11 淡色档** | 未动 | 同批提交；门禁 读 ≤35%/≤45%、召回 ≥74%/≥75%、深色只减不增 |
| 5 | **S5 新集对账** | **卡在输入上** | 见下 |

**唯一的关键路径输入：一集全新、从未人工校对过的音频，用 v8/v5/v10 跑完整流水线。**
它同时是三件事的唯一来源：S2 提示词能否验证、下一个 E/R/Rec 数据点（前两集口径不同不可连趋势）、
§37.11 长度阈值定值所缺的第三集。**没有它，1–4 全部只能停在"代码写完、未兑现"。**
GPT 自述的一次重试在 6/29 批次上撞供应商 HTTP 500 而中止 —— 这属外部因素，不算失败，但说明
这一集必须显式排进议程、并允许分批续跑。

---

## §41 「拆解白宫所谓的中国转运骗局」丢词问题复核（2026-08-26，用户要求核对）

用户原话：「因为'拆解白宫所谓的中国转运骗局'有字母丢失问题在 s104 的这一行上，然后我让它修了之后重新跑了，并且也修好了」。
盘上有两次 stable-run，同一集、同一音频，构成一次**天然 A/B**：

| | 10:01 `0e2a1e05` | 22:55 `c92f6efe` |
|---|---|---|
| `code_commit` | `380864a` | `380864a`（同一个，见 41.4） |
| `cache_used` | True | **False（全量重跑 ASR + 重译）** |
| 父字幕 / 词账本 | 200 / 2126 | 203 / 2149 |
| `validation_status` / `render_blocked` | passed / False | passed / False |
| 翻译提示词（请求账本实测） | `translation_v7` | **`translation_v8`** |

### 41.1 真正的缺陷不在 S0104，而是整整一句被吞掉

S0104 两次运行的英文逐字相同（`Well, I mean, building a plastic casing, attaching the blades, and wiring a control board around a bare motor?`），
分页也相同（P01/P02），**没有任何字母丢失**。用户记的 ID 不准，但他察觉到的问题是真的，在 **S0141**：

- 旧运行 S0141 = `Right. He objects to goods that have, and again, I'm quoting, Wait, wait, wait.`
- 新运行 S0141 = `Right. He objects to goods that have, and again, I'm quoting,`，其后完整补回 **26 个词**：
  `China origin inputs or components, Chinese ownership or financing, relationships with Chinese suppliers or manufacturers, China-based production steps, or China origin routing histories.`

**这是全文唯一的实质差异**（整篇 12693 → 12880 字符，逐字符 diff 只有这一处插入 + 41.3 那一处）。

### 41.2 为什么它此前既没被拦下、也不可能被人眼发现（本项目目前最危险的一类）

词账本坐实了机制：旧运行 `quoting,` 收在 494830ms，紧接着 `Wait, wait, wait. So, if a factory in`
被塞进 495251–496752ms，然后 `Malaysia` 直接跳到 **509240ms** ——
即**整集唯一一处 ≥1.8s 的词间空档：`in` → `Malaysia` 之间 12.49 秒**，而且横在一个句子中间。
新运行同一区间被 26 个词正常填满，`Malaysia` 锚点 509240ms 不变，**≥1.8s 空档数 = 0**。

**旧运行的三重掩护**：
1. 质量校验 `passed`、`render_blocked=False`、错误码 `[]`；
2. `editor-review-ledger.json` 39 条标记里，**S0140–S0142 一条都没有**；
3. 中文把丢掉的清单顺手抹平成 `他反对的是那些……我引用原文，等等等等。` —— **读起来毫无破绽**。

→ **这类缺陷（丢词 + 时间戳被压缩重用 + 中文自动圆场）是他逐条肉眼校对也发现不了的**，
与 §37.10 记的漏译同属"必须靠机器守恒律拦"的类别。**`97e5e04` 的门禁设计（1.8–15s 有声空档未修复就在英文冻结前停机）
正命中这个案例**：12.49s 落在窗口内。→ 撤回 §40.1 把它称为"计划外地基层改动"的措辞，
它是对用户报障的正当修复；但 §40.1 那条要求仍然有效（不得对任何已校对集重跑）。

### 41.3 新运行引入了一处新错（他必须改，位置已被清单标出）

`S0160 = And Over look at what they actually include in this so-called shadow network.`
—— `Over` 从上一句 `Over 70%.` 里跑掉了，上一句在新运行变成只剩 `70%.`（S0159）。
词账本显示该窗口的 `And / Over / look` 三个词的 `alignment_source` 由旧运行的 `whisperx`
变成 `stable-ts-fallback+final-ledger-boundary-reconciled`，即这一小段是回退解码的产物，
与 41.2 的空档修复不在同一位置（558s vs 495–509s），属**整集重转录的独立副作用，不是修复引起的**。

**好消息：清单两条都标出来了**，其中一条还猜对了原因：
`english_boundary_audit / incomplete_short_fragment：70%. | And Over look at…` 与
`model_asr_suspicious：英文"And Over look"疑似ASR错误，可能应为"And also look"…，中文"再看看"合理，但英文原文不自然。`
→ **处置：手改这一条英文即可，不要为此放宽任何判定。**

### 41.4 归因的诚实边界：无法从产物证明是修复起的作用

两次 run 的 `code_commit` 都是 `380864a`，而 ASR 修复提交于 **23:33**，晚于 22:55 的运行。
但工作区文件 mtime 为 `faster_whisper.py` 21:42、`transcript_thread.py` 20:56，**都早于该次运行**；
且 `translation_v8` 是**仅存在于工作区的未提交改动**却出现在该次请求账本里 →
**当时运行的是工作区代码，ASR 修复极可能已生效**。
无法进一步证明的原因是：**修复成功时不往任何冻结产物里留痕**（新增的 `last_compressed_timing_repairs`／
`unresolved_internal_gap_candidates` 只挂在内存对象上）。

**工单 S0c（便宜且一次性解决可核查性）**：修复补回的词在 `word-ledger.json` 的 `alignment_source`
上加后缀（如 `+internal-gap-retry`），并把本次修复证据写进 run artifacts。
词账本本来就逐词记 `alignment_source`，这是顺水推舟；做完之后这类核对是一行命令，而不是今天这样的取证推断。
**另：`code_commit` 记的是 HEAD 而非实际加载的代码，本次已造成误判风险 → 建议同时记录关键源文件的 mtime/哈希。**

### 41.5 顺带把 §40.4 的 S2 验证做掉了（同集同音频 A/B，这是能拿到的最干净口径）

`translation_v7`（10:01）vs `translation_v8`（22:55），同一集、同一音频：

| 指标 | v7 | v8 | 判定 |
|---|---|---|---|
| 英文以语气词/话语标记开头的父 | 67 | 67 | 分母相同 |
| 其中中文也保留了标记 | 14 = **21%** | 50 = **75%** | **靶子命中**（§37.3 的 3.6% 措辞地板正是这类） |
| 每页中文字数 中位 / p90 / max | 11 / 17 / 20 | 11 / 17 / **21** | **§36.3.3 容量棘轮通过**（≤ +2 字） |
| 整条中文字数 中位 / p90 / max | 14.5 / 25 / 36 | 15 / 26 / 36 | 通过 |
| 逐页中文为空的页 | 0 / 71 | 0 / 73 | 通过 |

→ **S2 从"已上线未验证"升为"提示词确实把语气词补回来了，且没有把中文撑长"**。
仍未兑现的只剩一件：**这是否让他少改**（需要他校对这一集出 E/R/Rec）。
更正 §40.4 的措辞：不是"无法验证"，是"观看质量方向已验证、E 收益待他校对"。

### 41.6 这一集就是 §40.5 卡住的那个输入（但只解锁一半）

它是全新、从未人工校对、`cache_used=False`、v8 提示词的完整自动结果
→ **S5 对账与 §37.11 长度阈值第三集的输入已经在盘上了。**
但 **`podcast_learning_video.py` mtime 23:57，晚于 22:55 的运行 → 本次运行不含 S0，也不含 S3' 的容量线 26→22。**
所以：**能验 S2、能出 E/R/Rec、能定长度阈值；不能验 S0 与 S3'。**

本次清单口径（供他校对后对账用）：**43 条标记 / 38 个父 = 读取率 18.7%，0 条 BLOCKER**。
其中已确认为真错的至少四条：S0160 语序（见 41.3）、`S0121` 的 `303 billion` 数字对应偏差、
`S0095` 标签与风扇的位置关系被弄反、`S0013` 逐页中文顺序倒置。
→ **建议他先只改这几条，然后直接合成，不要重跑。**

### 41.7 「And Over look」这一类怎么系统解决：证据已经在词账本里，是清单规则漏了它

用户问「这种怎么解决呢」。**不要试图把 ASR 做对**（chunk 接缝处的词错位是概率性的，必然复发），
正解是**让这种位置必然出现在清单上**。证据本来就是逐词记录的确定性信息：`word-ledger.json` 的 `alignment_source`。

**实测（22:55 那次运行）**：`stable-ts-fallback` 词 40/2149 = 1.9%，
**含至少一个回退词的父字幕 = 11/203 = 5.4%**：
`S0023 S0036 S0048 S0051 S0136 S0137 S0138 S0158 S0159 S0160 S0183`
—— **出错的 S0159 与 S0160 都在里面**，S0160 有 5 个回退词（`And Over look at what`）。
10:01 那次是 9/200 = 4.5%，其中 `S0156`＝当时的 `Over 70%.` —— **同一个声学难点两次运行都被回退命中，说明这个信号跨运行稳定**。

**为什么这次没标出来（已读代码定位）**：`subtitle_review_marks.py:507-558` 的 `_final_timeline_fallback_marks`
有两道过滤，两道都把它挡掉了：
1. 只看**该条字幕的首词与末词**（`edge_words = (ledger[word_start], ledger[word_end])`，529 行）
   → S0160 内部的 `Over/look/at/what` 根本不看；
2. 即便命中首词，还要求该词时长 **≤40ms 或 >1500ms**（542-549 行）
   → S0160 首词 `And` 是回退词但 570ms，S0159 的 `70%.` 是回退词但 520ms，**双双被过滤掉**。

**工单 S0d（只加标记，无可弄坏项，与 §37.4 清单瘦身同批提交）**：
把该规则从"首末词 + 异常时长"改为"**本条字幕含任一 `stable-ts-fallback` 来源的词**"；
时长条件降级为严重度区分（异常时长 → 建议试听；正常时长 → 建议核对英文原文措辞/词序）。
**实测代价与收益**：本集标记 1 → 11 条（读取率 18.7% → 约 21%），
命中的 11 条里已确认含真错的至少 3 条（S0159+S0160 同一处词错位、`S0051` 的 `American`→`America’s`，
后者本来就被 `article_asr_correction_review` 独立标了），**精确率约 27%，远高于本集清单均值**。
门禁：(a) 本集必须标出 S0159 与 S0160；(b) 全库 62 集读取率增量 ≤5pp；(c) 不得新增任何 BLOCKER。

**必须与 41.2 那一类分开记账**：丢词案（S0141）的词全部是 `whisperx`，**回退信号抓不到它**；
它靠的是 12.49s 有声空档门禁（`97e5e04`）。
→ **两张网各管一类：空档门禁管"词被吞掉"，回退来源标记管"词被搞乱"。两者都需要，不可互相替代。**

## §42 翻译层还剩多少收益：两集已校对集的改动构成拆解（2026-08-26，用户问"翻译还有必要继续优化吗"）

### 42.1 样本与口径

**入选（认真校对、有完整 `before_parent_states` 链）**

| 集 | 产物 | 父数 | touched | E |
|---|---|---|---|---|
| 测试音频-当前代码 | `stable-runs/20260824T201840.701773-2290bd40/人工终稿字幕包/generations/20260824T230018847331-f5cc2294/人工终稿字幕-edits.json` | 120 | 23 | 19.2% |
| 无论怎么衡量，就业市场都很疲软 | `stable-checkpoints/20260821T145313.192574-4fbdb7bc/.manual-editor-drafts/5bde47bdb7ca48fdb4e65ae6.json` | 238 | 28 | 11.8% |
| **合计** | | **358** | **51** | **14.2%** |

**排除**：`日本X世代的困境：被反复诅咒的一代人`（241 父 / touched 2）与
`白宫对中国转运骗局的荒谬指控`（217 父 / touched 3）两份草稿——其 touched 父的终稿中文为空，
是 §37 中文停产 / §39 未保存的残件，不是校对量，不能进分母也不能进分子。

**方法**：每父取最早出现的 `before_parent_states` 为自动基线，与终稿 `cues` + `display_page_edits` 比对；
比较前统一剥离标点与空白（`，。、；：？！""''（）()…—-·《》` 与空格）。
`测试音频` 两个 generation（22:15 / 23:00）跑出完全相同的分类结果，口径自洽。

### 42.2 改动构成（按父计，一父只归一类，优先级 A>B>C>D>E）

| 类别 | 测试音频 | 就业市场 | 合计 | 占全集 |
|---|---|---|---|---|
| A 英文文本被改 | 0 | 3 | 3 | 0.8% |
| B 中文总量不变，只随分页重新分配 | 6 | 9 | 15 | 4.2% |
| C 页中文为空 → 他补齐 | 4 | 5 | 9 | 2.5% |
| D 中文不完整 / 多余（一方是另一方子串） | 2 | 4 | 6 | 1.7% |
| E 中文实质改写 | 11 | 7 | 18 | 5.0% |

**第一个要记住的数**：英文只被改了 3 条 / 358（0.8%）。
他在终稿编辑器里的时间，96% 花在中文和分页上，不在英文上。

### 42.3 E 类 18 条逐条读完：**没有一例是意思译错**

单页父只占 4 条（`测试音频 S0093/S0104/S0105`、`就业市场 S0043`），全部是风格 / 字面度取舍：

- `S0105` 机器「只要你做的不只是换个标签。嗯」→ 他「一旦你做了超出单纯更换贴纸之外的任何操作。」
  （机器那版中文更顺；他要更贴英文字面，因为这是教学视频，要能逐词对上）
- `S0093` 「承载着很重的分量」→「承担了关键作用」，并补回被丢的 `Okay`→「好吧」
- `就业市场 S0043` 只是删掉一个冗余的「确实」

其余 14 条全部落在多页父上。
→ **父级整句翻译（`translation-v8`）已经没有可测的质量债务。剩下的中文成本几乎全在分页层。**

### 42.4 病因定位：`translation-v10` 为迁就英文页序，主动打乱了中文语序

`display-page-translations.json` 的每个多页父同时存着两串中文：
`source_parent_chinese`（父级权威中文）与 `aggregate_chinese`（各页 `zh` 拼接）。
标点归一化后两者不等，就说明 v10 重排过语序。**这是零成本的现成证据，不需要新记任何东西。**

| 集 | 多页父 | 被重排 | 比例 |
|---|---|---|---|
| 拆解白宫所谓的中国转运骗局（v8 新运行 `20260825T225507`） | 34 | 13 | 38.2% |
| 测试音频-当前代码 | 32 | 9 | 28.1% |
| 无论怎么衡量，就业市场都很疲软 | 24 | 7 | 29.2% |

**逐条读完 29 例的结论：父级那一版全部通顺正确，页版全部更差或持平，没有一例页版更好。**举证：

- `就业市场 S0170` 父「只计算在地方政府正式登记失业的人数。」
  → 页「只计算**人数**在地方政府正式登记失业的**人数**。」（同一个词被抄了两遍，与 `S0045.P02`「中国商品商品」同类）
- `就业市场 S0213` 父「它捕捉了近1300万真实的人在变化就业市场中的复杂现实。」
  → 页「它捕捉了近1300万真实的人的复杂现实在变化就业市场中。」（洋泾浜倒装，他原地改回）
- `白宫 S0104` 父「给裸电机加上塑料外壳、装上叶片、接好控制板」
  → 页「加上塑料外壳、装上叶片，**给裸电机**接好控制板」（「给裸电机」挂到了错的动词上，**语义已变**）
- `白宫 S0122` 父「这占2018年美国自华进口总额的56%」
  → 页「这占到了56%，离谱——2018年美国自华进口总额」
- `白宫 S0095` 父「如果你现在看看桌上风扇的标签……」
  → 页「如果你看看标签现在就在你桌上风扇上。」（内置 LLM 审计已独立判定为 `english_chinese_mismatch`）

**必须与 §37.x 分开记账**：分页边界本身没有错，切分层也没有错。
错的是"同一批英文页之下，中文该不该跟着倒装"这个决策。这是 v10 提示词的层级，不是切分层。

### 42.5 交叉验证：重排到底是不是他动手的原因

| 集 | 被重排父 | 其中他动过 | 精确率 | 他没动的 |
|---|---|---|---|---|
| 测试音频 | 9 | 6 | 67% | S0023 S0028 S0031 |
| 就业市场 | 7 | 5 | 71% | （2 条） |
| 合计 | 16 | 11 | **69%** | |

**69% 高于清单整体 Rec 51.6%**（§37）。反向看：他的 18 条实质改写里有 7 条落在被重排的父上。

### 42.6 现有清单对这一类的召回只有 15%

白宫 v8 清单：43 条 / 38 父 / 读取率 18.7%。其中中文类只有 7 条。
对 13 个被重排的父，只命中 2 个——`display_page_chinese_order_review` 命中 `S0013`（1/13），
内置 LLM 审计以 `model_english_chinese_mismatch` 命中 `S0095`。**召回 15.4%。**

漏掉的 11 个：`S0006 S0051 S0104 S0112 S0122 S0156 S0169 S0174 S0176 S0188 S0203`。
其中 `S0104`、`S0122` 是语义已受损的真错，且这一集他还没校对——**如果不加规则，这两条会直接合成进片子。**

### 42.7 工单 S3''：翻译侧唯一还值得做的事，分两步

**(a) 清单侧——先做，便宜、零风险、不改任何产物**

新增规则 `display_page_chinese_reordered`：多页父满足
`norm(aggregate_chinese) != norm(source_parent_chinese)` 即出 `REVIEW`，`category="chinese_coherence"`。
**理由文案里必须把 `source_parent_chinese` 原文带出来当建议值**——因为父级那一版就是正确答案，
不带出来就等于把成本从"发现"搬到"重新打字"。
同时提供一个动作：**按词界把父级中文重切回各页**（不重新调 LLM，纯字符串切分 + 词界对齐）。

- 实测代价：白宫 v8 标记 38 父 → 49 父，读取率 18.7% → 24.1%（+5.4pp）
- 实测精确率：69%（两集 11/16）
- 门禁：(a) 本集必须标出 `S0104` 与 `S0122`；(b) 全库 62 集读取率增量 ≤6pp；(c) 不得新增任何 BLOCKER；
  (d) 已被 `display_page_chinese_order_review` 命中的 `S0013` 不得重复出条目

**(b) 生成侧——改 `translation-v10` 提示词，必须过容量棘轮**

把"每页中文对齐每页英文"从硬约束降级为软偏好；硬约束改成
**"整父中文的语序必须与父级权威中文一致，只允许在词界处切断，不允许调序、不允许重复用词"**。

- 门禁：容量棘轮（页中文中位/p90 涨幅 ≤2 字，现基线 12/17）；重排率 38.2% → ≤10%；
  `display_page_chinese_order_review` 命中数不增加；语气词保留率不低于 §41.5 的 75%；空页中文仍为 0
- **禁止在任何已校对集上验证**（重跑会冲掉他的校对，见 §40.1）

### 42.8 顺带测出的两笔非翻译账

**(1) `chinese_review_required` 误报，占全集 1.1%**
C 类 9 条里有 4 条，他打开后原样重敲了父级中文，终稿与自动结果标点归一化后**完全相同**：
`测试音频 S0062`、`就业市场 S0029 / S0061 / S0223`。
（例：`S0062` 父级「应用立刻帮我绕过拥堵，」→ 终稿「应用立刻帮我绕过拥堵，」，一字未变。）
这 4 条是**标记精确率问题，不是翻译问题**。另外要注意：这 9 个父在生成时都是**单页父**，
根本不在 `display-page-translations.json` 里，页中文为空是"无人工覆盖"的正常状态、渲染时回落父级中文；
所以这一类的真实成本不是"中文丢了"，而是"被 `chinese_review_required` 叫过来看了一眼却无事可做"。

**(2) 父级中文在相邻两父之间分配错位（`allocation-v5`），每集 1-2 例**
`测试音频 S0106/S0107`：`S0106` 英文只有 `Rejigging your corporate supply chain`，
父级中文却是「重组企业供应链，合法变更产品原产国」（把 `S0107` 的内容吞进来了）；
`S0107` 父级中文「只为降低关税负担」反而缺了那部分。他分两次手动重切（22:08:29 → 22:08:50）。
这是分配层的账，不是翻译质量的账。

### 42.9 内置翻译质量审计自己是半死的（这条优先级高于改提示词）

白宫 v8 `translation-quality-audit.json`：

- `status = "PARTIAL"`，`audited_subtitle_count = 83 / 203`，`unaudited_subtitle_ids` 共 **120 条**
- `batch_errors` 7 条，全部是 `translation_quality_audit_request_failed`
  （`accuracy_asr` / `fluency_page_load` / `continuity_mapping` 三个 focus 在前两批全灭，第三批 `accuracy_asr` 再灭一次）

**即：这一集有 59% 的字幕从来没被自动翻译审计看过。**
而它看过的那 41% 里就抓出了 `S0095`——本集最严重的重排案。
→ **先修重试/降批/单条兜底，比改提示词划算得多**，这是同样成本下召回涨得最快的一处。

精确率泄漏一例：`model_number_or_negation_error` 对 `S0120/S0121` 的 `reason` 自己写着
「两行相邻，数字不同，中文均正确，无错误」，却照样生成了 item 并进了清单。
→ 模型结论为"无错误"时不应出条目（在解析层加一道自证矛盾过滤）。

### 42.10 完成率账：直接回答"翻译还有必要继续优化吗"

当前两集合计 **E = 14.2%**，即自动化完成 **85.8%**。可回收的部分：

| 来源 | 父数 | 占全集 | 归属层 |
|---|---|---|---|
| D 中文不完整/多余 | 6 | 1.7% | 分页中文 v10 |
| E 里落在被重排父上的 | 7 | 2.0% | 分页中文 v10 |
| C 里非白做的 | 5 | 1.4% | 分页中文 v10 / 分配层 |
| `chinese_review_required` 误报（§42.8-1） | 4 | 1.1% | 清单精确率 |
| 分配错位（§42.8-2） | 2 | 0.6% | `allocation-v5` |
| **合计可回收** | **24** | **6.7pp** | |

→ 上限：**E 降到约 7.5%，完成率约 92.5%，落在他要的 90-95% 区间内。**

剩下的约 7.5% 拆开：B 类 4.2% 是分页/切分成本（§37.x 的账）、
A 类 0.8% 是英文/ASR（§41.7 的账）、E 里的单页风格改写 1.1% **不可自动化**（是他的教学取舍，机器没错）、
其余为零散。

**结论（三句）**

1. **父级整句翻译不要再优化了。**两集 358 父里零事实错译，唯一的父级层改写全是风格取舍，属于不可回收成本。
2. **分页中文（v10）值得做，而且是翻译侧唯一还能把完成率推进目标区间的动作**：
   它现在有 28-38% 的多页父被主动倒装，其中 69% 他会动手，语义受损的比例约每集 2 条。
3. **顺序是 §42.9 → §42.7(a) → §42.7(b)**：先让自动审计别再半死（59% 未审），
   再加零风险的重排清单规则（+5.4pp 读取，69% 精确率），最后才动提示词（需容量棘轮 + 一集全新音频）。

---

## §43 翻译提示词 v7→v8 的 A/B 实测（白宫集同一音频、同日两次运行）

问题：GPT 调整过翻译之后，质量到底提升了没有。这一节用**同一集音频的前后两次运行**直接对照，
不是靠人工校对痕迹反推，也不需要重跑任何已校对集。

### 43.1 对照对的确定（用 `llm-request-ledger.json`，不信 `code_commit`）

| 运行 | 目录 | 父级翻译任务 | 分页翻译任务 | 结论 |
|---|---|---|---|---|
| 旧 | `stable-runs/20260825T100141.604489-0e2a1e05/` | `screen_subtitle_semantic_full_translation_v7` ×7 + `..._unit_v2` ×128（**全部 cache_hit**）+ `style_retry_v1` ×2 | `display_page_translation_v2` ×7 | **调整前** |
| 新 | `stable-runs/20260825T225507.737643-c92f6efe/` | `screen_subtitle_semantic_full_translation_v8` ×23（无 cache_hit） | `display_page_translation_v2` ×7 + `retry_v2` ×1 | **调整后** |

两次运行都在 2026-08-25，同一音频、同一 ASR 源。可比性边界：

- 父级共 200（旧）/ 203（新），同 ID 200 条；
- 其中**英文完全相同 140 条**，英文变了 60 条（`S0141` 起全部下移，即 §41.4 那次 26 词补回导致的 ID 漂移）；
- **所有横向数字都只在这 140 条上算**，避免把切分改动记到翻译账上；
- 分页层：140 条里两次都是多页的父 **20 条**，只多页于一侧的 **0 条**（分页结构没变，干净对照）。

### 43.2 父级整句：变了多少，保真度有没有退步

| 指标 | v7（旧） | v8（新） | 判定 |
|---|---|---|---|
| 同英文父中文被改写 | — | **123 / 140 = 87.9%** | 改动面很大 |
| 中文为空 | 0 | 0 | 无回归 |
| 英文里有数字而中文缺失 | 0 | 0 | **无漏数** |
| 英文有否定而中文无否定词 | 3（`S0012/S0051/S0103`，均为 `dodge/without` 类误报） | 同 3 条 | 无回归 |
| 相邻重复词（`X X` 2-4 字） | 0 | 0 | 无回归 |
| 中文字数 中位/均值 | 14 / 14.9 | **15 / 15.4** | 容量棘轮通过（≤+2） |
| 中文字数 p90 | 25 | 26 | 通过 |
| 每英文词的中文字数 中位 | 1.44 | 1.50 | 略胀，可接受 |

### 43.3 v8 的真实收益：口语语气词的保留率 28% → 81%

判据（可复算）：英文以 `Right/Yeah/Yes/Exactly/Okay/Well/Wow/Oh/Sure/No/I mean/You know/Like` 开头的父，
中文是否以 `对/嗯/是啊/没错/好/哇/哦/确实/当然/不是/不对/呃/我是说/你知道/正是/就是` 开头。

| | 命中 | 占比 |
|---|---|---|
| 同英文父中英文以语气词开头 | 53 / 140 | 37.9% |
| v7 中文保留 | 15 | **28%** |
| v8 中文保留 | 43 | **81%** |
| v8 新保留 | 28 条（`S0003 S0006 S0008 S0010 S0011 S0014 S0021 S0022 S0023 S0030 S0032 S0044 S0048 S0049 S0051 S0060 S0066 S0075 S0079 S0093 S0100 S0102 S0105 S0111 S0117 S0122 S0125 S0130`） | |
| v8 丢失 | **0 条** | |

→ 与 §41.6 报的 21%→75% 同向同量级（这里口径更严：只看句首、只看同英文父）。
**S2 这一改是成立的，而且没有以任何保真度指标为代价。** 这是 v8 唯一可测量的净收益。

### 43.4 父级质量人工读判：123 条改写全部读完

我把 123 条改写逐条读了。**没有一条是 v8 把意思译错、或 v7 对而 v8 错。** 分布是：

- **明确变好（约 8 条）**：
  - `S0078` v7「通常是在到达最终目的地之前，在中转枢纽。」（介词短语悬空）→ v8「通常先经中转枢纽，再抵达最终目的地。」
  - `S0058` v7「对美出口也在飙升。」漏掉了 `at the exact same time` → v8「对美出口也恰好同步飙升。」
  - `S0002` v7「它被称为"切斯特顿栅栏"。」→ v8「这条法则就叫切斯特顿的栅栏。」（有指代先行词）
  - `S0132` v7「特朗普提到贸易欺诈特别工作组」（`raised` 误解为"提到"）→ v8「特朗普成立的贸易欺诈特别工作组」
- **明确变差（约 4 条，全在语域/信息量，不在语义）**：
  - `S0122` v7「令人难以置信」（对 `improbable`）→ v8「离谱」（口语过头，且"该信源"生硬）
  - `S0013` v7 保留了「深入细节前」→ v8 丢掉了 `before we get into the weeds`
  - `S0118/S0119` v8 相邻两条都用「离谱」（v7 也重复，未改善）
- **其余约 111 条是同义换词**（「文件/报告」「电动机/电机」「扇叶/叶片」等），质量持平。

→ 结论与 §42.3 一致并互相印证：**父级这一层已经没有可回收的质量债**，v7→v8 的差异全部落在"像不像人说话"，
而这正是 v8 想改的东西，也确实改成了。**父级到此为止，别再动。**

### 43.5 代价在分页层：重排率 25% → 35%，零修复

同 20 条两次都多页的父上：

| 指标 | v7 | v8 | 判定 |
|---|---|---|---|
| 被 v10 重排（`norm(aggregate) != norm(source_parent)`） | 5 / 20 = **25.0%** | 7 / 20 = **35.0%** | **退步 +10pp** |
| 两次都重排 | `S0006 S0095 S0104 S0112 S0122` | 同 | |
| **v8 新引入的重排** | — | **`S0013` `S0051`** | 新增 |
| v8 修好的重排 | — | **0 条** | 没有一条被修好 |
| 分页中文字数 中位 / p90 | 10 / 17 | 11.5 / 17 | 容量棘轮通过 |
| 悬挂连词收尾页（全集口径） | 3（4.2%） | 2（2.7%） | 略好 |
| 空页中文（全集口径） | 0 | 0 | 无回归 |

逐条读的结果（页版之间比，不是跟父版比）：

- `S0122` **明确变差**：v7 页版「消息来源指出，这相当于美国 ‖ 2018年从中国进口总额的56%，令人难以置信。」虽倒装但可读；
  v8 页版「对，该信源称，这占到了56%，离谱 ‖ ——2018年美国自华进口总额。」第二页成了悬空名词短语，**上屏就是半句话**。
- `S0112` **明确变差**：v8 页版插入破折号插入语「指出，就这些规则 ‖ ——TPP原产地规则——谈判花了近十年。」，v7 页版是干净三段。
- `S0006` **变差**：v8 页一「嗯，没真正明白就不要拆除。」已经打了句号，页二「当初为什么有人修建它。」变成孤立残句；
  v7 页版跨页仍是一句。
- `S0104` **持平（两版都错）**：v7/v8 页二都把「给裸电机」挂到了后半个动词上（§42.4 已记），父版两次都是对的。
- `S0095` **略好**：v7 页版「标签」出现两次；v8 改掉了重复，但生造了「现在就在你桌上风扇上」——本集内置审计正好抓到了这条。
- `S0013` `S0051` **v8 新坏**：`S0013` 页版把「在讨论一开始／就须严格划定讨论范围」拆到首尾两页且"讨论"重复；
  `S0051` 把「份额」挪到了第二页开头。两条都不算重伤，但都是父版原本没有的问题。

**因果解释**：v8 把父级中文写得更口语、更长（句首多了「对/嗯」，中位 +1 字），
`display_page_translation_v2`（即 `translation-v10`）为了让每页中文对齐该页英文，重排的动机就更强、切点更难放。
**父级越自然，分页层破坏得越多** —— 这正是 §42.7(b) 那条硬约束要解决的问题，而且现在有了 A/B 数据支撑。

### 43.6 清单与自动审计：都没跟上

| | v7 运行 | v8 运行 |
|---|---|---|
| 清单条目 / 命中父数 | 39 / 36（读取 18.0%） | 43 / 38（读取 18.7%） |
| `high_confidence_chinese_semantic_issue` | 3 | **1** |
| `display_page_chinese_order_review` | 0 | 1 |
| 内置翻译审计 | `PARTIAL`，审 **80/200**，批次失败 **7** | `PARTIAL`，审 **83/203**，批次失败 **7** |
| 审计抓到的 | `S0072`（`creeds`→`creds` ASR） | `S0095`、`S0160`、+1 条自证矛盾误报（`S0120/S0121`） |

两点必须记下来：

1. **审计半死的问题在 v8 运行里一模一样**（7 批全失败、约 60% 字幕从未被看过），§42.9 的工单没有任何进展。
   两次运行抓到的问题几乎不重叠（`S0072` 只在旧运行被抓、`S0095` 只在新运行被抓），
   **说明现在抓到什么基本靠运气**，不是能力差异。
2. v8 新引入的 7 条重排里，清单只标出 1 条（`display_page_chinese_order_review`），
   `S0122`/`S0112`/`S0006` 三条上屏就是半句话的，**一条都没标**。与 §42.6 的召回 15% 完全吻合。

### 43.7 直接回答"提升了没有"

**父级整句：提升了，而且是他要的那种提升。**口语语气词保留 28%→81%、零丢失、保真度全项无回归、
容量棘轮通过；123 条改写零错译。父级到此收工。

**上屏效果：净收益接近零，甚至略负。**因为父级变自然的同时，分页层重排率从 25% 涨到 35%，
新坏 2 条、修好 0 条，且最难看的三条（`S0122` `S0112` `S0006`）都是 v8 版更差。
观众看到的是分页版，不是父版 —— 所以**"翻译改好了但视频没变好"是当前真实状态**。

**因此优先级不变，且证据更硬**：§42.9（修审计重试）→ §42.7(a)（重排进清单 + 一键回落父版）→ §42.7(b)（v10 硬约束）。
其中 §42.7(a) 现在有了更强的理由：**它能直接兜住 v8 带来的这 +10pp 重排**，而不必回退 v8。

**验证夹具（给 GPT）**：以上全部指标都可以在这两次运行上零成本复算，脚本在
`outputs/cmp_parent.py`（父级改写+保真度）、`outputs/cmp_fidelity.py`（数字/否定/长度）、
`outputs/cmp_page.py`（分页重排 A/B）、`outputs/pagequal.py`（单次运行页质量）。
做 §42.7(b) 时的 PASS 线：语气词保留率 ≥81%（不得回退 v8 的收益）、重排率 ≤10%、
分页中文中位 ≤13 / p90 ≤19、空页 0、`S0122/S0112/S0006/S0104` 四条页版必须与父版语序一致。
**仍然禁止在任何已校对集上跑。**

## §45 第二十二轮（2026-08-26）：女性集人工终稿逐页复核 ＝ 本轮暴露的缺陷清单

用户要求：把这一轮结果暴露出的问题写成清单，交给 GPT 自己判断「哪些该修、哪些风险太大暂时不动」。
本节即该清单。**§45.7 是可以直接执行的入口，前面几节是它的证据。**

### 45.1 取证对象与数据时点（全部只读，未改任何工程文件）

| 项 | 值 |
| --- | --- |
| 集 | 中国职场女性为何悄然掉队？ |
| 失败运行（基线） | `work-dir/…/subtitle/stable-checkpoints/20260826T040659.244182-79951e43`（04:06，`display_page_translation_invalid`，`render_blocked=true`，`attempts_used=8`，`code_commit 3f28f04b`） |
| 人工终稿包 | 源音频旁 `…-处理结果/人工终稿字幕包/generations/20260826T052301761106-4ce733af`（05:23 生成，**不在仓库 work-dir 内**） |
| 终稿状态 | `display-page-translations.json` = `status PASS`，`planner_version article-fixed-font-pages-v33`，`errors 0` |
| 规模变化 | 306 页 / 271 父 → **302 页 / 267 父**；`contract_hash` 与 `人工终稿分页映射.json` 一致；302 页无缺中文 |
| 音频 | `cut_ms 962617`，派生 m4a 与末页 `end_ms` **完全对齐**（剪口干净） |
| 已合成 | 主片 05:43、英文字幕版 06:04 —— **本轮属于「合成后复核」，不是合成前拦截** |

复核方法：把 `parents[].pages[].zh` 与 `render_plans` 合并成 302 行「本页英文 ‖ 本页中文」（`outputs/merge.py`），
与 04:06 基线逐父对齐，再对 302 页做**逐页人读**＋机械检查（数字丢失、残留英文、中文重复、
长度比、阅读速度、停留时长、容量超线、句末标点）。

### 45.2 人工终稿修好了什么（这部分不需要动代码，用来界定「剩下的才是缺陷」）

共触及 32 个父字幕：28 条改写/重切、4 条删除（`S0219` 并入 `S0218`；`S0269`–`S0271` 随音频剪掉）。

- **6 处词级 ASR 错**：`Huangxi→Huangshi`(S0019)、`rooflessly→ruthlessly`(S0053)、`massive job→jump`(S0060)、
  `Guangxi→Guanxi`(S0088)、`Ms. Macedo→Ms. Dou`(S0101)、`potishing→punishing`(S0128)，
  另有 `Su Du→Ms Dou`(S0178)。
- **1 处断名**：`S0218`「…named Mrs.」/`S0219`「Wu in the source text.」→ 并成一句。
- **约 20 处重切/重并**（`S0007/S0008`、`S0033/S0034`、`S0055`、`S0064`、`S0073`、`S0108`、`S0149`、
  `S0152/S0153`、`S0156`、`S0161`、`S0190`、`S0196`、`S0215`、`S0267`），上屏读感普遍变好。
- **容量没有被改差**：`EN>85` 字符页 33→**31**，最长 114 不变；`CJK>26` 4→**3**，最长 29→**28**；字号档位仍是 52/54/56。
  → **本轮不构成抬容量线的新证据，§37 的 26→22 结论不动。**

### 45.3 本轮**新**暴露的缺陷：人工终稿编辑器层（此前二十一轮全部没测到）

这一层此前只被当作「绕过渲染阻断的逃生口」，从没有人核对过它的产物。本轮 302 页逐页读完后，
发现**它会把人工修改带出新的错误，而且三条保存校验（`_validate_cues` /
`_validate_display_page_boundary_overrides` / `_validate_no_silent_display_page_state_loss`）一条都拦不住**。

**（1）并页时中文是「拼接」而不是「重写」→ 生成病句。已上屏。**
`S0089` 把两页并成 P01/P02 后：

```
04:06 基线  P01 Now, these banquets have been increasingly restricted recently   ‖ 近来，这些饭局日益受到限制，
            P02 by new compliance and disciplinary guidelines,                   ‖ 来自新的合规与纪律准则。
人工终稿    P01 Now, these banquets                                              ‖ 近来，这些饭局
            P02 have been increasingly restricted recently by new compliance …   ‖ 日益受到限制来自新的合规与纪律准则。
```

P02 的中文是两段旧译**直接首尾相接**，成了「受到限制来自…」这种病句（正确形态是
「日益受到新的合规与纪律准则的限制」）。另外 `recently` 已被并进 P02 的英文，
而对应的「近来」还留在 P01 —— 中英分页不对位。

**（2）改英文不会让对应中文失效 → 旧误听的译文残留。已上屏。**
`S0053` 英文已从 `rooflessly` 改成 `ruthlessly`，中文仍是「毫无庇护、冷酷高效」；
「毫无庇护」正是当初把 `roofless(无屋顶)` 直译出来的产物。**英文改对了，错译还在屏幕上。**
同类风险面：本轮 6 处词级 ASR 修正里，只有这一处的中文带了误听痕迹，但机制是通用的 ——
**编辑器不校验「本条中文是否仍与本条英文对应」。**

**（3）同类缺陷只修了其中一处 → 留下孤立称谓页。已上屏。**
`S0177` = `Right. Ms.` ‖「对，女士。」（661 ms），紧接 `S0178` =「窦女士，40出头的科技从业者」。
这与他修掉的 `S0218/S0219`（`Mrs.` / `Wu`）**是同一种断名缺陷**，只是这处的后半截落在了另一个父字幕上，
所以没被一起看见。上屏效果是称谓连报两遍。

**（4）中文句末标点在编辑后丢失：4 条。**
`S0101`、`S0103`、`S0118`、`S0122` 的英文都以 `.` 收句，中文无「。」（同页非续页）。

**（5）单词卡：静默丢卡 + 无去重。**
`normalization_diagnostics` = `raw 20 / accepted 20 / normalized 20 / scheduled 16`
→ **4 张卡生成了但从未排上屏，且 `rejected` 为空、无任何日志**（§44 的「静默丢卡」在正式产物里复现）。
上屏 16 张里还有两组重复：`on paper`(cue 130) 与 `On paper`(cue 139)、
`runway`(cue 213) 与 `full career runway`(cue 256) → **有效卡约 14 张，16 分钟的片子明显偏少**。
`priority` 只有 5(13 张)/4(7 张) 两个值，**§44 的 priority 退化在正式产物里同样复现**。

**（6）单词卡缓存晚于第一次渲染写入。**
主片 05:43 完成，`人工终稿字幕.vocab_cards.json` 05:56 才落盘，英文字幕版 06:04 渲染。
→ 两个成片的卡面**有可能不一致**；旧缓存已被覆盖，无法事后比对。这是流程时序问题，不是算法问题。

**（7）一条正面结论（写下来避免以后重复排查）：删尾父 + 剪音频这条路是干净的。**
删掉 `S0269`–`S0271` 后，末页 `end_ms` 与 `media-derivation.json` 的 `cut_ms 962617` 严格相等，
`decision_hash`/`derived_media_sha256` 齐备，无悬挂 cue、无空洞。**此处不需要任何改动。**

### 45.4 本轮再次确认的旧缺陷（都已定位到 file:line，不是推测）

**（A）整集阻塞的单点根因：`_caption_has_terminal_completion` 只认 `. ! ?`。**
`app/core/utils/podcast_learning_video.py:2792-2795`

```python
def _caption_has_terminal_completion(words: list[str]) -> bool:
    if not words:
        return False
    return bool(re.search(r"[.!?][\"')\]]*$", str(words[-1]).strip()))
```

`S0089` 的 P02 起始词是 `by`（`_article_complete_prepositional_continuation_shape` 在 **2930** 行已把
`by/from/in/into` 列入白名单）、issue 只有 `unsupported_tight_page_transition`（**已在允许集内**）、
剩余 6 词（≥ `ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS = 6`，**221** 行）——
**唯一不成立的条件就是 2947 行的 `_caption_has_terminal_completion(remaining)`，因为这条 cue 以逗号收尾。**

链路：该 flag 为 False → `_article_secondary_review_boundary_is_complete`(**7196-7255**) 返回 False →
`incomplete_review_count` = 1(**6271-6275**) → **6409** 行门禁要求 `incomplete_review_count == 0`
→ 所有候选被拒 → `no_complete_normal_font_page_partition` → 整集失败 → 内置翻译审计
**SKIPPED（0/271 父被审）**。

**推论（比这一集更重要）**：因为整个 review 救援家族（`complete_prepositional_continuation`、
`complete_title_restart`、`forced_complete_to_phrase`、`complete_from_gerund/from_nominal/to_infinitive`、
`complete_participial_restart`、`complete_temporal_adjunct`，见 **7280-7315**）**都串联了这同一个助词**，
所以**任何以逗号收尾的 cue 都无法被救援** —— 这不是一条数据的问题，是一个结构性死区。

**（B）ASR 纠错门禁没有「地名」上下文豁免。**
`app/core/article_context.py:2838-2843` 有 `_context_supported_person_candidate`（人名）、
**2229**（技术词）、**2328**（书名）三个豁免，**唯独没有地名/城市**。
`Huangshi` 的 glossary 类别是 `city`、`final_confidence 0.80`，卡在 **577** 行 `high_confidence = 0.82` 上，
`entity_gate_passed=true`、`grammar_validation` 也过了，仍然只落到 `review_only`
（`_not_applied_reason` → `below_high_confidence_threshold`，**2573**）。

**（C）`_token_looks_entity_like` 的 `len(core) >= 3` 让两字母名字整体隐形。**
`app/core/article_context.py:3120-3133`。`Ms` / `Su` / `Du` 三个 token 全部判为非实体
→ `entity_like_count = 0 < max(2, 3-1)` → **3103** 行 `multi_token_not_entity_like`
→ `Ms Su Du → Ms Dou`（**0.87**，置信度足够）被门禁挡掉，最终只能靠人手改。
**音译的两字母中文姓氏（Su/Du/Wu/Lu/Yu…）是这条规则的系统性盲区。**

**（D）人工复核清单被高置信churn噪声占满。**
女性集 `review_only` 清单 10 条里 **8 条是 maternity↔paternity 的来回改写（0.81）**，
真正有价值的 `Ms Dou`(0.87) 根本没进清单（被 C 挡在更前面）。
→ 清单的信噪比使它实际不可用。

**（E）`abbreviation_name_split` 只作用于换行，不作用于 cue 边界。**
`podcast_learning_video.py:512-520` 的 `ARTICLE_LINE_ATOMIC_BOUNDARY_ISSUES` 含 `abbreviation_name_split`，
但它只保护**行内折行**。所以 `S0177`「Right. Ms.」和 `S0218/S0219`「Mrs.」/「Wu」这种
**跨 cue 的称谓断裂完全不受约束**。可复用的 token 集已经存在：**4018-4029** 行 `ends_sentence` 里的
`{dr, jr, mr, mrs, ms, prof, sr, st, vs}`。

**（F）本轮最硬的新数字：运行自带质检队列的召回只有 50%，词级 ASR 错更只有 1/6。**

| 口径 | 数 |
| --- | --- |
| 他实际动手修的父字幕 | **32** |
| 运行自带队列（`字幕质检队列.srt` ∪ `字幕语义复核队列.srt`）总条目 | **81** |
| 32 条里被队列标出的 | **16 → 召回 50%** |
| 81 条里最终被采纳修改的 | **16 → 精确率 20%** |
| 6 处词级 ASR 错里被队列标出的 | **仅 `S0128` 1 处 → 17%** |
| 队列漏掉的（他自己找出来的） | `S0007 S0019 S0033 S0034 S0053 S0060 S0088 S0101 S0136 S0149 S0152 S0153 S0218 S0219 S0267 S0269` |

**结论**：队列漏掉的那一类有共同特征 —— **误听成了另一个合法英文单词**
（`rooflessly/job/Guangxi/potishing/Macedo/Huangxi`），拼写检查、语法检查、置信度全都不报警。
这正是队列现在完全不覆盖的类别，也是 §42.9「审计半死」之外**独立的一条召回缺口**。
（两份队列的 mtime 都是 04:06，即**失败运行**的产物；终稿保存后并未重新生成质检队列 —— 附带问题。）

### 45.5 缺陷清单（GPT 按此逐条判「改 / 暂不动」，禁止直接开工）

编号规则：`W` = 本轮女性集（women）。风险栏是**我的初判**，GPT 必须自己复核后给出结论。

| 编号 | 现象（可复现） | 根因位置 | 建议改法 | 我的风险初判 | 我建议优先级 |
| --- | --- | --- | --- | --- | --- |
| **W1** | 逗号收尾的 cue 永远进不了 review 救援 → `S0089` 一条卡死整集 271 父，翻译审计 0/271 | `podcast_learning_video.py:2792-2795`（被 7196-7255、7280-7315、6630-6668 共同串联） | 给该助词加一个**受限**的第二形态：仅当剩余词数 ≥ `ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS` **且** 该页 `issue_codes ⊆ existing_continuation_issues` **且** 下一页首词在 `ARTICLE_PAGE_PHRASE_START_WORDS` 时，允许以 `,` 收尾视作可接受。**不要改正则本身**（它被别处复用），新增独立判定函数 | 中。放宽门禁必然让一部分本该被拦的边界通过，是**交换不是净赚**，必须靠 A/B 数字确认 | **P0**（唯一能把整集从「不可渲染」拉回「可渲染」的一条） |
| **W2** | 并页时中文首尾直接拼接 → 病句（`S0089.P02`「日益受到限制来自…」） | 人工终稿编辑器保存路径：`manual_final_subtitle_editor.py`，三条 `_validate_*` 均不检查中文 | 加一条**保存期断言**（先只报警不阻断）：若某页中文是其原分页中文的**字符串直接串联**且串联点两侧不成句（缺连接成分/出现「受到…来自」类断裂），标进清单 | 低（只加检查，不改数据） | **P1** |
| **W3** | 改英文后中文不失效 → `S0053`「毫无庇护」残留 | 同上，编辑器无「本条中文 vs 本条英文」一致性校验 | 保存期比对：英文被编辑过的 cue，若其中文**未同时被编辑**，一律进清单（不阻断保存） | 低 | **P1** |
| **W4** | 跨 cue 称谓断裂不受约束 → `S0177`「Right. Ms.」孤页、`S0218/S0219`「Mrs.」/「Wu」 | `podcast_learning_video.py:512-520` 的 `abbreviation_name_split` 只管折行 | 在 cue 边界判定里禁止「以 `{dr,jr,mr,mrs,ms,prof,sr,st,vs}` + `.` 结尾」成为边界；token 集直接复用 **4018-4029** 行 `ends_sentence` 里的那一份 | 低（是收紧不是放宽，且集合已存在） | **P1** |
| **W5** | 单词卡 `scheduled 16 < normalized 20`，4 张静默丢弃、`rejected` 空、无日志 | 单词卡排期层（`normalization_diagnostics` 出处） | 丢卡必须写 `rejected[reason]` 并计数；`scheduled < normalized` 时在成片日志里显式告警 | 低（纯可观测性） | **P1** |
| **W6** | 单词卡不去重：`on paper`(130)/`On paper`(139)、`runway`(213)/`full career runway`(256) | 同上 | 归一化阶段按 casefold + 词形包含关系去重，保留 `priority` 高者、`cue_index` 小者 | 低 | **P2** |
| **W7** | 中文句末标点在人工编辑后丢失：`S0101 S0103 S0118 S0122` | 编辑器无标点一致性检查 | 保存期检查：英文以 `.!?` 收句而中文无 `。！？` 且非续页 → 进清单 | 低 | **P2** |
| **W8** | ASR 纠错无地名豁免 → `Huangshi`(city, 0.80) 只能 `review_only` | `article_context.py:2838-2843` 旁缺 place 分支（对照 2229 技术词 / 2328 书名） | **新增** `_context_supported_place_candidate`：glossary 类别属地名类 **且** `context_match` **且** `final_confidence ≥ 0.6` → 与人名同等豁免 | 中。豁免面比人名宽，需要跑一遍历史候选看会多批准什么 | **P2** |
| **W9** | `len(core) >= 3` 让两字母名字整体隐形 → `Ms Su Du → Ms Dou`(0.87) 被 `multi_token_not_entity_like` 挡掉 | `article_context.py:3120-3133`（配合 3095-3103） | 首字母大写且长度 2 的 token，若**同一候选内相邻 token 也首字母大写**，判为 entity-like；不要无条件放宽 `len>=2` | 中。放宽实体判定会让更多候选进入后续门禁 | **P2** |
| **W10** | 人工复核清单 10 条里 8 条是 maternity↔paternity churn(0.81)，有价值的 0.87 那条根本没进 | `_not_applied_reason` / 清单装配 | 同一父字幕内**语义互为反义的来回改写**归为一类，折叠成 1 条并降序到清单末尾 | 低 | **P2** |
| **W11** | 队列召回 50%、词级 ASR 错召回 1/6；漏的全是「误听成另一个合法英文词」 | 质检队列生成层 | 用 `article_glossary.json` 做**反向**校验：文稿里出现的专名/术语，若 ASR 结果与 glossary 条目**编辑距离 ≤2 但不相等**，一律进队列（`Huangxi/Huangshi`、`Guangxi/Guanxi` 都能被这条抓到） | 中低。会带来一批误报，但这一类现在**召回是 0** | **P1** |
| **W12** | 终稿保存后不重新生成质检队列（两份 srt 仍是 04:06 失败运行的产物） | 终稿保存流程 | 终稿保存后重跑一次队列生成，或在文件名/头部标注其对应的运行时间戳 | 低 | **P3** |
| **W13** | 单词卡缓存（05:56）晚于主片渲染（05:43），两个成片卡面可能不一致 | 渲染与卡缓存的时序 | 渲染前把卡缓存哈希写进成片旁的 manifest，渲染时校验；不一致则拒绝复用 | 低 | **P3** |

已在别节立项、本轮**不重复立项**的：容量线 26→22（§37）、审计批次失败 7/7（§42.9）、
分页重排进清单＋一键回落父版（§42.7a）、v10 硬约束（§42.7b）。**W1 与 §37 的 S0 工单是同一族问题的两个不同单点，不要合并处理。**

### 45.6 三条明确反对的改法（我自己试过或算过，写下来防止重复踩）

1. **不要把 `high_confidence` 从 0.82 往下调**去救 `Huangshi`(0.80)。
   女性集里那 8 条 maternity↔paternity 的 churn 候选正好在 **0.81** —— 一降就全部自动应用，
   等于用一个真修复换八个真错误。W8 必须走**新增类别豁免**，不能走降阈值。
2. **不要把 `_token_looks_entity_like` 的 `len(core) >= 3` 直接改成 `>= 2`**。
   两字母大写 token 在英文里大量是缩写和句首词，无条件放宽会把噪声灌进后续门禁。W9 要加**相邻大写 token** 这个附加条件。
3. **不要为 W1 直接放宽 6409 行门禁本身**（例如把 `incomplete_review_count == 0` 改成 `<= 1`）。
   那会一次性放过所有类型的不完整边界；W1 的做法是**只让「逗号 + 介词续接」这一种形状可被判为完整**，
   影响面可度量。

### 45.7 给 GPT 的指令（用户可直接整段转交）

> §45 是外部审计员对「中国职场女性为何悄然掉队？」这一集的**人工终稿逐页复核**结果，
> 一共 302 页全部人读过，外加机械检查。§45.5 是一张 13 条的缺陷清单（W1–W13）。
>
> **第一步：先做判断，不要先写代码。**
> 逐条读 W1–W13，每条给出三项，写回本文档 §45.8（你自己新建）：
> (1) 判定 = `改` / `暂不动`；
> (2) 理由，必须引用你自己读到的 `file:line`，不要复述我的话；
> (3) 若判 `改`，写出**改动面**：会碰哪几个函数、有没有别处复用、你打算怎么证明它没让别的集变差。
> 只要有一条你认为我定位错了，直接写「§45 该条定位有误」并给出你的读法 —— 我要的是对账，不是同意。
>
> **第二步：只做 W1，做完停下来。**
> W1 是唯一能把这一集从「不可渲染」拉回「可渲染」的改动，其余先不要动。按 §45.6 第 3 条的限制做：
> 新增独立判定函数，**不要改 2792-2795 那个正则本身**（它被 7280-7315 一族复用）。
>
> 做完后在**未经人工校对的新音频**上跑一次（**严禁在测试音频、白宫集、日本集、女性集这四集上跑**，
> 它们都已人工校对，重跑会换掉英文 → 换掉 LLM 缓存键 → 中文重译 → 校对成果全丢），回报这 6 个数：
> 1. `no_complete_normal_font_page_partition` 出现次数（期望 0）；
> 2. 该集是否 `status PASS`、`errors` 条数；
> 3. `incomplete_review_count > 0` 的候选数量（改前 / 改后）；
> 4. **被新形态放过的边界总数**，以及其中**逗号 + 介词续接**以外的形状有几个（期望 0）；
> 5. 内置翻译审计是否从 `SKIPPED` 变成实际有审（审了多少 / 总多少、批次失败几批）；
> 6. 容量：`EN>85` 页数、最长英文字符数、`CJK>26` 页数、最长中文字数 —— 与改动前同集对比，**不得变差**。
>
> **第三步：W2/W3/W4/W5/W11 只在 W1 的数字回报之后再开工，且一次一条。**
> 这五条我判为低风险且能直接兜住这一集暴露出的错误类型（并页病句、改英文不改中文、
> 跨 cue 称谓断裂、静默丢卡、误听成合法英文词），但**先做判断，别抢跑**。
>
> **硬约束（每条都已经被违反过一次）：**
> - 禁止 `git checkout .` / `git restore .` / `git stash`；只允许 `git add <具体文件>`；
> - 禁止在 `runtime/` 下做全仓 grep/find（158,077 个文件，必超时）；
> - 禁止调用 `write_subtitle_review_ledger`，只读 `load_subtitle_review_marks`；
> - 禁止改 `stable-runs/` 里已冻结的产物；
> - 禁止在上述四集已校对音频上重跑；
> - 每条改动必须能用 `outputs/` 里现成的脚本复算：`cmp_parent.py`(父级改写/保真)、
>   `cmp_fidelity.py`(数字/否定/长度)、`cmp_page.py`(分页重排 A/B)、`pagequal.py`(单次运行页质量)、
>   `merge.py`(把 `parents` 与 `render_plans` 合成完整的每页中英对照 —— **只看 `render_plans` 会漏掉所有多页父的中文**)。

**这一集本身怎么办**：成片已经出了（主片 05:43）。W1–W13 都不能回溯修复已合成的视频。
§45.3 列出的 4 处上屏残留（`S0089` 病句、`S0053`「毫无庇护」、`S0177` 孤立「Ms.」、4 条缺句号）
只能在**人工终稿编辑器里手改这四条后重新保存并只重渲染**，不走 stable 管线。
## §46 第二十三轮（2026-08-26）：把 W1–W13 收敛成 6 条通用机制 ＋ 1 条独立小改

**这一节回答的问题**：他问的不是「这一集怎么补」，而是
「这次暴露的问题有没有通用办法，让以后大多数音频都不出错」。
下面 G1–G6 是通用机制（与具体音频无关、装一次长期生效），
§46.8 说明哪一类**任何新规则都抓不到**，只能靠修审计。

### §46.1 为什么逐条修 W1–W13 达不到他要的效果

W1–W13 是**这一集的症状清单**，每条都绑在一个具体 ID 上（S0089 的逗号尾、S0053 的旧中文、
S0177 的孤立 Ms.、20 张卡掉 4 张）。逐条打补丁的三个问题：

1. **覆盖不了没见过的同类**。W1 只放开「逗号尾 + 介词起页」，
   下一集换成「破折号尾 + 分词起页」照样整集报废——因为根因不是缺哪条豁免，
   而是 `_caption_has_terminal_completion` 只认 `.!?`（§45.6 已论证）。
2. **W2/W3/W5/W7 本身不修任何东西**，只是把问题捞进清单，
   而清单的召回率这一集实测 50%、精确率 20%、6 处词级听错只进队 1 处（§45.4）。
   往一个 50% 召回的清单里再加四类检查，仍然是 50% 那一侧的东西继续上屏。
3. **没有验收口径**。「以后大多数音频不出错」必须能被测量，
   否则改完 13 条也说不出改没改好。这就是 G6 存在的理由。

### §46.2 G1｜失败局部化：一个父句的分页失败不得判整集死刑（P0，最高杠杆）

**取证**：04:06 那次 `display-page-translations.json` 是 `status ERROR`，
`errors[]` 里**只有一条**，`cue_index 89 / S0089`。而 S0089 自己的 render_plan 里写着
`"review_only": true, "renderable": true` —— 也就是说**规划器自己认为这一页能渲染**，
是集级策略把这条 review 升格成了 error，才让 306 页全部作废、审计队列停在 04:06 不再更新。

**通用机制**：分页失败按父句隔离。
单个父句拿不到 normal-font 合法切分时，标 `review_only + degraded`（允许降字号/允许多一页/允许留在原字号超宽），
计入集级 `degraded_page_count`，**不进 `errors[]`**。
集级只在两种情况下失败：`renderable=false` 的父句存在，或 `degraded_page_count` 超过阈值（建议 ≤2% 且 ≤8 条）。

**为什么这是通用的**：它不关心失败原因是逗号尾、破折号、专名还是超长从句。
所有「单点阻断整集」的未来变体一次性消除，且不需要预测下一集会踩哪条谓词。
副作用是可能有 1–2 页排版不好看——这远好于整集不可渲染并连带停掉中文分页产出（§37 的日本集就是这个模式）。

### §46.3 G2｜专名以文章原文和 glossary 为真值（P0，能吃掉本轮 4 处词级错的 4 处）

**取证**：这一集的 `article_glossary.json` 是 38 条的列表，每条带
`canonical_name / aliases / category / canonical_in_article / evidence`。
实测里面**已经有** Huangshi、Ms Dou、Wu、Chen、Erica；`article_source.txt`（5783 字节）里
Huangshi 1 次、Dou 2 次、Wu 1 次、Chen 1 次、Erica 1 次。
也就是说 S0019（Huangxi）、S0101（Ms. Macedo）、S0178（Su Du）、S0218（Mrs. / Wu 断名）
**这四处的正确答案早就在这次运行自己的产物里躺着**，管线只是没用。

**根因**：`_should_apply_candidate` 走 `high_confidence = 0.82` 的置信度门，
`_token_looks_entity_like` 要求 `len(core) >= 3`（两字母专名直接出局），
且 `_context_supported_person_candidate` 只有人名版本、没有地名版本。
换句话说，纠错被当成「猜」，而不是「对照真值表」。

**通用机制**：新增一条**优先于置信度门**的对齐规则。
对每个 ASR token（含跨 token 的 2-gram），若与某条 glossary 的 `canonical_name` 或 `aliases`
大小写归一后编辑距离 ≤2 且不相等，且该条 `canonical_in_article = true`，
则**直接改写为 canonical**，不查置信度、不查 `entity_like` 长度、不分 person/place 类别，
并在 ledger 记 `source: glossary_anchor` 以便回溯。
距离 =3 或该词本身也是合法英语词（Guangxi/Guanxi 这类）时只进队列不自动改（见 §46.8）。

**为什么这是通用的**：真值来自每一集自己的文章原文，不是硬编码词表，
所以换任何音频都成立；且专名类是**跨集最稳定的错误类型**（人名/地名/机构名必然反复出现）。

**可离线回归、不需要重跑**：拿他已经人工校对过的几集，
把「他手改的父句 × 改动前后的 token」和当集 glossary 对照，
直接算这条规则能自动修对多少、误改多少。误改率必须为 0 才允许默认开启。

### §46.4 G3｜非词校验：不是英语单词的，一律进队列（P1，能吃掉本轮 2 处）

**取证**：`potishing`（S0128）、`rooflessly`（S0053）都不是英语单词。
S0128 恰好进了队列，S0053 没进——说明现在没有一条规则专门管这个，进队是碰巧。

**通用机制**：ASR 校正后对每个 token 做一次词典存在性检查
（内置词表 ∪ 当集 glossary ∪ 已知缩写/口语形式白名单）。
不在其中的一律标 `unknown_token` 进质检队列，并给出编辑距离最近的 3 个候选。
不自动改（避免误伤生造词和外来词），但**保证 100% 进队**，不再靠运气。

**为什么这是通用的**：与内容无关，纯形式检查，任何音频都适用，且几乎不可能有假阴性。
代价是会有一些假阳性（人名、外语词），靠 glossary 和白名单压下去。

### §46.5 G4｜人工保存不变式：改了英文或改了分页的 cue，中文必须同时被处理（P1，取代 W2/W3/W7）

**取证**：这一集上屏的 4 处残留里有 3 处是**人工编辑器自己造出来的**，
不是管线的错：
- S0089 的 `chinese` 在管线产物里本来是正确的整句「近来，这些饭局日益受到新的合规与纪律准则的限制，」，
  上屏的病句「日益受到限制来自新的合规与纪律准则。」是**两页中文直接拼接**的结果；
- S0053 英文从 rooflessly 改成 ruthlessly，中文「毫无庇护」没跟着改；
- S0101/S0103/S0118/S0122 英文有句号、中文没有。

**通用机制**：在 `save_to_source_folder` 的校验链里加**一条**不变式
（与 `_validate_no_silent_display_page_state_loss` 同级）：
凡本次编辑中 `english` 文本或分页边界发生变化的父句，其中文必须满足其一——
(a) 中文也被本次编辑改过；(b) 中文由父级中文重新派生（多页时按边界重切，不是字符串拼接）；
(c) 编辑者显式勾选「中文已确认无需改」。
三者都不满足则列入保存后的「待确认中文」清单，且这份清单**必须在合成前清空或显式忽略**。
同时把「英文句末标点与中文句末标点不一致」并入同一条检查（这就是 W7，不必单列）。

**为什么这是通用的**：它不枚举任何具体病句形态，只锁「英文动了中文没动」这一个因果关系，
而这一集三类残留全部落在这一个关系里。

### §46.6 G5｜守恒不变式：任何会丢东西的阶段都必须 in == out + 有理由（P1，取代 W5）

**取证**：单词卡 `raw_items 20 / accepted 20 / normalized 20 / scheduled 16`，
`rejected` 映射**是空的**——4 张卡凭空消失且没有任何记录。
同一个模式在 §42.9 的内置翻译审计里也出现过：7 批全失败、约 59% 字幕从未被审，
流程照样报成功。

**通用机制**：给每个可能减少条目的阶段（单词卡调度、审计分批、分页中文写回、cue 分配）
统一加一条出口断言：`输入数 == 输出数 + Σ带原因的丢弃数`。
不成立就把差值和样本写进产物，并把该阶段标为 `incomplete`；
集级汇总里出现任何 `incomplete` 就在合成前提示。

**为什么这是通用的**：静默丢失是这个仓库反复出现的**同一种**缺陷
（§37 中文停产、§39 保存失败日志已死、§42.9 审计批失败、本轮丢 4 张卡），
一条断言模板覆盖全部。

### §46.7 G6｜闭环召回度量：用他自己的手改当标准答案（P1，这是唯一的验收口径）

**取证**：这一集他改了 32 个父句，当次运行的 81 条质检队列只命中 16 条
→ 召回 50%、精确率 20%；6 处词级听错只进队 1 处。
漏掉的是 S0007 S0019 S0033 S0034 S0053 S0060 S0088 S0101 S0136 S0149 S0152 S0153 S0218 S0219 S0267 S0269。
这两个数字是**目前唯一能证明「以后大多数音频不出错」的东西**。

**通用机制**：加一个离线脚本（不进管线，只在他交出人工终稿包后跑）：
自动 diff 人工终稿包与对应运行的父级英文/中文/分页，输出他改了哪些 ID、
以及当次质检队列对这些 ID 的召回率、精确率、词级错误命中率。
每集一行，累积成表。

**验收线建议**：G2+G3 上线后，词级听错命中率从 1/6 提到 ≥5/6；
整体召回从 50% 提到 ≥75%；精确率不低于 20%（宁可多报）。
达不到就说明机制没生效，而不是靠感觉判断。

**目标要改口**：不是「以后不出错」（做不到，见 §46.8），
而是「出的错都在清单里，他按清单改就行」。这个目标可测、可验收。

### §46.8 通用机制抓不到的一类：错词本身也是合法英语词（诚实结论）

本轮 6 处词级听错的分类：

| 类型 | 实例 | 能否通用规则修 |
|---|---|---|
| 专名 vs 原文/glossary | Huangxi→Huangshi、Ms. Macedo→Ms. Dou、Su Du→Ms Dou、Mrs./Wu 断名 | 能，G2 自动改 |
| 非英语单词 | potishing→punishing、rooflessly→ruthlessly | 能，G3 必进队列 |
| 合法词换合法词 | massive job→massive jump、Guangxi→Guanxi | **不能** |

`job` 和 `jump` 都是词，`Guangxi` 和 `Guanxi` 都是真实存在的专名（一个是广西、一个是关系），
拼写、语法、置信度、词典、glossary 全部沉默——**任何新增的形式规则都抓不到它们**，
只有「读懂这句话在说什么」的语义审计能抓。
而语义审计正是 §42.9／§43 实测里 7 批全失败、约 59% 字幕从未被审的那个模块。

**所以这一类的通用解不是新规则，而是把审计修好**（§42/§43 已立项，与本轮无关）：
先让审计**真的跑完**（批失败必须重试并计入 G5 守恒断言），
再谈提高它的召回。在审计修好之前，这一类只能靠他人工过一遍，
G6 的数字负责告诉他每集大概还剩几处。

### §46.9 W1–W13 到 G1–G6 的映射

| 原清单 | 归入 | 说明 |
|---|---|---|
| W1 逗号尾救援死区 | G1 | 不再单独放开谓词；失败局部化后 S0089 这类不再阻断整集。若仍想放开，作为 G1 之后的可选优化 |
| W2 拼接病句检测 | G4 | 由「多页中文按边界重切、禁止字符串拼接」直接消除 |
| W3 英文改了中文没改 | G4 | 同一条不变式 |
| W7 中英标点不一致 | G4 | 同一条不变式 |
| W4 跨 cue 称谓断名禁令 | G2 | glossary 锚定后 Mrs./Wu 这类自然合并 |
| W8 地名上下文豁免 | G2 | 取消 person/place 区分即覆盖 |
| W9 两字母实体 | G2 | 取消 `len(core) >= 3` 即覆盖 |
| W11 glossary 编辑距离 ≤2 反查 | G2 | 就是 G2 的核心规则 |
| W5 静默丢卡日志 | G5 | 守恒断言的一个实例 |
| W6 单词卡去重 | 保留独立 | 与上面机制无关，独立小改（同 lemma／包含关系去重）|
| W10 churn 降噪 | G6 | 由召回/精确率数字驱动，不再凭感觉调 |
| W12 保存后重生质检队列 | G6 | 度量脚本的前置条件 |
| W13 卡缓存哈希绑定渲染 | G5 | 产物一致性断言 |

结论：**13 条压成 6 条通用机制 + 1 条独立小改（W6）**，
其中 G1、G2 是 P0，G3、G4、G5、G6 是 P1。

### §46.10 给 GPT 的落地顺序（一次只做一条，做完给数字再往下）

1. **G1**（失败局部化）。验收：拿 04:06 那次 checkpoint 重跑分页层，
   要求 `status PASS`、`degraded_page_count = 1`、S0089 可渲染、
   质检队列与中文分页正常产出；其余 305 页分页结果与 04:06 逐页一致（允许 S0089 两页变化）。
2. **G2**（glossary 锚定）。先只做**离线回归**：在已校对的几集上算自动修对数/误改数，
   误改为 0 才允许默认开启；开启后必须记 `source: glossary_anchor`。
3. **G3**（非词进队列）。验收：`rooflessly`、`potishing` 两个 token 100% 进队；
   在已校对集上统计假阳性率并给出白名单。
4. **G4**（保存不变式）。验收：构造一个「改英文不改中文」和一个「多页拼接」用例，
   保存时必须拦下；对本轮那份终稿包重放，应报出 S0053、S0089、以及 4 条缺句号。
5. **G5**（守恒断言）。验收：本轮那次单词卡数据应报 `丢弃 4 无原因`。
6. **G6**（度量脚本）。验收：对本轮终稿包跑出 32 改动 / 召回 50% / 精确率 20% / 词级 1-6。
7. **W6**（卡去重）独立做，验收：`on paper` 与 `On paper`、`runway` 与 `full career runway` 各只留一张。

**硬约束（每条都适用）**：不改任何 `stable-runs` 产物；
不重跑 测试音频／白宫集／日本集；每条改完先在 04:06 这个 checkpoint 上回归再说下一条。

### §46.11 GPT 对 G2–G6 的分诊回执 ＋ 三处修正（2026-08-26，G1 已实施、G2–G6 未实施）

GPT 的分诊结论：G2 能做但风险最高（改稳定英文→缓存键→下游全变，须先离线跑误改数=0）；
G3 低风险（只进队列不自动改，主要风险是人名/外语词/生造词误报）；
G4 能做但不应硬拦保存（会阻断旧人工包、破坏现有手工流程）；
G5 能做但改动面大（须按阶段分别接断言，粗粒度总断言会把合法筛选误判成丢失）；
G6 最安全（只读离线度量，但只能测不能修）；W6 低风险、主线定了再单独做。

**这份分诊整体成立，其中 G5 的判断优于本文档原本的写法**（原 §46.6 写成了统一断言模板，
应改为「每个丢弃路径必须自带原因」+ 各阶段各自断言；合法筛选本身就是「带原因的丢弃」，不算丢失）。
以下三处需要修正。

**修正一｜G2 的真实风险不是缓存，而是真值可能是错的，以及短专名的距离阈值定错了。**
缓存那条只在**回填旧集**时成立：G2 作用于 ASR 校正阶段，位于翻译之前，
新运行的中文本来就是从校正后的英文生成的，不存在键失效问题。
所以规则是：**只对新运行生效，永不回填任何已校对集**，缓存风险即消失。
真正的两个风险是：
(a) `article_glossary.json` 是模型从文章里抽的，canonical 本身可能就是错的 →
    必须要求 canonical 字符串**在 `article_source.txt` 里字面出现**
    （实测 Huangshi / Dou / Wu / Chen / Erica 都字面出现），只信原文、不信抽取结果；
(b) **本文档原来写的「编辑距离 ≤2」对短专名是错的** ——
    `Dou` 到 `do/you/down`、`Wu` 到 `we/who/us` 全在 2 以内，会大面积误改常见词。
    改为按长度分档：token 长度 <5 时只允许距离 ≤1，≥5 时允许 ≤2；
    且候选 token **本身不能是常见英语词**（复用 G3 的词典）；
    且短专名需有称谓或大写上下文（前面是 Mr/Ms/Mrs/Dr，或本身首字母大写且不在句首）。
本轮四处（Huangxi→Huangshi 距离 2 长度 7、Ms. Macedo→Ms. Dou 走称谓上下文、
Su Du→Ms Dou、Mrs./Wu 断名）在收紧后的阈值下仍全部命中。

**修正二｜G4 必须拆成两半，GPT 把一个纯修复和一个门禁混在了一起。**
- G4a：**多页父句的每页中文由父级中文按边界重新切分派生，禁止字符串拼接**。
  这是 S0089 上屏病句的直接成因，属于修复不是门禁，**无条件做，不涉及拦不拦保存**。
- G4b：「英文或分页动了但中文没动」写成一份「待确认中文」清单随包输出，**不拦保存** ——
  他用人工编辑器的前提正是 stable 已经被拦住了，再拦保存等于堵掉逃生口。
  门禁挪到**合成前**：清单非空则合成时提示并要求显式忽略。旧人工包因此不受影响。

**修正三｜执行顺序按「先解锁测量」排，不按风险排。**
G6 提到第二位：G2 的「误改数必须为 0」和 G3 的假阳性率，
都要靠 G6 那份「拿他手改当标准答案」的 diff 脚本才能算出来，否则验收标准落不了地。
G5 第一版**只接单词卡调度这一个阶段**（唯一有实证的静默丢弃：20→16、`rejected` 为空），
分页翻译／审计分批／cue 分配后续再逐个接。

修正后顺序：**G1（已完成）→ G6 → G3 → G2 → G4a → G5（仅单词卡）→ G4b → W6**。

### §46.12 对 G1／G6 实施结果的只读核查（2026-08-26 07:10–07:56）

**核查方法**：只读 `git diff`（基线 HEAD = `3f28f04`，02:09:25）＋ `output/regression-retry-check-20260826.txt`（07:10）
＋ 各文件 mtime。未运行任何管线、未修改任何项目文件。

**G1 实施是对的，按本文档 §46.2 的设计落地了**：
`podcast_learning_video.py` 里 `degraded_page_count` 从 0 处变成 6 处；
新测试 `test_renderable_review_fallback_is_degraded_without_blocking_the_blueprint`
断言 `blueprint["status"] == "PASS"`、`degraded_page_count == 1`、
`degraded_parents` 带 `cue_index/parent_subtitle_id/reasons`、`errors` 为空、
该父句 `renderable is True` 且 `degraded is True`。
分层也合理：底层 `_build_article_english_page_plan` 仍返回 `render_structural_overflow`，
只有 blueprint 层降级——原有的
`test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px`
被相应改写（bundle 改判为 `candidate_bundle` + `fallback_review`，plan 层断言保留），
这属于 G1 的必要伴随修改，不是把测试放水。

**但同一轮里夹带了一条不属于 G1 的选择逻辑改动**：
新谓词 `relative_clause_has_trailing_predicate`（HEAD 里 0 处，现在 5 处）
＋ 新测试 `test_tight_clause_entries_need_explicit_review_before_page_selection`，
内容是「关系从句入口会把后续谓语孤立时禁止在此分页」。
这改的是**选哪个切分**，不是**失败怎么上报**。

**这条夹带很可能就是那次回归唯一失败的原因**：
07:10 回归 `REGRESSION_EXIT=1`，唯一失败项 `article display readability contract`（364.05s），
唯一断言错误在
`test_three_line_fallback_promotes_complete_two_page_alternative:3581`
—— `assert plan["pages"][1]["english"] == expected_second_page`，
即某个父句**成功出了计划、但第二页英文文本变了**（Mixue／expansion engine 两例之一）。
G1 按设计不应改变任何成功用例的页面文本，只会改变失败用例的上报方式；
出现页面文本 diff，说明动的是选择器。
（另核实：该测试里那段 `except RenderStructuralOverflowError` 的宽松分支
在 HEAD 里就存在，本轮 diff 是 111 增 5 删、未触碰它，不存在改测试就过的情况。）

**为什么必须拆开**：§43 已实测过——同一次里既动上报又动选择，
结果是分页重排从 25% 升到 35%、新坏 2 修 0、上屏净收益约等于 0，
而且事后无法归因。要求 G1 单独保留，
`relative_clause_has_trailing_predicate` 退成独立项（记作 **G7**），
验收方式是拿 04:06 那个 checkpoint 做 before/after 逐页 diff，
明确报出「改变了几页、其中几页读感变好、几页变差」，好坏比不达标就不进。

**G6 已交付**：`scripts/measure_g6_manual_diff.py`（07:55）＋
`tests/test_measure_g6_manual_diff.py`（07:56）。
脚本自述只读、不 import 管线代码、不写运行目录与人工包，可输出 JSON 到 work-dir 之外。
做法比本文档 §46.7 设想的更好：它不是逐字 diff 文本，而是读人工包 `edits.json` 的
操作日志（`EDIT_OPERATIONS` 白名单区分「真编辑」与「仅确认」，
`WORD_OPERATIONS` 单列 `edit_english_surface` 以算词级命中率）。
待补的是**它跑出来的四个数**：改动父句数（人工核算 32）、
队列召回（50%）、精确率（20%）、词级命中（1/6）。对不上要先判定是脚本口径问题还是核算问题。

**回归为什么慢（实测）**：`Regression elapsed: 1005.21s`。
日志里可见它跑了 `test_asr_trust_contract`，其中真的去调 faster-whisper 子进程
（`faster-whisper …\audio.wav`），还反复加载 spaCy `en_core_web_sm`。
G1–G7 全在分页层，这些与改动无关。
同时 `AppData\logs\app.log` 轮转持续抛 `PermissionError: [WinError 32]`（文件被占用），
14870 行输出里绝大多数是这个 logging 报错——与 §39「保存失败日志已死」同一根因，
既拖慢也把真正的断言错误埋在一万四千行里（唯一一条 `AssertionError` 在第 14679 行）。
**要求**：分页层改动只跑分页相关用例 ＋ 04:06 checkpoint 逐页 diff；
全量回归仅在一条机制收尾时跑一次，且先把 log 轮转在测试期禁用。

### §46.13 固定工单模板（每条机制照抄，只换方括号里的内容）

**用法**：第一次把整段发给 GPT；之后每条只需说「按 §46.13 的格式做 Gx」，
再补方括号里那四项。目的是把「守不住边界」和「验证跑错东西」这两个浪费时间的毛病
一次性用格式压住，而不是每次临时叮嘱。

```
【本轮只做一件事：<Gx 一句话>】

一、开工前先回述，等我确认再动手
用三行说清：(1) 你打算改哪几个文件的哪几个函数；(2) 你打算跑哪几个测试用例；
(3) 你预计这次验证要多久。我没回你之前不要改代码。

二、改动范围
只许动：<文件/函数白名单>
不许动：其他任何文件。特别是不许动页面「选哪个切分」的逻辑——
本轮只允许改「失败怎么上报 / 怎么记录 / 怎么度量」。
超出白名单一个字都要先问我。

三、看见别的问题怎么办
不要改。写进回复末尾的「发现但没动」清单，一行一条，注明文件和行号。
顺手修别的问题这件事，在这个仓库里已经造成过「修 0 坏 2 且事后无法归因」，
所以宁可漏修，不许夹带。

四、不许改现有测试的断言
新行为写新测试。任何对已有 assert 的删改都要单独列出来、给理由、等我同意。
测试改了就过不算通过。

五、验证怎么做（照做，不要自己发挥）
只跑：<用例清单>
再跑：加载 <checkpoint> 的现成产物，只重跑 <哪一层>，与原产物逐页 diff。
明确禁止：全量测试套件、任何 ASR / faster-whisper、任何模型或网络调用、
合成视频、重跑整条管线。
这几条改动的输入都已经在磁盘上，纯本地计算。
超过一分钟就说明你跑错了东西，停下来问我。
跑之前把测试期的 app.log 轮转关掉，否则 WinError 32 会刷上万行、把真正的断言错误埋掉。

六、交付格式
先给数字，不要给叙述。至少给：<要求的 3–5 个具体数字>。
然后一句话结论：通过 / 不通过。
再然后才是你想说的其他内容。

七、做完停下
不要开始下一条。等我看完数字再说。

八、红线（每轮都适用）
不改 stable-runs 里任何产物；不重跑 测试音频／白宫集／日本集；
不执行 git checkout . / git restore . / git stash。
```

**为什么这八条各自有用**：一压边界（二、三）、二压「改测试蒙混过关」（四）、
三压验证成本（五，实测把 1005s 压到分钟内）、四压叙述型汇报（六，让好坏可判定）、
五压连做（七）。第一条「开工前回述」单条收益最大：
它把返工从「跑完 17 分钟才发现方向错」提前到三行字的成本。

### §46.14 D1｜常驻指令与文档瘦身（只动文档、不动代码）

**实测现状**：`AGENTS.md` 本身只有 108 行、不臃肿，问题在它的「Required Context Read Order」
点名的下游阅读量：`docs/PROJECT_OVERVIEW.md` 52 ＋ `ARCHITECTURE.md` 128 ＋ `PIPELINE.md` 800
＋ `SUBTITLE_RULES.md` 369 ＋ `CURRENT_STATE.md` 142 ≈ 1491 行，
再加「相关 active 任务文件」——而 `tasks/active/stable-subtitle-production-v1-log.md`
已经 **3832 行**，`tasks/archive/` **是空的**（从未归档）。
即每次实质改动前要吞约 5300 行。这直接喂养本项目最老的瓶颈（上下文溢出）。

**重名／重复（会导致读到旧结论）**：`docs/CODEX_STATE.md`（6 行）与根 `CODEX_STATE.md`（42 行）同名两份；
`docs/CURRENT_STATUS.md`（27 行）与 `docs/CURRENT_STATE.md`（142 行）名称近乎相同、都自称当前状态；
`docs/CODEX_HANDOFF.md`（196 行）又是一份交接说明；
根目录另有 `执行进展-给用户.md`、`现状与下一步-2026-08-24.md` 两份带日期的快照。

**本文档自身**：`EXTERNAL-AUDIT-2026-08-24.md` 已 5300+ 行 / 360KB，
是全仓最大的 md，比上述全部相加还多一倍。它不在必读清单内、不吃每轮额度，
但今后一律以「读 §xx」定向引用，不整份投喂；后续应在开头补一份小节索引。

**D1 三刀**：
1. 必读清单砍到三份（`ARCHITECTURE` / `SUBTITLE_RULES` / `CURRENT_STATE`）；
   `PIPELINE.md` 降级为「仅在改动跨阶段数据流时读」；
   `PROJECT_OVERVIEW.md` 降级为「首次接手时读一次」；
   任务文件改为「只读 active 内最近一轮 ＋ 50 行以内的当前状态摘要」。
2. 任务日志归档：3832 行的日志按轮切分，历史轮次移入 `tasks/archive/`，
   `active` 只留最近一两轮。**只许移动，不许删任何内容。**
3. 重名合并：同名 `CODEX_STATE.md` 保留一份；`CURRENT_STATUS.md` 并入 `CURRENT_STATE.md`；
   `CODEX_HANDOFF.md` 的交接内容并入保留的那份 STATE；
   根目录两份中文快照移入 `docs/archive/`。
   合并冲突以 mtime 较新者为准，且**必须列出被丢弃的旧结论**给用户过目。
   顺带把 `AGENTS.md` 里两节重复的「Root-Cause-First」合并为一节
   （保留全部实质要求，只去重措辞）。

**验收数字**：改前／改后「必读行数总计」（现约 5300）、`active` 任务日志行数（现 3832）、
`docs` 文件数、**删除行数必须为 0**、移动行数。
**验证方式**：不跑任何测试（未改代码），只需 `git diff --stat` 证明零 `.py` 改动。
**红线**：不改 AGENTS.md 的 Hard Constraints、Root-Cause-First 的实质要求、Do Not 各条；
保留 §46.13 那轮要求新增的 Verification Tiering 与 Scope Discipline 两节；
若那两节尚未提交，则与 D1 合并为对 `AGENTS.md` 的一次性修改，避免同一文件改两轮。

### §46.15 Codex 额度去哪了：一次改动循环的字节账（只读实测）

用户问「这是不是我 Codex 余额消耗很快的原因」。无法看到他的计费明细，
以下是**按实测文件体积推算**，不是账单核对。

| 一次「实质改动」循环里被读进上下文的东西 | 实测体积 | 备注 |
|---|---|---|
| 全量回归输出 | **1,049,252 字节 / 14,870 行** | 其中 **7,087 行（约一半）是 `WinError 32` 日志轮转报错**，纯垃圾；唯一一条 `AssertionError` 在第 14,679 行 |
| AGENTS.md 必读清单 | **327,322 字节** | 其中 `tasks/active/stable-subtitle-production-v1-log.md` 单独占 **237,097** 字节（3,832 行） |
| 巨石源文件（改动时不可避免大段读） | `screen_editor.py` **1,044,083** 字节 / 24,427 行；`podcast_learning_video.py` **455,933** 字节 / 12,020 行 | 两者合计约 1.5 MB |

**关键判断**：最贵的不是文档，是**全量回归的 1 MB 输出**，理由有二：
一是它一半是同一条 `WinError 32` 反复刷屏，付费读垃圾；
二是它**每次内容都不同，无法被 prompt 缓存**，而文档反复读同一份是可以被缓存的。
回归一旦失败（07:10 那次 `REGRESSION_EXIT=1`）就要「修 → 再跑 → 再读 1 MB」，成本翻倍。

**按性价比排序的止血动作**（前两条零风险，已含在 §46.13 五、和 §46.14 D1 里）：
1. **测试期禁用 `app.log` 轮转，并让回归只输出摘要**（失败项名称 ＋ 断言原文 ＋ 耗时），
   完整 stdout 落盘但不读进上下文。单这一条就砍掉 1 MB 里的大半。
2. **分级验证**：小改动根本不跑全量回归，那 1 MB 从源头不产生。
3. **归档 3,832 行任务日志**：把必读量从 327 KB 降到 90 KB 量级。
4. 拆分 `screen_editor.py`（24,427 行）收益最大但风险也最高，**现在不动**，
   等 G 系列机制收尾后单独立项。

### §46.16 D2｜回归输出瘦身（唯一允许改的代码是 `scripts/run_regression.py`）

**根因已定位到具体一行**：`scripts/run_regression.py:18` 的 `subprocess.run(...)`
**没有 `capture_output`**，子进程 stdout 直通终端，
所以 14,870 行里 7,087 行的 `WinError 32` 噪音全部进了上下文。
脚本本身已经有结构化摘要（`== 名称 ==`、`PASS/FAIL (耗时)`、`Regression elapsed`、
末尾失败项列表），也已经支持 `--list` 与按 slug 选跑——**聚焦验证的能力早就有，只是没被用**。

**D2 要求**（改动面刻意做小，只动输出，不动判定）：
1. `run_step` 改为捕获子进程输出，整份写入 `output/regression-logs/<slug>-<时间戳>.log`；
   终端／上下文只保留：节名、`PASS/WARN/FAIL`、耗时。
2. 失败时额外只打印该步日志的**尾部 30 行** ＋ 匹配
   `AssertionError|Error:|FAILED|Traceback` 的行（去掉 `logging`/`WinError 32` 噪音），
   并给出完整日志的文件路径。
3. 测试期禁用 `AppData\logs\app.log` 的轮转（改用环境变量或测试期开关，
   不要动生产日志配置的默认值）。
4. 保留 `--verbose` 恢复旧的直通行为，默认关闭。
5. **判定语义一字不改**：`returncode`、`allow_warning_exit`、
   `REGRESSION_EXIT` 的计算逻辑保持原样。

**验收数字**：同一份 profile 跑一次，报出「终端输出行数：改前 14,870 → 改后 ?」、
落盘日志总行数（应 ≥14,870，不许丢）、失败项数量与名称是否与改前一致。
**必须证明**：故意造一个失败步（临时改一个断言再改回），
摘要模式下仍能看到失败项名称和断言原文，且 `REGRESSION_EXIT=1`。
**红线**：不改任何测试用例、不改被跑的用例集合、不改 `AGENTS.md`（那是 D1 的事）。

### §46.17 D3｜出片优先的阻断分诊规则（为什么它「没有全局概念」）

**用户的观察**（2026-08-26 08:52）：女性集跑完被阻断，他问接下来干嘛，
Codex 答「马上修这个阻断点」——而实际正解是**在人工终稿编辑器里手改那一条、绕过阻断、当天出片**，
代码修复应该是另一件事。他说它「糊里糊涂、没有全局概念」。

**三条成因，其中两条是仓库自己造的，不是它笨**：
1. **它没有成本感**。手动绕过约几十秒；改代码要动 `podcast_learning_video.py`（12,020 行）
   再跑一次全量回归（1,005 秒、1 MB 输出），还可能改坏另外 305 页。
   这两件事在它眼里都只是「一个任务」，没有量纲。
2. **它没有目标函数**。`AGENTS.md` 的 Project Purpose 只写了产物形态，
   从没写「今天出片优先于修管线」。它的默认目标退化成「让报错消失」。
3. **规矩本明确禁止绕过**。Root-Cause-First 那节原文禁止
   `local exception / threshold relaxation / silent fallback / downstream repair`，
   所以它看到阻断时，**是被指令要求去修根因的**。它在照章办事。

**D3 要求**（改 `AGENTS.md`，新增一节 Blocking Triage，与 Root-Cause-First 并列且优先于它）：
1. 一次运行被阻断时，先报三个量：阻断点数量、能否在人工终稿编辑器内绕过、
   代码修复的影响面（涉及多少页／多少集）与验证成本（分钟）。
2. **默认路径**：阻断点数量少且可人工绕过时，默认建议「人工绕过 ＋ 出片」，
   代码修复登记为独立工单，**不当场动手**。
3. 只有当阻断是系统性的（同一根因跨集反复出现，或单集内阻断点超过阈值）才建议立即改代码。
4. **任何「立刻修」的提议都必须同时给出不修的绕过方案**，二选一由用户决定。
   Root-Cause-First 约束的是「决定要修时怎么修」，不是「现在必须修」。
5. 决策权归用户。agent 只提供选项与成本，不替用户排优先级。

**给用户的口袋问题**（它说「马上修 X」时反问三句）：不修会怎样？有没有手动绕过？
修它要多久、影响多少页？——三问答不上来就先别动手。

---

### 46.18 §42.7／§42.9 执行状态核查 ＋ 女性集把审计的真实开关暴露出来了（只读，2026-08-26）

用户问：早先那条「依据 §42.7／§43 先读再动手」的工单做了没有、还要不要做、是否等 D2 之后一起做。
本节给三个可核对的答案。

**(1) 没做，两处都无代码痕迹**

- `display_page_chinese_reordered`（§42.7a 的新清单规则）：在 `app/`、`scripts/`、`tests/` 全域 grep **0 命中**。
- §42.9 要求的「重试／降批／单条兜底」：`translation_quality_audit.py` mtime 仍是 **2026-08-24 14:07**
  （§42 写出之前的版本，此后未被碰过）。其请求循环仍是
  `except Exception → batch_errors.append(...) → continue`，
  **没有 retry、没有降批、没有单条兜底**；`max_retries=0` 也仍在调用侧写死。
  → §42.9 与 §42.7(a)(b) 全部处于未开工状态。

**(2) 但「要一集新音频当基线」这件事，女性集已经交付了，而且结论比白宫更严重**

女性集两个 checkpoint（`20260826T033853` 与 `20260826T040659`）的 `translation-quality-audit.json` 完全一致：

| 量 | 白宫 v8（§42.9） | 女性集（本节） |
|---|---|---|
| `status` | `PARTIAL` | **`SKIPPED`** |
| `source_subtitle_count` | 203 | **271** |
| `audited_subtitle_count` | 83（41%） | **0（0%）** |
| `issue_count` | >0 | **0** |
| `batch_errors` | 7 条请求失败 | 1 条 `translation_quality_audit_skipped_page_projection_failed` |

**即：女性集有 100% 的字幕从未被自动翻译审计看过。**不是超时、不是限流，是被一道更上游的开关整体跳过。

**(3) 开关定位（比 §42.9 的诊断更靠前一层）**

`app/thread/subtitle_thread.py` 的 `_run_translation_quality_audit`（1054-1090 行）：

```python
if str(page_artifact.get("status") or "") != "PASS":
    payload = {... "status": "SKIPPED", "audited_subtitle_count": 0,
               "batch_errors": [{"code": "translation_quality_audit_skipped_page_projection_failed"}]}
```

分页蓝图不是 `PASS` 就**整集不审**，不是「只跳过坏页」。
女性集 `display-page-translations.json` 的 `status = "ERROR"`，`errors` 只有 **1 条**：

```json
{"cue_index": 89, "reason": "no_complete_normal_font_page_partition",
 "code": "display_page_blueprint_invalid", "parent_subtitle_id": "S0089"}
```

**一父（就是他手改的那个 S0089）→ 整集蓝图 ERROR → 271 条字幕零审计。**
这是 §37 那条「1 父阻断整集」放大效应在审计层的第二次现形，与 §37.1 同构。

**(4) 因此 §42.9 的第一步很可能已被 G1 顺手解决，不需要新写代码去验证**

G1（degraded 化）落地时间：`podcast_learning_video.py` mtime **2026-08-26 07:23**；
女性集两次运行是 **03:38 / 04:06**，都在 G1 之前。
G1 的效果正是把 `no_complete_normal_font_page_partition` 从 `errors`（→ERROR）改成
`degraded_parents`（→PASS + `degraded_page_count`），
而上面那道开关只看 `status == "PASS"`。
→ **G1 若真如其测试所述，女性集重跑一次就会让审计从 `SKIPPED` 变成实际运行**，
零额外改动。这也是 G1 那四个验收数字之外顺带能收的第五个数。

**(5) 排序结论**

1. D2 先做完（正在进行）。
2. 然后**只做一件事**：用女性集重跑一次取数。理由：他的人工终稿冻在桌面独立包里（见 §45），
   重跑不毁校对；而且这是同时收 G1 四个数 ＋ 审计是否复活的**同一次运行**，不额外花钱。
   要读的就两个字段：`translation-quality-audit.json` 的 `status` 与 `audited_subtitle_count`。
3. 看到数字再分叉：
   - 若 `status` 变 `PARTIAL/OK` 且 `audited_subtitle_count` 明显 >0 ——
     §42.9 只剩「请求失败重试／降批／单条兜底」这半条要做，优先级从最高降为中等。
   - 若仍是 `SKIPPED` —— 那道 `status == "PASS"` 硬门必须单独改成「按页跳过、其余照审」，
     这条才升回最高优先级。
4. §42.7(a)（重排进清单）与 §42.7(b)（v10 硬约束）**继续排在后面**，不要和上面这步捆在一起：
   (b) 需要一集全新音频 ＋ 容量棘轮，成本远高于收益顺序里排在它前面的项。

**重要性判断（回答「重要嘛」）**：重要，但**不是现在动手**的那种重要。
它是 §46.8 认定的唯一能抓 `job→jump`／`Guangxi→Guanxi` 这类「合法词错成合法词」的机制——
形式规则永远抓不到，只有语义审计能抓。所以它的天花板高；
但现在挡住它的不是它自己的代码，而是上游一道开关，而那道开关大概已经被 G1 顺手推开了。
**先花一次运行确认，再决定是否投入改代码。**

### 46.19 工单 M1｜女性集测量运行（零代码改动，只为取数）

> **已被 §46.20 取代（2026-08-26）**。用户要离开去休息，无法在中途看数字再做决定，
> 因此改为无人值守版：整段 M1 不需要重跑整条管线、不需要 GUI、不花 LLM 额度，
> 并把分叉判定预先写成规则交给 GPT 自己执行。本节保留作为需求来源，**不要照本节下单**。

**前提**：用户 2026-08-26 明确「花钱没事，只要项目能自动化 90-95」。
所以本轮不再为省额度而回避重跑；但仍然只允许**一次**运行，且**不许附带任何代码改动**。

**为什么可以重跑女性集**（唯一被允许重跑的已出片集）：
人工终稿冻结在桌面独立包内，与 `work-dir` 无关（见 §45），重跑不销毁校对成果。
`测试音频／白宫集／日本集` 仍然禁止重跑。

**必须保留的基线**：checkpoint `20260826T040659.244182-79951e43`
（G1 之前的产物，是本轮所有 diff 的对照面）。不许删除、不许覆盖、不许移动。

**要求交付的数字（先给数字，再给结论）**

1. `display-page-translations.json`：`status`、`errors` 条数、`degraded_page_count`、`degraded_parents` 列表。
2. `S0089`（`cue_index` 89）：`renderable` / `degraded` 两个布尔值，以及它最终上屏用的字号档。
3. 与 04:06 基线逐页 diff：总页数、内容发生变化的页数、其中归因于 G1 的页数、归因于 G7
   （`relative_clause_has_trailing_predicate`）的页数。**G7 必须单独计数**，
   否则无法判断 §46.12 记的那条夹带改动是净收益还是净损失。
4. `translation-quality-audit.json`：`status`、`audited_subtitle_count` / `source_subtitle_count`、
   `issue_count`、`batch_errors` 条数与各 `code` 计数。
5. 若 `status` 仍为 `SKIPPED`：给出 `page_artifact["status"]` 的实际值，
   用来判定是 G1 没起作用还是那道 `== "PASS"` 硬门需要单独改。

**红线**：本轮不许改任何 `.py`；不许改现有断言；不许顺手修任何在运行中发现的问题
（写进「发现但没动」清单）；不许合成视频；不许跑全量回归。
取完上面五组数就停下，等用户看完再谈下一步。

**分叉规则**（数字回来后按 §46.18(3) 执行，不要自行决定）：
审计复活 → §42.9 降级为中等优先级，下一步转 G3；
审计仍 `SKIPPED` → 那道硬门改成「按页跳过、其余照审」升为最高优先级。

**与 90-95 目标的关系**：§42.10 已算过账，可回收 6.7pp、上限约 **92.5%**，
其中最大的一块（1.7+2.0+1.4 = 5.1pp）全部落在分页中文 v10，也就是 §42.7(b)。
**所以为了达到他要的 90-95，§42.7 最终必须做**，只是顺序仍在 M1 与 G3 之后：
它需要一集全新音频 ＋ 容量棘轮门禁，是本清单里单价最高的一项，
必须等审计复活（能自动发现重排）之后再做，否则改完没有便宜的验收手段。

### 46.20 工单 M1'｜无人值守版：离线取数 ＋ 预写分叉（取代 §46.19）

**为什么改成离线**：`scripts/` 下**没有任何整集管线的命令行入口**
（只有 `run_allocation_only_replay.py` 这类分层重放），整集运行要靠 GUI，GPT 无人值守跑不了。
而 M1 想要的两件事都不需要整集运行：

- G1 的验收（S0089 是否从 `errors` 变 `degraded`、其余页是否零变化）
  **只依赖磁盘上已有的 checkpoint 产物**，是纯本地重算。
- 「翻译审计会不会复活」**不需要真的调一次审计**：那道门的条件就是
  `page_artifact["status"] == "PASS"`（`app/thread/subtitle_thread.py` 1073 行）。
  重算后的蓝图 `status` 一旦是 `PASS`，门就是开的，逻辑上可判定，不必花钱验证。

→ 所以 M1' 全程 **零 LLM 调用、零 ASR、零 GUI、零额度**，可以在无人值守下跑完。

**第一步（只读，唯一允许的新增文件）**

以 checkpoint `20260826T040659.244182-79951e43` 的现成产物为输入，
用**当前代码**（含 G1、G7）离线重算分页蓝图那一层，与原产物逐页 diff。
若没有现成入口，**允许且仅允许新增一个只读脚本** `scripts/measure_g1_blueprint_diff.py`；
**不许修改任何既有 `.py`**；不许写入 checkpoint 目录；不许删除或移动基线 checkpoint。

要输出的数字：

1. 重算后蓝图的 `status`、`errors` 条数、`degraded_page_count`、`degraded_parents` 列表。
2. `S0089`（`cue_index` 89）的 `renderable` / `degraded` 两个布尔值与最终字号档。
3. 总页数、内容变化的页数、其中归因 G1 的页数、归因 G7
   （`relative_clause_has_trailing_predicate`）的页数。**G7 单独计数，不许合并进 G1。**
4. 一句判定：`page_artifact["status"] == "PASS"` 是否成立
   （即 `translation-quality-audit.json` 那道整集跳过的门是否已被 G1 推开）。

**第二步：按数字自己分叉，不要等用户**

- **若第一步第 4 项成立（门已开）** → 继续做 §42.9 的剩余半条，
  **只许动 `app/core/subtitle_processor/translation_quality_audit.py` 一个文件**：
  (a) 请求失败后重试（含退避）；(b) 重试仍失败则把该批降批、最终降到单条兜底；
  (c) 解析层加自证矛盾过滤——模型 `reason` 自称「无错误／均正确」时不得生成 item（§42.9 实测泄漏 9.96%）。
  验证方式：**新增单元测试，用假响应驱动，不许联网、不许调模型、不许跑整集**；
  只跑 `--only fixed-id-translation-quality-audit`（必要时加 `syntax-check`）。
  交付数字：重试后成功批数／总批数（用假失败注入）、降批触发次数、
  自证矛盾过滤掉的条目数、新增测试数、`git diff --stat`。
- **若第一步第 4 项不成立（门仍关着）** → **不许**去改分页逻辑找原因。
  改动范围换成 `app/thread/subtitle_thread.py` 的 `_run_translation_quality_audit` 一处：
  把「蓝图非 PASS 就整集跳过」改成「只排除不合格的页，其余页照审」，并新增测试。
  同样不许联网、不许跑整集。交付：改动行数、新增测试数、
  以及在女性集产物上模拟时 `audited_subtitle_count` 从 0 变成多少。

**第三步：停**

写完报告就停，不要开始 G3／G2／G4／W6 任何一条。

**无人值守硬约束（全程适用）**

1. **最多两次提交**（第一步的新脚本一次，第二步的改动一次），本地提交，**不许 push**。
2. 不许 `git checkout .` / `git restore .` / `git stash`；不许改任何既有测试的断言。
3. 不许重跑任何一集（`测试音频／白宫集／日本集／女性集`都不许）；不许合成视频；不许开 GUI。
4. 不许动 `app/core/utils/podcast_learning_video.py`、`screen_editor.py`，
   以及任何「页面选哪个切分」的逻辑。本轮一个字都不许碰选择层。
5. 验证只用 `--only <相关用例>`；**全程不许 `--profile full`**；
   收尾最多允许一次 `--profile pipeline`。跑前关掉测试期 app.log 轮转（否则 WinError 32 刷万行）。
6. 顺手发现的任何其他问题都不许修，写进报告的「发现但没动」清单，一行一条带文件与行号。
7. 任何一步遇到自己判断不了的情况：**停下写报告，不许猜着改**。
   按 §46.17 的 Blocking Triage，无人值守时默认选项永远是「停下」而不是「修」。

**报告落地（用户醒来只读一个文件）**

写到 `docs/handoffs/M1-女性集离线取数-20260826.md`，结构固定：
第一段只放数字表；第二段一句话结论（门开了／没开、第二步做了哪一条）；
第三段「发现但没动」清单；第四段两次提交的哈希与 `git diff --stat`。
**先给数字，不要给叙述。**

### 46.21 M1' 结果验收（只读复核，2026-08-26 10:0x）

GPT 交付 `docs/handoffs/M1-女性集离线取数-20260826.md`。逐项复核结论如下。

**(1) G1 验收通过，且比预期更干净**

| 量 | 数字 | 判定 |
|---|---:|---|
| 重算蓝图 `status` | `PASS` | 门开了 |
| `errors` 条数 | `0`（原 1） | S0089 不再阻断 |
| `degraded_page_count` / `degraded_parents` | `1` / `S0089` | 按设计降级 |
| `S0089` `renderable` / `degraded` | `true` / `true` | 可上屏 |
| `S0089` 字号档 | 两页均 `56px` | 未被迫缩字号 |
| 总页数 / 内容变化页数 | `306` / **`0`** | 其余页零回归 |
| `page_artifact["status"] == "PASS"` | 成立 | 审计整集跳过的门已推开 |

**「其余 305 页零变化」这条是 G1 最重要的验收**：它证明 G1 只改了「失败怎么上报」，
没有碰「选哪个切分」。这是 §46.12 当初要求把 G1 与 G7 拆开的全部意义。

**(2) G7 实测零收益，且是当前唯一红灯的最可能来源 → 应当撤掉**

- **G7 归因页数 = 0**。即 `relative_clause_has_trailing_predicate` 在一整集 306 页真实数据上
  **一页都没有改变**。它承诺的收益在这一集上等于零。
- 同时 GPT 自报「`tests/test_article_display_readability_contract.py:3251` 的既有高压分页断言仍失败」。
  该行属于 `test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries`（3198 行起），
  失败的断言是 `assert [page["english"] for page in plan["pages"]] == [text]`——
  **一个本该单页的高压句现在被切成多页，正是选择层被改动的特征**。
  （注：07:10 那次回归的红灯在 3581 行的三行回落测试，位置已变，说明选择层改动不止一处后果。）
- 收益 0 页、代价 1 个既有测试变红 → **撤掉 G7 是本轮性价比最高的动作**，
  且它本来就是未经许可夹带进来的改动（§46.12）。
  撤法：手工删除那 5 处，**不许** `git restore` / `git checkout`。
  若撤完那条测试仍红，说明红灯另有来源，**停下写报告，不许继续改选择层**。

**(3) 两个必须补的欠账**

- **`持久化新增测试数 = 0`**。§42.9 的重试／降批到单条兜底／自证矛盾过滤三处逻辑
  目前**没有任何常驻测试保护**，只有两个临时内联假响应验证（跑完即消失）。
  下一轮任何人改这个文件都可能静默破坏它，而它恰好是 §46.8 认定的唯一能抓
  `job→jump` 那类错的机制。必须补成 `tests/` 里的持久化用例。
  已知假响应口径可直接固化：终止批 12/12、重试 18 次、降批 9 次、自证矛盾过滤 1 条、
  永久失败时最终 `batch_errors` 3 条（每 focus 一条单条错误）。
- **G1 至今没有提交**。`git show HEAD:app/core/utils/podcast_learning_video.py`
  里 `relative_clause_has_trailing_predicate` 与 `degraded_page_count` **均为 0 命中**，
  工作树里才有——也就是说 **G1 整套机制只活在未提交的工作树里**，
  任何一次误操作就没了。已提交的只有 `620106d`（测量脚本）与 `fdd9d83`（审计重试）。

**(4) 提交安全警告（本轮必须写进工单）**

`git status` 有 150 个文件被标记修改，`git diff --numstat` 合计 **+180374 / −177834**，
其中绝大多数是**整文件等量增删**（如 `app/_vendor/jieba/dict.txt` 109749/109749），
典型的**换行符（CRLF↔LF）噪音，不是真实改动**。
→ **绝对禁止 `git add -A` / `git add .`**，只许 `git add <具体文件>`。
否则真实改动会被 18 万行噪音淹掉，事后无法归因（这正是 §46.13 第三条要防的事）。

**(5) 排序结论：下一轮只做「落地与止血」，不做新机制**

1. 撤 G7（手改 5 处）→ 确认 3251 行那条测试恢复绿。
2. 给 §42.9 补持久化测试。
3. 单独提交 G1（只 add 相关文件），提交信息里写清「只改失败上报，不改切分选择，
   306 页 diff 为 0」。不许 push。
4. 做完停。G3／G2／G4／G5／W6 全部继续等。

**(6) 用户侧的下一步只有一件事：下一集新音频照常跑**

审计现在只是「代码上活了」，**还没有在任何真实一集上跑过一次**
（女性集那两次运行发生在修复之前，`audited_subtitle_count = 0`）。
不许为此重跑任何已出片集。所以第一份真实召回数据必须等他下一集新音频，
届时要读的四个数：`status`、`audited_subtitle_count / source_subtitle_count`、
`issue_count`、`batch_errors` 各 code 计数。
**那四个数才是判断 §42.7(b) 值不值得做的依据**——在拿到它们之前不要动翻译提示词。

### 46.22 红灯根因定位：G1 不只改了上报，它新增了一条选择路径（只读，2026-08-26 10:4x）

撤掉 G7 后那条测试**仍然红**（GPT 报告 `docs/handoffs/G1-G7撤除止血-20260826.md`，
`--only article-display-readability-contract` FAIL，耗时 319.90s，未提交）。
所以红灯不是 G7 造成的。我改用只读方式读代码定位，避免再花 320 秒盲试。

**(1) 先把真实改动量从换行噪音里剥出来**

`git diff --ignore-all-space --ignore-blank-lines --numstat`：

| 文件 | 真实改动 | 原始 numstat（含 CRLF 噪音） |
|---|---:|---:|
| `podcast_learning_video.py` | **+518 / −49** | +2910 / −2383 |
| `screen_editor.py` | **+653 / −16** | 同上量级 |
| `tests/test_article_display_readability_contract.py` | **+110 / −4** | — |

→ 后续所有 diff 一律加 `--ignore-all-space --ignore-blank-lines`，否则读不出真东西。

**(2) 失败的那条测试是 HEAD 里就有的（不是新写的）**

`git show HEAD:tests/...` 第 3092 行就有
`test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries`，
`S9513` 用例在 3109／3130 行。**即：这是既有契约被破坏，不是新测试写错。**

其 `S9513` 实际切分（GPT 报告第 24-27 行）：

1. `In 2025, the administration of Donald Trump announced that it would aggressively`
2. `revoke visas for Chinese nationals studying in unspecified critical fields.`

**副词 `aggressively` 被留在上一页，它的谓语 `revoke` 掉到下一页。**
这正是该测试名字要拒绝的那种不完整短语边界——**测试是对的，代码是错的**。
HEAD 的行为是抛 `RenderStructuralOverflowError`（测试的 `except` 分支接住），现在不抛了。

**(3) 根因：`_build_article_english_page_plan` 里新增的 review 回落候选没有做完整性门禁**

`app/core/utils/podcast_learning_video.py` 6355-6388：

```python
complete_normal_font_candidates = [
    candidate for candidate in candidates
    if not int(candidate.get("incomplete_review_count") or 0)
    and int(candidate.get("relaxed_raw_hard_count") or 0) <= 1
]
fallback_review_candidate = None
if (candidates and not complete_normal_font_candidates) or ...:
    failure_reasons.add("no_complete_normal_font_page_partition")
    if _return_candidates and candidates:
        fallback_review_candidate = min(
            candidates,
            key=lambda candidate: (int(candidate.get("incomplete_review_count") or 0), ...),
        )
```

`min(...)` 把 `incomplete_review_count` 当**排序键**，**不是过滤条件**。
所以当所有候选都有不完整边界时（`S9513` 正是这种），它照样挑一个出来返回
`status="candidate_bundle"` / `candidate_mode="review_fallback"`，于是不再抛错。

**这不是「失败怎么上报」的改动，这是「选哪个切分」的改动**——
正是 §46.13 第二条和 M1' 硬约束第 4 条明令禁止的那一层。
它同时解释了另一件事：GPT 在同一轮里**改掉了既有断言**
（`test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px`
原本 `for result in (bundle, plan): assert result["status"] == "render_structural_overflow"`，
被改成 `bundle` 期望 `candidate_bundle` / `fallback_review is True`）。
→ §46.12 当时判断「没有放宽测试」是**错的，需在此更正**：确实存在既有断言被放宽。

**(4) 修法：把排序键改成过滤条件，只此一处**

```python
fallback_pool = [c for c in candidates if not int(c.get("incomplete_review_count") or 0)]
```
只在 `fallback_pool` 非空时取 `min(fallback_pool, key=...)`；为空则**不产生回落候选**，
维持 HEAD 的失败关闭行为。

- `S9513`：所有候选都不完整 → 无回落 → 继续抛错 → 既有测试恢复绿。
- `S0038`（G1 要救的那条）：**能否存活取决于它是靠哪个条件落到 fallback 的**。
  若它是 `incomplete_review_count == 0` 但 `relaxed_raw_hard_count >= 2`，则仍被救；
  若它本身边界就不完整，则会被这道门挡掉、G1 的降级案例失效。
  **这一点必须先测量再动手，不许猜**。

**(5) 因此下一轮先花几秒钟做一次三行测量，再改一行**

对 `S9513`、`S0038`、以及 `test_no_safe_normal_font_partition...` 用的那条 cue，
各打印其全部候选的 `incomplete_review_count` 与 `relaxed_raw_hard_count`。
这是纯本地计算，秒级完成，**不许用 320 秒的整文件回归去试**。

**验证成本纪律（本轮新增，之后长期适用）**：迭代阶段直接调那一两个测试函数
（`python -c "import tests.test_x as m; m.test_a(); m.test_b()"`），秒级；
只有在最后一次收尾时才允许跑一次 `--only article-display-readability-contract`。
GPT 这轮花 319.90 秒只换回「仍然 FAIL」一句话，是可以避免的浪费。

**(6) 两条都必须绿才算过**

`test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries`
与 `test_renderable_review_fallback_is_degraded_without_blocking_the_blueprint`
必须同时通过，且 `test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px`
的既有断言要恢复原样。
**若为了救 S0038 必须放宽完整性门禁，则停下报告，不许自行取舍**——
那意味着 G1 的降级方案与既有分页契约冲突，需要重新设计（例如降级时不给页面、
只标记该父需人工处理），这属于设计决策，不属于本轮授权范围。

### 46.23 §46.22 的假设被实测推翻，真问题是两条测试在同一条 cue 上互相矛盾（2026-08-26 10:5x）

GPT 报告 `docs/handoffs/review-fallback-integrity-gate-20260826.md`。**我上一节的假设(4)错了，此处更正。**

**(1) 实测数字**

| cue | 候选数 | `(incomplete_review_count, relaxed_raw_hard_count)` |
|---|---:|---|
| `S9513` | 33 | **31 个 `(0,0)`**、2 个 `(1,0)` |
| `S0038` | 7 | 全部不完整：`(1,0),(2,0),(1,0),(2,0),(1,0),(1,0),(2,0)` |
| `test_no_safe_normal_font_partition...` 的 cue | 7 | **与 S0038 完全相同** |

→ **`S9513` 根本没走回落路径**：它有 31 个「完整」候选，走的是正常路径。
所以我说的「所有候选都不完整才被迫回落」对它不成立，加过滤治不了它。
`S9513` 的真问题在**完整性判定本身**：把 `aggressively | revoke`
这个割开副词与其谓语的边界算成了 `incomplete_review_count = 0`。

**(2) 更要紧的发现：那两条测试用的是同一条 cue，期望互相矛盾**

我核了源码，`test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px`
用的 `text` 与 `_syntax_backed_cue(text, "S0038")`，
与 G1 新写的 `test_renderable_review_fallback_is_degraded_without_blocking_the_blueprint`
**是逐字相同的同一条句子、同一个 ID**。

- 既有契约（HEAD 就有）：这条 cue 必须 `render_structural_overflow`，**失败关闭**。
- G1 的新测试：这条 cue 的蓝图必须 `PASS`、`degraded`、且 `plan["renderable"] is True`。

**同一输入，两个相反的期望。**所以「三条同时绿」在当前设计下不可能达成，
不是 GPT 没做到，是我给的目标自相矛盾。§46.22(6) 那条「必须三条同时绿」应作废。
（唯一起了作用的是同一节第(6)条的止损口：GPT 没有为了凑绿去删既有契约测试，而是停下报告。
这条纪律要保留。）

**(3) 出路：用仓库自己已有的人工提案 API，把两个层次分开**

关键线索在既有测试自己的 `except` 分支里——它接住 `RenderStructuralOverflowError` 之后调用的是：

```python
podcast_learning_video.propose_article_manual_page_word_ranges(
    cue, 2, allow_review_boundary=True, allow_hard_boundary=True)
```

**仓库早就有一条「失败关闭之后再另外提出人工分页方案」的正规通道。**
G1 本该用它，而不是去改 `_build_article_english_page_plan` 的返回值。正确分层是：

- **底层不变**：`_build_article_english_page_plan` 对这类 cue 继续 `render_structural_overflow`，
  既有契约原样保留（这也是 §46.12 说的「只改上报、不改选择」）。
- **蓝图层兜住**：`build_article_display_page_blueprint` 捕获该错误后，
  调 `propose_article_manual_page_word_ranges` 生成降级页，
  记进 `degraded_parents`，蓝图 `status` 保持 `PASS`，并**强制把该父推进审校队列**。

这样：既有契约绿、G1 新测试（蓝图 `PASS`/`degraded`/`renderable`）也能绿、
翻译审计那道 `status == "PASS"` 的门照样开、且降级页一定会出现在他的清单里不会静默上屏。

**(4) 但在动手之前必须先补一个我漏掉的步骤：HEAD 基线**

本轮和上轮都是在**未提交的工作树**上迭代，而这棵树里除 G1／G7 之外还有大量早先的未提交改动
（`--ignore-all-space` 口径下 `screen_editor.py` +653/−16、`podcast_learning_video.py` +518/−49）。
**我们从未确认这三条测试在 HEAD 上是什么状态**，所以无法判断 `S9513` 的红灯
是 G1 造成的、还是早先某轮改动造成的、还是 HEAD 本来就红。
在没有基线的情况下继续改选择层，就是拿假设换假设。

做法（非破坏性，不动当前工作树）：
`git worktree add ../vc-head-baseline HEAD`，在该副本里用同一个 `runtime\python.exe`
直接调那三个测试函数，报出各自 PASS/FAIL。**禁止** `git stash / restore / checkout` 达到同样目的。

**(5) 分叉规则**

- 若 `S9513` 那条在 HEAD **也是 FAIL** → 它是早于本轮的既有欠账，**不再阻塞 G1**。
  按 (3) 重做 G1 分层，只要求「既有失败关闭断言 ＋ G1 蓝图降级」两条绿，
  `S9513` 单独立工单（属于完整性判定，不在本轮授权内）。
- 若 `S9513` 在 HEAD **是 PASS** → 是工作树里某处改动破坏了它，**先归因再改**：
  在 HEAD 副本里逐个应用 `podcast_learning_video.py` 的改动块，找出第一个让它变红的块，
  报出块的行号范围。归因之前不许再改任何选择逻辑。

**(6) 记一笔方法论账（对我自己）**

这一轮的错误来源是：我在没有基线的情况下，直接对着一棵混合了多轮未提交改动的工作树提假设。
**今后凡是「某条既有测试红了」的问题，第一步一律是建 HEAD 副本确认它在基线上是什么状态**，
而不是先猜根因。代价对比：一次 worktree 基线是秒级，而上两轮各花了 319.90 秒／数十行改动才排除一个假设。

### 46.24 纠错机制：把「外部审计说的」降级为待核验前提（2026-08-26，用户要求）

用户原话：「你应该加入纠错机制啊，别让 codex 完全相信你说的啊，我都不知道最近几次让 gpt 做的东西对不对，
我怕越搞越杂」。这是本轮最重要的一条要求，因为它针对的是**流程缺陷而不是某个 bug**。

**(1) 失效点在哪：测量是「前奏」而不是「闸门」**

上一轮我确实要求 GPT 先打印三组数字再改代码，它照做了，数字也确实推翻了我的假设
（`S9513` 有 31 个完整候选 → 根本没走回落路径）。
**但它打完数字之后照样按我的原计划改了代码**——因为工单把测量写成了第一步，没写成"不符即停"。
于是错误假设仍然消耗了一轮改动。
→ **测量必须是闸门**：结果与前提不符时，本轮立即终止，只交差异报告。

**(2) 三条常驻纠错条款（每个工单都要带，写进 §46.13 模板）**

- **前提核验门**：工单开头必须有一节「本单依赖的前提」，逐条编号、每条都可用代码或产物核验。
  GPT 必须**先逐条核验并报「成立／不成立＋证据」**，其中任何一条不成立
  → **立即停止，不许执行后续任何步骤**，只交差异报告。
- **反驳义务（明确授权）**：外部审计（我）写的东西是**待核验的假设，不是事实**。
  发现前提、行号、函数名、数字与代码不符时，**反驳优先于执行**。
  「按指令做完了但方向是错的」比「拒绝执行并说明理由」严重得多。
  以后每单结尾固定一句：**「如果本单的前提与代码不符，请驳回本单并只给差异报告。」**
- **目标自洽检查**：验收目标里若出现两条断言，需先检查它们的**输入是否同一条**。
  同一输入而期望相反 → 目标自相矛盾，必须先指出、不许试图凑绿。
  （本轮实例：`test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` 与
  `test_renderable_review_fallback_is_degraded_without_blocking_the_blueprint`
  用的是逐字相同的同一条 `S0038` cue，期望相反。这是我下单时该自查而没查的。）

**(3) 常驻化（工单 D4，只改 `AGENTS.md`，不动代码）**

在 `AGENTS.md` 的 `## Scope Discipline` 之后新增一节 `## External Audit Claims Are Hypotheses`，
内容三句：
1. `EXTERNAL-AUDIT-*.md` 与外部审计给出的工单，其中的行号、函数名、数字、因果判断
   **都是待核验假设**，执行前必须核验。
2. 任一前提核验失败 → 停止本单，只交差异报告；**不许在错误前提上继续实现**。
3. 驳回一个前提不成立的工单是**正确行为**，不算未完成任务。

**(4) 用户侧的验收方式（他不读代码也能判断机制有没有生效）**

看 GPT 的报告开头有没有「前提核验」那一段、每条前提后面有没有跟数字或行号。
**没有这一段就是机制没生效**，无论后面写得多好都退回。

**(5) 回答「最近几次做的东西对不对、会不会越搞越杂」——用状态清点回答，不用保证回答**

事实层面：**最近两轮（撤 G7、加完整性过滤）零提交**，
所以我的两个错假设**没有沉淀进版本历史**，只留在工作树里。
但"杂"是真的，且早于这两轮：

| 现状 | 数字 | 性质 |
|---|---:|---|
| 工作树被标记修改的文件 | 150 | 其中绝大多数是 CRLF 噪音 |
| 原始 numstat | +180374 / −177834 | 不可读 |
| `--ignore-all-space` 后 `podcast_learning_video.py` | +518 / −49 | 真实改动，跨多轮，未提交 |
| `--ignore-all-space` 后 `screen_editor.py` | +653 / −16 | 真实改动，跨多轮，未提交 |
| G1 全套 | 未提交 | HEAD 里 `degraded_page_count` 0 命中 |
| 已知红灯 | ≥1 条既有测试 | 归因未完成 |

→ **当前最高优先级不是任何 G 系列机制，而是「清点并回到一个绿色的已提交基线」（工单 M2）**。
理由：现在连"代码处于什么状态"都没人说得清（包括我），
在这种树上继续叠机制，每一轮的归因成本都会上升。
M2 的验收标准是一句话：**HEAD 上那几条测试是绿的，且工作树里剩下的真实改动都有明确归属**。

---

## §46.25 M2 被驳回的复核：两个数都是真的，只是量的不是同一个东西（2026-08-26 11:2x）

GPT 驳回了 §46.24 末尾那份 M2 工单，理由是 P1/P2 基线过时。**驳回本身符合机制，不算未完成任务。**
但我把两边的数重测了一遍，结论是：**没有任何一条实质前提被推翻，四条里有两条是我把"口径"写漏了。**

### (1) P1 的 150 vs 40：两个数都对

| 命令 | 结果 |
|---|---|
| `git status --short` 按前两字分类 | ` M` 146、` D` 4、`??` 65（合计 215 行） |
| `git diff --numstat \| wc -l` | 150 |
| `git diff --ignore-all-space --ignore-blank-lines --numstat \| wc -l` | **44** |

GPT 报的是「109 行 = 40 modified + 4 deleted + 65 untracked」。
40 + 4 = **44**，正好等于忽略空白后的文件数。
也就是说它报的是**真实内容有改动的文件数**，我报的是**git 认为被修改的文件数**；
差出来的 146−40 = 106 个文件全是 CRLF 换行噪音（整文件等量增删）。
两个数都是真的，标签错了：那 109 不是 `git status --short` 的行数。

**这个差异对工单结论没有影响**，反而是好消息——真正要清点的文件只有 44 个，不是 150 个。

### (2) P2 的 +518 vs +524：差额是它自己上一轮加的

`podcast_learning_video.py` 上一轮加了约 14 行 `fallback_pool` 过滤（见 review-fallback-integrity-gate 报告），
所以 +518 → +524 是**它自己造成的漂移**，不是我的数错。
我在工单里写了「约 +518/−49」，用近似值当判定条件本身就是错的写法。

### (3) P3 我的表述不准确，GPT 的更新更准确

我写的是「HEAD 里一处都没有 `degraded_page_count`」，实际是：
`HEAD:app/` 里没有（生产实现确实未提交，这是实质结论，成立），
但 HEAD 的 docs 和 `scripts/measure_g1_blueprint_diff.py`（提交 620106d）里有引用。
以后这类前提一律限定路径：**`git grep degraded_page_count HEAD -- app/` 无输出**。

### (4) 机制要打的补丁：前提分两类

上一版工单把「结构事实」和「参考数字」混在同一节，等于给了一个必然会过时的停止条件——
任何数字在 GPT 动过树之后立刻失效，于是机制从"防错"退化成"卡在四舍五入上"。

从本节起，工单第零节必须分成两类，且各自写明核验命令：

- **判定性前提（A 类）**：结构性、可二值判定、不随行数漂移。
  例：某函数在 HEAD 存不存在、某标识符在 `HEAD:app/` 有没有、某测试当前是 PASS 还是 FAIL。
  **任一条不成立 → 立即停止本单，只交差异报告。**
- **待报数（N 类）**：所有计数、增删行数、文件数。
  写法一律是「**报出当前值**」，附精确命令；**N 类永远不是停止条件**，
  与我文档里的旧值不一致时，在报告里更正即可，继续执行。

工单末尾那句改成：「如果本单的**判定性前提**与代码不符，请驳回本单并只给差异报告。」

### (5) 我自己先做的目标自洽检查（§46.24 第三条，这次生效了）

上一版 M2 要求在 HEAD 副本里跑三个测试函数。实测：

| 测试函数 | HEAD | 工作树 |
|---|---|---|
| `test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries` | 存在 | 存在 |
| `test_renderable_review_fallback_is_degraded_without_blocking_the_blueprint` | **不存在** | 存在 |
| `test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` | 存在 | 存在 |

第二条是 G1 这轮新加的，HEAD 上根本没有这个函数——
上一版工单要求在基线里跑它，是又一个不可能同时成立的目标。
重发版只要求跑那两条既有测试。

另外记一笔环境事实：`git worktree list` 显示已有 8 个历史 worktree，其中 7 个标 `prunable`
（codex 临时目录、`E:/VideoCaptioner-baseline-compare`、三个 `-worktrees/` 分支副本）。
本单新建的副本用固定路径 `../vc-head-baseline`，与这些互不冲突；**不许 prune 或删除上面任何一个已有副本**。

### (6) M2' 工单正文（重发，替代 §46.24 末尾那份）

见下一节 §46.26。

---

## §46.26 工单 M2'（重发）：基线取证 ＋ 工作树盘点（2026-08-26）

格式按 §46.13；前提分类按 §46.25(4)。本单**不修任何代码**。

### 第零节 判定性前提（A 类，任一条不成立 → 立即停止，只交差异报告）

| # | 前提 | 核验命令 | 期望 |
|---|---|---|---|
| A1 | 当前 HEAD 是 `fdd9d83`，分支 `main` | `git rev-parse --short HEAD` ／ `git branch --show-current` | `fdd9d83` ／ `main` |
| A2 | G1 的生产实现未提交 | `git grep -c degraded_page_count HEAD -- app/` | 无输出（退出码非 0） |
| A3 | `test_renderable_review_fallback_is_degraded_without_blocking_the_blueprint` 在 HEAD 不存在、在工作树存在 | `git show HEAD:tests/test_article_display_readability_contract.py \| grep -c "def test_renderable_review_fallback"` ／ 同名 grep 工作树 | `0` ／ `1` |
| A4 | 工作树里 `test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries` 当前是 FAIL | 直接调该函数 | FAIL |

### 第零节之二 待报数（N 类，只报当前值，不是停止条件）

- N1：`git status --short` 按前两字分类计数（` M` / ` D` / `??` 各多少行）。
- N2：`git diff --numstat \| wc -l` 与 `git diff --ignore-all-space --ignore-blank-lines --numstat \| wc -l` 两个文件数。
- N3：`podcast_learning_video.py` 与 `screen_editor.py` 在 `--ignore-all-space --ignore-blank-lines` 口径下的 `+/−`。

### 第一节 三件事，顺序固定

**(1) 基线取证。** 新建非破坏性副本：`git worktree add ../vc-head-baseline HEAD`。
**禁止** `git stash` / `git restore` / `git checkout` 达到同样目的；
**禁止** 对 `git worktree list` 里已有的 8 个副本做 prune / remove。
在副本里用与主树相同的 `runtime\python.exe`，逐个直接调这两个函数（HEAD 上不存在第三个，跳过并注明）：

```
python -c "import tests.test_article_display_readability_contract as m; m.test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries()"
python -c "import tests.test_article_display_readability_contract as m; m.test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px()"
```

每条报 PASS / FAIL；FAIL 的报断言所在行号 ＋ 断言两侧的实际值（不要贴整段 traceback）。
**不要在副本里跑 `run_regression.py`。** 副本用完保留，不删，等我复核。

**(2) 工作树 hunk 盘点。** 只看这两个文件：

```
git diff --ignore-all-space --ignore-blank-lines -U0 -- app/core/utils/podcast_learning_video.py app/core/utils/screen_editor.py
```

逐 hunk 一行，格式固定为：`行号范围 | 一句话说它在做什么 | 归属`。
归属四选一：`G1`、`G7 残留`、`早先某轮`、`说不清`。
说不清的宁可写说不清，不要猜。

**(3) 提交拆分建议。** 只写建议，不执行。列出你建议的每个提交包含哪些**具体文件路径**，
以及为什么这几个文件应该在同一个提交里。
**绝对禁止** `git add -A` / `git add .`；本单不做任何 `git add`、`commit`、`push`、`reset`、`clean`。

### 第二节 报告

写到 `docs/handoffs/M2-基线与工作树盘点-20260826.md`，开头必须是「前提核验」一节，
A1-A4 逐条给「成立／不成立 ＋ 证据（数字或行号）」，N1-N3 给当前值。

如果本单的**判定性前提**与代码不符，请驳回本单并只给差异报告。

---

## §46.27 对 GPT「90-95% 自动化路线」提案的审阅（2026-08-26 11:14）

结论：**方向同意，六条里四条与本文档已有结论一致（这是收敛，不是新信息）；一条有致命缺口，一条不能未经测量就采纳。**

### (1) 已经一致的四条，不必再论证

| 提案 | 本文档对应 |
|---|---|
| 英文／ID／时间轴走严格路径，LLM 不许碰 | 一直是硬约束 |
| plan 层失败关闭 ＋ blueprint 层局部降级 | §46.23(3) 已给出同一分层（`propose_article_manual_page_word_ranges`） |
| S9513 单独立票，不用 fallback 门禁掩盖 | §46.23(2) 已定为独立工单（完整性判定层缺陷） |
| 用新音频统计而不是重跑人工校对集 | §46.20 / G6 已定；且「不许重跑已出片集」是用户级硬约束 |

### (2) 致命缺口：`degraded` 目前等于「静默出片」

提案把 `degraded` 当安全阀，前提是"进入人工审校队列"这件事真的会发生。
**实测不成立。** 两条证据：

- 女性集 S0089 就是 degraded 的实际形态：blueprint PASS、`degraded_page_count` 1、
  两页都是 56px、`renderable=True` —— 它**上屏了**，而且带着病句上屏了。
- 用户 2026-08-26 08:45 明确带着四处已知上屏残留发片（"赶时间"），
  并在 08:47 说"之前的不管了"。**审校队列这个出口在他的实际工作流里不存在。**

所以按现在的形态，`degraded` 只是把"整集失败"换成了"这一页悄悄错着出片"，
自动化率会在纸面上从 60% 跳到 95%，而屏幕上的错字一个都没少。

**必须补的一条（列为提案第 7 条）**：降级必须落到他真正会看的那个地方——
合成前的上屏校对清单，按父句列出 `degraded` 的页、页内英文与页内中文原文、降级原因，
一集一个文件。他校对时只看这张清单，而不是通读 306 页。
没有这一条，前面六条的收益无法验证，也不该宣称 90-95%。

### (3) 阈值没写数：整集失败线必须给具体值

提案说"降级页超过阈值时整集才失败"，没给阈值。以女性集为唯一样本（306 页、1 个降级父句）建议：
不可渲染页 `> 0` → 整集失败；降级父句数 `> 父句总数的 2%` → 整集失败；
ID／时间轴／词账本任一被改写 → 整集失败。
阈值一旦写进代码，必须同时在报告里输出分子分母，否则下一轮又要重测。

### (4) 第 3 条（分页中文只切不重排）不能未经测量就采纳

提案要求页面中文按父级中文的词序切开、禁止倒装补词。这与已测数据存在张力：
§42/§43 测得分页重排在多页父句里占 28-38%、精确率 69%、召回 15%。
禁掉重排会把"每页中英对不上"从少数情况变成系统性情况——
观众一次只看一页，页内中英错配对教学视频是直接的可读性损失。
这是一个**设计取舍，不是显然正确的修法**：
用父级中文切片 = 句子整体通顺、单页对应关系变差；
重排 = 单页对应好、31% 的改写有风险。

**必须先离线测量再决定**（零额度，用女性集 306 页现成产物）：
按父级中文切片重算所有多页父句的页面中文，与当前上屏版本逐页对比，
报三个数：完全一致的页数、切片版更好的页数、切片版更差的页数。
这就是 G4a 的内容，把它提前到第 3 条之前做。

### (5) 顺序问题：第一步不是新机制，是把已有的东西落地

提案说"先把整集被一个坏父句拖死降到很低"——那正是 G1，**它已经写完了**，
但只活在未提交的工作树里，并且让一条既有测试变红（§46.22/§46.23）。
所以真实的第一步是 M2'（基线取证 ＋ 工作树盘点，§46.26），
第二步是按 §46.23(3) 重做 G1 的分层并单独提交，第三步才是 S9513 独立票。
在"没人说得清代码处于什么状态"的树上讨论路线图，收益无法归因。

### (6) 90-95% 现在没有分母

审计至今没在任何一集真实音频上跑过（女性集那次 `audited 0`）。
**当前自动化率的真实值是未知，不是 60% 也不是 95%。**
第一个数据点等他下一集新音频；在拿到 `status` / `audited/source` / `issue_count` / `batch_errors`
这四个数之前，任何百分比目标都只是口号。

---

## §46.28 M2' 回执：两条红灯早于本会话，且 HEAD 本身就不绿（2026-08-26 11:5x）

GPT 交了 `M2-基线与工作树盘点-20260826.md`，前提核验齐全（A1-A4 全成立、N1-N3 给了当前值）。
**最重要的一条结论，把之前那场"是不是一条路走到黑"的担忧彻底钉死了：**

### (1) 两条测试在 HEAD（fdd9d83）上就是 FAIL —— 本会话的未提交改动没有造成它们

| 测试 | HEAD 结果 | 证据 |
|---|---|---|
| `test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries` | **FAIL** | `:3248`，S9513 被切成 `...would aggressively` / `revoke visas...` 两页，期望整句单页 |
| `test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` | **FAIL** | `:1694`，`bundle.status` 期望 `render_structural_overflow`，实际 `candidate_bundle` ＋ `candidate_mode=manual_review_fallback`；**同次调用 `plan.status` 仍是 `render_structural_overflow`** |

含义有两层：
- **止血结论**：这两条红灯是 HEAD 就带的欠账，不是这个会话（也不是 G1 的未提交改动）新挖的坑。
  §46.22 里我一度以为是 G1 造成的，§46.23 已撤回；现在基线取证给了铁证——撤回是对的。
- **新的、更硬的事实**：**HEAD 本身就不绿。** M2 原本的验收标准是"回到一个绿色的已提交基线"，
  现在证明**那个绿色基线根本不存在**——最近一次提交 fdd9d83 就带着这两条红灯。
  所以"拆分提交回到绿基线"这条路要改：不能假设有绿基线可退，只能选
  (a) 先把 HEAD 这两条红灯修绿再谈 G1，或 (b) 明确把它们记为"提交时已存在的已知欠账"，G1 叠在上面。

### (2) `bundle` 红、`plan` 绿 —— 正好指向 §46.23(3) 的分层修法

第二条测试的证据里有一处关键：同一次调用，`bundle.status` 是坏的（漏成了 `manual_review_fallback`），
但 `plan.status` 已经是 `render_structural_overflow`（失败关闭）。
也就是说**下层 plan 的失败关闭是对的，是上层 bundle 把 manual_review_fallback 泄漏了出来**。
这与 §46.23(3) 的处方完全吻合：plan 层继续失败关闭，降级只应发生在 blueprint 层。
换句话说，**G1 重做分层这件事，顺带就是修好这两条红灯的正解**——不是两件事，是一件事。

### (3) 工作树盘点：G1 干净可归属，G7 零残留

`git diff --ignore-all-space --ignore-blank-lines -U0` 口径下：
- `screen_editor.py`（**实际在 `app/core/subtitle_processor/`，不是我工单写的 utils**）：真实改动约 26 个 hunk，
  G1 占 6 处（degraded 状态初始化／统计写入产物与校验摘要），其余全是"早先某轮"的翻译提示词 v8/v10、
  backchannel 口头语保留、checkpoint 恢复。
- `podcast_learning_video.py`：G1 集中在 4801-6463（人工分页候选＋review fallback 池＋completeness 过滤）
  和 8322-8511（blueprint 层 degraded 标记与阈值失败），归属清晰；其余是词卡/视觉排版的"早先某轮"。
- **`relative_clause_has_trailing_predicate`（G7）当前零命中，确认已彻底撤除。**
- N 值复核：真实改动文件 44 个（=40 改+4 删），CRLF 噪音已被忽略；`podcast_learning_video.py` +524/−49、
  `screen_editor.py` +653/−16，与我上一版工单里的近似值差异已在 §46.25 解释过，不再是问题。

### (4) 提交拆分建议已给（四包），但先别提交

GPT 建议分四包：G1 分层（最后做）、翻译语义、checkpoint/重试、词卡视觉。
方向合理，但它自己也写了"当前不能提交，因为 HEAD 与工作树测试都暴露了 bundle/plan 契约问题"。
**同意先不提交。** 提交顺序要等 (1) 里的 (a)/(b) 决策定了才动。

### (5) 下一步（等用户拍板 (a) 还是 (b)）

两条路我都写清成本：
- **(a) 先修红再提交**：按 §46.23(3) 让 blueprint 层吃掉降级、bundle 不再泄漏 manual_review_fallback、
  S9513 谓语完整性单独判定 → 两条测试转绿 → 再把 G1 那几个 hunk 单独提交。
  好处是提交历史干净、S9513/S0038 真被修好；成本是这是一次真代码改动，要按前提核验门下单。
- **(b) 先提交再修**：把两条红灯记为 HEAD 已存在的已知欠账，先把 G1 落盘（degraded 机制先固化），
  红灯留给独立票。好处是 G1 不再只活在工作树里（当前风险）；成本是提交历史里带着两条已知红灯。

我的倾向是 (a)：因为 (1)(2) 已经证明"修红灯"和"G1 重做分层"是同一件事，分开做等于做两遍。

---

## §46.29 工单 G1'：修绿两条红灯 ＋ 降级清单 ＋ 数量闸门（2026-08-26）

用户拍板走 (a)，并追加一条硬约束：**"没办法的就标红放着我处理，但不能太多"**。
这把 degraded 从"静默上屏"改成"有出口＋有上限"。本单是真代码改动，按前提核验门执行。

### 用户约束翻译成代码

- "标红放着我处理" → degraded 页必须落到**合成前的上屏校对清单**（§46.27 第 7 条），他只看这张。
- "不能太多" → 数量闸门：**不可渲染页 > 0 立即整集失败；degraded 父句 > 父句总数 2% 整集失败**。
  2% 在约 270 句的一集里≈5 句；女性集实测只有 1 句，远在线内。阈值写常量，报告必须带分子/分母。

### 第零节 判定性前提（A 类，任一不成立 → 停止只交差异报告）

| # | 前提 | 核验 | 期望 |
|---|---|---|---|
| A1 | HEAD=fdd9d83、main | `git rev-parse --short HEAD` | fdd9d83 |
| A2 | 基线副本仍在 | `git worktree list \| grep vc-head-baseline` | 有一行 |
| A3 | `test_no_safe...` 同次调用 plan 已失败关闭、bundle 泄漏 | 见 §46.28(2) | plan=`render_structural_overflow`、bundle=`candidate_bundle` |
| A4 | `screen_editor.py` 在 `app/core/subtitle_processor/` | `ls app/core/subtitle_processor/screen_editor.py` | 存在 |

### 第一节 改动（四件，顺序固定，每件改完立刻单测该函数）

1. **堵住 bundle 泄漏**（治 `test_no_safe_normal_font_partition_fails_closed`）。
   plan 层已正确失败关闭，不要动。只在上层 bundle：当 plan 是 `render_structural_overflow` 时，
   bundle 不许再降级成 `manual_review_fallback` 返回，必须同样失败关闭。
   验收：`test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` 转 PASS。

2. **S9513 谓语完整性**（治 `test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries`）。
   在边界判定层加一个显式检查：不许把动词与其宾语（`aggressively` / `revoke visas`）从中间切开。
   这是 §46.23(2) 定的独立缺陷，**用完整性判定，不要用 fallback 门禁去掩盖**。
   验收：该测试转 PASS，S9513 回到整句单页。

3. **blueprint 层降级出口**（§46.23(3) 分层）。
   blueprint 捕获 plan 的失败关闭 → 调 `propose_article_manual_page_word_ranges` 生成可渲染页 →
   记 `degraded_parents` → `status` 保持 PASS。
   数量闸门：不可渲染页 > 0 或 degraded 父句 > 父句总数 2% → 整集 ERROR（不是 PASS）。
   阈值写成命名常量；产物里输出 `degraded_page_count` / `total_parent_count` / 比例。

4. **降级上屏校对清单**（用户"放着我处理"的落点）。
   合成前写一个文件，每个 degraded 父句一行：父句 ID、涉及的页、页内英文、页内中文、降级原因。
   一集一个文件，放 `docs/handoffs/` 或产物目录（你定，报告里写清路径）。

### 第二节 验证（省额度）

迭代期只调单个函数：`python -c "import tests.test_article_display_readability_contract as m; m.test_x()"`。
四件都改完，**收尾只跑一次** `python scripts/run_regression.py --only article-display-readability-contract`。
另外用女性集 306 页现成 checkpoint 产物离线生成一次降级清单（零额度），确认 degraded 父句数=1、在 2% 线内，
把这张清单贴进报告，让用户眼见"不能太多"确实成立。

### 第三节 边界

本单**不提交、不 push、不 git add**；改绿并出报告即止，提交拆分留下一单。
基线副本 `../vc-head-baseline` 不删。读 diff 一律 `--ignore-all-space --ignore-blank-lines`。
报告写到 `docs/handoffs/G1-修绿与降级清单-20260826.md`，开头「前提核验」A1-A4 逐条给证据。
如果本单的**判定性前提**与代码不符，请驳回本单并只给差异报告。

---

## §46.30 G1' 回执复核：三条目标测试绿了，但 S9513 的修法碰坏了 S9522（我亲自跑基线 A/B 推翻了 GPT 的"本来就红"）（2026-08-26 12:5x）

GPT 交了 `G1-修绿与降级清单-20260826.md`：三条目标测试 PASS、女性集降级清单就 S0089 一行（1/271，闸门内）。
**这两点是真的、是好的。** 但它的收尾回归里冒出第四条红灯 `test_three_line_fallback_promotes_complete_two_page_alternative`（S9522），
它写的是「既有 S9522 断言，HEAD 基线副本同样 FAIL；未改选择逻辑」——**这句话我没信，自己跑了基线 A/B，结论相反。**

### (1) 我做的验证（同一个无 spaCy 环境，只换 `podcast_learning_video.py` 一个文件）

| 被测版本 | `test_three_line_fallback...`（S9522） |
|---|---|
| HEAD (fdd9d83) 的 `podcast_learning_video.py` | **PASS** |
| 当前工作树的 `podcast_learning_video.py` | **FAIL** |

先确认该测试函数在 HEAD 与工作树**逐字节相同**（不是本轮新增或放宽的断言），
再用 importlib 把两个版本分别塞进 `sys.modules` 同一位置跑同一个测试，控制变量只有这一个文件。
**结论：S9522 在 HEAD 是绿的，是本轮改动把它弄红的。GPT 的"本来就红/未改选择逻辑"不成立。**

### (2) 坏在哪：S9513 的谓语完整性修法过度，劈开了名词短语

S9522 期望第二页是 `into the most aggressive expansion engine in the modern food and beverage industry.`（HEAD 就是这么切的）。
工作树现在切成：
- 第一页 `You're getting plugged directly into the most aggressive expansion`
- 第二页 `engine in the modern food and beverage industry.`

把名词 `expansion engine` 从中间劈开了。也就是说，为治 S9513（别把动词/宾语劈开）加的边界完整性检查**用力过猛，反手在 S9522 制造了新的短语劈裂**。这正是"修一处碰坏一处"的经典形态，也是我一开始坚持先建基线的原因。

### (3) 处置：不提交，narrow 修法后重验四条再提交

- **不能提交。** G1' 现在是"修好两条、碰坏一条"，净值不清，提交进历史等于把回归固化。
- 下一单（G1''）：把 S9513 的完整性检查收窄到只针对"动词—宾语"这类真正的谓语切割，
  不要波及 `expansion engine` 这种名词修饰关系；判据以"HEAD 上 S9522 本来能过"为锚。
- 验收改成**四条同时绿**：原三条 ＋ `test_three_line_fallback_promotes_complete_two_page_alternative`，
  并且要求 GPT 自己也在 `../vc-head-baseline` 里把这第四条跑一遍、报 HEAD 上是 PASS（纠正它这次的误报）。
- 机制备注：这次是 GPT 的**自证报告出错**（把自己造成的回归说成既有欠账）。
  纠错机制这次是靠我方独立跑基线 A/B 抓到的——说明"反驳义务"不能只让 GPT 单方面执行，
  我方对"某测试本来是不是绿"这类可秒级判定的结论，必须自己跑一遍基线，不接受口头断言。

> **【2026-08-26 13:xx 撤回】本节 (1)(2)(3) 的结论错了，见 §46.31。**
> 我那次 A/B 跑在**缺 spaCy 模型**的 VM 里（会打印 "spaCy English model not found"），
> 分页走的是降级路径，不是生产实际路径。GPT 用带 spaCy 的 runtime 跑，HEAD 上 S9522 本来就 FAIL。
> 后来我把 runtime 里的 en_core_web_sm 模型接进 VM 重跑，**HEAD 与工作树 S9522 都 FAIL 且切法相同**——
> 本轮没碰坏 S9522，GPT 的 G1' 报告是对的，G1'' 被驳回也是对的。

---

## §46.31 撤回 §46.30：S9522 是既有红灯，本轮没碰坏它；错在我用了缺模型的环境（2026-08-26 13:xx）

GPT 驳回了 G1''，理由是判定性前提 A3（"HEAD 基线 S9522 PASS"）不成立——它在 `../vc-head-baseline`
用真 runtime 跑，HEAD 上 S9522 就是 FAIL，切成 `...expansion engine` | `in the modern...`。
**这次是 GPT 对、我错。纠错机制这一环反向抓到了我的错。**

### (1) 我错在哪：VM 缺 spaCy 模型，跑的是降级分页路径

§46.30 那次 A/B 我在 VM 里跑，日志有 "spaCy English model not found; syntax-assisted subtitle cutting disabled"。
分页器在**没有句法模型**时走的是另一条路，恰好让 HEAD 版把 S9522 切对、工作树版切错，
于是我误判成"本轮把它弄红的"。但生产 runtime 是带 spaCy 的，这条降级路径根本不代表真实行为。

### (2) 补跑：把 runtime 的模型接进 VM，HEAD 与工作树同为 FAIL

我把 `runtime/Lib/site-packages/en_core_web_sm/en_core_web_sm-3.8.0` 通过 monkeypatch `spacy.load`
接进 VM 的 spaCy(3.8.15)，重做同一 A/B：

| 被测版本（spaCy ON） | S9522 |
|---|---|
| HEAD (fdd9d83) 的 `podcast_learning_video.py` | **FAIL** |
| 当前工作树的 `podcast_learning_video.py` | **FAIL** |

两边同为 FAIL、切法相同。**结论：S9522 在 HEAD 上本就 FAIL，是长期既有欠账，本轮没有改变它。**
这与 GPT 的 G1' 报告（S9522 既有红灯）一致。

### (3) 真实状态修正

- HEAD（真实环境）本就是红的：至少 S9513、S0038、S9522 三条 FAIL。**不存在绿色基线可退。**
- **G1' 是净改善、无回归**：把 S9513、S0038 两条从红改绿，S9522 仍是它没去动的既有红灯。
  §46.30 里"修好两条、碰坏一条"的说法作废，正确说法是"修好两条、留着一条既有红灯没动"。
- G1'' 作废（它的前提本身是我给错的）。

### (4) 机制教训（写死，双向）

1. "某测试本来是不是绿"这类判定，**必须在与生产一致的环境里跑**。
   VM 缺 spaCy 模型时，分页走降级路径，绝对 PASS/FAIL 不可信；
   要么把 runtime 的 en_core_web_sm 接进来（可行，已验证），要么就以 GPT 在真 runtime 的结果为准。
2. 纠错机制是双向的：上一轮我用它抓 GPT 的误报，这一轮 GPT 用它抓我的误判。**两边都可能错，谁的结论都要能被基线复现。**
3. 我给工单写判定性前提时，**不能把我自己没在生产环境验证过的结论当 A 类前提**（A3 就是这么翻车的）。

### (5) 下一步：先确认无回归，再提交 G1'（不再改边界逻辑）

不要再动 S9513 的边界逻辑了（两次教训：碰边界就起涟漪）。改为纯验证 ＋ 提交：
- 见 §46.32 工单：在工作树和 `../vc-head-baseline` 各跑一次 `--only article-display-readability-contract`，
  导出两份完整 pass/fail 清单，做差集。
- 判据：**工作树的失败集合 ⊆ 基线的失败集合**（本轮只减红不增红）→ G1' 无回归，可提交。
  若出现基线绿、工作树红的项 → 那才是真回归，停下报告。
- S9522 归为独立欠账票，本轮不修（它是既有红，和 G1' 无关）。

---

## §46.32 工单 G2-verify：只验证 G1' 无回归、再按 M2 归属提交（不改任何 .py 逻辑）（2026-08-26 13:xx）

以下整段即发给 GPT 的工单（按 §46.13 八条）。核心判据是"失败集子集"，不是任何单条测试的预设结果——
因为 §46.30 就是我把一条没在生产环境验过的结果当前提才翻车的。

```
按 §46.13 做一单，代号 G1'-verify-commit。这一单不改任何 .py 逻辑、不改任何测试断言，只做验证＋提交。

【开工前先回述确认（三行）】
1. 当前 HEAD 短号 =（应为 fdd9d83），分支 =（应为 main）。
2. git worktree list 里有没有 ../vc-head-baseline 指向 fdd9d83（detached）。
3. 当前工作树里 G1／G1' 的未提交改动是否仍在（podcast_learning_video.py、screen_editor.py 等）。
以上任一条不成立，停止本单、只给差异报告。注意：本单不预设任何单条测试是绿还是红。

【要测什么】
在两个树上各跑一次同一批 contract 测试，只跑这一个契约，禁止全量套件、禁止 ASR／faster-whisper／spaCy 模型下载／合成／重跑管线，单次超一分钟就是跑错了：
  runtime\python.exe scripts\run_regression.py --only article-display-readability-contract
- A：当前工作树跑一次，导出完整用例级 pass/fail 清单（每个测试函数一行 PASS/FAIL）。
- B：在 ../vc-head-baseline（HEAD=fdd9d83）上，用你在 M2／G1'' 里已验证可行的方式跑同一批，导出同样格式的清单。
两次都要带上正式 runtime 的 spaCy 英文模型（en_core_web_sm，runtime\Lib\site-packages 里那个），否则分页走降级路径、结果不算数。

【判据（先给数字再给结论）】
先贴两份清单和它们的差集，再下结论：
- 令 F_base = 基线 B 的失败函数集合，F_wt = 工作树 A 的失败函数集合。
- 无回归判据：F_wt ⊆ F_base（工作树只减红、不增红）。
- 报出三个数：基线红几条、工作树红几条、被 G1' 修绿的是哪几条（F_base − F_wt）。
- 若出现任何"基线 PASS 但工作树 FAIL"的函数（F_wt − F_base 非空），那就是真回归：停止本单、只给报告、不要提交。
预期：S9513、S0038 从红转绿；S9522 两边都红（既有欠账，本单不碰）。但一切以你导出的清单为准，不以这句预期为准。

【提交（只有判据通过才做）】
- 只按 M2 盘点里归属为 G1 / G1' 的 hunk 暂存，用 git add -p 逐块选，禁止 git add -A / git add . / git add 整个文件（这两个文件里还混着不属于 G1 的历史改动，整文件暂存会把它们一起带进去）。
- 暂存后先跑 git diff --cached --ignore-all-space --ignore-blank-lines 贴出来，确认暂存集只含 G1／G1' 的 hunk，不含别的。
- 确认无误后提交，commit message 说明"落盘 G1 文章分页分层＋G1' 修绿 S9513/S0038＋降级校对清单；S9522 为既有欠账未动"。不要 git push。
- 提交后停下，把 commit 短号和 git show --stat 贴回来。

【看见别的问题】
只许写"发现但没动"清单，不许顺手改。

【红线】
不动 stable-runs，不重跑测试音频／白宫集／日本集／女性集，不许 git checkout / restore / stash，不许 prune／删除任何 worktree 副本，不许 push。

如果本单的判定性前提与代码不符，请驳回本单并只给差异报告。
```

### §46.33 G1'-verify 回执：撞上我自己的一分钟红线，非 GPT 之错（2026-08-26 13:27）

GPT 按单执行，三条前提成立，但两树的契约运行都在 60 秒未完成，它照工单"超一分钟就是跑错了"到点 Ctrl+C 中止，
判据无法计算，正确地停止提交、零改动。**这是我的红线设错了，不是 GPT 的问题。**
病因：`article-display-readability-contract` 是纯离线契约，慢是因为它在用例里反复加载 spaCy 英文模型十几次
（基线捕获文件 1776 字节全是 spaCy 加载日志，没有 ASR/合成）。§46.13 那条"一分钟"是为拦全量套件／ASR 定的，
对这个反复 reload 模型的离线契约太紧。
修法：对**这一个离线契约**放开墙钟上限（给到十几分钟），真正的红线仍是"不许碰 ASR／faster-whisper／模型下载／合成／重跑管线／全量套件"，而不是墙钟。
已发 G1'-verify-commit-r2（下面整段），只改这一处，其余判据与红线不变。

```
按 §46.13 做一单，代号 G1'-verify-commit-r2。承接 G1'-verify-commit：那一单撞上"超一分钟就中止"的限制而中止，本单只把这一条限制放开，其余不变。仍不改任何 .py 逻辑、不改任何测试断言，只做验证＋提交。

【为什么放开时间】
article-display-readability-contract 是纯离线契约，耗时长只是因为用例里反复加载 spaCy 英文模型，不是在跑 ASR/合成。所以本单允许这个契约跑到自然结束（预计几分钟到十几分钟）。真正的红线仍是：不许触发 ASR／faster-whisper／模型下载／视频合成／音频管线重跑／全量测试套件——一旦看到这些立即停。墙钟不再是停止条件，只要它老老实实在跑这一个契约。

【开工前先回述确认（三行）】
1. HEAD 短号 =（应为 fdd9d83），分支 =（应为 main）。
2. git worktree list 里有没有 ../vc-head-baseline 指向 fdd9d83（detached）。
3. 工作树里 G1／G1' 未提交改动是否仍在。任一不成立→停止、只给差异报告。本单不预设任何单条测试是绿还是红。

【要测什么】
两树各跑一次同一批 contract，只跑这一个契约，带上正式 runtime 的 spaCy 模型（en_core_web_sm）：
  runtime\python.exe scripts\run_regression.py --only article-display-readability-contract
- A：当前工作树，导出完整逐函数 PASS/FAIL 清单（每个测试函数一行）。
- B：../vc-head-baseline（HEAD=fdd9d83），用你在 M2／G1'' 已验证可行的方式跑同一批，导出同样格式。
让它自然跑完再取汇总；若脚本汇总不含逐函数结果，改用能列出每个函数 PASS/FAIL 的方式（如 pytest 的 -rA），但仍只跑这一个契约文件、仍带 spaCy 模型、仍禁 ASR/合成/全量。

【判据（先给数字再给结论）】
先贴两份逐函数清单和差集，再下结论：
- F_base=基线失败函数集，F_wt=工作树失败函数集。
- 无回归判据：F_wt ⊆ F_base（只减红不增红）。
- 报三个数：基线红几条、工作树红几条、被修绿的是哪几条（F_base−F_wt）。
- 出现任何"基线 PASS 但工作树 FAIL"（F_wt−F_base 非空）=真回归：停止、只给报告、不提交。
预期 S9513/S0038 转绿、S9522 两边都红，但以导出的清单为准，不以这句为准。

【提交（只有判据通过才做）】
- 只按 M2 盘点里归属 G1/G1' 的 hunk 用 git add -p 逐块暂存，禁止 git add -A / git add . / git add 整个文件。
- 暂存后先 git diff --cached --ignore-all-space --ignore-blank-lines 贴出来确认只含 G1/G1' hunk。
- 确认后提交，message 说明"落盘 G1 分页分层＋G1' 修绿 S9513/S0038＋降级校对清单；S9522 为既有欠账未动"。不要 push。
- 提交后停下，贴回 commit 短号和 git show --stat。

【看见别的问题】只许写"发现但没动"清单，不许顺手改。
【红线】不动 stable-runs，不重跑测试音频／白宫集／日本集／女性集，不许 git checkout/restore/stash，不许 prune/删除 worktree，不许 push，不许碰 ASR/模型下载/合成/全量套件。

如果本单的判定性前提与代码不符，请驳回本单并只给差异报告。
```

### §46.34 G1'-verify-r2 回执：黄金环境跑通，推翻两处旧结论（2026-08-26 13:50）

这是至今**第一份可信的全契约 A/B**：真 runtime、真 spaCy、pytest（有 fixture）、跑到自然结束（基线 408s／工作树 485s）。
用它一次性纠正了两个都源自"坏 harness"的旧误判。

**数字（gold-standard）**

| | 基线 HEAD fdd9d83 | 当前工作树 |
|---|---:|---:|
| 契约函数数 | 107 | 110 |
| PASS | 106 | 108 |
| FAIL | 1 | 2 |

- 基线唯一红：`test_three_line_fallback_promotes_complete_two_page_alternative`（S9522）。
- 工作树两红：上面这条（既有）＋ `test_tight_clause_entries_need_explicit_review_before_page_selection`（本轮新增函数，基线没有）。
- `F_wt − F_base = {test_tight_clause…}`（非空）→ 子集判据不通过，GPT 正确停止提交、零改动。

**推翻结论一：§46.28「那两条测试在 HEAD 上就是 FAIL、没有绿色基线」是错的。**
`test_high_pressure_secondary_review_rejects_incomplete_phrase_boundaries` 与
`test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` 在**基线与工作树都 PASS**（已逐行核对两份清单）。
M2 当时是"直接调这两个测试函数"（非 pytest、无 fixture，很可能也没带 spaCy）才得出 FAIL——
和 §46.30 同一类环境假象。**真相：HEAD 本身几乎全绿（106/107），唯一真实既有红灯只有 S9522。**
连带作废：所谓"G1' 修绿了 S9513/S0038 两条"——这两条从来没红过，G1' 在本契约里**修绿数＝0**。

**推翻结论二（部分）：本轮不是"零回归"。** 工作树确实新增了一条基线没有的失败函数 `test_tight_clause`。
但它不是行为回归，是**测试残留**：该测试断言 `_article_display_boundary_decision(...)` 返回值里有
`relative_clause_has_trailing_predicate` 这个键（第 2171 行），而这个键是 G7 的字段、已随 G7 撤除被删（全仓 grep：
该标识符只剩在测试文件、docs、`scripts/measure_g1_blueprint_diff.py` 里，**app/ 生产代码里没有**）。
所以测试取键即 KeyError→FAIL。这正是 §46.13 记过的"夹带"模式：G1/G7 期加进来的测试，绑着一个后来被删的字段，成了孤儿。

**但这条测试不是纯垃圾。** 它的第一例（"person who … wasn't just wasting wood"，trailing_predicate=True）
断言分页评分返回 None，即"关系从句入口把后面的谓语甩掉时应拒绝"——**和 S9513 的谓语完整性是同一个诉求**。
G7 用 `relative_clause_has_trailing_predicate` 暴露它，G7 删了，这个诉求现在（如果还在）应由 G1' 的完整性检查承接。
所以修法是二选一，**需要先确认诉求是否已在现有代码里存活，再决定**：
(a) 若诉求已由 G1' 的完整性检查覆盖→把该测试改写成用存活的机制断言，不再引用已删字段；
(b) 若该测试纯粹测 G7 已删功能、诉求别处已有覆盖→作为"完成 G7 撤除"的收尾把它删掉。
**两种都不许把 `relative_clause_has_trailing_predicate` 字段加回去**（那是走回头路）。

**当前净状态（更新）**
- HEAD 几乎全绿，唯一既有红＝S9522（长句分页选择，独立欠账票，本轮不碰）。
- 工作树相对 HEAD：没修绿任何契约测试，新增一条孤儿测试失败（test_tight_clause，绑已删 G7 字段）。
- G1' 的"分层降级＋女性集降级清单"部分仍是真实产物（§46.29 那几项），但**不能连着这条失败测试一起提交**。

**下一步（待用户拍板）**：先让 GPT 把 test_tight_clause 定性清楚（诉求是否已由现有完整性检查覆盖），
再据此决定删或改写——这是测试层改动，不碰分页边界逻辑。定性清楚且改成绿后，重跑子集判据，
`F_wt ⊆ F_base`（都只剩 S9522）即可提交。见 §46.35 工单。

### §46.35 工单 G1'-orphan-test：先定性孤儿测试、再删或改写、重跑子集判据、提交（2026-08-26 14:xx）

```
按 §46.13 做一单，代号 G1'-orphan-test。目标：把工作树里唯一比 HEAD 多出来的失败测试
test_tight_clause_entries_need_explicit_review_before_page_selection 处理成绿（这是测试层，不改任何分页边界逻辑、不加回任何已删字段），然后重跑子集判据并提交 G1'。

【开工前先回述确认（三行）】
1. HEAD 短号=（应 fdd9d83），分支=main。
2. 工作树 tests/test_article_display_readability_contract.py:2138 有 test_tight_clause_entries_need_explicit_review_before_page_selection，第 2171 行断言 _article_display_boundary_decision(...) 的返回里有 relative_clause_has_trailing_predicate 键。
3. 全仓（排除 runtime/）grep relative_clause_has_trailing_predicate：确认 app/ 生产代码里已无此字段（只剩测试/docs/measure 脚本）。
任一不成立→停止、只给差异报告。

【第一步：定性（先给事实再动手）】
回答三问并贴证据：
Q1 该测试第一例（trailing_predicate=True，"person who ... wasn't just wasting wood"）表达的诉求是"关系从句入口甩掉后续谓语时，该边界的分页评分应为 None（拒绝）"。这个诉求在当前工作树代码里还成不成立？（直接调 _article_page_break_score 看是否返回 None，贴结果）
Q2 这个诉求（拒绝甩谓语的关系从句边界）在**别的现存测试**里有没有覆盖？（grep 同契约文件里断言同类行为的用例，列出函数名）
Q3 该测试第二例（trailing_predicate=False）表达"关系从句不甩谓语时该 split 允许上屏且进入分页起点"，当前代码是否满足？

【第二步：按定性结果三选一】
- 情形A：诉求在代码里成立、且已有别的现存测试覆盖 → 直接删除 test_tight_clause 整个函数（它只剩在引用已删 G7 字段，属 G7 撤除收尾）。
- 情形B：诉求在代码里成立、但没有别的测试覆盖 → 把 test_tight_clause 改写成用现存机制断言（例如断言 _article_page_break_score 对甩谓语例返回 None、对不甩例进入 _page_starts），删掉对 relative_clause_has_trailing_predicate 的引用。不许加回该字段。
- 情形C：诉求在代码里已不成立（甩谓语例现在不再被拒绝）→ 这是真缺陷不是测试问题，停止本单、只给报告，不要删测试也不要提交。
只允许改这一个测试函数，不许动其它测试断言、不许动 app/ 逻辑、不许加回 relative_clause_has_trailing_predicate。

【第三步：重跑子集判据（同 §46.33 环境，带 spaCy、跑完）】
runtime\python.exe scripts\run_regression.py --only article-display-readability-contract  （工作树）
基线 B 用 ../vc-head-baseline 同法跑一次。导出两份逐函数 PASS/FAIL 清单。
判据：F_wt ⊆ F_base。预期两边都只剩 S9522（test_three_line_fallback）。
出现任何"基线 PASS 但工作树 FAIL"→停止、只给报告、不提交。

【第四步：提交（判据通过才做）】
- 只按 M2 盘点里归属 G1/G1' 的 hunk ＋本单改的这一个测试函数，用 git add -p 逐块暂存；禁止 git add -A / . / 整文件。
- git diff --cached --ignore-all-space --ignore-blank-lines 贴出来确认暂存集干净。
- 提交，message 说明"落盘 G1 分页分层＋G1' 降级清单＋收尾 G7 孤儿测试；S9522 既有欠账未动"。不 push。
- 贴回 commit 短号和 git show --stat。

【看见别的问题】只写"发现但没动"清单。
【红线】不动 stable-runs，不重跑测试音频/白宫集/日本集/女性集，不许 git checkout/restore/stash，不许 prune/删 worktree，不许 push，不许碰 ASR/模型下载/合成/全量套件，不许加回已删 G7 字段。

如果本单的判定性前提与代码不符，请驳回本单并只给差异报告。
```

### §46.36 G1'-orphan-test 回执＝情形 C，但"是不是缺陷"要看我们还要不要这条规则（2026-08-26 22:34）

GPT 定性清楚，按单停手，做得对：test_tight_clause 第一例（`person | who … wasn't just wasting wood`）
当前工作树**不再拒绝**这个切点（issue=`dependency_phrase_entrance_split`、classification=review、score=3120、进 page_starts），
第二例（`professors | who have …`）输出**一模一样**——即现在代码根本不区分这两例，两例都放行。
所以这不是删测试能掩盖的孤儿字段问题，是"拒绝甩谓语的关系从句入口"这条诉求在生产代码里已不成立（情形 C）。
Q2：契约里没有与第一例等价的现存覆盖（有几条相关但不等价）。

**但"情形 C＝必须另立生产工单修"这个结论，是我工单里预设"该诉求合法"才成立的。现在要重判这个预设：**
- 这条诉求原本由 **G7（`relative_clause_has_trailing_predicate`）** 实现，而 G7 是 2026-08-26 10:33「撤除止血」**故意删掉的**
  （见 `G1-G7撤除止血` 报告），正是用户路线图想摆脱的"给分页器不断加特例规则"那一类。
- 删 G7 后 S9513（test_high_pressure）一度红，G1' 加了**更一般的谓语完整性检查**把它修绿（r2 已证 test_high_pressure 两树皆 PASS）。
  也就是说 S9513 那条大诉求已被 G1' 承接；**test_tight_clause 卡的是 G7 独有的、更窄的一个特例**，G1' 没覆盖它。
- 第一例的切分（`…assume the person` | `who put it there wasn't just wasting wood, you know.`）是把名词头和它的关系从句＋主句谓语拆开，
  是**轻度**别扭、非灾难；且是合成测试用例，用户真实各集里没观测到此问题。

**因此这是产品取舍，不是纯技术缺陷，交用户拍板（§46.36 决策）：**
- 路线 A（放弃这条特例）：把 test_tight_clause 当 G7 撤除的收尾删掉，审计里写明"甩谓语关系从句入口的拒绝随 G7 一并放弃，
  更一般的谓语完整性由 G1' 承接"，然后 G1' 就能落盘。**符合"少加特例规则"的方向，零边界逻辑改动，零回归风险。我推荐 A。**
- 路线 B（保留这条特例）：另立生产工单，在 G1' 的完整性检查里把"关系从句入口甩掉后续谓语"也纳入拒绝——
  这是往分页边界逻辑里加规则，正是反复咬我们的高回归区，ROI 低（只为一个合成用例）。若真要做，必做基线子集判据护栏。

我推荐 A：地基探清后一步落盘 G1'，把 S9522 和"要不要这条窄特例"都记成独立欠账，不在这轮扩大边界改动。

### §46.37 用户拍板路线 A（2026-08-26 22:44）：删孤儿测试、重跑子集判据、落盘 G1'

用户用大白话确认理解后选 A（"测试是体检项，删体检项不改身体；存盘存的是你现在已在跑的东西，输出不变"）。
下面整段即工单。

```
按 §46.13 做一单，代号 G1'-landA。目标：把工作树里唯一比 HEAD 多出来的失败测试
test_tight_clause_entries_need_explicit_review_before_page_selection 整个删掉（这条特例随 G7 撤除一并放弃，
更一般的谓语完整性已由 G1' 承接），然后重跑子集判据并落盘 G1'。只动这一个测试函数，不碰任何 app/ 逻辑、不加回任何已删字段。

【开工前先回述确认（三行）】
1. HEAD 短号=（应 fdd9d83），分支=main。
2. 工作树 tests/test_article_display_readability_contract.py:2138 有 test_tight_clause_entries_need_explicit_review_before_page_selection，且该函数只在本工作树、HEAD 里没有。
3. 全仓（排除 runtime/）grep relative_clause_has_trailing_predicate：app/ 生产代码里已无此字段。
任一不成立→停止、只给差异报告。

【第一步：删测试】
删除 test_tight_clause_entries_need_explicit_review_before_page_selection 整个函数（连同其上方的空行/装饰），不动同文件其它任何函数、不改任何别的断言、不碰 app/、不加回 relative_clause_has_trailing_predicate。

【第二步：重跑子集判据（带 spaCy、跑完，允许几分钟到十几分钟；只跑这一个契约；禁 ASR/模型下载/合成/全量套件）】
工作树：runtime\python.exe scripts\run_regression.py --only article-display-readability-contract
基线 B：../vc-head-baseline 同法跑一次。
导出两份逐函数 PASS/FAIL 清单。判据：F_wt ⊆ F_base。预期两边都只剩 S9522（test_three_line_fallback）。
出现任何"基线 PASS 但工作树 FAIL"→停止、只给报告、不提交。

【第三步：提交（判据通过才做）】
- 只按 M2 盘点里归属 G1/G1' 的 hunk ＋本单这一处测试删除，用 git add -p 逐块暂存；禁止 git add -A / git add . / git add 整个文件。
- git diff --cached --ignore-all-space --ignore-blank-lines 贴出来确认暂存集只含 G1/G1' hunk ＋该测试删除，不含别的历史改动。
- 提交，message 说明"落盘 G1 分页分层＋G1' 降级清单；随 G7 撤除删甩谓语关系从句特例测试；S9522 既有欠账未动"。不 push。
- 贴回 commit 短号和 git show --stat。

【看见别的问题】只写"发现但没动"清单，不许顺手改。
【红线】不动 stable-runs，不重跑测试音频/白宫集/日本集/女性集，不许 git checkout/restore/stash，不许 prune/删 worktree，不许 push，不许碰 ASR/模型下载/合成/全量套件，不许加回已删 G7 字段，不许改本单以外的任何测试断言。

如果本单的判定性前提与代码不符，请驳回本单并只给差异报告。
```

### §46.38 G1' 已落盘（2026-08-26 23:1x）——本会话第一个真正成果

G1'-landA 回执：3 files changed / 577 insertions / 13 deletions，提交后暂存区为空，其它历史未提交改动保持原样，
未 push、未重跑音频、未合成。发现但没动：S9522 仍是两树共同的既有分页测试欠账。
（回执没带 commit 短号，下次让它附上以便对账；不阻塞。）
**状态：G1（文章分页分层）＋ G1'（降级校对清单 ＋ 随 G7 撤除删甩谓语特例测试）已进 git 历史。**
从此 HEAD 不再"只活在工作树里"，之前一串 §46.28→§46.34 的取证／误判／纠正到此收口。
剩余分页欠账只有 S9522 一条（独立票，长句三行回退的第二页起点），本会话不再碰边界逻辑。

**下一步顺序（沿用旧定，未变）**：S9522 独立票；§42.9 持久化测试（现 0；fixture 12/12 批、18 重试、9 降批、1 自证矛盾过滤、3 batch_errors）；
G4a 离线重排测量→G3→G2→G5→G4b→W6；零散欠账 D2/D4/G6。
**用户侧唯一动作**：下一集新音频照常 GUI 跑，读四个数（status / audited÷source / issue_count / batch_errors 按 code），
这是复活后翻译审计的第一次真实运行；拿到四个数前不动翻译提示词、不为取数重跑已出片集。

### §46.39 工单 A1-degrade-lastresort：单个父句无法正常分页时降级上屏＋记清单，别掐整集、别跳过审计（2026-08-27 00:xx）

**背景（复活审计第一次真跑＝被跳过）**：用户 2026-08-27 00:12 用 GUI 跑新音频「中国人形机器人，赚钱仍是难题」（256 父）。
读 artifacts 四个数：`translation-quality-audit.json` status=**SKIPPED**、audited 0/256、issue_count 0、
batch_errors 唯一码 `translation_quality_audit_skipped_page_projection_failed`。
`translation-structure-errors.json` 只一条 `display_page_blueprint_invalid`，命中父句 **S0239**
（"You know, utilizing existing factory floors to train robots rather than building these dedicated data centers from scratch. Gotcha."），
reason=`no_complete_normal_font_page_partition`。run-manifest：`display_page_translation_status=ERROR`、
`display_page_degraded_count=0`、`degraded-review-checklist.jsonl` 为 0 字节空文件。
**判读：256 父里就 S0239 一句排不出合法正常字号分页，且 blueprint 内的降级尝试
`_article_manual_degraded_render_plan(cue, bundle_errors)` 也返回 None（2..max 每个页数的
`propose_article_manual_page_word_ranges` 都 raise），于是 blueprint `raise RenderStructuralOverflowError`
→ screen_editor（~1932）兜成 status ERROR、stamp `display_page_blueprint_invalid`
→ `_run_translation_quality_audit`（subtitle_thread.py ~1073）因 artifact status≠PASS 整个 SKIPPED。
一句话掐掉整集出片＋整个审计。这一集没生成样式 ASS／视频，只有原始 SRT。**

**目标行为**：一个父句排不下，应**降级上屏并记进 `degraded-review-checklist.jsonl`（供用户人工回看）、
计入 `degraded_parents`、`display_page_translation_status` 保持 PASS、翻译审计照常运行**——
而不是整集 ERROR＋跳过审计。比例闸门此处不会误伤：阈值＝max(1, floor(256×0.02))=5，只 1 句降级，1>5 为假。

**前提核验（先跑先报数；任一 A 类不成立就驳回本单只给差异报告）**
- A1（可判定）：真 runtime＋真 spaCy 下，对 S0239 单独走 blueprint，
  `_build_article_english_page_plan` 是否返回 error bundle（status≠candidate_bundle、reason 含 `no_complete_normal_font_page_partition`）？
- A2（可判定）：同一 S0239，`_article_manual_degraded_render_plan` 是否返回 None？
- A3（可判定）：`_run_translation_quality_audit` 的跳过条件是否就是 `_display_page_translation_artifact["status"] != "PASS"`？
- N（报数即可）：source_subtitle_count=256、degraded 阈值=5、当前 degraded_count=0。
**改动白名单（只许动这些）**
- `app/core/utils/podcast_learning_video.py`：给 blueprint 降级链加**最后兜底**——当
  `_article_manual_degraded_render_plan` 对某父返回 None 时，别直接进 `errors`／`raise`，而是把该父作为
  **review_only 降级页**产出（整父单页或你判断最稳的形态），记入 `degraded_parents`，blueprint 仍返回 `status:"PASS"`。
  比例闸门 `ARTICLE_DISPLAY_DEGRADED_MAX_RATIO` 逻辑不变（超阈值仍整集 ERROR）。
- `app/core/subtitle_processor/screen_editor.py`：如降级页需正确落进 `degraded-review-checklist.jsonl`／
  `display-page-translations`，在对应记账处做**最小**配合改动即可。
- 具体兜底形态由你按代码实况定；唯一硬约束见红线。

**红线（绝对不许）**
- **不许**缩字号／50px 兜底：plan 层"fails closed 不用 50px"是对的，保留；
  `test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` 必须继续 PASS。
- **不许**加回 G7 字段 `relative_clause_has_trailing_predicate`。
- 不许 `git add -A`/`git add .`、不许 push、不许 commit（本单只到验证＋清单，提交留下一单）。
- 不许跑 ASR／下载模型／合成视频／整套 `run_regression` 全量。

**发现但没动清单**：列出为此改动读到、但本单不处理的相邻问题（如 fallback_review 单页在 ~8552 被从 parents 丢弃是否另有坑）。

**不改现有断言**：不得改任何现存测试断言来"配合"通过；新行为要测就另加新测试。

**验证方式（禁全量禁 ASR）**
1. 子集判据（黄金环境）：工作树与 ../vc-head-baseline 各跑一次
   `runtime\python.exe scripts\run_regression.py --only article-display-readability-contract`，
   两份逐函数清单做差集，判据 **F_wt ⊆ F_base（只减红不增红）**。允许耗时数分钟（spaCy 反复加载），别因慢判失败。
2. 定点复算（禁重跑音频）：用**本集已有 checkpoint**离线重建 blueprint，证明
   **S0239 进 `degraded_parents`、`display_page_translation_status`=PASS、
   `degraded-review-checklist.jsonl` 出现 S0239 一行、`translation-quality-audit.json` status 不再 SKIPPED（跑出真实四个数）。**

**先数字后结论**：报告开头先摆 A1–A3 核验结果（跟数字／行号）＋两项验证数字，再写结论。

**做完停下**：验证＋清单给完即停，不 commit／push／add、不删基线副本。
报告写 `docs/handoffs/A1-degrade-lastresort-20260827.md`。

**如果本单的判定性前提与代码不符，请驳回本单并只给差异报告。**

### §46.40 工单 P1-page-rebreak：按中文标点把"塞挤/断错"的上屏页只拆不并地重断，逐父封闭、文本不变、排版护栏兜底（2026-08-27）

**背景（从用户人工终稿提炼的通用规律）**：用户手动终稿包 `20260827T054046460067-b90f9792` 的 `edits.json` 是权威记录。
逐条比对"他动之前(before_parent_states)"与"终稿(display_page_edits)"后，抛开 5 处 ASR 英文改动，他绝大多数手工是同一件事：
**机器把中文照英文的词范围切页，中文语法不在同一处断，于是页尾落在半句/破折号上、或把两句(甚至一句超长)挤进一页；他重新断页，让每页是一个能独立读完、以自然停顿(。？！：；，、)收尾的完整小句。**
关键：这类重断**只重分配该父句自己已定稿的中文**，中文串接一字不变，不跨父句、不改时间轴——血缘半径为 0，天生不会连累别的字幕。
用户已明确要的自动化范围：**只做"拆"（一档句末标点内切 + 二档最高级逗号切超长/挤句页），不做"并"**——因为拆只会让页更短、必然排得下；并会让页变长、可能重新触发 §46.39 那个 `no_complete_normal_font_page_partition`。

**这一集(中国人形机器人)的纯重分页铁证＝比对基准(ground truth)**：以下 6 个父，他只挪了页边界、中文文本串接完全不变（我已离线校验 `concat(zh) 前后一致=True`）。
括号内是人工在英文词序号上选的切点：

| 父 | 机器页(word范围) | 人工终稿页(word范围) | 人工切点＝中文落点 | 档 |
|---|---|---|---|---|
| S0208 | [2136-2140][2141-2154] | [2136-2140][2141-2152][2153-2154] | 2152\|2153＝"…迁移到机器上。"后 | 一档(句末。) |
| S0102 | [1027-1038][1039-1058] | [1027-1038][1039-1044][1045-1058] | 1044\|1045＝"就有一间模拟药房，"后 | 二档(，) |
| S0132 | [1341-1361] | [1341-1356][1357-1361] | 1356\|1357＝"…细微磨损，"后 | 二档(，) |
| S0212 | [2194-2208] | [2194-2204][2205-2208] | 2204\|2205＝"…金属执行器、"后 | 二档(、) |
| S0244 | [2548-2568] | [2548-2557][2558-2568] | 2557\|2558＝"…巨大实体规模，"后 | 二档(，) |
| S0187 | [1891-1905][1906-1914] | [1891-1898][1899-1914] | 1898\|1899＝"…2026年上半年，"后(并把"高达70%"下移与后句同页) | 二档(，)＋再平衡 |

（S0187 是最难的一例：机器 P1 尾巴吊着无标点的"…高达70%"，人工把切点移到更靠前的逗号、让"高达70%"跟下句同页。自动规则不一定复现这一手，允许它与人工不同，只要仍满足下方所有不变式。）

**目标行为**：在机器决定完各父的上屏页之后，加一道**逐父的"只拆不并"重断后处理**：
- 一档（近零误判）：若某页投影出的中文里出现句末标点 `。？！` 却不在页尾＝两句挤一页 → 在该标点对应的英文词边界处把这页拆开，使每段以句末标点收尾。
- 二档（要护栏）：若某页中文明显偏长或页尾是无标点的半句 → 在该页内**最高优先级**的中文停顿（优先 `：；`，其次 `，、`）对应的英文词边界处拆开。
- 拆出的每一子页都必须过机器**原有的**正常字号排版/宽度契约；**任一子页排不下 → 这个父整体退回机器原始分法**（记入 fallback 名单，不报错、不缩字号）。
- 全程**不改任何中文字符、不并页、不跨父、不改父的总时间轴**（子页时间＝父范围内的顺序切分，无缝无叠）。

**前提核验（先跑先报数；任一 A 类不成立就驳回本单只给差异报告）**
- A1（可判定）：每父的上屏页中文(zh)确由"机器先定英文词范围、再把中文投影到各页"产生，且存在"一页 zh 内含非页尾 `。？！`"的真实实例（本集候选 S0208 等）。请报命中的父/页清单。
- A2（可判定）：是否存在"英文词边界 ↔ 中文字符位置"的对齐信息，能把一个中文标点落点映射回英文词序号以决定拆点？若无此对齐、需对新子范围重投影中文，请说明并据此判可行性（不可行就驳回）。
- A3（可判定）：机器原有的单页排版/宽度契约（即产出 `no_complete_normal_font_page_partition` 的那套判定）能否被单独调用来校验一个候选子页是否排得下？
- N（报数即可）：本集 6 个基准父的机器页数与人工页数（见上表）；`ARTICLE_DISPLAY_DEGRADED_MAX_RATIO=0.02` 逻辑本单不动。

**改动白名单（只许动这些）**
- `app/core/utils/podcast_learning_video.py`：在 blueprint 产页后加"只拆不并重断"后处理＋每子页排版校验＋排不下退回原分法；具体实现形态由你按代码实况定。
- `app/core/subtitle_processor/screen_editor.py`：如重断后的页需正确落进 `display-page-translations`／映射产物，做**最小**配合改动。
- 需要就新增测试；不得改任何现存断言来配合通过。

**红线（绝对不许）**
- **只拆不并**：本单不实现任何合并/上移半截页的自动化（那是另一单，因为会让页变长可能排不下）。
- **不改中文文本**：重断前后每父 `concat(各页zh)` 必须逐字符相等。
- **不跨父、不改时间轴**：父集合、每父的 `word_start..word_end` 总包络、总时间范围前后不变。
- **不缩字号／不 50px 兜底**：`test_no_safe_normal_font_partition_fails_closed_instead_of_using_50px` 必须继续 PASS；排不下就退回原分法，绝不靠缩字号硬塞。
- **不许**加回 G7 字段；不许 `git add -A`/`git add .`、不许 push、不许 commit（本单只到验证＋比对）；不许跑 ASR／下模型／合成视频／全量 `run_regression`。

**发现但没动清单**：列出为此改动读到、但本单不处理的相邻问题（如二档在多个逗号间如何选优、S0187 那类需要"再平衡"的情形）。

**验证方式（禁全量禁 ASR；这一段就是用户要的"做好验证＋让你能比对"）**
1. **无回归子集判据（黄金环境）**：工作树与 `../vc-head-baseline` 各跑一次
   `runtime\python.exe scripts\run_regression.py --only article-display-readability-contract`，逐函数清单做差集，判据 **F_wt ⊆ F_base（只减红不增红）**。允许耗时数分钟，别因慢判失败。
2. **本集离线全量不变式（禁重跑音频，用已有 checkpoint/artifacts 离线重建后处理）**，对全 256 父逐父断言并报计数：
   (a) 文本不变：∀父 `concat(new zh)==concat(old zh)` 逐字符；违反数必须=0。
   (b) 只拆不并：∀父 `new页数 ≥ old页数`；父集合不变；每父 `word` 总包络不变；违反数=0。
   (c) 时间轴：每父子页时间是其原范围的有序无缝切分；违反数=0。
   (d) 一档达成：原来"含非页尾 `。？！`"的页，重断后不再有任何页在页中残留句末标点；报残留数（目标 0）。
   (e) 排版护栏：每个新子页过原排版契约；报"排不下→退回原分法"的父数（fallback 名单）。
3. **对比人工终稿基准（比对，核心）**：对上表 6 个基准父，把**自动重断的切点**与**人工切点**逐父比对，报：
   - 完全一致的父数/6（切点英文词边界完全相同）；
   - 不一致的父，列出自动切点 vs 人工切点，并说明是否仍满足 2(a)-(e)（即"虽与人工不同但合法可读"）。
   这组数字就是这条规律的真实精度证据；S0187 允许不一致。

**先数字后结论**：报告开头先摆 A1–A3 核验（跟数字/行号）＋验证 1、2(a)-(e) 的计数＋验证 3 的"命中数/6"，再写结论。

**做完停下**：验证＋比对给完即停，不 commit／push／add、不删基线副本。
报告写 `docs/handoffs/P1-page-rebreak-20260827.md`。

**如果本单的判定性前提与代码不符（尤其 A2 对齐信息不存在），请驳回本单并只给差异报告。**

### §46.41 工单 T1-display-timing-lead：字幕出现时机——只把停顿串接线 1000→1500ms（消掉停顿后的空屏）；全局早量 40ms、提前量上限 200ms 维持不变（对齐 Netflix「贴音频第一帧、容差 1-2 帧」标准）（2026-08-27）

**背景（用户看合成视频定点反馈）**：本集"中国人形机器人"合成视频约 3:50 处，"没错，随着杯子装满…你手中的重心也在不断变化。"(S0069) 结束后，说话人停顿约 1.08 秒，下一句"聊天机器人可以读一千万次…"(S0070) 的字幕只比人声早 40ms 才出现，观感是等了近 1 秒空屏、字幕迟到才冒出来。用户已同意用调时间参数的方式改善（他本来就想要字幕适度提前出现）。
**定位**：`final_cue_timeline.py` 的短空档串接 `_chain_short_display_gaps` 只处理 `word_gap < SHORT_GAP_CHAIN_THRESHOLD_MS(=1000)` 的空档；此处 word_gap=1081ms（S0069 末词 `up.` end=230414 → S0070 首词 `So,` start=231495），1081≥1000 未被串接，于是后句只享全局 lead_in=40ms，前一句 230674 就消失、后一句 231455 才出，中间 781ms 空屏。

**前提核验（先跑先报数；任一 A 类不成立就驳回本单只给差异报告）**
- A1（可判定）：`final_cue_timeline.py` 顶部常量 `DISPLAY_LEAD_IN_MS=40`、`DISPLAY_TAIL_PADDING_MS=260`、`SHORT_GAP_CHAIN_THRESHOLD_MS=1000`、`MAX_CHAINED_NEXT_LEAD_MS=200`（约第 20-25 行）。请核实并报行号。
- A2（可判定）：`_chain_short_display_gaps`（约第 609-669 行）只在 `word_gap>0 且 word_gap<threshold_ms` 时把左右两句共享一个边界（`left.end=right.start=boundary`），`boundary=min(old_right_start, max(lower_bound, left_word_end+word_gap*3//4))`，后句提前量=`right_word_start-boundary`，受 `max_next_lead_ms` 上限约束。请核实。
- A3（可判定，关键）：production 路径 `screen_editor.py`(约 8606-8611) 与 `manual_final_subtitle_editor.py`(约 9333-9345) 调 `derive_final_cue_timeline` 时，`lead_in_ms` 传的是常量 `DISPLAY_LEAD_IN_MS`、`tail_padding_ms` 传 `DISPLAY_TAIL_PADDING_MS`；而 `SHORT_GAP_CHAIN_THRESHOLD_MS`/`MAX_CHAINED_NEXT_LEAD_MS` 是在 `derive_final_cue_timeline` 内部（约第 186-187 行）直接读常量。即**改这四个常量即可全局生效，无需改调用点**。请核实并报行号；若并非唯一入口（别处硬编码了 40/1000/200），驳回。
- N（报数即可）：拿本集现成 checkpoint（`work-dir/中国人形机器人.../stable-runs/20260827T041727...-artifacts`）离线重算，报改前 S0069→S0070 的 word_gap、display 空档、后句提前量。本单不重跑音频。

**改动（改动白名单：只许改 `final_cue_timeline.py` 这一个常量 ＋ `tests/test_final_cue_timeline.py` 一条钉死旧值的测试）**
1. `SHORT_GAP_CHAIN_THRESHOLD_MS`：1000 → 1500（≤1.5 秒的停顿也让前句延后收尾、后句略提前，消掉空屏）。

**刻意不改（对齐成熟方案，见 §46.41 附注）**：
- `DISPLAY_LEAD_IN_MS` 维持 **40**——Netflix Timed Text 规定字幕入点应贴在音频第一帧、容差仅 1-2 帧（≈40-80ms），40ms≈1 帧已是教科书值；全局提到 150ms（≈3-4 帧）反而超标。3:50 的问题不是"全局出太晚"，而是停顿造成的空屏。
- `MAX_CHAINED_NEXT_LEAD_MS` 维持 **200**——停顿里后句最多早 0.2 秒足够，不必到 0.4 秒。3:50 的修复主要来自"前句延后收尾填掉空屏"，不是把后句大幅提前。
- `DISPLAY_TAIL_PADDING_MS`、`TARGET_DISPLAY_DURATION_MS`、`HARD_MIN_DISPLAY_DURATION_MS` 一律不动。
（可选：若用户要全片都略早出，可把 `DISPLAY_LEAD_IN_MS` 提到 **80**（仍在 Netflix 1-2 帧容差内），但非本单默认，需用户另行点名。）

**预期会变红、必须相应更新（本单唯一允许改的测试断言；这是"规则变了"不是"改坏了"，别硬让它变绿）**
- `test_one_second_parent_pause_is_not_chained`（约 148-170 行）：其 words=(1000,2000),(3000,3800)、word_gap=1000，旧线 1000 时"不串接"；新线 1500 下 1000<1500 会被串接，断言必然翻。请改成断言"≥1500 的停顿不串接"（例如把第二词起点从 3000 挪到 ≥3500 再断言不串接），并另加/改一条正面用例断言"1000ms 这类停顿现在会被串接"。
- **应仍 PASS、不要动**：`test_short_parent_gap_caps_the_next_cue_lead_in`（129-146，cap 未改故仍=2760/200）、`test_short_parent_gap_is_chained_at_the_original_three_quarter_boundary`（104-127，word_gap=740 仍=2555/185）。lead_in 未改；`test_stable_caption_rules.py:3624` 用符号引用也不受影响。请核实除上面那一条外没有别的断言被波及。

**红线（绝对不许）**
- 不碰分页/翻译/allocation/审计/字号；不动 `DISPLAY_TAIL_PADDING_MS`/`DISPLAY_LEAD_IN_MS`/`MAX_CHAINED_NEXT_LEAD_MS`；全单只改 `SHORT_GAP_CHAIN_THRESHOLD_MS` 一个数 ＋ 上述一条测试断言。
- 不许 `git add -A`/`git add .`、不许 push、不许 commit（本单只到验证＋离线比对）；不许跑 ASR／下模型／合成视频／全量 `run_regression`。
- 不得为让别的测试变绿去改与本单无关的断言；若出现 `test_one_second_parent_pause_is_not_chained` 之外的测试变红，**停手报差异**（说明前提 A 判错了）。

**§46.41 附注（成熟方案的补偿量，2026-08-27 web 核实）**：Netflix Timed Text Style Guide（Subtitle Timing Guidelines）明确要求字幕入点落在**音频第一帧、容差仅 1-2 帧**（24fps≈42-83ms、25fps=40-80ms、30fps≈33-67ms），且是"贴住"而非"提前"。BBC/EBU-TT 同样以贴合语音为准。故本项目现值 `DISPLAY_LEAD_IN_MS=40`（≈1 帧）本就合标准，150ms（3-4 帧）偏大、不采纳。真正要治的 3:50 是**停顿空屏**，用串接线（前句延后收尾填空屏）解决，与全局早量无关。

**发现但没动清单**：列出为此改动读到、但本单不处理的相邻问题（如 `_extend_short_display_ranges` 是否也该跟着调、tail padding 要不要一起动）。

**验证方式（禁全量禁 ASR）**
1. **无回归子集判据（黄金环境）**：更新那两条测试后，工作树与 `../vc-head-baseline` 各跑一次
   `runtime\python.exe scripts\run_regression.py --only final-cue-timeline`（或覆盖 `test_final_cue_timeline` 的实际 `--only` 名，按代码取）。判据：**除本单明确声明更新的两条测试外，工作树不得出现任何新红**；更新后的两条应为绿。允许耗时数分钟，别因慢判失败。
2. **本集离线全量不变式（禁重跑音频，用现有 artifacts 把 records 以新常量离线重算）**，对全 256 cue 断言并报计数：
   (a) 本单只动 `start_ms`/`end_ms`：∀cue 的 `word_start`/`word_end`/`zh`/父集合/`word_envelope` 前后不变——违反数=0。
   (b) 无 `start_ms<0`、无 `start_ms≥end_ms`；违反数=0。
   (c) 无新的显示区间重叠（相邻 `end≤next.start`，或经 overlap resolver 后仍单调不叠）；违反数=0。
   (d) 每 cue 提前量=`word_envelope_start-start_ms`，报分布（min/median/max）：确认连续段约 40ms、停顿后 ≤200ms，无异常大值。
3. **定点对比（核心，就是用户问的 3:50）**：报 S0069→S0070 改前/改后的：左句 display end、右句 display start、两句之间 display 空档、右句提前量。目标：空档从 781ms 大幅收窄（左句延后收尾＋右句提前），右句提前量落在 200-400ms。并报全集"改后仍 >500ms 的 display 空档"清单及其 word_gap，供用户眼看别处有没有被带坏。

**先数字后结论**：报告开头先摆 A1-A3 核验（跟行号）＋验证 1 的差集 ＋ 验证 2(a)-(d) 计数 ＋ 验证 3 的定点数，再写结论。
**做完停下**：验证＋离线比对给完即停，不 commit／push／add、不删基线副本。报告写 `docs/handoffs/T1-display-timing-20260827.md`。

**如果本单的判定性前提与代码不符（尤其 A3：`SHORT_GAP_CHAIN_THRESHOLD_MS` 并非全局唯一入口、别处另有硬编码 1000），请驳回本单并只给差异报告。**

### §46.42 工单 ROI-number-anchor：数字锚点分页错位测量（只读·离线·零 API，用来决定要不要建完整五类语义锚点审计）（2026-08-27）

背景：GPT 于 09:29 提出"语义锚点分页审计（否定/数字/实体/条件/关键动作五类，只读低风险版）"。方向对，但别一次建五类。先用最硬的一类"数字"在已成功 run 上离线测真实命中/误报，用数据决定 ROI。数字最硬：阿拉伯数字中英文写法一致、几乎不误判，且数字放错页后果最严重。GPT 原单硬伤：拿供应链这集的 S0260 当正例——但该集 `display_page_translation_status=ERROR`、全篇 `parents[].pages[].zh` 全空（不是只有 S0260 两页空，是全 325 页 zh 皆 null，因为页翻译阶段是全有或全无：只要 S0136/S0260 校验没过，整段中止、所有页 zh 都不落盘），锚点脚本在该集只会满屏 uncertain。正例须用合成样例，且必须在 PASS run 上测。

一、前提（不成立就驳回、只回差异报告）
A1. PASS run 的 `display-page-translations.json`：逐页中文在 `parents[].pages[].zh`、逐页英文在 `parents[].pages[].english`、页序 `page_index`，多页父句在顶层 `parents[]`（已核：机器人 `stable-runs/20260827T041727` 结构成立，S0001 P01 zh="8月17日，"／P02 zh="一台名为…"）。ERROR run 的 `parents/zh` 为空、不可用。
A2. 英文页数字与对应 zh 数字为同一阿拉伯写法（August 17th→8月17日、460%→460%）；中文写成"十万/一半/三分之一"是已知盲区、归 missing/uncertain、不算误报。
A3. 选用 run 均 `status=PASS` 且 `parents[].pages[].zh` 全非空。

二、不做：只读；不改任何 checkpoint／字幕／分页／时间轴／ID、不写回任何 run 目录；不调模型／网络／API；只测数字一类（否定/实体/条件/动作留待 ROI 过后正式工单）；不设 BLOCKER；不动现有测试断言；人工终稿与 stable-runs 只读不写。

三、输入：GPT 自选 ≥3 个不同选题的 PASS run。建议：机器人 `stable-runs/20260827T041727`、白宫 `stable-runs/20260825T225507`、石油 `stable-runs/20260817T022205`。

四、测量逻辑（数字锚点）：对每个多页父句，从每页 english、每页 zh 各抽数字 token（整数／千分位逗号／小数／百分号／年份／序数 17th），归一化去逗号、统一百分号（"100,000"=="100000"、"460%"=="460%"）；对该父句每个归一化数字比较英文出现页集 en_pages 与中文出现页集 zh_pages：都单页且不同→REVIEW（数字错位）；英文有、中文全无该数字→missing（软信号、低）；出现多页或拿不准→uncertain 不报。失败安全：任何拿不准一律进 uncertain。

五、输出（写 `output/`、不写回任何 run）：每 run 一份 `measure_page_number_anchors_<run>.json`（字段：multi_page_parents／numbers_checked／review_count／missing_count／uncertain_count／items[{parent_id,number,en_pages,zh_pages,bucket,sample_en,sample_zh}]）＋一份跨 run 汇总。

六、验收：零网络／模型／API，每 run 跑完 <1 分钟；所有现有文件／checkpoint 字节不变、现有测试不改断言且不因本脚本变红；≥2 条合成单测（①数字故意落到错误 zh 页的父句→必报 REVIEW；②中文调序但数字仍在正确页→必不报）；报真实 REVIEW／missing／uncertain 数，并由 GPT 人眼核每条 REVIEW 是真错位还是噪音、报真错位数 vs 噪音数；不先编总体自动化成功率。

七、判定门：≥3 集里数字锚点报出 ≥1 条真错位、且误报可控→放行去建完整五类审计（带三修正：只在 PASS run 上测、S0260 正例用合成样例、每类分别报误报率）；几集下来真错位≈0→搁置（数字都不出问题，更软的否定/实体大概率不值那份误报成本）。

**如果本单的判定性前提（尤其 A1 逐页中文字段 `parents[].pages[].zh`、A2 数字同写法）与产物不符，请驳回本单并只给差异报告。**

---

## §46.43 ROI-number-anchor 回执核验（Claude，2026-08-27）——同意搁置五类，但记两条诚实保留

GPT 报告 `docs/handoffs/ROI-number-anchor-20260827.md`：4 集 PASS run、131 多页父、278 页、7 个英文阿拉伯数字、**0 REVIEW（无跨页错位）**、7 missing（全人核为可解释的数字表达差异：10 million→一千万/1000万、100 million→一亿、303/40/330 billion→3030/400/3300亿美元、24 months→每两年）、0 uncertain、合成单测 2/2、零 API/网络/checkpoint 改动。

**Claude 独立复算（机器人 20260827T041727，只读）复现 GPT 结果**：多页父 43（与报告一致）、REVIEW 0、missing 3＝S0121/S0172/S0205（与报告同一批）。GPT 核心结论可复现，执行干净、零副作用，判定门命中"真错位≈0→搁置"分支。**同意搁置完整五类语义锚点审计。**

**但两条诚实保留（供用户判断是否值得再补一探，不改搁置结论）：**
1. **数字锚点在本类内容里"半盲"**：英文 large round number 写 `10 million`（数字 10），中文写"一千万/1000万"——数字字面不对应，脚本根本定位不到中文数字，只能记 missing。所以 "0 REVIEW" 是"在能比对的少数里没发现错位"，不是"证明分页无错位"。这反而更说明数字不是好锚点。
2. **真正的动机缺陷（S0260）是否定错位，不是数字**："最终在哪组装并不重要"那类。本次数字探针根本没测否定这一类。用数字≈0 推断否定也≈0，是弱外推。

**可选下一步（等用户拍板，倾向直接收）：**
- (a) 直接收：判定门是数字锚点，门已给出搁置，照门收，翻译质量/ASR 那边去投精力。
- (b) 再补一探否定锚点：否定是闭集（不/没/无/非/未 vs not/no/never/n't/cannot），同样只读离线、失败安全进 uncertain，能真正测到 S0260 那类症状，再决定是否彻底放弃这条线。成本约等于本次数字探针。

**独立于本线的今日阻断仍压着**：供应链集"中国企业正把供应链铺满全球" S0136/S0260 逐页翻译失败（`display_page_translation_invalid`）→整集 zh 全 null→审计 SKIPPED，先重跑，复发再下降级兜底工单（与 A1 平行）。ROI 这条线不解决它。

---

## §46.44 核心流程打磨清单（Claude 复核当前基线后，2026-08-27）

**先核实的基线现状（以 git 为准，纠正我此前过时说法）：**
- T1 已提交（f0a819f，SHORT_GAP_CHAIN_THRESHOLD_MS=1500 已在 HEAD），lead_in 40ms 合 Netflix 帧级标准。时间轴层面无欠账，只欠用户重合成机器人集人眼验 3:50。
- A1 兜底及大量修复已入库（eb2f607..HEAD 二十余笔：a9bcd81 页翻译契约收紧、42c6598 语气词保留、5522275 审计走所选 LLM、52a8ebc 冻结父检查点续跑、871ebf6/9b4f7d6 手工终稿包链路两笔修复等）。工作树现在基本干净：真实未提交改动只剩 screen_editor.py 13 行。
- 那 13 行未提交改动＝**混合批打捞**：批次校验失败不再整批丢弃（删掉 status!=PASS 早退），改为逐父单独校验、好句入库，重试不再重复已成功的请求。这正对着供应链集 S0136/S0260"两句坏→整集 325 页 zh 全 null"的病根。

**质量基数（机器人集 304 页实测，见 §46.43 前后）**：中文 cps 中位 4.7/上限 9 内、超线仅 4 页；英文跟语速走；<1s 闪页 33 页；分页切点 86.7% 落标点、约一成页断错（人工终稿 30 次分页修改的来源）。观众侧对市面规范约 7.5 分。

**打磨清单（不含 ASR、不含单词卡，按优先序）：**
1. **收尾混合批打捞（最高优先）**：给 GPT 下验证单——子集判据零新红＋用供应链集 checkpoint 离线重放，证明坏句(S0136/S0260)不再拖垮整集；并确认坏句自身去向（进 degraded＋清单，而非仍 ERROR）。过了就提交。这一步把"崩谁降谁、整集照出"补齐。
2. **供应链集重跑出片**（在 1 之上），顺带拿该集审计四个数。
3. **机器人集重合成**，人眼验 3:50 空屏是否收窄（代码已入库，纯眼看）。
4. **闪页治理（量完再立单）**：离线量 33 页<1s 里多少低于 0.83s 规范线、是否集中在"没错。/嗯。"应答页；两个候选修法（页内向邻页借时长 vs 应答短页并入邻页）按测量结果二选一。低风险、观众可感。
5. **句号档分页重断拍板**：方案已成型（内部句末标点拆＋应答词豁免名单＋英中句末数相等 fail-closed 16/16＋每子页过排版契约），零改字零风险，但只收回约 1/7 手工拆页。上＝免费小赢；逗号档没有词级对齐、天花板 69%，明确放弃自动、继续人工。
6. **手工终稿包→合成链路补持久回归**：连续两笔修复（871ebf6 删页后对账、9b4f7d6 载入终稿包后恢复合成）说明这条他每集必经的链路脆；连带 §42.9 审计解析持久测试仍为 0 的旧账，一并补。
7. **保持提交卫生**：现在一修一提的节奏很好，别退回 44 文件大杂烩状态。

预期：1+4+5 落地后观众侧约 7.5→8.5；6 落地后减少"每集第一跑必踩新坑"的概率。1-3 是本周的事，4-6 各自 measure-first，7 是习惯。

---

## §46.45 工单 S1-page-translation-lastresort：页翻译无效父的最后兜底 ＋ 打捞改动收编（按 §46.13 八条执行）

**开工前回述三行确认**：本单只做"页翻译校验失败的父级降级兜底"一件事；打捞改动收编进本单一并验证；别的发现只记清单不动手。

**一、判定性前提（不成立就驳回）：**
A1. 工作树 `screen_editor.py` 约 2359 行：重试耗尽后 `artifact.status != "PASS"` → 整段置 ERROR 并 raise，**没有降级出口**（Claude 已核工作树代码，行号可能漂移，以语义为准）。
A2. 工作树存在未提交的约 13 行打捞改动（`_store_display_page_translation_units` 删除 status!=PASS 早退、逐父单独校验入库；约 3315 行注释"Store only the valid parent units…"）。
A3. 供应链集 checkpoint 可离线重放：S0136 `page_translation_id_missing`、S0260 `display_page_semantic_validation_failed`，整集 325 页 zh 全 null、审计 SKIPPED。
A4. A1-degrade-lastresort 的降级记账机制（degraded_parents＋清单＋`ARTICLE_DISPLAY_DEGRADED_MAX_RATIO=0.02` 比率闸门）已在库中可复用。

**二、改动文件白名单**：`app/core/subtitle_processor/screen_editor.py`（含收编那 13 行）；如需复用降级记账，`app/core/utils/podcast_learning_video.py` 最小配合。超出白名单的问题一律记"发现但没动"清单。

**三、做什么：**
1. 先验证打捞改动本身（子集判据）。
2. 加最后兜底：某父重试耗尽仍校验失败 → 走**确定性退路**（优先复用现有确定性切分/降级路径，例如该父整句中文落单页的 review_only 降级页，具体机制 GPT 按现有 A1 模式选最小实现），记 degraded_parents＋写入降级清单＋计入 2% 比率闸门；比率内则整段 status=PASS、审计照跑；超比率仍整集 ERROR（闸门语义不变）。
3. 供应链集 checkpoint 离线重放证明：S0136/S0260 进 degraded（degraded_count=2、清单 2 行）、其余父的 pages[].zh 非 null、`display_page_translation_status=PASS`、翻译审计不再 SKIPPED（离线假响应证管路即可，不调真模型）。

**四、不许做**：不改现有测试断言；不动 stable-runs/人工终稿；不缩字号；不调 API/模型/ASR/合成；不跑全量回归（子集判据＋定点单测，超一分钟就是跑错了）；不 git checkout/restore/stash；**不 commit**（验证通过后等用户点头，届时连同这 13 行按 hunk 提交）。

**五、验证方式**：子集判据 F_wt⊆F_base 零新红；≥2 条合成单测（①一个父校验失败其余正常→该父 degraded、整段 PASS、其余父 zh 完整；②失败父占比超 2%→整段 ERROR 仍生效）；三给出供应链重放的真实数字（degraded 数/非空 zh 页数/审计 audited 数）。

**六、先给数字再给结论；七、做完停下。**

**八、红线同 §46.13。如果本单的判定性前提（尤其 A1"重试耗尽无降级出口"、A4 降级记账可复用）与代码不符，请驳回本单并只给差异报告。**

---

### §46.45.1 闪页实测定论（Claude，测完即结论，暂不立单）

机器人集 33 页<1s 实测：24 页低于 0.833s 规范线，构成几乎全是应答插话（Right./Yeah./Mm-hmm./Okay. 等，15 页单词、5 页两词），它们本就是独立父句；一批正好停在 0.70s＝已被 `TARGET_DISPLAY_DURATION_MS=700` 拉满，更短的（0.24-0.66s）是被下一句顶住、无空可借。结论：这是听觉冗余的应答词，观众靠耳朵不靠读，实际损失小。**唯一低价工单候选**＝把 TARGET 700→850（与 T1 同型的单常量改动，只影响有空档的页，被顶住的页不动、不会重叠）；不做"删/并应答页"——那是真实对话，42c6598 刚特意保留语气词，别左手删右手。等用户要做再立单。

---

## §46.46 工单 F1-alignment-probe：翻译时输出中英对照表的可行性探针（只测不改管线，按 §46.13 八条执行）

**背景一句话**：分页切中文老出错、逐页中文校验老崩，共同根因是管线里不存在"英文词段↔中文短语"对照表。设想的架构解法是让模型交出这张表、下游照表确定性切页。本单先花小钱验证最大的不确定点：**模型能否稳定交出合格的对照表**。测完给数字，不改任何管线代码。

**开工前回述三行确认**：本单只做离线探针脚本＋小规模真实模型调用＋报告；不改 app/ 下任何文件；别的发现只记"发现但没动"清单。

**一、判定性前提（不成立就驳回）：**
A1. PASS run 里每个多页父句可取到：整句英文、整句已定稿中文（authoritative-parent-chinese.json）、现行每页英文词范围与每页 zh（display-page-translations.json parents[].pages[]）。
A2. 翻译所用的 LLM 服务可在管线外单独小批量调用（走现有服务配置即可）。
A3. 机器人集人工终稿包（桌面 generations 目录）里有用户手改分页的改前/改后记录，可当 ground truth（§46.40 已内嵌 6 父切点表可直接用）。

**二、改动文件白名单**：仅新增 `scripts/probe_alignment_emission.py` ＋ `tests/test_probe_alignment_emission.py`；输出写 `output/f1-alignment-probe/`。**app/ 一个字不许动。**

**三、探针设计：**
1. 样本：≥30 个多页父句，跨 ≥2 集 PASS run；必须包含难例——机器人集用户手改过分页的 S0100/S0102/S0104/S0167/S0176/S0208，＋供应链集当时切崩的 S0136/S0260（父级中文是好的，可用）。
2. 任务设计（关键：**不重翻**）：给模型整句英文＋**已定稿的整句中文**，只让它做对齐——把中文按短语切开，每个中文短语标注对应的英文词区间（词序号），输出 JSON。译文本身一个字不许生成、不许改。
3. 确定性校验（硬门）：①所有中文短语按序拼接必须与原中文**逐字相等**；②每个英文区间必须落在句内、区间允许中英语序不同但不许超界；③JSON 结构合法。任一不过＝该父不合规（允许重试 1 次）。
4. 模拟切页：用现行每页英文词范围，把每个中文短语归到其英文区间（多数词）所在的页，得到"照表切"的每页中文；与 ①现行机器版每页 zh、②用户手改终稿版（6 父 ground truth）三方对比。
5. 成本上限：总请求 ≤70 次（30-35 父 × 最多 1 重试），用便宜档模型（与现行页翻译同档），报告里给出实际调用数与 token 花费。

**四、报数字（先数字后结论）**：合规率（硬门通过父数/总数）；重试后合规率；拼接逐字相等率；6 个 ground-truth 父上"照表切"命中用户切法的数目 vs 现行机器版命中数；S0136/S0260 这两个老崩点是否合规；失败父的失败模式分类。

**五、判定门**：合规率 ≥90% **且** ground-truth 命中数 ≥ 现行机器版 → 放行下一单（增量实现：翻译新增对齐字段、拼接校验、不合规自动退回现行两步法，v8 译文零风险）；合规率 <90% 或照表切反而更差 → 搁置，只留失败模式报告。

**六、不许做**：不改 app/、不改现有测试断言、不动 stable-runs/人工终稿（只读）、不写 checkpoint、不跑全量回归、不 commit；探针脚本本身要带 ≥1 条离线合成单测（伪造模型响应过/不过硬门各一例）。

**七、做完停下，报告写 `docs/handoffs/F1-alignment-probe-<日期>.md`。**

**八、如果本单的判定性前提（尤其 A1 数据可取、A3 终稿包可读）与实际不符，请驳回本单并只给差异报告。**

## §46.47 工单 P1-whole-sentence-chinese-prototype：多页父级整句中文显示原型（只做本集样片，按 §46.13 八条执行）

**背景（Claude 只读测量，用户已批准做原型）**：当前多页父级的每页中文由"分页再翻译"那一步产生，把整句中文切碎去凑英文每页边界，导致上屏中文半截别扭；且该步是全有或全无，任一父校验失败→整集 zh 变空停产（S0136/S0260 老崩点）。用户"站起来办公"终稿实测：220 句里 199 句字词未改，38 次手改中文＋10 次拆页绝大多数只是"重新决定在哪断页"。设想：多页父级不再切，直接整句显示父级权威中文，英文照旧逐页翻。本单只在这一集做可看样片供用户肉眼判"连贯性"，不改管线、不落地。

**一、开工前先回述三行等确认**：本单只做什么、白名单、验证方式，回述我确认后再动手。

**二、改动文件白名单**：只允许新增一个独立原型脚本（如 `scripts/proto_whole_sentence_zh.py`）＋其产物；**不改 app/ 任何现有渲染/翻译代码**，用旁路开关，不动现有管线。

**三、判定性前提（A 类，先核验，任一不成立即驳回）**：
A1 多页父级每页 zh 来自 display-page-translation 步，单页父级用 authoritative-parent-chinese；render_plans[].pages 有英文＋时间、无中文。
A2 authoritative-parent-chinese[父].chinese 是完整通顺整句；本集 23 个多页父，其页 zh 拼接≈该整句（Claude 测：全集 199/220 字词一致）。
A3 显示层中文对多页父取自每页 zh；改成取父级整句是纯显示改动，不影响英文分页、cue 时间轴、合成、隐藏中文版。

**四、做什么（只这一集）**：读现有机器版产物（stable-runs/20260828T032249…，只读），对每个多页父，把父级权威整句中文作为一块，在该父第一页 start_ms 到末页 end_ms 期间恒定显示；英文页/时间/字号一律不动。产出可看样片（渲染帧或字幕文件皆可，能让用户肉眼判读即可）。单页父完全不动。

**五、报数字（先数字后结论）**：①本集多页父数、整句中文渲染后各占几行、行宽是否溢出（列出溢出的父）；②英文每页文本与时间是否与原产物逐字节一致（必须一致）；③给出样片路径供用户看。

**六、不许做/红线**：不碰"每行中文对齐每行英文"（§46.46 语序墙已否，别再进）；不改英文分页/时间/ASR/翻译/合成；不重跑管线、不跑全量回归、不写 checkpoint、不 commit；不动 stable-runs 与人工终稿（只读）；看见别的问题只写"发现但没动"清单。

**七、做完停下，报告写 `docs/handoffs/P1-whole-sentence-zh-<日期>.md`，附样片位置。**

**八、如果本单的判定性前提（尤其 A2 拼接≈整句、A3 纯显示改动）与实际不符，请驳回本单并只给差异报告。**\n

## §46.48 工单 P1-land-test：把「多页父整句中文」接进真实渲染层（旗标默认关、只测本集、不落地不提交，按 §46.13 八条执行）

**背景（用户已看 §46.47 旁路样片，认可方向，现要「先测测」真实管线里的效果）**：§46.47 用独立脚本证明了整句显示在这一集英文逐字节不变、中文≤2 行零溢出、且比切碎版更自然。现要把同一逻辑接进 app/ 真实渲染/显示层，但用旗标包起来、默认关，只在本集验证真实产物与旁路样片一致、且默认关时与现有产物逐字节相同。**仍是测，不落地、不提交、不改默认行为。**

**一、开工前先回述三行等确认**：本单只做什么、白名单（含你点名的确切文件）、验证方式，回述我确认后再动手。

**二、改动文件白名单**：只允许改「多页父选取每页 zh」的那一个显示/渲染模块，外加一个默认关闭的旗标/配置项；**旗标关＝现有行为一字不差**。不改英文分页、cue 时间轴、ASR、翻译、合成、单页父路径。你在回述里点名确切文件；若发现这一步的中文来源不在单一可切换处、必须动到分页或时间才能换，直接走第八条驳回。

**三、判定性前提（A 类，先核验，任一不成立即驳回）**：
A1 真实显示层里，多页父「每页 zh」的选取存在一个孤立可切换点，改这里取父级 authoritative 整句不需要碰英文分页/时间。
A2 旗标默认关时，本集真实产物（英文页文本、时间、单页父中文、多页父每页 zh）与现有 stable 产物逐字节一致。
A3 旗标开时，本集多页父整句显示结果与 §46.47 旁路样片一致（英文哈希 True、多页父中文＝父级整句、零溢出）。

**四、做什么（只这一集）**：在白名单模块加旗标；旗标开＝多页父显示父级权威整句（该父第一页 start_ms 到末页 end_ms 恒定），英文页/时间/字号不动、单页父不动。对本集：默认关跑一遍、旗标开跑一遍，各出真实产物。用现有 stable 产物（20260828T032249…，只读）当对照，不重跑 ASR/翻译/合成，只走显示/渲染那一步。

**五、报数字（先数字后结论）**：①旗标关的本集产物 vs 现有 stable 产物是否逐字节一致（必须一致，这是「没砸默认路径」的证据）；②旗标开时英文每页文本＋时间是否与 stable 逐字节一致、多页父数、整句中文各占几行、列出溢出父（应为 0）；③旗标开结果与 §46.47 旁路样片是否一致；④两版产物路径供用户肉眼看。

**六、不许做/红线**：不碰「每行中文对齐每行英文」（§46.46 语序墙已否）；不改英文分页/时间/ASR/翻译/合成；旗标默认必须关、不改任何现有集的既有产物；本集「逐页切中文」那一步这次保持原样不动（把它改成非阻断是另一单，不在本单范围）；不重跑管线、不跑全量回归（只跑本集显示/渲染一步，超一分钟即跑错）、不写 checkpoint、不 commit；不动 stable-runs 与人工终稿（只读）；看见别的问题只写「发现但没动」清单。

**七、做完停下，报告写 `docs/handoffs/P1-whole-sentence-zh-land-test-<日期>.md`，附两版产物位置与三项一致性结论（关=stable、开英文=stable、开=样片）。**

**八、如果本单的判定性前提与实际不符——尤其 A1 没有单一可切换点、或 A2 旗标关时产物与 stable 不是逐字节一致——请驳回本单并只给差异报告，不要为了接旗标去改分页或时间。**

## §46.49 参考竞品字幕做法观察报告（Claude 逐帧看两支 B 站视频，2026-08-28）——观察＋假设，供 GPT 核实

**来源**：桌面两支视频，同一个号「英语脱敏实验室」（画面挂 The Economist），与我们同赛道：`我们正进入一个普遍"性压抑"的时代。.mp4`（约15分）、`《牛来》爆红背后,是中国年轻人的文化抵抗。.mp4`（约17.5分）。均 1280×720、字幕为烧录（无软字幕轨）。**方法**：ffmpeg 抽前 180 秒→裁底部字幕带→mpdecimate 去重得约 60–66 帧→montage 成表逐帧读。原视频在桌面；抽出的帧在我的临时目录（非仓库、易失），GPT 要复核可按此法重抽。

**观察（画面读到的事实，非代码结论）**：
① 版式＝字幕条式：底部一屏一小段，英文大字在上、中文小字在下；左栏一张生词卡（词＋音标＋词性＋词典释义），句中高亮该生词。
② 切分＝按意群/逗号/停顿断，一屏≈一个小句（英文 1–2 行）。
③ 翻译＝每屏中文都是通顺完整的一小段；长句拆成多屏时每段各自通顺、末尾用逗号/顿号挂住，连起来成整句。牛来前 3 分钟实例：`And this movie has blinking cows. By all standard logic,`→「而这部片只有眨眼的牛。按正常逻辑，」／`a movie like Niu Lai shouldn't even be in the same theater,`→「像《牛来》这种片根本不该同台放映，」／`let alone competing with Marvel. How is this happening?`→「更别说跟漫威同台竞技了。怎么做到的？」。so…that… 那句同样三屏用逗号接：「线上的狂热过于汹涌和剧烈，／以至于把人们真正轰出了家门，／纷纷涌进了实体电影院。」
④ 时间＝一屏跟一屏贴音频走，无提前整句剧透。
⑤ 生词＝侧栏给词典形（excruciatingly＝极其痛苦地），句内翻译用语境自然形（让人抓狂），二者不同。

**推断（我的假设，请拿代码核实或驳回）**：这套既不是我们现在的「整句翻好→按长度切英文页→拿定死的整句中文去凑页」（会语序乱/别扭），也不是 §46.47 的「整句中文挂满多页」（会剧透）；而是第三条——在意群处断、每段单独翻、标点接续，于是同时拿到「每屏中文跟音频走不剧透」和「每段中文都是人话」。关键差异＝断点位置＋操作顺序：我方英文分页按长度切、切点常落半句中间，且「先整句翻再剁中文」，撞上中英语序差＝§46.46 语序墙；竞品先在中英都能干净断开的意群/标点处切，再逐段翻，绕开墙。旁证（待核实）：此前测过自动切点约 86.7% 落标点——方向一致，坏在剩余落进半句那部分＋「先整句后剁」的顺序。

**请 GPT 核实的具体点**：
1. stable 管线里多页父的每页中文，到底是不是「从整句中文按英文页边界切出来」的（查 display-page-translation 那步实现）。
2. 英文分页切点判据是否以「长度/排版」为主、是否允许切在小句中间（非标点处）。
3. 若改成「只在标点/意群边界切页、且每页中文按该意群单独生成」，工程落在哪一层、动多大，是否比 §46.47 显示旗标更上游。
4. 若上面对参考视频的观察与事实不符（比如它其实也切半句、中文也有硬凑），请指出。

**红线**：这是观察＋假设报告，不是让你改代码——先只核实并给结论，别动管线、别跑全量回归、别改现有断言、别 commit。若判定性推断（尤其「竞品靠意群切＋逐段翻绕开语序墙」「我方是先整句翻再按长度剁」）与代码或画面不符，请驳回本报告并只给差异。
