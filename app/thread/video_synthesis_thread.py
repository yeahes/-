import datetime
import json
import logging
import re
import threading
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from app.common.config import cfg
from app.core.bk_asr.asr_data import ASRData
from app.core.entities import SynthesisTask
from app.core.subtitle_processor.screen_editor import (
    CHINESE_CPS_ERROR,
    SUBTITLE_DURATION_INVALID_MS,
)
from app.core.subtitle_processor.stable_artifacts import (
    file_sha256,
    find_stable_manifest_for_artifact,
    manifest_generation_dir,
    resolve_manifest_owned_path,
    validate_manifest_artifact,
)
from app.core.subtitle_processor.stable_pipeline_contracts import stable_payload_hash
from app.core.utils.logger import setup_logger
from app.core.utils.podcast_learning_video import render_podcast_learning_video
from app.core.utils.video_utils import (
    MediaSynthesisCancelled,
    add_subtitles,
    terminate_media_process,
)

logger = setup_logger("video_synthesis_thread")

MANUAL_DRAFT_ALLOWED_BLOCK_REASONS = frozenset(
    {
        "render_structural_overflow",
        "manual_page_translation_required",
        "manual_page_translation_invalid",
    }
)


def _manual_draft_subtitle_path(manifest: dict, manifest_path: Path) -> Path:
    """Validate the immutable inputs before allowing a page-quality draft."""
    override = manifest.get("manual_final_override") or {}
    if not isinstance(override, dict) or int(override.get("schema_version") or 0) < 2:
        raise RuntimeError("只有保存过的人工终稿包可以合成草稿视频。")

    reasons = {
        str(code or "")
        for code in (manifest.get("validation_error_codes") or [])
        if str(code or "")
    }
    override_reason = str(override.get("render_block_reason") or "")
    if override_reason:
        reasons.add(override_reason)
    if not reasons or not reasons.issubset(MANUAL_DRAFT_ALLOWED_BLOCK_REASONS):
        raise RuntimeError("当前阻断不属于可人工承担的分页草稿范围，拒绝合成。")

    subtitle_path = resolve_manifest_owned_path(
        manifest_path,
        manifest,
        str(override.get("subtitle_path") or ""),
        str(override.get("subtitle_sha256") or ""),
    )
    if subtitle_path is None or not validate_manifest_artifact(
        manifest,
        "original_top_srt",
        subtitle_path,
        manifest_path=manifest_path,
    ):
        raise RuntimeError("人工终稿字幕路径或清单哈希无效，拒绝合成草稿。")
    expected_hash = str(override.get("subtitle_sha256") or "")
    if not expected_hash or file_sha256(subtitle_path) != expected_hash:
        raise RuntimeError("人工终稿字幕哈希不一致，拒绝合成草稿。")

    artifact_dir = resolve_manifest_owned_path(
        manifest_path,
        manifest,
        str(override.get("artifact_dir") or ""),
        expect_directory=True,
    )
    timeline_path = resolve_manifest_owned_path(
        manifest_path,
        manifest,
        str(override.get("final_cue_timeline_path") or ""),
    )
    ledger_path = resolve_manifest_owned_path(
        manifest_path,
        manifest,
        str(override.get("word_ledger_path") or ""),
    )
    if artifact_dir is None or timeline_path is None or ledger_path is None:
        raise RuntimeError("人工终稿缺少最终时间轴或词级账本，拒绝合成草稿。")
    try:
        artifact_owner = artifact_dir.resolve()
        if (
            timeline_path.resolve().parent != artifact_owner
            or ledger_path.resolve().parent != artifact_owner
        ):
            raise RuntimeError("人工终稿时间轴或词级账本不属于当前字幕包。")
    except OSError as exc:
        raise RuntimeError("人工终稿时间轴或词级账本路径无效。") from exc
    timeline_sha256 = str(override.get("final_cue_timeline_sha256") or "")
    ledger_sha256 = str(override.get("word_ledger_sha256") or "")
    if (
        not timeline_sha256
        or file_sha256(timeline_path) != timeline_sha256
        or not ledger_sha256
        or file_sha256(ledger_path) != ledger_sha256
    ):
        raise RuntimeError("人工终稿时间轴或词级账本哈希不一致，拒绝合成草稿。")
    draft_page_path = resolve_manifest_owned_path(
        manifest_path,
        manifest,
        str(manifest.get("manual_draft_page_plan_path") or ""),
        str(manifest.get("manual_draft_page_plan_sha256") or ""),
    )
    draft_page_sha256 = str(
        manifest.get("manual_draft_page_plan_sha256") or ""
    )
    override_draft_page_path = resolve_manifest_owned_path(
        manifest_path,
        manifest,
        str(override.get("manual_draft_page_plan_path") or ""),
        str(override.get("manual_draft_page_plan_sha256") or ""),
    )
    override_draft_page_sha256 = str(
        override.get("manual_draft_page_plan_sha256") or ""
    )
    try:
        draft_page_owned = (
            draft_page_path is not None
            and override_draft_page_path is not None
            and draft_page_path.resolve().parent == artifact_owner
            and draft_page_path.resolve() == override_draft_page_path.resolve()
        )
    except OSError:
        draft_page_owned = False
    if (
        not draft_page_owned
        or not draft_page_sha256
        or draft_page_sha256 != override_draft_page_sha256
        or file_sha256(draft_page_path) != draft_page_sha256
    ):
        raise RuntimeError("人工草稿缺少已保存且校验通过的分页计划，请重新保存字幕包。")
    generation_dir = manifest_generation_dir(manifest_path, manifest)
    if generation_dir is not None:
        try:
            subtitle_path.resolve().relative_to(generation_dir)
        except (OSError, ValueError) as exc:
            raise RuntimeError("人工终稿字幕不属于当前 generation，拒绝合成草稿。") from exc
    elif manifest_path.parent.resolve() != subtitle_path.parent.resolve():
        raise RuntimeError("人工终稿字幕不属于当前清单目录，拒绝合成草稿。")
    return subtitle_path


def ensure_synthesis_subtitle_not_blocked(
    subtitle_path: str | Path,
    *,
    allow_manual_draft: bool = False,
) -> None:
    """Reject a blocked package even when its SRT is selected directly."""
    selected = Path(subtitle_path)
    manifest_path = selected if selected.name == "stable-final-manifest.json" else (
        find_stable_manifest_for_artifact(selected)
        or selected.parent / "stable-final-manifest.json"
    )
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"稳定字幕包不可读取：{manifest_path}") from exc
    if not isinstance(manifest, dict) or not manifest.get("render_blocked"):
        return
    if allow_manual_draft:
        draft_subtitle = _manual_draft_subtitle_path(manifest, manifest_path)
        if selected == manifest_path:
            return
        try:
            if selected.resolve() == draft_subtitle.resolve():
                return
        except OSError:
            if selected == draft_subtitle:
                return
        raise RuntimeError("草稿授权只适用于当前人工终稿字幕。")
    if _blocked_manifest_reading_speed_is_now_safe(manifest, manifest_path):
        return
    if selected == manifest_path:
        raise RuntimeError("稳定字幕包尚未通过检查，已阻止合成视频。")
    candidate_paths = list((manifest.get("paths") or {}).values())
    override_path = str(
        (manifest.get("manual_final_override") or {}).get("subtitle_path") or ""
    )
    if override_path:
        candidate_paths.append(override_path)
    try:
        selected_resolved = selected.resolve()
    except OSError:
        selected_resolved = selected
    for candidate in candidate_paths:
        if not candidate:
            continue
        try:
            candidate_path = (
                resolve_manifest_owned_path(manifest_path, manifest, str(candidate))
                or Path(str(candidate)).resolve()
            )
        except OSError:
            candidate_path = Path(str(candidate))
        if candidate_path == selected_resolved:
            raise RuntimeError("当前字幕属于未通过检查的字幕包，已阻止合成视频。")


def resolve_synthesis_package_inputs(
    manifest_path: str | Path,
    media_path: str = "",
    *,
    allow_manual_draft: bool = False,
) -> tuple[str, str]:
    """Validate a stable package and recover its source media when available."""
    selected = Path(manifest_path)
    try:
        manifest = json.loads(selected.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"稳定字幕包不可读取：{selected}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError(f"稳定字幕包格式无效：{selected}")
    if manifest.get("render_blocked"):
        if allow_manual_draft:
            _manual_draft_subtitle_path(manifest, selected)
        else:
            raise RuntimeError("稳定字幕包尚未通过检查，请先处理人工复核项。")

    stable_path = resolve_manifest_owned_path(
        selected,
        manifest,
        str((manifest.get("paths") or {}).get("original_top_srt") or ""),
        str((manifest.get("paths_sha256") or {}).get("original_top_srt") or ""),
    )
    if stable_path is None:
        raise RuntimeError("稳定字幕包中的终稿路径或哈希无效。")
    if not validate_manifest_artifact(
        manifest,
        "original_top_srt",
        stable_path,
        manifest_path=selected,
    ):
        raise RuntimeError("稳定字幕包中的终稿路径或哈希无效。")

    override = manifest.get("manual_final_override") or {}
    manifest_media = str(
        override.get("source_media_path")
        or manifest.get("source_media_path")
        or ""
    )
    tail_trim = override.get("tail_trim") or manifest.get("tail_trim") or {}
    media_mute = override.get("media_mute") or manifest.get("media_mute") or {}
    media_derivation = (
        override.get("media_derivation")
        or manifest.get("media_derivation")
        or {}
    )
    if media_derivation and (tail_trim or media_mute):
        raise RuntimeError("稳定字幕包不能同时包含 v2 媒体派生和旧媒体编辑记录。")
    if tail_trim and media_mute:
        raise RuntimeError("稳定字幕包不能同时包含尾部裁剪和区间静音。")
    if media_derivation:
        intervals = list(media_derivation.get("mute_intervals") or [])
        raw_cut = media_derivation.get("cut_ms")
        try:
            cut_ms = int(raw_cut) if raw_cut is not None else None
            previous_end = -1
            intervals_valid = True
            for item in intervals:
                start_ms = int(item.get("start_ms", -1))
                end_ms = int(item.get("end_ms", 0))
                subtitle_id = str(item.get("subtitle_id") or "").strip()
                if (
                    not subtitle_id
                    or start_ms < 0
                    or end_ms <= start_ms
                    or start_ms < previous_end
                    or (cut_ms is not None and end_ms > cut_ms)
                ):
                    intervals_valid = False
                    break
                previous_end = end_ms
        except (AttributeError, TypeError, ValueError):
            cut_ms = None
            intervals_valid = False
        decision_payload = {
            "schema_version": 2,
            "source_media_sha256": str(
                media_derivation.get("source_media_sha256") or ""
            ),
            "source_word_ledger_hash": str(
                media_derivation.get("source_word_ledger_hash") or ""
            ),
            "cut_ms": cut_ms,
            "mute_intervals": intervals,
        }
        if (
            int(media_derivation.get("schema_version") or 0) != 2
            or (cut_ms is None and not intervals)
            or (raw_cut is not None and cut_ms is None)
            or (cut_ms is not None and cut_ms <= 0)
            or not intervals_valid
            or not decision_payload["source_media_sha256"]
            or not decision_payload["source_word_ledger_hash"]
            or str(media_derivation.get("decision_hash") or "")
            != stable_payload_hash(decision_payload)
        ):
            raise RuntimeError("媒体派生包中的区间、切点或决策哈希无效。")
    elif media_mute:
        intervals = list(media_mute.get("intervals") or [])
        decision_payload = {
            "schema_version": int(media_mute.get("schema_version") or 0),
            "source_media_sha256": str(
                media_mute.get("source_media_sha256") or ""
            ),
            "source_word_ledger_hash": str(
                media_mute.get("source_word_ledger_hash") or ""
            ),
            "intervals": intervals,
        }
        interval_ids = [
            str(item.get("subtitle_id") or "")
            for item in intervals
            if isinstance(item, dict)
        ]
        try:
            intervals_valid = all(
                int(item.get("start_ms", -1)) >= 0
                and int(item.get("end_ms", 0))
                > int(item.get("start_ms", -1))
                for item in intervals
            )
        except (AttributeError, TypeError, ValueError):
            intervals_valid = False
        if (
            not intervals
            or len(interval_ids) != len(intervals)
            or not intervals_valid
            or any(not subtitle_id for subtitle_id in interval_ids)
            or interval_ids
            != [str(value) for value in media_mute.get("muted_subtitle_ids") or []]
            or not decision_payload["source_media_sha256"]
            or not decision_payload["source_word_ledger_hash"]
            or str(media_mute.get("decision_hash") or "")
            != stable_payload_hash(decision_payload)
        ):
            raise RuntimeError("区间静音包中的字幕范围或决策哈希无效。")
    if media_derivation or tail_trim or media_mute:
        active_derivation = media_derivation or tail_trim or media_mute
        expected_hash = str(active_derivation.get("derived_media_sha256") or "")
        derived_media = resolve_manifest_owned_path(
            selected,
            manifest,
            str(active_derivation.get("derived_media_path") or ""),
            expected_hash,
        )
        if (
            derived_media is None
            or not expected_hash
            or (
                manifest_media
                and resolve_manifest_owned_path(
                    selected,
                    manifest,
                    manifest_media,
                    expected_hash,
                ) != derived_media
            )
        ):
            label = "媒体派生" if media_derivation else (
                "区间静音" if media_mute else "尾部裁剪"
            )
            raise RuntimeError(f"{label}包中的派生音频路径或哈希无效。")
        # A caller may still hold the original media selected before saving.
        # The trim package owns the derived audio and must override that stale input.
        resolved_media = str(derived_media.resolve())
    else:
        resolved_media = str(media_path or "")
        if not resolved_media and manifest_media and Path(manifest_media).is_file():
            resolved_media = str(Path(manifest_media))
    return resolved_media, str(selected)


def synthesis_package_has_tail_trim(manifest_path: str | Path) -> bool:
    path = Path(manifest_path)
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(manifest, dict)
        and (
            manifest.get("media_derivation")
            or (manifest.get("manual_final_override") or {}).get(
                "media_derivation"
            )
            or
            manifest.get("tail_trim")
            or (manifest.get("manual_final_override") or {}).get("tail_trim")
        )
    )


def synthesis_package_has_media_mute(manifest_path: str | Path) -> bool:
    path = Path(manifest_path)
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(manifest, dict)
        and (
            manifest.get("media_derivation")
            or (manifest.get("manual_final_override") or {}).get(
                "media_derivation"
            )
            or
            manifest.get("media_mute")
            or (manifest.get("manual_final_override") or {}).get("media_mute")
        )
    )


def _blocked_manifest_reading_speed_is_now_safe(
    manifest: dict,
    manifest_path: Path | None = None,
) -> bool:
    """Allow an old manifest only when its sole retired blocker is revalidated.

    This is deliberately narrow: it never clears missing translations, timing,
    English-length, ID, or any other structural validation failure.
    """
    errors = list((manifest.get("validation_summary") or {}).get("errors") or [])
    if not errors or {str(item.get("code") or "") for item in errors} != {
        "reading_speed_error"
    }:
        return False

    declared = str((manifest.get("paths") or {}).get("original_top_srt") or "")
    if manifest_path is not None:
        stable_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            declared,
            str((manifest.get("paths_sha256") or {}).get("original_top_srt") or ""),
        )
    else:
        stable_path = Path(declared)
    if stable_path is None:
        return False
    if not stable_path.exists() or stable_path.stat().st_size <= 0:
        return False

    try:
        subtitle_data = ASRData.from_srt(stable_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        logger.warning("Cannot revalidate blocked stable subtitle: %s", exc)
        return False

    for segment in subtitle_data.segments:
        duration_ms = max(1, int(segment.end_time) - int(segment.start_time))
        if duration_ms < SUBTITLE_DURATION_INVALID_MS:
            continue
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", segment.translated_text or ""))
        if (
            chinese_chars >= 12
            and duration_ms >= 1200
            and chinese_chars / (duration_ms / 1000.0) > CHINESE_CPS_ERROR
        ):
            return False
    return True


def resolve_podcast_template_subtitle(
    video_file: str,
    subtitle_file: str,
    *,
    allow_manual_draft: bool = False,
) -> str:
    """Prefer bilingual original-on-top SRT for the podcast learning template."""
    subtitle_path = Path(subtitle_file)
    search_dir = subtitle_path.parent
    video_stem = Path(video_file).stem

    manifest_path = find_stable_manifest_for_artifact(subtitle_path)
    if manifest_path is None:
        manifest_path = search_dir / "stable-final-manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"稳定字幕清单不可读取，已阻止使用旧字幕合成视频：{manifest_path}"
            ) from exc
        if not isinstance(manifest, dict):
            raise RuntimeError(
                f"稳定字幕清单格式无效，已阻止使用旧字幕合成视频：{manifest_path}"
            )
        if manifest.get("render_blocked"):
            if allow_manual_draft:
                return str(_manual_draft_subtitle_path(manifest, manifest_path))
            if _blocked_manifest_reading_speed_is_now_safe(manifest, manifest_path):
                stable_path = resolve_manifest_owned_path(
                    manifest_path,
                    manifest,
                    str(manifest.get("paths", {}).get("original_top_srt", "")),
                    str(
                        (manifest.get("paths_sha256") or {}).get(
                            "original_top_srt"
                        )
                        or ""
                    ),
                )
                if stable_path is None or not validate_manifest_artifact(
                    manifest,
                    "original_top_srt",
                    stable_path,
                    manifest_path=manifest_path,
                ):
                    raise RuntimeError(
                        "稳定字幕清单中的终稿路径或哈希无效，已阻止合成视频。"
                    )
                logger.info(
                    "Revalidated legacy reading-speed manifest under current threshold: %s",
                    manifest_path,
                )
                return str(stable_path)
            logger.warning("Stable subtitle manifest is blocked by validation: %s", manifest_path)
            raise RuntimeError(
                "字幕体检未通过，已阻止使用该稳定字幕合成视频。"
            )
        manual_override = manifest.get("manual_final_override") or {}
        manual_path_text = str(manual_override.get("subtitle_path") or "")
        manual_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            manual_path_text,
            str(manual_override.get("subtitle_sha256") or ""),
        )
        if manual_path is not None and manual_path.exists() and manual_path.stat().st_size > 0:
            if manual_override.get("render_blocked"):
                raise RuntimeError(
                    "人工终稿仍缺少可验证的分页中文或存在结构溢出，已阻止合成视频。"
                )
            expected_hash = str(manual_override.get("subtitle_sha256") or "")
            if (
                int(manual_override.get("schema_version") or 1) >= 2
                and not expected_hash
            ) or (expected_hash and file_sha256(manual_path) != expected_hash):
                raise RuntimeError(
                    "人工终稿字幕哈希与清单不一致，已阻止合成视频。"
                )
            logger.info(
                "Resolved podcast subtitle from manual final override: %s", manual_path
            )
            return str(manual_path)
        stable_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            str((manifest.get("paths") or {}).get("original_top_srt") or ""),
            str((manifest.get("paths_sha256") or {}).get("original_top_srt") or ""),
        )
        if stable_path is not None and validate_manifest_artifact(
            manifest,
            "original_top_srt",
            stable_path,
            manifest_path=manifest_path,
        ):
            logger.info("Resolved podcast subtitle from stable manifest: %s", stable_path)
            return str(stable_path)
        raise RuntimeError(
            f"稳定字幕清单未指向可用终稿，已阻止使用旧字幕合成视频：{manifest_path}"
        )

    candidates = [
        search_dir / "stable-final-original-top.srt",
        search_dir / f"{video_stem}-原文在上.srt",
        search_dir / f"{video_stem}-译文在上.srt",
    ]
    candidates.extend(sorted(search_dir.glob("stable-final-*-top.srt")))
    candidates.extend(sorted(search_dir.glob("*-原文在上.srt")))
    candidates.extend(sorted(search_dir.glob("*-译文在上.srt")))
    if subtitle_path.suffix.lower() == ".srt":
        candidates.append(subtitle_path)

    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            return str(candidate)
    return subtitle_file


class VideoSynthesisThread(QThread):
    finished = pyqtSignal(SynthesisTask)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, task: SynthesisTask):
        super().__init__()
        self.task = task
        self._cancel_event = threading.Event()
        self._process_lock = threading.Lock()
        self._active_process = None
        logger.debug(f"初始化 VideoSynthesisThread，任务: {self.task}")

    def run(self):
        try:
            if self.is_cancelled():
                raise MediaSynthesisCancelled("视频合成已取消")
            logger.info(f"\n===========视频合成任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")
            video_file = self.task.video_path
            subtitle_file = self.task.subtitle_path
            output_path = self.task.output_path
            soft_subtitle = self.task.synthesis_config.soft_subtitle
            need_video = self.task.synthesis_config.need_video
            podcast_learning_template = (
                self.task.synthesis_config.podcast_learning_template
            )
            render_mode = self.task.synthesis_config.subtitle_render_mode
            subtitle_layout = self.task.synthesis_config.subtitle_layout
            rounded_style = self.task.synthesis_config.rounded_style
            manual_draft_mode = bool(
                getattr(self.task.synthesis_config, "manual_draft_mode", False)
            )

            if manual_draft_mode and (
                not podcast_learning_template
                or self.task.synthesis_config.podcast_template_style != "文章单词"
            ):
                raise RuntimeError("人工草稿只能使用文章单词模板合成。")

            selected_subtitle = Path(subtitle_file)
            package_manifest = (
                selected_subtitle
                if selected_subtitle.suffix.lower() == ".json"
                else find_stable_manifest_for_artifact(selected_subtitle)
            )
            package_input = str(package_manifest or subtitle_file)
            has_tail_trim = synthesis_package_has_tail_trim(package_input)
            has_media_mute = synthesis_package_has_media_mute(package_input)
            if (has_tail_trim or has_media_mute) and not podcast_learning_template:
                label = "隐藏并静音" if has_media_mute else "尾部裁剪"
                raise RuntimeError(f"{label}终稿第一版只能使用静态播客模板合成。")

            if not need_video:
                logger.info(f"不需要合成视频，跳过")
                self.progress.emit(100, self.tr("合成完成"))
                self.finished.emit(self.task)
                return

            if package_manifest is not None:
                video_file, subtitle_file = resolve_synthesis_package_inputs(
                    package_manifest,
                    video_file,
                    allow_manual_draft=manual_draft_mode,
                )

            ensure_synthesis_subtitle_not_blocked(
                subtitle_file,
                allow_manual_draft=manual_draft_mode,
            )

            logger.info(f"开始合成视频: {video_file}")
            self.progress.emit(5, self.tr("正在合成"))

            if podcast_learning_template:
                subtitle_file = resolve_podcast_template_subtitle(
                    video_file,
                    subtitle_file,
                    allow_manual_draft=manual_draft_mode,
                )
                logger.info(f"Podcast learning template subtitle: {subtitle_file}")
                render_podcast_learning_video(
                    video_file,
                    subtitle_file,
                    output_path,
                    template_style=self.task.synthesis_config.podcast_template_style,
                    show_ai_vocab=self.task.synthesis_config.podcast_template_ai_vocab,
                    english_only=bool(
                        getattr(
                            self.task.synthesis_config,
                            "podcast_template_english_only",
                            False,
                        )
                    ),
                    title_text=self.task.synthesis_config.podcast_template_title,
                    background_path=self.task.synthesis_config.podcast_template_background,
                    cover_path=self.task.synthesis_config.podcast_template_cover,
                    logo_path=self.task.synthesis_config.podcast_template_logo,
                    date_text=self.task.synthesis_config.podcast_template_date,
                    progress_callback=self.progress_callback,
                    cancel_check=self.is_cancelled,
                    process_callback=self._set_active_process,
                    allow_manual_draft=manual_draft_mode,
                )
                if self.is_cancelled():
                    raise MediaSynthesisCancelled("视频合成已取消")
                self.progress.emit(100, self.tr("合成完成"))
                logger.info(f"Podcast learning template video saved: {output_path}")
                self.finished.emit(self.task)
                return

            add_subtitles(
                video_file,
                subtitle_file,
                output_path,
                soft_subtitle=soft_subtitle,
                render_mode=render_mode,
                subtitle_layout=subtitle_layout,
                rounded_style=rounded_style,
                progress_callback=self.progress_callback,
                cancel_check=self.is_cancelled,
                process_callback=self._set_active_process,
            )

            if self.is_cancelled():
                raise MediaSynthesisCancelled("视频合成已取消")
            self.progress.emit(100, self.tr("合成完成"))
            logger.info(f"视频合成完成，保存路径: {output_path}")

            self.finished.emit(self.task)
        except MediaSynthesisCancelled:
            logger.info("视频合成已取消")
            self.progress.emit(0, self.tr("已取消"))
        except Exception as e:
            logger.exception(f"视频合成失败: {e}")
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("视频合成失败"))
        finally:
            self._set_active_process(None)

    def progress_callback(self, value, message):
        if self.is_cancelled():
            raise MediaSynthesisCancelled("视频合成已取消")
        progress = int(5 + int(value) / 100 * 95)
        logger.debug(f"合成进度: {progress}% - {message}")
        self.progress.emit(progress, str(progress) + "% " + message)

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set() or self.isInterruptionRequested()

    def _set_active_process(self, process) -> None:
        with self._process_lock:
            self._active_process = process
            cancel_now = process is not None and self.is_cancelled()
        if cancel_now:
            terminate_media_process(process)

    def stop(self) -> None:
        """Cooperatively stop rendering and terminate its active ffmpeg process."""
        self._cancel_event.set()
        self.requestInterruption()
        with self._process_lock:
            process = self._active_process
        terminate_media_process(process)
        if self.isRunning() and not self.wait(3000):
            logger.warning("视频合成线程未能在3秒内停止")
