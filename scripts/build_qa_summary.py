import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_console(text: str) -> None:
    """Do not fail a completed QA run when a legacy filename has unsupported characters."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding)
        print(safe_text)


def _latest_artifact_dir() -> Path:
    candidates = sorted(
        (ROOT / "work-dir").glob("*/subtitle/*artifacts"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No artifact directory found under work-dir/*/subtitle/*artifacts")
    return candidates[0]


def _resolve_artifact_dir(path: Path) -> Path:
    """Accept either a stable artifacts directory or its parent subtitle directory."""
    candidate = path.expanduser().resolve()
    if (candidate / "run-manifest.json").is_file():
        return candidate

    children = [
        child
        for child in candidate.iterdir()
        if child.is_dir() and (child / "run-manifest.json").is_file()
    ] if candidate.is_dir() else []
    if children:
        return max(children, key=lambda child: child.stat().st_mtime)

    raise FileNotFoundError(
        "Could not find run-manifest.json. Provide a stable artifacts directory "
        "or the subtitle directory that contains one."
    )


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
        self.final_timeline = _load_json(artifact_dir / "final-cue-timeline.json", {})
        self.word_ledger = _load_json(artifact_dir / "word-ledger.json", {})
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
            if record.get("start_ms") is None:
                record["start_ms"] = item.get("start_ms")
            if record.get("end_ms") is None:
                record["end_ms"] = item.get("end_ms")
            record["english"] = record.get("english") or _normal_text(item, "text", "original", "english")
            record["chinese"] = _normal_text(item, "translated_text", "translated", "zh") or record.get("chinese", "")
        timeline_records = self.final_timeline.get("records") if isinstance(self.final_timeline, dict) else []
        for item in timeline_records or []:
            if not isinstance(item, dict):
                continue
            subtitle_id = str(item.get("subtitle_id") or "")
            record = records.get(subtitle_id)
            if record is None:
                continue
            record["start_ms"] = item.get("start_ms", record.get("start_ms"))
            record["end_ms"] = item.get("end_ms", record.get("end_ms"))
            record["word_start"] = item.get("word_start")
            record["word_end"] = item.get("word_end")
            record["word_alignment_sources"] = list(item.get("word_alignment_sources") or [])
        return records

    def build(self) -> dict:
        items: list[dict] = []
        items.extend(self._structure_items())
        items.extend(self._validation_items())
        items.extend(self._allocation_items())
        items.extend(self._local_boundary_items())
        items.extend(self._timeline_alignment_items())
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
                "timeline_alignment_backend": self._timeline_alignment_backend(),
                "timeline_fallback_cue_count": sum(
                    1
                    for item in items
                    if item.get("code") == "timeline_alignment_fallback"
                ),
                "timeline_contract_error_count": sum(
                    1
                    for item in items
                    if item.get("code") == "final_cue_timeline_invalid"
                ),
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
                    "start_ms": record.get("start_ms"),
                    "end_ms": record.get("end_ms"),
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
                if code == "suspicious_cut":
                    source_severity = "INFO"
                items = group.get("items") if isinstance(group.get("items"), list) else [group]
                for entry in items:
                    entry_severity = source_severity
                    if code == "syntax_boundary_audit":
                        entry_severity = (
                            "REVIEW"
                            if entry.get("classification") == "review"
                            else "INFO"
                        )
                    if (
                        code == "chinese_semantic_group_warning"
                        and entry.get("mapping_valid") is False
                    ):
                        entry_severity = "INFO"
                    subtitle_ids = _ids_from_payload(entry)
                    if not subtitle_ids:
                        subtitle_ids = self._ids_by_english_pair(entry)
                    result.append(
                        self._make_item(
                            severity=entry_severity,
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

    def _timeline_alignment_backend(self) -> str:
        if not isinstance(self.final_timeline, dict):
            return ""
        alignment = self.final_timeline.get("alignment") or {}
        return str(alignment.get("applied_backend") or alignment.get("requested_backend") or "")

    def _timeline_alignment_items(self) -> list[dict]:
        """Surface only direct timing-evidence limitations for human review.

        A cue is not considered uncertain merely because its display padding
        differs from its word envelope. The final timeline intentionally adds
        controlled lead-in and tail padding. The two cases below instead have
        direct evidence: a failed timeline contract or one or more words that
        could not be matched by WhisperX and retained stable-ts timing.
        """
        if not isinstance(self.final_timeline, dict):
            return []
        result = []
        validation = self.final_timeline.get("validation") or {}
        errors = validation.get("errors") if isinstance(validation, dict) else []
        if errors:
            result.append(
                self._make_item(
                    severity="BLOCKER",
                    code="final_cue_timeline_invalid",
                    title="最终字幕时间轴契约失败",
                    reason="最终 cue 未能完整满足冻结词账本的 ID、顺序或词时间契约。",
                    subtitle_ids=_ids_from_payload(errors),
                    source="final-cue-timeline.json",
                    details={"errors": list(errors)},
                )
            )

        word_sources = self._timeline_word_sources()
        for subtitle_id, record in sorted(self.by_id.items(), key=lambda item: _subtitle_id_sort_key(item[0])):
            sources = set(record.get("word_alignment_sources") or [])
            word_start = record.get("word_start")
            word_end = record.get("word_end")
            fallback_word_ids = []
            if isinstance(word_start, int) and isinstance(word_end, int):
                fallback_word_ids = [
                    word_id
                    for word_id in range(word_start, word_end + 1)
                    if "fallback" in word_sources.get(word_id, "").lower()
                ]
            if not fallback_word_ids and not any("fallback" in value.lower() for value in sources):
                continue
            total_words = max(1, int(word_end) - int(word_start) + 1) if isinstance(word_start, int) and isinstance(word_end, int) else 0
            result.append(
                self._make_item(
                    severity="REVIEW",
                    code="timeline_alignment_fallback",
                    title="最终时间轴含回退词",
                    reason=(
                        f"该条 {len(fallback_word_ids)}/{total_words or '?'} 个冻结词未匹配 WhisperX，"
                        "保留 stable-ts 词时间；建议试听这一条的首尾。"
                    ),
                    subtitle_ids=[subtitle_id],
                    source="final-cue-timeline.json",
                    details={
                        "word_start": word_start,
                        "word_end": word_end,
                        "fallback_word_ids": fallback_word_ids,
                        "word_alignment_sources": sorted(sources),
                        "timeline_backend": self._timeline_alignment_backend(),
                    },
                )
            )
        return result

    def _timeline_word_sources(self) -> dict[int, str]:
        if not isinstance(self.word_ledger, dict):
            return {}
        result = {}
        for position, word in enumerate(self.word_ledger.get("words") or []):
            if not isinstance(word, dict):
                continue
            try:
                word_id = int(word.get("word_id", position))
            except (TypeError, ValueError):
                continue
            result[word_id] = str(word.get("alignment_source") or "")
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


def _ms_to_srt_timestamp(ms: int) -> str:
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _review_queue_items(
    summary: dict,
    review_limit: int | None = None,
) -> tuple[list[dict], int]:
    """Keep every distinct blocker and actionable review in the playable queue."""
    selected: list[dict] = []
    review_count = 0
    normalized_limit = None if review_limit is None else max(0, int(review_limit))
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for item in summary.get("items") or []:
        severity = str(item.get("severity") or "")
        if severity not in {"BLOCKER", "REVIEW"}:
            continue
        key = (str(item.get("code") or ""), tuple(item.get("subtitle_ids") or []))
        if key in seen:
            continue
        seen.add(key)
        if severity == "REVIEW":
            review_count += 1
            if normalized_limit is not None and review_count > normalized_limit:
                continue
        selected.append(item)
    omitted = (
        max(0, review_count - normalized_limit)
        if normalized_limit is not None
        else 0
    )
    return selected, omitted


def _review_item_time_range(item: dict) -> tuple[int, int] | None:
    context = item.get("context") or []
    values = [
        (entry.get("start_ms"), entry.get("end_ms"))
        for entry in context
        if entry.get("start_ms") is not None and entry.get("end_ms") is not None
    ]
    if not values:
        return None
    start_ms = min(int(start) for start, _ in values)
    end_ms = max(int(end) for _, end in values)
    return (start_ms, max(start_ms + 1, end_ms))


def _review_queue_srt(
    summary: dict,
    review_limit: int | None = None,
) -> tuple[str, dict]:
    items, omitted = _review_queue_items(summary, review_limit=review_limit)
    blocks: list[str] = []
    written_items: list[dict] = []
    for item in items:
        time_range = _review_item_time_range(item)
        if time_range is None:
            continue
        start_ms, end_ms = time_range
        lines = [
            f"[QC][{item.get('severity', 'REVIEW')}] {item.get('title', '')}",
            f"ID: {', '.join(item.get('subtitle_ids') or []) or '-'}",
            f"原因: {item.get('reason') or '-'}",
        ]
        for context in (item.get("context") or [])[:3]:
            subtitle_id = str(context.get("subtitle_id") or "")
            english = str(context.get("english") or "").strip()
            chinese = str(context.get("chinese") or "").strip()
            if english:
                lines.append(f"{subtitle_id} EN: {english}")
            if chinese:
                lines.append(f"{subtitle_id} ZH: {chinese}")
        blocks.append(
            "\n".join(
                [
                    str(len(blocks) + 1),
                    f"{_ms_to_srt_timestamp(start_ms)} --> {_ms_to_srt_timestamp(end_ms)}",
                    *lines,
                ]
            )
        )
        written_items.append(item)
    return "\n\n".join(blocks) + ("\n" if blocks else ""), {
        "queue_item_count": len(written_items),
        "omitted_review_count": omitted,
        "review_limit": 0 if review_limit is None else max(0, int(review_limit)),
        "subtitle_ids": [
            subtitle_id
            for item in written_items
            for subtitle_id in item.get("subtitle_ids") or []
        ],
    }


def write_qa_review_artifacts(
    artifact_dir: Path,
    source_audio_dir: Path | None = None,
    review_limit: int | None = None,
) -> dict:
    """Write reproducible machine artifacts and a complete human-review SRT."""
    builder = QASummaryBuilder(artifact_dir)
    summary = builder.build()
    json_path = artifact_dir / "qa-summary.json"
    md_path = artifact_dir / "qa-summary.md"
    queue_json_path = artifact_dir / "qa-review-queue.json"
    queue_srt_path = artifact_dir / "qa-review-queue.srt"
    _write_json(json_path, summary)
    md_path.write_text(_markdown(summary), encoding="utf-8")
    queue_srt, queue_meta = _review_queue_srt(summary, review_limit=review_limit)
    queue_payload = {
        "schema_version": 1,
        "source_run": {
            "artifact_dir": str(artifact_dir),
            "code_commit": summary["summary"].get("code_commit"),
            "translation_model": summary["summary"].get("translation_model"),
            "subtitle_count": summary["summary"].get("subtitle_count"),
        },
        "queue": queue_meta,
        "items": _review_queue_items(summary, review_limit=review_limit)[0],
    }
    _write_json(queue_json_path, queue_payload)
    queue_srt_path.write_text(queue_srt, encoding="utf-8-sig")

    result = {
        "qa_summary": str(json_path),
        "qa_markdown": str(md_path),
        "qa_review_queue_json": str(queue_json_path),
        "qa_review_queue_srt": str(queue_srt_path),
        **summary["summary"],
        **queue_meta,
    }
    if source_audio_dir is not None and source_audio_dir.exists():
        source_path = source_audio_dir / "字幕质检队列.srt"
        source_path.write_text(queue_srt, encoding="utf-8-sig")
        result["source_audio_qa_review_queue_srt"] = str(source_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a human-readable subtitle QA summary from stable artifacts.")
    parser.add_argument("--artifact-dir", type=Path, default=None)
    args = parser.parse_args()
    artifact_dir = _resolve_artifact_dir(args.artifact_dir) if args.artifact_dir else _latest_artifact_dir()
    result = write_qa_review_artifacts(artifact_dir)
    _print_console(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
