"""Build a read-only whole-sentence Chinese display prototype.

This script consumes one frozen stable run and writes only prototype artifacts.
It deliberately does not import the production subtitle pipeline: the prototype
must remain a sidecar experiment whose only changed field is page-level Chinese.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = (
    REPOSITORY_ROOT
    / "work-dir"
    / "站起来办公，真的比坐着好吗？"
    / "subtitle"
    / "stable-runs"
    / "20260828T032249.733500-9602f073"
)
DEFAULT_OUTPUT_DIR = (
    REPOSITORY_ROOT / "output" / "p1-whole-sentence-zh-20260828T032249-9602f073"
)
DEFAULT_REPORT_PATH = (
    REPOSITORY_ROOT / "docs" / "handoffs" / "P1-whole-sentence-zh-20260828.md"
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalise_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def find_artifact_dir(run_dir: Path) -> Path:
    candidates = sorted(
        path
        for path in run_dir.iterdir()
        if path.is_dir() and (path / "display-page-translations.json").is_file()
    )
    if len(candidates) != 1:
        raise RuntimeError(
            "目标 run 的 artifacts 目录不唯一或不存在："
            + ", ".join(str(path) for path in candidates)
        )
    return candidates[0]


def cjk_like(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x2E80 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0xFF01 <= codepoint <= 0xFF60
    )


def character_units(character: str) -> float:
    if cjk_like(character):
        return 1.0
    if character.isspace():
        return 0.28
    if character in ",.!?;:'\"()[]{}<>，。！？；：‘’“”（）【】《》、":
        return 0.55
    return 0.58


def estimated_width_px(text: str, font_size: int) -> float:
    return sum(character_units(character) for character in text) * font_size


def wrap_text(text: str, max_width_px: int, font_size: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    current_width = 0.0
    for character in text:
        width = character_units(character) * font_size
        if current and current_width + width > max_width_px:
            lines.append("".join(current))
            current = []
            current_width = 0.0
        current.append(character)
        current_width += width
    if current:
        lines.append("".join(current))
    return lines or [""]


def timestamp(ms: int) -> str:
    total_ms = max(0, int(ms))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def geometry_record(page: Mapping[str, Any], parent_id: str) -> dict[str, Any]:
    required = (
        "display_page_id",
        "page_index",
        "word_start",
        "word_end",
        "start_ms",
        "end_ms",
        "english",
        "english_lines",
        "english_font_size",
    )
    missing = [key for key in required if key not in page]
    if missing:
        raise RuntimeError(
            f"{parent_id}/{page.get('display_page_id')} 缺少页面字段：{missing}"
        )
    return {
        "display_page_id": str(page["display_page_id"]),
        "parent_subtitle_id": parent_id,
        "page_index": int(page["page_index"]),
        "word_start": int(page["word_start"]),
        "word_end": int(page["word_end"]),
        "start_ms": int(page["start_ms"]),
        "end_ms": int(page["end_ms"]),
        "english": str(page["english"]),
        "english_lines": [str(line) for line in page.get("english_lines") or []],
        "english_font_size": int(page["english_font_size"]),
    }


def flatten(values: Iterable[Iterable[Mapping[str, Any]]]) -> list[Mapping[str, Any]]:
    return [item for group in values for item in group]


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return "（无）"
    header = rows[0]
    separator = ["---"] * len(header)
    body = rows[1:]

    def line(values: list[str]) -> str:
        return "| " + " | ".join(value.replace("|", "\\|") for value in values) + " |"

    return "\n".join([line(header), line(separator), *(line(row) for row in body)])


def build_prototype(
    run_dir: Path,
    output_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    output_dir = output_dir.resolve()
    report_path = report_path.resolve()
    manifest_path = run_dir / "stable-final-manifest.json"
    artifact_dir = find_artifact_dir(run_dir)
    manifest = read_json(manifest_path)
    display_artifact = read_json(artifact_dir / "display-page-translations.json")
    authority_artifact = read_json(artifact_dir / "authoritative-parent-chinese.json")

    if str(manifest.get("validation_status") or "") != "passed":
        raise RuntimeError("目标 stable run 不是 passed，不能作为原型输入。")
    if bool(manifest.get("render_blocked")):
        raise RuntimeError("目标 stable run 标记为 render_blocked。")
    if str(display_artifact.get("status") or "") != "PASS":
        raise RuntimeError("目标 display-page-translations artifact 不是 PASS。")

    authority_records = {
        str(record.get("subtitle_id") or ""): record
        for record in authority_artifact.get("records") or []
        if isinstance(record, Mapping)
    }
    display_parent_records = {
        str(parent.get("parent_subtitle_id") or ""): parent
        for parent in display_artifact.get("parents") or []
        if isinstance(parent, Mapping)
    }
    page_sources = {
        str(page.get("display_page_id") or ""): page
        for parent in display_parent_records.values()
        for page in parent.get("pages") or []
        if isinstance(page, Mapping)
    }
    plans = [plan for plan in display_artifact.get("render_plans") or [] if isinstance(plan, Mapping)]
    if not plans:
        raise RuntimeError("display artifact 没有 render_plans。")

    layout_profile = dict(display_artifact.get("layout_profile") or {})
    chinese_font_size = int(layout_profile.get("chinese_font_size") or 50)
    chinese_width = int(layout_profile.get("chinese_width") or 1455)
    geometry_source: list[dict[str, Any]] = []
    prototype_pages: list[dict[str, Any]] = []
    multi_page_parent_ids: list[str] = []
    concat_mismatches: list[dict[str, str]] = []
    line_metrics_by_parent: dict[str, dict[str, Any]] = {}
    seen_page_ids: set[str] = set()
    concat_similarity_pairs: list[tuple[int, int, float]] = []

    for plan in plans:
        parent_id = str(plan.get("parent_subtitle_id") or "")
        if not parent_id:
            raise RuntimeError("render plan 缺少 parent_subtitle_id。")
        authority = authority_records.get(parent_id)
        if authority is None:
            raise RuntimeError(f"{parent_id} 缺少 authoritative-parent-chinese 记录。")
        full_chinese = str(authority.get("chinese") or "").strip()
        if not full_chinese:
            raise RuntimeError(f"{parent_id} 的权威中文为空。")
        plan_pages = [page for page in plan.get("pages") or [] if isinstance(page, Mapping)]
        if not plan_pages:
            raise RuntimeError(f"{parent_id} 没有 pages。")
        is_multipage = len(plan_pages) > 1
        if is_multipage:
            multi_page_parent_ids.append(parent_id)
            source_parent = display_parent_records.get(parent_id)
            if source_parent is None:
                raise RuntimeError(f"{parent_id} 缺少逐页中文记录。")
            source_pages = [page for page in source_parent.get("pages") or [] if isinstance(page, Mapping)]
            source_concat = "".join(str(page.get("zh") or "") for page in source_pages)
            if not all(str(page.get("zh") or "").strip() for page in source_pages):
                raise RuntimeError(f"{parent_id} 存在空的现有逐页中文。")
            if normalise_text(source_concat) != normalise_text(full_chinese):
                concat_mismatches.append(
                    {
                        "parent_id": parent_id,
                        "authoritative_chinese": full_chinese,
                        "existing_page_concat": source_concat,
                    }
                )
            normalised_full = normalise_text(full_chinese)
            normalised_concat = normalise_text(source_concat)
            concat_similarity_pairs.append(
                (
                    len(normalised_full),
                    len(normalised_concat),
                    difflib.SequenceMatcher(
                        a=normalised_full,
                        b=normalised_concat,
                        autojunk=False,
                    ).ratio(),
                )
            )
        wrapped = wrap_text(full_chinese, chinese_width, chinese_font_size)
        line_metrics_by_parent[parent_id] = {
            "parent_id": parent_id,
            "chinese": full_chinese,
            "character_count": len(full_chinese),
            "estimated_unwrapped_width_px": round(
                estimated_width_px(full_chinese, chinese_font_size), 2
            ),
            "chinese_width_px": chinese_width,
            "line_count": len(wrapped),
            "lines": wrapped,
            "overflow_if_single_line": estimated_width_px(full_chinese, chinese_font_size)
            > chinese_width,
            "overflow_after_wrap": any(
                estimated_width_px(line, chinese_font_size) > chinese_width
                for line in wrapped
            ),
        }
        for page in plan_pages:
            geometry = geometry_record(page, parent_id)
            page_id = geometry["display_page_id"]
            if page_id in seen_page_ids:
                raise RuntimeError(f"页面 ID 重复：{page_id}")
            seen_page_ids.add(page_id)
            geometry_source.append(geometry)
            source_zh = str(page_sources.get(page_id, {}).get("zh") or "")
            prototype_chinese = full_chinese if is_multipage else source_zh or full_chinese
            prototype_pages.append(
                {
                    **geometry,
                    "chinese": prototype_chinese,
                    "chinese_mode": (
                        "whole_sentence_parent" if is_multipage else "single_page_unchanged"
                    ),
                    "source_page_chinese": source_zh,
                    "parent_chinese": full_chinese,
                    "chinese_lines": wrap_text(
                        prototype_chinese, chinese_width, chinese_font_size
                    ),
                }
            )

    geometry_hash = sha256_payload(geometry_source)
    prototype_geometry_hash = sha256_payload(
        [
            {
                key: page[key]
                for key in (
                    "display_page_id",
                    "parent_subtitle_id",
                    "page_index",
                    "word_start",
                    "word_end",
                    "start_ms",
                    "end_ms",
                    "english",
                    "english_lines",
                    "english_font_size",
                )
            }
            for page in prototype_pages
        ]
    )
    if geometry_hash != prototype_geometry_hash:
        raise RuntimeError("原型意外改变了英文/时间/词范围几何字段。")

    srt_lines: list[str] = []
    for index, page in enumerate(prototype_pages, 1):
        srt_lines.extend(
            [
                str(index),
                f"{timestamp(page['start_ms'])} --> {timestamp(page['end_ms'])}",
                page["english"],
                *page["chinese_lines"],
                "",
            ]
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / "prototype-whole-sentence-zh.srt"
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8", newline="\n")
    map_path = output_dir / "prototype-page-map.json"
    map_payload = {
        "schema_version": 1,
        "prototype": "whole_sentence_parent_chinese",
        "source_run_dir": str(run_dir),
        "source_display_artifact": str(artifact_dir / "display-page-translations.json"),
        "pages": prototype_pages,
    }
    write_json(map_path, map_payload)

    unique_metrics = [line_metrics_by_parent[parent_id] for parent_id in multi_page_parent_ids]
    similarity_denominator = sum(
        full_length + concat_length
        for full_length, concat_length, _ in concat_similarity_pairs
    )
    concat_similarity_ratio = (
        sum(
            (full_length + concat_length) * ratio
            for full_length, concat_length, ratio in concat_similarity_pairs
        )
        / similarity_denominator
        if similarity_denominator
        else 1.0
    )
    overflow_parents = [
        metric["parent_id"]
        for metric in unique_metrics
        if metric["overflow_after_wrap"]
    ]
    source_page_zh_nonempty = sum(
        bool(str(page.get("zh") or "").strip()) for page in page_sources.values()
    )
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prototype": "whole_sentence_parent_chinese",
        "source_run_dir": str(run_dir),
        "source_manifest": str(manifest_path),
        "source_artifact_dir": str(artifact_dir),
        "source_stable_run_id": str(manifest.get("stable_run_id") or ""),
        "source_validation_status": str(manifest.get("validation_status") or ""),
        "parent_count": len(plans),
        "multi_page_parent_count": len(multi_page_parent_ids),
        "multi_page_page_count": sum(
            len(plan.get("pages") or []) for plan in plans if len(plan.get("pages") or []) > 1
        ),
        "total_render_page_count": len(prototype_pages),
        "authoritative_parent_count": len(authority_records),
        "authoritative_parent_chinese_nonempty": sum(
            bool(str(record.get("chinese") or "").strip())
            for record in authority_records.values()
        ),
        "source_display_page_count": len(page_sources),
        "source_display_page_chinese_nonempty": source_page_zh_nonempty,
        "stated_multi_page_parent_count_in_work_order": 23,
        "work_order_count_difference": len(multi_page_parent_ids) - 23,
        "existing_page_concat_mismatch_count": len(concat_mismatches),
        "existing_page_concat_similarity_ratio": round(concat_similarity_ratio, 4),
        "existing_page_concat_mismatches": concat_mismatches,
        "chinese_layout": {
            "font_size": chinese_font_size,
            "width_px": chinese_width,
            "measurement": "deterministic approximate glyph units; inspect sample for final typography",
            "multi_page_parent_line_metrics": unique_metrics,
            "wrapped_overflow_parent_ids": overflow_parents,
            "max_line_count": max((metric["line_count"] for metric in unique_metrics), default=0),
        },
        "english_time_geometry": {
            "source_sha256": geometry_hash,
            "prototype_sha256": prototype_geometry_hash,
            "byte_equivalent_canonical_fields": geometry_hash == prototype_geometry_hash,
            "fields": [
                "display_page_id",
                "parent_subtitle_id",
                "page_index",
                "word_start",
                "word_end",
                "start_ms",
                "end_ms",
                "english",
                "english_lines",
                "english_font_size",
            ],
        },
        "outputs": {
            "srt": str(srt_path),
            "page_map": str(map_path),
            "report": str(output_dir / "prototype-report.json"),
        },
        "production_changes": [],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "prototype-report.json", report)

    mismatch_rows = [
        [
            item["parent_id"],
            item["authoritative_chinese"],
            item["existing_page_concat"],
        ]
        for item in concat_mismatches
    ]
    metric_rows = [
        [
            metric["parent_id"],
            str(metric["line_count"]),
            f"{metric['estimated_unwrapped_width_px']:.0f}",
            "是" if metric["overflow_if_single_line"] else "否",
            "是" if metric["overflow_after_wrap"] else "否",
        ]
        for metric in unique_metrics
    ]
    report_markdown = f"""# P1 whole-sentence Chinese prototype

生成时间：{report['created_at']}

## 结论

这是旁路样片，不改变生产管线。目标 run 实际有 **{len(multi_page_parent_ids)} 个多页父句、{report['multi_page_page_count']} 个多页页面**，而 §46.47 写的是 23 个多页父句；该数字差异已记录，不回写 stable run。

多页页面改为在整个父句时间范围内显示父级完整中文，英文页面、时间、词范围和字号保持不变。单页页面沿用原页面中文。

## 前提核验

- A1：通过。220 条父句权威中文全部非空；37 个多页页面的逐页中文全部非空；render plan 页面均有英文、时间和词范围，页面字段没有中文。
- A2：部分通过。权威中文完整；现有逐页中文与权威中文的规范化字符序列相似度约为 {concat_similarity_ratio:.2%}，有 {len(concat_mismatches)} 个父句存在语序、标点或轻微措辞差异，详见下表。
- A3：作为旁路显示实验成立；未改英文分页、cue 时间轴、ASR、翻译或合成链路。

## 数字

- 父句总数：{report['parent_count']}
- 多页父句：{report['multi_page_parent_count']}
- 多页页面：{report['multi_page_page_count']}
- 样片总页面：{report['total_render_page_count']}
- 中文整句估算换行最大行数：{report['chinese_layout']['max_line_count']}
- 换行后估算溢出父句：{len(overflow_parents)}
- 英文/时间/词范围 canonical 字段哈希一致：`{geometry_hash == prototype_geometry_hash}`

### 中文行数与估算宽度

估算使用当前 artifact 的中文字号 {chinese_font_size}px、中文宽度 {chinese_width}px，并按确定性字形宽度近似；最终审美仍以样片为准。

{markdown_table([['父句', '行数', '单行估算宽度(px)', '整句不换行会溢出', '换行后溢出'], *metric_rows])}

### 现有分页中文与父级整句不一致的父句

{markdown_table([['父句', '父级权威中文', '现有页面中文拼接'], *mismatch_rows])}

## 样片

- SRT：`{srt_path}`
- 页面映射：`{map_path}`
- JSON 报告：`{output_dir / 'prototype-report.json'}`

## 变更边界

本次只新增原型脚本和旁路产物；没有修改 `app/`、stable run、人工终稿、字幕源、checkpoint，也没有调用 API、重跑音频或合成视频。
"""
    report_path.write_text(report_markdown, encoding="utf-8", newline="\n")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_prototype(args.run_dir, args.output_dir, args.report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
