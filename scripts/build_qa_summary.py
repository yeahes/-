import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_artifact_dir() -> Path:
    candidates = sorted(
        (ROOT / "work-dir").glob("*/subtitle/*artifacts"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No artifact directory found under work-dir/*/subtitle/*artifacts")
    return candidates[0]


def _subtitle_id_sort_key(subtitle_id: str) -> tuple[int, str]:
    match = re.search(r"S(\d+)", subtitle_id or "")
    return (int(match.group(1)) if match else 10**9, subtitle_id or "")


def _ids_from_payload(payload: Any) -> list[str]:
    found: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {
                    "subtitle_id",
                    "left_subtitle_id",
                    "right_subtitle_id",
                    "expected_subtitle_id",
                } and isinstance(item, str):
                    found.add(item)
                elif key in {
                    "subtitle_ids",
                    "expected_subtitle_ids",
                    "returned_subtitle_ids",
                    "mapped_subtitle_ids",
                    "missing_subtitle_ids",
                    "duplicate_subtitle_ids",
                    "unknown_subtitle_ids",
                    "actual_subtitle_ids",
                } and isinstance(item, list):
                    found.update(str(entry) for entry in item if isinstance(entry, str))
                if isinstance(key, str) and re.fullmatch(r"S\d{4}", key):
                    found.add(key)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    return sorted((item for item in found if re.fullmatch(r"S\d{4}", item)), key=_subtitle_id_sort_key)


def _group_ids_from_payload(payload: Any) -> list[str]:
    found: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "semantic_group_id" and isinstance(item, str):
                    found.add(item)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    return sorted(found)


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text or ""))


def _ms_to_srt(ms: int | None) -> str:
    if ms is None:
        return ""
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _normal_text(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class QASummaryBuilder:
    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir
        self.subtitle_dir = artifact_dir.parent
        self.manifest = _load_json(artifact_dir / "run-manifest.json", {})
        self.validation = _load_json(artifact_dir / "validation-report.json", {})
        self.translation_errors = _load_json(artifact_dir / "translation-structure-errors.json", [])
        self.allocation_unresolved = _load_json(artifact_dir / "allocation-unresolved.json", [])
        self.allocation_retry_log = _load_json(artifact_dir / "allocation-retry-log.json", [])
        self.spans = _load_json(artifact_dir / "subtitle-spans.json", [])
        self.translations = _load_json(artifact_dir / "translations.json", [])
        self.by_id = self._build_subtitle_index()

    def _build_subtitle_index(self) -> dict[str, dict]:
        records: dict[str, dict] = {}
        for index, item in enumerate(self.spans, 1):
            subtitle_id = str(item.get("subtitle_id") or f"S{index:04d}")
            records[subtitle_id] = {
                "subtitle_id": subtitle_id,
                "index": index,
                "start_ms": item.get("start_ms"),
                "end_ms": item.get("end_ms"),
                "english": _normal_text(item, "original", "text", "english"),
                "chinese": _normal_text(item, "translated", "translated_text", "zh"),
            }
        for index, item in enumerate(self.translations, 1):
            subtitle_id = str(item.get("subtitle_id") or f"S{index:04d}")
            record = records.setdefault(
                subtitle_id,
                {"subtitle_id": subtitle_id, "index": index, "english": "", "chinese": ""},
            )
            record["start_ms"] = record.get("start_ms", item.get("start_ms"))
            record["end_ms"] = record.get("end_ms", item.get("end_ms"))
            record["english"] = record.get("english") or _normal_text(item, "text", "original", "english")
            record["chinese"] = _normal_text(item, "translated_text", "translated", "zh") or record.get("chinese", "")
        return records

    def build(self) -> dict:
        items: list[dict] = []
        items.extend(self._structure_items())
        items.extend(self._validation_items())
        items.extend(self._allocation_items())
        items.extend(self._local_boundary_items())
        items.sort(key=lambda item: (self._severity_rank(item["severity"]), _subtitle_id_sort_key((item.get("subtitle_ids") or [""])[0]), item["code"]))
        counts = {"BLOCKER": 0, "REVIEW": 0, "INFO": 0}
        for item in items:
            counts[item["severity"]] = counts.get(item["severity"], 0) + 1
        return {
            "schema_version": 1,
            "artifact_dir": str(self.artifact_dir),
            "subtitle_dir": str(self.subtitle_dir),
            "summary": {
                "status": "BLOCKED" if counts["BLOCKER"] else ("REVIEW" if counts["REVIEW"] else "PASS"),
                "blocker_count": counts["BLOCKER"],
                "review_count": counts["REVIEW"],
                "info_count": counts["INFO"],
                "subtitle_count": self.manifest.get("subtitle_count") or len(self.by_id),
                "translation_structure_error_count": len(self.translation_errors),
                "allocation_unresolved_count": len(self.allocation_unresolved),
                "translation_model": self.manifest.get("translation_model") or self.manifest.get("model"),
                "code_commit": self.manifest.get("code_commit"),
                "cache_used": self.manifest.get("cache_used"),
            },
            "items": items,
        }

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {"BLOCKER": 0, "REVIEW": 1, "INFO": 2}.get(severity, 9)

    def _context_for_ids(self, subtitle_ids: list[str]) -> list[dict]:
        context = []
        for subtitle_id in subtitle_ids:
            record = self.by_id.get(subtitle_id, {})
            context.append(
                {
                    "subtitle_id": subtitle_id,
                    "time": self._time_for_record(record),
                    "english": record.get("english", ""),
                    "chinese": record.get("chinese", ""),
                    "word_count": _word_count(record.get("english", "")),
                }
            )
        return context

    @staticmethod
    def _time_for_record(record: dict) -> str:
        start = record.get("start_ms")
        end = record.get("end_ms")
        if start is None or end is None:
            return ""
        return f"{_ms_to_srt(start)} --> {_ms_to_srt(end)}"

    def _make_item(
        self,
        *,
        severity: str,
        code: str,
        title: str,
        reason: str,
        subtitle_ids: list[str],
        source: str,
        semantic_group_ids: list[str] | None = None,
        details: dict | None = None,
    ) -> dict:
        return {
            "severity": severity,
            "code": code,
            "title": title,
            "reason": reason,
            "subtitle_ids": sorted(set(subtitle_ids), key=_subtitle_id_sort_key),
            "semantic_group_ids": semantic_group_ids or [],
            "source": source,
            "details": details or {},
            "context": self._context_for_ids(sorted(set(subtitle_ids), key=_subtitle_id_sort_key)[:6]),
        }

    def _structure_items(self) -> list[dict]:
        if not self.translation_errors:
            return []
        grouped: dict[str, list[dict]] = {}
        for error in self.translation_errors:
            grouped.setdefault(str(error.get("code") or "translation_structure_error"), []).append(error)
        return [
            self._make_item(
                severity="BLOCKER",
                code=code,
                title=f"结构门禁错误：{code}",
                reason="英文 subtitle_id 与中文返回 ID 不一致，必须阻止最终渲染。",
                subtitle_ids=_ids_from_payload(errors),
                semantic_group_ids=_group_ids_from_payload(errors),
                source="translation-structure-errors.json",
                details={"count": len(errors), "first": errors[:3]},
            )
            for code, errors in grouped.items()
        ]

    def _validation_items(self) -> list[dict]:
        result: list[dict] = []
        for level, severity in (("errors", "BLOCKER"), ("warnings", "REVIEW")):
            for group in self.validation.get(level, []) or []:
                code = str(group.get("code") or "validation_item")
                source_severity = severity
                if code in {"suspicious_cut", "syntax_boundary_audit"}:
                    source_severity = "INFO"
                items = group.get("items") if isinstance(group.get("items"), list) else [group]
                max_items = 12 if source_severity == "REVIEW" else 8
                for entry in items[:max_items]:
                    subtitle_ids = _ids_from_payload(entry)
                    if not subtitle_ids:
                        subtitle_ids = self._ids_by_english_pair(entry)
                    result.append(
                        self._make_item(
                            severity=source_severity,
                            code=code,
                            title=self._validation_title(code, entry, group),
                            reason=str(entry.get("reason") or group.get("message") or ""),
                            subtitle_ids=subtitle_ids,
                            semantic_group_ids=_group_ids_from_payload(entry),
                            source="validation-report.json",
                            details={k: v for k, v in entry.items() if k not in {"original", "translated"}},
                        )
                    )
        return result

    def _ids_by_english_pair(self, entry: dict) -> list[str]:
        texts = [entry.get("original"), entry.get("previous"), entry.get("current")]
        found = []
        for subtitle_id, record in self.by_id.items():
            english = record.get("english", "")
            if english and any(isinstance(text, str) and text.strip() == english for text in texts):
                found.append(subtitle_id)
        return sorted(found, key=_subtitle_id_sort_key)

    def _allocation_items(self) -> list[dict]:
        result = []
        for record in self.allocation_unresolved:
            issue_codes = [str(code) for code in record.get("issue_codes") or []]
            subtitle_ids = _ids_from_payload(record.get("allocation")) or _ids_from_payload(record)
            result.append(
                self._make_item(
                    severity="REVIEW",
                    code="allocation_quality_unresolved",
                    title="中文逐条分配未完全解决",
                    reason=f"{record.get('reason', '')}; issues={', '.join(issue_codes)}",
                    subtitle_ids=subtitle_ids,
                    semantic_group_ids=_group_ids_from_payload(record),
                    source="allocation-unresolved.json",
                    details={
                        "issue_codes": issue_codes,
                        "full_english": record.get("full_english", ""),
                        "full_translation": record.get("full_translation", ""),
                    },
                )
            )
        for record in self.allocation_retry_log:
            comparison = record.get("quality_comparison") or {}
            if comparison.get("decision") != "keep_original":
                continue
            result.append(
                self._make_item(
                    severity="INFO",
                    code="allocation_retry_rejected",
                    title="allocation retry 已拒绝并保留原结果",
                    reason=", ".join(comparison.get("reasons") or []) or str(record.get("reason_codes") or ""),
                    subtitle_ids=_ids_from_payload(record.get("original_allocation")) or _ids_from_payload(record),
                    semantic_group_ids=_group_ids_from_payload(record),
                    source="allocation-retry-log.json",
                    details={
                        "original_issue_codes": comparison.get("original_issue_codes", []),
                        "retry_issue_codes": comparison.get("retry_issue_codes", []),
                    },
                )
            )
        return result

    def _local_boundary_items(self) -> list[dict]:
        result = []
        marker_only = re.compile(r"^(?:i mean|you know|i guess|well,? i mean|though)[, .!?]*$", re.I)
        tail_marker = re.compile(r"(?:,|\b)(?:i mean|you know|i guess|though)[, .!?]*$", re.I)
        independent = re.compile(r"^(?:why|yes|no|yeah|right|really|exactly|okay|ok|wow|sure)[,.!? ]*$", re.I)
        for subtitle_id, record in sorted(self.by_id.items(), key=lambda item: _subtitle_id_sort_key(item[0])):
            english = record.get("english", "")
            words = _word_count(english)
            if marker_only.match(english):
                result.append(
                    self._make_item(
                        severity="REVIEW",
                        code="discourse_marker_only",
                        title="英文口头标记单独成条",
                        reason="I mean / you know / I guess / though 不应单独作为普通字幕。",
                        subtitle_ids=[subtitle_id],
                        source="subtitle-spans.json",
                    )
                )
            elif tail_marker.search(english) and not marker_only.match(english):
                result.append(
                    self._make_item(
                        severity="INFO",
                        code="discourse_marker_tail",
                        title="英文口头标记悬在句尾",
                        reason="可人工判断是否需要和后句重排；当前不阻断成片。",
                        subtitle_ids=[subtitle_id],
                        source="subtitle-spans.json",
                    )
                )
            elif words <= 2 and not independent.match(english):
                result.append(
                    self._make_item(
                        severity="INFO",
                        code="very_short_non_answer",
                        title="极短英文字幕",
                        reason="不是明确独立回答时，可能需要人工看一眼切分。",
                        subtitle_ids=[subtitle_id],
                        source="subtitle-spans.json",
                    )
                )
        return result

    @staticmethod
    def _validation_title(code: str, entry: dict, group: dict) -> str:
        titles = {
            "reading_speed_error": "阅读速度严重超限",
            "reading_speed_warning": "阅读速度偏快",
            "asr_suspicious": "ASR 可疑文本",
            "chinese_semantic_group_warning": "中文语义/流畅度可疑",
            "suspicious_cut": "英文切点可疑",
            "syntax_boundary_audit": "英文句法边界可疑",
            "duplicate_chinese": "相邻中文字幕可能重复",
            "subtitle_duration_short_warning": "字幕显示时间偏短",
            "subtitle_duration_invalid": "字幕显示时间过短",
        }
        title = titles.get(code, str(group.get("message") or code))
        subtitle_id = entry.get("subtitle_id")
        if isinstance(subtitle_id, str):
            return f"{title}：{subtitle_id}"
        return title


def _markdown(summary: dict) -> str:
    lines = []
    meta = summary["summary"]
    lines.append("# Subtitle QA Summary")
    lines.append("")
    lines.append(f"- Status: `{meta['status']}`")
    lines.append(f"- Model: `{meta.get('translation_model')}`")
    lines.append(f"- Commit: `{meta.get('code_commit')}`")
    lines.append(f"- Subtitle count: `{meta.get('subtitle_count')}`")
    lines.append(f"- Blocker / Review / Info: `{meta['blocker_count']} / {meta['review_count']} / {meta['info_count']}`")
    lines.append(f"- Artifact dir: `{summary['artifact_dir']}`")
    lines.append("")
    for severity in ("BLOCKER", "REVIEW", "INFO"):
        items = [item for item in summary["items"] if item["severity"] == severity]
        lines.append(f"## {severity} ({len(items)})")
        if not items:
            lines.append("")
            lines.append("None.")
            lines.append("")
            continue
        for index, item in enumerate(items, 1):
            ids = ", ".join(item.get("subtitle_ids") or []) or "-"
            groups = ", ".join(item.get("semantic_group_ids") or []) or "-"
            lines.append("")
            lines.append(f"### {index}. {item['title']}")
            lines.append(f"- Code: `{item['code']}`")
            lines.append(f"- IDs: `{ids}`")
            lines.append(f"- Groups: `{groups}`")
            lines.append(f"- Source: `{item['source']}`")
            lines.append(f"- Reason: {item.get('reason') or '-'}")
            for context in item.get("context") or []:
                lines.append(f"- {context['subtitle_id']} `{context.get('time')}`")
                if context.get("english"):
                    lines.append(f"  - EN: {context['english']}")
                if context.get("chinese"):
                    lines.append(f"  - ZH: {context['chinese']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a human-readable subtitle QA summary from stable artifacts.")
    parser.add_argument("--artifact-dir", type=Path, default=None)
    args = parser.parse_args()
    artifact_dir = args.artifact_dir or _latest_artifact_dir()
    builder = QASummaryBuilder(artifact_dir)
    summary = builder.build()
    json_path = artifact_dir / "qa-summary.json"
    md_path = artifact_dir / "qa-summary.md"
    _write_json(json_path, summary)
    md_path.write_text(_markdown(summary), encoding="utf-8")
    print(json.dumps({"qa_summary": str(json_path), "qa_markdown": str(md_path), **summary["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
