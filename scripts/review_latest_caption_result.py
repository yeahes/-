import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def newest_manifest(work_dir: Path, sample: str = "") -> Path:
    manifests = [
        path
        for path in work_dir.rglob("stable-final-manifest.json")
        if "rerun-" not in str(path)
        and (not sample or sample in str(path))
    ]
    if not manifests:
        raise SystemExit(f"No stable-final-manifest.json found under {work_dir}")
    return max(manifests, key=lambda path: path.stat().st_mtime)


def issue_count(summary: dict, key: str) -> int:
    value = summary.get(key)
    return len(value) if isinstance(value, list) else 0


def unique_repairs(items: list) -> list:
    unique = []
    seen = set()
    for item in items:
        key = (
            item.get("subtitle_id"),
            item.get("before_chinese"),
            item.get("after_chinese"),
            item.get("before_start_ms"),
            item.get("before_end_ms"),
            item.get("after_start_ms"),
            item.get("after_end_ms"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_review(manifest_path: Path) -> str:
    manifest = load_json(manifest_path)
    validation = manifest.get("validation_summary") or {}
    errors = list(validation.get("errors") or [])
    warnings = list(validation.get("warnings") or [])
    info = list(validation.get("info") or [])
    repair_log = list(manifest.get("safe_auto_repair_log") or [])
    candidates = list(manifest.get("safe_auto_repair_candidates") or [])
    changed = unique_repairs([
        item for item in repair_log
        if str(item.get("code") or "").endswith("_repaired")
        or str(item.get("code") or "") in {
            "safe_repair_changed",
            "chinese_text_repaired",
            "severe_chinese_speed_repaired",
            "missing_chinese_filled",
            "timing_padding_repaired",
        }
    ])
    rejected = [
        item for item in repair_log
        if "rejected" in str(item.get("code") or "")
        or "skipped" in str(item.get("code") or "")
    ]
    blocked = bool(manifest.get("render_blocked"))
    if blocked:
        verdict = "失败：有硬错误，合成应被阻止。"
    elif errors:
        verdict = "异常：报告里还有 ERROR，需要先看。"
    elif warnings:
        verdict = "可用：没有 ERROR，但还有 WARNING 需要抽查。"
    else:
        verdict = "通过：没有阻断问题。"

    lines = [
        f"样本：{manifest_path.parts[-3] if len(manifest_path.parts) >= 3 else manifest_path.parent.name}",
        f"Manifest：{manifest_path}",
        f"结论：{verdict}",
        f"字幕数：{manifest.get('subtitle_count', 0)}",
        f"ERROR：{len(errors)}",
        f"WARNING：{len(warnings)}",
        f"INFO：{len(info)}",
        f"安全修复：{'开' if manifest.get('safe_auto_repair_enabled') else '关'}",
        f"修复候选：{len(candidates)}",
        f"实际修复：{len(changed)}",
        f"跳过/拒绝：{len(rejected)}",
    ]
    if changed:
        lines.append("")
        lines.append("实际修复明细：")
        for item in changed[:12]:
            lines.append(
                f"- {item.get('subtitle_id', '')} {item.get('start', '')} --> {item.get('end', '')} {item.get('code', '')}"
            )
            before = str(item.get("before_chinese") or "").strip()
            after = str(item.get("after_chinese") or "").strip()
            if before or after:
                lines.append(f"  前：{before}")
                lines.append(f"  后：{after}")
    if warnings:
        lines.append("")
        lines.append("主要 WARNING：")
        for issue in warnings[:8]:
            count = issue_count(issue, "items")
            suffix = f"（{count}项）" if count else ""
            lines.append(f"- {issue.get('code', '')}：{issue.get('message', '')}{suffix}")
    if errors:
        lines.append("")
        lines.append("ERROR：")
        for issue in errors[:8]:
            count = issue_count(issue, "items")
            suffix = f"（{count}项）" if count else ""
            lines.append(f"- {issue.get('code', '')}：{issue.get('message', '')}{suffix}")
    paths = manifest.get("result_summary_paths") or {}
    if paths:
        lines.append("")
        lines.append("摘要文件：")
        for path in paths.values():
            lines.append(f"- {path}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review the latest stable caption result.")
    parser.add_argument("--work-dir", default=str(ROOT / "work-dir"))
    parser.add_argument("--sample", default="")
    args = parser.parse_args()
    manifest = newest_manifest(Path(args.work_dir), args.sample)
    print(build_review(manifest))


if __name__ == "__main__":
    main()
