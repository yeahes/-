# T1-display-timing-lead 验证报告

生成时间：2026-08-27 08:21:00 +08:00

## 前提核验与数字

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| A1 常量位置和值 | 成立 | `final_cue_timeline.py:20` `DISPLAY_LEAD_IN_MS=40`；`:21` `DISPLAY_TAIL_PADDING_MS=260`；`:24` 原值 `SHORT_GAP_CHAIN_THRESHOLD_MS=1000`、本轮改为 `1500`；`:25` `MAX_CHAINED_NEXT_LEAD_MS=200`。 |
| A2 串接谓词与边界 | 成立 | `_chain_short_display_gaps` 位于 `final_cue_timeline.py:609-669`；`:639` 仅接受 `0 < word_gap < threshold`；`:642-652` 计算 3/4 边界并受后句最大提前量约束；`:654-655` 写成左右共享边界。 |
| A3 稳定模式最终时间轴入口 | 成立 | `derive_final_cue_timeline` 在 `final_cue_timeline.py:184-187` 直接读取两个常量；生产调用仅见 `screen_editor.py:8606-8611` 与 `manual_final_subtitle_editor.py:9333-9345`，均传入 `DISPLAY_LEAD_IN_MS` 和 `DISPLAY_TAIL_PADDING_MS`。未发现第二个稳定模式最终时间轴串接入口或同用途硬编码 `1000`。 |
| 旧产物复算一致性 | 256/256 | 用旧阈值 `1000` 离线复算后，与现存 `final-cue-timeline.json` 的 records 完全一致，差异 0。 |

说明：`app/core/bk_asr/asr_data.py:470` 另有旧的 `optimize_timing(threshold_ms=1000)` 字面值，调用点在 `screen_editor.py:960` 和 `transcribe.py:103`。`screen_editor.py:952-958` 表明有词时间戳时不走该分支；稳定模式最终 cue 还会在 `screen_editor.py:8571-8624` 从冻结词账本重建，因此它不是本工单所改的最终权威时间轴入口。

### 聚焦测试

| 树 | 用例数 | 结果 | 失败集合 |
| --- | ---: | --- | --- |
| 当前工作树 | 19 | PASS | 空 |
| `../vc-head-baseline` | 18 | PASS | 空 |

命令均为 `runtime\python.exe scripts\run_regression.py --only final-cue-timeline`。工作树新增了一条 `1000ms` 正向串接用例，因此比基线多 1 条；失败集合差集为空，没有新增红灯。

### 256 条离线重算

| 指标 | 数字 |
| --- | ---: |
| 新时间轴状态 | PASS |
| validation errors | 0 |
| cue records | 256 |
| 时间发生变化的 cue | 7 |
| `start_ms/end_ms` 以外字段变化 | 0 |
| `word_start/word_end` 变化 | 0 |
| word envelope 变化 | 0 |
| 字幕 ID、顺序、父集合变化 | 0 |
| 中文变化 | 0（只读输入，records 不携带/改写中文） |
| `start_ms < 0` | 0 |
| `start_ms >= end_ms` | 0 |
| 新重叠 | 0 |
| 改后显示空档 `>500ms` | 0 |

变化 cue：`S0035`、`S0036`、`S0037`、`S0069`、`S0070`、`S0123`、`S0124`。

新增串接边界共 4 处：

| 边界 | word gap | 改前显示空档 | 改后后句提前量 |
| --- | ---: | ---: | ---: |
| S0035 -> S0036 | 1440ms | 1140ms | 200ms |
| S0036 -> S0037 | 1200ms | 900ms | 200ms |
| S0069 -> S0070 | 1081ms | 781ms | 200ms |
| S0123 -> S0124 | 1461ms | 1161ms | 200ms |

提前量全量分布为 `min=0ms / median=80ms / max=360ms`。本轮新纳入的 4 个停顿边界，后句提前量均为 `200ms`。全量有两个既存例外超过 200ms：`S0062=360ms`、`S0242=260ms`；两条在改前已经存在，且不属于 7 条变化 cue。原因是后续 `_extend_short_display_ranges` 为极短 cue 补显示时长，可再次向前扩展 start；它说明 `MAX_CHAINED_NEXT_LEAD_MS=200` 只约束短空档串接步骤，不是最终全局硬上限。

### S0069 -> S0070 定点

| 状态 | 左句 display end | 右句 display start | 显示空档 | 右句提前量 | word gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| 改前 | 230674ms | 231455ms | 781ms | 40ms | 1081ms |
| 改后 | 231295ms | 231295ms | 0ms | 200ms | 1081ms |

全集改后仍 `>500ms` 的显示空档：0 处，清单为空。

## 结论

T1 白名单范围内通过：`1000 -> 1500` 只改变 7 条 cue 的 `start_ms/end_ms`，目标 S0069 -> S0070 的 781ms 空屏收窄为 0ms，新增停顿串接的后句提前量均为 200ms；256 条记录没有结构变化、非法区间或新重叠。工作树与 HEAD 基线的聚焦测试都无失败。

全局“最终提前量不超过 200ms”目前不是严格不变量：`_extend_short_display_ranges` 留有 2 条本轮未新增的例外。本工单按白名单未处理它们，也未改 tail padding、短 cue 延展、分页、翻译、allocation、审计或字号。

## 发现但没动

- `app/core/subtitle_processor/final_cue_timeline.py:672-728`：`_extend_short_display_ranges` 可在串接步骤之后继续提前极短 cue，产生 `S0062=360ms`、`S0242=260ms` 的既存最终提前量；需另立工单决定 200ms 是仅约束停顿串接，还是最终全局硬上限。
- `app/core/bk_asr/asr_data.py:470-500`：非词时间戳旧路径仍有独立的 `optimize_timing(threshold_ms=1000)`，但不拥有稳定模式最终权威 cue 时间轴，本轮未动。
