"""Local, word-ledger-backed editing for completed stable subtitle outputs.

This module is deliberately downstream of the generation pipeline.  It never
calls ASR or an LLM.  A manual boundary move is represented as a transfer of a
continuous original word range between adjacent final cues, so the resulting
times can be recovered from the frozen word ledger instead of guessed from
text length.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence

from app.core.bk_asr.asr_data import ASRData
from app.config import BIN_PATH
from app.core.entities import SupportedAudioFormats, SupportedVideoFormats
from app.core.output_paths import media_result_dir
from app.core.subtitle_processor.stable_artifacts import (
    file_sha256,
    write_json_artifact,
    write_text_artifact,
)
from app.core.subtitle_processor.stable_display_page_contract import display_page_id
from app.core.subtitle_processor.stable_pipeline_contracts import stable_payload_hash
from app.core.utils.video_utils import staged_media_output


_SUBTITLE_ID_RE = re.compile(r"S\d{4,}")
_SUPPORTED_MEDIA_SUFFIXES = {
    f".{item.value}" for item in (*SupportedAudioFormats, *SupportedVideoFormats)
}


class ManualFinalSubtitleEditError(ValueError):
    """Raised when an edit cannot be traced to the immutable word ledger."""


def _materialize_tail_trim_audio(
    source_path: Path,
    output_path: Path,
    cut_ms: int,
) -> None:
    if not source_path.is_file() or int(cut_ms) <= 0:
        raise ManualFinalSubtitleEditError("尾部裁剪缺少有效的原始音频或切点。")
    ffmpeg = BIN_PATH / "ffmpeg.exe"
    if not ffmpeg.is_file():
        raise ManualFinalSubtitleEditError("找不到项目 FFmpeg，无法生成裁剪音频。")
    cut_seconds = int(cut_ms) / 1000.0
    try:
        with staged_media_output(output_path) as staged_path:
            result = subprocess.run(
                [
                    str(ffmpeg),
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source_path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-af",
                    f"atrim=start=0:end={cut_seconds:.3f},asetpts=PTS-STARTPTS",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    "-y",
                    str(staged_path),
                ],
                capture_output=True,
                text=True,
                timeout=max(60, int(cut_seconds) + 30),
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
            if result.returncode != 0:
                detail = str(result.stderr or "").strip()[-2000:]
                raise ManualFinalSubtitleEditError(
                    "FFmpeg 无法生成派生裁剪音频。"
                    + (f"（{detail}）" if detail else "")
                )
    except subprocess.TimeoutExpired as exc:
        raise ManualFinalSubtitleEditError("生成派生裁剪音频超时。") from exc


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
    display_page_edits: List[Dict[str, Any]] = field(default_factory=list)
    display_page_boundary_overrides: Dict[str, List[int]] = field(
        default_factory=dict
    )
    recovered_formal_boundary_evidence: Dict[str, Dict[str, Any]] = field(
        default_factory=dict,
        repr=False,
    )
    recovered_stale_page_drafts: Dict[str, Dict[str, Any]] = field(
        default_factory=dict,
        repr=False,
    )
    tail_trim: Dict[str, Any] = field(default_factory=dict)
    loaded_subtitle_path: Path | None = None
    source_media_path: Path | None = None
    import_notice: str = ""
    _display_page_model_cache_key: str = field(
        default="",
        init=False,
        repr=False,
        compare=False,
    )
    _display_page_model_cache: Dict[str, Dict[str, Any]] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )
    _display_page_preview_cache: Dict[str, Dict[str, Any]] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )

    @staticmethod
    def _expanded_numeric_boundary_word_count(
        word_ledger: Sequence[Mapping[str, Any]],
        *,
        left_word_start: int,
        left_word_end: int,
        right_word_start: int,
        right_word_end: int,
        requested_word_count: int,
        move_to_next: bool,
    ) -> int:
        """Expand a manual move until it no longer splits a numeric phrase."""
        requested = max(int(requested_word_count), 1)
        left_start = int(left_word_start)
        left_end = int(left_word_end)
        right_start = int(right_word_start)
        right_end = int(right_word_end)
        if left_end + 1 != right_start:
            return requested

        surfaces = [
            str(word.get("surface", word.get("token", "")) or "")
            for word in word_ledger
        ]

        def boundary_splits_numeric_phrase(boundary: int) -> bool:
            if boundary <= 0 or boundary >= len(surfaces):
                return False
            previous_surface = surfaces[boundary - 1]
            # A trailing comma/semicolon/colon is a real readable boundary
            # for a completed date or number clause (for example,
            # ``2026, the market``).  Do not let the numeric fallback absorb
            # the following article or noun just because the previous token
            # happens to be numeric.  Internal thousands separators are not
            # affected because they do not occur at the end of the surface.
            if re.search(r"[,;:!?][\"')\]]*\s*$", previous_surface):
                return False
            from app.core.utils.podcast_learning_video import (
                _looks_like_numeric_phrase_boundary,
            )

            if _looks_like_numeric_phrase_boundary(surfaces, boundary):
                return True

            def normalized(value: str) -> str:
                return re.sub(r"[^A-Za-z0-9'.]", "", value).lower()

            previous = normalized(previous_surface)
            following = normalized(surfaces[boundary])
            numeric_words = {
                "zero", "one", "two", "three", "four", "five", "six",
                "seven", "eight", "nine", "ten", "eleven", "twelve",
                "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
                "eighteen", "nineteen", "twenty", "thirty", "forty",
                "fifty", "sixty", "seventy", "eighty", "ninety",
                "hundred", "thousand", "million", "billion", "trillion",
            }
            previous_is_numeric = bool(
                re.fullmatch(r"\d+(?:[.,]\d+)?", previous)
                or previous in numeric_words
            )
            following_is_head = bool(
                following
                and following.isalpha()
                and following
                not in {
                    "and", "but", "for", "in", "of", "on", "or", "to", "with",
                }
            )
            return previous_is_numeric and following_is_head

        if move_to_next:
            source_count = left_end - left_start + 1
            count = min(requested, source_count)
            boundary = left_end - count + 1
            while boundary > left_start and boundary_splits_numeric_phrase(boundary):
                count += 1
                boundary -= 1
            return count

        source_count = right_end - right_start + 1
        count = min(requested, source_count)
        boundary = right_start + count
        while boundary <= right_end and boundary_splits_numeric_phrase(boundary):
            count += 1
            boundary += 1
        return count

    def expanded_manual_boundary_word_count(
        self,
        *,
        left_word_start: int,
        left_word_end: int,
        right_word_start: int,
        right_word_end: int,
        requested_word_count: int,
        move_to_next: bool,
    ) -> int:
        return self._expanded_numeric_boundary_word_count(
            self.word_ledger,
            left_word_start=left_word_start,
            left_word_end=left_word_end,
            right_word_start=right_word_start,
            right_word_end=right_word_end,
            requested_word_count=requested_word_count,
            move_to_next=move_to_next,
        )

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
        if resolved_manifest_path is None and not manifest_path:
            recovered = cls._recover_stale_display_page_import(
                source_path,
                work_dir=work_dir,
            )
            if recovered is not None:
                return recovered
        if resolved_manifest_path is None or not resolved_manifest_path.exists():
            raise ManualFinalSubtitleEditError(
                "找不到与此字幕对应的稳定产物，无法按词级时间调整边界。"
            )
        manifest = cls._read_json(resolved_manifest_path)
        if cls._is_manifest_display_page_subtitle(source_path, manifest):
            override = manifest.get("manual_final_override") or {}
            source_paths = manifest.get("source_subtitle_paths") or {}
            source_display_text = str(
                source_paths.get("display_page_bilingual_srt") or ""
            ).strip()
            if (
                override.get("subtitle_path")
                and source_display_text
                and cls._same_path(source_path, Path(source_display_text))
            ):
                recovered = cls._recover_stale_display_page_import(
                    source_path,
                    work_dir=work_dir,
                    current_manifest_path=resolved_manifest_path,
                )
                if recovered is not None:
                    return recovered
            parent_path = cls._display_page_parent_subtitle_path(manifest)
            if parent_path is None or not parent_path.is_file():
                raise ManualFinalSubtitleEditError(
                    "实际分页字幕缺少对应的父字幕，不能安全编辑。"
                )
            if cls._same_path(source_path, parent_path):
                raise ManualFinalSubtitleEditError("实际分页字幕映射到了自身。")
            session = cls.load_for_subtitle(
                parent_path,
                work_dir=work_dir,
                manifest_path=resolved_manifest_path,
            )
            session.loaded_subtitle_path = source_path
            return session
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
        expected_count = int(manifest.get("subtitle_count") or 0)
        if expected_count and len(spans) != expected_count:
            raise ManualFinalSubtitleEditError("稳定检查点没有包含全部固定字幕 ID。")

        source_data = ASRData.from_subtitle_file(str(source_path))
        if len(source_data.segments) != len(spans):
            raise ManualFinalSubtitleEditError(
                "当前字幕条数与稳定产物不一致，拒绝用错误词级账本修改时间轴。"
            )
        cues = cls._build_cues(source_data, spans, word_ledger)
        session = cls(
            subtitle_path=source_path,
            manifest_path=resolved_manifest_path,
            artifact_dir=artifact_dir,
            word_ledger=word_ledger,
            cues=cues,
            source_word_ledger_hash=stable_payload_hash(cls._ledger_payload(word_ledger)),
            history=[],
            loaded_subtitle_path=source_path,
            source_media_path=cls._manifest_source_media_path(
                manifest,
                resolved_manifest_path,
                source_path,
            ),
        )
        session._validate_cues()
        session._remember_known_formal_boundary_evidence()
        return session

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

    @classmethod
    def find_manifest_for_subtitle(
        cls,
        subtitle_path: str | Path,
        *,
        work_dir: str | Path | None = None,
    ) -> Path | None:
        """Resolve a trusted package for an exact subtitle path or byte copy."""
        return cls._find_manifest_for_subtitle(Path(subtitle_path).resolve(), work_dir)

    @classmethod
    def load_from_failure_record(
        cls,
        failure_path: str | Path,
    ) -> "ManualFinalSubtitleSession":
        failure_file = Path(failure_path).resolve()
        failure = cls._read_json(failure_file)
        if not failure.get("render_blocked"):
            raise ManualFinalSubtitleEditError("当前记录不是被阻止的字幕检查点。")
        manifest_text = str(
            failure.get("editable_checkpoint_manifest_path") or ""
        ).strip()
        if not manifest_text:
            raise ManualFinalSubtitleEditError("本次失败没有可编辑字幕检查点。")
        manifest_path = Path(manifest_text).resolve()
        if not manifest_path.is_file():
            raise ManualFinalSubtitleEditError("失败字幕检查点已经不存在。")
        manifest = cls._read_json(manifest_path)
        if not manifest.get("editable_checkpoint") or not manifest.get(
            "render_blocked"
        ):
            raise ManualFinalSubtitleEditError("失败字幕检查点清单无效。")
        failure_attempt_id = str(failure.get("attempt_id") or "")
        manifest_attempt_id = str(manifest.get("attempt_id") or "")
        if (
            not failure_attempt_id
            or not manifest_attempt_id
            or failure_attempt_id != manifest_attempt_id
        ):
            raise ManualFinalSubtitleEditError("失败记录与字幕检查点不属于同一次运行。")
        return cls.load_from_manifest(manifest_path)

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

    @staticmethod
    def _parse_display_page_boundary_overrides(value: Any) -> Dict[str, List[int]]:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping):
            raise ManualFinalSubtitleEditError("人工分页边界记录格式无效。")
        overrides: Dict[str, List[int]] = {}
        for raw_parent_id, raw_starts in value.items():
            parent_id = str(raw_parent_id or "").strip()
            if not parent_id or not isinstance(raw_starts, list):
                raise ManualFinalSubtitleEditError("人工分页边界记录格式无效。")
            try:
                starts = [int(item) for item in raw_starts]
            except (TypeError, ValueError) as exc:
                raise ManualFinalSubtitleEditError(
                    "人工分页边界记录包含无效的词位置。"
                ) from exc
            if any(item < 0 for item in starts) or starts != sorted(set(starts)):
                raise ManualFinalSubtitleEditError(
                    "人工分页边界必须按词账本顺序连续保存。"
                )
            overrides[parent_id] = starts
        return overrides

    @staticmethod
    def _parse_recovered_stale_page_drafts(
        value: Any,
    ) -> Dict[str, Dict[str, Any]]:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping):
            raise ManualFinalSubtitleEditError("旧分页中文草稿记录格式无效。")
        drafts: Dict[str, Dict[str, Any]] = {}
        for raw_page_id, raw_draft in value.items():
            page_id = str(raw_page_id or "").strip()
            if (
                not page_id
                or page_id in drafts
                or not isinstance(raw_draft, Mapping)
                or str(raw_draft.get("display_page_id") or "") != page_id
            ):
                raise ManualFinalSubtitleEditError("旧分页中文草稿页面身份无效。")
            try:
                draft = {
                    "display_page_id": page_id,
                    "parent_subtitle_id": str(
                        raw_draft.get("parent_subtitle_id") or ""
                    ),
                    "word_start": int(raw_draft.get("word_start", -1)),
                    "word_end": int(raw_draft.get("word_end", -1)),
                    "start_ms": int(raw_draft.get("start_ms", -1)),
                    "end_ms": int(raw_draft.get("end_ms", -1)),
                    "english": str(raw_draft.get("english") or ""),
                    "chinese": str(raw_draft.get("chinese") or ""),
                }
            except (TypeError, ValueError) as exc:
                raise ManualFinalSubtitleEditError(
                    "旧分页中文草稿包含无效词范围或时间。"
                ) from exc
            if (
                not draft["parent_subtitle_id"]
                or draft["word_start"] < 0
                or draft["word_end"] < draft["word_start"]
                or draft["start_ms"] < 0
                or draft["end_ms"] <= draft["start_ms"]
                or not draft["english"].strip()
                or not draft["chinese"].strip()
            ):
                raise ManualFinalSubtitleEditError("旧分页中文草稿内容不完整。")
            drafts[page_id] = draft
        return drafts

    @staticmethod
    def _source_media_from_result_directory(anchor: Path) -> Path | None:
        """Resolve one exact media sibling from the owned result-directory name."""
        candidate_anchor = Path(anchor)
        search_nodes = [candidate_anchor, *candidate_anchor.parents]
        result_dir = next(
            (
                node
                for node in search_nodes
                if node.name.endswith("-处理结果")
            ),
            None,
        )
        if result_dir is None:
            return None
        source_stem = result_dir.name[: -len("-处理结果")]
        if not source_stem or not result_dir.parent.is_dir():
            return None
        matches = [
            item.resolve()
            for item in result_dir.parent.iterdir()
            if item.is_file()
            and item.stem.casefold() == source_stem.casefold()
            and item.suffix.casefold() in _SUPPORTED_MEDIA_SUFFIXES
        ]
        return matches[0] if len(matches) == 1 else None

    @classmethod
    def _manifest_source_media_path(
        cls,
        manifest: Mapping[str, Any],
        *anchors: Path,
    ) -> Path | None:
        text = str(
            (manifest.get("manual_final_override") or {}).get("source_media_path")
            or manifest.get("source_media_path")
            or ""
        ).strip()
        if text:
            path = Path(text)
            if path.is_file():
                return path.resolve()
        for anchor in anchors:
            resolved = cls._source_media_from_result_directory(Path(anchor))
            if resolved is not None:
                return resolved
        return None

    @classmethod
    def _is_manifest_display_page_subtitle(
        cls,
        subtitle_path: Path,
        manifest: Mapping[str, Any],
    ) -> bool:
        try:
            actual_hash = file_sha256(subtitle_path).lower()
        except OSError:
            return False
        override = manifest.get("manual_final_override") or {}
        paths = manifest.get("paths") or {}
        source_paths = manifest.get("source_subtitle_paths") or {}
        parent_path_values = (
            str(override.get("subtitle_path") or ""),
            str(paths.get("original_top_srt") or ""),
            str(source_paths.get("named_bilingual_original_top_srt") or ""),
            str(source_paths.get("bilingual_original_top_srt") or ""),
        )
        if any(
            value and cls._same_path(subtitle_path, Path(value))
            for value in parent_path_values
        ):
            return False
        path_values = (
            str(override.get("display_page_srt_path") or ""),
            str(paths.get("display_page_bilingual_srt") or ""),
            str(source_paths.get("display_page_bilingual_srt") or ""),
        )
        if any(
            value and cls._same_path(subtitle_path, Path(value))
            for value in path_values
        ):
            return True
        hashes = (
            str(override.get("display_page_srt_sha256") or "").lower(),
            str((manifest.get("paths_sha256") or {}).get("display_page_bilingual_srt") or "").lower(),
            str((manifest.get("source_subtitle_paths_sha256") or {}).get("display_page_bilingual_srt") or "").lower(),
        )
        parent_hashes = {
            str(value or "").lower()
            for value in (
                override.get("subtitle_sha256"),
                (manifest.get("paths_sha256") or {}).get("original_top_srt"),
                (manifest.get("source_subtitle_paths_sha256") or {}).get(
                    "named_bilingual_original_top_srt"
                ),
                (manifest.get("source_subtitle_paths_sha256") or {}).get(
                    "bilingual_original_top_srt"
                ),
            )
            if value
        }
        if actual_hash in parent_hashes:
            return False
        return actual_hash in {value for value in hashes if value}

    @staticmethod
    def _display_page_parent_subtitle_path(
        manifest: Mapping[str, Any],
    ) -> Path | None:
        override = manifest.get("manual_final_override") or {}
        paths = manifest.get("paths") or {}
        source_paths = manifest.get("source_subtitle_paths") or {}
        for value in (
            override.get("subtitle_path"),
            paths.get("original_top_srt"),
            source_paths.get("named_bilingual_original_top_srt"),
            source_paths.get("bilingual_original_top_srt"),
        ):
            text = str(value or "").strip()
            if text:
                return Path(text).resolve()
        return None

    @staticmethod
    def _companion_display_page_map_path(subtitle_path: Path) -> Path | None:
        name = subtitle_path.name
        named_suffix = "-实际分页双语字幕.srt"
        if name.endswith(named_suffix):
            return subtitle_path.with_name(
                name[: -len(named_suffix)] + "-实际分页映射.json"
            )
        if name == "人工终稿分页双语字幕.srt":
            return subtitle_path.with_name("人工终稿分页映射.json")
        return None

    @classmethod
    def _recover_stale_display_page_import(
        cls,
        subtitle_path: Path,
        *,
        work_dir: str | Path | None,
        current_manifest_path: str | Path | None = None,
    ) -> "ManualFinalSubtitleSession" | None:
        """Open the current parent package without trusting an obsolete page file."""
        map_path = cls._companion_display_page_map_path(subtitle_path)
        if map_path is None or not map_path.is_file():
            return None
        page_map = cls._read_json(map_path)
        expected_page_hash = str(
            page_map.get("display_page_subtitle_sha256") or ""
        ).lower()
        try:
            actual_page_hash = file_sha256(subtitle_path).lower()
        except OSError as exc:
            raise ManualFinalSubtitleEditError("无法校验实际分页字幕。") from exc
        if not expected_page_hash or expected_page_hash != actual_page_hash:
            raise ManualFinalSubtitleEditError(
                "实际分页字幕与旁边的分页映射不一致，不能安全恢复编辑。"
            )

        parent_text = str(page_map.get("source_parent_subtitle_path") or "").strip()
        parent_path = Path(parent_text).resolve() if parent_text else None
        if parent_path is None or not parent_path.is_file():
            raise ManualFinalSubtitleEditError(
                "这份实际分页字幕已经过期，但找不到它对应的父字幕。"
            )
        current_manifest = (
            Path(current_manifest_path).resolve()
            if current_manifest_path
            else cls._find_manifest_for_subtitle(parent_path, work_dir)
        )
        if current_manifest is None or not current_manifest.is_file():
            raise ManualFinalSubtitleEditError(
                "这份实际分页字幕已经过期，但找不到当前人工终稿包；请导入最新的原文在上双语字幕。"
            )

        stale_data = ASRData.from_subtitle_file(str(subtitle_path))
        mapped_pages = list(page_map.get("pages") or [])
        if len(stale_data.segments) != len(mapped_pages):
            raise ManualFinalSubtitleEditError(
                "实际分页字幕与分页映射的页面数量不一致。"
            )
        recovered_drafts: Dict[str, Dict[str, Any]] = {}
        for segment, raw_page in zip(stale_data.segments, mapped_pages):
            if not isinstance(raw_page, Mapping):
                raise ManualFinalSubtitleEditError("实际分页映射包含无效页面。")
            page_id = str(raw_page.get("display_page_id") or "").strip()
            parent_id = str(raw_page.get("parent_subtitle_id") or "").strip()
            english = str(raw_page.get("english") or "")
            chinese = str(raw_page.get("chinese") or "")
            try:
                identity_matches = (
                    page_id
                    and parent_id
                    and page_id not in recovered_drafts
                    and int(raw_page.get("start_ms", -1)) == int(segment.start_time)
                    and int(raw_page.get("end_ms", -1)) == int(segment.end_time)
                    and cls._normalised_tokens(english)
                    == cls._normalised_tokens(segment.text)
                    and re.sub(r"\s+", "", chinese)
                    == re.sub(r"\s+", "", str(segment.translated_text or ""))
                    and int(raw_page.get("word_start", -1)) >= 0
                    and int(raw_page.get("word_end", -1))
                    >= int(raw_page.get("word_start", -1))
                )
            except (TypeError, ValueError):
                identity_matches = False
            if not identity_matches:
                raise ManualFinalSubtitleEditError(
                    "实际分页字幕与分页映射的页面身份、英文、中文或时间不一致。"
                )
            if chinese.strip():
                recovered_drafts[page_id] = {
                    "display_page_id": page_id,
                    "parent_subtitle_id": parent_id,
                    "word_start": int(raw_page["word_start"]),
                    "word_end": int(raw_page["word_end"]),
                    "start_ms": int(raw_page["start_ms"]),
                    "end_ms": int(raw_page["end_ms"]),
                    "english": english,
                    "chinese": chinese,
                }

        session = cls.load_from_manifest(current_manifest)
        session.loaded_subtitle_path = subtitle_path
        session.recovered_stale_page_drafts = recovered_drafts
        session.import_notice = (
            "导入的实际分页已被后续保存淘汰；已自动打开最新人工终稿，"
            "身份仍匹配的旧分页中文仅作为待确认草稿显示"
        )
        return session

    @classmethod
    def _find_manifest_for_subtitle(
        cls, subtitle_path: Path, work_dir: str | Path | None
    ) -> Path | None:
        if not subtitle_path.is_file():
            return None
        try:
            subtitle_sha256 = file_sha256(subtitle_path)
        except OSError:
            return None

        candidates: list[Path] = []
        direct = subtitle_path.parent / "stable-final-manifest.json"
        if direct.is_file():
            candidates.append(direct)
        candidates.extend(
            subtitle_path.parent.glob("*-人工终稿字幕包/stable-final-manifest.json")
        )
        legacy_portable = (
            subtitle_path.parent / "人工终稿字幕包" / "stable-final-manifest.json"
        )
        if legacy_portable.is_file():
            candidates.append(legacy_portable)
        if work_dir:
            root = Path(work_dir)
            if root.exists():
                candidates.extend(root.rglob("stable-final-manifest.json"))

        ranked_matches: list[tuple[tuple[int, int, float], Path]] = []
        seen: set[str] = set()
        for manifest_path in candidates:
            manifest_key = os.path.normcase(str(manifest_path.resolve()))
            if manifest_key in seen:
                continue
            seen.add(manifest_key)
            try:
                manifest = cls._read_json(manifest_path)
            except ManualFinalSubtitleEditError:
                continue

            override = manifest.get("manual_final_override") or {}
            manifest_paths = manifest.get("paths") or {}
            source_paths = manifest.get("source_subtitle_paths") or {}
            is_manual_package = bool(
                isinstance(override, Mapping)
                and int(override.get("schema_version") or 0) >= 1
                and override.get("subtitle_path")
            )
            override_exact = bool(
                override.get("subtitle_path")
                and cls._same_path(
                    subtitle_path,
                    Path(str(override.get("subtitle_path"))),
                )
            )
            manifest_exact = any(
                value and cls._same_path(subtitle_path, Path(str(value)))
                for value in manifest_paths.values()
            )
            source_exact = any(
                value and cls._same_path(subtitle_path, Path(str(value)))
                for value in source_paths.values()
            )
            original_top_reset = subtitle_path.name.endswith(
                "-原文在上双语字幕.srt"
            )
            exact_path = bool(
                override_exact
                or manifest_exact
                or (
                    source_exact
                    and not (original_top_reset and is_manual_package)
                )
            )

            override_hash = str(override.get("subtitle_sha256") or "").lower()
            published_hashes = {
                str(value or "").lower()
                for value in (
                    override_hash,
                    *(manifest.get("paths_sha256") or {}).values(),
                    *(manifest.get("source_subtitle_paths_sha256") or {}).values(),
                )
                if value
            }
            hash_match = subtitle_sha256.lower() in published_hashes
            if not hash_match:
                continue

            try:
                modified = manifest_path.stat().st_mtime
            except OSError:
                modified = 0.0
            rank = (
                2 if exact_path else 1,
                1 if is_manual_package else 0,
                modified,
            )
            ranked_matches.append((rank, manifest_path))

        if not ranked_matches:
            return None
        ranked_matches.sort(key=lambda item: item[0], reverse=True)
        return ranked_matches[0][1]

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
            subtitle_id = str(span.get("subtitle_id") or "")
            if not _SUBTITLE_ID_RE.fullmatch(subtitle_id):
                raise ManualFinalSubtitleEditError(
                    f"第 {index} 条缺少有效的固定字幕 ID。"
                )
            if subtitle_id != f"S{index:04d}":
                raise ManualFinalSubtitleEditError(
                    f"第 {index} 条固定字幕 ID 顺序不完整。"
                )
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
        manifest = cls._read_json(manifest_path)
        override = manifest.get("manual_final_override") or {}
        override_schema = int(override.get("schema_version") or 0)
        owned_edit_text = str(override.get("edit_artifact_path") or "").strip()
        owned_edit_path = Path(owned_edit_text) if owned_edit_text else None
        expected_edit_hash = str(
            override.get("edit_artifact_sha256") or ""
        ).strip()
        if override_schema >= 3 or expected_edit_hash:
            if (
                owned_edit_path is None
                or not owned_edit_path.is_file()
                or not cls._same_path(owned_edit_path, edit_artifact_path)
                or not expected_edit_hash
                or file_sha256(edit_artifact_path) != expected_edit_hash
            ):
                raise ManualFinalSubtitleEditError(
                    "人工终稿编辑记录与清单哈希不一致。"
                )

        payload = cls._read_json(edit_artifact_path)
        ledger = list(payload.get("word_ledger") or [])
        cues = list(payload.get("cues") or [])
        if not ledger or not cues:
            raise ManualFinalSubtitleEditError("人工终稿编辑记录不完整。")
        embedded_ledger_hash = stable_payload_hash(cls._ledger_payload(ledger))
        recorded_ledger_hash = str(
            payload.get("source_word_ledger_hash") or ""
        ).strip()
        if not recorded_ledger_hash or recorded_ledger_hash != embedded_ledger_hash:
            raise ManualFinalSubtitleEditError(
                "人工终稿编辑记录内的词账本哈希不一致。"
            )
        owned_ledger_text = str(override.get("word_ledger_path") or "").strip()
        owned_ledger_path = Path(owned_ledger_text) if owned_ledger_text else None
        expected_ledger_file_hash = str(
            override.get("word_ledger_sha256") or ""
        ).strip()
        if override_schema >= 3:
            if (
                owned_ledger_path is None
                or not owned_ledger_path.is_file()
                or not expected_ledger_file_hash
                or file_sha256(owned_ledger_path) != expected_ledger_file_hash
            ):
                raise ManualFinalSubtitleEditError(
                    "人工终稿词账本与清单哈希不一致。"
                )
            owned_ledger_payload = cls._read_json(owned_ledger_path)
            owned_ledger = list(owned_ledger_payload.get("words") or [])
            if (
                not owned_ledger
                or stable_payload_hash(cls._ledger_payload(owned_ledger))
                != embedded_ledger_hash
            ):
                raise ManualFinalSubtitleEditError(
                    "人工终稿编辑记录引用了不同的词账本。"
                )
        owned_artifact_text = str(override.get("artifact_dir") or "").strip()
        owned_artifact_path = Path(owned_artifact_text) if owned_artifact_text else None
        if (
            owned_artifact_path is None
            or not owned_artifact_path.is_dir()
            or not cls._same_path(owned_artifact_path.parent, manifest_path.parent)
            or not (owned_artifact_path / "translations.json").is_file()
        ):
            source_artifact_text = str(
                payload.get("source_artifact_dir") or ""
            ).strip()
            owned_artifact_path = (
                Path(source_artifact_text) if source_artifact_text else None
            )
        if owned_artifact_path is None or not owned_artifact_path.exists():
            owned_artifact_path = cls._artifact_dir_for_manifest(
                manifest_path,
                manifest,
            )
        session = cls(
            subtitle_path=subtitle_path,
            manifest_path=manifest_path,
            artifact_dir=owned_artifact_path,
            word_ledger=ledger,
            cues=cues,
            source_word_ledger_hash=str(payload.get("source_word_ledger_hash") or ""),
            history=list(payload.get("history") or []),
            display_page_edits=list(payload.get("display_page_edits") or []),
            display_page_boundary_overrides=(
                cls._parse_display_page_boundary_overrides(
                    payload.get("display_page_boundary_overrides")
                )
            ),
            recovered_stale_page_drafts=(
                cls._parse_recovered_stale_page_drafts(
                    payload.get("recovered_stale_page_drafts")
                )
            ),
            tail_trim=dict(payload.get("tail_trim") or {}),
            loaded_subtitle_path=subtitle_path,
            source_media_path=cls._manifest_source_media_path(
                manifest,
                manifest_path,
                subtitle_path,
            ),
        )
        session._validate_cues()
        session._validate_display_page_boundary_overrides()
        session._remember_known_formal_boundary_evidence()
        recovered_count = session._recover_identity_matched_history_page_drafts()
        if recovered_count:
            session.import_notice = (
                f"已从可撤销历史恢复 {recovered_count} 条身份完全匹配的分页中文；"
                "这些内容仍需人工确认后才能作为正式终稿。"
            )
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

    def _article_render_cue(
        self,
        cue_index: int,
        boundary_items: Mapping[str, Mapping[str, Any]],
    ):
        from app.core.utils.podcast_learning_video import Cue

        cue = self.cues[cue_index]
        word_start = int(cue["word_start"])
        word_end = int(cue["word_end"])
        return Cue(
            index=cue_index + 1,
            start=int(cue["start_time"]) / 1000.0,
            end=int(cue["end_time"]) / 1000.0,
            en=str(cue["original_subtitle"]),
            zh=str(cue.get("translated_subtitle") or ""),
            speaker="manual",
            subtitle_id=str(cue.get("cue_id") or ""),
            word_timing=tuple(
                {
                    "word_id": word_id,
                    "surface": str(
                        self.word_ledger[word_id].get(
                            "surface",
                            self.word_ledger[word_id].get("token", ""),
                        )
                    ),
                    "start": self._word_start_time(word_id) / 1000.0,
                    "end": self._word_end_time(word_id) / 1000.0,
                }
                for word_id in range(word_start, word_end + 1)
            ),
            display_boundary_evidence={
                str(right_word): dict(boundary_items[str(right_word)])
                for right_word in range(word_start + 1, word_end + 1)
            },
        )

    def _ensure_unmodified_english(self, cue: Mapping[str, Any]) -> None:
        expected = self._words_text(self.word_ledger, int(cue["word_start"]), int(cue["word_end"]))
        if self._normalised_tokens(cue.get("original_subtitle", "")) != self._normalised_tokens(expected):
            raise ManualFinalSubtitleEditError(
                "该行英文已被自由修改，无法再按原始词级账本移动边界。"
            )

    def _record_history(self, operation: str, before: Sequence[Mapping[str, Any]], **details: Any) -> None:
        self._remember_formal_boundary_evidence(self.cues)
        self._remember_formal_boundary_evidence(before)
        self.history.append(
            {
                "operation": operation,
                "at": datetime.now().isoformat(timespec="seconds"),
                "before_cues": copy.deepcopy(list(before)),
                "before_display_page_edits": copy.deepcopy(
                    self.display_page_edits
                ),
                "before_display_page_boundary_overrides": copy.deepcopy(
                    self.display_page_boundary_overrides
                ),
                "before_tail_trim": copy.deepcopy(self.tail_trim),
                **details,
            }
        )

    @staticmethod
    def _cue_boundary_word_ids(
        cues: Sequence[Mapping[str, Any]],
    ) -> set[int]:
        return {
            int(cue.get("word_start") or 0)
            for cue in list(cues)[1:]
            if int(cue.get("word_start") or 0) > 0
        }

    def _remember_formal_boundary_evidence(
        self,
        cues: Sequence[Mapping[str, Any]],
    ) -> None:
        """Retain provenance for legacy packages that omitted cue edges."""
        for right in self._cue_boundary_word_ids(cues):
            if right <= 0 or right >= len(self.word_ledger):
                continue
            left_word = self.word_ledger[right - 1]
            right_word = self.word_ledger[right]
            pause_ms = int(
                right_word.get("start_ms", right_word.get("start_time", 0)) or 0
            ) - int(
                left_word.get("end_ms", left_word.get("end_time", 0)) or 0
            )
            self.recovered_formal_boundary_evidence.setdefault(
                str(right),
                {
                    "hard_issues": [],
                    "soft_issues": ["recovered_formal_cue_boundary"],
                    "boundary_score": 0.0,
                    "protected_syntax": False,
                    "pause_ms": pause_ms,
                    "evidence_origin": "accepted_formal_cue_boundary",
                },
            )

    def _remember_known_formal_boundary_evidence(self) -> None:
        self._remember_formal_boundary_evidence(self.cues)
        for entry in self.history:
            before = entry.get("before_cues") or []
            if isinstance(before, list):
                self._remember_formal_boundary_evidence(before)

    def _validate_cues(self) -> None:
        previous_word_end = -1
        previous_end_time = -1
        source_subtitle_ids: List[str] = []
        cue_ids = set()
        for index, cue in enumerate(self.cues, 1):
            start = int(cue.get("word_start", -1))
            end = int(cue.get("word_end", -1))
            start_time = int(cue.get("start_time", -1))
            end_time = int(cue.get("end_time", -1))
            if start != previous_word_end + 1 or end < start or end >= len(self.word_ledger):
                raise ManualFinalSubtitleEditError(f"第 {index} 条的词范围不连续。")
            if start_time < 0 or end_time <= start_time or start_time < previous_end_time:
                raise ManualFinalSubtitleEditError(f"第 {index} 条的时间轴无效或重叠。")
            cue_id = str(cue.get("cue_id") or "")
            cue_source_ids = [
                str(value) for value in cue.get("source_subtitle_ids") or []
            ]
            if (
                not _SUBTITLE_ID_RE.fullmatch(cue_id)
                or cue_id in cue_ids
                or not cue_source_ids
                or cue_id != cue_source_ids[0]
                or any(not _SUBTITLE_ID_RE.fullmatch(value) for value in cue_source_ids)
            ):
                raise ManualFinalSubtitleEditError(
                    f"第 {index} 条的固定字幕 ID 无效或重复。"
                )
            cue_ids.add(cue_id)
            source_subtitle_ids.extend(cue_source_ids)
            previous_word_end = end
            previous_end_time = end_time
        if previous_word_end != len(self.word_ledger) - 1:
            raise ManualFinalSubtitleEditError("字幕没有覆盖完整词级账本。")
        expected_source_ids = [
            f"S{index:04d}" for index in range(1, len(source_subtitle_ids) + 1)
        ]
        if source_subtitle_ids != expected_source_ids:
            raise ManualFinalSubtitleEditError("固定字幕 ID 存在遗漏、重复或顺序漂移。")

    def _validate_display_page_boundary_overrides(self) -> None:
        cue_by_id = {
            str(cue.get("cue_id") or ""): cue
            for cue in self.cues
            if str(cue.get("cue_id") or "")
        }
        for parent_id, starts in self.display_page_boundary_overrides.items():
            cue = cue_by_id.get(parent_id)
            if cue is None:
                raise ManualFinalSubtitleEditError(
                    "人工分页边界引用了不存在的父字幕。"
                )
            word_start = int(cue["word_start"])
            word_end = int(cue["word_end"])
            previous = word_start
            for start in starts:
                if int(start) <= previous or int(start) > word_end:
                    raise ManualFinalSubtitleEditError(
                        "人工分页边界超出父字幕的冻结词范围。"
                    )
                previous = int(start)

    def _validate_no_silent_display_page_state_loss(self) -> None:
        if self.display_page_edits or self.display_page_boundary_overrides:
            return
        for entry in reversed(self.history):
            if (
                entry.get("before_display_page_edits")
                or entry.get("before_display_page_boundary_overrides")
            ):
                raise ManualFinalSubtitleEditError(
                    "检测到人工分页状态异常归零，已拒绝保存；"
                    "请撤销最近的父字幕边界操作，或从原文在上双语字幕重新开始。"
                )

    def state_fingerprint(self) -> str:
        """Return the complete mutable editor state used for clean/dirty checks."""
        return stable_payload_hash(
            {
                "word_ledger": self._ledger_payload(self.word_ledger),
                "cues": self.cues,
                "display_page_edits": self.display_page_edits,
                "display_page_boundary_overrides": (
                    self.display_page_boundary_overrides
                ),
                "tail_trim": self.tail_trim,
            }
        )

    def _invalidate_display_page_state(self) -> None:
        self.display_page_edits = []
        self.display_page_boundary_overrides = {}

    def _display_page_rows_before_formal_boundary_change(
        self,
    ) -> List[Dict[str, Any]]:
        """Snapshot a complete visible page model before parent spans change."""
        rows = [
            copy.deepcopy(dict(row))
            for row in self._display_page_model_data().values()
        ]
        if not rows or any(
            row.get("display_page_unavailable")
            or not str(row.get("display_page_id") or "")
            for row in rows
        ):
            return []
        return rows

    def _recover_identity_matched_history_page_drafts(self) -> int:
        """Recover only blank current pages from the package's hashed undo history."""
        current_rows = [
            dict(row) for row in self._display_page_model_data().values()
        ]
        missing_by_page_id = {
            str(row.get("display_page_id") or ""): row
            for row in current_rows
            if str(row.get("display_page_id") or "")
            and not str(row.get("translated_subtitle") or "").strip()
            and not row.get("display_page_unavailable")
        }
        if not missing_by_page_id:
            return 0

        candidates: Dict[str, Dict[str, Any]] = {}
        for history_entry in self.history:
            if not isinstance(history_entry, Mapping):
                continue
            for raw_edit in history_entry.get("before_display_page_edits") or []:
                if not isinstance(raw_edit, Mapping):
                    continue
                page_id = str(raw_edit.get("display_page_id") or "").strip()
                chinese = str(
                    raw_edit.get("chinese")
                    or raw_edit.get("translated_subtitle")
                    or raw_edit.get("stale_chinese_draft")
                    or ""
                ).strip()
                if not page_id or not chinese:
                    continue
                try:
                    candidates[page_id] = {
                        "parent_subtitle_id": str(
                            raw_edit.get("parent_subtitle_id")
                            or raw_edit.get("manual_cue_id")
                            or ""
                        ),
                        "word_start": int(raw_edit.get("word_start", -1)),
                        "word_end": int(raw_edit.get("word_end", -1)),
                        "english": str(
                            raw_edit.get("english")
                            or raw_edit.get("original_subtitle")
                            or ""
                        ),
                        "chinese": chinese,
                    }
                except (TypeError, ValueError):
                    continue

        recovered = 0
        for page_id, row in missing_by_page_id.items():
            candidate = candidates.get(page_id)
            if candidate is None:
                continue
            if (
                candidate["parent_subtitle_id"]
                != str(row.get("manual_cue_id") or "")
                or candidate["word_start"] != int(row.get("word_start", -2))
                or candidate["word_end"] != int(row.get("word_end", -2))
                or self._normalised_tokens(candidate["english"])
                != self._normalised_tokens(row.get("original_subtitle"))
            ):
                continue
            self.recovered_stale_page_drafts[page_id] = {
                "display_page_id": page_id,
                "parent_subtitle_id": candidate["parent_subtitle_id"],
                "word_start": candidate["word_start"],
                "word_end": candidate["word_end"],
                "start_ms": int(row["start_time"]),
                "end_ms": int(row["end_time"]),
                "english": str(row.get("original_subtitle") or ""),
                "chinese": candidate["chinese"],
            }
            recovered += 1
        return recovered

    def _reflow_display_page_state_after_formal_boundary_change(
        self,
        previous_rows: Sequence[Mapping[str, Any]],
        affected_parent_ids: Sequence[str],
    ) -> bool:
        """Rebuild only changed parents while freezing every unaffected page."""
        affected = {str(value or "").strip() for value in affected_parent_ids}
        affected.discard("")
        cue_by_id = {
            str(cue.get("cue_id") or ""): cue
            for cue in self.cues
            if str(cue.get("cue_id") or "")
        }
        rows_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        for raw_row in previous_rows:
            row = copy.deepcopy(dict(raw_row))
            parent_id = str(row.get("manual_cue_id") or "")
            if parent_id and str(row.get("display_page_id") or ""):
                rows_by_parent.setdefault(parent_id, []).append(row)
        if (
            not previous_rows
            or not affected
            or any(parent_id not in cue_by_id for parent_id in affected)
            or any(not rows_by_parent.get(parent_id) for parent_id in affected)
        ):
            self._invalidate_display_page_state()
            return False

        unaffected_edits = [
            self._unchanged_display_page_edit_from_model_row(row)
            for row in previous_rows
            if str(row.get("manual_cue_id") or "") not in affected
        ]
        overrides = {
            parent_id: list(starts)
            for parent_id, starts in self.display_page_boundary_overrides.items()
            if parent_id not in affected
        }
        for parent_id in affected:
            cue = cue_by_id[parent_id]
            cue_start = int(cue["word_start"])
            cue_end = int(cue["word_end"])
            prior_pages = sorted(
                rows_by_parent[parent_id],
                key=lambda row: int(row["word_start"]),
            )
            internal_starts = sorted(
                {
                    int(row["word_start"])
                    for row in prior_pages[1:]
                    if cue_start < int(row["word_start"]) <= cue_end
                }
            )
            # An empty list is an explicit one-page override. It still matters
            # when the parent English span changed and the source plan is stale.
            overrides[parent_id] = internal_starts

        self.display_page_boundary_overrides = overrides
        self.display_page_edits = unaffected_edits
        rebuilt_rows = [
            copy.deepcopy(dict(row))
            for row in self._display_page_model_data().values()
        ]
        if not rebuilt_rows or any(
            row.get("display_page_unavailable")
            or not str(row.get("display_page_id") or "")
            for row in rebuilt_rows
        ):
            self._invalidate_display_page_state()
            return False

        rebuilt_edits: List[Dict[str, Any]] = []
        for row in rebuilt_rows:
            parent_id = str(row.get("manual_cue_id") or "")
            edit = self._unchanged_display_page_edit_from_model_row(row)
            if parent_id in affected:
                visible_chinese = str(
                    row.get("translated_subtitle")
                    or cue_by_id[parent_id].get("translated_subtitle")
                    or ""
                ).strip()
                edit.update(
                    {
                        "chinese": "",
                        "chinese_review_acknowledged": False,
                        "boundary_review_acknowledged": False,
                        "stale_chinese_draft": visible_chinese,
                        "chinese_stale_unconfirmed": True,
                        "chinese_draft_kind": "formal_boundary_reflow_draft",
                    }
                )
            rebuilt_edits.append(edit)
        self.display_page_edits = rebuilt_edits
        return True

    def apply_parent_model_data(
        self,
        rows: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        """Apply parent Chinese by stable identity; frozen English stays immutable."""
        if len(rows) != len(self.cues):
            raise ManualFinalSubtitleEditError(
                "字幕行数已变化，无法安全应用人工终稿操作。"
            )
        updates: List[tuple[Dict[str, Any], str]] = []
        for index, cue in enumerate(self.cues, 1):
            row = rows.get(str(index))
            if row is None:
                raise ManualFinalSubtitleEditError("父字幕表数据不完整。")
            key = (
                str(row.get("manual_cue_id") or ""),
                int(row.get("word_start", -1)),
                int(row.get("word_end", -1)),
            )
            expected_key = (
                str(cue.get("cue_id") or ""),
                int(cue.get("word_start", -1)),
                int(cue.get("word_end", -1)),
            )
            if key != expected_key:
                raise ManualFinalSubtitleEditError(
                    "父字幕 ID 或冻结词范围已漂移，拒绝按表格行号写回。"
                )
            if (
                int(row.get("start_time", -1)) != int(cue.get("start_time", -2))
                or int(row.get("end_time", -1)) != int(cue.get("end_time", -2))
            ):
                raise ManualFinalSubtitleEditError(
                    "父字幕时间轴已漂移，无法安全写回人工编辑。"
                )
            if str(row.get("original_subtitle") or "") != str(
                cue.get("original_subtitle") or ""
            ):
                raise ManualFinalSubtitleEditError(
                    "父字幕英文由冻结词账本生成，不能直接改写；请使用边界调整。"
                )
            chinese = str(row.get("translated_subtitle") or "")
            if chinese != str(cue.get("translated_subtitle") or ""):
                updates.append((cue, chinese))
        if not updates:
            return False
        before = copy.deepcopy(self.cues)
        self._record_history(
            "edit_parent_chinese",
            before,
            affected_parent_ids=[
                str(cue.get("cue_id") or "") for cue, _chinese in updates
            ],
        )
        for cue, chinese in updates:
            cue["translated_subtitle"] = chinese
        return True

    def move_suffix_to_next(self, left_index: int, word_count: int) -> None:
        if left_index < 0 or left_index + 1 >= len(self.cues):
            raise ManualFinalSubtitleEditError("只能把末尾词移动到紧邻的下一条字幕。")
        if word_count <= 0:
            raise ManualFinalSubtitleEditError("移动词数必须大于零。")
        left = self.cues[left_index]
        right = self.cues[left_index + 1]
        previous_page_rows = self._display_page_rows_before_formal_boundary_change()
        before_page_edits = copy.deepcopy(self.display_page_edits)
        before_page_overrides = copy.deepcopy(
            self.display_page_boundary_overrides
        )
        self._ensure_unmodified_english(left)
        self._ensure_unmodified_english(right)
        word_count = self.expanded_manual_boundary_word_count(
            left_word_start=int(left["word_start"]),
            left_word_end=int(left["word_end"]),
            right_word_start=int(right["word_start"]),
            right_word_end=int(right["word_end"]),
            requested_word_count=word_count,
            move_to_next=True,
        )
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
        pages_preserved = self._reflow_display_page_state_after_formal_boundary_change(
            previous_page_rows,
            [str(left.get("cue_id") or ""), str(right.get("cue_id") or "")],
        )
        if (previous_page_rows or before_page_edits or before_page_overrides) and not pages_preserved:
            self.cues[left_index : left_index + 2] = before
            self.display_page_edits = before_page_edits
            self.display_page_boundary_overrides = before_page_overrides
            self.history.pop()
            self._validate_cues()
            self._validate_display_page_boundary_overrides()
            raise ManualFinalSubtitleEditError(
                "调整后的实际分页无法局部重建，字幕和人工分页均未修改。"
            )

    def move_prefix_to_previous(self, right_index: int, word_count: int) -> None:
        if right_index <= 0 or right_index >= len(self.cues):
            raise ManualFinalSubtitleEditError("只能把开头词移动到紧邻的上一条字幕。")
        if word_count <= 0:
            raise ManualFinalSubtitleEditError("移动词数必须大于零。")
        left = self.cues[right_index - 1]
        right = self.cues[right_index]
        previous_page_rows = self._display_page_rows_before_formal_boundary_change()
        before_page_edits = copy.deepcopy(self.display_page_edits)
        before_page_overrides = copy.deepcopy(
            self.display_page_boundary_overrides
        )
        self._ensure_unmodified_english(left)
        self._ensure_unmodified_english(right)
        word_count = self.expanded_manual_boundary_word_count(
            left_word_start=int(left["word_start"]),
            left_word_end=int(left["word_end"]),
            right_word_start=int(right["word_start"]),
            right_word_end=int(right["word_end"]),
            requested_word_count=word_count,
            move_to_next=False,
        )
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
        pages_preserved = self._reflow_display_page_state_after_formal_boundary_change(
            previous_page_rows,
            [str(left.get("cue_id") or ""), str(right.get("cue_id") or "")],
        )
        if (previous_page_rows or before_page_edits or before_page_overrides) and not pages_preserved:
            self.cues[right_index - 1 : right_index + 1] = before
            self.display_page_edits = before_page_edits
            self.display_page_boundary_overrides = before_page_overrides
            self.history.pop()
            self._validate_cues()
            self._validate_display_page_boundary_overrides()
            raise ManualFinalSubtitleEditError(
                "调整后的实际分页无法局部重建，字幕和人工分页均未修改。"
            )

    def merge_adjacent(self, first_index: int, last_index: int) -> None:
        if first_index < 0 or last_index >= len(self.cues) or first_index >= last_index:
            raise ManualFinalSubtitleEditError("请选择至少两条相邻字幕进行合并。")
        selected = self.cues[first_index : last_index + 1]
        for left, right in zip(selected, selected[1:]):
            if int(left["word_end"]) + 1 != int(right["word_start"]):
                raise ManualFinalSubtitleEditError("选中的字幕词范围不连续，不能安全合并。")
        previous_page_rows = self._display_page_rows_before_formal_boundary_change()
        selected_parent_ids = [str(cue.get("cue_id") or "") for cue in selected]
        retained_parent_id = selected_parent_ids[0]
        remapped_page_rows = []
        for raw_row in previous_page_rows:
            row = copy.deepcopy(dict(raw_row))
            if str(row.get("manual_cue_id") or "") in selected_parent_ids:
                row["manual_cue_id"] = retained_parent_id
            remapped_page_rows.append(row)
        before = copy.deepcopy(selected)
        before_page_edits = copy.deepcopy(self.display_page_edits)
        before_page_overrides = copy.deepcopy(
            self.display_page_boundary_overrides
        )
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
        for parent_id in selected_parent_ids[1:]:
            self.display_page_boundary_overrides.pop(parent_id, None)
        pages_preserved = self._reflow_display_page_state_after_formal_boundary_change(
            remapped_page_rows,
            [retained_parent_id],
        )
        if previous_page_rows and not pages_preserved:
            self.cues[first_index : first_index + 1] = before
            self.display_page_edits = before_page_edits
            self.display_page_boundary_overrides = before_page_overrides
            self.history.pop()
            self._validate_cues()
            self._validate_display_page_boundary_overrides()
            raise ManualFinalSubtitleEditError(
                "合并后的实际分页无法满足固定词账本、时间轴或排版约束，字幕未修改。"
            )

    @staticmethod
    def _history_affected_parent_ids(entry: Mapping[str, Any]) -> set[str]:
        affected = {
            str(value or "").strip()
            for value in entry.get("affected_parent_ids") or []
            if str(value or "").strip()
        }
        parent_id = str(entry.get("parent_subtitle_id") or "").strip()
        if parent_id:
            affected.add(parent_id)
        for key in ("display_page_id", "left_page_id", "right_page_id"):
            page_id = str(entry.get(key) or "").strip()
            if ".P" in page_id:
                affected.add(page_id.split(".P", 1)[0])
        if affected:
            return affected
        if str(entry.get("operation") or "") in {
            "move_suffix_to_next",
            "move_prefix_to_previous",
            "merge_adjacent",
            "trim_tail_from_cue",
        }:
            return {
                str(cue.get("cue_id") or cue.get("subtitle_id") or "").strip()
                for cue in entry.get("before_cues") or []
                if str(
                    cue.get("cue_id") or cue.get("subtitle_id") or ""
                ).strip()
            }
        return set()

    def can_undo_for_parent(self, parent_subtitle_id: str) -> bool:
        parent_id = str(parent_subtitle_id or "").strip()
        return bool(
            parent_id
            and self.history
            and parent_id
            in self._history_affected_parent_ids(self.history[-1])
        )

    def undo_for_parent(self, parent_subtitle_id: str) -> bool:
        if not self.can_undo_for_parent(parent_subtitle_id):
            raise ManualFinalSubtitleEditError(
                "当前字幕没有可撤销的最新调整；不能跳过后续修改单独回滚。"
            )
        return self.undo()

    def undo(self) -> bool:
        if not self.history:
            return False
        self._remember_known_formal_boundary_evidence()
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
        elif entry["operation"] in {
            "edit_parent_chinese",
            "edit_display_page_chinese",
        }:
            self.cues = before
        elif entry["operation"] in {
            "move_display_page_boundary",
            "split_parent_into_display_pages",
            "merge_display_page_with_next",
            "confirm_display_page_boundary",
            "confirm_all_nonblocking_display_page_reviews",
        }:
            self.cues = before
        elif entry["operation"] == "trim_tail_from_cue":
            self.cues = before
            self.word_ledger = list(entry.get("before_word_ledger") or [])
            self.source_word_ledger_hash = str(
                entry.get("before_source_word_ledger_hash") or ""
            )
            previous_media = str(
                entry.get("before_source_media_path") or ""
            ).strip()
            self.source_media_path = Path(previous_media) if previous_media else None
            previous_artifact_dir = str(
                entry.get("before_artifact_dir") or ""
            ).strip()
            if previous_artifact_dir:
                self.artifact_dir = Path(previous_artifact_dir)
        else:
            return False
        self.display_page_edits = list(
            entry.get("before_display_page_edits") or []
        )
        self.display_page_boundary_overrides = (
            self._parse_display_page_boundary_overrides(
                entry.get("before_display_page_boundary_overrides")
            )
        )
        self.tail_trim = dict(entry.get("before_tail_trim") or {})
        self._validate_cues()
        self._validate_display_page_boundary_overrides()
        return True

    def to_model_data(
        self,
        *,
        prefer_display_pages: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        if prefer_display_pages:
            page_rows = self._display_page_model_data()
            if page_rows:
                return page_rows
        return self._parent_model_data()

    def _parent_model_data(self) -> Dict[str, Dict[str, Any]]:
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

    def _display_page_model_data(self) -> Dict[str, Dict[str, Any]]:
        cache_key = self._display_page_model_state_key()
        if cache_key == self._display_page_model_cache_key:
            return copy.deepcopy(self._display_page_model_cache)
        previews = self._display_page_previews()
        if not previews:
            self._display_page_model_cache_key = cache_key
            self._display_page_model_cache = {}
            return {}
        rows: Dict[str, Dict[str, Any]] = {}
        row_index = 0
        for cue_index, cue in enumerate(self.cues):
            parent_id = str(cue.get("cue_id") or "")
            pages = list(previews.get(parent_id) or [])
            if not pages:
                row_index += 1
                rows[str(row_index)] = {
                    "start_time": int(cue["start_time"]),
                    "end_time": int(cue["end_time"]),
                    "original_subtitle": str(cue["original_subtitle"]),
                    "translated_subtitle": str(
                        cue.get("translated_subtitle") or ""
                    ),
                    "manual_cue_id": parent_id,
                    "source_subtitle_ids": list(
                        cue.get("source_subtitle_ids") or []
                    ),
                    "display_page_id": "",
                    "display_page_view": True,
                    "display_page_unavailable": True,
                    "parent_cue_index": cue_index,
                    "word_start": int(cue["word_start"]),
                    "word_end": int(cue["word_end"]),
                    "english_font_size": 0,
                    "display_page_review_required": True,
                    "display_page_boundary_classification": "unavailable",
                    "display_page_issue_codes": ["display_page_unavailable"],
                    "display_page_chinese_stale": False,
                    "display_page_chinese_confirmed": True,
                    "chinese_review_required": True,
                }
                continue
            for page in pages:
                row_index += 1
                boundary_before = dict(page.get("boundary_before") or {})
                boundary_classification = str(
                    boundary_before.get("classification") or ""
                )
                boundary_issue_codes = [
                    str(code)
                    for code in boundary_before.get("issue_codes") or []
                    if str(code)
                ]
                translation_issue_codes = [
                    str(code)
                    for code in page.get("translation_issue_codes") or []
                    if str(code)
                ]
                display_issue_codes = list(
                    dict.fromkeys(
                        [*boundary_issue_codes, *translation_issue_codes]
                    )
                )
                boundary_acknowledged = bool(
                    page.get("boundary_review_acknowledged")
                )
                boundary_review_required = bool(
                    translation_issue_codes
                    or boundary_classification == "hard"
                    or (
                        boundary_classification == "review"
                        or boundary_issue_codes
                    )
                    and not boundary_acknowledged
                )
                chinese_confirmed = bool(
                    str(page.get("chinese") or "").strip()
                    and not translation_issue_codes
                    and not page.get("chinese_stale_draft")
                    and (
                        not cue.get("chinese_review_required")
                        or page.get("chinese_review_acknowledged")
                    )
                )
                rows[str(row_index)] = {
                    "start_time": int(page["start_ms"]),
                    "end_time": int(page["end_ms"]),
                    "original_subtitle": str(page["english"]),
                    "translated_subtitle": str(page["chinese"]),
                    "manual_cue_id": parent_id,
                    "source_subtitle_ids": list(
                        cue.get("source_subtitle_ids") or []
                    ),
                    "display_page_id": str(page["display_page_id"]),
                    "display_page_view": True,
                    "display_page_unavailable": False,
                    "display_page_index": int(page["page_index"]),
                    "parent_cue_index": cue_index,
                    "word_start": int(page["word_start"]),
                    "word_end": int(page["word_end"]),
                    "english_font_size": int(page["english_font_size"]),
                    "display_page_review_required": boundary_review_required,
                    "display_page_boundary_acknowledged": (
                        boundary_acknowledged
                    ),
                    "display_page_boundary_classification": (
                        boundary_classification
                        or ("review" if translation_issue_codes else "")
                    ),
                    "display_page_issue_codes": display_issue_codes,
                    "display_page_chinese_stale": bool(
                        page.get("chinese_stale_draft")
                    ),
                    "display_page_chinese_draft_kind": str(
                        page.get("chinese_draft_kind") or ""
                    ),
                    "display_page_chinese_confirmed": chinese_confirmed,
                    "chinese_review_required": not chinese_confirmed,
                }
        self._display_page_model_cache_key = cache_key
        self._display_page_model_cache = copy.deepcopy(rows)
        return rows

    @staticmethod
    def _display_page_cache_file_token(path: Path) -> List[Any]:
        try:
            stat = path.stat()
        except OSError:
            return [str(path), -1, -1]
        return [str(path), int(stat.st_size), int(stat.st_mtime_ns)]

    def _display_page_model_state_key(self) -> str:
        """Bind a reusable page model to all mutable and file-backed owners."""
        return stable_payload_hash(
            {
                "session": self.state_fingerprint(),
                "recovered_formal_boundary_evidence": (
                    self.recovered_formal_boundary_evidence
                ),
                "recovered_stale_page_drafts": self.recovered_stale_page_drafts,
                "files": [
                    self._display_page_cache_file_token(path)
                    for path in (
                        self.manifest_path,
                        self.artifact_dir / "display-page-translations.json",
                        self.artifact_dir / "manual-draft-page-plan.json",
                        self.artifact_dir / "display-boundary-evidence.json",
                    )
                ],
            }
        )

    def has_display_page_model(self) -> bool:
        return bool(self._display_page_model_data())

    @staticmethod
    def _unchanged_display_page_edit_from_model_row(
        row: Mapping[str, Any],
    ) -> Dict[str, Any]:
        displayed_chinese = str(row.get("translated_subtitle") or "").strip()
        stale_unconfirmed = bool(
            row.get("display_page_chinese_stale")
            and not row.get("display_page_chinese_confirmed")
        )
        edit = {
            "display_page_id": str(row.get("display_page_id") or ""),
            "parent_subtitle_id": str(row.get("manual_cue_id") or ""),
            "word_start": int(row["word_start"]),
            "word_end": int(row["word_end"]),
            "english": str(row.get("original_subtitle") or ""),
            "chinese": "" if stale_unconfirmed else displayed_chinese,
            "chinese_review_acknowledged": bool(
                row.get("display_page_chinese_confirmed")
                and displayed_chinese
            ),
            "boundary_review_acknowledged": bool(
                row.get("display_page_boundary_acknowledged")
            ),
        }
        if stale_unconfirmed:
            edit["stale_chinese_draft"] = displayed_chinese
            edit["chinese_stale_unconfirmed"] = True
            edit["chinese_draft_kind"] = str(
                row.get("display_page_chinese_draft_kind") or ""
            )
        return edit

    def apply_display_page_model_data(
        self,
        rows: Mapping[str, Mapping[str, Any]],
        *,
        allow_incomplete_chinese: bool = False,
    ) -> bool:
        expected = self._display_page_model_data()
        if not expected or len(rows) != len(expected):
            raise ManualFinalSubtitleEditError(
                "实际分页行数或权威分页映射已变化，无法安全保存。"
            )
        edits: List[Dict[str, Any]] = []
        chinese_by_parent: Dict[str, List[str]] = {}
        incomplete_chinese_parents: set[str] = set()
        unconfirmed_chinese_parents: set[str] = set()
        fallback_chinese_by_parent: Dict[str, str] = {}
        changed = False
        changed_parent_ids: set[str] = set()
        for index in range(1, len(expected) + 1):
            key = str(index)
            source = expected.get(key)
            row = rows.get(key)
            if source is None or row is None:
                raise ManualFinalSubtitleEditError("实际分页表数据不完整。")
            identity_fields = (
                "manual_cue_id",
                "word_start",
                "word_end",
                "start_time",
                "end_time",
            )
            if source.get("display_page_id"):
                identity_fields = ("display_page_id", *identity_fields)
            if any(str(row.get(name)) != str(source.get(name)) for name in identity_fields):
                raise ManualFinalSubtitleEditError(
                    "实际分页的页面 ID、父 ID、词范围或时间已漂移。"
                )
            if str(row.get("original_subtitle") or "") != str(
                source.get("original_subtitle") or ""
            ):
                raise ManualFinalSubtitleEditError(
                    "实际分页英文由冻结词范围生成，不能直接改写；请回到父字幕处理英文边界。"
                )
            chinese = str(row.get("translated_subtitle") or "").strip()
            stale_chinese_draft = bool(source.get("display_page_chinese_stale"))
            chinese_text_changed = bool(
                chinese != str(source.get("translated_subtitle") or "").strip()
            )
            stale_chinese_confirmed = bool(
                chinese
                and (
                    row.get("display_page_chinese_confirmed")
                    or chinese_text_changed
                )
            )
            source_chinese_confirmed = bool(
                source.get("display_page_chinese_confirmed")
            )
            authoritative_chinese = (
                chinese
                if not stale_chinese_draft or stale_chinese_confirmed
                else ""
            )
            if (
                not authoritative_chinese
                and not stale_chinese_draft
                and not allow_incomplete_chinese
            ):
                raise ManualFinalSubtitleEditError("实际分页中文不能为空。")
            parent_id = str(source["manual_cue_id"])
            if source.get("display_page_id"):
                chinese_by_parent.setdefault(parent_id, []).append(
                    authoritative_chinese
                )
                if not authoritative_chinese:
                    incomplete_chinese_parents.add(parent_id)
                if not stale_chinese_confirmed:
                    unconfirmed_chinese_parents.add(parent_id)
                edit = {
                    "display_page_id": str(source["display_page_id"]),
                    "parent_subtitle_id": parent_id,
                    "word_start": int(source["word_start"]),
                    "word_end": int(source["word_end"]),
                    "english": str(source["original_subtitle"]),
                    "chinese": authoritative_chinese,
                    "chinese_review_acknowledged": bool(
                        stale_chinese_confirmed and authoritative_chinese
                    ),
                    "boundary_review_acknowledged": bool(
                        source.get("display_page_boundary_acknowledged")
                    ),
                }
                if stale_chinese_draft and not stale_chinese_confirmed:
                    edit["stale_chinese_draft"] = chinese
                    edit["chinese_stale_unconfirmed"] = True
                    edit["chinese_draft_kind"] = str(
                        source.get("display_page_chinese_draft_kind") or ""
                    )
                edits.append(edit)
            else:
                fallback_chinese_by_parent[parent_id] = chinese
            row_changed = bool(
                chinese_text_changed
                or (stale_chinese_draft and stale_chinese_confirmed)
                or stale_chinese_confirmed != source_chinese_confirmed
            )
            changed = changed or row_changed
            if row_changed and parent_id:
                changed_parent_ids.add(parent_id)
        complete_page_model = all(
            bool(item.get("display_page_id")) for item in expected.values()
        )
        if not changed:
            # Opening the actual-page view establishes the already validated
            # page artifact as the manual checkpoint. A no-op save must not
            # invoke a new planner and silently change what the editor showed.
            if complete_page_model and not any(
                item.get("chinese_stale_unconfirmed") for item in edits
            ):
                self.display_page_edits = edits
            return False

        before = copy.deepcopy(self.cues)
        self._record_history(
            "edit_display_page_chinese",
            before,
            affected_parent_ids=sorted(changed_parent_ids),
        )
        cue_by_id = {
            str(cue.get("cue_id") or ""): cue for cue in self.cues
        }
        for parent_id, values in chinese_by_parent.items():
            cue = cue_by_id.get(parent_id)
            if cue is None:
                raise ManualFinalSubtitleEditError(
                    "实际分页引用了不存在的父字幕 ID。"
                )
            if (
                parent_id in incomplete_chinese_parents
                or parent_id in unconfirmed_chinese_parents
            ):
                cue["chinese_review_required"] = True
            else:
                cue["translated_subtitle"] = "".join(values)
                cue["chinese_review_required"] = False
        for parent_id, chinese in fallback_chinese_by_parent.items():
            cue = cue_by_id.get(parent_id)
            if cue is None:
                raise ManualFinalSubtitleEditError(
                    "实际分页引用了不存在的父字幕 ID。"
                )
            cue["translated_subtitle"] = chinese
            cue["chinese_review_required"] = True
        self.display_page_edits = edits if complete_page_model else []
        return True

    def display_page_review_summary(self) -> Dict[str, Any]:
        """Return actionable manual review counts for the current page identity."""
        rows = list(self._display_page_model_data().values())
        chinese_pages = [
            str(row.get("display_page_id") or row.get("manual_cue_id") or "")
            for row in rows
            if row.get("chinese_review_required")
        ]
        boundary_pages = [
            str(row.get("display_page_id") or row.get("manual_cue_id") or "")
            for row in rows
            if row.get("display_page_review_required")
            and str(row.get("display_page_boundary_classification") or "")
            != "hard"
        ]
        hard_pages = [
            str(row.get("display_page_id") or row.get("manual_cue_id") or "")
            for row in rows
            if row.get("display_page_unavailable")
            or (
                row.get("display_page_review_required")
                and str(row.get("display_page_boundary_classification") or "")
                == "hard"
            )
        ]
        return {
            "unconfirmed_chinese_count": len(chinese_pages),
            "unconfirmed_chinese_pages": chinese_pages,
            "boundary_review_count": len(boundary_pages),
            "boundary_review_pages": boundary_pages,
            "hard_page_count": len(hard_pages),
            "hard_pages": hard_pages,
        }

    def confirm_display_page_chinese(self, page_id: str) -> Dict[str, Any]:
        """Accept the visible Chinese for one exact page identity."""
        rows = self._display_page_model_data()
        target = next(
            (
                row
                for row in rows.values()
                if str(row.get("display_page_id") or "") == str(page_id)
            ),
            None,
        )
        if target is None or target.get("display_page_unavailable"):
            raise ManualFinalSubtitleEditError("找不到可确认的实际分页中文。")
        if not str(target.get("translated_subtitle") or "").strip():
            raise ManualFinalSubtitleEditError("当前实际分页中文为空，不能确认。")
        if target.get("display_page_chinese_confirmed"):
            return {"changed": False, "display_page_id": str(page_id)}
        target["display_page_chinese_confirmed"] = True
        target["chinese_review_required"] = False
        changed = self.apply_display_page_model_data(
            rows,
            allow_incomplete_chinese=True,
        )
        return {"changed": bool(changed), "display_page_id": str(page_id)}

    def confirm_display_page_boundary(self, page_id: str) -> Dict[str, Any]:
        """Acknowledge the reviewed boundary before one exact display page."""
        rows = self._display_page_model_data()
        target = next(
            (
                row
                for row in rows.values()
                if str(row.get("display_page_id") or "") == str(page_id)
            ),
            None,
        )
        if target is None or target.get("display_page_unavailable"):
            raise ManualFinalSubtitleEditError("找不到可确认的实际分页边界。")
        if str(target.get("display_page_boundary_classification") or "") == "hard":
            raise ManualFinalSubtitleEditError("结构性硬错误不能用人工确认跳过。")
        if not target.get("display_page_review_required"):
            return {"changed": False, "display_page_id": str(page_id)}
        before = copy.deepcopy(self.cues)
        self._record_history(
            "confirm_display_page_boundary",
            before,
            display_page_id=str(page_id),
        )
        edits = [
            self._unchanged_display_page_edit_from_model_row(row)
            for row in rows.values()
        ]
        for edit in edits:
            if str(edit.get("display_page_id") or "") == str(page_id):
                edit["boundary_review_acknowledged"] = True
                break
        self.display_page_edits = edits
        return {"changed": True, "display_page_id": str(page_id)}

    def confirm_all_nonblocking_display_page_reviews(self) -> Dict[str, Any]:
        """Accept visible Chinese drafts and REVIEW boundaries, never hard errors."""
        rows = self._display_page_model_data()
        if not rows or any(row.get("display_page_unavailable") for row in rows.values()):
            raise ManualFinalSubtitleEditError(
                "当前实际分页不完整，不能批量确认非阻断提醒。"
            )
        chinese_ids = [
            str(row.get("display_page_id") or "")
            for row in rows.values()
            if row.get("chinese_review_required")
            and str(row.get("translated_subtitle") or "").strip()
        ]
        boundary_ids = [
            str(row.get("display_page_id") or "")
            for row in rows.values()
            if row.get("display_page_review_required")
            and str(row.get("display_page_boundary_classification") or "")
            != "hard"
        ]
        for row in rows.values():
            if str(row.get("display_page_id") or "") in chinese_ids:
                row["display_page_chinese_confirmed"] = True
                row["chinese_review_required"] = False
        chinese_changed = False
        if chinese_ids:
            chinese_changed = self.apply_display_page_model_data(
                rows,
                allow_incomplete_chinese=True,
            )
        current_rows = self._display_page_model_data()
        if boundary_ids:
            if not chinese_changed:
                self._record_history(
                    "confirm_all_nonblocking_display_page_reviews",
                    copy.deepcopy(self.cues),
                    chinese_count=len(chinese_ids),
                    boundary_count=len(boundary_ids),
                    affected_parent_ids=sorted(
                        {
                            page_id.split(".P", 1)[0]
                            for page_id in [*chinese_ids, *boundary_ids]
                            if ".P" in page_id
                        }
                    ),
                )
            edits = [
                self._unchanged_display_page_edit_from_model_row(row)
                for row in current_rows.values()
            ]
            boundary_set = set(boundary_ids)
            for edit in edits:
                if str(edit.get("display_page_id") or "") in boundary_set:
                    edit["boundary_review_acknowledged"] = True
            self.display_page_edits = edits
        return {
            "changed": bool(chinese_ids or boundary_ids),
            "chinese_count": len(chinese_ids),
            "boundary_count": len(boundary_ids),
        }

    def move_display_page_boundary(
        self,
        left_page_id: str,
        word_count: int,
        *,
        move_to_next: bool,
    ) -> Dict[str, Any]:
        """Move words across two adjacent pages of one unchanged parent cue."""
        if word_count <= 0:
            raise ManualFinalSubtitleEditError("移动词数必须大于零。")
        model_rows = list(self._display_page_model_data().values())
        if not model_rows or any(
            not str(row.get("display_page_id") or "") for row in model_rows
        ):
            raise ManualFinalSubtitleEditError(
                "当前实际分页不完整，不能安全移动分页边界。"
            )
        try:
            left_position = next(
                index
                for index, row in enumerate(model_rows)
                if str(row.get("display_page_id") or "") == str(left_page_id)
            )
        except StopIteration as exc:
            raise ManualFinalSubtitleEditError("找不到选中的实际分页。") from exc
        if left_position + 1 >= len(model_rows):
            raise ManualFinalSubtitleEditError("最后一屏后面没有可调整的实际分页。")

        left = dict(model_rows[left_position])
        right = dict(model_rows[left_position + 1])
        parent_id = str(left.get("manual_cue_id") or "")
        if (
            not parent_id
            or parent_id != str(right.get("manual_cue_id") or "")
        ):
            raise ManualFinalSubtitleEditError(
                "这两屏属于不同父字幕；请使用正式字幕边界移动。"
            )

        parent_rows = [
            dict(row)
            for row in model_rows
            if str(row.get("manual_cue_id") or "") == parent_id
        ]
        page_ids = [str(row.get("display_page_id") or "") for row in parent_rows]
        try:
            page_index = page_ids.index(str(left_page_id))
        except ValueError as exc:
            raise ManualFinalSubtitleEditError("实际分页顺序已变化。") from exc
        if page_index + 1 >= len(parent_rows):
            raise ManualFinalSubtitleEditError("只能调整同一父字幕内相邻两屏。")

        ranges = [
            [int(row["word_start"]), int(row["word_end"])]
            for row in parent_rows
        ]
        left_count = ranges[page_index][1] - ranges[page_index][0] + 1
        right_count = ranges[page_index + 1][1] - ranges[page_index + 1][0] + 1
        word_count = self.expanded_manual_boundary_word_count(
            left_word_start=ranges[page_index][0],
            left_word_end=ranges[page_index][1],
            right_word_start=ranges[page_index + 1][0],
            right_word_end=ranges[page_index + 1][1],
            requested_word_count=word_count,
            move_to_next=move_to_next,
        )
        if move_to_next:
            if word_count >= left_count:
                raise ManualFinalSubtitleEditError("不能把上一屏的全部英文词移走。")
            boundary = ranges[page_index][1] - word_count + 1
        else:
            if word_count >= right_count:
                raise ManualFinalSubtitleEditError("不能把下一屏的全部英文词移走。")
            boundary = ranges[page_index + 1][0] + word_count
        ranges[page_index][1] = boundary - 1
        ranges[page_index + 1][0] = boundary

        cue_index = next(
            (
                index
                for index, cue in enumerate(self.cues)
                if str(cue.get("cue_id") or "") == parent_id
            ),
            -1,
        )
        if cue_index < 0:
            raise ManualFinalSubtitleEditError("实际分页引用了不存在的父字幕。")
        cue = self.cues[cue_index]
        artifact = self._effective_display_page_artifact()
        source_plan = next(
            (
                dict(plan)
                for plan in artifact.get("render_plans") or []
                if isinstance(plan, Mapping)
                and str(plan.get("parent_subtitle_id") or "") == parent_id
            ),
            None,
        )
        if source_plan is None:
            raise ManualFinalSubtitleEditError("找不到该父字幕的冻结分页计划。")

        from app.core.utils.podcast_learning_video import (
            Cue,
            RenderStructuralOverflowError,
            rebuild_article_frozen_page_plan_from_word_ranges,
        )

        boundary_payload = self._validated_display_boundary_evidence()
        boundary_items = dict(boundary_payload.get("boundaries") or {})
        word_start = int(cue["word_start"])
        word_end = int(cue["word_end"])
        render_cue = Cue(
            index=cue_index + 1,
            start=int(cue["start_time"]) / 1000.0,
            end=int(cue["end_time"]) / 1000.0,
            en=str(cue["original_subtitle"]),
            zh=str(cue.get("translated_subtitle") or ""),
            speaker="manual",
            subtitle_id=parent_id,
            word_timing=tuple(
                {
                    "word_id": word_id,
                    "surface": str(
                        self.word_ledger[word_id].get(
                            "surface",
                            self.word_ledger[word_id].get("token", ""),
                        )
                    ),
                    "start": self._word_start_time(word_id) / 1000.0,
                    "end": self._word_end_time(word_id) / 1000.0,
                }
                for word_id in range(word_start, word_end + 1)
            ),
            display_boundary_evidence={
                str(right_word): dict(boundary_items[str(right_word)])
                for right_word in range(word_start + 1, word_end + 1)
            },
        )
        page_translations = {
            str(row["display_page_id"]): str(row.get("translated_subtitle") or "")
            for row in parent_rows
        }
        current_ranges = [
            (int(row["word_start"]), int(row["word_end"]))
            for row in parent_rows
        ]
        try:
            source_page_ranges = [
                (int(page["word_start"]), int(page["word_end"]))
                for page in source_plan.get("pages") or []
                if isinstance(page, Mapping)
            ]
            if source_page_ranges != current_ranges:
                source_plan = rebuild_article_frozen_page_plan_from_word_ranges(
                    render_cue,
                    source_plan,
                    current_ranges,
                    page_translations,
                    allow_page_count_change=True,
                    allow_incomplete_page_translations=True,
                    allow_manual_review=True,
                )
            rebuilt_plan = rebuild_article_frozen_page_plan_from_word_ranges(
                render_cue,
                source_plan,
                [(start, end) for start, end in ranges],
                page_translations,
                allow_incomplete_page_translations=True,
                allow_manual_review=True,
            )
        except RenderStructuralOverflowError as exc:
            reasons = ", ".join(
                str(item.get("reason") or "")
                for item in getattr(exc, "errors", [])
                if isinstance(item, Mapping)
            )
            raise ManualFinalSubtitleEditError(
                "这个移动会造成语法硬切、页面过短或排版溢出，已拒绝。"
                + (f"（{reasons}）" if reasons else "")
            ) from exc

        rebuilt_by_id = {
            str(page.get("display_page_id") or ""): dict(page)
            for page in rebuilt_plan.get("pages") or []
        }
        new_edits: List[Dict[str, Any]] = []
        affected_page_ids = {
            str(left.get("display_page_id") or ""),
            str(right.get("display_page_id") or ""),
        }
        for row in model_rows:
            page_id = str(row.get("display_page_id") or "")
            row_parent_id = str(row.get("manual_cue_id") or "")
            if row_parent_id == parent_id:
                page = rebuilt_by_id.get(page_id)
                if page is None:
                    raise ManualFinalSubtitleEditError("重建后的分页 ID 不完整。")
                page_start = int(page["word_start"])
                page_end = int(page["word_end"])
                english = str(page.get("english") or "")
            else:
                page_start = int(row["word_start"])
                page_end = int(row["word_end"])
                english = str(row.get("original_subtitle") or "")
            if row_parent_id == parent_id:
                if page_id not in affected_page_ids:
                    new_edits.append(
                        self._unchanged_display_page_edit_from_model_row(row)
                    )
                    continue
                visible_chinese = str(
                    row.get("translated_subtitle") or ""
                ).strip()
                edit = {
                    "display_page_id": page_id,
                    "parent_subtitle_id": row_parent_id,
                    "word_start": page_start,
                    "word_end": page_end,
                    "english": english,
                    "chinese": "",
                    "chinese_review_acknowledged": False,
                    "boundary_review_acknowledged": bool(
                        page_id == str(right.get("display_page_id") or "")
                        or row.get("display_page_boundary_acknowledged")
                    ),
                }
                if visible_chinese:
                    edit.update(
                        {
                            "stale_chinese_draft": visible_chinese,
                            "chinese_stale_unconfirmed": True,
                            "chinese_draft_kind": (
                                "manual_boundary_move_draft"
                            ),
                        }
                    )
                new_edits.append(edit)
            else:
                new_edits.append(
                    self._unchanged_display_page_edit_from_model_row(row)
                )

        before = copy.deepcopy(self.cues)
        self._record_history(
            "move_display_page_boundary",
            before,
            parent_subtitle_id=parent_id,
            left_page_id=str(left_page_id),
            word_count=int(word_count),
            move_to_next=bool(move_to_next),
        )
        self.display_page_boundary_overrides[parent_id] = [
            int(page["word_start"])
            for page in list(rebuilt_plan.get("pages") or [])[1:]
        ]
        self.display_page_edits = new_edits
        cue["chinese_review_required"] = True
        return {
            "parent_subtitle_id": parent_id,
            "left_page_id": str(left_page_id),
            "right_page_id": str(right.get("display_page_id") or ""),
            "word_count": int(word_count),
            "move_to_next": bool(move_to_next),
            "warnings": [
                {
                    "classification": str(
                        page.get("boundary_before", {}).get("classification") or ""
                    ),
                    "issue_codes": list(
                        page.get("boundary_before", {}).get("issue_codes") or []
                    ),
                    "pause_ms": page.get("boundary_before", {}).get("pause_ms"),
                    "page_duration_ms": page.get("boundary_before", {}).get(
                        "page_duration_ms"
                    ),
                }
                for page in list(rebuilt_plan.get("pages") or [])[1:]
                if str(
                    page.get("boundary_before", {}).get("classification") or ""
                )
                == "review"
            ],
        }

    def merge_display_page_with_next(
        self,
        left_page_id: str,
    ) -> Dict[str, Any]:
        """Remove one internal page boundary without changing its parent cue."""
        page_id = str(left_page_id or "").strip()
        model_rows = list(self._display_page_model_data().values())
        if not page_id or not model_rows or any(
            not str(row.get("display_page_id") or "")
            or row.get("display_page_unavailable")
            for row in model_rows
        ):
            raise ManualFinalSubtitleEditError(
                "当前实际分页不完整，不能安全合并分屏。"
            )
        try:
            left_position = next(
                index
                for index, row in enumerate(model_rows)
                if str(row.get("display_page_id") or "") == page_id
            )
        except StopIteration as exc:
            raise ManualFinalSubtitleEditError("找不到选中的实际分页。") from exc
        if left_position + 1 >= len(model_rows):
            raise ManualFinalSubtitleEditError("最后一屏后面没有可合并的分屏。")

        left = dict(model_rows[left_position])
        right = dict(model_rows[left_position + 1])
        parent_id = str(left.get("manual_cue_id") or "")
        if not parent_id or parent_id != str(right.get("manual_cue_id") or ""):
            raise ManualFinalSubtitleEditError(
                "下一屏属于另一条父字幕；请使用“合并相邻父字幕”。"
            )
        parent_rows = [
            dict(row)
            for row in model_rows
            if str(row.get("manual_cue_id") or "") == parent_id
        ]
        page_ids = [str(row.get("display_page_id") or "") for row in parent_rows]
        try:
            page_index = page_ids.index(page_id)
        except ValueError as exc:
            raise ManualFinalSubtitleEditError("实际分页顺序已变化。") from exc
        if page_index + 1 >= len(parent_rows):
            raise ManualFinalSubtitleEditError("只能合并同一父字幕内的相邻两屏。")

        cue_index = next(
            (
                index
                for index, cue in enumerate(self.cues)
                if str(cue.get("cue_id") or "") == parent_id
            ),
            -1,
        )
        if cue_index < 0:
            raise ManualFinalSubtitleEditError("实际分页引用了不存在的父字幕。")
        cue = self.cues[cue_index]
        self._ensure_unmodified_english(cue)
        source_plan = next(
            (
                dict(plan)
                for plan in self._effective_display_page_artifact().get(
                    "render_plans"
                )
                or []
                if isinstance(plan, Mapping)
                and str(plan.get("parent_subtitle_id") or "") == parent_id
            ),
            None,
        )
        if source_plan is None:
            raise ManualFinalSubtitleEditError("找不到该父字幕的冻结分页计划。")

        source_groups: List[List[Dict[str, Any]]] = [
            [dict(row)] for row in parent_rows
        ]
        source_groups[page_index : page_index + 2] = [
            [parent_rows[page_index], parent_rows[page_index + 1]]
        ]
        ranges = [
            (
                int(group[0]["word_start"]),
                int(group[-1]["word_end"]),
            )
            for group in source_groups
        ]
        page_translations = {
            display_page_id(parent_id, index + 1): "".join(
                str(row.get("translated_subtitle") or "").strip()
                for row in group
            )
            for index, group in enumerate(source_groups)
        }

        from app.core.utils.podcast_learning_video import (
            RenderStructuralOverflowError,
            rebuild_article_frozen_page_plan_from_word_ranges,
        )

        boundary_payload = self._validated_display_boundary_evidence()
        try:
            rebuilt_plan = rebuild_article_frozen_page_plan_from_word_ranges(
                self._article_render_cue(
                    cue_index,
                    dict(boundary_payload.get("boundaries") or {}),
                ),
                source_plan,
                ranges,
                page_translations,
                allow_page_count_change=True,
                allow_incomplete_page_translations=True,
                allow_manual_review=True,
            )
        except RenderStructuralOverflowError as exc:
            reasons = ", ".join(
                str(item.get("reason") or "")
                for item in getattr(exc, "errors", [])
                if isinstance(item, Mapping)
            )
            raise ManualFinalSubtitleEditError(
                "合并后单屏会过长、过短或无法按固定字号排版，字幕未修改。"
                + (f"（{reasons}）" if reasons else "")
            ) from exc

        rebuilt_pages = [
            dict(page)
            for page in rebuilt_plan.get("pages") or []
            if isinstance(page, Mapping)
        ]
        if len(rebuilt_pages) != len(source_groups):
            raise ManualFinalSubtitleEditError("合并后的分页数量不一致。")

        replacement_edits: List[Dict[str, Any]] = []
        for page, group in zip(rebuilt_pages, source_groups):
            new_page_id = str(page.get("display_page_id") or "")
            visible_chinese = page_translations.get(new_page_id, "")
            stale_unconfirmed = any(
                row.get("display_page_chinese_stale")
                and not row.get("display_page_chinese_confirmed")
                for row in group
            )
            chinese_confirmed = bool(
                visible_chinese
                and not stale_unconfirmed
                and all(
                    row.get("display_page_chinese_confirmed") for row in group
                )
            )
            edit = {
                "display_page_id": new_page_id,
                "parent_subtitle_id": parent_id,
                "word_start": int(page["word_start"]),
                "word_end": int(page["word_end"]),
                "english": str(page.get("english") or ""),
                "chinese": "" if stale_unconfirmed else visible_chinese,
                "chinese_review_acknowledged": chinese_confirmed,
                "boundary_review_acknowledged": bool(
                    group[0].get("display_page_boundary_acknowledged")
                ),
            }
            if stale_unconfirmed:
                edit.update(
                    {
                        "stale_chinese_draft": visible_chinese,
                        "chinese_stale_unconfirmed": True,
                        "chinese_draft_kind": "merged_page_draft",
                    }
                )
            replacement_edits.append(edit)

        new_edits: List[Dict[str, Any]] = []
        inserted_parent = False
        for row in model_rows:
            if str(row.get("manual_cue_id") or "") == parent_id:
                if not inserted_parent:
                    new_edits.extend(replacement_edits)
                    inserted_parent = True
                continue
            new_edits.append(self._unchanged_display_page_edit_from_model_row(row))
        if not inserted_parent:
            raise ManualFinalSubtitleEditError("当前实际分页没有覆盖所选父字幕。")

        self._record_history(
            "merge_display_page_with_next",
            copy.deepcopy(self.cues),
            parent_subtitle_id=parent_id,
            left_page_id=page_id,
            removed_boundary_word_id=int(right["word_start"]),
        )
        self.display_page_boundary_overrides[parent_id] = [
            int(page["word_start"]) for page in rebuilt_pages[1:]
        ]
        self.display_page_edits = new_edits
        return {
            "parent_subtitle_id": parent_id,
            "left_page_id": page_id,
            "merged_page_id": str(rebuilt_pages[page_index]["display_page_id"]),
            "removed_boundary_word_id": int(right["word_start"]),
            "page_count": len(rebuilt_pages),
        }

    def split_parent_into_display_pages(
        self,
        parent_subtitle_id: str,
        page_count: int,
    ) -> Dict[str, Any]:
        """Replace one parent's display-page count without changing the parent cue."""
        parent_id = str(parent_subtitle_id or "").strip()
        requested = int(page_count)
        if requested not in {2, 3, 4}:
            raise ManualFinalSubtitleEditError("人工分页只支持拆成 2、3 或 4 屏。")
        cue_index = next(
            (
                index
                for index, cue in enumerate(self.cues)
                if str(cue.get("cue_id") or "") == parent_id
            ),
            -1,
        )
        if cue_index < 0:
            raise ManualFinalSubtitleEditError("找不到要拆分的父字幕。")
        cue = self.cues[cue_index]
        self._ensure_unmodified_english(cue)

        artifact = self._effective_display_page_artifact()
        source_plan = next(
            (
                dict(plan)
                for plan in artifact.get("render_plans") or []
                if isinstance(plan, Mapping)
                and str(plan.get("parent_subtitle_id") or "") == parent_id
            ),
            None,
        )
        if source_plan is None:
            raise ManualFinalSubtitleEditError("找不到该父字幕的冻结分页计划。")

        from app.core.utils.podcast_learning_video import (
            RenderStructuralOverflowError,
            propose_article_manual_page_word_ranges,
            rebuild_article_frozen_page_plan_from_word_ranges,
        )

        boundary_payload = self._validated_display_boundary_evidence()
        render_cue = self._article_render_cue(
            cue_index,
            dict(boundary_payload.get("boundaries") or {}),
        )
        try:
            ranges = propose_article_manual_page_word_ranges(
                render_cue,
                requested,
                allow_review_boundary=True,
            )
            new_page_ids = [
                display_page_id(parent_id, index + 1)
                for index in range(requested)
            ]
            rebuilt_plan = rebuild_article_frozen_page_plan_from_word_ranges(
                render_cue,
                source_plan,
                ranges,
                {page_id: "" for page_id in new_page_ids},
                allow_page_count_change=True,
                allow_incomplete_page_translations=True,
                allow_manual_review=True,
            )
        except RenderStructuralOverflowError as exc:
            reasons = ", ".join(
                str(item.get("reason") or "")
                for item in getattr(exc, "errors", [])
                if isinstance(item, Mapping)
            )
            raise ManualFinalSubtitleEditError(
                "这条字幕找不到满足语法、停顿、900ms 和固定字号的安全分页。"
                + (f"（{reasons}）" if reasons else "")
            ) from exc

        current_rows = list(self._display_page_model_data().values())
        if not current_rows:
            raise ManualFinalSubtitleEditError("当前实际分页不完整，不能人工拆分。")
        rebuilt_pages = [
            dict(page)
            for page in rebuilt_plan.get("pages") or []
            if isinstance(page, Mapping)
        ]
        if len(rebuilt_pages) != requested:
            raise ManualFinalSubtitleEditError("人工分页重建后的页面数量不一致。")

        current_parent_rows = [
            row
            for row in current_rows
            if str(row.get("manual_cue_id") or "") == parent_id
        ]
        same_page_identity = len(current_parent_rows) == len(rebuilt_pages) and all(
            str(row.get("display_page_id") or "")
            == str(page.get("display_page_id") or "")
            and int(row.get("word_start", -1)) == int(page.get("word_start", -2))
            and int(row.get("word_end", -1)) == int(page.get("word_end", -2))
            and self._normalised_tokens(row.get("original_subtitle"))
            == self._normalised_tokens(page.get("english"))
            for row, page in zip(current_parent_rows, rebuilt_pages)
        )
        if same_page_identity:
            return {
                "parent_subtitle_id": parent_id,
                "page_count": requested,
                "display_page_ids": [
                    str(page["display_page_id"]) for page in rebuilt_pages
                ],
                "word_ranges": [
                    [int(page["word_start"]), int(page["word_end"])]
                    for page in rebuilt_pages
                ],
                "chinese_review_required": any(
                    bool(row.get("chinese_review_required"))
                    for row in current_parent_rows
                ),
                "changed": False,
            }

        new_edits: List[Dict[str, Any]] = []
        inserted_parent = False
        for row in current_rows:
            row_parent_id = str(row.get("manual_cue_id") or "")
            if row_parent_id == parent_id:
                if inserted_parent:
                    continue
                for page in rebuilt_pages:
                    new_edits.append(
                        {
                            "display_page_id": str(page["display_page_id"]),
                            "parent_subtitle_id": parent_id,
                            "word_start": int(page["word_start"]),
                            "word_end": int(page["word_end"]),
                            "english": str(page.get("english") or ""),
                            "chinese": "",
                            "chinese_review_required": True,
                        }
                    )
                inserted_parent = True
                continue
            new_edits.append(self._unchanged_display_page_edit_from_model_row(row))
        if not inserted_parent:
            raise ManualFinalSubtitleEditError("当前实际分页没有覆盖所选父字幕。")

        before = copy.deepcopy(self.cues)
        self._record_history(
            "split_parent_into_display_pages",
            before,
            parent_subtitle_id=parent_id,
            page_count=requested,
        )
        self.display_page_boundary_overrides[parent_id] = [
            int(page["word_start"]) for page in rebuilt_pages[1:]
        ]
        self.display_page_edits = new_edits
        cue["chinese_review_required"] = True
        return {
            "parent_subtitle_id": parent_id,
            "page_count": requested,
            "display_page_ids": [
                str(page["display_page_id"]) for page in rebuilt_pages
            ],
            "word_ranges": [
                [int(page["word_start"]), int(page["word_end"])]
                for page in rebuilt_pages
            ],
            "chinese_review_required": True,
            "changed": True,
        }

    def _preview_tail_trim_at_word(
        self,
        first_removed_word_id: int,
        *,
        first_removed_display_page_id: str = "",
    ) -> Dict[str, Any]:
        """Return one non-mutating tail cut at an authoritative word boundary."""
        boundary = int(first_removed_word_id)
        if boundary <= 0 or boundary >= len(self.word_ledger):
            raise ManualFinalSubtitleEditError(
                "尾部删除必须至少保留一个已说出的词，并删除后续内容。"
            )
        cue_index = next(
            (
                index
                for index, cue in enumerate(self.cues)
                if int(cue["word_start"]) <= boundary <= int(cue["word_end"])
            ),
            -1,
        )
        if cue_index < 0:
            raise ManualFinalSubtitleEditError("删除位置不属于当前固定字幕词范围。")
        first_removed = self.cues[cue_index]
        partial_parent_trim = boundary > int(first_removed["word_start"])
        if not partial_parent_trim and cue_index <= 0:
            raise ManualFinalSubtitleEditError("不能从第一条字幕开头删除全部内容。")
        source = self._tail_trim_source_media_path()
        if source is None or not source.is_file():
            raise ManualFinalSubtitleEditError("找不到原始音频，不能安全裁剪尾部。")
        kept_word_end_ms = self._word_end_time(boundary - 1)
        removed_word_start_ms = self._word_start_time(boundary)
        if removed_word_start_ms < kept_word_end_ms:
            raise ManualFinalSubtitleEditError(
                "保留内容与待删除内容的词时间重叠，找不到安全尾部切点。"
            )
        cut_ms = int(round((kept_word_end_ms + removed_word_start_ms) / 2))
        first_fully_removed_index = cue_index + (1 if partial_parent_trim else 0)
        removed_ids = [
            str(cue.get("cue_id") or "")
            for cue in self.cues[first_fully_removed_index:]
        ]
        kept_last = (
            first_removed if partial_parent_trim else self.cues[cue_index - 1]
        )
        return {
            "source_media_path": str(source.resolve()),
            "source_media_sha256": file_sha256(source),
            "cut_ms": cut_ms,
            "safe_gap_start_ms": kept_word_end_ms,
            "safe_gap_end_ms": removed_word_start_ms,
            "first_removed_word_id": boundary,
            "first_removed_cue_index": cue_index,
            "first_removed_display_page_id": str(
                first_removed_display_page_id or ""
            ),
            "partial_parent_trim": partial_parent_trim,
            "kept_last_subtitle_id": str(kept_last.get("cue_id") or ""),
            "first_removed_subtitle_id": str(first_removed.get("cue_id") or ""),
            "removed_subtitle_ids": removed_ids,
            "preview_start_ms": max(0, cut_ms - 3000),
            "preview_end_ms": cut_ms + 2000,
        }

    def preview_tail_trim(self, first_removed_index: int) -> Dict[str, Any]:
        """Return a cue-boundary tail cut without changing session state."""
        index = int(first_removed_index)
        if index <= 0 or index >= len(self.cues):
            raise ManualFinalSubtitleEditError(
                "尾部删除必须至少保留第一条字幕，并从后续父字幕开始。"
            )
        return self._preview_tail_trim_at_word(
            int(self.cues[index]["word_start"])
        )

    def preview_tail_trim_from_display_page(
        self,
        display_page_id_value: str,
    ) -> Dict[str, Any]:
        page_id = str(display_page_id_value or "").strip()
        page = next(
            (
                row
                for row in self._display_page_model_data().values()
                if str(row.get("display_page_id") or "") == page_id
                and not row.get("display_page_unavailable")
            ),
            None,
        )
        if page is None:
            raise ManualFinalSubtitleEditError("找不到可裁剪的实际分页。")
        return self._preview_tail_trim_at_word(
            int(page["word_start"]),
            first_removed_display_page_id=page_id,
        )

    def trim_tail_from_cue(self, first_removed_index: int) -> Dict[str, Any]:
        """Remove a cue suffix and retain a reversible, non-destructive cut decision."""
        decision = self.preview_tail_trim(first_removed_index)
        return self._apply_tail_trim_decision(decision)

    def trim_tail_from_display_page(
        self,
        display_page_id_value: str,
    ) -> Dict[str, Any]:
        """Trim from one actual page while retaining earlier pages of its parent."""
        decision = self.preview_tail_trim_from_display_page(
            display_page_id_value
        )
        return self._apply_tail_trim_decision(decision)

    def _apply_tail_trim_decision(
        self,
        decision: Mapping[str, Any],
    ) -> Dict[str, Any]:
        decision = copy.deepcopy(dict(decision))
        decision["source_formal_word_ledger_hash"] = self._formal_word_ledger_hash(
            self.word_ledger
        )
        index = int(decision["first_removed_cue_index"])
        boundary = int(decision["first_removed_word_id"])
        partial_parent_trim = bool(decision.get("partial_parent_trim"))
        previous_page_rows = list(self._display_page_model_data().values())
        before_cues = copy.deepcopy(self.cues)
        before_word_ledger = copy.deepcopy(self.word_ledger)
        before_hash = self.source_word_ledger_hash
        self._record_history(
            "trim_tail_from_cue",
            before_cues,
            first_removed_index=index,
            first_removed_word_id=boundary,
            first_removed_display_page_id=str(
                decision.get("first_removed_display_page_id") or ""
            ),
            before_word_ledger=before_word_ledger,
            before_source_word_ledger_hash=before_hash,
            before_source_media_path=(
                str(self.source_media_path.resolve())
                if self.source_media_path is not None
                else ""
            ),
            before_artifact_dir=str(self.artifact_dir.resolve()),
        )

        if partial_parent_trim:
            retained = self.cues[index]
            retained_id = str(retained.get("cue_id") or "")
            retained["word_end"] = boundary - 1
            retained["end_time"] = self._word_end_time(boundary - 1)
            retained["original_subtitle"] = self._words_text(
                self.word_ledger,
                int(retained["word_start"]),
                boundary - 1,
            )
            retained_pages = [
                row
                for row in previous_page_rows
                if str(row.get("manual_cue_id") or "") == retained_id
                and int(row.get("word_end", -1)) < boundary
            ]
            retained["translated_subtitle"] = "".join(
                str(row.get("translated_subtitle") or "").strip()
                for row in retained_pages
            )
            retained["chinese_review_required"] = not retained_pages or any(
                not str(row.get("translated_subtitle") or "").strip()
                or (
                    bool(row.get("display_page_chinese_stale"))
                    and not bool(row.get("display_page_chinese_confirmed"))
                )
                for row in retained_pages
            )
            kept = self.cues[: index + 1]
        else:
            kept = self.cues[:index]
        kept_word_end = int(kept[-1]["word_end"])
        kept_ids = {str(cue.get("cue_id") or "") for cue in kept}
        self.cues = kept
        self.word_ledger = self.word_ledger[: boundary]
        self.source_word_ledger_hash = stable_payload_hash(
            self._ledger_payload(self.word_ledger)
        )
        if partial_parent_trim and previous_page_rows:
            self.display_page_edits = [
                self._unchanged_display_page_edit_from_model_row(row)
                for row in previous_page_rows
                if str(row.get("manual_cue_id") or "") in kept_ids
                and int(row.get("word_end", -1)) <= kept_word_end
            ]
        else:
            self.display_page_edits = [
                item
                for item in self.display_page_edits
                if str(item.get("parent_subtitle_id") or "") in kept_ids
            ]
        self.display_page_boundary_overrides = {
            parent_id: [start for start in starts if int(start) < boundary]
            for parent_id, starts in self.display_page_boundary_overrides.items()
            if parent_id in kept_ids
        }
        decision["decision_hash"] = stable_payload_hash(
            {
                "source_media_sha256": decision["source_media_sha256"],
                "cut_ms": decision["cut_ms"],
                "first_removed_subtitle_id": decision[
                    "first_removed_subtitle_id"
                ],
                "first_removed_word_id": boundary,
                "first_removed_display_page_id": decision.get(
                    "first_removed_display_page_id", ""
                ),
                "removed_subtitle_ids": decision["removed_subtitle_ids"],
            }
        )
        self.tail_trim = decision
        self._validate_cues()
        self._validate_display_page_boundary_overrides()
        return copy.deepcopy(decision)

    def _tail_trim_source_media_path(self) -> Path | None:
        original = str(self.tail_trim.get("source_media_path") or "").strip()
        if original:
            candidate = Path(original)
            if candidate.is_file():
                return candidate
        if self.source_media_path is not None and self.source_media_path.is_file():
            return self.source_media_path
        for anchor in (
            self.loaded_subtitle_path,
            self.subtitle_path,
            self.manifest_path,
        ):
            inferred = self._source_media_from_result_directory(Path(anchor))
            if inferred is not None:
                return inferred
        return None

    def _recover_display_page_artifact_from_complete_edits(self) -> Dict[str, Any]:
        """Rebuild an editor-only page model from exact saved word ranges."""
        from app.core.subtitle_processor.stable_display_page_contract import (
            DISPLAY_PAGE_PLANNER_VERSION,
            DISPLAY_PAGE_SCHEMA_VERSION,
        )
        from app.core.utils.podcast_learning_video import (
            RenderStructuralOverflowError,
            article_display_page_layout_profile,
            rebuild_article_frozen_page_plan_from_word_ranges,
        )

        if not self.display_page_edits:
            return {}
        edits_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        seen_page_ids: set[str] = set()
        try:
            for raw_edit in self.display_page_edits:
                if not isinstance(raw_edit, Mapping):
                    return {}
                edit = dict(raw_edit)
                page_id = str(edit.get("display_page_id") or "")
                parent_id = str(edit.get("parent_subtitle_id") or "")
                if not page_id or not parent_id or page_id in seen_page_ids:
                    return {}
                seen_page_ids.add(page_id)
                edits_by_parent.setdefault(parent_id, []).append(edit)

            cue_ids = {
                str(cue.get("cue_id") or "")
                for cue in self.cues
                if str(cue.get("cue_id") or "")
            }
            if set(edits_by_parent) != cue_ids:
                return {}

            boundary_payload = self._validated_display_boundary_evidence()
            boundary_items = dict(boundary_payload.get("boundaries") or {})
            render_plans: List[Dict[str, Any]] = []
            parents: List[Dict[str, Any]] = []
            for cue_index, cue in enumerate(self.cues):
                parent_id = str(cue.get("cue_id") or "")
                parent_edits = sorted(
                    edits_by_parent[parent_id],
                    key=lambda item: int(item.get("word_start", -1)),
                )
                expected_word_start = int(cue["word_start"])
                page_ranges: List[tuple[int, int]] = []
                for page_index, edit in enumerate(parent_edits, 1):
                    word_start = int(edit.get("word_start", -1))
                    word_end = int(edit.get("word_end", -1))
                    expected_page_id = display_page_id(parent_id, page_index)
                    expected_english = self._words_text(
                        self.word_ledger,
                        word_start,
                        word_end,
                    )
                    if (
                        str(edit.get("display_page_id") or "") != expected_page_id
                        or word_start != expected_word_start
                        or word_end < word_start
                        or word_end > int(cue["word_end"])
                        or self._normalised_tokens(edit.get("english"))
                        != self._normalised_tokens(expected_english)
                    ):
                        return {}
                    page_ranges.append((word_start, word_end))
                    expected_word_start = word_end + 1
                if expected_word_start - 1 != int(cue["word_end"]):
                    return {}

                render_cue = self._article_render_cue(cue_index, boundary_items)
                page_translations = {
                    str(edit["display_page_id"]): str(
                        edit.get("chinese")
                        or edit.get("stale_chinese_draft")
                        or ""
                    )
                    for edit in parent_edits
                }
                rebuilt = rebuild_article_frozen_page_plan_from_word_ranges(
                    render_cue,
                    {
                        "pages": [
                            {"display_page_id": display_page_id(parent_id, 1)}
                        ]
                    },
                    page_ranges,
                    page_translations,
                    allow_page_count_change=True,
                    allow_incomplete_page_translations=True,
                    allow_manual_review=True,
                )
                rebuilt_pages = list(rebuilt.get("pages") or [])
                if len(rebuilt_pages) != len(parent_edits):
                    return {}
                parent_pages: List[Dict[str, Any]] = []
                for page, edit in zip(rebuilt_pages, parent_edits):
                    if (
                        str(page.get("display_page_id") or "")
                        != str(edit.get("display_page_id") or "")
                        or int(page.get("word_start", -1))
                        != int(edit.get("word_start", -2))
                        or int(page.get("word_end", -1))
                        != int(edit.get("word_end", -2))
                        or self._normalised_tokens(page.get("english"))
                        != self._normalised_tokens(edit.get("english"))
                    ):
                        return {}
                    page["chinese"] = str(edit.get("chinese") or "").strip()
                    page["zh"] = page["chinese"]
                    parent_pages.append(
                        {
                            "display_page_id": str(page["display_page_id"]),
                            "word_start": int(page["word_start"]),
                            "word_end": int(page["word_end"]),
                            "english": str(page.get("english") or ""),
                        }
                    )
                rebuilt["pages"] = rebuilt_pages
                rebuilt["chinese"] = str(cue.get("translated_subtitle") or "")
                render_plans.append(rebuilt)
                if len(parent_pages) > 1:
                    parents.append(
                        {
                            "parent_subtitle_id": parent_id,
                            "english": str(cue.get("original_subtitle") or ""),
                            "chinese": str(cue.get("translated_subtitle") or ""),
                            "word_start": int(cue["word_start"]),
                            "word_end": int(cue["word_end"]),
                            "pages": parent_pages,
                        }
                    )
        except (
            KeyError,
            TypeError,
            ValueError,
            ManualFinalSubtitleEditError,
            RenderStructuralOverflowError,
        ):
            return {}

        return {
            "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
            "status": "REVIEW",
            "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
            "layout_profile": article_display_page_layout_profile(),
            "errors": [{"code": "manual_page_translation_required"}],
            "parents": parents,
            "render_plans": render_plans,
            "recovery_source": "complete_manual_page_edits",
        }

    def _effective_display_page_artifact(self) -> Dict[str, Any]:
        artifact_path = self.artifact_dir / "display-page-translations.json"
        try:
            artifact = self._read_json(artifact_path)
        except ManualFinalSubtitleEditError:
            return {}
        try:
            manifest = self._read_json(self.manifest_path)
        except ManualFinalSubtitleEditError:
            manifest = {}
        expected_artifact_hash = str(
            manifest.get("display_page_translation_sha256") or ""
        ).strip()
        if (
            expected_artifact_hash
            and file_sha256(artifact_path) != expected_artifact_hash
        ):
            return {}
        if str(artifact.get("status") or "") != "PASS":
            source_artifact = artifact
            try:
                draft_path = Path(
                    str(manifest.get("manual_draft_page_plan_path") or "")
                )
                expected_hash = str(
                    manifest.get("manual_draft_page_plan_sha256") or ""
                )
                if (
                    not draft_path.is_file()
                    or not expected_hash
                    or not self._same_path(draft_path.parent, self.artifact_dir)
                    or file_sha256(draft_path) != expected_hash
                ):
                    raise ManualFinalSubtitleEditError(
                        "人工草稿分页产物不可用。"
                    )
                artifact = self._read_json(draft_path)
            except (ManualFinalSubtitleEditError, OSError):
                artifact = source_artifact
            if (
                str(artifact.get("status") or "") != "REVIEW"
                and not (
                    str(artifact.get("status") or "") == "ERROR"
                    and artifact.get("render_plans")
                    and (artifact.get("parents") or artifact.get("errors"))
                )
            ):
                return self._recover_display_page_artifact_from_complete_edits()
        return dict(artifact)

    def _display_page_previews(self) -> Dict[str, List[Dict[str, Any]]]:
        artifact = self._effective_display_page_artifact()
        if not artifact:
            return {}
        allow_incomplete_page_chinese = str(artifact.get("status") or "") != "PASS"

        translation_errors_by_parent: Dict[str, set[str]] = {}
        translation_errors_by_page: Dict[str, set[str]] = {}
        for error in artifact.get("errors") or []:
            if not isinstance(error, Mapping):
                continue
            code = str(error.get("code") or "").strip()
            parent_id = str(error.get("parent_subtitle_id") or "").strip()
            page_id = str(error.get("display_page_id") or "").strip()
            if not parent_id and page_id and ".P" in page_id:
                parent_id = page_id.split(".P", 1)[0]
            if code and parent_id:
                translation_errors_by_parent.setdefault(parent_id, set()).add(code)
            if code and page_id:
                translation_errors_by_page.setdefault(page_id, set()).add(code)

        translated_pages: Dict[str, Dict[str, Any]] = {}
        translated_parent_chinese: Dict[str, str] = {}
        for parent in artifact.get("parents") or []:
            if not isinstance(parent, Mapping):
                continue
            parent_id = str(parent.get("parent_subtitle_id") or "")
            aggregate_chinese = str(parent.get("aggregate_chinese") or "")
            if parent_id and aggregate_chinese:
                translated_parent_chinese[parent_id] = aggregate_chinese
            for page in parent.get("pages") or []:
                if not isinstance(page, Mapping):
                    continue
                page_id = str(page.get("display_page_id") or "")
                if page_id:
                    translated_pages[page_id] = dict(page)

        cue_by_id = {
            str(cue.get("cue_id") or ""): cue
            for cue in self.cues
            if str(cue.get("cue_id") or "")
        }
        cue_index_by_id = {
            str(cue.get("cue_id") or ""): index
            for index, cue in enumerate(self.cues)
            if str(cue.get("cue_id") or "")
        }
        edited_pages = {
            str(item.get("display_page_id") or ""): dict(item)
            for item in self.display_page_edits
            if isinstance(item, Mapping)
            and str(item.get("display_page_id") or "")
        }
        previews: Dict[str, List[Dict[str, Any]]] = {}
        boundary_payload: Dict[str, Any] | None = None

        def recovered_page(
            raw_page: Mapping[str, Any], parent_id: str
        ) -> Dict[str, Any]:
            page_id = str(raw_page.get("display_page_id") or "")
            draft = dict(self.recovered_stale_page_drafts.get(page_id) or {})
            if not draft:
                return {}
            if (
                str(draft.get("parent_subtitle_id") or "")
                != parent_id
                or int(draft.get("word_start", -1))
                != int(raw_page.get("word_start", -2))
                or int(draft.get("word_end", -1))
                != int(raw_page.get("word_end", -2))
                or int(draft.get("start_ms", -1))
                != int(raw_page.get("start_ms", -2))
                or int(draft.get("end_ms", -1))
                != int(raw_page.get("end_ms", -2))
                or self._normalised_tokens(draft.get("english"))
                != self._normalised_tokens(raw_page.get("english"))
            ):
                return {}
            return draft

        for source_plan in artifact.get("render_plans") or []:
            if not isinstance(source_plan, Mapping):
                continue
            parent_id = str(source_plan.get("parent_subtitle_id") or "")
            plan: Mapping[str, Any] = source_plan
            subtitle_id = parent_id
            cue = cue_by_id.get(subtitle_id)
            override_starts = self.display_page_boundary_overrides.get(parent_id)
            if cue is None:
                self._display_page_preview_cache.pop(parent_id, None)
                continue
            parent_page_prefix = f"{parent_id}.P"
            parent_cache_key = stable_payload_hash(
                {
                    "source_word_ledger_hash": self.source_word_ledger_hash,
                    "cue_index": cue_index_by_id[parent_id],
                    "cue": cue,
                    "source_plan": source_plan,
                    "override_starts": override_starts,
                    "edited_pages": [
                        item
                        for item in self.display_page_edits
                        if str(item.get("parent_subtitle_id") or "") == parent_id
                    ],
                    "translated_pages": {
                        page_id: page
                        for page_id, page in translated_pages.items()
                        if page_id.startswith(parent_page_prefix)
                    },
                    "translated_parent_chinese": translated_parent_chinese.get(
                        parent_id,
                        "",
                    ),
                    "parent_errors": sorted(
                        translation_errors_by_parent.get(parent_id, set())
                    ),
                    "page_errors": {
                        page_id: sorted(codes)
                        for page_id, codes in translation_errors_by_page.items()
                        if page_id.startswith(parent_page_prefix)
                    },
                    "recovered_drafts": {
                        page_id: draft
                        for page_id, draft in self.recovered_stale_page_drafts.items()
                        if page_id.startswith(parent_page_prefix)
                    },
                    "allow_incomplete_page_chinese": allow_incomplete_page_chinese,
                    "boundary_evidence": (
                        {
                            "file": self._display_page_cache_file_token(
                                self.artifact_dir
                                / "display-boundary-evidence.json"
                            ),
                            "recovered": self.recovered_formal_boundary_evidence,
                        }
                        if override_starts is not None
                        else None
                    ),
                }
            )
            cached_parent = self._display_page_preview_cache.get(parent_id) or {}
            if str(cached_parent.get("key") or "") == parent_cache_key:
                previews[subtitle_id] = copy.deepcopy(
                    list(cached_parent.get("pages") or [])
                )
                continue
            if cue is not None and override_starts is not None:
                source_pages = [
                    dict(page)
                    for page in source_plan.get("pages") or []
                    if isinstance(page, Mapping)
                ]
                if not source_pages or len(override_starts) not in {0, 1, 2, 3}:
                    continue
                boundaries = [int(cue["word_start"]), *override_starts]
                ranges = [
                    (
                        start,
                        (
                            boundaries[index + 1] - 1
                            if index + 1 < len(boundaries)
                            else int(cue["word_end"])
                        ),
                    )
                    for index, start in enumerate(boundaries)
                ]
                page_translations = {}
                for index in range(len(ranges)):
                    page_id = display_page_id(parent_id, index + 1)
                    edited = edited_pages.get(page_id)
                    translated = translated_pages.get(page_id) or {}
                    page_translations[page_id] = (
                        str(edited.get("chinese") or "")
                        if edited is not None
                        else str(translated.get("zh") or "")
                    )
                try:
                    from app.core.utils.podcast_learning_video import (
                        RenderStructuralOverflowError,
                        rebuild_article_frozen_page_plan_from_word_ranges,
                    )

                    if boundary_payload is None:
                        boundary_payload = self._validated_display_boundary_evidence()
                    render_cue = self._article_render_cue(
                        self.cues.index(cue),
                        dict(boundary_payload.get("boundaries") or {}),
                    )
                    plan = rebuild_article_frozen_page_plan_from_word_ranges(
                        render_cue,
                        source_plan,
                        ranges,
                        page_translations,
                        allow_page_count_change=True,
                        allow_incomplete_page_translations=True,
                        allow_manual_review=True,
                    )
                except (RenderStructuralOverflowError, ManualFinalSubtitleEditError):
                    continue
            raw_pages = plan.get("pages")
            if cue is None or not isinstance(raw_pages, list) or not raw_pages:
                continue
            page_english = " ".join(
                str(page.get("english") or "").strip()
                for page in raw_pages
                if isinstance(page, Mapping)
            ).strip()
            if self._normalised_tokens(cue.get("original_subtitle")) != self._normalised_tokens(
                page_english or plan.get("english")
            ):
                continue
            current_chinese = re.sub(r"\s+", "", str(cue.get("translated_subtitle") or ""))
            source_page_chinese = [
                str(
                    (translated_pages.get(str(page.get("display_page_id") or "")) or {}).get("zh")
                    or page.get("chinese")
                    or page.get("zh")
                    or recovered_page(page, parent_id).get("chinese")
                    or ""
                )
                for page in raw_pages
                if isinstance(page, Mapping)
            ]
            page_aggregate_chinese = (
                "".join(source_page_chinese)
                if len(source_page_chinese) == len(raw_pages)
                and all(value.strip() for value in source_page_chinese)
                else ""
            )
            planned_chinese = re.sub(
                r"\s+",
                "",
                page_aggregate_chinese
                or translated_parent_chinese.get(subtitle_id, "")
                or str(plan.get("chinese") or ""),
            )
            parent_translation_stale = bool(
                planned_chinese and current_chinese != planned_chinese
            )
            pages: List[Dict[str, Any]] = []
            manual_page_override = parent_id in self.display_page_boundary_overrides
            local_parent_split_proposals: Dict[str, str] = {}
            if manual_page_override and len(raw_pages) > 1 and current_chinese:
                from app.core.utils.podcast_learning_video import (
                    _strict_split_chinese_visual_pages,
                )

                page_word_counts = [
                    int(page.get("word_end", -1))
                    - int(page.get("word_start", -1))
                    + 1
                    for page in raw_pages
                    if isinstance(page, Mapping)
                ]
                proposed_chinese_pages = _strict_split_chinese_visual_pages(
                    str(cue.get("translated_subtitle") or ""),
                    len(raw_pages),
                    page_word_counts,
                    strict=True,
                )
                if (
                    proposed_chinese_pages is not None
                    and len(proposed_chinese_pages) == len(raw_pages)
                    and re.sub(r"\s+", "", "".join(proposed_chinese_pages))
                    == current_chinese
                ):
                    local_parent_split_proposals = {
                        str(page.get("display_page_id") or ""): chinese
                        for page, chinese in zip(raw_pages, proposed_chinese_pages)
                        if isinstance(page, Mapping)
                        and str(page.get("display_page_id") or "")
                        and str(chinese or "").strip()
                    }
            for raw_page in raw_pages:
                if not isinstance(raw_page, Mapping):
                    pages = []
                    break
                page_id = str(raw_page.get("display_page_id") or "")
                translation_issue_codes = sorted(
                    translation_errors_by_parent.get(parent_id, set())
                    | translation_errors_by_page.get(page_id, set())
                )
                translated = translated_pages.get(page_id, {})
                recovered = recovered_page(raw_page, parent_id)
                edited = edited_pages.get(page_id)
                artifact_chinese = str(
                    translated.get("zh")
                    or raw_page.get("chinese")
                    or raw_page.get("zh")
                    or ""
                )
                recovered_chinese = str(recovered.get("chinese") or "")
                proposal_chinese = str(
                    local_parent_split_proposals.get(page_id) or ""
                )
                chinese_draft_kind = ""
                if edited is not None:
                    if (
                        str(edited.get("parent_subtitle_id") or "") != subtitle_id
                        or int(edited.get("word_start", -1))
                        != int(raw_page.get("word_start", -2))
                        or int(edited.get("word_end", -1))
                        != int(raw_page.get("word_end", -2))
                        or str(edited.get("english") or "")
                        != str(raw_page.get("english") or "")
                    ):
                        pages = []
                        break
                    edited_chinese = str(edited.get("chinese") or "")
                    stale_chinese = ""
                    if edited.get("chinese_stale_unconfirmed"):
                        saved_stale_chinese = str(
                            edited.get("stale_chinese_draft") or ""
                        )
                        saved_draft_kind = str(
                            edited.get("chinese_draft_kind") or ""
                        )
                        if (
                            saved_stale_chinese
                            and saved_draft_kind
                            == "manual_boundary_move_draft"
                        ):
                            stale_chinese = saved_stale_chinese
                            chinese_draft_kind = saved_draft_kind
                        elif recovered_chinese:
                            stale_chinese = recovered_chinese
                            chinese_draft_kind = (
                                "recovered_identity_matched_draft"
                            )
                        elif proposal_chinese:
                            stale_chinese = proposal_chinese
                            chinese_draft_kind = "local_parent_split_proposal"
                        elif saved_stale_chinese:
                            stale_chinese = saved_stale_chinese
                            chinese_draft_kind = (
                                saved_draft_kind
                                or "stale_artifact_page_draft"
                            )
                        elif artifact_chinese:
                            stale_chinese = artifact_chinese
                            chinese_draft_kind = "stale_artifact_page_draft"
                    elif not edited_chinese.strip() and recovered_chinese:
                        stale_chinese = recovered_chinese
                        chinese_draft_kind = "recovered_identity_matched_draft"
                    elif not edited_chinese.strip() and proposal_chinese:
                        stale_chinese = proposal_chinese
                        chinese_draft_kind = "local_parent_split_proposal"
                    elif (
                        parent_translation_stale
                        and not edited_chinese.strip()
                        and artifact_chinese
                    ):
                        stale_chinese = artifact_chinese
                        chinese_draft_kind = "stale_artifact_page_draft"
                    chinese_stale_draft = bool(stale_chinese)
                    chinese = stale_chinese if chinese_stale_draft else edited_chinese
                else:
                    if recovered_chinese:
                        chinese = recovered_chinese
                        chinese_stale_draft = True
                        chinese_draft_kind = "recovered_identity_matched_draft"
                    elif proposal_chinese:
                        chinese = proposal_chinese
                        chinese_stale_draft = True
                        chinese_draft_kind = "local_parent_split_proposal"
                    else:
                        chinese = artifact_chinese
                        chinese_stale_draft = bool(
                            chinese and parent_translation_stale
                        )
                        if chinese_stale_draft:
                            chinese_draft_kind = "stale_artifact_page_draft"
                if len(raw_pages) == 1 and (
                    not chinese or chinese_stale_draft
                ):
                    chinese = str(cue.get("translated_subtitle") or "")
                    chinese_stale_draft = bool(
                        chinese
                        and edited
                        and edited.get("chinese_stale_unconfirmed")
                        and str(edited.get("chinese_draft_kind") or "")
                        == "formal_boundary_reflow_draft"
                    )
                    if chinese_stale_draft:
                        chinese_draft_kind = (
                            chinese_draft_kind or "formal_boundary_reflow_draft"
                        )
                if (
                    not chinese
                    and not manual_page_override
                    and not allow_incomplete_page_chinese
                ):
                    pages = []
                    break
                pages.append(
                    {
                        "display_page_id": page_id,
                        "page_index": int(raw_page.get("page_index") or len(pages) + 1),
                        "word_start": int(raw_page.get("word_start", -1)),
                        "word_end": int(raw_page.get("word_end", -1)),
                        "english": str(raw_page.get("english") or ""),
                        "chinese": chinese,
                        "chinese_stale_draft": chinese_stale_draft,
                        "chinese_draft_kind": chinese_draft_kind,
                        "chinese_review_acknowledged": bool(
                            edited
                            and edited.get("chinese_review_acknowledged")
                        ),
                        "boundary_review_acknowledged": bool(
                            edited
                            and edited.get("boundary_review_acknowledged")
                        ),
                        "start_ms": int(raw_page.get("start_ms") or cue["start_time"]),
                        "end_ms": int(raw_page.get("end_ms") or cue["end_time"]),
                        "english_font_size": int(
                            raw_page.get("english_font_size")
                            or plan.get("english_font_size")
                            or 0
                        ),
                        "boundary_before": dict(raw_page.get("boundary_before") or {}),
                        "translation_issue_codes": translation_issue_codes,
                    }
                )
            if pages and (
                manual_page_override
                or allow_incomplete_page_chinese
                or any(page["chinese_stale_draft"] for page in pages)
                or re.sub(r"\s+", "", "".join(page["chinese"] for page in pages))
                == current_chinese
            ):
                previews[subtitle_id] = pages
                self._display_page_preview_cache[parent_id] = {
                    "key": parent_cache_key,
                    "pages": copy.deepcopy(pages),
                }
            else:
                self._display_page_preview_cache.pop(parent_id, None)
        active_parent_ids = {
            str(plan.get("parent_subtitle_id") or "")
            for plan in artifact.get("render_plans") or []
            if isinstance(plan, Mapping)
            and str(plan.get("parent_subtitle_id") or "")
        }
        self._display_page_preview_cache = {
            parent_id: cached
            for parent_id, cached in self._display_page_preview_cache.items()
            if parent_id in active_parent_ids
        }
        return previews

    def save_to_source_folder(
        self,
        *,
        source_media_path: str | Path | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> Dict[str, Any]:
        def report(percent: int, stage: str) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(int(percent), str(stage))
            except Exception:
                # Progress reporting must never invalidate an otherwise safe
                # package write from the background worker.
                pass

        self._validate_cues()
        self._validate_display_page_boundary_overrides()
        self._validate_no_silent_display_page_state_loss()
        report(5, "正在核对冻结字幕和词时间账本")
        source_dir = self.subtitle_path.parent
        media_candidate = source_media_path or self.source_media_path
        media_path = Path(media_candidate).resolve() if media_candidate else None
        if media_path is not None and not media_path.is_file():
            media_path = None
        user_media_path = self._tail_trim_source_media_path() if self.tail_trim else None
        if user_media_path is None or not user_media_path.is_file():
            user_media_path = media_path
        result_dir = media_result_dir(user_media_path) if user_media_path else None
        preferred_package_dir = (
            result_dir / "人工终稿字幕包"
            if result_dir is not None
            else source_dir / "人工终稿字幕包"
        )
        current_manifest = self._read_json(self.manifest_path)
        current_override = current_manifest.get("manual_final_override") or {}
        existing_override_path = Path(
            str(current_override.get("subtitle_path") or "")
        )
        reusing_owned_package = bool(
            int(current_override.get("schema_version") or 0) >= 2
            and existing_override_path.is_file()
            and self._same_path(existing_override_path, self.subtitle_path)
            and self._same_path(self.manifest_path.parent, self.subtitle_path.parent)
            and self._same_path(self.manifest_path.parent, preferred_package_dir)
        )
        package_dir = (
            self.manifest_path.parent
            if reusing_owned_package
            else preferred_package_dir
        )
        if self.tail_trim:
            trim_source = self._tail_trim_source_media_path()
            if trim_source is None or not trim_source.is_file():
                raise ManualFinalSubtitleEditError(
                    "尾部裁剪记录缺少原始音频，无法保存派生终稿包。"
                )
            expected_source_hash = str(
                self.tail_trim.get("source_media_sha256") or ""
            )
            if (
                not expected_source_hash
                or file_sha256(trim_source) != expected_source_hash
            ):
                raise ManualFinalSubtitleEditError(
                    "原始音频已变化，尾部裁剪决定已失效。"
                )
            package_dir.mkdir(parents=True, exist_ok=True)
            trim_audio_path = package_dir / f"{trim_source.stem}-尾部裁剪.m4a"
            trim_record_path = package_dir / "tail-trim.json"
            reuse_trimmed_audio = False
            if trim_audio_path.is_file() and trim_record_path.is_file():
                try:
                    trim_record = self._read_json(trim_record_path)
                    reuse_trimmed_audio = bool(
                        str(trim_record.get("decision_hash") or "")
                        == str(self.tail_trim.get("decision_hash") or "")
                        and str(trim_record.get("derived_media_sha256") or "")
                        == file_sha256(trim_audio_path)
                    )
                except ManualFinalSubtitleEditError:
                    reuse_trimmed_audio = False
            if not reuse_trimmed_audio:
                report(10, "正在生成非破坏式尾部裁剪音频")
                _materialize_tail_trim_audio(
                    trim_source,
                    trim_audio_path,
                    int(self.tail_trim["cut_ms"]),
                )
            trim_record = {
                **self.tail_trim,
                "derived_media_path": str(trim_audio_path),
                "derived_media_sha256": file_sha256(trim_audio_path),
            }
            write_json_artifact(trim_record_path, trim_record)
            self.tail_trim = trim_record
            media_path = trim_audio_path.resolve()
        srt_path = package_dir / "人工终稿字幕.srt"
        display_page_srt_path = package_dir / "人工终稿分页双语字幕.srt"
        display_page_map_path = package_dir / "人工终稿分页映射.json"
        edit_path = package_dir / "人工终稿字幕-edits.json"
        artifact_dir = package_dir / "人工终稿字幕-artifacts"
        report(
            18,
            (
                "正在复用冻结分页，仅重建人工调整项"
                if self.display_page_edits
                else "正在复用冻结分页；边界变化时才重新规划全片"
            ),
        )
        render_contract = self._write_manual_render_contract(artifact_dir)
        review_summary = self.display_page_review_summary()
        report(70, "实际分页检查完成，正在写入双语字幕")
        self._write_bilingual_srt(srt_path)
        source_paths = current_manifest.get("source_subtitle_paths") or {}
        source_hashes = current_manifest.get("source_subtitle_paths_sha256") or {}

        def immutable_source_path(*keys: str) -> Path | None:
            for key in keys:
                value = str(source_paths.get(key) or "").strip()
                expected_hash = str(source_hashes.get(key) or "").strip().lower()
                if not value or not expected_hash:
                    continue
                candidate = Path(value)
                if (
                    candidate.is_file()
                    and file_sha256(candidate).lower() == expected_hash
                ):
                    return candidate.resolve()
            return None

        source_bilingual_path = immutable_source_path(
            "named_bilingual_original_top_srt",
            "bilingual_original_top_srt",
        )
        final_timeline_path = artifact_dir / "final-cue-timeline.json"
        word_ledger_path = artifact_dir / "word-ledger.json"
        edit_payload = {
            "schema_version": 2,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_subtitle": str(self.subtitle_path),
            "source_artifact_dir": str(self.artifact_dir),
            "source_word_ledger_hash": self.source_word_ledger_hash,
            "word_ledger": self.word_ledger,
            "cues": self.cues,
            "history": self.history,
            "display_page_edits": self.display_page_edits,
            "display_page_boundary_overrides": self.display_page_boundary_overrides,
            "recovered_stale_page_drafts": self.recovered_stale_page_drafts,
            "tail_trim": self.tail_trim,
            "source_media_path": str(media_path) if media_path else "",
        }
        report(80, "正在保存可撤销编辑记录")
        write_json_artifact(edit_path, edit_payload)
        edit_artifact_sha256 = file_sha256(edit_path)
        exported_page_paths = {"srt": "", "map": ""}
        if not render_contract["render_blocked"]:
            report(86, "正在导出实际分页字幕和映射")
            exported_page_paths = self._write_display_page_exports(
                display_page_srt_path,
                display_page_map_path,
                render_contract["display_artifact"],
                source_parent_subtitle_path=srt_path,
            )
        immutable_page_srt = immutable_source_path("display_page_bilingual_srt")
        immutable_page_map = immutable_source_path("display_page_map")
        source_display_page_paths = {
            "srt": str(immutable_page_srt) if immutable_page_srt else "",
            "map": str(immutable_page_map) if immutable_page_map else "",
        }
        manual_override = {
            "schema_version": 3,
            "subtitle_path": str(srt_path),
            "subtitle_sha256": file_sha256(srt_path),
            "edit_artifact_path": str(edit_path),
            "edit_artifact_sha256": edit_artifact_sha256,
            "artifact_dir": str(artifact_dir),
            "final_cue_timeline_path": str(final_timeline_path),
            "final_cue_timeline_sha256": file_sha256(final_timeline_path),
            "word_ledger_path": str(word_ledger_path),
            "word_ledger_sha256": file_sha256(word_ledger_path),
            "display_page_translation_path": str(
                artifact_dir / "display-page-translations.json"
            ),
            "display_boundary_evidence_path": str(
                artifact_dir / "display-boundary-evidence.json"
            ),
            "display_page_srt_path": exported_page_paths["srt"],
            "display_page_srt_sha256": (
                file_sha256(Path(exported_page_paths["srt"]))
                if exported_page_paths["srt"]
                else ""
            ),
            "display_page_map_path": exported_page_paths["map"],
            "display_page_map_sha256": (
                file_sha256(Path(exported_page_paths["map"]))
                if exported_page_paths["map"]
                else ""
            ),
            "manual_draft_page_plan_path": render_contract[
                "manual_draft_page_plan_path"
            ],
            "manual_draft_page_plan_sha256": render_contract[
                "manual_draft_page_plan_sha256"
            ],
            "render_blocked": bool(render_contract["render_blocked"]),
            "render_block_reason": render_contract["render_block_reason"],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "source_word_ledger_hash": self.source_word_ledger_hash,
            "manual_cue_count": len(self.cues),
            "source_media_path": str(media_path) if media_path else "",
            "tail_trim": self.tail_trim,
            "chinese_review_required_count": sum(
                bool(cue.get("chinese_review_required")) for cue in self.cues
            ),
            "display_page_review_summary": review_summary,
        }
        manual_manifest = {
            "schema_version": 2,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "stable_run_id": (
                "manual-"
                + stable_payload_hash(
                    {
                        "cues": self.cues,
                        "tail_trim_decision_hash": self.tail_trim.get(
                            "decision_hash", ""
                        ),
                    }
                )[:16]
            ),
            # This manifest owns the files in the manual package, so its run
            # directory must match the package containing the published SRT.
            "stable_run_dir": str(package_dir),
            "validation_status": (
                "failed" if render_contract["render_blocked"] else "passed"
            ),
            "render_blocked": bool(render_contract["render_blocked"]),
            "validation_error_codes": (
                [render_contract["render_block_reason"]]
                if render_contract["render_blocked"]
                else []
            ),
            "paths": {
                "original_top_srt": str(srt_path),
                **(
                    {"display_page_bilingual_srt": exported_page_paths["srt"]}
                    if exported_page_paths["srt"]
                    else {}
                ),
            },
            "paths_sha256": {
                "original_top_srt": file_sha256(srt_path),
                **(
                    {
                        "display_page_bilingual_srt": file_sha256(
                            Path(exported_page_paths["srt"])
                        )
                    }
                    if exported_page_paths["srt"]
                    else {}
                ),
            },
            "source_subtitle_paths": {
                **(
                    {"bilingual_original_top_srt": str(source_bilingual_path)}
                    if source_bilingual_path is not None
                    else {}
                ),
                **(
                    {
                        "display_page_bilingual_srt": source_display_page_paths[
                            "srt"
                        ],
                        "display_page_map": source_display_page_paths["map"],
                    }
                    if source_display_page_paths["srt"]
                    else {}
                ),
            },
            "final_cue_timeline_path": str(final_timeline_path),
            "final_cue_timeline_sha256": file_sha256(final_timeline_path),
            "word_ledger_path": str(word_ledger_path),
            "word_ledger_sha256": file_sha256(word_ledger_path),
            "display_page_translation_path": str(
                artifact_dir / "display-page-translations.json"
            ),
            "display_page_translation_status": render_contract["display_status"],
            "display_page_translation_contract_hash": render_contract[
                "display_contract_hash"
            ],
            "display_page_translation_sha256": file_sha256(
                artifact_dir / "display-page-translations.json"
            ),
            "display_boundary_evidence_path": str(
                artifact_dir / "display-boundary-evidence.json"
            ),
            "display_boundary_evidence_sha256": file_sha256(
                artifact_dir / "display-boundary-evidence.json"
            ),
            "display_page_map_path": exported_page_paths["map"],
            "display_page_map_sha256": (
                file_sha256(Path(exported_page_paths["map"]))
                if exported_page_paths["map"]
                else ""
            ),
            "manual_draft_page_plan_path": render_contract[
                "manual_draft_page_plan_path"
            ],
            "manual_draft_page_plan_sha256": render_contract[
                "manual_draft_page_plan_sha256"
            ],
            "manual_final_override": manual_override,
            "display_page_review_summary": review_summary,
            "source_media_path": str(media_path) if media_path else "",
            "tail_trim": self.tail_trim,
        }
        manual_manifest["source_subtitle_paths_sha256"] = {
            key: file_sha256(Path(value))
            for key, value in manual_manifest["source_subtitle_paths"].items()
            if value
        }
        package_manifest_path = package_dir / "stable-final-manifest.json"
        report(96, "正在校验并发布人工终稿包")
        write_json_artifact(package_manifest_path, manual_manifest)
        report(100, "人工终稿包已保存")
        return {
            "subtitle_path": str(srt_path),
            "edit_artifact_path": str(edit_path),
            "artifact_dir": str(artifact_dir),
            "manifest_path": str(package_manifest_path),
            "source_media_path": str(media_path) if media_path else "",
            "tail_trim": self.tail_trim,
            "render_blocked": bool(render_contract["render_blocked"]),
            "render_block_reason": render_contract["render_block_reason"],
            "display_page_srt_path": exported_page_paths["srt"],
            "display_page_map_path": exported_page_paths["map"],
            "source_display_page_srt_path": source_display_page_paths["srt"],
            "source_display_page_map_path": source_display_page_paths["map"],
            "manual_draft_ready": bool(
                render_contract["manual_draft_page_plan_path"]
            ),
            "manual_draft_page_plan_path": render_contract[
                "manual_draft_page_plan_path"
            ],
            "manual_draft_page_plan_sha256": render_contract[
                "manual_draft_page_plan_sha256"
            ],
            "display_page_review_summary": review_summary,
            "source_bilingual_original_top_srt": (
                str(source_bilingual_path) if source_bilingual_path is not None else ""
            ),
        }

    def _source_page_units(self) -> List[Dict[str, Any]]:
        spans = self._read_json(self.artifact_dir / "subtitle-spans.json")
        translations = self._read_json(self.artifact_dir / "translations.json")
        try:
            display_artifact = self._read_json(
                self.artifact_dir / "display-page-translations.json"
            )
        except ManualFinalSubtitleEditError:
            display_artifact = {}
        translated_by_id = {
            str(item.get("subtitle_id") or ""): item
            for item in translations
            if isinstance(item, Mapping)
        }
        display_by_id = {
            str(item.get("parent_subtitle_id") or ""): item
            for item in (display_artifact.get("parents") or [])
            if isinstance(item, Mapping)
        }
        units: List[Dict[str, Any]] = []
        for span in spans:
            if not isinstance(span, Mapping):
                continue
            subtitle_id = str(span.get("subtitle_id") or "")
            display_parent = display_by_id.get(subtitle_id)
            if display_parent:
                for page in display_parent.get("pages") or []:
                    if isinstance(page, Mapping):
                        units.append(
                            {
                                "display_page_id": str(
                                    page.get("display_page_id") or ""
                                ),
                                "parent_subtitle_id": subtitle_id,
                                "word_start": int(page["word_start"]),
                                "word_end": int(page["word_end"]),
                                "english": str(page.get("english") or ""),
                                "chinese": str(page.get("zh") or ""),
                            }
                        )
                continue
            translated = translated_by_id.get(subtitle_id, {})
            units.append(
                {
                    "word_start": int(span["word_start"]),
                    "word_end": int(span["word_end"]),
                    "english": str(
                        span.get("original")
                        or translated.get("text")
                        or ""
                    ),
                    "chinese": str(translated.get("translated_text") or ""),
                }
            )
        return sorted(units, key=lambda item: int(item["word_start"]))

    def _source_semantic_page_translations(
        self,
    ) -> Dict[str, Dict[str, Any]]:
        """Return only source pages whose identity can be verified exactly."""
        result: Dict[str, Dict[str, Any]] = {}
        for unit in self._source_page_units():
            page_id = str(unit.get("display_page_id") or "")
            parent_id = str(unit.get("parent_subtitle_id") or "")
            chinese = str(unit.get("chinese") or "").strip()
            if not page_id or not parent_id or not chinese or page_id in result:
                continue
            result[page_id] = {
                "display_page_id": page_id,
                "parent_subtitle_id": parent_id,
                "word_start": int(unit["word_start"]),
                "word_end": int(unit["word_end"]),
                "english": str(unit.get("english") or ""),
                "chinese": chinese,
            }
        return result

    def _visible_display_page_translations(
        self,
    ) -> Dict[str, Dict[str, Any]]:
        """Return the exact page text currently visible in the manual editor."""
        result: Dict[str, Dict[str, Any]] = {}
        for parent_id, pages in self._display_page_previews().items():
            for page in pages:
                page_id = str(page.get("display_page_id") or "")
                chinese = str(page.get("chinese") or "").strip()
                if not page_id or not parent_id or not chinese or page_id in result:
                    continue
                result[page_id] = {
                    "display_page_id": page_id,
                    "parent_subtitle_id": str(parent_id),
                    "word_start": int(page["word_start"]),
                    "word_end": int(page["word_end"]),
                    "english": str(page.get("english") or ""),
                    "chinese": chinese,
                }
        return result

    def _reuse_source_page_translations(
        self,
        parents: Sequence[Mapping[str, Any]],
    ) -> Dict[str, List[Dict[str, str]]] | None:
        if not parents:
            return {"pages": []}
        units = self._source_page_units()
        by_start = {int(unit["word_start"]): unit for unit in units}
        response_pages: List[Dict[str, str]] = []
        for parent in parents:
            aggregate = ""
            for page in parent.get("pages") or []:
                page_start = int(page["word_start"])
                page_end = int(page["word_end"])
                cursor = page_start
                english_parts: List[str] = []
                chinese_parts: List[str] = []
                while cursor <= page_end:
                    unit = by_start.get(cursor)
                    if unit is None or int(unit["word_end"]) > page_end:
                        return None
                    english_parts.append(str(unit.get("english") or ""))
                    chinese_parts.append(str(unit.get("chinese") or ""))
                    cursor = int(unit["word_end"]) + 1
                if cursor - 1 != page_end:
                    return None
                expected_english = " ".join(str(page.get("english") or "").split())
                source_english = " ".join(" ".join(english_parts).split())
                chinese = re.sub(r"\s+", "", "".join(chinese_parts))
                if source_english != expected_english or not chinese:
                    return None
                aggregate += chinese
                response_pages.append(
                    {
                        "display_page_id": str(page.get("display_page_id") or ""),
                        "zh": chinese,
                    }
                )
            if aggregate != re.sub(r"\s+", "", str(parent.get("chinese") or "")):
                return None
        return {"pages": response_pages}

    def _display_page_edit_translation_response(
        self,
        parents: Sequence[Mapping[str, Any]],
        render_plans: Sequence[Mapping[str, Any]],
    ) -> Dict[str, List[Dict[str, str]]] | None:
        if not self.display_page_edits:
            return None
        edits = {
            str(item.get("display_page_id") or ""): item
            for item in self.display_page_edits
            if isinstance(item, Mapping)
        }
        expected_pages = {
            str(page.get("display_page_id") or ""): (
                str(plan.get("parent_subtitle_id") or ""),
                page,
            )
            for plan in render_plans
            if isinstance(plan, Mapping)
            for page in plan.get("pages") or []
            if isinstance(page, Mapping)
            and str(page.get("display_page_id") or "")
        }
        if set(edits) != set(expected_pages):
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: "
                "人工逐页中文对应的页面集合已被重新规划。"
            )
        for page_id, (parent_id, page) in expected_pages.items():
            edited = edits[page_id]
            if (
                str(edited.get("parent_subtitle_id") or "") != parent_id
                or int(edited.get("word_start", -1))
                != int(page.get("word_start", -2))
                or int(edited.get("word_end", -1))
                != int(page.get("word_end", -2))
                or str(edited.get("english") or "")
                != str(page.get("english") or "")
                or bool(edited.get("chinese_stale_unconfirmed"))
                or not str(edited.get("chinese") or "").strip()
            ):
                raise ManualFinalSubtitleEditError(
                    "manual_page_translation_required: "
                    "人工逐页中文与重新校验后的页面 ID 或词范围不一致。"
                )
        response_pages: List[Dict[str, str]] = []
        for parent in parents:
            parent_id = str(parent.get("parent_subtitle_id") or "")
            for page in parent.get("pages") or []:
                page_id = str(page.get("display_page_id") or "")
                edited = edits.get(page_id)
                if edited is None:
                    raise ManualFinalSubtitleEditError(
                        "manual_page_translation_required: "
                        "人工逐页中文与重新校验后的页面 ID 或词范围不一致。"
                    )
                response_pages.append(
                    {
                        "display_page_id": page_id,
                        "zh": str(edited.get("chinese") or "").strip(),
                    }
                )
        return {"pages": response_pages}

    @classmethod
    def _formal_word_ledger_hash(
        cls,
        ledger: Sequence[Mapping[str, Any]],
    ) -> str:
        payload = [
            [
                str(word.get("surface", word.get("token", "")) or ""),
                str(word.get("normalized", word.get("token", "")) or ""),
                int(word.get("start_ms", word.get("start_time", 0)) or 0),
                int(word.get("end_ms", word.get("end_time", 0)) or 0),
            ]
            for word in ledger
        ]
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _validated_display_boundary_evidence(self) -> Dict[str, Any]:
        path = self.artifact_dir / "display-boundary-evidence.json"
        try:
            payload = self._read_json(path)
        except ManualFinalSubtitleEditError as exc:
            raise ManualFinalSubtitleEditError(
                "manual_page_boundary_evidence_required: "
                "稳定产物缺少冻结分页边界证据。"
            ) from exc
        expected_hash = self._formal_word_ledger_hash(self.word_ledger)
        accepted_source_hash = (
            str(self.tail_trim.get("source_formal_word_ledger_hash") or "")
            if self.tail_trim
            else expected_hash
        )
        if (
            not isinstance(payload, Mapping)
            or int(payload.get("schema_version") or 0) != 1
            or str(payload.get("policy_version") or "")
            != "formal-boundary-evidence-v1"
            or str(payload.get("word_ledger_hash") or "")
            not in {expected_hash, accepted_source_hash}
        ):
            raise ManualFinalSubtitleEditError(
                "manual_page_boundary_evidence_required: "
                "冻结分页边界证据与当前词级账本不匹配。"
            )
        boundaries = payload.get("boundaries")
        if not isinstance(boundaries, Mapping):
            raise ManualFinalSubtitleEditError(
                "manual_page_boundary_evidence_required: "
                "冻结分页边界证据格式无效。"
            )
        self._remember_known_formal_boundary_evidence()
        complete_boundaries = {
            str(key): dict(value)
            for key, value in boundaries.items()
            if isinstance(value, Mapping)
        }
        for key, value in self.recovered_formal_boundary_evidence.items():
            complete_boundaries.setdefault(str(key), dict(value))

        required = {str(right) for right in range(1, len(self.word_ledger))}
        if any(key not in complete_boundaries for key in required):
            raise ManualFinalSubtitleEditError(
                "manual_page_boundary_evidence_required: "
                "人工字幕范围内的冻结分页边界证据不完整。"
            )
        return {
            "schema_version": 1,
            "policy_version": "formal-boundary-evidence-v1",
            "word_ledger_hash": expected_hash,
            "boundaries": {
                key: dict(complete_boundaries[key])
                for key in sorted(required, key=int)
            },
        }

    def _blueprint_from_frozen_display_page_edits(
        self,
    ) -> Dict[str, Any] | None:
        from app.core.utils.podcast_learning_video import (
            RenderStructuralOverflowError,
            rebuild_article_frozen_page_plan_from_word_ranges,
            reflow_article_frozen_page_plan_same_screen,
        )

        if self.display_page_boundary_overrides and not self.display_page_edits:
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: 人工分页边界缺少对应的逐页字幕。"
            )
        strict_checkpoint = bool(
            self.display_page_edits or self.display_page_boundary_overrides
        )
        artifact = self._effective_display_page_artifact()
        if not artifact:
            if not strict_checkpoint:
                return None
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: 无法恢复已冻结的人工分页计划。"
            )
        artifact_status = str(artifact.get("status") or "")
        if artifact_status not in {"PASS", "REVIEW", "ERROR"}:
            if not strict_checkpoint:
                return None
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: 已冻结的人工分页计划状态无效。"
            )
        if artifact_status != "PASS" and not strict_checkpoint:
            return None
        raw_plans = list(artifact.get("render_plans") or [])
        if not raw_plans:
            if not strict_checkpoint:
                return None
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: 权威分页产物缺少渲染计划。"
            )
        cues = {
            str(cue.get("cue_id") or ""): cue for cue in self.cues
        }
        edits = {
            str(item.get("display_page_id") or ""): item
            for item in self.display_page_edits
            if isinstance(item, Mapping)
        }
        plans: List[Dict[str, Any]] = []
        parents: List[Dict[str, Any]] = []
        seen_parents: set[str] = set()
        seen_pages: set[str] = set()
        boundary_payload: Dict[str, Any] | None = None
        for raw_plan in raw_plans:
            if not isinstance(raw_plan, Mapping):
                raise ManualFinalSubtitleEditError(
                    "manual_page_translation_required: 权威分页计划格式无效。"
                )
            source_parent_id = str(raw_plan.get("parent_subtitle_id") or "")
            plan = copy.deepcopy(dict(raw_plan))
            parent_id = source_parent_id
            cue = cues.get(parent_id)
            if (
                cue is None
                and self.tail_trim
                and parent_id
                in set(self.tail_trim.get("removed_subtitle_ids") or [])
            ):
                continue
            override_starts = self.display_page_boundary_overrides.get(
                source_parent_id
            )
            render_cue = None
            if cue is not None and override_starts is not None:
                if boundary_payload is None:
                    boundary_payload = self._validated_display_boundary_evidence()
                render_cue = self._article_render_cue(
                    self.cues.index(cue),
                    dict(boundary_payload.get("boundaries") or {}),
                )
                source_pages = [
                    dict(page)
                    for page in raw_plan.get("pages") or []
                    if isinstance(page, Mapping)
                ]
                if not source_pages or len(override_starts) not in {0, 1, 2, 3}:
                    raise ManualFinalSubtitleEditError(
                        "manual_page_translation_required: 人工分页边界数量无效。"
                    )
                boundaries = [int(cue["word_start"]), *override_starts]
                override_ranges = [
                    (
                        start,
                        (
                            boundaries[index + 1] - 1
                            if index + 1 < len(boundaries)
                            else int(cue["word_end"])
                        ),
                    )
                    for index, start in enumerate(boundaries)
                ]
                page_translations = {
                    display_page_id(parent_id, index + 1): str(
                        (
                            edits.get(display_page_id(parent_id, index + 1))
                            or {}
                        ).get("chinese")
                        or ""
                    )
                    for index in range(len(override_ranges))
                }
                try:
                    plan = rebuild_article_frozen_page_plan_from_word_ranges(
                        render_cue,
                        raw_plan,
                        override_ranges,
                        page_translations,
                        allow_page_count_change=True,
                        allow_incomplete_page_translations=True,
                        allow_manual_review=True,
                    )
                except (RenderStructuralOverflowError, KeyError, TypeError, ValueError) as exc:
                    raise ManualFinalSubtitleEditError(
                        "manual_page_translation_required: 人工分页边界无法通过重新校验。"
                    ) from exc
            if cue is not None:
                if boundary_payload is None:
                    boundary_payload = self._validated_display_boundary_evidence()
                if render_cue is None:
                    render_cue = self._article_render_cue(
                        self.cues.index(cue),
                        dict(boundary_payload.get("boundaries") or {}),
                    )
                try:
                    plan = reflow_article_frozen_page_plan_same_screen(
                        render_cue,
                        plan,
                    )
                except (RenderStructuralOverflowError, KeyError, TypeError, ValueError) as exc:
                    raise ManualFinalSubtitleEditError(
                        "manual_page_translation_required: 冻结分页的页内排版无法升级。"
                    ) from exc
            if (
                cue is None
                or parent_id != source_parent_id
                or parent_id in seen_parents
                or int(plan.get("word_start", -1)) != int(cue["word_start"])
                or int(plan.get("word_end", -1)) != int(cue["word_end"])
                or self._normalised_tokens(plan.get("english"))
                != self._normalised_tokens(cue.get("original_subtitle"))
            ):
                if not strict_checkpoint:
                    return None
                raise ManualFinalSubtitleEditError(
                    "manual_page_translation_required: "
                    "权威分页计划与当前父字幕或冻结词范围不一致。"
                )
            seen_parents.add(parent_id)
            plan["chinese"] = str(cue.get("translated_subtitle") or "")
            pages = list(plan.get("pages") or [])
            parent_pages: List[Dict[str, Any]] = []
            for raw_page in pages:
                if not isinstance(raw_page, Mapping):
                    raise ManualFinalSubtitleEditError(
                        "manual_page_translation_required: 权威页面格式无效。"
                    )
                page = copy.deepcopy(dict(raw_page))
                page_id = str(page.get("display_page_id") or "")
                edited = edits.get(page_id)
                invalid_page = not page_id or page_id in seen_pages
                if edited is not None:
                    invalid_page = invalid_page or (
                        str(edited.get("parent_subtitle_id") or "") != parent_id
                        or int(edited.get("word_start", -1))
                        != int(page.get("word_start", -2))
                        or int(edited.get("word_end", -1))
                        != int(page.get("word_end", -2))
                        or str(edited.get("english") or "")
                        != str(page.get("english") or "")
                    )
                elif strict_checkpoint:
                    invalid_page = True
                if invalid_page:
                    raise ManualFinalSubtitleEditError(
                        "manual_page_translation_required: "
                        "人工逐页中文与权威页面 ID 或词范围不一致。"
                    )
                seen_pages.add(page_id)
                if edited is not None:
                    page["chinese"] = str(edited.get("chinese") or "").strip()
                    page["zh"] = page["chinese"]
                parent_pages.append(
                    {
                        "display_page_id": page_id,
                        "word_start": int(page["word_start"]),
                        "word_end": int(page["word_end"]),
                        "english": str(page.get("english") or ""),
                    }
                )
            plan["pages"] = pages = [
                copy.deepcopy(dict(page))
                for page in plan.get("pages") or []
            ]
            if strict_checkpoint:
                for page in pages:
                    edited = edits[str(page.get("display_page_id") or "")]
                    page["chinese"] = str(edited.get("chinese") or "").strip()
                    page["zh"] = page["chinese"]
            plans.append(plan)
            if len(parent_pages) > 1:
                parents.append(
                    {
                        "parent_subtitle_id": parent_id,
                        "english": str(cue.get("original_subtitle") or ""),
                        "chinese": str(cue.get("translated_subtitle") or ""),
                        "word_start": int(cue["word_start"]),
                        "word_end": int(cue["word_end"]),
                        "pages": parent_pages,
                    }
                )
        if set(cues) != seen_parents or (
            strict_checkpoint and set(edits) != seen_pages
        ):
            if not strict_checkpoint:
                return None
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: "
                "权威分页没有完整覆盖当前父字幕和人工页面编辑。"
            )
        if set(self.display_page_boundary_overrides) - seen_parents:
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: 人工分页计划引用了未知父字幕。"
            )
        return {"parents": parents, "render_plans": plans}

    def _write_manual_render_contract(self, artifact_dir: Path) -> Dict[str, Any]:
        from app.core.subtitle_processor.stable_display_page_contract import (
            DISPLAY_PAGE_PLANNER_VERSION,
            DISPLAY_PAGE_SCHEMA_VERSION,
            build_display_page_contract,
            validate_page_translation_response,
        )
        from app.core.utils.podcast_learning_video import (
            Cue,
            RenderStructuralOverflowError,
            article_display_page_layout_profile,
            build_article_manual_draft_page_artifact,
            build_article_display_page_blueprint,
        )

        boundary_payload = self._validated_display_boundary_evidence()
        boundary_items = dict(boundary_payload.get("boundaries") or {})
        records = []
        render_cues = []
        for index, cue in enumerate(self.cues, 1):
            subtitle_id = str(cue.get("cue_id") or f"S{index:04d}")
            word_start = int(cue["word_start"])
            word_end = int(cue["word_end"])
            records.append(
                {
                    "subtitle_id": subtitle_id,
                    "word_start": word_start,
                    "word_end": word_end,
                    "start_ms": int(cue["start_time"]),
                    "end_ms": int(cue["end_time"]),
                    "original": str(cue["original_subtitle"]),
                    "translated": str(cue.get("translated_subtitle") or ""),
                }
            )
            render_cues.append(
                Cue(
                    index=index,
                    start=int(cue["start_time"]) / 1000.0,
                    end=int(cue["end_time"]) / 1000.0,
                    en=str(cue["original_subtitle"]),
                    zh=str(cue.get("translated_subtitle") or ""),
                    speaker="male" if index % 2 else "female",
                    subtitle_id=subtitle_id,
                    word_timing=tuple(
                        {
                            "word_id": word_id,
                            "surface": str(
                                self.word_ledger[word_id].get(
                                    "surface",
                                    self.word_ledger[word_id].get("token", ""),
                                )
                            ),
                            "start": self._word_start_time(word_id) / 1000.0,
                            "end": self._word_end_time(word_id) / 1000.0,
                        }
                        for word_id in range(word_start, word_end + 1)
                    ),
                    display_boundary_evidence={
                        str(right): dict(boundary_items[str(right)])
                        for right in range(word_start + 1, word_end + 1)
                    },
                )
            )

        timeline = {
            "schema_version": 1,
            "records": records,
            "validation": {
                "status": "PASS",
                "error_count": 0,
                "errors": [],
            },
        }
        layout_profile = article_display_page_layout_profile()
        render_block_reason = ""
        blueprint: Dict[str, Any] = {}
        try:
            blueprint = self._blueprint_from_frozen_display_page_edits() or (
                build_article_display_page_blueprint(render_cues)
            )
            multipage_parents = list(blueprint.get("parents") or [])
            page_response = self._display_page_edit_translation_response(
                multipage_parents,
                list(blueprint.get("render_plans") or []),
            )
            if page_response is None:
                page_response = self._reuse_source_page_translations(
                    multipage_parents
                )
            if multipage_parents and page_response is None:
                render_block_reason = "manual_page_translation_required"
        except RenderStructuralOverflowError:
            render_block_reason = "render_structural_overflow"
        except ManualFinalSubtitleEditError:
            render_block_reason = "manual_page_translation_required"

        if not render_block_reason:
            contract = build_display_page_contract(
                multipage_parents,
                layout_profile=layout_profile,
                planner_version=DISPLAY_PAGE_PLANNER_VERSION,
                render_plans=blueprint.get("render_plans") or [],
            )
            display_artifact = validate_page_translation_response(
                contract,
                page_response or {"pages": []},
            )
            contract_hash = str(display_artifact.get("contract_hash") or "")
            if str(display_artifact.get("status") or "") != "PASS":
                render_block_reason = "manual_page_translation_invalid"
        else:
            contract_hash = stable_payload_hash(
                {
                    "manual_cues": records,
                    "layout_profile": layout_profile,
                    "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
                }
            )
            display_artifact = {
                "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
                "status": "ERROR",
                "contract_hash": contract_hash,
                "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
                "layout_profile": layout_profile,
                "errors": [{"code": render_block_reason}],
                "parents": (
                    list(blueprint.get("parents") or [])
                    if render_block_reason == "manual_page_translation_required"
                    else []
                ),
                "render_plans": list(blueprint.get("render_plans") or []),
            }
        write_json_artifact(
            artifact_dir / "word-ledger.json",
            {"words": self.word_ledger},
        )
        write_json_artifact(artifact_dir / "final-cue-timeline.json", timeline)
        write_json_artifact(
            artifact_dir / "display-page-translations.json",
            display_artifact,
        )
        manual_draft_page_plan_path = ""
        manual_draft_page_plan_sha256 = ""
        if render_block_reason:
            try:
                draft_page_translations = self._source_semantic_page_translations()
                draft_page_translations.update(
                    self._visible_display_page_translations()
                )
                draft_artifact = build_article_manual_draft_page_artifact(
                    render_cues,
                    display_artifact.get("render_plans") or [],
                    draft_page_translations,
                )
            except RenderStructuralOverflowError:
                draft_artifact = None
            if draft_artifact is not None:
                draft_path = artifact_dir / "manual-draft-page-plan.json"
                write_json_artifact(draft_path, draft_artifact)
                manual_draft_page_plan_path = str(draft_path)
                manual_draft_page_plan_sha256 = file_sha256(draft_path)
        write_json_artifact(
            artifact_dir / "display-boundary-evidence.json",
            boundary_payload,
        )
        write_json_artifact(
            artifact_dir / "subtitle-spans.json",
            [
                {
                    "subtitle_id": record["subtitle_id"],
                    "word_start": record["word_start"],
                    "word_end": record["word_end"],
                    "original": record["original"],
                }
                for record in records
            ],
        )
        write_json_artifact(
            artifact_dir / "translations.json",
            [
                {
                    "subtitle_id": record["subtitle_id"],
                    "text": record["original"],
                    "translated_text": record["translated"],
                }
                for record in records
            ],
        )
        return {
            "render_blocked": bool(render_block_reason),
            "render_block_reason": render_block_reason,
            "display_status": display_artifact["status"],
            "display_contract_hash": contract_hash,
            "display_artifact": display_artifact,
            "manual_draft_page_plan_path": manual_draft_page_plan_path,
            "manual_draft_page_plan_sha256": manual_draft_page_plan_sha256,
        }

    def export_display_page_subtitles(
        self,
        srt_path: str | Path,
        map_path: str | Path,
        *,
        source_parent_subtitle_path: str | Path | None = None,
    ) -> Dict[str, str]:
        artifact_path = self.artifact_dir / "display-page-translations.json"
        artifact = self._read_json(artifact_path)
        manifest = self._read_json(self.manifest_path)
        expected_hash = str(
            manifest.get("display_page_translation_sha256") or ""
        ).strip()
        if expected_hash and file_sha256(artifact_path) != expected_hash:
            raise ManualFinalSubtitleEditError(
                "实际分页产物哈希与稳定清单不一致。"
            )
        return self._write_display_page_exports(
            Path(srt_path),
            Path(map_path),
            artifact,
            source_parent_subtitle_path=(
                Path(source_parent_subtitle_path)
                if source_parent_subtitle_path
                else self.subtitle_path
            ),
        )

    def _write_display_page_exports(
        self,
        srt_path: Path,
        map_path: Path,
        display_artifact: Mapping[str, Any],
        *,
        source_parent_subtitle_path: str | Path | None = None,
    ) -> Dict[str, str]:
        if str(display_artifact.get("status") or "") != "PASS":
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: "
                "只有通过校验的页面中文才能导出分页字幕。"
            )
        page_chinese = {
            str(page.get("display_page_id") or ""): str(page.get("zh") or "")
            for parent in display_artifact.get("parents") or []
            if isinstance(parent, Mapping)
            for page in parent.get("pages") or []
            if isinstance(page, Mapping)
        }
        parent_chinese = {
            str(cue.get("cue_id") or ""): str(
                cue.get("translated_subtitle") or ""
            )
            for cue in self.cues
        }
        pages: List[Dict[str, Any]] = []
        for plan in display_artifact.get("render_plans") or []:
            if not isinstance(plan, Mapping):
                continue
            parent_id = str(plan.get("parent_subtitle_id") or "")
            plan_pages = list(plan.get("pages") or [])
            for page in plan_pages:
                if not isinstance(page, Mapping):
                    continue
                page_id = str(page.get("display_page_id") or "")
                chinese = (
                    page_chinese.get(page_id, "")
                    if len(plan_pages) > 1
                    else parent_chinese.get(parent_id, "")
                )
                try:
                    item = {
                        "display_page_id": page_id,
                        "parent_subtitle_id": parent_id,
                        "word_start": int(page["word_start"]),
                        "word_end": int(page["word_end"]),
                        "start_ms": int(page["start_ms"]),
                        "end_ms": int(page["end_ms"]),
                        "english": str(
                            page.get("english") or page.get("en") or ""
                        ),
                        "chinese": chinese,
                    }
                except (KeyError, TypeError, ValueError) as exc:
                    raise ManualFinalSubtitleEditError(
                        "manual_page_translation_required: "
                        "冻结页面计划缺少可导出的时间或词范围。"
                    ) from exc
                if (
                    not item["display_page_id"]
                    or not item["parent_subtitle_id"]
                    or not item["english"]
                    or not item["chinese"]
                    or item["end_ms"] <= item["start_ms"]
                ):
                    raise ManualFinalSubtitleEditError(
                        "manual_page_translation_required: "
                        "冻结页面计划或页面中文不完整。"
                    )
                pages.append(item)
        if not pages:
            raise ManualFinalSubtitleEditError(
                "manual_page_translation_required: 没有可导出的冻结页面。"
            )

        lines: List[str] = []
        for index, page in enumerate(pages, 1):
            lines.extend(
                [
                    str(index),
                    f"{self._srt_timestamp(page['start_ms'])} --> "
                    f"{self._srt_timestamp(page['end_ms'])}",
                    page["english"],
                    page["chinese"],
                    "",
                ]
            )
        write_text_artifact(srt_path, "\n".join(lines), encoding="utf-8-sig")
        parent_path = Path(source_parent_subtitle_path or self.subtitle_path)
        write_json_artifact(
            map_path,
            {
                "schema_version": 1,
                "source_parent_subtitle_path": str(parent_path),
                "source_parent_subtitle_sha256": (
                    file_sha256(parent_path) if parent_path.is_file() else ""
                ),
                "display_page_subtitle_path": str(srt_path),
                "display_page_subtitle_sha256": file_sha256(srt_path),
                "display_page_contract_hash": str(
                    display_artifact.get("contract_hash") or ""
                ),
                "pages": pages,
            },
        )
        return {"srt": str(srt_path), "map": str(map_path)}

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
        write_text_artifact(path, "\n".join(lines), encoding="utf-8-sig")

    @staticmethod
    def _srt_timestamp(value: int) -> str:
        milliseconds = max(0, int(value))
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(milliseconds, 1_000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
