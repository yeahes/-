"""Local, word-ledger-backed editing for completed stable subtitle outputs.

This module is deliberately downstream of the generation pipeline.  It never
calls ASR or an LLM.  A manual boundary move is represented as a transfer of a
continuous original word range between adjacent final cues, so the resulting
times can be recovered from the frozen word ledger instead of guessed from
text length.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from app.core.bk_asr.asr_data import ASRData
from app.core.subtitle_processor.stable_pipeline_contracts import stable_payload_hash


class ManualFinalSubtitleEditError(ValueError):
    """Raised when an edit cannot be traced to the immutable word ledger."""


@dataclass
class ManualFinalSubtitleSession:
    """A mutable presentation layer over immutable final-word provenance."""

    subtitle_path: Path
    manifest_path: Path
    artifact_dir: Path
    word_ledger: List[Dict[str, Any]]
    cues: List[Dict[str, Any]]
    source_word_ledger_hash: str
    history: List[Dict[str, Any]]

    @classmethod
    def load_for_subtitle(
        cls,
        subtitle_path: str | Path,
        *,
        work_dir: str | Path | None = None,
        manifest_path: str | Path | None = None,
    ) -> "ManualFinalSubtitleSession":
        source_path = Path(subtitle_path).resolve()
        resolved_manifest_path = (
            Path(manifest_path).resolve()
            if manifest_path
            else cls._find_manifest_for_subtitle(source_path, work_dir)
        )
        if resolved_manifest_path is None or not resolved_manifest_path.exists():
            raise ManualFinalSubtitleEditError(
                "找不到与此字幕对应的稳定产物，无法按词级时间调整边界。"
            )
        manifest = cls._read_json(resolved_manifest_path)
        override = manifest.get("manual_final_override") or {}
        override_text = str(override.get("subtitle_path") or "")
        edit_artifact_text = str(override.get("edit_artifact_path") or "")
        override_path = Path(override_text) if override_text else None
        edit_artifact_path = Path(edit_artifact_text) if edit_artifact_text else None
        if (
            override_path is not None
            and edit_artifact_path is not None
            and override_path.exists()
            and cls._same_path(source_path, override_path)
            and edit_artifact_path.exists()
        ):
            return cls._load_saved_session(source_path, resolved_manifest_path, edit_artifact_path)

        artifact_dir = cls._artifact_dir_for_manifest(resolved_manifest_path, manifest)
        spans = cls._read_json(artifact_dir / "subtitle-spans.json")
        ledger_payload = cls._read_json(artifact_dir / "word-ledger.json")
        word_ledger = list(ledger_payload.get("words") or [])
        if not spans or not word_ledger:
            raise ManualFinalSubtitleEditError("稳定产物缺少字幕词范围或词级时间账本。")

        source_data = ASRData.from_subtitle_file(str(source_path))
        if len(source_data.segments) != len(spans):
            raise ManualFinalSubtitleEditError(
                "当前字幕条数与稳定产物不一致，拒绝用错误词级账本修改时间轴。"
            )
        cues = cls._build_cues(source_data, spans, word_ledger)
        return cls(
            subtitle_path=source_path,
            manifest_path=resolved_manifest_path,
            artifact_dir=artifact_dir,
            word_ledger=word_ledger,
            cues=cues,
            source_word_ledger_hash=stable_payload_hash(cls._ledger_payload(word_ledger)),
            history=[],
        )

    @classmethod
    def load_from_manifest(cls, manifest_path: str | Path) -> "ManualFinalSubtitleSession":
        manifest_file = Path(manifest_path).resolve()
        manifest = cls._read_json(manifest_file)
        override = manifest.get("manual_final_override") or {}
        source_paths = manifest.get("source_subtitle_paths") or {}
        subtitle_text = str(
            override.get("subtitle_path")
            or source_paths.get("bilingual_original_top_srt")
            or (manifest.get("paths") or {}).get("original_top_srt")
            or ""
        )
        subtitle_path = Path(subtitle_text)
        if not subtitle_path.exists():
            raise ManualFinalSubtitleEditError("稳定终稿字幕文件不存在。")
        return cls.load_for_subtitle(subtitle_path, manifest_path=manifest_file)

    @staticmethod
    def _read_json(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManualFinalSubtitleEditError(f"无法读取稳定产物：{path}") from exc

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        try:
            return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))
        except OSError:
            return os.path.normcase(str(left)) == os.path.normcase(str(right))

    @classmethod
    def _find_manifest_for_subtitle(
        cls, subtitle_path: Path, work_dir: str | Path | None
    ) -> Path | None:
        direct = subtitle_path.parent / "stable-final-manifest.json"
        if direct.exists():
            return direct
        if not work_dir:
            return None
        root = Path(work_dir)
        if not root.exists():
            return None
        matches = []
        for manifest_path in root.rglob("stable-final-manifest.json"):
            try:
                manifest = cls._read_json(manifest_path)
            except ManualFinalSubtitleEditError:
                continue
            paths = list((manifest.get("paths") or {}).values())
            paths.extend((manifest.get("source_subtitle_paths") or {}).values())
            override = manifest.get("manual_final_override") or {}
            if override.get("subtitle_path"):
                paths.append(override["subtitle_path"])
            if any(cls._same_path(subtitle_path, Path(str(path))) for path in paths if path):
                matches.append(manifest_path)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ManualFinalSubtitleEditError("找到多个对应的稳定产物，请从音频目录打开最新双语字幕。")
        return None

    @classmethod
    def _artifact_dir_for_manifest(cls, manifest_path: Path, manifest: Mapping[str, Any]) -> Path:
        coverage_path = Path(str(manifest.get("coverage_report") or ""))
        if coverage_path.name:
            stem = coverage_path.stem.removesuffix("-coverage-report")
            candidate = coverage_path.with_name(f"{stem}-artifacts")
            if (candidate / "subtitle-spans.json").exists():
                return candidate
        candidates = [
            path for path in manifest_path.parent.glob("*-artifacts")
            if (path / "subtitle-spans.json").exists()
        ]
        if len(candidates) == 1:
            return candidates[0]
        raise ManualFinalSubtitleEditError("找不到唯一的稳定字幕 artifacts 目录。")

    @classmethod
    def _build_cues(
        cls,
        data: ASRData,
        spans: Sequence[Mapping[str, Any]],
        ledger: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        cues = []
        for index, (segment, span) in enumerate(zip(data.segments, spans), 1):
            try:
                word_start = int(span.get("word_start"))
                word_end = int(span.get("word_end"))
            except (TypeError, ValueError) as exc:
                raise ManualFinalSubtitleEditError(f"第 {index} 条没有有效词范围。") from exc
            if word_start < 0 or word_end < word_start or word_end >= len(ledger):
                raise ManualFinalSubtitleEditError(f"第 {index} 条词范围超出词级账本。")
            expected = cls._words_text(ledger, word_start, word_end)
            if cls._normalised_tokens(segment.text) != cls._normalised_tokens(expected):
                raise ManualFinalSubtitleEditError(
                    f"第 {index} 条英文与冻结词级账本不一致，不能安全移动边界。"
                )
            subtitle_id = str(span.get("subtitle_id") or f"S{index:04d}")
            cues.append(
                {
                    "cue_id": subtitle_id,
                    "source_subtitle_ids": [subtitle_id],
                    "word_start": word_start,
                    "word_end": word_end,
                    "start_time": int(segment.start_time),
                    "end_time": int(segment.end_time),
                    "original_subtitle": segment.text,
                    "translated_subtitle": segment.translated_text,
                    "chinese_review_required": False,
                }
            )
        return cues

    @classmethod
    def _load_saved_session(
        cls, subtitle_path: Path, manifest_path: Path, edit_artifact_path: Path
    ) -> "ManualFinalSubtitleSession":
        payload = cls._read_json(edit_artifact_path)
        ledger = list(payload.get("word_ledger") or [])
        cues = list(payload.get("cues") or [])
        if not ledger or not cues:
            raise ManualFinalSubtitleEditError("人工终稿编辑记录不完整。")
        source_artifact_text = str(payload.get("source_artifact_dir") or "").strip()
        source_artifact_path = Path(source_artifact_text) if source_artifact_text else None
        if source_artifact_path is None or not source_artifact_path.exists():
            manifest = cls._read_json(manifest_path)
            source_artifact_path = cls._artifact_dir_for_manifest(manifest_path, manifest)
        session = cls(
            subtitle_path=subtitle_path,
            manifest_path=manifest_path,
            artifact_dir=source_artifact_path,
            word_ledger=ledger,
            cues=cues,
            source_word_ledger_hash=str(payload.get("source_word_ledger_hash") or ""),
            history=list(payload.get("history") or []),
        )
        session._validate_cues()
        return session

    @staticmethod
    def _ledger_payload(ledger: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "surface": str(word.get("surface", word.get("token", "")) or ""),
                "start_ms": int(word.get("start_ms", word.get("start_time", 0)) or 0),
                "end_ms": int(word.get("end_ms", word.get("end_time", 0)) or 0),
            }
            for word in ledger
        ]

    @staticmethod
    def _normalised_tokens(text: str) -> List[str]:
        return [
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", str(text or ""))
        ]

    @classmethod
    def _words_text(cls, ledger: Sequence[Mapping[str, Any]], start: int, end: int) -> str:
        return " ".join(
            str(word.get("surface", word.get("token", "")) or "").strip()
            for word in ledger[start : end + 1]
        ).strip()

    def _word_start_time(self, index: int) -> int:
        word = self.word_ledger[index]
        return int(word.get("start_ms", word.get("start_time", 0)) or 0)

    def _word_end_time(self, index: int) -> int:
        word = self.word_ledger[index]
        return int(word.get("end_ms", word.get("end_time", 0)) or 0)

    def _ensure_unmodified_english(self, cue: Mapping[str, Any]) -> None:
        expected = self._words_text(self.word_ledger, int(cue["word_start"]), int(cue["word_end"]))
        if self._normalised_tokens(cue.get("original_subtitle", "")) != self._normalised_tokens(expected):
            raise ManualFinalSubtitleEditError(
                "该行英文已被自由修改，无法再按原始词级账本移动边界。"
            )

    def _record_history(self, operation: str, before: Sequence[Mapping[str, Any]], **details: Any) -> None:
        self.history.append(
            {
                "operation": operation,
                "at": datetime.now().isoformat(timespec="seconds"),
                "before_cues": copy.deepcopy(list(before)),
                **details,
            }
        )

    def _validate_cues(self) -> None:
        previous_word_end = -1
        previous_end_time = -1
        for index, cue in enumerate(self.cues, 1):
            start = int(cue.get("word_start", -1))
            end = int(cue.get("word_end", -1))
            start_time = int(cue.get("start_time", -1))
            end_time = int(cue.get("end_time", -1))
            if start != previous_word_end + 1 or end < start or end >= len(self.word_ledger):
                raise ManualFinalSubtitleEditError(f"第 {index} 条的词范围不连续。")
            if start_time < 0 or end_time <= start_time or start_time < previous_end_time:
                raise ManualFinalSubtitleEditError(f"第 {index} 条的时间轴无效或重叠。")
            previous_word_end = end
            previous_end_time = end_time

    def move_suffix_to_next(self, left_index: int, word_count: int) -> None:
        if left_index < 0 or left_index + 1 >= len(self.cues):
            raise ManualFinalSubtitleEditError("只能把末尾词移动到紧邻的下一条字幕。")
        if word_count <= 0:
            raise ManualFinalSubtitleEditError("移动词数必须大于零。")
        left = self.cues[left_index]
        right = self.cues[left_index + 1]
        self._ensure_unmodified_english(left)
        self._ensure_unmodified_english(right)
        boundary = int(left["word_end"]) - int(word_count) + 1
        if boundary <= int(left["word_start"]):
            raise ManualFinalSubtitleEditError("不能把一条字幕的全部英文词移动到下一条。")
        if boundary != int(right["word_start"]) - int(word_count):
            raise ManualFinalSubtitleEditError("两条字幕的原始词范围不连续，不能安全移动。")
        before = copy.deepcopy([left, right])
        left["word_end"] = boundary - 1
        right["word_start"] = boundary
        left["original_subtitle"] = self._words_text(
            self.word_ledger, int(left["word_start"]), int(left["word_end"])
        )
        right["original_subtitle"] = self._words_text(
            self.word_ledger, int(right["word_start"]), int(right["word_end"])
        )
        left["end_time"] = self._word_end_time(int(left["word_end"]))
        right["start_time"] = self._word_start_time(int(right["word_start"]))
        left["chinese_review_required"] = True
        right["chinese_review_required"] = True
        self._validate_cues()
        self._record_history(
            "move_suffix_to_next",
            before,
            left_index=left_index,
            word_count=word_count,
            new_boundary_word_index=boundary,
        )

    def move_prefix_to_previous(self, right_index: int, word_count: int) -> None:
        if right_index <= 0 or right_index >= len(self.cues):
            raise ManualFinalSubtitleEditError("只能把开头词移动到紧邻的上一条字幕。")
        if word_count <= 0:
            raise ManualFinalSubtitleEditError("移动词数必须大于零。")
        left = self.cues[right_index - 1]
        right = self.cues[right_index]
        self._ensure_unmodified_english(left)
        self._ensure_unmodified_english(right)
        boundary = int(right["word_start"]) + int(word_count)
        if boundary > int(right["word_end"]):
            raise ManualFinalSubtitleEditError("不能把一条字幕的全部英文词移动到上一条。")
        if boundary != int(left["word_end"]) + int(word_count) + 1:
            raise ManualFinalSubtitleEditError("两条字幕的原始词范围不连续，不能安全移动。")
        before = copy.deepcopy([left, right])
        left["word_end"] = boundary - 1
        right["word_start"] = boundary
        left["original_subtitle"] = self._words_text(
            self.word_ledger, int(left["word_start"]), int(left["word_end"])
        )
        right["original_subtitle"] = self._words_text(
            self.word_ledger, int(right["word_start"]), int(right["word_end"])
        )
        left["end_time"] = self._word_end_time(int(left["word_end"]))
        right["start_time"] = self._word_start_time(int(right["word_start"]))
        left["chinese_review_required"] = True
        right["chinese_review_required"] = True
        self._validate_cues()
        self._record_history(
            "move_prefix_to_previous",
            before,
            right_index=right_index,
            word_count=word_count,
            new_boundary_word_index=boundary,
        )

    def merge_adjacent(self, first_index: int, last_index: int) -> None:
        if first_index < 0 or last_index >= len(self.cues) or first_index >= last_index:
            raise ManualFinalSubtitleEditError("请选择至少两条相邻字幕进行合并。")
        selected = self.cues[first_index : last_index + 1]
        for left, right in zip(selected, selected[1:]):
            if int(left["word_end"]) + 1 != int(right["word_start"]):
                raise ManualFinalSubtitleEditError("选中的字幕词范围不连续，不能安全合并。")
        before = copy.deepcopy(selected)
        merged = {
            "cue_id": str(selected[0]["cue_id"]),
            "source_subtitle_ids": [
                source_id for cue in selected for source_id in cue.get("source_subtitle_ids", [])
            ],
            "word_start": int(selected[0]["word_start"]),
            "word_end": int(selected[-1]["word_end"]),
            "start_time": int(selected[0]["start_time"]),
            "end_time": int(selected[-1]["end_time"]),
            "original_subtitle": self._words_text(
                self.word_ledger,
                int(selected[0]["word_start"]),
                int(selected[-1]["word_end"]),
            ),
            "translated_subtitle": "".join(
                str(cue.get("translated_subtitle") or "") for cue in selected
            ),
            "chinese_review_required": any(
                bool(cue.get("chinese_review_required")) for cue in selected
            ),
        }
        self.cues[first_index : last_index + 1] = [merged]
        self._validate_cues()
        self._record_history(
            "merge_adjacent",
            before,
            first_index=first_index,
            last_index=last_index,
        )

    def undo(self) -> bool:
        if not self.history:
            return False
        entry = self.history.pop()
        before = list(entry.get("before_cues") or [])
        if not before:
            return False
        if entry["operation"] == "move_suffix_to_next":
            start = int(entry["left_index"])
            self.cues[start : start + 2] = before
        elif entry["operation"] == "move_prefix_to_previous":
            start = int(entry["right_index"]) - 1
            self.cues[start : start + 2] = before
        elif entry["operation"] == "merge_adjacent":
            start = int(entry["first_index"])
            self.cues[start : start + 1] = before
        else:
            return False
        self._validate_cues()
        return True

    def to_model_data(self) -> Dict[str, Dict[str, Any]]:
        return {
            str(index): {
                "start_time": int(cue["start_time"]),
                "end_time": int(cue["end_time"]),
                "original_subtitle": str(cue["original_subtitle"]),
                "translated_subtitle": str(cue.get("translated_subtitle") or ""),
                "manual_cue_id": str(cue.get("cue_id") or ""),
                "source_subtitle_ids": list(cue.get("source_subtitle_ids") or []),
                "word_start": int(cue["word_start"]),
                "word_end": int(cue["word_end"]),
                "chinese_review_required": bool(cue.get("chinese_review_required")),
            }
            for index, cue in enumerate(self.cues, 1)
        }

    def save_to_source_folder(self) -> Dict[str, str]:
        source_dir = self.subtitle_path.parent
        srt_path = source_dir / "人工终稿字幕.srt"
        edit_path = source_dir / "人工终稿字幕-edits.json"
        self._write_bilingual_srt(srt_path)
        edit_payload = {
            "schema_version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_subtitle": str(self.subtitle_path),
            "source_artifact_dir": str(self.artifact_dir),
            "source_word_ledger_hash": self.source_word_ledger_hash,
            "word_ledger": self.word_ledger,
            "cues": self.cues,
            "history": self.history,
        }
        edit_path.write_text(json.dumps(edit_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = self._read_json(self.manifest_path)
        manifest["manual_final_override"] = {
            "schema_version": 1,
            "subtitle_path": str(srt_path),
            "edit_artifact_path": str(edit_path),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "source_word_ledger_hash": self.source_word_ledger_hash,
            "manual_cue_count": len(self.cues),
            "chinese_review_required_count": sum(
                bool(cue.get("chinese_review_required")) for cue in self.cues
            ),
        }
        self._write_json_atomic(self.manifest_path, manifest)
        return {"subtitle_path": str(srt_path), "edit_artifact_path": str(edit_path)}

    def _write_bilingual_srt(self, path: Path) -> None:
        lines = []
        for index, cue in enumerate(self.cues, 1):
            lines.extend(
                [
                    str(index),
                    f"{self._srt_timestamp(cue['start_time'])} --> {self._srt_timestamp(cue['end_time'])}",
                    str(cue["original_subtitle"]),
                ]
            )
            if cue.get("translated_subtitle"):
                lines.append(str(cue["translated_subtitle"]))
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8-sig")

    @staticmethod
    def _srt_timestamp(value: int) -> str:
        milliseconds = max(0, int(value))
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(milliseconds, 1_000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    @staticmethod
    def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
