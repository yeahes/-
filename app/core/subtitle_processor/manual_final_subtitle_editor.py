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
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence

from app.core.bk_asr.asr_data import ASRData
from app.config import BIN_PATH
from app.core.entities import SupportedAudioFormats, SupportedVideoFormats
from app.core.output_paths import (
    MEDIA_RESULT_MANUAL_PACKAGE_DIR,
    containing_media_result_dir,
    media_result_dir,
    media_result_manual_package_dir,
)
from app.core.subtitle_processor.stable_artifacts import (
    file_sha256,
    find_stable_manifest_for_artifact,
    resolve_manifest_owned_path,
    write_json_artifact,
    write_text_artifact,
)
from app.core.subtitle_processor.authoritative_parent_chinese import (
    AuthoritativeParentChineseError,
    bind_display_page_parent_records,
    build_authoritative_parent_chinese_artifact,
    parent_chinese_records_by_id,
    validate_authoritative_parent_chinese_artifact,
    validate_display_page_parent_records,
)
from app.core.subtitle_processor.stable_display_page_contract import display_page_id
from app.core.subtitle_processor.stable_pipeline_contracts import (
    WORD_LEDGER_HASH_VERSION,
    canonical_word_ledger_hash,
    stable_payload_hash,
)
from app.core.subtitle_processor.final_cue_timeline import (
    DISPLAY_LEAD_IN_MS,
    DISPLAY_TAIL_PADDING_MS,
    derive_final_cue_timeline,
)
from app.core.utils.video_utils import staged_media_output


_SUBTITLE_ID_RE = re.compile(r"S\d{4,}")
_SUPPORTED_MEDIA_SUFFIXES = {
    f".{item.value}" for item in (*SupportedAudioFormats, *SupportedVideoFormats)
}


class ManualFinalSubtitleEditError(ValueError):
    """Raised when an edit cannot be traced to the immutable word ledger."""

    def __init__(self, message: str, *, code: str = "") -> None:
        self.code = str(code or "")
        super().__init__(message)


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


def _materialize_media_mute_audio(
    source_path: Path,
    output_path: Path,
    intervals: Sequence[Mapping[str, Any]],
) -> None:
    """Create a duration-preserving audio copy with exact cue intervals muted."""
    if not source_path.is_file() or not intervals:
        raise ManualFinalSubtitleEditError("静音处理缺少有效的原始音频或字幕区间。")
    ffmpeg = BIN_PATH / "ffmpeg.exe"
    if not ffmpeg.is_file():
        raise ManualFinalSubtitleEditError("找不到项目 FFmpeg，无法生成静音音频。")
    expressions: List[str] = []
    latest_end_ms = 0
    for interval in intervals:
        start_ms = int(interval.get("start_ms") or 0)
        end_ms = int(interval.get("end_ms") or 0)
        if start_ms < 0 or end_ms <= start_ms:
            raise ManualFinalSubtitleEditError("静音字幕区间无效。")
        expressions.append(
            f"between(t,{start_ms / 1000.0:.3f},{end_ms / 1000.0:.3f})"
        )
        latest_end_ms = max(latest_end_ms, end_ms)
    enable_expression = "+".join(expressions)
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
                    f"volume=0:enable='{enable_expression}'",
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
                timeout=max(60, int(latest_end_ms / 1000) + 30),
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
            if result.returncode != 0:
                detail = str(result.stderr or "").strip()[-2000:]
                raise ManualFinalSubtitleEditError(
                    "FFmpeg 无法生成派生静音音频。"
                    + (f"（{detail}）" if detail else "")
                )
    except subprocess.TimeoutExpired as exc:
        raise ManualFinalSubtitleEditError("生成派生静音音频超时。") from exc


def _materialize_media_derivation_audio(
    source_path: Path,
    output_path: Path,
    *,
    cut_ms: int | None,
    mute_intervals: Sequence[Mapping[str, Any]],
) -> None:
    """Materialize one original-media derivation with optional mute and tail cut."""
    if not source_path.is_file():
        raise ManualFinalSubtitleEditError("媒体派生缺少有效的原始音频。")
    if cut_ms is not None and int(cut_ms) <= 0:
        raise ManualFinalSubtitleEditError("媒体派生切点无效。")
    if cut_ms is None and not mute_intervals:
        raise ManualFinalSubtitleEditError("媒体派生没有裁剪或静音操作。")
    ffmpeg = BIN_PATH / "ffmpeg.exe"
    if not ffmpeg.is_file():
        raise ManualFinalSubtitleEditError("找不到项目 FFmpeg，无法生成派生音频。")

    filters: List[str] = []
    latest_end_ms = int(cut_ms or 0)
    expressions: List[str] = []
    for interval in mute_intervals:
        start_ms = int(interval.get("start_ms") or 0)
        end_ms = int(interval.get("end_ms") or 0)
        if start_ms < 0 or end_ms <= start_ms:
            raise ManualFinalSubtitleEditError("媒体派生中的静音字幕区间无效。")
        expressions.append(
            f"between(t,{start_ms / 1000.0:.3f},{end_ms / 1000.0:.3f})"
        )
        latest_end_ms = max(latest_end_ms, end_ms)
    if expressions:
        filters.append(f"volume=0:enable='{'+'.join(expressions)}'")
    if cut_ms is not None:
        filters.extend(
            [
                f"atrim=start=0:end={int(cut_ms) / 1000.0:.3f}",
                "asetpts=PTS-STARTPTS",
            ]
        )
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
                    ",".join(filters),
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
                timeout=max(60, int(latest_end_ms / 1000) + 30),
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
            if result.returncode != 0:
                detail = str(result.stderr or "").strip()[-2000:]
                raise ManualFinalSubtitleEditError(
                    "FFmpeg 无法生成组合派生音频。"
                    + (f"（{detail}）" if detail else "")
                )
    except subprocess.TimeoutExpired as exc:
        raise ManualFinalSubtitleEditError("生成组合派生音频超时。") from exc


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
    parent_chinese_authority: Dict[str, Any] = field(default_factory=dict)
    redo_history: List[Dict[str, Any]] = field(default_factory=list)
    display_page_edits: List[Dict[str, Any]] = field(default_factory=list)
    display_page_boundary_overrides: Dict[str, List[int]] = field(
        default_factory=dict
    )
    # Presentation-only joins.  The word ledger remains the immutable timing
    # authority: one display surface can cover a contiguous range of words.
    english_surface_overrides: List[Dict[str, Any]] = field(default_factory=list)
    recovered_formal_boundary_evidence: Dict[str, Dict[str, Any]] = field(
        default_factory=dict,
        repr=False,
    )
    recovered_stale_page_drafts: Dict[str, Dict[str, Any]] = field(
        default_factory=dict,
        repr=False,
    )
    tail_trim: Dict[str, Any] = field(default_factory=dict)
    media_mute: Dict[str, Any] = field(default_factory=dict)
    media_derivation: Dict[str, Any] = field(default_factory=dict)
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
        if cls._is_manifest_display_page_subtitle(
            source_path,
            manifest,
            manifest_path=resolved_manifest_path,
        ):
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
            parent_path = cls._display_page_parent_subtitle_path(
                manifest,
                manifest_path=resolved_manifest_path,
            )
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
        override_path = cls._resolve_owned_package_file(
            resolved_manifest_path,
            override_text,
            str(override.get("subtitle_sha256") or ""),
        )
        edit_artifact_path = cls._resolve_owned_package_file(
            resolved_manifest_path,
            edit_artifact_text,
            str(override.get("edit_artifact_sha256") or ""),
        )
        manual_source_requested = bool(
            override_text
            and (
                (
                    override_path is not None
                    and cls._same_path(source_path, override_path)
                )
                or cls._same_path(source_path, Path(override_text))
                or (
                    source_path.parent == resolved_manifest_path.parent
                    and source_path.name == Path(override_text).name
                )
            )
        )
        if manual_source_requested and override_path is None:
            raise ManualFinalSubtitleEditError(
                "人工终稿字幕与清单哈希不一致。"
            )
        if manual_source_requested and edit_artifact_path is None:
            raise ManualFinalSubtitleEditError(
                "人工终稿编辑记录与清单哈希不一致。"
            )
        if manual_source_requested:
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
        if not cues or int(cues[-1].get("word_end", -1)) != len(word_ledger) - 1:
            raise ManualFinalSubtitleEditError("字幕没有覆盖完整词级账本。")
        source_word_ledger_hash = cls._semantic_word_ledger_hash(word_ledger)
        declared_ledger_hash = str(ledger_payload.get("hash") or "").strip()
        if declared_ledger_hash and declared_ledger_hash != source_word_ledger_hash:
            raise ManualFinalSubtitleEditError(
                "稳定产物内的词账本哈希与词级内容不一致。"
            )
        parent_chinese_authority = cls._load_parent_chinese_authority(
            artifact_dir,
            cues,
            source_word_ledger_hash,
            allow_missing_legacy_translation=bool(
                manifest.get("editable_checkpoint") or manifest.get("render_blocked")
            ),
        )
        session = cls(
            subtitle_path=source_path,
            manifest_path=resolved_manifest_path,
            artifact_dir=artifact_dir,
            word_ledger=word_ledger,
            cues=cues,
            source_word_ledger_hash=source_word_ledger_hash,
            history=[],
            english_surface_overrides=cls._parse_english_surface_overrides(
                ledger_payload.get("english_surface_overrides")
            ),
            parent_chinese_authority=parent_chinese_authority,
            loaded_subtitle_path=source_path,
            source_media_path=cls._manifest_source_media_path(
                manifest,
                resolved_manifest_path,
                source_path,
            ),
        )
        session._validate_cues()
        session._validate_english_surface_overrides()
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
        subtitle_hash = str(
            override.get("subtitle_sha256")
            or (manifest.get("source_subtitle_paths_sha256") or {}).get(
                "bilingual_original_top_srt"
            )
            or (manifest.get("paths_sha256") or {}).get("original_top_srt")
            or ""
        )
        subtitle_path = cls._resolve_owned_package_file(
            manifest_file,
            subtitle_text,
            subtitle_hash,
        )
        if subtitle_path is None:
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

    @classmethod
    def _resolve_owned_package_file(
        cls,
        manifest_path: Path,
        recorded_path: str | Path,
        expected_sha256: str = "",
    ) -> Path | None:
        """Resolve a manifest-owned file after the whole package was moved."""
        try:
            manifest = cls._read_json(Path(manifest_path))
        except ManualFinalSubtitleEditError:
            return None
        return resolve_manifest_owned_path(
            Path(manifest_path),
            manifest,
            recorded_path,
            expected_sha256,
        )

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
            media_override = (
                (manifest.get("manual_final_override") or {}).get(
                    "media_derivation"
                )
                or manifest.get("media_derivation")
                or (manifest.get("manual_final_override") or {}).get("tail_trim")
                or manifest.get("tail_trim")
                or (manifest.get("manual_final_override") or {}).get("media_mute")
                or manifest.get("media_mute")
                or {}
            )
            expected_hash = str(media_override.get("derived_media_sha256") or "")
            for anchor in anchors:
                manifest_path = (
                    Path(anchor)
                    if Path(anchor).name == "stable-final-manifest.json"
                    else find_stable_manifest_for_artifact(anchor)
                )
                if manifest_path is None:
                    continue
                resolved = resolve_manifest_owned_path(
                    manifest_path,
                    manifest,
                    text,
                    expected_hash,
                )
                if resolved is not None:
                    return resolved
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
        *,
        manifest_path: Path | None = None,
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
        if manifest_path is not None:
            parent_hash_values = (
                str(override.get("subtitle_sha256") or ""),
                str((manifest.get("paths_sha256") or {}).get("original_top_srt") or ""),
                str(
                    (manifest.get("source_subtitle_paths_sha256") or {}).get(
                        "named_bilingual_original_top_srt"
                    )
                    or ""
                ),
                str(
                    (manifest.get("source_subtitle_paths_sha256") or {}).get(
                        "bilingual_original_top_srt"
                    )
                    or ""
                ),
            )
            for value, expected_hash in zip(parent_path_values, parent_hash_values):
                resolved = cls._resolve_owned_package_file(
                    Path(manifest_path),
                    value,
                    expected_hash,
                )
                if resolved is not None and cls._same_path(subtitle_path, resolved):
                    return False
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
        if manifest_path is not None:
            path_hash_values = (
                str(override.get("display_page_srt_sha256") or ""),
                str(
                    (manifest.get("paths_sha256") or {}).get(
                        "display_page_bilingual_srt"
                    )
                    or ""
                ),
                str(
                    (manifest.get("source_subtitle_paths_sha256") or {}).get(
                        "display_page_bilingual_srt"
                    )
                    or ""
                ),
            )
            for value, expected_hash in zip(path_values, path_hash_values):
                resolved = cls._resolve_owned_package_file(
                    Path(manifest_path),
                    value,
                    expected_hash,
                )
                if resolved is not None and cls._same_path(subtitle_path, resolved):
                    return True
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

    @classmethod
    def _display_page_parent_subtitle_path(
        cls,
        manifest: Mapping[str, Any],
        *,
        manifest_path: Path | None = None,
    ) -> Path | None:
        override = manifest.get("manual_final_override") or {}
        paths = manifest.get("paths") or {}
        source_paths = manifest.get("source_subtitle_paths") or {}
        path_hashes = manifest.get("paths_sha256") or {}
        source_hashes = manifest.get("source_subtitle_paths_sha256") or {}
        for value, expected_hash in (
            (override.get("subtitle_path"), override.get("subtitle_sha256")),
            (paths.get("original_top_srt"), path_hashes.get("original_top_srt")),
            (
                source_paths.get("named_bilingual_original_top_srt"),
                source_hashes.get("named_bilingual_original_top_srt"),
            ),
            (
                source_paths.get("bilingual_original_top_srt"),
                source_hashes.get("bilingual_original_top_srt"),
            ),
        ):
            text = str(value or "").strip()
            if not text:
                continue
            if manifest_path is not None:
                resolved = cls._resolve_owned_package_file(
                    Path(manifest_path),
                    text,
                    str(expected_hash or ""),
                )
                if resolved is not None:
                    return resolved
            candidate = Path(text)
            if candidate.is_file():
                return candidate.resolve()
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
        generation_manifest = find_stable_manifest_for_artifact(subtitle_path)
        if generation_manifest is not None:
            candidates.append(generation_manifest)
        candidates.extend(
            subtitle_path.parent.glob("*-人工终稿字幕包/stable-final-manifest.json")
        )
        result_root = containing_media_result_dir(subtitle_path)
        if result_root is not None:
            nested_portable = (
                result_root
                / MEDIA_RESULT_MANUAL_PACKAGE_DIR
                / "stable-final-manifest.json"
            )
            if nested_portable.is_file():
                candidates.append(nested_portable)
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
        override = manifest.get("manual_final_override") or {}
        owned_artifact = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            str(override.get("artifact_dir") or ""),
            expect_directory=True,
        )
        if (
            owned_artifact is not None
            and (owned_artifact / "subtitle-spans.json").is_file()
        ):
            return owned_artifact
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

    @staticmethod
    def _normalised_chinese(text: object) -> str:
        return re.sub(r"\s+", "", str(text or ""))

    @classmethod
    def _assert_subtitle_matches_cues(
        cls,
        subtitle_path: Path,
        cues: Sequence[Mapping[str, Any]],
    ) -> None:
        data = ASRData.from_subtitle_file(str(subtitle_path))
        visible_cues = [cue for cue in cues if not cue.get("display_suppressed")]
        if len(data.segments) != len(visible_cues):
            raise ManualFinalSubtitleEditError(
                "authoritative_parent_chinese_conflict: 父字幕与人工编辑记录条数不一致。"
            )
        for index, (segment, cue) in enumerate(
            zip(data.segments, visible_cues),
            1,
        ):
            if (
                cls._normalised_tokens(segment.text)
                != cls._normalised_tokens(str(cue.get("original_subtitle") or ""))
                or cls._normalised_chinese(segment.translated_text)
                != cls._normalised_chinese(cue.get("translated_subtitle"))
                or int(segment.start_time) != int(cue.get("start_time") or 0)
                or int(segment.end_time) != int(cue.get("end_time") or 0)
            ):
                raise ManualFinalSubtitleEditError(
                    "authoritative_parent_chinese_conflict: "
                    f"第 {index} 条父字幕与人工编辑记录不一致。"
                )

    @classmethod
    def _load_parent_chinese_authority(
        cls,
        artifact_dir: Path,
        cues: Sequence[Mapping[str, Any]],
        source_word_ledger_hash: str,
        *,
        require_authority: bool = False,
        allow_missing_legacy_translation: bool = False,
    ) -> Dict[str, Any]:
        authority_path = artifact_dir / "authoritative-parent-chinese.json"
        translations_path = artifact_dir / "translations.json"
        authority: Dict[str, Any] = {}
        if authority_path.is_file():
            authority = cls._read_json(authority_path)
            try:
                authority = validate_authoritative_parent_chinese_artifact(
                    authority,
                    expected_parents=cues,
                    expected_word_ledger_hash=source_word_ledger_hash,
                )
            except AuthoritativeParentChineseError as exc:
                raise ManualFinalSubtitleEditError(str(exc)) from exc
        elif require_authority:
            raise ManualFinalSubtitleEditError(
                "authoritative_parent_chinese_missing: 人工终稿缺少权威中文记录。"
            )

        if not translations_path.is_file():
            if allow_missing_legacy_translation and not require_authority:
                return build_authoritative_parent_chinese_artifact(
                    cues,
                    source_word_ledger_hash=source_word_ledger_hash,
                    producer="legacy_blocked_checkpoint",
                )
            raise ManualFinalSubtitleEditError(
                "authoritative_parent_chinese_missing: 稳定产物缺少 translations.json。"
            )
        translations = cls._read_json(translations_path)
        translated_by_id = {
            str(item.get("subtitle_id") or ""): item
            for item in translations
            if isinstance(item, Mapping)
        }
        cue_by_id = {
            str(cue.get("cue_id") or ""): cue
            for cue in cues
        }
        if set(translated_by_id) != set(cue_by_id):
            raise ManualFinalSubtitleEditError(
                "authoritative_parent_chinese_conflict: translations.json 的固定 ID 不完整。"
            )
        for subtitle_id, cue in cue_by_id.items():
            translated = translated_by_id[subtitle_id]
            if (
                cls._normalised_tokens(str(translated.get("text") or ""))
                != cls._normalised_tokens(str(cue.get("original_subtitle") or ""))
                or cls._normalised_chinese(translated.get("translated_text"))
                != cls._normalised_chinese(cue.get("translated_subtitle"))
            ):
                raise ManualFinalSubtitleEditError(
                    "authoritative_parent_chinese_conflict: "
                    f"{subtitle_id} 的父字幕与 translations.json 中文不一致。"
                )

        if authority:
            records_by_id = parent_chinese_records_by_id(authority)
            for subtitle_id, translated in translated_by_id.items():
                record = records_by_id[subtitle_id]
                if (
                    str(translated.get("parent_source_hash") or "")
                    != str(record.get("source_hash") or "")
                    or str(translated.get("parent_record_hash") or "")
                    != str(record.get("record_hash") or "")
                ):
                    raise ManualFinalSubtitleEditError(
                        "authoritative_parent_chinese_conflict: "
                        f"{subtitle_id} 的 translations.json 未绑定当前中文记录。"
                    )
            display_path = artifact_dir / "display-page-translations.json"
            if display_path.is_file():
                display_artifact = cls._read_json(display_path)
                if str(display_artifact.get("status") or "") == "PASS":
                    try:
                        validate_display_page_parent_records(
                            display_artifact,
                            records_by_id,
                        )
                    except AuthoritativeParentChineseError as exc:
                        raise ManualFinalSubtitleEditError(str(exc)) from exc
            return authority

        return build_authoritative_parent_chinese_artifact(
            cues,
            source_word_ledger_hash=source_word_ledger_hash,
            producer="legacy_consistent_import",
        )

    @classmethod
    def _load_saved_session(
        cls, subtitle_path: Path, manifest_path: Path, edit_artifact_path: Path
    ) -> "ManualFinalSubtitleSession":
        manifest = cls._read_json(manifest_path)
        override = manifest.get("manual_final_override") or {}
        override_schema = int(override.get("schema_version") or 0)
        owned_edit_text = str(override.get("edit_artifact_path") or "").strip()
        expected_edit_hash = str(
            override.get("edit_artifact_sha256") or ""
        ).strip()
        owned_edit_path = cls._resolve_owned_package_file(
            manifest_path,
            owned_edit_text,
            expected_edit_hash,
        )
        if override_schema >= 3 or expected_edit_hash:
            if (
                owned_edit_path is None
                or not cls._same_path(owned_edit_path, edit_artifact_path)
                or not expected_edit_hash
            ):
                raise ManualFinalSubtitleEditError(
                    "人工终稿编辑记录与清单哈希不一致。"
                )

        payload = cls._read_json(edit_artifact_path)
        ledger = list(payload.get("word_ledger") or [])
        cues = list(payload.get("cues") or [])
        if not ledger or not cues:
            raise ManualFinalSubtitleEditError("人工终稿编辑记录不完整。")
        embedded_ledger_hash = cls._semantic_word_ledger_hash(ledger)
        recorded_ledger_hash = str(
            payload.get("source_word_ledger_hash") or ""
        ).strip()
        accepted_embedded_hashes = {embedded_ledger_hash}
        if int(payload.get("schema_version") or 0) < 4:
            accepted_embedded_hashes.add(cls._legacy_word_ledger_hash(ledger))
        if (
            not recorded_ledger_hash
            or recorded_ledger_hash not in accepted_embedded_hashes
        ):
            raise ManualFinalSubtitleEditError(
                "人工终稿编辑记录内的词账本哈希不一致。"
            )
        owned_ledger_text = str(override.get("word_ledger_path") or "").strip()
        expected_ledger_file_hash = str(
            override.get("word_ledger_sha256") or ""
        ).strip()
        owned_ledger_path = cls._resolve_owned_package_file(
            manifest_path,
            owned_ledger_text,
            expected_ledger_file_hash,
        )
        if override_schema >= 3:
            if (
                owned_ledger_path is None
                or not expected_ledger_file_hash
            ):
                raise ManualFinalSubtitleEditError(
                    "人工终稿词账本与清单哈希不一致。"
                )
            owned_ledger_payload = cls._read_json(owned_ledger_path)
            owned_ledger = list(owned_ledger_payload.get("words") or [])
            owned_ledger_hash = cls._semantic_word_ledger_hash(owned_ledger)
            declared_owned_ledger_hash = str(
                owned_ledger_payload.get("hash") or ""
            ).strip()
            if (
                not owned_ledger
                or owned_ledger_hash != embedded_ledger_hash
                or (
                    declared_owned_ledger_hash
                    and declared_owned_ledger_hash != owned_ledger_hash
                )
            ):
                raise ManualFinalSubtitleEditError(
                    "人工终稿编辑记录引用了不同的词账本。"
                )
        owned_artifact_text = str(override.get("artifact_dir") or "").strip()
        owned_artifact_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            owned_artifact_text,
            expect_directory=True,
        )
        if (
            owned_artifact_path is None
            or not owned_artifact_path.is_dir()
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
        cls._assert_subtitle_matches_cues(subtitle_path, cues)
        edit_schema = int(payload.get("schema_version") or 0)
        authority_ledger_hash = (
            embedded_ledger_hash if edit_schema >= 4 else recorded_ledger_hash
        )
        parent_chinese_authority = cls._load_parent_chinese_authority(
            owned_artifact_path,
            cues,
            authority_ledger_hash,
            require_authority=override_schema >= 4,
            allow_missing_legacy_translation=bool(
                manifest.get("editable_checkpoint") or manifest.get("render_blocked")
            ),
        )
        if override_schema >= 4:
            authority_path = cls._resolve_owned_package_file(
                manifest_path,
                str(override.get("parent_chinese_authority_path") or ""),
                str(override.get("parent_chinese_authority_sha256") or ""),
            )
            expected_authority_path = (
                owned_artifact_path / "authoritative-parent-chinese.json"
            ).resolve()
            if (
                authority_path is None
                or not cls._same_path(authority_path, expected_authority_path)
                or str(override.get("parent_chinese_authority_hash") or "")
                != str(parent_chinese_authority.get("artifact_hash") or "")
            ):
                raise ManualFinalSubtitleEditError(
                    "authoritative_parent_chinese_conflict: "
                    "人工终稿清单引用了不同的权威中文记录。"
                )
        saved_derivation = dict(payload.get("media_derivation") or {})
        saved_tail_trim = dict(payload.get("tail_trim") or {})
        saved_media_mute = dict(payload.get("media_mute") or {})
        if saved_derivation and (saved_tail_trim or saved_media_mute):
            raise ManualFinalSubtitleEditError(
                "人工终稿不能同时包含 v2 媒体派生和旧媒体编辑记录。"
            )
        if saved_derivation:
            source_media_text = str(
                saved_derivation.get("source_media_path") or ""
            )
            source_media_hash = str(
                saved_derivation.get("source_media_sha256") or ""
            )
            if saved_derivation.get("cut_ms") is not None:
                saved_tail_trim = {
                    "source_media_path": source_media_text,
                    "source_media_sha256": source_media_hash,
                    "cut_ms": int(saved_derivation["cut_ms"]),
                    "decision_hash": str(
                        saved_derivation.get("decision_hash") or ""
                    ),
                    "derived_media_path": str(
                        saved_derivation.get("derived_media_path") or ""
                    ),
                    "derived_media_sha256": str(
                        saved_derivation.get("derived_media_sha256") or ""
                    ),
                }
            if list(saved_derivation.get("mute_intervals") or []):
                saved_media_mute = {
                    "source_media_path": source_media_text,
                    "source_media_sha256": source_media_hash,
                    "intervals": list(
                        saved_derivation.get("mute_intervals") or []
                    ),
                    "derived_media_path": str(
                        saved_derivation.get("derived_media_path") or ""
                    ),
                    "derived_media_sha256": str(
                        saved_derivation.get("derived_media_sha256") or ""
                    ),
                }
        session = cls(
            subtitle_path=subtitle_path,
            manifest_path=manifest_path,
            artifact_dir=owned_artifact_path,
            word_ledger=ledger,
            cues=cues,
            source_word_ledger_hash=authority_ledger_hash,
            history=list(payload.get("history") or []),
            parent_chinese_authority=parent_chinese_authority,
            redo_history=list(payload.get("redo_history") or []),
            display_page_edits=list(payload.get("display_page_edits") or []),
            display_page_boundary_overrides=(
                cls._parse_display_page_boundary_overrides(
                    payload.get("display_page_boundary_overrides")
                )
            ),
            english_surface_overrides=cls._parse_english_surface_overrides(
                payload.get("english_surface_overrides")
            ),
            recovered_stale_page_drafts=(
                cls._parse_recovered_stale_page_drafts(
                    payload.get("recovered_stale_page_drafts")
                )
            ),
            tail_trim=saved_tail_trim,
            media_mute=saved_media_mute,
            media_derivation=saved_derivation,
            loaded_subtitle_path=subtitle_path,
            source_media_path=cls._manifest_source_media_path(
                manifest,
                manifest_path,
                subtitle_path,
            ),
        )
        session._validate_cues()
        session._validate_english_surface_overrides()
        session._validate_media_mute_contract(
            manifest=manifest,
            manifest_path=manifest_path,
            require_materialized=any(
                bool(cue.get("media_muted")) for cue in session.cues
            ),
        )
        session._validate_display_page_boundary_overrides()
        session.compact_english_surface_history()
        session.compact_parent_scoped_history()
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
    def _legacy_word_ledger_hash(
        ledger: Sequence[Mapping[str, Any]],
    ) -> str:
        return stable_payload_hash(
            ManualFinalSubtitleSession._ledger_payload(ledger)
        )

    @staticmethod
    def _semantic_word_ledger_hash(
        ledger: Sequence[Mapping[str, Any]],
    ) -> str:
        return canonical_word_ledger_hash(ledger)

    @staticmethod
    def _normalised_tokens(text: str) -> List[str]:
        return [
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", str(text or ""))
        ]

    @classmethod
    def _parse_english_surface_overrides(cls, value: Any) -> List[Dict[str, Any]]:
        if value in (None, []):
            return []
        if not isinstance(value, list):
            raise ManualFinalSubtitleEditError("英文显示合并记录格式无效。")
        parsed: List[Dict[str, Any]] = []
        for raw in value:
            if not isinstance(raw, Mapping):
                raise ManualFinalSubtitleEditError("英文显示合并记录格式无效。")
            try:
                start = int(raw["word_start"])
                end = int(raw["word_end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ManualFinalSubtitleEditError("英文显示合并词范围无效。") from exc
            expected = [str(item) for item in raw.get("expected_surfaces") or []]
            surface = re.sub(r"\s+", " ", str(raw.get("display_surface") or "")).strip()
            parent_id = str(raw.get("parent_subtitle_id") or "").strip()
            if end <= start or not expected or not surface or not parent_id:
                raise ManualFinalSubtitleEditError("英文显示合并内容不完整。")
            parsed.append(
                {
                    "word_start": start,
                    "word_end": end,
                    "expected_surfaces": expected,
                    "display_surface": surface,
                    "parent_subtitle_id": parent_id,
                }
            )
        return sorted(parsed, key=lambda item: (item["word_start"], item["word_end"]))

    @classmethod
    def _words_text(cls, ledger: Sequence[Mapping[str, Any]], start: int, end: int) -> str:
        return " ".join(
            str(word.get("surface", word.get("token", "")) or "").strip()
            for word in ledger[start : end + 1]
        ).strip()

    def _display_words_text(self, start: int, end: int) -> str:
        """Resolve display surfaces while retaining every source word in ledger."""
        by_start = {int(item["word_start"]): item for item in self.english_surface_overrides}
        parts: List[str] = []
        word_id = int(start)
        while word_id <= int(end):
            override = by_start.get(word_id)
            if override is not None:
                override_end = int(override["word_end"])
                if override_end > end:
                    raise ManualFinalSubtitleEditError("显示词合并被字幕或分页边界截断。")
                parts.append(str(override["display_surface"]))
                word_id = override_end + 1
                continue
            parts.append(str(self.word_ledger[word_id].get("surface", self.word_ledger[word_id].get("token", "")) or "").strip())
            word_id += 1
        return " ".join(part for part in parts if part).strip()

    def _display_word_spans(self, start: int, end: int) -> List[Dict[str, Any]]:
        by_start = {int(item["word_start"]): item for item in self.english_surface_overrides}
        spans: List[Dict[str, Any]] = []
        word_id = int(start)
        while word_id <= int(end):
            override = by_start.get(word_id)
            span_end = int(override["word_end"]) if override is not None else word_id
            if span_end > end:
                raise ManualFinalSubtitleEditError("显示词合并被字幕或分页边界截断。")
            spans.append(
                {
                    "word_start": word_id,
                    "word_end": span_end,
                    "surface": str(override["display_surface"]) if override else str(self.word_ledger[word_id].get("surface", self.word_ledger[word_id].get("token", "")) or "").strip(),
                }
            )
            word_id = span_end + 1
        return spans

    def _validate_english_surface_overrides(self) -> None:
        previous_end = -1
        cue_by_id = {str(cue.get("cue_id") or ""): cue for cue in self.cues}
        for item in self.english_surface_overrides:
            start = int(item["word_start"])
            end = int(item["word_end"])
            parent_id = str(item["parent_subtitle_id"])
            cue = cue_by_id.get(parent_id)
            if (
                start <= previous_end
                or start < 0
                or end >= len(self.word_ledger)
                or cue is None
                or start < int(cue["word_start"])
                or end > int(cue["word_end"])
            ):
                raise ManualFinalSubtitleEditError("英文显示合并范围重叠、越界或跨越父字幕。")
            expected = [
                str(self.word_ledger[word_id].get("surface", self.word_ledger[word_id].get("token", "")) or "").strip()
                for word_id in range(start, end + 1)
            ]
            if expected != list(item["expected_surfaces"]):
                raise ManualFinalSubtitleEditError("英文显示合并的原词基线已变化，请重新编辑。")
            if not str(item["display_surface"] or "").strip():
                raise ManualFinalSubtitleEditError("英文显示合并不能为空。")
            previous_end = end

    def _assert_boundary_outside_english_surface_overrides(
        self,
        boundary_word_id: int,
    ) -> None:
        boundary = int(boundary_word_id)
        if any(
            int(item["word_start"]) < boundary <= int(item["word_end"])
            for item in self.english_surface_overrides
        ):
            raise ManualFinalSubtitleEditError(
                "当前边界会切开人工合并的英文词面，请先撤销该英文修正。"
            )

    def _rebind_english_surface_overrides_to_cues(self) -> None:
        """Keep a display span bound to the one cue that owns its raw words."""
        for item in self.english_surface_overrides:
            start = int(item["word_start"])
            end = int(item["word_end"])
            owners = [
                cue
                for cue in self.cues
                if int(cue["word_start"]) <= start
                and end <= int(cue["word_end"])
            ]
            if len(owners) != 1:
                raise ManualFinalSubtitleEditError(
                    "字幕边界切开了人工合并的英文词面。"
                )
            item["parent_subtitle_id"] = str(owners[0]["cue_id"])
        for cue in self.cues:
            cue["original_subtitle"] = self._display_words_text(
                int(cue["word_start"]),
                int(cue["word_end"]),
            )
        self._validate_english_surface_overrides()

    def replace_english_surface_span(
        self,
        *,
        parent_subtitle_id: str,
        word_start: int,
        word_end: int,
        replacement_text: str,
    ) -> bool:
        """Join contiguous source words into one presentation-only surface."""
        parent_id = str(parent_subtitle_id or "").strip()
        replacement = re.sub(r"\s+", " ", str(replacement_text or "")).strip()
        cue = next((item for item in self.cues if str(item.get("cue_id") or "") == parent_id), None)
        if cue is None or not replacement or "\n" in str(replacement_text or ""):
            raise ManualFinalSubtitleEditError("英文显示合并的字幕 ID 或替换文本无效。")
        start, end = int(word_start), int(word_end)
        if start >= end or start < int(cue["word_start"]) or end > int(cue["word_end"]):
            raise ManualFinalSubtitleEditError("只能合并同一父字幕内连续的至少两个词。")
        expected = [
            str(self.word_ledger[word_id].get("surface", self.word_ledger[word_id].get("token", "")) or "").strip()
            for word_id in range(start, end + 1)
        ]
        if not all(expected):
            raise ManualFinalSubtitleEditError("冻结词没有可用于显示合并的英文词面。")
        current_pages = self._visible_display_page_rows(
            self._display_page_model_data()
        )
        for row in current_pages:
            if str(row.get("manual_cue_id") or "") != parent_id:
                continue
            page_start, page_end = int(row["word_start"]), int(row["word_end"])
            if page_start < start <= page_end or page_start <= end < page_end:
                raise ManualFinalSubtitleEditError("英文显示合并不能跨越实际分页边界。")
        candidate = {
            "word_start": start, "word_end": end, "expected_surfaces": expected,
            "display_surface": replacement, "parent_subtitle_id": parent_id,
        }
        before = copy.deepcopy(self.english_surface_overrides)
        before_cues = copy.deepcopy(self.cues)
        retained = [item for item in before if int(item["word_end"]) < start or int(item["word_start"]) > end]
        if len(retained) != len(before) and not any(item == candidate for item in before):
            raise ManualFinalSubtitleEditError("英文显示合并不能与已有合并范围重叠。")
        if any(item == candidate for item in before):
            return False
        self.english_surface_overrides = sorted([*retained, candidate], key=lambda item: int(item["word_start"]))
        try:
            self._validate_english_surface_overrides()
            cue["original_subtitle"] = self._display_words_text(int(cue["word_start"]), int(cue["word_end"]))
            for edit in self.display_page_edits:
                page_start, page_end = int(edit["word_start"]), int(edit["word_end"])
                if page_start < start <= page_end or page_start <= end < page_end:
                    raise ManualFinalSubtitleEditError("英文显示合并不能跨越实际分页边界。")
                if page_start <= start and end <= page_end:
                    edit["english"] = self._display_words_text(page_start, page_end)
                    edit["chinese_review_acknowledged"] = False
            cue["chinese_review_required"] = True
            self._validate_cues()
        except Exception:
            self.english_surface_overrides = before
            cue["original_subtitle"] = self._display_words_text(int(cue["word_start"]), int(cue["word_end"]))
            raise
        self._record_history(
            "edit_english_surface_span", before_cues,
            affected_parent_ids=[parent_id], before_english_surface_overrides=before,
        )
        return True

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
        from app.core.utils.podcast_learning_video import (
            Cue,
            _project_article_display_word_timing,
        )

        cue = self.cues[cue_index]
        word_start = int(cue["word_start"])
        word_end = int(cue["word_end"])
        display_word_spans = tuple(
            self._display_word_spans(word_start, word_end)
        )
        raw_word_timing = tuple(
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
        )
        projected_timing = _project_article_display_word_timing(
            raw_word_timing,
            display_word_spans,
        )
        if not projected_timing:
            raise ManualFinalSubtitleEditError(
                "英文显示词面无法映射回冻结词时间。"
            )
        return Cue(
            index=cue_index + 1,
            start=int(cue["start_time"]) / 1000.0,
            end=int(cue["end_time"]) / 1000.0,
            en=str(cue["original_subtitle"]),
            zh=str(cue.get("translated_subtitle") or ""),
            speaker="manual",
            subtitle_id=str(cue.get("cue_id") or ""),
            word_timing=projected_timing,
            display_word_spans=display_word_spans,
            display_boundary_evidence={
                str(right_word): dict(boundary_items[str(right_word)])
                for right_word in range(word_start + 1, word_end + 1)
            },
        )

    def build_display_page_candidate_workspace(
        self,
        parent_subtitle_id: str,
        *,
        min_page_count: int = 2,
        max_page_count: int | None = None,
    ) -> Dict[str, Any]:
        """Build read-only page alternatives for one frozen parent cue.

        Candidate planning is deliberately separate from the mutable page
        edits.  The returned ranges are global word-ledger IDs and can be
        applied later as one parent-scoped edit.
        """
        parent_id = str(parent_subtitle_id or "").strip()
        cue_index = next(
            (
                index
                for index, cue in enumerate(self.cues)
                if str(cue.get("cue_id") or "") == parent_id
            ),
            -1,
        )
        if cue_index < 0:
            raise ManualFinalSubtitleEditError("找不到要查看候选分页的父字幕。")
        cue = self.cues[cue_index]
        self._ensure_unmodified_english(cue)
        boundary_payload = self._validated_display_boundary_evidence()
        from app.core.utils.podcast_learning_video import (
            ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES,
            article_display_boundary_explanation,
            build_article_display_page_candidate_workspace,
        )

        requested_max_page_count = (
            ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES
            if max_page_count is None
            else int(max_page_count)
        )

        workspace = build_article_display_page_candidate_workspace(
            self._article_render_cue(
                cue_index,
                dict(boundary_payload.get("boundaries") or {}),
            ),
            min_page_count=min_page_count,
            max_page_count=requested_max_page_count,
        )
        first_word = int(cue["word_start"])
        for candidate in workspace.get("candidates") or []:
            plan = candidate.get("plan") or {}
            pages = []
            source_pages = list(plan.get("pages") or candidate.get("pages") or [])
            for page_index, page in enumerate(source_pages):
                local_start = int(page.get("word_start"))
                local_end = int(page.get("word_end"))
                previous_page = source_pages[page_index - 1] if page_index else {}
                boundary = dict(page.get("boundary_before") or {})
                pages.append(
                    {
                        **dict(page),
                        "word_start": first_word + local_start,
                        "word_end": first_word + local_end,
                        "boundary_explanation": article_display_boundary_explanation(
                            boundary,
                            left_english=str(previous_page.get("en") or ""),
                            right_english=str(page.get("en") or ""),
                        ),
                    }
                )
            candidate["global_word_ranges"] = [
                [int(page["word_start"]), int(page["word_end"])]
                for page in pages
            ]
            candidate["pages"] = pages
            candidate["applicable"] = all(
                bool(page.get("boundary_explanation", {}).get("applicable", True))
                for page in pages[1:]
            )
        return workspace

    def build_display_page_risk_queue(
        self,
        *,
        min_page_count: int = 2,
        max_page_count: int = 4,
    ) -> List[Dict[str, Any]]:
        """Return a read-only queue of parents worth human page review.

        The queue is an editor aid only.  It never changes the frozen parent
        cues or calls the mutating page-edit methods.  A parent is included
        when its current pages carry a concrete density, font, boundary, or
        confirmation signal. Candidate planning is deliberately lazy: the
        focused workspace computes alternatives only after the user selects
        one parent, rather than blocking the Qt thread for the entire file.
        """
        page_rows = self._visible_display_page_rows(self._display_page_model_data())
        rows_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        for row in page_rows:
            parent_id = str(row.get("manual_cue_id") or "").strip()
            if parent_id:
                rows_by_parent.setdefault(parent_id, []).append(dict(row))

        queue: List[Dict[str, Any]] = []
        for cue in self.cues:
            parent_id = str(cue.get("cue_id") or "").strip()
            if not parent_id or cue.get("display_suppressed"):
                continue
            word_count = int(cue.get("word_end", -1)) - int(cue.get("word_start", 0)) + 1
            current_rows = rows_by_parent.get(parent_id, [])
            reasons: List[str] = []
            if word_count > 16:
                reasons.append("英文超过16词")
            font_sizes = [
                int(row.get("english_font_size") or 0)
                for row in current_rows
                if str(row.get("english_font_size") or "").strip()
            ]
            if font_sizes and min(font_sizes) < 56:
                reasons.append(f"字号降到{min(font_sizes)}")
            if any(bool(row.get("display_page_review_required")) for row in current_rows):
                reasons.append("分页边界待复核")
            if any(
                str(row.get("translated_subtitle") or "").strip()
                and not bool(row.get("display_page_chinese_confirmed"))
                for row in current_rows
            ):
                reasons.append("分页中文待确认")
            if any(bool(row.get("display_page_chinese_stale")) for row in current_rows):
                reasons.append("分页中文是旧草稿")

            if not reasons:
                continue
            queue.append(
                {
                    "parent_subtitle_id": parent_id,
                    "english": str(cue.get("original_subtitle") or ""),
                    "word_count": word_count,
                    "start_time": int(cue.get("start_time") or 0),
                    "end_time": int(cue.get("end_time") or 0),
                    "reasons": list(dict.fromkeys(reasons)),
                    "current_page_count": len(current_rows),
                    "candidate_count": 0,
                    "best_candidate": {},
                }
            )
        queue.sort(
            key=lambda item: (
                -int(item.get("word_count") or 0),
                -len(item.get("reasons") or []),
                str(item.get("parent_subtitle_id") or ""),
            )
        )
        return queue

    def _ensure_unmodified_english(self, cue: Mapping[str, Any]) -> None:
        expected = self._display_words_text(
            int(cue["word_start"]), int(cue["word_end"])
        )
        if self._normalised_tokens(cue.get("original_subtitle", "")) != self._normalised_tokens(expected):
            raise ManualFinalSubtitleEditError(
                "该行英文已被自由修改，无法再按原始词级账本移动边界。"
            )

    @staticmethod
    def _surface_units(text: str) -> List[str]:
        return re.findall(r"\S+", str(text or "").strip())

    def _plan_english_surface_edit(
        self,
        *,
        word_start: int,
        word_end: int,
        replacement_text: str,
    ) -> Dict[str, Any] | None:
        """Bind one visible English correction to exactly one frozen word ID."""
        replacement = re.sub(r"\s+", " ", str(replacement_text or "")).strip()
        if not replacement or "\n" in str(replacement_text or ""):
            raise ManualFinalSubtitleEditError("人工英文不能为空或包含换行。")
        expected = self._display_words_text(word_start, word_end)
        if replacement == expected:
            return None

        target_units = self._surface_units(replacement)
        current_units: List[str] = []
        unit_ranges: Dict[int, tuple[int, int]] = {}
        for span in self._display_word_spans(word_start, word_end):
            span_start = int(span["word_start"])
            span_end = int(span["word_end"])
            units = self._surface_units(span.get("surface", ""))
            if not units:
                raise ManualFinalSubtitleEditError(
                    f"冻结词 {span_start} 没有可编辑的英文词面。"
                )
            if span_start == span_end:
                unit_ranges[span_start] = (
                    len(current_units),
                    len(current_units) + len(units),
                )
            current_units.extend(units)

        candidates: List[Dict[str, Any]] = []
        for word_id, (unit_start, unit_end) in unit_ranges.items():
            before = current_units[:unit_start]
            after = current_units[unit_end:]
            if len(target_units) < len(before) + len(after) + 1:
                continue
            if target_units[: len(before)] != before:
                continue
            if after and target_units[-len(after) :] != after:
                continue
            replacement_end = len(target_units) - len(after) if after else len(target_units)
            replacement_units = target_units[len(before) : replacement_end]
            if not replacement_units:
                continue
            current_word_units = current_units[unit_start:unit_end]
            if replacement_units == current_word_units:
                continue
            candidates.append(
                {
                    "word_id": word_id,
                    "before_surface": " ".join(current_word_units),
                    "after_surface": " ".join(replacement_units),
                }
            )

        unique_candidates = {
            (int(item["word_id"]), str(item["after_surface"])): item
            for item in candidates
        }
        if len(unique_candidates) != 1:
            raise ManualFinalSubtitleEditError(
                "人工英文一次只能修改一个冻结词；如需调整词序或字幕边界，"
                "请继续使用边界调整功能。"
            )
        plan = next(iter(unique_candidates.values()))
        if len(self._surface_units(plan["after_surface"])) > 4 or len(
            str(plan["after_surface"])
        ) > 80:
            raise ManualFinalSubtitleEditError(
                "单个冻结词的人工替换过长；请检查是否误改了整句。"
            )
        return plan

    def _apply_english_surface_edit_plans(
        self,
        plans: Sequence[Mapping[str, Any]],
    ) -> None:
        seen_word_ids: set[int] = set()
        for raw_plan in plans:
            word_id = int(raw_plan["word_id"])
            if word_id in seen_word_ids or not 0 <= word_id < len(self.word_ledger):
                raise ManualFinalSubtitleEditError("人工英文词面修改存在重复或越界词 ID。")
            seen_word_ids.add(word_id)
            word = self.word_ledger[word_id]
            current_surface = str(word.get("surface", word.get("token", "")) or "")
            if self._surface_units(current_surface) != self._surface_units(
                raw_plan.get("before_surface", "")
            ):
                raise ManualFinalSubtitleEditError("人工英文修改基线已经变化，请重新编辑。")
            replacement = str(raw_plan.get("after_surface") or "").strip()
            word["surface"] = replacement
            if "token" in word:
                word["token"] = replacement
            word["normalized"] = " ".join(self._normalised_tokens(replacement))

        self._rebind_english_surface_overrides_to_cues()
        for edit in self.display_page_edits:
            try:
                edit["english"] = self._display_words_text(
                    int(edit["word_start"]),
                    int(edit["word_end"]),
                )
                if any(
                    int(edit["word_start"]) <= word_id <= int(edit["word_end"])
                    for word_id in seen_word_ids
                ):
                    edit["chinese_review_acknowledged"] = False
            except (KeyError, TypeError, ValueError):
                continue
        self.source_word_ledger_hash = self._semantic_word_ledger_hash(
            self.word_ledger
        )

    def _record_history(
        self,
        operation: str,
        before: Sequence[Mapping[str, Any]],
        **details: Any,
    ) -> None:
        self._remember_formal_boundary_evidence(self.cues)
        self._remember_formal_boundary_evidence(before)
        entry = {
            "operation": operation,
            "at": datetime.now().isoformat(timespec="seconds"),
            **details,
        }
        affected = self._history_affected_parent_ids(entry)
        if (
            operation in self._PARENT_SCOPED_HISTORY_OPERATIONS
            and len(affected) == 1
        ):
            parent_id = next(iter(affected))
            parent_state = self._capture_parent_runtime_state(parent_id)
            before_cue = next(
                (
                    copy.deepcopy(dict(cue))
                    for cue in before
                    if str(cue.get("cue_id") or "").strip() == parent_id
                ),
                None,
            )
            if before_cue is not None:
                parent_state["cue"] = before_cue
            entry.update(
                {
                    "history_schema_version": 2,
                    "before_parent_states": {parent_id: parent_state},
                }
            )
        else:
            entry.setdefault("before_cues", copy.deepcopy(list(before)))
            entry.setdefault(
                "before_display_page_edits",
                copy.deepcopy(self.display_page_edits),
            )
            entry.setdefault(
                "before_display_page_boundary_overrides",
                copy.deepcopy(self.display_page_boundary_overrides),
            )
            entry.setdefault(
                "before_recovered_stale_page_drafts",
                copy.deepcopy(self.recovered_stale_page_drafts),
            )
            entry.setdefault(
                "before_tail_trim",
                copy.deepcopy(self.tail_trim),
            )
            entry.setdefault(
                "before_media_derivation",
                copy.deepcopy(self.media_derivation),
            )
        self.history.append(entry)
        self.redo_history.clear()

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
            parent_states = entry.get("before_parent_states") or {}
            if isinstance(parent_states, Mapping):
                compact_cues = [
                    state.get("cue")
                    for state in parent_states.values()
                    if isinstance(state, Mapping)
                    and isinstance(state.get("cue"), Mapping)
                ]
                self._remember_formal_boundary_evidence(compact_cues)

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
            if cue.get("media_muted") and not cue.get("display_suppressed"):
                raise ManualFinalSubtitleEditError(
                    f"第 {index} 条已静音但仍显示字幕，人工终稿状态无效。"
                )
            expected_english = self._display_words_text(start, end)
            if self._normalised_tokens(
                cue.get("original_subtitle", "")
            ) != self._normalised_tokens(expected_english):
                raise ManualFinalSubtitleEditError(
                    f"第 {index} 条英文与当前词级账本不一致。"
                )
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

    def _media_mute_intervals(self) -> List[Dict[str, Any]]:
        return [
            {
                "subtitle_id": str(cue.get("cue_id") or ""),
                "start_ms": int(cue["start_time"]),
                "end_ms": int(cue["end_time"]),
            }
            for cue in self.cues
            if cue.get("media_muted")
        ]

    def _media_mute_decision_payload(
        self,
        source_media_sha256: str,
        intervals: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "source_media_sha256": str(source_media_sha256 or ""),
            "source_word_ledger_hash": self._semantic_word_ledger_hash(
                self.word_ledger
            ),
            "intervals": [
                {
                    "subtitle_id": str(item.get("subtitle_id") or ""),
                    "start_ms": int(item.get("start_ms") or 0),
                    "end_ms": int(item.get("end_ms") or 0),
                }
                for item in intervals
            ],
        }

    def _media_derivation_decision_payload(
        self,
        source_media_sha256: str,
        *,
        cut_ms: int | None,
        mute_intervals: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "schema_version": 2,
            "source_media_sha256": str(source_media_sha256 or ""),
            "source_word_ledger_hash": self._semantic_word_ledger_hash(
                self.word_ledger
            ),
            "cut_ms": int(cut_ms) if cut_ms is not None else None,
            "mute_intervals": [
                {
                    "subtitle_id": str(item.get("subtitle_id") or ""),
                    "start_ms": int(item.get("start_ms") or 0),
                    "end_ms": int(item.get("end_ms") or 0),
                }
                for item in mute_intervals
            ],
        }

    @staticmethod
    def _validate_ordered_mute_intervals(
        intervals: Sequence[Mapping[str, Any]],
        *,
        cut_ms: int | None = None,
    ) -> None:
        previous_end = -1
        for interval in intervals:
            subtitle_id = str(interval.get("subtitle_id") or "").strip()
            start_ms = int(interval.get("start_ms") or 0)
            end_ms = int(interval.get("end_ms") or 0)
            if (
                not subtitle_id
                or start_ms < 0
                or end_ms <= start_ms
                or start_ms < previous_end
                or (cut_ms is not None and end_ms > int(cut_ms))
            ):
                raise ManualFinalSubtitleEditError("媒体派生中的静音区间无效或不按字幕顺序。")
            previous_end = end_ms

    def _validate_media_mute_contract(
        self,
        *,
        manifest: Mapping[str, Any] | None = None,
        manifest_path: Path | None = None,
        require_materialized: bool = False,
    ) -> None:
        intervals = self._media_mute_intervals()
        if self.media_derivation:
            source_hash = str(
                self.media_derivation.get("source_media_sha256") or ""
            )
            raw_cut = self.media_derivation.get("cut_ms")
            try:
                cut_ms = int(raw_cut) if raw_cut is not None else None
            except (TypeError, ValueError) as exc:
                raise ManualFinalSubtitleEditError("媒体派生切点无效。") from exc
            if cut_ms is not None and cut_ms <= 0:
                raise ManualFinalSubtitleEditError("媒体派生切点无效。")
            if self.tail_trim and int(self.tail_trim.get("cut_ms") or 0) != int(
                cut_ms or 0
            ):
                raise ManualFinalSubtitleEditError("媒体派生切点与尾部裁剪决定不一致。")
            self._validate_ordered_mute_intervals(intervals, cut_ms=cut_ms)
            expected_decision = self._media_derivation_decision_payload(
                source_hash,
                cut_ms=cut_ms,
                mute_intervals=intervals,
            )
            if (
                not source_hash
                or list(self.media_derivation.get("mute_intervals") or []) != intervals
                or str(self.media_derivation.get("source_word_ledger_hash") or "")
                != str(expected_decision["source_word_ledger_hash"])
                or str(self.media_derivation.get("decision_hash") or "")
                != stable_payload_hash(expected_decision)
            ):
                raise ManualFinalSubtitleEditError(
                    "媒体派生决定与当前字幕 ID、时间轴或词账本不一致。"
                )
            original_text = str(
                self.media_derivation.get("source_media_path") or ""
            ).strip()
            if original_text:
                original_path = Path(original_text)
                if original_path.is_file() and file_sha256(original_path) != source_hash:
                    raise ManualFinalSubtitleEditError("媒体派生绑定的原始音频哈希不一致。")
            if require_materialized:
                if manifest is None or manifest_path is None:
                    raise ManualFinalSubtitleEditError("无法校验派生音频。")
                manifest_record = (
                    (manifest.get("manual_final_override") or {}).get(
                        "media_derivation"
                    )
                    or manifest.get("media_derivation")
                    or {}
                )
                if dict(manifest_record) != self.media_derivation:
                    raise ManualFinalSubtitleEditError(
                        "人工终稿清单与编辑记录中的媒体派生合同不一致。"
                    )
                derived_hash = str(
                    self.media_derivation.get("derived_media_sha256") or ""
                )
                derived_path = resolve_manifest_owned_path(
                    Path(manifest_path),
                    manifest,
                    str(self.media_derivation.get("derived_media_path") or ""),
                    derived_hash,
                )
                if derived_path is None or not derived_hash:
                    raise ManualFinalSubtitleEditError("派生音频路径或哈希无效。")
            return
        if not intervals:
            if self.media_mute:
                raise ManualFinalSubtitleEditError(
                    "静音合同存在，但没有对应的固定字幕区间。"
                )
            return
        if not self.media_mute:
            if require_materialized:
                raise ManualFinalSubtitleEditError(
                    "隐藏并静音的字幕缺少派生音频合同。"
                )
            return

        source_hash = str(self.media_mute.get("source_media_sha256") or "")
        expected_decision = self._media_mute_decision_payload(
            source_hash,
            intervals,
        )
        if (
            not source_hash
            or list(self.media_mute.get("intervals") or []) != intervals
            or list(self.media_mute.get("muted_subtitle_ids") or [])
            != [item["subtitle_id"] for item in intervals]
            or str(self.media_mute.get("source_word_ledger_hash") or "")
            != str(expected_decision["source_word_ledger_hash"])
            or str(self.media_mute.get("decision_hash") or "")
            != stable_payload_hash(expected_decision)
        ):
            raise ManualFinalSubtitleEditError(
                "隐藏并静音决定与当前字幕 ID、时间轴或词账本不一致。"
            )

        original_text = str(self.media_mute.get("source_media_path") or "").strip()
        if original_text:
            original_path = Path(original_text)
            if original_path.is_file() and file_sha256(original_path) != source_hash:
                raise ManualFinalSubtitleEditError(
                    "隐藏并静音合同绑定的原始音频哈希不一致。"
                )
        if require_materialized:
            if manifest is None or manifest_path is None:
                raise ManualFinalSubtitleEditError("无法校验派生静音音频。")
            manifest_record = (
                (manifest.get("manual_final_override") or {}).get("media_mute")
                or manifest.get("media_mute")
                or {}
            )
            if dict(manifest_record) != self.media_mute:
                raise ManualFinalSubtitleEditError(
                    "人工终稿清单与编辑记录中的静音合同不一致。"
                )
            derived_hash = str(self.media_mute.get("derived_media_sha256") or "")
            derived_path = resolve_manifest_owned_path(
                Path(manifest_path),
                manifest,
                str(self.media_mute.get("derived_media_path") or ""),
                derived_hash,
            )
            if derived_path is None or not derived_hash:
                raise ManualFinalSubtitleEditError(
                    "派生静音音频路径或哈希无效。"
                )

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
            compact_states = entry.get("before_parent_states") or {}
            compact_page_state = any(
                bool(state.get("display_page_edits"))
                or bool(state.get("display_page_boundary_override"))
                for state in compact_states.values()
                if isinstance(state, Mapping)
            ) if isinstance(compact_states, Mapping) else False
            if (
                entry.get("before_display_page_edits")
                or entry.get("before_display_page_boundary_overrides")
                or compact_page_state
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
                "english_surface_overrides": self.english_surface_overrides,
                "cues": self.cues,
                "display_page_edits": self.display_page_edits,
                "display_page_boundary_overrides": (
                    self.display_page_boundary_overrides
                ),
                "recovered_stale_page_drafts": self.recovered_stale_page_drafts,
                "tail_trim": self.tail_trim,
                "media_mute": self.media_mute,
                "media_derivation": self.media_derivation,
            }
        )

    def _current_parent_chinese_authority(self) -> Dict[str, Any]:
        try:
            previous_by_id = parent_chinese_records_by_id(
                self.parent_chinese_authority
            )
        except (AuthoritativeParentChineseError, TypeError, ValueError):
            previous_by_id = {}
        records: List[Dict[str, Any]] = []
        for cue in self.cues:
            subtitle_id = str(cue.get("cue_id") or "")
            previous = previous_by_id.get(subtitle_id, {})
            candidate = build_authoritative_parent_chinese_artifact(
                [cue],
                source_word_ledger_hash=self.source_word_ledger_hash,
                producer="manual_final_editor",
            )["records"][0]
            unchanged = bool(
                previous
                and str(previous.get("source_hash") or "")
                == str(candidate.get("source_hash") or "")
                and str(previous.get("chinese_hash") or "")
                == str(candidate.get("chinese_hash") or "")
            )
            records.append(
                {
                    **cue,
                    "provenance": (
                        dict(previous.get("provenance") or {})
                        if unchanged
                        else {
                            "kind": "manual_override",
                            "producer": "manual_final_editor",
                            "base_record_hash": str(
                                previous.get("record_hash") or ""
                            ),
                            "display_page_contract_hash": "",
                        }
                    ),
                }
            )
        return build_authoritative_parent_chinese_artifact(
            records,
            source_word_ledger_hash=self.source_word_ledger_hash,
            producer="manual_final_editor",
        )

    def snapshot_for_save(self) -> "ManualFinalSubtitleSession":
        """Freeze current editor state without copying immutable history payloads."""
        snapshot = copy.copy(self)
        snapshot.word_ledger = copy.deepcopy(self.word_ledger)
        snapshot.cues = copy.deepcopy(self.cues)
        snapshot.parent_chinese_authority = copy.deepcopy(
            self.parent_chinese_authority
        )
        # History entries are append-only after creation.  The save worker only
        # serializes them, while the UI is disabled for the duration of save.
        snapshot.history = list(self.history)
        snapshot.redo_history = list(self.redo_history)
        snapshot.display_page_edits = copy.deepcopy(self.display_page_edits)
        snapshot.display_page_boundary_overrides = copy.deepcopy(
            self.display_page_boundary_overrides
        )
        snapshot.recovered_formal_boundary_evidence = copy.deepcopy(
            self.recovered_formal_boundary_evidence
        )
        snapshot.recovered_stale_page_drafts = copy.deepcopy(
            self.recovered_stale_page_drafts
        )
        snapshot.tail_trim = copy.deepcopy(self.tail_trim)
        snapshot.media_mute = copy.deepcopy(self.media_mute)
        snapshot.media_derivation = copy.deepcopy(self.media_derivation)
        snapshot._display_page_model_cache_key = ""
        snapshot._display_page_model_cache = {}
        snapshot._display_page_preview_cache = {}
        return snapshot

    def recovery_draft_path(self) -> Path:
        """Return a manifest-bound sidecar that never publishes a final package."""
        try:
            manifest_hash = file_sha256(self.manifest_path)
        except OSError as exc:
            raise ManualFinalSubtitleEditError(
                "当前稳定清单不可读取，无法保存恢复草稿。"
            ) from exc
        return (
            self.manifest_path.parent
            / ".manual-editor-drafts"
            / f"{manifest_hash[:24]}.json"
        )

    def save_recovery_draft(self) -> Path:
        """Atomically persist editable state without publishing a final package."""
        self._validate_cues()
        self._validate_display_page_boundary_overrides()
        draft_path = self.recovery_draft_path()
        state = self._capture_runtime_state()
        payload = {
            "schema_version": 1,
            "kind": "manual-final-working-draft",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "base_manifest_sha256": file_sha256(self.manifest_path),
            "base_subtitle_sha256": file_sha256(self.subtitle_path),
            "state": state,
            "history": self.history,
            "redo_history": self.redo_history,
        }
        payload["draft_state_hash"] = stable_payload_hash(
            {
                "state": state,
                "history": self.history,
                "redo_history": self.redo_history,
            }
        )
        write_json_artifact(draft_path, payload, compact=True)
        return draft_path

    def restore_recovery_draft(self) -> bool:
        """Restore a draft only when its published base is still exact."""
        draft_path = self.recovery_draft_path()
        if not draft_path.is_file():
            return False
        payload = self._read_json(draft_path)
        if (
            int(payload.get("schema_version") or 0) != 1
            or str(payload.get("kind") or "") != "manual-final-working-draft"
            or str(payload.get("base_manifest_sha256") or "")
            != file_sha256(self.manifest_path)
            or str(payload.get("base_subtitle_sha256") or "")
            != file_sha256(self.subtitle_path)
        ):
            return False
        state = payload.get("state") or {}
        history = list(payload.get("history") or [])
        redo_history = list(payload.get("redo_history") or [])
        expected_hash = stable_payload_hash(
            {
                "state": state,
                "history": history,
                "redo_history": redo_history,
            }
        )
        if str(payload.get("draft_state_hash") or "") != expected_hash:
            raise ManualFinalSubtitleEditError("人工恢复草稿内容不完整或已损坏。")
        candidate = copy.copy(self)
        candidate._restore_runtime_state(state)
        candidate.history = history
        candidate.redo_history = redo_history
        candidate.compact_english_surface_history()
        candidate.compact_parent_scoped_history()
        embedded_hash = candidate._semantic_word_ledger_hash(candidate.word_ledger)
        accepted_hashes = {
            embedded_hash,
            candidate._legacy_word_ledger_hash(candidate.word_ledger),
        }
        if candidate.source_word_ledger_hash not in accepted_hashes:
            raise ManualFinalSubtitleEditError("人工恢复草稿的词账本哈希不一致。")
        self._restore_runtime_state(state)
        self.history = candidate.history
        self.redo_history = redo_history
        self.import_notice = "已恢复上次未保存的人工字幕草稿。"
        return True

    def discard_recovery_draft(self) -> None:
        try:
            self.recovery_draft_path().unlink(missing_ok=True)
        except (ManualFinalSubtitleEditError, OSError):
            pass

    def _invalidate_display_page_state(self) -> None:
        self.display_page_edits = []
        self.display_page_boundary_overrides = {}

    def _display_page_rows_before_formal_boundary_change(
        self,
    ) -> List[Dict[str, Any]]:
        """Snapshot a complete visible page model before parent spans change."""
        rows = self._visible_display_page_rows(self._display_page_model_data())
        if not rows or any(
            row.get("display_page_unavailable")
            or not str(row.get("display_page_id") or "")
            for row in rows
        ):
            return []
        return rows

    def _recover_identity_matched_history_page_drafts(self) -> int:
        """Recover only blank current pages from the package's hashed undo history."""
        current_rows = self._visible_display_page_rows(
            self._display_page_model_data()
        )
        missing_by_page_id = {
            str(row.get("display_page_id") or ""): row
            for row in current_rows
            if str(row.get("display_page_id") or "")
            and (
                not str(row.get("translated_subtitle") or "").strip()
                or str(row.get("display_page_chinese_draft_kind") or "")
                == "parent_chinese_fallback"
            )
            and not row.get("display_page_unavailable")
        }
        if not missing_by_page_id:
            return 0

        candidates: Dict[str, Dict[str, Any]] = {}
        for history_entry in self.history:
            if not isinstance(history_entry, Mapping):
                continue
            history_edits = list(
                history_entry.get("before_display_page_edits") or []
            )
            compact_states = history_entry.get("before_parent_states") or {}
            if isinstance(compact_states, Mapping):
                for state in compact_states.values():
                    if isinstance(state, Mapping):
                        history_edits.extend(
                            state.get("display_page_edits") or []
                        )
            for raw_edit in history_edits:
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
        rebuilt_rows = self._visible_display_page_rows(
            self._display_page_model_data()
        )
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
        """Apply parent text while keeping IDs, word ownership, and times fixed."""
        if len(rows) != len(self.cues):
            raise ManualFinalSubtitleEditError(
                "字幕行数已变化，无法安全应用人工终稿操作。"
            )
        chinese_updates: List[tuple[Dict[str, Any], str]] = []
        english_plans: List[Dict[str, Any]] = []
        english_parent_ids: set[str] = set()
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
            row_english = str(row.get("original_subtitle") or "")
            if row_english != str(cue.get("original_subtitle") or ""):
                plan = self._plan_english_surface_edit(
                    word_start=int(cue["word_start"]),
                    word_end=int(cue["word_end"]),
                    replacement_text=row_english,
                )
                if plan is not None:
                    english_plans.append(plan)
                    english_parent_ids.add(str(cue.get("cue_id") or ""))
            chinese = str(row.get("translated_subtitle") or "")
            if chinese != str(cue.get("translated_subtitle") or ""):
                chinese_updates.append((cue, chinese))
        if not chinese_updates and not english_plans:
            return False
        affected_parent_ids = sorted(
            english_parent_ids
            | {
                str(cue.get("cue_id") or "")
                for cue, _chinese in chinese_updates
            }
        )
        before = (
            copy.deepcopy(self.cues)
            if english_plans or len(affected_parent_ids) != 1
            else ()
        )
        self._record_history(
            "edit_english_surface" if english_plans else "edit_parent_chinese",
            before,
            affected_parent_ids=affected_parent_ids,
            before_word_ledger_items=(
                [
                    {
                        "word_id": word_id,
                        "word": copy.deepcopy(self.word_ledger[word_id]),
                    }
                    for word_id in sorted(
                        {int(plan["word_id"]) for plan in english_plans}
                    )
                ]
                if english_plans
                else []
            ),
            before_source_word_ledger_hash=(
                self.source_word_ledger_hash if english_plans else ""
            ),
            before_formal_word_ledger_hash=(
                self._formal_word_ledger_hash(self.word_ledger)
                if english_plans
                else ""
            ),
        )
        if english_plans:
            self._apply_english_surface_edit_plans(english_plans)
        for cue, chinese in chinese_updates:
            cue["translated_subtitle"] = chinese
        for cue in self.cues:
            if str(cue.get("cue_id") or "") in english_parent_ids:
                cue["chinese_review_required"] = True
        self._validate_cues()
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
        before_surface_overrides = copy.deepcopy(self.english_surface_overrides)
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
        self._assert_boundary_outside_english_surface_overrides(boundary)
        before = copy.deepcopy([left, right])
        left["word_end"] = boundary - 1
        right["word_start"] = boundary
        self._rebind_english_surface_overrides_to_cues()
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
            before_english_surface_overrides=before_surface_overrides,
        )
        pages_preserved = self._reflow_display_page_state_after_formal_boundary_change(
            previous_page_rows,
            [str(left.get("cue_id") or ""), str(right.get("cue_id") or "")],
        )
        if (previous_page_rows or before_page_edits or before_page_overrides) and not pages_preserved:
            self.cues[left_index : left_index + 2] = before
            self.display_page_edits = before_page_edits
            self.display_page_boundary_overrides = before_page_overrides
            self.english_surface_overrides = before_surface_overrides
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
        before_surface_overrides = copy.deepcopy(self.english_surface_overrides)
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
        self._assert_boundary_outside_english_surface_overrides(boundary)
        before = copy.deepcopy([left, right])
        left["word_end"] = boundary - 1
        right["word_start"] = boundary
        self._rebind_english_surface_overrides_to_cues()
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
            before_english_surface_overrides=before_surface_overrides,
        )
        pages_preserved = self._reflow_display_page_state_after_formal_boundary_change(
            previous_page_rows,
            [str(left.get("cue_id") or ""), str(right.get("cue_id") or "")],
        )
        if (previous_page_rows or before_page_edits or before_page_overrides) and not pages_preserved:
            self.cues[right_index - 1 : right_index + 1] = before
            self.display_page_edits = before_page_edits
            self.display_page_boundary_overrides = before_page_overrides
            self.english_surface_overrides = before_surface_overrides
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
        before_surface_overrides = copy.deepcopy(self.english_surface_overrides)
        merged = {
            "cue_id": str(selected[0]["cue_id"]),
            "source_subtitle_ids": [
                source_id for cue in selected for source_id in cue.get("source_subtitle_ids", [])
            ],
            "word_start": int(selected[0]["word_start"]),
            "word_end": int(selected[-1]["word_end"]),
            "start_time": int(selected[0]["start_time"]),
            "end_time": int(selected[-1]["end_time"]),
            "original_subtitle": self._display_words_text(
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
        self._rebind_english_surface_overrides_to_cues()
        self._validate_cues()
        self._record_history(
            "merge_adjacent",
            before,
            first_index=first_index,
            last_index=last_index,
            before_english_surface_overrides=before_surface_overrides,
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
            self.english_surface_overrides = before_surface_overrides
            self.history.pop()
            self._validate_cues()
            self._validate_display_page_boundary_overrides()
            raise ManualFinalSubtitleEditError(
                "合并后的实际分页无法满足固定词账本、时间轴或排版约束，字幕未修改。"
            )

    def set_cue_display_suppressed(
        self,
        parent_subtitle_id: str,
        suppressed: bool,
    ) -> Dict[str, Any]:
        """Hide one parent cue from rendering without trimming media or ledger words."""
        parent_id = str(parent_subtitle_id or "").strip()
        cue = next(
            (
                item
                for item in self.cues
                if str(item.get("cue_id") or "") == parent_id
            ),
            None,
        )
        if cue is None:
            raise ManualFinalSubtitleEditError("找不到要隐藏的固定字幕 ID。")
        target = bool(suppressed)
        if not target and cue.get("media_muted"):
            raise ManualFinalSubtitleEditError(
                "该条同时隐藏并静音；请使用“恢复字幕和声音”。"
            )
        if bool(cue.get("display_suppressed")) == target:
            return {"changed": False, "subtitle_id": parent_id, "suppressed": target}
        if target and sum(
            not bool(item.get("display_suppressed")) for item in self.cues
        ) <= 1:
            raise ManualFinalSubtitleEditError("至少需要保留一条可显示字幕。")

        self._record_history(
            "set_display_suppressed",
            (),
            affected_parent_ids=[parent_id],
            parent_subtitle_id=parent_id,
            suppressed=target,
        )
        cue["display_suppressed"] = target
        if target:
            self.display_page_edits = [
                item
                for item in self.display_page_edits
                if str(item.get("parent_subtitle_id") or "") != parent_id
            ]
            self.display_page_boundary_overrides.pop(parent_id, None)
        self._display_page_preview_cache.pop(parent_id, None)
        self._validate_cues()
        return {"changed": True, "subtitle_id": parent_id, "suppressed": target}

    def set_cue_hidden_and_media_muted(
        self,
        parent_subtitle_id: str,
        enabled: bool,
    ) -> Dict[str, Any]:
        """Hide one complete parent cue and mute only its fixed timeline span."""
        parent_id = str(parent_subtitle_id or "").strip()
        cue = next(
            (
                item
                for item in self.cues
                if str(item.get("cue_id") or "") == parent_id
            ),
            None,
        )
        if cue is None:
            raise ManualFinalSubtitleEditError("找不到要隐藏并静音的固定字幕 ID。")
        target = bool(enabled)
        current = bool(cue.get("media_muted")) and bool(
            cue.get("display_suppressed")
        )
        if current == target:
            return {
                "changed": False,
                "subtitle_id": parent_id,
                "hidden_and_muted": target,
            }
        if target and not cue.get("display_suppressed") and sum(
            not bool(item.get("display_suppressed")) for item in self.cues
        ) <= 1:
            raise ManualFinalSubtitleEditError("至少需要保留一条可显示字幕。")

        self._record_history(
            "set_hidden_and_media_muted",
            copy.deepcopy(self.cues),
            affected_parent_ids=[parent_id],
            parent_subtitle_id=parent_id,
            hidden_and_muted=target,
            before_media_mute=copy.deepcopy(self.media_mute),
            before_media_derivation=copy.deepcopy(self.media_derivation),
            before_source_media_path=(
                str(self.source_media_path.resolve())
                if self.source_media_path is not None
                else ""
            ),
        )
        cue["media_muted"] = target
        cue["display_suppressed"] = target
        self.media_derivation = {}
        if target:
            self.display_page_edits = [
                item
                for item in self.display_page_edits
                if str(item.get("parent_subtitle_id") or "") != parent_id
            ]
            self.display_page_boundary_overrides.pop(parent_id, None)
        elif not any(bool(item.get("media_muted")) for item in self.cues):
            original_media = self._media_mute_source_media_path()
            if original_media is not None:
                self.source_media_path = original_media.resolve()
            self.media_mute = {}
        self._display_page_preview_cache.pop(parent_id, None)
        self._validate_cues()
        return {
            "changed": True,
            "subtitle_id": parent_id,
            "hidden_and_muted": target,
        }

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
        entry = self._latest_history_entry_for_parent(parent_id)
        return bool(entry and self._history_is_parent_scoped(entry, parent_id))

    def undo_for_parent(self, parent_subtitle_id: str) -> bool:
        parent_id = str(parent_subtitle_id or "").strip()
        found = self._latest_history_entry_for_parent(parent_id, with_index=True)
        if found is None:
            raise ManualFinalSubtitleEditError(
                "当前字幕没有可撤销的最新调整；分页或中文历史可能已不存在。"
            )
        history_index, entry = found
        if not self._history_is_parent_scoped(entry, parent_id):
            raise ManualFinalSubtitleEditError(
                "这次操作同时影响了跨字幕边界、词账本或音频，不能只撤销一行；"
                "请使用整体撤销。"
            )
        return self._undo_parent_scoped_history_entry(history_index, parent_id)

    _PARENT_SCOPED_HISTORY_OPERATIONS = {
        "edit_parent_chinese",
        "edit_display_page_chinese",
        "set_display_suppressed",
        "move_display_page_boundary",
        "split_parent_into_display_pages",
        "split_display_page",
        "merge_display_page_with_next",
        "confirm_display_page_boundary",
        "confirm_all_nonblocking_display_page_reviews",
    }

    def _latest_history_entry_for_parent(
        self,
        parent_subtitle_id: str,
        *,
        with_index: bool = False,
    ) -> Any:
        parent_id = str(parent_subtitle_id or "").strip()
        if not parent_id:
            return None
        for index in range(len(self.history) - 1, -1, -1):
            entry = self.history[index]
            if parent_id in self._history_affected_parent_ids(entry):
                return (index, entry) if with_index else entry
        return None

    @classmethod
    def _history_is_parent_scoped(
        cls,
        entry: Mapping[str, Any],
        parent_subtitle_id: str,
    ) -> bool:
        affected = cls._history_affected_parent_ids(entry)
        return bool(
            str(entry.get("operation") or "")
            in cls._PARENT_SCOPED_HISTORY_OPERATIONS
            and affected == {str(parent_subtitle_id or "").strip()}
        )

    @staticmethod
    def _parent_page_items(
        values: Sequence[Mapping[str, Any]],
        parent_subtitle_id: str,
    ) -> List[Dict[str, Any]]:
        parent_id = str(parent_subtitle_id or "").strip()
        return [
            copy.deepcopy(dict(value))
            for value in values
            if str(value.get("parent_subtitle_id") or "").strip() == parent_id
        ]

    def _capture_parent_runtime_state(self, parent_subtitle_id: str) -> Dict[str, Any]:
        parent_id = str(parent_subtitle_id or "").strip()
        cue = next(
            (
                copy.deepcopy(dict(value))
                for value in self.cues
                if str(value.get("cue_id") or "").strip() == parent_id
            ),
            None,
        )
        drafts = {
            str(page_id): copy.deepcopy(dict(value))
            for page_id, value in self.recovered_stale_page_drafts.items()
            if str(page_id).startswith(f"{parent_id}.P")
        }
        return {
            "parent_subtitle_id": parent_id,
            "cue": cue,
            "display_page_edits": self._parent_page_items(
                self.display_page_edits, parent_id
            ),
            "has_display_page_boundary_override": (
                parent_id in self.display_page_boundary_overrides
            ),
            "display_page_boundary_override": copy.deepcopy(
                self.display_page_boundary_overrides.get(parent_id) or []
            ),
            "recovered_stale_page_drafts": drafts,
        }

    def _parent_runtime_state_before_history(
        self,
        entry: Mapping[str, Any],
        parent_subtitle_id: str,
    ) -> Dict[str, Any]:
        parent_id = str(parent_subtitle_id or "").strip()
        compact_states = entry.get("before_parent_states") or {}
        if isinstance(compact_states, Mapping):
            compact_state = compact_states.get(parent_id)
            if isinstance(compact_state, Mapping):
                return copy.deepcopy(dict(compact_state))
        cue = next(
            (
                copy.deepcopy(dict(value))
                for value in entry.get("before_cues") or []
                if str(value.get("cue_id") or "").strip() == parent_id
            ),
            None,
        )
        overrides = entry.get("before_display_page_boundary_overrides") or {}
        drafts = entry.get("before_recovered_stale_page_drafts") or {}
        return {
            "parent_subtitle_id": parent_id,
            "cue": cue,
            "display_page_edits": self._parent_page_items(
                entry.get("before_display_page_edits") or [], parent_id
            ),
            "has_display_page_boundary_override": parent_id in overrides,
            "display_page_boundary_override": copy.deepcopy(
                overrides.get(parent_id) or []
            ),
            "recovered_stale_page_drafts": {
                str(page_id): copy.deepcopy(dict(value))
                for page_id, value in drafts.items()
                if str(page_id).startswith(f"{parent_id}.P")
            },
        }

    def compact_parent_scoped_history(self) -> int:
        """Migrate legacy full-document entries to parent-sized undo commands."""
        compacted = 0
        migrated: List[Dict[str, Any]] = []
        full_state_keys = {
            "before_cues",
            "before_display_page_edits",
            "before_display_page_boundary_overrides",
            "before_recovered_stale_page_drafts",
            "before_tail_trim",
        }
        for raw_entry in self.history:
            entry = dict(raw_entry)
            affected = self._history_affected_parent_ids(entry)
            if (
                entry.get("before_parent_states")
                or not self._history_is_parent_scoped(
                    entry,
                    next(iter(affected)) if len(affected) == 1 else "",
                )
            ):
                migrated.append(raw_entry)
                continue
            parent_id = next(iter(affected))
            parent_state = self._parent_runtime_state_before_history(
                entry,
                parent_id,
            )
            if not isinstance(parent_state.get("cue"), Mapping):
                migrated.append(raw_entry)
                continue
            compact_entry = {
                key: copy.deepcopy(value)
                for key, value in entry.items()
                if key not in full_state_keys
            }
            compact_entry["history_schema_version"] = 2
            compact_entry["before_parent_states"] = {
                parent_id: parent_state
            }
            migrated.append(compact_entry)
            compacted += 1
        if compacted:
            self.history = migrated
        return compacted

    def compact_english_surface_history(self) -> int:
        """Replace legacy full-ledger English undo payloads with word deltas."""
        compacted = 0
        rolling_ledger = copy.deepcopy(self.word_ledger)
        migrated_reversed: List[Dict[str, Any]] = []
        for raw_entry in reversed(self.history):
            entry = dict(raw_entry)
            before_ledger = entry.get("before_word_ledger")
            before_items = list(entry.get("before_word_ledger_items") or [])
            if (
                str(entry.get("operation") or "") == "edit_english_surface"
                and isinstance(before_ledger, list)
                and len(before_ledger) == len(rolling_ledger)
            ):
                changed_word_ids = [
                    word_id
                    for word_id, (before_word, after_word) in enumerate(
                        zip(before_ledger, rolling_ledger)
                    )
                    if before_word != after_word
                ]
                if changed_word_ids:
                    compact_entry = {
                        key: copy.deepcopy(value)
                        for key, value in entry.items()
                        if key != "before_word_ledger"
                    }
                    compact_entry["before_word_ledger_items"] = [
                        {
                            "word_id": word_id,
                            "word": copy.deepcopy(before_ledger[word_id]),
                        }
                        for word_id in changed_word_ids
                    ]
                    compact_entry["before_formal_word_ledger_hash"] = (
                        self._formal_word_ledger_hash(before_ledger)
                    )
                    entry = compact_entry
                    compacted += 1
                rolling_ledger = copy.deepcopy(before_ledger)
            elif (
                str(entry.get("operation") or "") == "edit_english_surface"
                and before_items
            ):
                for item in before_items:
                    try:
                        word_id = int(item.get("word_id", -1))
                    except (TypeError, ValueError):
                        continue
                    word = item.get("word")
                    if 0 <= word_id < len(rolling_ledger) and isinstance(
                        word, Mapping
                    ):
                        rolling_ledger[word_id] = copy.deepcopy(dict(word))
            elif (
                isinstance(before_ledger, list)
                and before_ledger
                and str(entry.get("operation") or "") == "trim_tail_from_cue"
            ):
                rolling_ledger = copy.deepcopy(before_ledger)
            migrated_reversed.append(entry)
        if compacted:
            self.history = list(reversed(migrated_reversed))
        return compacted

    def _restore_parent_runtime_state(self, state: Mapping[str, Any]) -> None:
        parent_id = str(state.get("parent_subtitle_id") or "").strip()
        cue = state.get("cue")
        cue_index = next(
            (
                index
                for index, value in enumerate(self.cues)
                if str(value.get("cue_id") or "").strip() == parent_id
            ),
            -1,
        )
        if cue_index < 0 or not isinstance(cue, Mapping):
            raise ManualFinalSubtitleEditError(
                "当前字幕身份已变化，无法安全恢复这条字幕的历史。"
            )
        self.cues[cue_index] = copy.deepcopy(dict(cue))
        other_edits = [
            copy.deepcopy(dict(value))
            for value in self.display_page_edits
            if str(value.get("parent_subtitle_id") or "").strip() != parent_id
        ]
        restored_edits = [
            copy.deepcopy(dict(value))
            for value in state.get("display_page_edits") or []
        ]
        cue_order = {
            str(value.get("cue_id") or ""): index
            for index, value in enumerate(self.cues)
        }
        self.display_page_edits = sorted(
            [*other_edits, *restored_edits],
            key=lambda value: (
                cue_order.get(str(value.get("parent_subtitle_id") or ""), 10**9),
                int(value.get("word_start", 10**9)),
                str(value.get("display_page_id") or ""),
            ),
        )
        if state.get("has_display_page_boundary_override"):
            self.display_page_boundary_overrides[parent_id] = [
                int(value)
                for value in state.get("display_page_boundary_override") or []
            ]
        else:
            self.display_page_boundary_overrides.pop(parent_id, None)
        self.recovered_stale_page_drafts = {
            page_id: value
            for page_id, value in self.recovered_stale_page_drafts.items()
            if not str(page_id).startswith(f"{parent_id}.P")
        }
        self.recovered_stale_page_drafts.update(
            {
                str(page_id): copy.deepcopy(dict(value))
                for page_id, value in (
                    state.get("recovered_stale_page_drafts") or {}
                ).items()
            }
        )
        if self.media_mute and not any(
            bool(value.get("media_muted")) for value in self.cues
        ):
            original_media = self._media_mute_source_media_path()
            if original_media is not None:
                self.source_media_path = original_media.resolve()
            self.media_mute = {}
        self._display_page_preview_cache.pop(parent_id, None)
        self._validate_cues()
        self._validate_display_page_boundary_overrides()

    def _undo_parent_scoped_history_entry(
        self,
        history_index: int,
        parent_subtitle_id: str,
    ) -> bool:
        entry = self.history[history_index]
        parent_id = str(parent_subtitle_id or "").strip()
        after = self._capture_parent_runtime_state(parent_id)
        before = self._parent_runtime_state_before_history(entry, parent_id)
        self._restore_parent_runtime_state(before)
        self.history.pop(history_index)
        self.redo_history.append(
            {
                "history_entry": copy.deepcopy(entry),
                "parent_scoped_after": after,
                "affected_parent_ids": [parent_id],
            }
        )
        return True

    def _capture_runtime_state(self) -> Dict[str, Any]:
        return {
            "word_ledger": copy.deepcopy(self.word_ledger),
            "english_surface_overrides": copy.deepcopy(
                self.english_surface_overrides
            ),
            "cues": copy.deepcopy(self.cues),
            "source_word_ledger_hash": self.source_word_ledger_hash,
            "display_page_edits": copy.deepcopy(self.display_page_edits),
            "display_page_boundary_overrides": copy.deepcopy(
                self.display_page_boundary_overrides
            ),
            "recovered_formal_boundary_evidence": copy.deepcopy(
                self.recovered_formal_boundary_evidence
            ),
            "recovered_stale_page_drafts": copy.deepcopy(
                self.recovered_stale_page_drafts
            ),
            "tail_trim": copy.deepcopy(self.tail_trim),
            "media_mute": copy.deepcopy(self.media_mute),
            "media_derivation": copy.deepcopy(self.media_derivation),
            "source_media_path": (
                str(self.source_media_path) if self.source_media_path else ""
            ),
            "artifact_dir": str(self.artifact_dir),
        }

    def _capture_english_history_state(
        self,
        history_entry: Mapping[str, Any],
    ) -> Dict[str, Any]:
        word_ids: set[int] = set()
        for item in history_entry.get("before_word_ledger_items") or []:
            try:
                word_id = int(item.get("word_id", -1))
            except (AttributeError, TypeError, ValueError):
                continue
            if 0 <= word_id < len(self.word_ledger):
                word_ids.add(word_id)
        return {
            "word_ledger_items": [
                {
                    "word_id": word_id,
                    "word": copy.deepcopy(self.word_ledger[word_id]),
                }
                for word_id in sorted(word_ids)
            ],
            "cues": copy.deepcopy(self.cues),
            "source_word_ledger_hash": self.source_word_ledger_hash,
            "display_page_edits": copy.deepcopy(self.display_page_edits),
        }

    def _restore_english_history_state(
        self,
        state: Mapping[str, Any],
    ) -> None:
        for item in state.get("word_ledger_items") or []:
            word_id = int(item.get("word_id", -1))
            word = item.get("word")
            if not 0 <= word_id < len(self.word_ledger) or not isinstance(
                word, Mapping
            ):
                raise ManualFinalSubtitleEditError(
                    "人工英文撤销记录引用了无效的冻结词。"
                )
            self.word_ledger[word_id] = copy.deepcopy(dict(word))
        self.cues = copy.deepcopy(list(state.get("cues") or []))
        self.source_word_ledger_hash = str(
            state.get("source_word_ledger_hash") or ""
        )
        self.display_page_edits = copy.deepcopy(
            list(state.get("display_page_edits") or [])
        )
        self._validate_cues()

    def _restore_runtime_state(self, state: Mapping[str, Any]) -> None:
        self.word_ledger = copy.deepcopy(list(state.get("word_ledger") or []))
        self.english_surface_overrides = self._parse_english_surface_overrides(
            state.get("english_surface_overrides")
        )
        self.cues = copy.deepcopy(list(state.get("cues") or []))
        self.source_word_ledger_hash = str(
            state.get("source_word_ledger_hash") or ""
        )
        self.display_page_edits = copy.deepcopy(
            list(state.get("display_page_edits") or [])
        )
        self.display_page_boundary_overrides = (
            self._parse_display_page_boundary_overrides(
                state.get("display_page_boundary_overrides")
            )
        )
        self.recovered_formal_boundary_evidence = copy.deepcopy(
            dict(state.get("recovered_formal_boundary_evidence") or {})
        )
        self.recovered_stale_page_drafts = self._parse_recovered_stale_page_drafts(
            state.get("recovered_stale_page_drafts")
        )
        self.tail_trim = copy.deepcopy(dict(state.get("tail_trim") or {}))
        self.media_mute = copy.deepcopy(dict(state.get("media_mute") or {}))
        self.media_derivation = copy.deepcopy(
            dict(state.get("media_derivation") or {})
        )
        media_text = str(state.get("source_media_path") or "").strip()
        self.source_media_path = Path(media_text) if media_text else None
        artifact_text = str(state.get("artifact_dir") or "").strip()
        if artifact_text:
            self.artifact_dir = Path(artifact_text)
        self._validate_cues()
        self._validate_english_surface_overrides()
        self._validate_display_page_boundary_overrides()

    def can_redo_for_parent(self, parent_subtitle_id: str) -> bool:
        parent_id = str(parent_subtitle_id or "").strip()
        return bool(
            parent_id
            and self.redo_history
            and parent_id
            in set(self.redo_history[-1].get("affected_parent_ids") or [])
        )

    def redo_for_parent(self, parent_subtitle_id: str) -> bool:
        if not self.can_redo_for_parent(parent_subtitle_id):
            raise ManualFinalSubtitleEditError(
                "当前字幕没有可重做的最新调整；不能跳过其他修改单独重做。"
            )
        return self.redo()

    def redo(self) -> bool:
        if not self.redo_history:
            return False
        redo_entry = self.redo_history.pop()
        history_entry = copy.deepcopy(dict(redo_entry.get("history_entry") or {}))
        parent_scoped_after = redo_entry.get("parent_scoped_after")
        if isinstance(parent_scoped_after, Mapping):
            parent_id = str(parent_scoped_after.get("parent_subtitle_id") or "")
            if not self._history_is_parent_scoped(history_entry, parent_id):
                self.redo_history.append(redo_entry)
                return False
            before = self._capture_parent_runtime_state(parent_id)
            try:
                self._restore_parent_runtime_state(parent_scoped_after)
            except Exception:
                self._restore_parent_runtime_state(before)
                self.redo_history.append(redo_entry)
                raise
            self.history.append(history_entry)
            return True
        after_english_state = redo_entry.get("after_english_state")
        if isinstance(after_english_state, Mapping):
            if (
                not history_entry
                or str(history_entry.get("operation") or "")
                != "edit_english_surface"
            ):
                self.redo_history.append(redo_entry)
                return False
            before_english_state = self._capture_english_history_state(
                history_entry
            )
            try:
                self._restore_english_history_state(after_english_state)
            except Exception:
                self._restore_english_history_state(before_english_state)
                self.redo_history.append(redo_entry)
                raise
            self.history.append(history_entry)
            return True
        after_state = redo_entry.get("after_state") or {}
        if not history_entry or not after_state:
            return False
        before_state = self._capture_runtime_state()
        try:
            self._restore_runtime_state(after_state)
        except Exception:
            self._restore_runtime_state(before_state)
            self.redo_history.append(redo_entry)
            raise
        self.history.append(history_entry)
        return True

    def undo(self) -> bool:
        if not self.history:
            return False
        top_entry = self.history[-1]
        affected = self._history_affected_parent_ids(top_entry)
        if len(affected) == 1:
            parent_id = next(iter(affected))
            if self._history_is_parent_scoped(top_entry, parent_id):
                return self._undo_parent_scoped_history_entry(
                    len(self.history) - 1,
                    parent_id,
                )
        self._remember_known_formal_boundary_evidence()
        compact_english_history = bool(
            str(top_entry.get("operation") or "") == "edit_english_surface"
            and top_entry.get("before_word_ledger_items")
        )
        after_state = (
            self._capture_english_history_state(top_entry)
            if compact_english_history
            else self._capture_runtime_state()
        )
        entry = self.history.pop()
        before = list(entry.get("before_cues") or [])
        if not before:
            self.history.append(entry)
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
        elif entry["operation"] == "edit_english_surface":
            self.cues = before
            before_items = list(entry.get("before_word_ledger_items") or [])
            if before_items:
                for item in before_items:
                    word_id = int(item.get("word_id", -1))
                    word = item.get("word")
                    if not 0 <= word_id < len(self.word_ledger) or not isinstance(
                        word, Mapping
                    ):
                        self.history.append(entry)
                        return False
                    self.word_ledger[word_id] = copy.deepcopy(dict(word))
            else:
                self.word_ledger = copy.deepcopy(
                    list(entry.get("before_word_ledger") or [])
                )
            self.source_word_ledger_hash = str(
                entry.get("before_source_word_ledger_hash") or ""
            )
        elif entry["operation"] == "edit_english_surface_span":
            self.cues = before
        elif entry["operation"] in {
            "set_display_suppressed",
        }:
            self.cues = before
        elif entry["operation"] == "set_hidden_and_media_muted":
            self.cues = before
            self.media_mute = copy.deepcopy(
                dict(entry.get("before_media_mute") or {})
            )
            self.media_derivation = copy.deepcopy(
                dict(entry.get("before_media_derivation") or {})
            )
            previous_media = str(
                entry.get("before_source_media_path") or ""
            ).strip()
            self.source_media_path = Path(previous_media) if previous_media else None
        elif entry["operation"] in {
            "move_display_page_boundary",
            "split_parent_into_display_pages",
            "split_display_page",
            "merge_display_page_with_next",
            "merge_adjacent_display_pages",
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
            self.media_mute = copy.deepcopy(
                dict(entry.get("before_media_mute") or {})
            )
            self.media_derivation = copy.deepcopy(
                dict(entry.get("before_media_derivation") or {})
            )
        else:
            self.history.append(entry)
            return False
        if "before_english_surface_overrides" in entry:
            self.english_surface_overrides = self._parse_english_surface_overrides(
                entry.get("before_english_surface_overrides")
            )
            self._rebind_english_surface_overrides_to_cues()
        self.display_page_edits = list(
            entry.get("before_display_page_edits") or []
        )
        self.display_page_boundary_overrides = (
            self._parse_display_page_boundary_overrides(
                entry.get("before_display_page_boundary_overrides")
            )
        )
        self.tail_trim = dict(entry.get("before_tail_trim") or {})
        self.media_derivation = dict(
            entry.get("before_media_derivation") or {}
        )
        self._validate_cues()
        self._validate_english_surface_overrides()
        self._validate_display_page_boundary_overrides()
        redo_entry = {
            "history_entry": copy.deepcopy(entry),
            "affected_parent_ids": sorted(
                self._history_affected_parent_ids(entry)
            ),
        }
        redo_entry[
            "after_english_state" if compact_english_history else "after_state"
        ] = after_state
        self.redo_history.append(redo_entry)
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
                "display_suppressed": bool(cue.get("display_suppressed")),
                "media_muted": bool(cue.get("media_muted")),
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
            if cue.get("display_suppressed"):
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
                    "display_page_unavailable": False,
                    "parent_cue_index": cue_index,
                    "word_start": int(cue["word_start"]),
                    "word_end": int(cue["word_end"]),
                    "english_font_size": 0,
                    "display_page_review_required": False,
                    "display_page_boundary_classification": "",
                    "display_page_issue_codes": [],
                    "display_page_chinese_stale": False,
                    "display_page_chinese_confirmed": True,
                    "chinese_review_required": False,
                    "display_suppressed": True,
                    "media_muted": bool(cue.get("media_muted")),
                }
                continue
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
                    "display_suppressed": False,
                    "media_muted": False,
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
                has_internal_page_boundary = bool(
                    int(page.get("page_index") or 0) > 1
                )
                boundary_review_required = bool(
                    translation_issue_codes
                    or boundary_classification == "hard"
                    or (
                        has_internal_page_boundary
                        and (
                            boundary_classification == "review"
                            or boundary_issue_codes
                        )
                    )
                    and not boundary_acknowledged
                )
                single_page_parent_identity = bool(
                    len(pages) == 1
                    and int(page.get("word_start", -1))
                    == int(cue.get("word_start", -2))
                    and int(page.get("word_end", -1))
                    == int(cue.get("word_end", -2))
                    and re.sub(r"\s+", "", str(page.get("chinese") or ""))
                    == re.sub(
                        r"\s+", "", str(cue.get("translated_subtitle") or "")
                    )
                )
                chinese_confirmed = bool(
                    str(page.get("chinese") or "").strip()
                    and not translation_issue_codes
                    and not page.get("chinese_stale_draft")
                    and (
                        single_page_parent_identity
                        or not cue.get("chinese_review_required")
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
                    "display_page_chinese_pending": bool(
                        not str(page.get("chinese") or "").strip()
                    ),
                    "chinese_review_required": not chinese_confirmed,
                    "display_suppressed": False,
                    "media_muted": False,
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
        return bool(
            self._visible_display_page_rows(self._display_page_model_data())
        )

    @staticmethod
    def _visible_display_page_rows(
        rows: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return page rows that participate in the visible render model."""
        source = rows.values() if isinstance(rows, Mapping) else rows
        return [
            copy.deepcopy(dict(row))
            for row in source
            if isinstance(row, Mapping) and not row.get("display_suppressed")
        ]

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
        english_plans: List[Dict[str, Any]] = []
        english_parent_ids: set[str] = set()
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
            if source.get("display_suppressed"):
                if (
                    str(row.get("original_subtitle") or "")
                    != str(source.get("original_subtitle") or "")
                    or str(row.get("translated_subtitle") or "").strip()
                    != str(source.get("translated_subtitle") or "").strip()
                ):
                    raise ManualFinalSubtitleEditError(
                        "隐藏字幕请先恢复显示，再修改英文或中文。"
                    )
                continue
            row_english = str(row.get("original_subtitle") or "")
            english_text_changed = bool(
                row_english != str(source.get("original_subtitle") or "")
            )
            parent_id = str(source["manual_cue_id"])
            if english_text_changed:
                plan = self._plan_english_surface_edit(
                    word_start=int(source["word_start"]),
                    word_end=int(source["word_end"]),
                    replacement_text=row_english,
                )
                if plan is not None:
                    english_plans.append(plan)
                    english_parent_ids.add(parent_id)
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
                    "english": row_english,
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
                english_text_changed
                or chinese_text_changed
                or (stale_chinese_draft and stale_chinese_confirmed)
                or stale_chinese_confirmed != source_chinese_confirmed
            )
            changed = changed or row_changed
            if row_changed and parent_id:
                changed_parent_ids.add(parent_id)
        visible_expected = self._visible_display_page_rows(expected)
        complete_page_model = bool(visible_expected) and all(
            bool(item.get("display_page_id")) for item in visible_expected
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

        before = (
            copy.deepcopy(self.cues)
            if english_plans or len(changed_parent_ids) != 1
            else ()
        )
        self._record_history(
            "edit_english_surface" if english_plans else "edit_display_page_chinese",
            before,
            affected_parent_ids=sorted(changed_parent_ids),
            before_word_ledger_items=(
                [
                    {
                        "word_id": word_id,
                        "word": copy.deepcopy(self.word_ledger[word_id]),
                    }
                    for word_id in sorted(
                        {int(plan["word_id"]) for plan in english_plans}
                    )
                ]
                if english_plans
                else []
            ),
            before_source_word_ledger_hash=(
                self.source_word_ledger_hash if english_plans else ""
            ),
            before_formal_word_ledger_hash=(
                self._formal_word_ledger_hash(self.word_ledger)
                if english_plans
                else ""
            ),
        )
        if english_plans:
            self._apply_english_surface_edit_plans(english_plans)
            for edit in edits:
                edit["english"] = self._display_words_text(
                    int(edit["word_start"]),
                    int(edit["word_end"]),
                )
                if str(edit.get("parent_subtitle_id") or "") in english_parent_ids:
                    edit["chinese_review_acknowledged"] = False
            unconfirmed_chinese_parents.update(english_parent_ids)
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
        self._validate_cues()
        return True

    def display_page_review_summary(self) -> Dict[str, Any]:
        """Return actionable manual review counts for the current page identity."""
        rows = self._visible_display_page_rows(self._display_page_model_data())
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
        if (
            str(target.get("display_page_chinese_draft_kind") or "")
            == "parent_chinese_fallback"
        ):
            raise ManualFinalSubtitleEditError(
                "当前显示的是父字幕中文预览，不能直接确认；请按每屏英文填写分页中文。"
            )
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
        self._record_history(
            "confirm_display_page_boundary",
            (),
            display_page_id=str(page_id),
        )
        edits = [
            self._unchanged_display_page_edit_from_model_row(row)
            for row in self._visible_display_page_rows(rows)
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
        visible_rows = self._visible_display_page_rows(rows)
        if not visible_rows or any(
            row.get("display_page_unavailable") for row in visible_rows
        ):
            raise ManualFinalSubtitleEditError(
                "当前实际分页不完整，不能批量确认非阻断提醒。"
            )
        chinese_ids = [
            str(row.get("display_page_id") or "")
            for row in visible_rows
            if row.get("chinese_review_required")
            and str(row.get("translated_subtitle") or "").strip()
            and str(row.get("display_page_chinese_draft_kind") or "")
            != "parent_chinese_fallback"
        ]
        boundary_ids = [
            str(row.get("display_page_id") or "")
            for row in visible_rows
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
                for row in self._visible_display_page_rows(current_rows)
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

    def preview_display_page_boundary_candidates(
        self,
        left_page_id: str,
        *,
        offsets: Sequence[int] = (-2, -1, 1, 2),
        minimum_words: int = 4,
        minimum_duration_ms: int = 900,
    ) -> List[Dict[str, Any]]:
        """Return nearby word-ledger cut suggestions without mutating the session."""
        rows = self._visible_display_page_rows(self._display_page_model_data())
        try:
            left_position = next(
                index
                for index, row in enumerate(rows)
                if str(row.get("display_page_id") or "") == str(left_page_id)
            )
        except StopIteration:
            return []
        if left_position + 1 >= len(rows):
            return []
        left = rows[left_position]
        right = rows[left_position + 1]
        parent_id = str(left.get("manual_cue_id") or "")
        if not parent_id or parent_id != str(right.get("manual_cue_id") or ""):
            return []
        left_start = int(left["word_start"])
        left_end = int(left["word_end"])
        right_start = int(right["word_start"])
        right_end = int(right["word_end"])
        if right_start != left_end + 1:
            return []
        boundary_items = dict(
            self._validated_display_boundary_evidence().get("boundaries") or {}
        )
        from app.core.utils.podcast_learning_video import (
            article_display_boundary_explanation,
        )

        results: List[Dict[str, Any]] = []
        seen_boundaries: set[int] = set()
        for raw_offset in offsets:
            offset = int(raw_offset)
            if not offset:
                continue
            move_to_next = offset < 0
            requested = abs(offset)
            count = self.expanded_manual_boundary_word_count(
                left_word_start=left_start,
                left_word_end=left_end,
                right_word_start=right_start,
                right_word_end=right_end,
                requested_word_count=requested,
                move_to_next=move_to_next,
            )
            boundary = left_end - count + 1 if move_to_next else right_start + count
            if boundary in seen_boundaries or boundary <= left_start or boundary > right_end:
                continue
            seen_boundaries.add(boundary)
            actual_offset = boundary - right_start
            left_count = boundary - left_start
            right_count = right_end - boundary + 1
            left_duration = self._word_end_time(boundary - 1) - self._word_start_time(left_start)
            right_duration = self._word_end_time(right_end) - self._word_start_time(boundary)
            evidence = dict(boundary_items.get(str(boundary)) or {})
            hard = [str(value) for value in evidence.get("hard_issues") or []]
            soft = [str(value) for value in evidence.get("soft_issues") or []]
            classification = "hard" if hard else ("review" if soft else "allow")
            explanation = article_display_boundary_explanation(
                {
                    "classification": classification,
                    "issue_codes": [*hard, *soft],
                    "confidence": "high" if hard else ("medium" if soft else "low"),
                    "pause_ms": evidence.get("pause_ms"),
                },
                left_english=self._display_words_text(left_start, boundary - 1),
                right_english=self._display_words_text(boundary, right_end),
            )
            rejection_reasons = []
            if left_count < minimum_words or right_count < minimum_words:
                rejection_reasons.append("一侧少于 4 个词")
            if left_duration < minimum_duration_ms or right_duration < minimum_duration_ms:
                rejection_reasons.append("一侧显示不足 0.9 秒")
            if hard:
                rejection_reasons.append(explanation["summary_zh"])
            recommendation = (
                "blocked"
                if rejection_reasons
                else ("review" if classification == "review" else "recommended")
            )
            results.append(
                {
                    "left_page_id": str(left_page_id),
                    "parent_subtitle_id": parent_id,
                    "requested_offset": offset,
                    "actual_offset": actual_offset,
                    "move_to_next": move_to_next,
                    "word_count": abs(actual_offset),
                    "right_word_id": boundary,
                    "left_word_count": left_count,
                    "right_word_count": right_count,
                    "left_duration_ms": left_duration,
                    "right_duration_ms": right_duration,
                    "left_english": explanation["left_english"],
                    "right_english": explanation["right_english"],
                    "pause_ms": evidence.get("pause_ms"),
                    "boundary_explanation": explanation,
                    "recommendation": recommendation,
                    "applicable": not rejection_reasons,
                    "rejection_reasons": rejection_reasons,
                }
            )
        return results

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
        model_rows = self._visible_display_page_rows(
            self._display_page_model_data()
        )
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

        self._record_history(
            "move_display_page_boundary",
            (),
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
        model_rows = self._visible_display_page_rows(
            self._display_page_model_data()
        )
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
            (),
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

    def merge_adjacent_display_pages(
        self,
        left_page_id: str,
        right_page_id: str,
    ) -> Dict[str, Any]:
        """Merge two selected visible rows as one atomic page operation."""
        left_id = str(left_page_id or "").strip()
        right_id = str(right_page_id or "").strip()
        model_rows = self._visible_display_page_rows(
            self._display_page_model_data()
        )
        if not left_id or not right_id or not model_rows or any(
            not str(row.get("display_page_id") or "")
            or row.get("display_page_unavailable")
            for row in model_rows
        ):
            raise ManualFinalSubtitleEditError(
                "当前实际分页不完整，不能安全合并相邻页面。"
            )
        positions = {
            str(row.get("display_page_id") or ""): index
            for index, row in enumerate(model_rows)
        }
        if (
            left_id not in positions
            or right_id not in positions
            or positions[right_id] != positions[left_id] + 1
        ):
            raise ManualFinalSubtitleEditError("请选择两条连续相邻的实际分页。")

        left = dict(model_rows[positions[left_id]])
        right = dict(model_rows[positions[right_id]])
        left_parent_id = str(left.get("manual_cue_id") or "")
        right_parent_id = str(right.get("manual_cue_id") or "")
        if not left_parent_id or not right_parent_id:
            raise ManualFinalSubtitleEditError("实际分页缺少稳定父字幕 ID。")
        if left_parent_id == right_parent_id:
            result = self.merge_display_page_with_next(left_id)
            result["parent_merge"] = False
            result["affected_parent_ids"] = [left_parent_id]
            return result

        cue_index_by_id = {
            str(cue.get("cue_id") or ""): index
            for index, cue in enumerate(self.cues)
        }
        left_cue_index = cue_index_by_id.get(left_parent_id, -1)
        right_cue_index = cue_index_by_id.get(right_parent_id, -1)
        if left_cue_index < 0 or right_cue_index != left_cue_index + 1:
            raise ManualFinalSubtitleEditError(
                "所选页面不属于连续相邻的父字幕。"
            )

        before_cues = copy.deepcopy(self.cues)
        before_page_edits = copy.deepcopy(self.display_page_edits)
        before_page_overrides = copy.deepcopy(
            self.display_page_boundary_overrides
        )
        # Existing history entries are immutable; this transaction only appends
        # temporary entries before replacing the list with the original cursor.
        before_history = list(self.history)
        before_tail_trim = copy.deepcopy(self.tail_trim)
        selected_boundary = (
            int(left["word_end"]),
            int(right["word_start"]),
        )
        try:
            self.merge_adjacent(left_cue_index, right_cue_index)
            merged_rows = self._visible_display_page_rows(
                self._display_page_model_data()
            )
            boundary_position = next(
                (
                    index
                    for index in range(len(merged_rows) - 1)
                    if str(merged_rows[index].get("manual_cue_id") or "")
                    == left_parent_id
                    and str(merged_rows[index + 1].get("manual_cue_id") or "")
                    == left_parent_id
                    and int(merged_rows[index].get("word_end", -1))
                    == selected_boundary[0]
                    and int(merged_rows[index + 1].get("word_start", -1))
                    == selected_boundary[1]
                ),
                -1,
            )
            if boundary_position >= 0:
                page_result = self.merge_display_page_with_next(
                    str(merged_rows[boundary_position]["display_page_id"])
                )
            else:
                already_merged = next(
                    (
                        row
                        for row in merged_rows
                        if str(row.get("manual_cue_id") or "") == left_parent_id
                        and int(row.get("word_start", -1))
                        == int(left["word_start"])
                        and int(row.get("word_end", -1))
                        == int(right["word_end"])
                    ),
                    None,
                )
                if already_merged is None:
                    raise ManualFinalSubtitleEditError(
                        "父字幕合并后没有保留所选页面边界，无法确认合并结果。"
                    )
                page_result = {
                    "parent_subtitle_id": left_parent_id,
                    "merged_page_id": str(
                        already_merged.get("display_page_id") or ""
                    ),
                    "page_count": sum(
                        str(row.get("manual_cue_id") or "") == left_parent_id
                        for row in merged_rows
                    ),
                }

            merged_page_id = str(page_result.get("merged_page_id") or "")
            merged_chinese = "".join(
                str(row.get("translated_subtitle") or "").strip()
                for row in (left, right)
            )
            stale_unconfirmed = any(
                row.get("display_page_chinese_stale")
                and not row.get("display_page_chinese_confirmed")
                for row in (left, right)
            )
            chinese_confirmed = bool(
                merged_chinese
                and not stale_unconfirmed
                and all(
                    row.get("display_page_chinese_confirmed")
                    for row in (left, right)
                )
            )
            merged_edit = next(
                (
                    edit
                    for edit in self.display_page_edits
                    if str(edit.get("display_page_id") or "") == merged_page_id
                ),
                None,
            )
            if merged_edit is None:
                raise ManualFinalSubtitleEditError(
                    "合并后的页面没有可持久化编辑记录。"
                )
            merged_edit.update(
                {
                    "chinese": "" if stale_unconfirmed else merged_chinese,
                    "chinese_review_acknowledged": chinese_confirmed,
                }
            )
            if stale_unconfirmed:
                merged_edit.update(
                    {
                        "stale_chinese_draft": merged_chinese,
                        "chinese_stale_unconfirmed": True,
                        "chinese_draft_kind": "merged_page_draft",
                    }
                )
            else:
                for key in (
                    "stale_chinese_draft",
                    "chinese_stale_unconfirmed",
                    "chinese_draft_kind",
                ):
                    merged_edit.pop(key, None)

            self.history = before_history
            self._record_history(
                "merge_adjacent_display_pages",
                before_cues,
                affected_parent_ids=[left_parent_id, right_parent_id],
                parent_subtitle_id=left_parent_id,
                first_index=left_cue_index,
                last_index=right_cue_index,
                left_page_id=left_id,
                right_page_id=right_id,
                before_display_page_edits=before_page_edits,
                before_display_page_boundary_overrides=before_page_overrides,
                before_tail_trim=before_tail_trim,
            )
            page_result.update(
                {
                    "parent_merge": True,
                    "affected_parent_ids": [left_parent_id, right_parent_id],
                }
            )
            return page_result
        except Exception:
            self.cues = before_cues
            self.display_page_edits = before_page_edits
            self.display_page_boundary_overrides = before_page_overrides
            self.history = before_history
            self.tail_trim = before_tail_trim
            self._validate_cues()
            self._validate_display_page_boundary_overrides()
            raise

    def split_display_page(
        self,
        display_page_id_value: str,
        *,
        allow_high_risk: bool = False,
    ) -> Dict[str, Any]:
        """Split only one selected page while freezing every other page."""
        selected_page_id = str(display_page_id_value or "").strip()
        current_rows = self._visible_display_page_rows(
            self._display_page_model_data()
        )
        if not selected_page_id or not current_rows or any(
            not str(row.get("display_page_id") or "")
            or row.get("display_page_unavailable")
            for row in current_rows
        ):
            raise ManualFinalSubtitleEditError(
                "当前实际分页不完整，不能只拆当前屏。"
            )
        selected = next(
            (
                dict(row)
                for row in current_rows
                if str(row.get("display_page_id") or "") == selected_page_id
            ),
            None,
        )
        if selected is None:
            raise ManualFinalSubtitleEditError("找不到要拆分的实际分页。")
        parent_id = str(selected.get("manual_cue_id") or "")
        parent_rows = [
            dict(row)
            for row in current_rows
            if str(row.get("manual_cue_id") or "") == parent_id
        ]
        from app.core.utils.podcast_learning_video import (
            ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES,
        )

        if len(parent_rows) >= ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES:
            raise ManualFinalSubtitleEditError(
                "该父字幕已经达到人工分页上限，不能继续增加页面。"
            )
        try:
            selected_index = next(
                index
                for index, row in enumerate(parent_rows)
                if str(row.get("display_page_id") or "") == selected_page_id
            )
        except StopIteration as exc:
            raise ManualFinalSubtitleEditError("实际分页顺序已变化。") from exc

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
            propose_article_manual_page_word_ranges,
            rebuild_article_frozen_page_plan_from_word_ranges,
        )

        boundary_payload = self._validated_display_boundary_evidence()
        boundary_items = dict(boundary_payload.get("boundaries") or {})
        render_cue = self._article_render_cue(cue_index, boundary_items)
        parent_word_start = int(cue["word_start"])
        page_word_start = int(selected["word_start"])
        page_word_end = int(selected["word_end"])
        local_start = page_word_start - parent_word_start
        local_end = page_word_end - parent_word_start
        local_timing = tuple(render_cue.word_timing[local_start : local_end + 1])
        local_cue = Cue(
            index=render_cue.index,
            start=float(local_timing[0]["start"]),
            end=float(local_timing[-1]["end"]),
            en=self._display_words_text(page_word_start, page_word_end),
            zh=str(selected.get("translated_subtitle") or ""),
            speaker=render_cue.speaker,
            subtitle_id=parent_id,
            word_timing=local_timing,
            display_boundary_evidence={
                str(right_word): dict(boundary_items[str(right_word)])
                for right_word in range(page_word_start + 1, page_word_end + 1)
            },
        )
        try:
            selected_ranges = propose_article_manual_page_word_ranges(
                local_cue,
                2,
                allow_review_boundary=True,
                allow_hard_boundary=allow_high_risk,
            )
            ranges = [
                (int(row["word_start"]), int(row["word_end"]))
                for row in parent_rows
            ]
            ranges[selected_index : selected_index + 1] = selected_ranges
            new_page_ids = [
                display_page_id(parent_id, index + 1)
                for index in range(len(ranges))
            ]
            preserved_by_range = {
                (int(row["word_start"]), int(row["word_end"])): row
                for row in parent_rows
                if str(row.get("display_page_id") or "") != selected_page_id
            }
            page_translations = {
                page_id: str(
                    preserved_by_range.get(word_range, {}).get(
                        "translated_subtitle"
                    )
                    or ""
                ).strip()
                for page_id, word_range in zip(new_page_ids, ranges)
            }
            rebuilt_plan = rebuild_article_frozen_page_plan_from_word_ranges(
                render_cue,
                source_plan,
                ranges,
                page_translations,
                allow_page_count_change=True,
                allow_incomplete_page_translations=True,
                allow_manual_review=True,
            )
        except RenderStructuralOverflowError as exc:
            reason_codes = {
                str(item.get("reason") or "")
                for item in getattr(exc, "errors", [])
                if isinstance(item, Mapping)
            }
            reasons = ", ".join(
                sorted(reason for reason in reason_codes if reason)
            )
            raise ManualFinalSubtitleEditError(
                "当前屏内部找不到满足固定字号和时间轴的可用切点。"
                + (f"（{reasons}）" if reasons else ""),
                code=(
                    "manual_high_risk_page_split_confirmation_required"
                    if (
                        not allow_high_risk
                        and "manual_page_count_has_no_safe_partition"
                        in reason_codes
                    )
                    else ""
                ),
            ) from exc

        rebuilt_pages = [
            dict(page)
            for page in rebuilt_plan.get("pages") or []
            if isinstance(page, Mapping)
        ]
        if len(rebuilt_pages) != len(parent_rows) + 1:
            raise ManualFinalSubtitleEditError("当前屏拆分后的页面数量不一致。")

        replacement_edits: List[Dict[str, Any]] = []
        for page in rebuilt_pages:
            word_range = (int(page["word_start"]), int(page["word_end"]))
            source_row = preserved_by_range.get(word_range)
            if source_row is None:
                edit = {
                    "display_page_id": str(page["display_page_id"]),
                    "parent_subtitle_id": parent_id,
                    "word_start": word_range[0],
                    "word_end": word_range[1],
                    "english": str(page.get("english") or ""),
                    "chinese": "",
                    "chinese_review_acknowledged": False,
                    "boundary_review_acknowledged": False,
                }
            else:
                edit = self._unchanged_display_page_edit_from_model_row(source_row)
                edit.update(
                    {
                        "display_page_id": str(page["display_page_id"]),
                        "parent_subtitle_id": parent_id,
                        "word_start": word_range[0],
                        "word_end": word_range[1],
                        "english": str(page.get("english") or ""),
                    }
                )
            replacement_edits.append(edit)

        new_edits: List[Dict[str, Any]] = []
        inserted_parent = False
        for row in current_rows:
            if str(row.get("manual_cue_id") or "") == parent_id:
                if not inserted_parent:
                    new_edits.extend(replacement_edits)
                    inserted_parent = True
                continue
            new_edits.append(self._unchanged_display_page_edit_from_model_row(row))
        if not inserted_parent:
            raise ManualFinalSubtitleEditError(
                "当前实际分页没有覆盖所选父字幕。"
            )

        self._record_history(
            "split_display_page",
            (),
            parent_subtitle_id=parent_id,
            display_page_id=selected_page_id,
            page_count=len(rebuilt_pages),
        )
        self.display_page_boundary_overrides[parent_id] = [
            int(page["word_start"]) for page in rebuilt_pages[1:]
        ]
        self.display_page_edits = new_edits
        cue["chinese_review_required"] = True
        split_pages = rebuilt_pages[selected_index : selected_index + 2]
        high_risk_override = any(
            str(
                page.get("boundary_before", {}).get(
                    "manual_original_classification"
                )
                or ""
            )
            == "hard"
            or "manual_short_page_review"
            in set(page.get("boundary_before", {}).get("issue_codes") or [])
            for page in split_pages[1:]
        )
        return {
            "changed": True,
            "parent_subtitle_id": parent_id,
            "source_page_id": selected_page_id,
            "split_page_ids": [
                str(page["display_page_id"]) for page in split_pages
            ],
            "page_count": len(rebuilt_pages),
            "word_ranges": [
                [int(page["word_start"]), int(page["word_end"])]
                for page in split_pages
            ],
            "high_risk_override": high_risk_override,
        }

    def split_parent_into_display_pages(
        self,
        parent_subtitle_id: str,
        page_count: int,
        *,
        word_ranges: Sequence[Sequence[int]] | None = None,
        preserve_matching_page_chinese: bool = False,
        allow_high_risk: bool = False,
    ) -> Dict[str, Any]:
        """Replace one parent's display-page count without changing the parent cue."""
        parent_id = str(parent_subtitle_id or "").strip()
        requested = int(page_count)
        from app.core.utils.podcast_learning_video import (
            ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES,
        )

        if requested not in range(2, ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES + 1):
            raise ManualFinalSubtitleEditError("人工分页只支持拆成 2 至 6 屏。")
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
            if word_ranges is None:
                ranges = propose_article_manual_page_word_ranges(
                    render_cue,
                    requested,
                    allow_review_boundary=True,
                    allow_hard_boundary=allow_high_risk,
                )
            else:
                ranges = [
                    (int(raw[0]), int(raw[1]))
                    for raw in word_ranges
                    if len(raw) >= 2
                ]
                if len(ranges) != requested:
                    raise RenderStructuralOverflowError(
                        [{"reason": "manual_page_candidate_cardinality_invalid"}]
                    )
                expected_start = int(cue["word_start"])
                expected_end = int(cue["word_end"])
                if (
                    not ranges
                    or ranges[0][0] != expected_start
                    or ranges[-1][1] != expected_end
                    or any(
                        start > end
                        or (index and start != ranges[index - 1][1] + 1)
                        for index, (start, end) in enumerate(ranges)
                    )
                ):
                    raise RenderStructuralOverflowError(
                        [{"reason": "manual_page_candidate_word_coverage_invalid"}]
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
            reason_codes = {
                str(item.get("reason") or "")
                for item in getattr(exc, "errors", [])
                if isinstance(item, Mapping)
            }
            reasons = ", ".join(
                sorted(reason for reason in reason_codes if reason)
            )
            raise ManualFinalSubtitleEditError(
                "这条字幕找不到满足语法、停顿、900ms 和固定字号的安全分页。"
                + (f"（{reasons}）" if reasons else ""),
                code=(
                    "manual_high_risk_page_split_confirmation_required"
                    if (
                        not allow_high_risk
                        and "manual_page_count_has_no_safe_partition"
                        in reason_codes
                    )
                    else ""
                ),
            ) from exc

        current_rows = self._visible_display_page_rows(
            self._display_page_model_data()
        )
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
                "high_risk_override": False,
                "changed": False,
            }

        existing_by_range = {
            (
                int(row.get("word_start", -1)),
                int(row.get("word_end", -1)),
            ): row
            for row in current_parent_rows
            if preserve_matching_page_chinese
        }
        new_edits: List[Dict[str, Any]] = []
        inserted_parent = False
        for row in current_rows:
            row_parent_id = str(row.get("manual_cue_id") or "")
            if row_parent_id == parent_id:
                if inserted_parent:
                    continue
                for page in rebuilt_pages:
                    word_range = (
                        int(page["word_start"]),
                        int(page["word_end"]),
                    )
                    previous = existing_by_range.get(word_range)
                    edit = {
                            "display_page_id": str(page["display_page_id"]),
                            "parent_subtitle_id": parent_id,
                            "word_start": word_range[0],
                            "word_end": word_range[1],
                            "english": str(page.get("english") or ""),
                            "chinese": (
                                str(previous.get("translated_subtitle") or "").strip()
                                if previous is not None
                                else ""
                            ),
                            "chinese_review_required": previous is None,
                        }
                    if previous is not None:
                        edit["chinese_review_acknowledged"] = bool(
                            previous.get("display_page_chinese_confirmed")
                        )
                    new_edits.append(edit)
                inserted_parent = True
                continue
            new_edits.append(self._unchanged_display_page_edit_from_model_row(row))
        if not inserted_parent:
            raise ManualFinalSubtitleEditError("当前实际分页没有覆盖所选父字幕。")

        self._record_history(
            "split_parent_into_display_pages",
            (),
            parent_subtitle_id=parent_id,
            page_count=requested,
        )
        self.display_page_boundary_overrides[parent_id] = [
            int(page["word_start"]) for page in rebuilt_pages[1:]
        ]
        self.display_page_edits = new_edits
        cue["chinese_review_required"] = True
        high_risk_override = any(
            str(
                page.get("boundary_before", {}).get(
                    "manual_original_classification"
                )
                or ""
            )
            == "hard"
            or "manual_short_page_review"
            in set(page.get("boundary_before", {}).get("issue_codes") or [])
            for page in rebuilt_pages[1:]
        )
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
            "high_risk_override": high_risk_override,
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
        self._assert_boundary_outside_english_surface_overrides(boundary)
        partial_parent_trim = bool(decision.get("partial_parent_trim"))
        previous_page_rows = self._visible_display_page_rows(
            self._display_page_model_data()
        )
        before_cues = copy.deepcopy(self.cues)
        before_word_ledger = copy.deepcopy(self.word_ledger)
        before_hash = self.source_word_ledger_hash
        before_surface_overrides = copy.deepcopy(self.english_surface_overrides)
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
            before_media_mute=copy.deepcopy(self.media_mute),
            before_media_derivation=copy.deepcopy(self.media_derivation),
            before_english_surface_overrides=before_surface_overrides,
        )

        if partial_parent_trim:
            retained = self.cues[index]
            retained_id = str(retained.get("cue_id") or "")
            retained["word_end"] = boundary - 1
            retained["end_time"] = self._word_end_time(boundary - 1)
            retained["original_subtitle"] = self._display_words_text(
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
        self.english_surface_overrides = [
            item
            for item in self.english_surface_overrides
            if int(item["word_end"]) < boundary
        ]
        self.word_ledger = self.word_ledger[: boundary]
        self.source_word_ledger_hash = self._semantic_word_ledger_hash(
            self.word_ledger
        )
        self._rebind_english_surface_overrides_to_cues()
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
        self.media_derivation = {}
        self._validate_cues()
        self._validate_display_page_boundary_overrides()
        return copy.deepcopy(decision)

    def _tail_trim_source_media_path(self) -> Path | None:
        original = str(self.media_derivation.get("source_media_path") or "").strip()
        expected_hash = str(
            self.media_derivation.get("source_media_sha256") or ""
        ).strip()
        if original:
            candidate = Path(original)
            if candidate.is_file() and (
                not expected_hash or file_sha256(candidate) == expected_hash
            ):
                return candidate.resolve()
        original = str(self.tail_trim.get("source_media_path") or "").strip()
        if original:
            candidate = Path(original)
            if candidate.is_file():
                return candidate
        if self.media_mute:
            original = str(
                self.media_mute.get("source_media_path") or ""
            ).strip()
            expected_hash = str(
                self.media_mute.get("source_media_sha256") or ""
            ).strip()
            if original:
                candidate = Path(original)
                if candidate.is_file() and (
                    not expected_hash or file_sha256(candidate) == expected_hash
                ):
                    return candidate.resolve()
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

    def _media_mute_source_media_path(self) -> Path | None:
        original = str(self.media_derivation.get("source_media_path") or "").strip()
        expected_hash = str(
            self.media_derivation.get("source_media_sha256") or ""
        ).strip()
        if original:
            candidate = Path(original)
            if candidate.is_file() and (
                not expected_hash or file_sha256(candidate) == expected_hash
            ):
                return candidate.resolve()
        original = str(self.media_mute.get("source_media_path") or "").strip()
        expected_hash = str(
            self.media_mute.get("source_media_sha256") or ""
        ).strip()
        if original:
            candidate = Path(original)
            if candidate.is_file() and (
                not expected_hash or file_sha256(candidate) == expected_hash
            ):
                return candidate.resolve()
        if self.source_media_path is not None and self.source_media_path.is_file():
            derived_hash = str(
                self.media_mute.get("derived_media_sha256") or ""
            ).strip()
            actual_hash = file_sha256(self.source_media_path)
            if not derived_hash or actual_hash != derived_hash:
                if not expected_hash or actual_hash == expected_hash:
                    return self.source_media_path.resolve()
        for anchor in (
            self.loaded_subtitle_path,
            self.subtitle_path,
            self.manifest_path,
        ):
            inferred = self._source_media_from_result_directory(Path(anchor))
            if inferred is not None and (
                not expected_hash or file_sha256(inferred) == expected_hash
            ):
                return inferred.resolve()
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
                and not cue.get("display_suppressed")
            }
            if set(edits_by_parent) != cue_ids:
                return {}

            boundary_payload = self._validated_display_boundary_evidence()
            boundary_items = dict(boundary_payload.get("boundaries") or {})
            render_plans: List[Dict[str, Any]] = []
            parents: List[Dict[str, Any]] = []
            for cue_index, cue in enumerate(self.cues):
                if cue.get("display_suppressed"):
                    continue
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
                    expected_english = self._display_words_text(
                        word_start, word_end
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
        if str(artifact.get("status") or "") != "PASS" and self.display_page_edits:
            recovered_artifact = (
                self._recover_display_page_artifact_from_complete_edits()
            )
            if recovered_artifact:
                return recovered_artifact
        if str(artifact.get("status") or "") != "PASS":
            source_artifact = artifact
            try:
                draft_path = resolve_manifest_owned_path(
                    self.manifest_path,
                    manifest,
                    str(manifest.get("manual_draft_page_plan_path") or ""),
                    str(manifest.get("manual_draft_page_plan_sha256") or ""),
                )
                if (
                    draft_path is None
                    or not self._same_path(draft_path.parent, self.artifact_dir)
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

    def display_page_plan_needs_refresh(self) -> bool:
        """Return whether a legacy page artifact must be rebuilt after code changes."""
        if self.display_page_edits or self.display_page_boundary_overrides:
            # Existing manual page ranges are user-owned and must be checked
            # by the normal strict save path before any automatic refresh.
            return False
        try:
            from app.core.subtitle_processor.stable_display_page_contract import (
                DISPLAY_PAGE_PLANNER_VERSION,
            )

            artifact = self._effective_display_page_artifact()
        except (ManualFinalSubtitleEditError, OSError):
            return False
        return bool(
            artifact
            and str(artifact.get("planner_version") or "")
            and str(artifact.get("planner_version") or "")
            != DISPLAY_PAGE_PLANNER_VERSION
        )

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
        source_parent_chinese_by_parent: Dict[str, str] = {}
        for parent in artifact.get("parents") or []:
            if not isinstance(parent, Mapping):
                continue
            parent_id = str(parent.get("parent_subtitle_id") or "")
            aggregate_chinese = str(parent.get("aggregate_chinese") or "")
            if parent_id and aggregate_chinese:
                translated_parent_chinese[parent_id] = aggregate_chinese
            source_parent_chinese = str(parent.get("source_parent_chinese") or "")
            if parent_id and source_parent_chinese:
                source_parent_chinese_by_parent[parent_id] = source_parent_chinese
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
            plan: Mapping[str, Any] = copy.deepcopy(dict(source_plan))
            subtitle_id = parent_id
            cue = cue_by_id.get(subtitle_id)
            override_starts = self.display_page_boundary_overrides.get(parent_id)
            if cue is None:
                self._display_page_preview_cache.pop(parent_id, None)
                continue
            if cue.get("display_suppressed"):
                self._display_page_preview_cache.pop(parent_id, None)
                continue
            # A failed display-page blueprint still owns the frozen parent
            # English/Chinese mapping.  Keep its one-page editable seed in
            # the editor instead of converting it into an "unavailable"
            # parent row.  The page is deliberately marked as an unconfirmed
            # display-only draft below; it is never accepted by the formal
            # page contract or synthesis gate.
            plan["english"] = self._display_words_text(
                int(cue["word_start"]),
                int(cue["word_end"]),
            )
            for page in plan.get("pages") or []:
                if not isinstance(page, dict):
                    continue
                try:
                    page["english"] = self._display_words_text(
                        int(page["word_start"]),
                        int(page["word_end"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            parent_page_prefix = f"{parent_id}.P"
            parent_fallback_chinese = str(
                source_plan.get("parent_chinese_fallback")
                or source_plan.get("chinese")
                or cue.get("translated_subtitle")
                or ""
            ).strip()
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
                    "source_parent_chinese": source_parent_chinese_by_parent.get(
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
                if not source_pages or not 0 <= len(override_starts) <= 5:
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
            source_parent_chinese = source_parent_chinese_by_parent.get(
                subtitle_id,
                "",
            )
            if source_parent_chinese:
                # New page artifacts bind their projection to the parent
                # translation that produced it. Page-local Chinese may be
                # re-ordered for visual reading and must not be compared
                # directly with the parent text.
                planned_chinese = re.sub(r"\s+", "", source_parent_chinese)
            else:
                # Legacy artifacts have no source-parent binding. Preserve
                # the old reconstruction check for backward compatibility.
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
            for raw_page_index, raw_page in enumerate(raw_pages):
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
                if (
                    not chinese
                    and allow_incomplete_page_chinese
                    and parent_fallback_chinese
                    and raw_page_index == 0
                    and (
                        len(raw_pages) > 1
                        or (
                            source_plan.get("editable_seed")
                            and not source_plan.get("renderable", True)
                        )
                    )
                ):
                    # Show the complete parent translation once as a reference.
                    # Repeating it on every failed page looks like valid
                    # page-local Chinese and makes the review state misleading.
                    chinese = parent_fallback_chinese
                    chinese_stale_draft = True
                    chinese_draft_kind = "parent_chinese_fallback"
                if len(raw_pages) == 1:
                    if not chinese:
                        chinese = str(cue.get("translated_subtitle") or "")
                    if (
                        chinese
                        and not chinese_stale_draft
                        and edited
                        and edited.get("chinese_stale_unconfirmed")
                        and str(edited.get("chinese_draft_kind") or "")
                        == "formal_boundary_reflow_draft"
                    ):
                        chinese_stale_draft = True
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
            parent_translation_is_current = bool(
                source_parent_chinese
                and re.sub(r"\s+", "", source_parent_chinese) == current_chinese
            )
            if pages and (
                manual_page_override
                or allow_incomplete_page_chinese
                or any(page["chinese_stale_draft"] for page in pages)
                or parent_translation_is_current
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
        final_cue_timeline = self._rebuild_authoritative_cue_timeline()
        # Loading an older manual package may retain its legacy semantic hash.
        # Every newly published generation upgrades to the canonical contract.
        self.source_word_ledger_hash = self._semantic_word_ledger_hash(
            self.word_ledger
        )
        report(5, "正在核对冻结字幕和词时间账本")
        source_dir = self.subtitle_path.parent
        muted_intervals = self._media_mute_intervals()
        cut_ms = int(self.tail_trim["cut_ms"]) if self.tail_trim else None
        self._validate_ordered_mute_intervals(muted_intervals, cut_ms=cut_ms)
        media_candidate = source_media_path or self.source_media_path
        media_path = Path(media_candidate).resolve() if media_candidate else None
        if media_path is not None and not media_path.is_file():
            media_path = None
        user_media_path = None
        if self.tail_trim or self.media_derivation:
            user_media_path = self._tail_trim_source_media_path()
        elif muted_intervals or self.media_mute:
            user_media_path = self._media_mute_source_media_path()
            if user_media_path is None and self.media_mute:
                raise ManualFinalSubtitleEditError(
                    "静音终稿缺少原始音频，不能安全保存或恢复声音。"
                )
        if user_media_path is None or not user_media_path.is_file():
            user_media_path = media_path
        if user_media_path is not None:
            media_path = user_media_path.resolve()
        result_dir = media_result_dir(user_media_path) if user_media_path else None
        preferred_package_dir = (
            media_result_manual_package_dir(user_media_path)
            if result_dir is not None
            else source_dir / MEDIA_RESULT_MANUAL_PACKAGE_DIR
        )
        current_manifest = self._read_json(self.manifest_path)
        current_override = current_manifest.get("manual_final_override") or {}
        reusing_owned_package = bool(
            int(current_override.get("schema_version") or 0) >= 2
            and self.manifest_path.name == "stable-final-manifest.json"
            and (
                self._same_path(self.manifest_path.parent, preferred_package_dir)
                or self.manifest_path.parent.name.endswith("人工终稿字幕包")
            )
        )
        package_dir = (
            self.manifest_path.parent
            if reusing_owned_package
            else preferred_package_dir
        )
        package_dir.mkdir(parents=True, exist_ok=True)
        generation_id = (
            datetime.now().strftime("%Y%m%dT%H%M%S%f")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        generation_relative_dir = Path("generations") / generation_id
        generation_dir = package_dir / generation_relative_dir
        generation_dir.mkdir(parents=True, exist_ok=False)
        published_tail_trim: Dict[str, Any] = {}
        published_media_mute: Dict[str, Any] = {}
        published_media_derivation: Dict[str, Any] = {}
        if cut_ms is not None or muted_intervals:
            derivation_source = self._tail_trim_source_media_path()
            if derivation_source is None:
                derivation_source = self._media_mute_source_media_path() or media_path
            if derivation_source is None or not derivation_source.is_file():
                raise ManualFinalSubtitleEditError(
                    "媒体派生缺少原始音频，无法保存终稿包。"
                )
            source_hash = file_sha256(derivation_source)
            if self.tail_trim and str(
                self.tail_trim.get("source_media_sha256") or ""
            ) not in ("", source_hash):
                raise ManualFinalSubtitleEditError("原始音频已变化，尾部裁剪决定已失效。")
            decision_payload = self._media_derivation_decision_payload(
                source_hash,
                cut_ms=cut_ms,
                mute_intervals=muted_intervals,
            )
            decision_hash = stable_payload_hash(decision_payload)
            derivation_audio_path = generation_dir / f"{derivation_source.stem}-人工终稿派生.m4a"
            derivation_record_path = generation_dir / "media-derivation.json"
            previous_derivation = self.media_derivation or (
                (current_manifest.get("manual_final_override") or {}).get(
                    "media_derivation"
                )
                or current_manifest.get("media_derivation")
                or {}
            )
            previous_audio = resolve_manifest_owned_path(
                self.manifest_path,
                current_manifest,
                str(previous_derivation.get("derived_media_path") or ""),
                str(previous_derivation.get("derived_media_sha256") or ""),
            )
            reuse_derivation = False
            if previous_audio is not None:
                try:
                    reuse_derivation = bool(
                        str(previous_derivation.get("decision_hash") or "")
                        == decision_hash
                        and str(previous_derivation.get("derived_media_sha256") or "")
                        == file_sha256(previous_audio)
                    )
                except OSError:
                    reuse_derivation = False
            if reuse_derivation:
                shutil.copyfile(previous_audio, derivation_audio_path)
            elif cut_ms is not None and not muted_intervals:
                report(10, "正在生成非破坏式尾部裁剪音频")
                _materialize_tail_trim_audio(
                    derivation_source, derivation_audio_path, cut_ms
                )
            elif muted_intervals and cut_ms is None:
                report(10, "正在生成不改变时长的字幕区间静音音频")
                _materialize_media_mute_audio(
                    derivation_source, derivation_audio_path, muted_intervals
                )
            else:
                report(10, "正在生成组合裁剪和静音音频")
                _materialize_media_derivation_audio(
                    derivation_source,
                    derivation_audio_path,
                    cut_ms=cut_ms,
                    mute_intervals=muted_intervals,
                )
            published_media_derivation = {
                **decision_payload,
                "source_media_path": str(derivation_source.resolve()),
                "decision_hash": decision_hash,
                "derived_media_path": str(derivation_audio_path.resolve()),
                "derived_media_sha256": file_sha256(derivation_audio_path),
            }
            write_json_artifact(derivation_record_path, published_media_derivation)
            media_path = derivation_audio_path.resolve()
        srt_path = generation_dir / "人工终稿字幕.srt"
        display_page_srt_path = generation_dir / "人工终稿分页双语字幕.srt"
        display_page_map_path = generation_dir / "人工终稿分页映射.json"
        edit_path = generation_dir / "人工终稿字幕-edits.json"
        artifact_dir = generation_dir / "人工终稿字幕-artifacts"
        report(
            18,
            (
                "正在复用冻结分页，仅重建人工调整项"
                if self.display_page_edits
                else "正在复用冻结分页；边界变化时才重新规划全片"
            ),
        )
        render_contract = self._write_manual_render_contract(
            artifact_dir,
            final_cue_timeline=final_cue_timeline,
        )
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
            "schema_version": 5,
            "word_ledger_hash_version": WORD_LEDGER_HASH_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_subtitle": str(self.subtitle_path),
            "source_artifact_dir": str(self.artifact_dir),
            "source_word_ledger_hash": self.source_word_ledger_hash,
            "parent_chinese_authority_hash": render_contract[
                "parent_chinese_authority_hash"
            ],
            "word_ledger": self.word_ledger,
            "english_surface_overrides": self.english_surface_overrides,
            "cues": self.cues,
            "history": self.history,
            "redo_history": self.redo_history,
            "display_page_edits": self.display_page_edits,
            "display_page_boundary_overrides": self.display_page_boundary_overrides,
            "recovered_stale_page_drafts": self.recovered_stale_page_drafts,
            "tail_trim": published_tail_trim,
            "media_mute": published_media_mute,
            "media_derivation": published_media_derivation,
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

        package_root = package_dir.resolve()

        def owned_relative(path: str | Path) -> str:
            text = str(path or "").strip()
            if not text:
                return ""
            try:
                resolved = Path(text).resolve()
                resolved.relative_to(package_root)
                return str(resolved)
            except (OSError, ValueError) as exc:
                raise ManualFinalSubtitleEditError(
                    "人工终稿 generation 引用了包目录以外的制品。"
                ) from exc

        manifest_media_path = str(
            published_media_derivation.get("derived_media_path")
            or (str(media_path) if media_path else "")
        )
        manual_override = {
            "schema_version": 5,
            "subtitle_path": owned_relative(srt_path),
            "subtitle_sha256": file_sha256(srt_path),
            "edit_artifact_path": owned_relative(edit_path),
            "edit_artifact_sha256": edit_artifact_sha256,
            "artifact_dir": owned_relative(artifact_dir),
            "final_cue_timeline_path": owned_relative(final_timeline_path),
            "final_cue_timeline_sha256": file_sha256(final_timeline_path),
            "word_ledger_path": owned_relative(word_ledger_path),
            "word_ledger_sha256": file_sha256(word_ledger_path),
            "parent_chinese_authority_path": owned_relative(
                render_contract["parent_chinese_authority_path"]
            ),
            "parent_chinese_authority_sha256": render_contract[
                "parent_chinese_authority_sha256"
            ],
            "parent_chinese_authority_hash": render_contract[
                "parent_chinese_authority_hash"
            ],
            "display_page_translation_path": owned_relative(
                artifact_dir / "display-page-translations.json"
            ),
            "display_boundary_evidence_path": owned_relative(
                artifact_dir / "display-boundary-evidence.json"
            ),
            "display_page_srt_path": owned_relative(exported_page_paths["srt"]),
            "display_page_srt_sha256": (
                file_sha256(Path(exported_page_paths["srt"]))
                if exported_page_paths["srt"]
                else ""
            ),
            "display_page_map_path": owned_relative(exported_page_paths["map"]),
            "display_page_map_sha256": (
                file_sha256(Path(exported_page_paths["map"]))
                if exported_page_paths["map"]
                else ""
            ),
            "manual_draft_page_plan_path": owned_relative(
                render_contract["manual_draft_page_plan_path"]
            ),
            "manual_draft_page_plan_sha256": render_contract[
                "manual_draft_page_plan_sha256"
            ],
            "render_blocked": bool(render_contract["render_blocked"]),
            "render_block_reason": render_contract["render_block_reason"],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "source_word_ledger_hash": self.source_word_ledger_hash,
            "word_ledger_hash_version": WORD_LEDGER_HASH_VERSION,
            "manual_cue_count": len(self.cues),
            "visible_manual_cue_count": sum(
                not bool(cue.get("display_suppressed")) for cue in self.cues
            ),
            "suppressed_subtitle_ids": [
                str(cue.get("cue_id") or "")
                for cue in self.cues
                if cue.get("display_suppressed")
            ],
            "muted_subtitle_ids": [
                str(cue.get("cue_id") or "")
                for cue in self.cues
                if cue.get("media_muted")
            ],
            "source_media_path": manifest_media_path,
            "tail_trim": published_tail_trim,
            "media_mute": published_media_mute,
            "media_derivation": published_media_derivation,
            "chinese_review_required_count": sum(
                bool(cue.get("chinese_review_required")) for cue in self.cues
            ),
            "display_page_review_summary": review_summary,
        }
        manual_manifest = {
            "schema_version": 5,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "stable_run_id": (
                "manual-"
                + stable_payload_hash(
                    {
                        "cues": self.cues,
                        "media_derivation_decision_hash": (
                            published_media_derivation.get("decision_hash", "")
                        ),
                    }
                )[:16]
            ),
            # This manifest owns the files in the manual package, so its run
            # directory must match the package containing the published SRT.
            "package_generation": {
                "schema_version": 1,
                "id": generation_id,
                "relative_dir": str(generation_relative_dir),
            },
            "stable_run_dir": str(generation_dir.resolve()),
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
                "original_top_srt": owned_relative(srt_path),
                **(
                    {
                        "display_page_bilingual_srt": owned_relative(
                            exported_page_paths["srt"]
                        )
                    }
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
            "final_cue_timeline_path": owned_relative(final_timeline_path),
            "final_cue_timeline_sha256": file_sha256(final_timeline_path),
            "word_ledger_path": owned_relative(word_ledger_path),
            "word_ledger_sha256": file_sha256(word_ledger_path),
            "parent_chinese_authority_path": owned_relative(
                render_contract["parent_chinese_authority_path"]
            ),
            "parent_chinese_authority_sha256": render_contract[
                "parent_chinese_authority_sha256"
            ],
            "parent_chinese_authority_hash": render_contract[
                "parent_chinese_authority_hash"
            ],
            "display_page_translation_path": owned_relative(
                artifact_dir / "display-page-translations.json"
            ),
            "display_page_translation_status": render_contract["display_status"],
            "display_page_translation_contract_hash": render_contract[
                "display_contract_hash"
            ],
            "display_page_translation_sha256": file_sha256(
                artifact_dir / "display-page-translations.json"
            ),
            "display_boundary_evidence_path": owned_relative(
                artifact_dir / "display-boundary-evidence.json"
            ),
            "display_boundary_evidence_sha256": file_sha256(
                artifact_dir / "display-boundary-evidence.json"
            ),
            "display_page_map_path": owned_relative(exported_page_paths["map"]),
            "display_page_map_sha256": (
                file_sha256(Path(exported_page_paths["map"]))
                if exported_page_paths["map"]
                else ""
            ),
            "manual_draft_page_plan_path": owned_relative(
                render_contract["manual_draft_page_plan_path"]
            ),
            "manual_draft_page_plan_sha256": render_contract[
                "manual_draft_page_plan_sha256"
            ],
            "manual_final_override": manual_override,
            "display_page_review_summary": review_summary,
            "source_media_path": manifest_media_path,
            "tail_trim": published_tail_trim,
            "media_mute": published_media_mute,
            "media_derivation": published_media_derivation,
            "suppressed_subtitle_ids": [
                str(cue.get("cue_id") or "")
                for cue in self.cues
                if cue.get("display_suppressed")
            ],
            "muted_subtitle_ids": [
                str(cue.get("cue_id") or "")
                for cue in self.cues
                if cue.get("media_muted")
            ],
        }
        manual_manifest["source_subtitle_paths_sha256"] = {
            key: file_sha256(Path(value))
            for key, value in manual_manifest["source_subtitle_paths"].items()
            if value
        }
        package_manifest_path = package_dir / "stable-final-manifest.json"
        report(96, "正在校验并发布人工终稿包")
        candidate_manifest_path = (
            package_dir / f".stable-final-manifest.{generation_id}.candidate.json"
        )
        write_json_artifact(candidate_manifest_path, manual_manifest)
        try:
            owned_files = (
                ("subtitle_path", "subtitle_sha256"),
                ("edit_artifact_path", "edit_artifact_sha256"),
                ("final_cue_timeline_path", "final_cue_timeline_sha256"),
                ("word_ledger_path", "word_ledger_sha256"),
                (
                    "parent_chinese_authority_path",
                    "parent_chinese_authority_sha256",
                ),
                ("display_page_srt_path", "display_page_srt_sha256"),
                ("display_page_map_path", "display_page_map_sha256"),
                ("manual_draft_page_plan_path", "manual_draft_page_plan_sha256"),
            )
            for path_key, hash_key in owned_files:
                declared = str(manual_override.get(path_key) or "")
                if not declared:
                    continue
                resolved = resolve_manifest_owned_path(
                    candidate_manifest_path,
                    manual_manifest,
                    declared,
                    str(manual_override.get(hash_key) or ""),
                )
                if resolved is None:
                    raise ManualFinalSubtitleEditError(
                        f"人工终稿 generation 制品校验失败：{path_key}"
                    )
            resolved_artifact_dir = resolve_manifest_owned_path(
                candidate_manifest_path,
                manual_manifest,
                manual_override["artifact_dir"],
                expect_directory=True,
            )
            if resolved_artifact_dir is None:
                raise ManualFinalSubtitleEditError(
                    "人工终稿 generation 的 artifacts 目录无效。"
                )
            validated_session = self.load_from_manifest(candidate_manifest_path)
            expected_tail_trim = (
                {
                    "source_media_path": str(
                        published_media_derivation.get("source_media_path") or ""
                    ),
                    "source_media_sha256": str(
                        published_media_derivation.get("source_media_sha256") or ""
                    ),
                    "cut_ms": int(published_media_derivation["cut_ms"]),
                    "decision_hash": str(
                        published_media_derivation.get("decision_hash") or ""
                    ),
                    "derived_media_path": str(
                        published_media_derivation.get("derived_media_path") or ""
                    ),
                    "derived_media_sha256": str(
                        published_media_derivation.get("derived_media_sha256") or ""
                    ),
                }
                if published_media_derivation.get("cut_ms") is not None
                else {}
            )
            expected_media_mute = (
                {
                    "source_media_path": str(
                        published_media_derivation.get("source_media_path") or ""
                    ),
                    "source_media_sha256": str(
                        published_media_derivation.get("source_media_sha256") or ""
                    ),
                    "intervals": list(
                        published_media_derivation.get("mute_intervals") or []
                    ),
                    "derived_media_path": str(
                        published_media_derivation.get("derived_media_path") or ""
                    ),
                    "derived_media_sha256": str(
                        published_media_derivation.get("derived_media_sha256") or ""
                    ),
                }
                if published_media_derivation.get("mute_intervals")
                else {}
            )
            expected_fingerprint = stable_payload_hash(
                {
                    "word_ledger": self._ledger_payload(self.word_ledger),
                    "english_surface_overrides": self.english_surface_overrides,
                    "cues": self.cues,
                    "display_page_edits": self.display_page_edits,
                    "display_page_boundary_overrides": (
                        self.display_page_boundary_overrides
                    ),
                    "recovered_stale_page_drafts": (
                        self.recovered_stale_page_drafts
                    ),
                    "tail_trim": expected_tail_trim,
                    "media_mute": expected_media_mute,
                    "media_derivation": published_media_derivation,
                }
            )
            if validated_session.state_fingerprint() != expected_fingerprint:
                raise ManualFinalSubtitleEditError(
                    "人工终稿 generation 回读状态与保存前不一致。"
                )
        finally:
            try:
                candidate_manifest_path.unlink(missing_ok=True)
            except OSError:
                pass
        write_json_artifact(package_manifest_path, manual_manifest)
        self.media_derivation = published_media_derivation
        if published_media_derivation.get("cut_ms") is not None:
            self.tail_trim = {
                "source_media_path": str(
                    published_media_derivation.get("source_media_path") or ""
                ),
                "source_media_sha256": str(
                    published_media_derivation.get("source_media_sha256") or ""
                ),
                "cut_ms": int(published_media_derivation["cut_ms"]),
                "decision_hash": str(
                    published_media_derivation.get("decision_hash") or ""
                ),
            }
        else:
            self.tail_trim = {}
        if list(published_media_derivation.get("mute_intervals") or []):
            self.media_mute = {
                "source_media_path": str(
                    published_media_derivation.get("source_media_path") or ""
                ),
                "source_media_sha256": str(
                    published_media_derivation.get("source_media_sha256") or ""
                ),
                "intervals": list(
                    published_media_derivation.get("mute_intervals") or []
                ),
            }
        else:
            self.media_mute = {}
        report(100, "人工终稿包已保存")
        return {
            "subtitle_path": str(srt_path),
            "edit_artifact_path": str(edit_path),
            "artifact_dir": str(artifact_dir),
            "manifest_path": str(package_manifest_path),
            "source_media_path": str(media_path) if media_path else "",
            "tail_trim": self.tail_trim,
            "media_mute": self.media_mute,
            "media_derivation": self.media_derivation,
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
        return canonical_word_ledger_hash(ledger)

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
        accepted_source_hashes = {expected_hash}
        if self.tail_trim:
            accepted_source_hashes.add(
                str(self.tail_trim.get("source_formal_word_ledger_hash") or "")
            )
        for entry in self.history:
            accepted_source_hashes.add(
                str(entry.get("before_formal_word_ledger_hash") or "")
            )
            before_ledger = entry.get("before_word_ledger") or []
            if isinstance(before_ledger, list) and before_ledger:
                accepted_source_hashes.add(
                    self._formal_word_ledger_hash(before_ledger)
                )
        accepted_source_hashes.discard("")
        if (
            not isinstance(payload, Mapping)
            or int(payload.get("schema_version") or 0) != 1
            or str(payload.get("policy_version") or "")
            != "formal-boundary-evidence-v1"
            or str(payload.get("word_ledger_hash") or "")
            not in accepted_source_hashes
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
        suppressed_parent_ids = {
            str(cue.get("cue_id") or "")
            for cue in self.cues
            if cue.get("display_suppressed")
        }
        cues = {
            str(cue.get("cue_id") or ""): cue
            for cue in self.cues
            if not cue.get("display_suppressed")
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
            if source_parent_id in suppressed_parent_ids:
                continue
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
                if not source_pages or not 0 <= len(override_starts) <= 5:
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
                plan["english"] = self._display_words_text(
                    int(cue["word_start"]),
                    int(cue["word_end"]),
                )
                for page in plan.get("pages") or []:
                    if not isinstance(page, dict):
                        continue
                    try:
                        page["english"] = self._display_words_text(
                            int(page["word_start"]),
                            int(page["word_end"]),
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
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
                # A tail trim (or another parent-local timing edit) can change
                # the cue envelope while the frozen page spans remain valid.
                # Keep the page IDs, word ranges, and interior boundaries
                # frozen, but reconcile only the two outer display edges with
                # the current authoritative parent cue.
                frozen_pages = list(plan.get("pages") or [])
                if self.tail_trim and frozen_pages:
                    frozen_pages[0]["start_ms"] = int(cue["start_time"])
                    frozen_pages[-1]["end_ms"] = int(cue["end_time"])
                    plan["pages"] = frozen_pages
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

    def _rebuild_authoritative_cue_timeline(self) -> Dict[str, Any]:
        expected_ids = [str(cue.get("cue_id") or "") for cue in self.cues]
        timeline = derive_final_cue_timeline(
            [
                {
                    "subtitle_id": str(cue.get("cue_id") or ""),
                    "word_start": int(cue["word_start"]),
                    "word_end": int(cue["word_end"]),
                }
                for cue in self.cues
            ],
            self.word_ledger,
            expected_subtitle_ids=expected_ids,
            lead_in_ms=DISPLAY_LEAD_IN_MS,
            tail_padding_ms=DISPLAY_TAIL_PADDING_MS,
            display_end_cap_ms=(
                int(self.tail_trim["cut_ms"])
                if self.tail_trim and self.tail_trim.get("cut_ms") is not None
                else None
            ),
        )
        validation = dict(timeline.get("validation") or {})
        if str(validation.get("status") or "") != "PASS":
            error_codes = sorted(
                {
                    str(item.get("code") or "final_timeline_invalid")
                    for item in validation.get("errors") or []
                    if isinstance(item, Mapping)
                }
            )
            detail = ", ".join(error_codes[:6])
            raise ManualFinalSubtitleEditError(
                "人工终稿时间轴无法从固定词账本安全重建。"
                + (f"（{detail}）" if detail else "")
            )

        records_by_id = {
            str(record.get("subtitle_id") or ""): record
            for record in timeline.get("records") or []
            if isinstance(record, Mapping)
        }
        if set(records_by_id) != set(expected_ids):
            raise ManualFinalSubtitleEditError(
                "人工终稿时间轴没有完整覆盖当前固定字幕 ID。"
            )
        for cue in self.cues:
            record = records_by_id[str(cue.get("cue_id") or "")]
            cue["start_time"] = int(record["start_ms"])
            cue["end_time"] = int(record["end_ms"])
        self._validate_cues()
        return timeline

    def _write_manual_render_contract(
        self,
        artifact_dir: Path,
        *,
        final_cue_timeline: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
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

        timeline = copy.deepcopy(
            dict(final_cue_timeline or self._rebuild_authoritative_cue_timeline())
        )
        timeline_records_by_id = {
            str(record.get("subtitle_id") or ""): dict(record)
            for record in timeline.get("records") or []
            if isinstance(record, Mapping)
        }
        boundary_payload = self._validated_display_boundary_evidence()
        boundary_items = dict(boundary_payload.get("boundaries") or {})
        records = []
        render_cues = []
        for index, cue in enumerate(self.cues, 1):
            subtitle_id = str(cue.get("cue_id") or f"S{index:04d}")
            word_start = int(cue["word_start"])
            word_end = int(cue["word_end"])
            display_suppressed = bool(cue.get("display_suppressed"))
            media_muted = bool(cue.get("media_muted"))
            timeline_record = timeline_records_by_id.get(subtitle_id)
            if timeline_record is None:
                raise ManualFinalSubtitleEditError(
                    "人工终稿时间轴缺少当前固定字幕 ID。"
                )
            records.append(
                {
                    **timeline_record,
                    "subtitle_id": subtitle_id,
                    "word_start": word_start,
                    "word_end": word_end,
                    "original": str(cue["original_subtitle"]),
                    "translated": str(cue.get("translated_subtitle") or ""),
                    "display_suppressed": display_suppressed,
                    "media_muted": media_muted,
                }
            )
            if display_suppressed:
                continue
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

        timeline["records"] = records
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
        parent_chinese_authority = self._current_parent_chinese_authority()
        parent_chinese_by_id = parent_chinese_records_by_id(
            parent_chinese_authority
        )
        if str(display_artifact.get("status") or "") == "PASS":
            try:
                display_artifact = bind_display_page_parent_records(
                    display_artifact,
                    parent_chinese_by_id,
                )
            except AuthoritativeParentChineseError as exc:
                raise ManualFinalSubtitleEditError(str(exc)) from exc
        write_json_artifact(
            artifact_dir / "word-ledger.json",
            {
                "schema_version": 2,
                "hash_version": WORD_LEDGER_HASH_VERSION,
                "hash": self._semantic_word_ledger_hash(self.word_ledger),
                "words": self.word_ledger,
                "english_surface_overrides": self.english_surface_overrides,
            },
        )
        write_json_artifact(artifact_dir / "final-cue-timeline.json", timeline)
        authority_path = artifact_dir / "authoritative-parent-chinese.json"
        write_json_artifact(authority_path, parent_chinese_authority)
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
                    "display_suppressed": bool(
                        record.get("display_suppressed")
                    ),
                    "media_muted": bool(record.get("media_muted")),
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
                    "translated_text": str(
                        parent_chinese_by_id[record["subtitle_id"]]["chinese"]
                    ),
                    "parent_source_hash": str(
                        parent_chinese_by_id[record["subtitle_id"]]["source_hash"]
                    ),
                    "parent_record_hash": str(
                        parent_chinese_by_id[record["subtitle_id"]]["record_hash"]
                    ),
                    "display_suppressed": bool(
                        record.get("display_suppressed")
                    ),
                    "media_muted": bool(record.get("media_muted")),
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
            "parent_chinese_authority_path": str(authority_path),
            "parent_chinese_authority_sha256": file_sha256(authority_path),
            "parent_chinese_authority_hash": str(
                parent_chinese_authority.get("artifact_hash") or ""
            ),
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
        visible_cues = [
            cue for cue in self.cues if not cue.get("display_suppressed")
        ]
        for index, cue in enumerate(visible_cues, 1):
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
