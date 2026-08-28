"""Build the §28 P1 Chinese-edit attribution table from manual snapshots.

The script replays only the JSON history snapshots. It does not import review
detectors, call a model, or write to a production artifact.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "objective-harness"))
from measure_objective import DEFAULT_INPUTS, _as_list, _load_document, _parent_ids, _root


EXPECTED_CHINESE_STEPS = {
    "employment": 61,
    "dreamcore": 149,
    "bad_animation": 75,
}
CHINESE_EDIT_OPERATION = "edit_display_page_chinese"
STRUCTURAL_OPERATIONS = frozenset(
    {
        "split_display_page",
        "split_parent_into_display_pages",
        "merge_display_page_with_next",
        "merge_adjacent_display_pages",
        "move_display_page_boundary",
        "move_prefix_to_previous",
        "move_suffix_to_next",
    }
)
RE_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[,.]\d+)*(?:%|[A-Za-z]+)?")
RE_CJK = re.compile(r"[\u3400-\u9fff]")
RE_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


def _snapshot_pages(state: Any) -> list[dict[str, Any]]:
    if not isinstance(state, Mapping):
        return []
    rows = state.get("display_page_edits")
    return [dict(row) for row in _as_list(rows) if isinstance(row, Mapping)]


def _before_states(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("before_parent_states")
    if isinstance(value, Mapping):
        return value
    # Employment's schema-v1 draft stores one complete page snapshot instead
    # of parent-scoped snapshots. Normalize it to the same internal shape.
    pages = [
        dict(page)
        for page in _as_list(item.get("before_display_page_edits"))
        if isinstance(page, Mapping) and page.get("parent_subtitle_id")
    ]
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"display_page_edits": []}
    )
    for page in pages:
        grouped[str(page["parent_subtitle_id"])] ["display_page_edits"].append(page)
    return grouped


def _final_pages_by_parent(root: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in _as_list(root.get("display_page_edits")):
        if not isinstance(page, Mapping):
            continue
        parent_id = str(page.get("parent_subtitle_id") or "")
        if parent_id:
            result[parent_id].append(dict(page))
    return dict(result)


def _next_before_state(
    history: list[Mapping[str, Any]], start: int, parent_id: str
) -> Mapping[str, Any] | None:
    for item in history[start + 1 :]:
        state = _before_states(item).get(parent_id)
        if isinstance(state, Mapping):
            return state
    return None


def _previous_operations(
    history: list[Mapping[str, Any]], start: int, parent_ids: set[str]
) -> dict[str, str]:
    result: dict[str, str] = {}
    remaining = set(parent_ids)
    for item in history[start - 1 :: -1]:
        ids = _parent_ids(item)
        for parent_id in remaining & ids:
            result[parent_id] = str(item.get("operation") or "")
        remaining -= ids
        if not remaining:
            break
    return result


def _page_map(pages: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(page.get("display_page_id")): page
        for page in pages
        if str(page.get("display_page_id") or "")
    }


def _text(page: Mapping[str, Any] | None, key: str) -> str:
    if not page:
        return ""
    return str(page.get(key) or "")


def _extract_rows(label: str, path: Path) -> list[dict[str, Any]]:
    document = _load_document(path)
    root = _root(document)
    history = [
        item
        for item in _as_list(document.get("history"))
        if isinstance(item, Mapping)
    ]
    final_pages = _final_pages_by_parent(root)
    rows: list[dict[str, Any]] = []
    for history_index, item in enumerate(history):
        if str(item.get("operation") or "") != CHINESE_EDIT_OPERATION:
            continue
        parent_ids = _parent_ids(item)
        before_states = _before_states(item)
        if not parent_ids:
            raise ValueError(f"P1 row has no parent ID: {label} history[{history_index}]")
        previous_operations = _previous_operations(history, history_index, parent_ids)
        follows_structure = any(
            operation in STRUCTURAL_OPERATIONS
            for operation in previous_operations.values()
        )
        pages: list[dict[str, Any]] = []
        for parent_id in sorted(parent_ids):
            before_state = before_states.get(parent_id)
            if not isinstance(before_state, Mapping):
                raise ValueError(
                    f"P1 row has no before snapshot: {label} history[{history_index}] {parent_id}"
                )
            after_state = _next_before_state(history, history_index, parent_id)
            after_pages = _snapshot_pages(after_state) if after_state else final_pages.get(parent_id, [])
            before_pages = _snapshot_pages(before_state)
            if not after_pages:
                raise ValueError(
                    f"P1 row has no after snapshot: {label} history[{history_index}] {parent_id}"
                )
            before_map = _page_map(before_pages)
            after_map = _page_map(after_pages)
            page_ids = sorted(set(before_map) | set(after_map))
            for page_id in page_ids:
                before_page = before_map.get(page_id)
                after_page = after_map.get(page_id)
                pages.append(
                    {
                        "display_page_id": page_id,
                        "english": _text(after_page, "english") or _text(before_page, "english"),
                        "before_chinese": _text(before_page, "chinese"),
                        "after_chinese": _text(after_page, "chinese"),
                        "before_exists": before_page is not None,
                        "after_exists": after_page is not None,
                    }
                )
        rows.append(
            {
                "label": label,
                "history_index": history_index,
                "operation_at": str(item.get("at") or ""),
                "parent_subtitle_ids": sorted(parent_ids),
                "parent_subtitle_id": ",".join(sorted(parent_ids)),
                "previous_parent_operations": previous_operations,
                "source_context": (
                    "after_manual_structure_change"
                    if follows_structure
                    else "initial_or_nonstructural"
                ),
                "pages": pages,
            }
        )
    return rows


def _numbers(text: str) -> set[str]:
    return {match.group(0).casefold() for match in RE_NUMBER.finditer(text)}


def _cjk_count(text: str) -> int:
    return len(RE_CJK.findall(text))


def _normalized_chinese(text: str) -> str:
    return RE_PUNCT.sub("", text)


def _has_duplicate_pages(pages: list[Mapping[str, Any]], key: str) -> bool:
    values = [str(page.get(key) or "").strip() for page in pages]
    return any(values[index] and values[index] == values[index + 1] for index in range(len(values) - 1))


def _classify(row: Mapping[str, Any]) -> dict[str, Any]:
    pages = [page for page in _as_list(row.get("pages")) if isinstance(page, Mapping)]
    before = "\n".join(str(page.get("before_chinese") or "") for page in pages)
    after = "\n".join(str(page.get("after_chinese") or "") for page in pages)
    english = "\n".join(str(page.get("english") or "") for page in pages)
    before_empty_to_filled = any(
        not str(page.get("before_chinese") or "").strip()
        and str(page.get("after_chinese") or "").strip()
        for page in pages
    )
    max_before = max((_cjk_count(str(page.get("before_chinese") or "")) for page in pages), default=0)
    max_after = max((_cjk_count(str(page.get("after_chinese") or "")) for page in pages), default=0)
    length_repaired = max_before > 24 and max_after <= 24
    duplicate_repaired = _has_duplicate_pages(pages, "before_chinese") and not _has_duplicate_pages(
        pages, "after_chinese"
    )
    english_numbers = _numbers(english)
    before_numbers = _numbers(before)
    after_numbers = _numbers(after)
    # Only call a number issue A-grade when the same Arabic token is visibly
    # present in the corrected Chinese and absent before. Locale conversion
    # such as "11.4 million" -> "1140万" still needs semantic reading (B).
    number_repaired = bool(
        english_numbers
        and english_numbers.issubset(after_numbers)
        and not english_numbers.issubset(before_numbers)
    )
    moved_page_text = False
    before_values = [str(page.get("before_chinese") or "").strip() for page in pages]
    after_values = [str(page.get("after_chinese") or "").strip() for page in pages]
    if len(before_values) == len(after_values) and len(before_values) > 1:
        moved_page_text = set(after_values) == set(before_values) and after_values != before_values

    if length_repaired:
        defect_type, detectability, basis = "长度超限", "A", "改前页中文字数超过登记的24字建议值，改后回到建议值内"
    elif duplicate_repaired:
        defect_type, detectability, basis = "相邻页重复", "A", "改前相邻页中文完全重复，改后不再重复"
    elif number_repaired:
        defect_type, detectability, basis = "实体或数字错", "A", "英文含数字且改前后中文数字集合发生可验证变化"
    elif moved_page_text:
        defect_type, detectability, basis = "中英分配错位", "A", "页面中文文本只在同一父字幕页之间换位"
    elif before_empty_to_filled:
        defect_type, detectability, basis = "语义漏译", "A", "改前页面中文为空，改后出现非空中文"
    elif _normalized_chinese(before) == _normalized_chinese(after):
        defect_type, detectability, basis = "纯风格偏好", "C", "去掉标点和空白后改前后文本相同"
    else:
        defect_type, detectability, basis = "中文不通顺", "B", "需要逐页阅读英文、中文和相邻页才能判断语义与连贯性"

    return {
        "defect_type": defect_type,
        "detectability": detectability,
        "classification_basis": basis,
        "before_cjk_max": max_before,
        "after_cjk_max": max_after,
        "english_numbers": sorted(english_numbers),
        "before_numbers": sorted(before_numbers),
        "after_numbers": sorted(after_numbers),
    }


def _load_mark_codes(artifact_dir: Path | None) -> tuple[dict[str, set[str]], str]:
    if artifact_dir is None or not artifact_dir.is_dir():
        return {}, "no bound artifact directory supplied"
    codes: dict[str, set[str]] = defaultdict(set)
    sources = [
        (artifact_dir / "editor-review-ledger.json", "items"),
        (artifact_dir / "semantic-review-queue.json", "items"),
        (artifact_dir / "translation-quality-audit.json", "items"),
        (artifact_dir / "display-page-translations.json", "reviews"),
    ]
    found = False
    for path, key in sources:
        if not path.is_file():
            continue
        found = True
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        values = payload.get(key) if isinstance(payload, Mapping) else None
        for item in _as_list(values):
            if not isinstance(item, Mapping):
                continue
            codes_for_item = [
                str(item.get("code") or item.get("category") or "")
            ]
            if not codes_for_item[0]:
                codes_for_item = [
                    str(value)
                    for value in _as_list(item.get("issue_codes"))
                    if str(value)
                ]
            codes_for_item = [code for code in codes_for_item if code]
            ids = item.get("subtitle_ids") or item.get("affected_parent_ids") or item.get("parent_subtitle_id")
            for value in _as_list(ids):
                if isinstance(value, str):
                    match = re.match(r"^(S\d+)", value)
                    if match:
                        codes[match.group(1)].update(codes_for_item)
    return dict(codes), "bound mark artifacts loaded" if found else "no mark artifact files found"


def _detector_reason(
    classification: Mapping[str, Any], mark_codes: set[str], mark_status: str
) -> dict[str, Any]:
    defect = str(classification["defect_type"])
    detectability = str(classification["detectability"])
    if mark_codes:
        return {
            "status": "triggered_but_user_still_edited",
            "evidence": sorted(mark_codes),
            "reason": "当前可绑定产物已有相关标记，但标记没有替代人工最终判断。",
        }
    if detectability == "C":
        return {
            "status": "intentionally_not_detected",
            "evidence": [],
            "reason": "纯风格偏好没有稳定的生产判据，现有检测器不应把它当缺陷。",
        }
    code_by_type = {
        "长度超限": "display_page_chinese_load_review / chinese_reading_speed_warning",
        "相邻页重复": "adjacent_chinese_duplicate_review",
        "实体或数字错": "display_page_chinese_continuity_review / number_allocation_mismatch",
        "中英分配错位": "display_page_chinese_continuity_review / entity_allocation_mismatch",
        "语义漏译": "display_page_translation_invalid / display_page_chinese_continuity_review",
        "中文不通顺": "translation_fluency_review / model_english_chinese_mismatch",
    }
    return {
        "status": "not_proven_from_current_evidence",
        "evidence": [],
        "reason": (
            f"候选检测器是 {code_by_type.get(defect, '未找到对应稳定 code')}，"
            f"但本样本没有绑定到该父字幕的当前标记；{mark_status}，"
            "因此不能进一步断言是未触发、被过滤还是请求未覆盖。"
        ),
    }


def _annotate(rows: list[dict[str, Any]], mark_codes: dict[str, set[str]], mark_status: str) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for row in rows:
        classification = _classify(row)
        parent_ids = [
            str(value)
            for value in _as_list(row.get("parent_subtitle_ids"))
            if str(value)
        ]
        if not parent_ids:
            parent_ids = [str(row["parent_subtitle_id"])]
        row = dict(row)
        row.update(classification)
        row["p2_eligible_a"] = bool(
            row["detectability"] == "A"
            and row.get("source_context") == "initial_or_nonstructural"
        )
        row["detector"] = _detector_reason(
            classification,
            {
                code
                for parent_id in parent_ids
                for code in mark_codes.get(parent_id, set())
            },
            mark_status,
        )
        annotated.append(row)
    return annotated


def _markdown(rows_by_label: Mapping[str, list[Mapping[str, Any]]], total_expected: int) -> str:
    all_rows = [row for rows in rows_by_label.values() for row in rows]
    defect_counts = Counter(str(row["defect_type"]) for row in all_rows)
    detectability_counts = Counter(str(row["detectability"]) for row in all_rows)
    lines = [
        "# P1 中文修改归因表",
        "",
        "本表从三份人工终稿 history 的前后快照生成；不修改检测器，不写回旧产物。",
        "分类中的 A/B/C 是可检测性，不是质量分数。A 为冻结产物可判定，B 需逐页读中英，C 为风格偏好。",
        "P2 只使用 source_context 为 initial_or_nonstructural 的 A 档；结构修改之后产生的空白页属于人工跟进，不直接做稳定流程标记。",
        "",
        f"覆盖：{len(all_rows)}/{total_expected} 条中文修改步骤。",
        f"P2 可用 A 档：{sum(1 for row in all_rows if row.get('p2_eligible_a'))} 条；"
        "用户先改分页后产生的 A 档跟进项不直接接入稳定标记。",
        "",
        "## 汇总",
        "",
        "### 缺陷类型",
        "",
        "| 类型 | 条数 | 占比 |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| {key} | {value} | {100 * value / len(all_rows):.1f}% |"
        for key, value in sorted(defect_counts.items())
    )
    lines.extend(
        [
            "",
            "### 可检测性",
            "",
            "| 档位 | 条数 | 占比 |",
            "|---|---:|---:|",
        ]
    )
    lines.extend(
        f"| {key} | {value} | {100 * value / len(all_rows):.1f}% |"
        for key, value in sorted(detectability_counts.items())
    )
    lines.extend(["", "## 逐条记录", ""])
    for label, rows in rows_by_label.items():
        lines.extend([f"### {label}", ""])
        lines.extend(
            [
                "| # | 父ID | 页 | 改前中文 | 改后中文 | 缺陷 | 可检测性 | 检测器依据 |",
                "|---:|---|---|---|---|---|---|---|",
            ]
        )
        for index, row in enumerate(rows, 1):
            page_text = "<br>".join(
                f"{page['display_page_id']}: {page['before_chinese']} → {page['after_chinese']}"
                for page in row["pages"]
            )
            lines.append(
                f"| {index} | {row['parent_subtitle_id']} | {page_text} | "
                f"{row['defect_type']} | {row['detectability']} | "
                f"{row['detector']['status']}：{row['detector']['reason']} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--employment", type=Path, default=DEFAULT_INPUTS["employment"])
    parser.add_argument("--dreamcore", type=Path, default=DEFAULT_INPUTS["dreamcore"])
    parser.add_argument("--bad-animation", type=Path, default=DEFAULT_INPUTS["bad_animation"])
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = {
        "employment": args.employment,
        "dreamcore": args.dreamcore,
        "bad_animation": args.bad_animation,
    }
    artifact_dirs = {
        "employment": Path(
            r"E:\VideoCaptioner-screen-subtitle\work-dir\无论怎么衡量，就业市场都很疲软"
        )
        / "subtitle"
        / "stable-checkpoints"
        / "20260821T145313.192574-4fbdb7bc"
        / "【样式字幕】无论怎么衡量，就业市场都很疲软-FasterWhisper ✨-英语-LLM 大模型翻译-artifacts",
        "dreamcore": Path(
            r"D:\经济学人\2026-08-15\其他媒体\中式梦核：千禧一代的怀旧密码"
        )
        / "中式梦核：千禧一代的怀旧密码-处理结果"
        / "人工终稿字幕包"
        / "generations"
        / "20260820T061937522986-12eebd05"
        / "人工终稿字幕-artifacts",
        "bad_animation": Path(
            r"D:\经济学人\2026-08-15\其他媒体\烂到爆红：一部动画电影的逆袭"
        )
        / "烂到爆红：一部动画的逆袭-处理结果"
        / "人工终稿字幕包"
        / "generations"
        / "20260818T065438686900-50c82531"
        / "人工终稿字幕-artifacts",
    }
    rows_by_label: dict[str, list[dict[str, Any]]] = {}
    for label, path in paths.items():
        rows = _extract_rows(label, path)
        expected = EXPECTED_CHINESE_STEPS[label]
        if len(rows) != expected:
            raise ValueError(f"{label}: expected {expected} Chinese edit steps, got {len(rows)}")
        mark_codes, mark_status = _load_mark_codes(artifact_dirs[label])
        rows_by_label[label] = _annotate(rows, mark_codes, mark_status)

    all_rows = [row for rows in rows_by_label.values() for row in rows]
    payload = {
        "schema": "chinese-attribution-p1-v1",
        "registered_total": sum(EXPECTED_CHINESE_STEPS.values()),
        "covered_total": len(all_rows),
        "coverage_percent": round(100 * len(all_rows) / sum(EXPECTED_CHINESE_STEPS.values()), 1),
        "passed": len(all_rows) == sum(EXPECTED_CHINESE_STEPS.values())
        and all(
            row.get("defect_type") and row.get("detectability") in {"A", "B", "C"}
            and row.get("detector", {}).get("reason")
            for row in all_rows
        ),
        "runs": rows_by_label,
        "summary": {
            "defect_type": dict(Counter(str(row["defect_type"]) for row in all_rows)),
            "detectability": dict(Counter(str(row["detectability"]) for row in all_rows)),
            "p2_eligible_a": sum(1 for row in all_rows if row.get("p2_eligible_a")),
            "a_after_manual_structure": sum(
                1
                for row in all_rows
                if row.get("detectability") == "A"
                and row.get("source_context") == "after_manual_structure_change"
            ),
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_markdown.write_text(
        _markdown(rows_by_label, sum(EXPECTED_CHINESE_STEPS.values())), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "registered_total": payload["registered_total"],
                "covered_total": payload["covered_total"],
                "coverage_percent": payload["coverage_percent"],
                "detectability": payload["summary"]["detectability"],
                "passed": payload["passed"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"P1 attribution failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
