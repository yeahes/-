from __future__ import annotations

from datetime import datetime
from pathlib import Path


def write_reports(results: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "latest-report.json"
    md_path = out_dir / "latest-report.md"

    import json

    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(results), encoding="utf-8")
    return json_path, md_path


def _markdown(results: dict) -> str:
    lines = [
        "# 字幕稳定模式审计报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| 样本 | 状态 | 字幕数 | ERROR | WARNING | 文件 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for name, result in results.get("samples", {}).items():
        lines.append(
            "| {name} | {status} | {count} | {errors} | {warnings} | {path} |".format(
                name=name,
                status=result.get("status", "UNKNOWN"),
                count=result.get("count", 0),
                errors=len(result.get("errors", [])),
                warnings=len(result.get("warnings", [])),
                path=result.get("path") or "",
            )
        )
    lines.extend(["", "## 问题明细", ""])
    for name, result in results.get("samples", {}).items():
        lines.extend([f"### {name}", ""])
        if result.get("status") == "MISSING":
            lines.extend(["未找到可审计的稳定模式双语 SRT。", ""])
            continue
        for level in ("errors", "warnings", "info"):
            items = result.get(level, [])
            lines.append(f"#### {level.upper()}：{len(items)}")
            if not items:
                lines.extend(["无", ""])
                continue
            for item in items[:80]:
                index = item.get("index", item.get("indices", ""))
                msg = item.get("message", item.get("code", ""))
                lines.append(f"- ID {index}：{msg}")
                english = item.get("english")
                chinese = item.get("chinese")
                rule_codes = item.get("rule_codes")
                confidence = item.get("confidence")
                evidence = item.get("evidence")
                left_id = item.get("left_subtitle_id")
                right_id = item.get("right_subtitle_id")
                suspicious_text = item.get("suspicious_text")
                if left_id or right_id:
                    lines.append(f"  边界：{left_id or ''} -> {right_id or ''}")
                if rule_codes:
                    lines.append(f"  规则：{', '.join(rule_codes)}")
                if confidence:
                    lines.append(f"  置信度：{confidence}")
                if evidence:
                    lines.append(f"  依据：{evidence}")
                if suspicious_text:
                    lines.append(f"  可疑文本：{suspicious_text}")
                if english:
                    lines.append(f"  英文：{english}")
                if chinese:
                    lines.append(f"  中文：{chinese}")
            if len(items) > 80:
                lines.append(f"- 其余 {len(items) - 80} 条已省略，请看 JSON。")
            lines.append("")
    return "\n".join(lines)
