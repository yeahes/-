import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.config import BIN_PATH
from app.core.output_paths import media_result_dir, media_result_subtitle_dir
from app.core.subtitle_processor.manual_final_subtitle_editor import (
    ManualFinalSubtitleEditError,
    ManualFinalSubtitleSession,
    _materialize_media_mute_audio,
)
from app.core.subtitle_processor import stable_display_page_contract
from app.core.subtitle_processor.authoritative_parent_chinese import (
    parent_chinese_records_by_id,
    validate_display_page_parent_records,
)
from app.core.subtitle_processor.stable_artifacts import file_sha256
from app.core.utils import podcast_learning_video
from app.thread.video_synthesis_thread import (
    resolve_podcast_template_subtitle,
    resolve_synthesis_package_inputs,
)
from app.core.utils.podcast_learning_video import (
    attach_article_word_timing,
    load_article_display_page_translation_artifact,
    parse_srt,
)


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_srt(path: Path) -> None:
    path.write_text(
        """1
00:00:00,000 --> 00:00:00,900
Right. It means our mental model is just completely
中文一

2
00:00:00,900 --> 00:00:01,200
out of date.
中文二
""",
        encoding="utf-8-sig",
    )


def test_legacy_display_page_plan_is_marked_for_refresh():
    session = ManualFinalSubtitleSession.__new__(ManualFinalSubtitleSession)
    session.display_page_edits = []
    session.display_page_boundary_overrides = {}
    session._effective_display_page_artifact = lambda: {
        "status": "ERROR",
        "planner_version": "article-fixed-font-pages-v28",
    }
    assert session.display_page_plan_needs_refresh() is True


def test_current_display_page_plan_does_not_require_refresh():
    session = ManualFinalSubtitleSession.__new__(ManualFinalSubtitleSession)
    session.display_page_edits = []
    session.display_page_boundary_overrides = {}
    session._effective_display_page_artifact = lambda: {
        "status": "PASS",
        "planner_version": stable_display_page_contract.DISPLAY_PAGE_PLANNER_VERSION,
    }
    assert session.display_page_plan_needs_refresh() is False


def _session_fixture(root: Path) -> tuple[ManualFinalSubtitleSession, Path, Path]:
    source_dir = root / "source"
    subtitle_dir = root / "work" / "subtitle"
    artifact_dir = subtitle_dir / "output-artifacts"
    source_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    source_srt = source_dir / "bilingual.srt"
    stable_srt = subtitle_dir / "stable-final-original-top.srt"
    _write_srt(source_srt)
    _write_srt(stable_srt)
    words = [
        "Right.",
        "It",
        "means",
        "our",
        "mental",
        "model",
        "is",
        "just",
        "completely",
        "out",
        "of",
        "date.",
    ]
    ledger_words = [
        {
            "word_id": index,
            "surface": word,
            "normalized": word.casefold().strip("."),
            "start_ms": index * 100,
            "end_ms": (index + 1) * 100,
        }
        for index, word in enumerate(words)
    ]
    _write_json(
        artifact_dir / "word-ledger.json",
        {"words": ledger_words},
    )
    _write_json(
        artifact_dir / "display-boundary-evidence.json",
        {
            "schema_version": 1,
            "policy_version": "formal-boundary-evidence-v1",
            "word_ledger_hash": ManualFinalSubtitleSession._formal_word_ledger_hash(
                ledger_words
            ),
            "boundaries": {
                str(right): {
                    "hard_issues": [],
                    "soft_issues": [],
                    "boundary_score": 0.0,
                    "protected_syntax": False,
                    "pause_ms": 0,
                }
                for right in range(1, len(ledger_words))
            },
        },
    )
    _write_json(
        artifact_dir / "subtitle-spans.json",
        [
            {
                "subtitle_id": "S0001",
                "word_start": 0,
                "word_end": 8,
                "original": "Right. It means our mental model is just completely",
            },
            {
                "subtitle_id": "S0002",
                "word_start": 9,
                "word_end": 11,
                "original": "out of date.",
            },
        ],
    )
    _write_json(
        artifact_dir / "translations.json",
        [
            {
                "subtitle_id": "S0001",
                "text": "Right. It means our mental model is just completely",
                "translated_text": "中文一",
            },
            {
                "subtitle_id": "S0002",
                "text": "out of date.",
                "translated_text": "中文二",
            },
        ],
    )
    manifest_path = subtitle_dir / "stable-final-manifest.json"
    _write_json(
        manifest_path,
        {
            "coverage_report": str(subtitle_dir / "output-coverage-report.txt"),
            "paths": {"original_top_srt": str(stable_srt)},
            "paths_sha256": {"original_top_srt": file_sha256(stable_srt)},
            "source_subtitle_paths": {"bilingual_original_top_srt": str(source_srt)},
        },
    )
    session = ManualFinalSubtitleSession.load_for_subtitle(source_srt, work_dir=root / "work")
    return session, source_srt, manifest_path


def _tail_trim_session_fixture(
    root: Path,
    source_media: Path,
) -> tuple[ManualFinalSubtitleSession, Path, Path]:
    _, source_srt, manifest_path = _session_fixture(root)
    artifact_dir = manifest_path.parent / "output-artifacts"
    ledger_path = artifact_dir / "word-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))["words"]
    for word in ledger[9:]:
        word["start_ms"] += 200
        word["end_ms"] += 200
    _write_json(ledger_path, {"words": ledger})

    evidence_path = artifact_dir / "display-boundary-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["word_ledger_hash"] = ManualFinalSubtitleSession._formal_word_ledger_hash(
        ledger
    )
    _write_json(evidence_path, evidence)

    session = ManualFinalSubtitleSession.load_for_subtitle(
        source_srt,
        work_dir=root / "work",
        manifest_path=manifest_path,
    )
    session.source_media_path = source_media.resolve()
    return session, source_srt, manifest_path


def _run_project_ffmpeg(*native_args: str) -> subprocess.CompletedProcess[str]:
    ffmpeg = BIN_PATH / "ffmpeg.exe"
    assert ffmpeg.is_file(), f"project FFmpeg is missing: {ffmpeg}"
    result = subprocess.run(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *native_args,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=(
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        ),
    )
    assert result.returncode == 0, result.stderr
    return result


def _project_ffmpeg_audio_duration_ms(path: Path) -> int:
    result = _run_project_ffmpeg(
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "null",
        "-",
    )
    out_time_us = [
        int(line.split("=", 1)[1])
        for line in result.stdout.splitlines()
        if line.startswith("out_time_us=")
    ]
    assert out_time_us, result.stdout
    return int(round(max(out_time_us) / 1000))


def _write_display_page_preview_artifact(session: ManualFinalSubtitleSession) -> None:
    _write_json(
        session.artifact_dir / "display-page-translations.json",
        {
            "status": "PASS",
            "parents": [
                {
                    "parent_subtitle_id": "S0001",
                    "pages": [
                        {"display_page_id": "S0001.P01", "zh": "中"},
                        {"display_page_id": "S0001.P02", "zh": "文一"},
                    ],
                }
            ],
            "render_plans": [
                {
                    "parent_subtitle_id": "S0001",
                    "english": "Right. It means our mental model is just completely",
                    "chinese": "中文一",
                    "word_start": 0,
                    "word_end": 8,
                    "english_font_size": 56,
                    "pages": [
                        {
                            "display_page_id": "S0001.P01",
                            "page_index": 1,
                            "word_start": 0,
                            "word_end": 3,
                            "english": "Right. It means our",
                            "start_ms": 0,
                            "end_ms": 400,
                            "english_font_size": 56,
                        },
                        {
                            "display_page_id": "S0001.P02",
                            "page_index": 2,
                            "word_start": 4,
                            "word_end": 8,
                            "english": "mental model is just completely",
                            "start_ms": 400,
                            "end_ms": 900,
                            "english_font_size": 56,
                        },
                    ],
                },
                {
                    "parent_subtitle_id": "S0002",
                    "english": "out of date.",
                    "chinese": "中文二",
                    "word_start": 9,
                    "word_end": 11,
                    "english_font_size": 54,
                    "pages": [
                        {
                            "display_page_id": "S0002.P01",
                            "page_index": 1,
                            "word_start": 9,
                            "word_end": 11,
                            "english": "out of date.",
                            "start_ms": 900,
                            "end_ms": 1200,
                            "english_font_size": 54,
                        }
                    ],
                },
            ],
        },
    )


def _splittable_parent_session(
    root: Path,
) -> tuple[ManualFinalSubtitleSession, Path, Path]:
    _, source_srt, manifest_path = _session_fixture(root)
    artifact_dir = manifest_path.parent / "output-artifacts"
    stable_srt = Path(
        json.loads(manifest_path.read_text(encoding="utf-8"))["paths"][
            "original_top_srt"
        ]
    )
    words = (
        "Students compare choices carefully. Families review costs together. "
        "Advisers explain visa rules clearly. Graduates plan careers thoughtfully."
    ).split()
    english = " ".join(words)
    chinese = "甲，乙，丙"
    subtitle_text = (
        "1\n"
        "00:00:00,000 --> 00:00:07,200\n"
        f"{english}\n"
        f"{chinese}\n"
    )
    source_srt.write_text(subtitle_text, encoding="utf-8-sig")
    stable_srt.write_text(subtitle_text, encoding="utf-8-sig")
    ledger_words = [
        {
            "word_id": index,
            "surface": word,
            "normalized": word.casefold().strip("."),
            "start_ms": index * 400,
            "end_ms": index * 400 + 300,
        }
        for index, word in enumerate(words)
    ]
    _write_json(artifact_dir / "word-ledger.json", {"words": ledger_words})
    _write_json(
        artifact_dir / "display-boundary-evidence.json",
        {
            "schema_version": 1,
            "policy_version": "formal-boundary-evidence-v1",
            "word_ledger_hash": ManualFinalSubtitleSession._formal_word_ledger_hash(
                ledger_words
            ),
            "boundaries": {
                str(right): {
                    "hard_issues": (
                        []
                        if right in {4, 8, 13}
                        else ["fixture_non_phrase_boundary"]
                    ),
                    "soft_issues": [],
                    "boundary_score": 0.0,
                    "protected_syntax": False,
                    "pause_ms": 100 if right in {4, 8, 13} else 0,
                }
                for right in range(1, len(words))
            },
        },
    )
    _write_json(
        artifact_dir / "subtitle-spans.json",
        [
            {
                "subtitle_id": "S0001",
                "word_start": 0,
                "word_end": len(words) - 1,
                "original": english,
            }
        ],
    )
    _write_json(
        artifact_dir / "translations.json",
        [
            {
                "subtitle_id": "S0001",
                "text": english,
                "translated_text": chinese,
            }
        ],
    )
    display_artifact_path = artifact_dir / "display-page-translations.json"
    _write_json(
        display_artifact_path,
        {
            "schema_version": 2,
            "status": "PASS",
            "parents": [],
            "render_plans": [
                {
                    "parent_subtitle_id": "S0001",
                    "english": english,
                    "chinese": chinese,
                    "word_start": 0,
                    "word_end": len(words) - 1,
                    "english_font_size": 56,
                    "font_fallback": {"used": False},
                    "pages": [
                        {
                            "display_page_id": "S0001.P01",
                            "page_index": 1,
                            "word_start": 0,
                            "word_end": len(words) - 1,
                            "english": english,
                            "chinese": chinese,
                            "start_ms": 0,
                            "end_ms": 7200,
                            "english_font_size": 56,
                            "english_lines": [english],
                            "english_width": 1400,
                            "boundary_before": {
                                "classification": "allow",
                                "confidence": "low",
                                "issue_codes": [],
                            },
                        }
                    ],
                }
            ],
        },
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["paths_sha256"]["original_top_srt"] = file_sha256(stable_srt)
    manifest["display_page_translation_path"] = str(display_artifact_path)
    manifest["display_page_translation_sha256"] = file_sha256(
        display_artifact_path
    )
    _write_json(manifest_path, manifest)
    session = ManualFinalSubtitleSession.load_for_subtitle(
        source_srt,
        work_dir=root / "work",
    )
    return session, source_srt, manifest_path


def _manual_page_state_fixture() -> tuple[list[dict], dict[str, list[int]]]:
    return (
        [
            {
                "display_page_id": "S0001.P01",
                "manual_cue_id": "S0001",
                "parent_cue_index": 0,
                "word_start": 0,
                "word_end": 3,
                "original_subtitle": "Right. It means our",
                "translated_subtitle": "中文",
                "start_time": 0,
                "end_time": 400,
                "english_font_size": 56,
            },
            {
                "display_page_id": "S0001.P02",
                "manual_cue_id": "S0001",
                "parent_cue_index": 0,
                "word_start": 4,
                "word_end": 8,
                "original_subtitle": "mental model is just completely",
                "translated_subtitle": "一",
                "start_time": 400,
                "end_time": 900,
                "english_font_size": 56,
            },
        ],
        {"S0001": [4]},
    )


def _write_immutable_source_page_snapshot(
    session: ManualFinalSubtitleSession,
    source_media: Path,
) -> tuple[Path, Path]:
    result_dir = media_result_dir(source_media)
    subtitle_dir = media_result_subtitle_dir(source_media)
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    parent_path = subtitle_dir / f"{source_media.stem}-原文在上双语字幕.srt"
    page_path = subtitle_dir / f"{source_media.stem}-实际分页双语字幕.srt"
    map_path = subtitle_dir / f"{source_media.stem}-实际分页映射.json"
    session._write_bilingual_srt(parent_path)
    render_contract = session._write_manual_render_contract(
        result_dir / "source-page-snapshot-artifacts"
    )
    assert render_contract["render_blocked"] is False
    session._write_display_page_exports(
        page_path,
        map_path,
        render_contract["display_artifact"],
        source_parent_subtitle_path=parent_path,
    )
    manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
    manifest["source_subtitle_paths"] = {
        "bilingual_original_top_srt": str(parent_path),
        "display_page_bilingual_srt": str(page_path),
        "display_page_map": str(map_path),
    }
    manifest["source_subtitle_paths_sha256"] = {
        key: file_sha256(Path(value))
        for key, value in manifest["source_subtitle_paths"].items()
    }
    _write_json(session.manifest_path, manifest)
    return page_path, map_path


def _assert_page_export_blocked(session: ManualFinalSubtitleSession) -> None:
    try:
        session.save_to_source_folder()
        assert False, "invalid page evidence must never be silently recalculated"
    except ManualFinalSubtitleEditError as exc:
        assert "manual_page_boundary_evidence_required" in str(exc)


def _assert_complete_formal_boundary_evidence(
    session: ManualFinalSubtitleSession,
    payload: dict,
) -> None:
    expected = [str(right) for right in range(1, len(session.word_ledger))]
    assert list(payload["boundaries"]) == expected
    assert len(payload["boundaries"]) == len(session.word_ledger) - 1


def test_manual_page_export_requires_matching_complete_boundary_evidence():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, _, _ = _session_fixture(root)
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence_path.unlink()
        _assert_page_export_blocked(session)

        session, _, _ = _session_fixture(root / "mismatch")
        payload = json.loads(
            (session.artifact_dir / "display-boundary-evidence.json").read_text(
                encoding="utf-8"
            )
        )
        payload["word_ledger_hash"] = "wrong-ledger-hash"
        _write_json(session.artifact_dir / "display-boundary-evidence.json", payload)
        _assert_page_export_blocked(session)

        session, _, _ = _session_fixture(root / "missing-boundary")
        payload = json.loads(
            (session.artifact_dir / "display-boundary-evidence.json").read_text(
                encoding="utf-8"
            )
        )
        payload["boundaries"].pop("5")
        _write_json(session.artifact_dir / "display-boundary-evidence.json", payload)
        _assert_page_export_blocked(session)


def test_legacy_package_recovers_omitted_saved_cue_boundary_across_move_and_undo():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        session.move_suffix_to_next(0, 1)
        saved = session.save_to_source_folder()
        manifest_path = Path(saved["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        evidence_path = Path(manifest["display_boundary_evidence_path"])
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        saved_cue_boundary = int(session.cues[1]["word_start"])
        assert saved_cue_boundary == 8
        evidence["boundaries"].pop(str(saved_cue_boundary))
        _write_json(evidence_path, evidence)
        manifest["display_boundary_evidence_sha256"] = file_sha256(evidence_path)
        _write_json(manifest_path, manifest)

        reloaded = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        loaded_payload = reloaded._validated_display_boundary_evidence()
        _assert_complete_formal_boundary_evidence(reloaded, loaded_payload)
        assert loaded_payload["boundaries"][str(saved_cue_boundary)][
            "evidence_origin"
        ] == "accepted_formal_cue_boundary"

        reloaded.move_suffix_to_next(0, 1)
        moved_payload = reloaded._validated_display_boundary_evidence()
        _assert_complete_formal_boundary_evidence(reloaded, moved_payload)

        undone_operations = []
        while reloaded.history:
            undone_operations.append(reloaded.history[-1]["operation"])
            assert reloaded.undo() is True
        assert undone_operations == [
            "move_suffix_to_next",
            "move_suffix_to_next",
        ]
        restored_payload = reloaded._validated_display_boundary_evidence()
        _assert_complete_formal_boundary_evidence(reloaded, restored_payload)
        assert [(cue["word_start"], cue["word_end"]) for cue in reloaded.cues] == [
            (0, 8),
            (9, 11),
        ]


def test_missing_internal_boundary_evidence_still_fails_closed():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, source_srt, manifest_path = _session_fixture(Path(temp_dir))
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["boundaries"].pop("5")
        _write_json(evidence_path, evidence)

        reloaded = ManualFinalSubtitleSession.load_for_subtitle(
            source_srt,
            manifest_path=manifest_path,
        )
        try:
            reloaded._validated_display_boundary_evidence()
        except ManualFinalSubtitleEditError as exc:
            assert "manual_page_boundary_evidence_required" in str(exc)
        else:
            raise AssertionError("an internal evidence gap must remain fatal")


def test_saved_package_keeps_complete_evidence_after_reload_move_undo_and_resave():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        session.move_suffix_to_next(0, 1)
        first_saved = session.save_to_source_folder()
        first_manifest = json.loads(
            Path(first_saved["manifest_path"]).read_text(encoding="utf-8")
        )
        first_evidence = json.loads(
            Path(first_manifest["display_boundary_evidence_path"]).read_text(
                encoding="utf-8"
            )
        )
        _assert_complete_formal_boundary_evidence(session, first_evidence)

        reloaded = ManualFinalSubtitleSession.load_from_manifest(
            first_saved["manifest_path"]
        )
        before_move = [dict(cue) for cue in reloaded.cues]
        reloaded.move_suffix_to_next(0, 1)
        assert reloaded.undo() is True
        assert reloaded.cues == before_move

        second_saved = reloaded.save_to_source_folder()
        second_manifest = json.loads(
            Path(second_saved["manifest_path"]).read_text(encoding="utf-8")
        )
        second_evidence = json.loads(
            Path(second_manifest["display_boundary_evidence_path"]).read_text(
                encoding="utf-8"
            )
        )
        _assert_complete_formal_boundary_evidence(reloaded, second_evidence)

        reopened = ManualFinalSubtitleSession.load_from_manifest(
            second_saved["manifest_path"]
        )
        _assert_complete_formal_boundary_evidence(
            reopened,
            reopened._validated_display_boundary_evidence(),
        )


def test_move_suffix_updates_text_ranges_and_timing_from_word_ledger():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))

        session.move_suffix_to_next(0, 2)

        assert session.cues[0]["original_subtitle"] == "Right. It means our mental model is"
        assert session.cues[1]["original_subtitle"] == "just completely out of date."
        assert (session.cues[0]["word_start"], session.cues[0]["word_end"]) == (0, 6)
        assert (session.cues[1]["word_start"], session.cues[1]["word_end"]) == (7, 11)
        assert session.cues[0]["end_time"] == 700
        assert session.cues[1]["start_time"] == 700
        assert session.cues[0]["chinese_review_required"] is True
        assert session.cues[1]["chinese_review_required"] is True


def test_save_rebuilds_short_gap_compensation_after_formal_boundary_move():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        for word in session.word_ledger[8:]:
            word["start_ms"] += 500
            word["end_ms"] += 500
        session.cues[1]["end_time"] += 500
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["word_ledger_hash"] = session._formal_word_ledger_hash(
            session.word_ledger
        )
        _write_json(evidence_path, evidence)

        session.move_suffix_to_next(0, 1)
        assert session.cues[1]["start_time"] - session.cues[0]["end_time"] == 500

        saved = session.save_to_source_folder()
        timeline = json.loads(
            Path(saved["artifact_dir"], "final-cue-timeline.json").read_text(
                encoding="utf-8"
            )
        )
        left, right = timeline["records"]
        assert left["end_ms"] == right["start_ms"] == 1175
        assert any(
            item["code"] == "final_timeline_short_gap_chained"
            and item["left_subtitle_id"] == "S0001"
            and item["right_subtitle_id"] == "S0002"
            for item in timeline["boundary_reconciliations"]
        )

        saved_cues = parse_srt(Path(saved["subtitle_path"]))
        assert round(saved_cues[0].end * 1000) == 1175
        assert round(saved_cues[1].start * 1000) == 1175
        display_artifact = json.loads(
            Path(
                saved["artifact_dir"], "display-page-translations.json"
            ).read_text(encoding="utf-8")
        )
        plans = {
            plan["parent_subtitle_id"]: plan
            for plan in display_artifact["render_plans"]
        }
        assert plans["S0001"]["pages"][-1]["end_ms"] == 1175
        assert plans["S0002"]["pages"][0]["start_ms"] == 1175
        page_map = json.loads(
            Path(saved["display_page_map_path"]).read_text(encoding="utf-8")
        )
        mapped_pages = {
            page["parent_subtitle_id"]: page for page in page_map["pages"]
        }
        assert mapped_pages["S0001"]["end_ms"] == 1175
        assert mapped_pages["S0002"]["start_ms"] == 1175


def test_formal_boundary_move_keeps_actual_pages_and_visible_chinese_drafts():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)

        model_data = session.to_model_data()
        assert [
            (
                row["display_page_id"],
                row["manual_cue_id"],
                row["original_subtitle"],
                row["translated_subtitle"],
                row["start_time"],
                row["end_time"],
                row["english_font_size"],
            )
            for row in model_data.values()
        ] == [
            ("S0001.P01", "S0001", "Right. It means our", "中", 0, 400, 56),
            (
                "S0001.P02",
                "S0001",
                "mental model is just completely",
                "文一",
                400,
                900,
                56,
            ),
            ("S0002.P01", "S0002", "out of date.", "中文二", 900, 1200, 54),
        ]

        model_data["1"]["original_subtitle"] = "mutated preview"
        assert session.to_model_data()["1"]["original_subtitle"] == "Right. It means our"

        session.move_suffix_to_next(0, 2)
        edited_model_data = session.to_model_data()
        assert [
            row["display_page_id"] for row in edited_model_data.values()
        ] == ["S0001.P01", "S0001.P02", "S0002.P01"]
        assert all(
            row["translated_subtitle"] for row in edited_model_data.values()
        )
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in edited_model_data.values()
        )
        assert [
            (row["manual_cue_id"], row["word_start"], row["word_end"])
            for row in edited_model_data.values()
        ] == [
            ("S0001", 0, 3),
            ("S0001", 4, 6),
            ("S0002", 7, 11),
        ]
        assert session.display_page_boundary_overrides == {
            "S0001": [4],
            "S0002": [],
        }
        assert len(session.display_page_edits) == 3


def test_formal_boundary_move_preserves_unaffected_page_identity_and_chinese():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        third_word_id = len(session.word_ledger)
        session.word_ledger.append(
            {
                "word_id": third_word_id,
                "surface": "Today.",
                "normalized": "today",
                "start_ms": 1200,
                "end_ms": 1300,
            }
        )
        session.cues.append(
            {
                "cue_id": "S0003",
                "source_subtitle_ids": ["S0003"],
                "word_start": third_word_id,
                "word_end": third_word_id,
                "start_time": 1200,
                "end_time": 1300,
                "original_subtitle": "Today.",
                "translated_subtitle": "今天。",
                "chinese_review_required": False,
            }
        )
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["word_ledger_hash"] = session._formal_word_ledger_hash(
            session.word_ledger
        )
        evidence["boundaries"][str(third_word_id)] = {
            "hard_issues": [],
            "soft_issues": [],
            "boundary_score": 0.0,
            "protected_syntax": False,
            "pause_ms": 0,
        }
        _write_json(evidence_path, evidence)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["render_plans"].append(
            {
                "parent_subtitle_id": "S0003",
                "english": "Today.",
                "chinese": "今天。",
                "word_start": third_word_id,
                "word_end": third_word_id,
                "english_font_size": 56,
                "pages": [
                    {
                        "display_page_id": "S0003.P01",
                        "page_index": 1,
                        "word_start": third_word_id,
                        "word_end": third_word_id,
                        "english": "Today.",
                        "chinese": "今天。",
                        "start_ms": 1200,
                        "end_ms": 1300,
                        "english_font_size": 56,
                    }
                ],
            }
        )
        _write_json(artifact_path, artifact)
        before = next(
            row
            for row in session.to_model_data().values()
            if row.get("display_page_id") == "S0003.P01"
        )

        session.move_suffix_to_next(0, 2)

        after = next(
            row
            for row in session.to_model_data().values()
            if row.get("display_page_id") == "S0003.P01"
        )
        assert {
            key: after[key]
            for key in (
                "display_page_id",
                "manual_cue_id",
                "word_start",
                "word_end",
                "original_subtitle",
                "translated_subtitle",
                "start_time",
                "end_time",
            )
        } == {
            key: before[key]
            for key in (
                "display_page_id",
                "manual_cue_id",
                "word_start",
                "word_end",
                "original_subtitle",
                "translated_subtitle",
                "start_time",
                "end_time",
            )
        }
        assert after["display_page_chinese_stale"] is False
        assert after["display_page_chinese_confirmed"] is True


def test_formal_boundary_reflow_failure_rolls_back_instead_of_clearing_pages():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        rows = list(session.to_model_data().values())
        session.display_page_edits = [
            session._unchanged_display_page_edit_from_model_row(row)
            for row in rows
        ]
        session.display_page_boundary_overrides = {"S0001": [4], "S0002": []}
        before_cues = json.loads(json.dumps(session.cues))
        before_edits = json.loads(json.dumps(session.display_page_edits))
        before_overrides = json.loads(
            json.dumps(session.display_page_boundary_overrides)
        )
        before_history = json.loads(json.dumps(session.history))

        def fail_reflow(*_args, **_kwargs):
            session._invalidate_display_page_state()
            return False

        with patch.object(
            session,
            "_reflow_display_page_state_after_formal_boundary_change",
            side_effect=fail_reflow,
        ):
            try:
                session.move_suffix_to_next(0, 2)
            except ManualFinalSubtitleEditError as exc:
                assert "实际分页" in str(exc)
            else:
                raise AssertionError("a failed local page reflow must reject the edit")

        assert session.cues == before_cues
        assert session.display_page_edits == before_edits
        assert session.display_page_boundary_overrides == before_overrides
        assert session.history == before_history


def test_save_rejects_silent_collapse_of_recorded_manual_page_state():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        rows = list(session.to_model_data().values())
        session.display_page_edits = [
            session._unchanged_display_page_edit_from_model_row(row)
            for row in rows
        ]
        session.display_page_boundary_overrides = {"S0001": [4], "S0002": []}
        session._record_history(
            "move_suffix_to_next",
            json.loads(json.dumps(session.cues)),
        )
        session._invalidate_display_page_state()

        try:
            session.save_to_source_folder()
        except ManualFinalSubtitleEditError as exc:
            assert "人工分页状态" in str(exc)
        else:
            raise AssertionError("collapsed manual page state must not be published")


def test_blank_current_pages_recover_only_exact_history_chinese_as_drafts():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        rows = session.to_model_data()
        session.history = [
            {
                "operation": "fixture",
                "before_display_page_edits": [
                    {
                        "display_page_id": row["display_page_id"],
                        "parent_subtitle_id": row["manual_cue_id"],
                        "word_start": row["word_start"],
                        "word_end": row["word_end"],
                        "english": row["original_subtitle"],
                        "chinese": row["translated_subtitle"],
                    }
                    for row in rows.values()
                ],
            }
        ]
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["status"] = "ERROR"
        artifact["errors"] = [{"code": "manual_page_translation_required"}]
        for parent in artifact["parents"]:
            for page in parent["pages"]:
                page["zh"] = ""
        for plan in artifact["render_plans"]:
            for page in plan["pages"]:
                page["chinese"] = ""
                page["zh"] = ""
        _write_json(artifact_path, artifact)

        recovered_count = session._recover_identity_matched_history_page_drafts()
        recovered_rows = list(session.to_model_data().values())

        assert recovered_count == 2
        first_parent_pages = [
            row for row in recovered_rows if row["manual_cue_id"] == "S0001"
        ]
        assert [row["translated_subtitle"] for row in first_parent_pages] == [
            "中",
            "文一",
        ]
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in first_parent_pages
        )


def test_page_row_chinese_edits_preserve_parent_and_page_identity():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        rows = session.to_model_data()
        rows["1"]["translated_subtitle"] = "这里是中"
        rows["2"]["translated_subtitle"] = "文第一页"

        session.apply_display_page_model_data(rows)

        assert session.cues[0]["translated_subtitle"] == "这里是中文第一页"
        refreshed = session.to_model_data()
        assert [
            (
                row["display_page_id"],
                row["manual_cue_id"],
                row["word_start"],
                row["word_end"],
                row["translated_subtitle"],
            )
            for row in refreshed.values()
        ] == [
            ("S0001.P01", "S0001", 0, 3, "这里是中"),
            ("S0001.P02", "S0001", 4, 8, "文第一页"),
            ("S0002.P01", "S0002", 9, 11, "中文二"),
        ]


def test_parent_model_sync_rejects_row_order_drift_before_writing_chinese():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        rows = session.to_model_data(prefer_display_pages=False)
        first = copy.deepcopy(rows["1"])
        second = copy.deepcopy(rows["2"])
        first["translated_subtitle"] = "第一条新译"
        second["translated_subtitle"] = "第二条新译"
        reordered = {"1": second, "2": first}
        before_cues = copy.deepcopy(session.cues)
        before_history = copy.deepcopy(session.history)
        caught = None

        try:
            session.apply_parent_model_data(reordered)
        except ManualFinalSubtitleEditError as exc:
            caught = exc

        assert caught is not None, "row order drift must fail before any cue is written"
        assert session.cues == before_cues
        assert session.history == before_history


def test_parent_chinese_edit_is_undoable_without_discarding_valid_page_state():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        rows = session.to_model_data(prefer_display_pages=False)
        page_edits, boundary_overrides = _manual_page_state_fixture()
        session.display_page_edits = copy.deepcopy(page_edits)
        session.display_page_boundary_overrides = copy.deepcopy(boundary_overrides)
        rows["1"]["translated_subtitle"] = "第一条人工新译"

        changed = session.apply_parent_model_data(rows)

        assert changed is True
        assert session.cues[0]["translated_subtitle"] == "第一条人工新译"
        assert session.history[-1]["operation"] == "edit_parent_chinese"
        assert session.display_page_edits == page_edits
        assert session.display_page_boundary_overrides == boundary_overrides
        assert session.undo() is True
        assert session.cues[0]["translated_subtitle"] == "中文一"
        assert session.display_page_edits == page_edits
        assert session.display_page_boundary_overrides == boundary_overrides


def test_incomplete_page_state_rejects_structural_change_atomically():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        page_edits, boundary_overrides = _manual_page_state_fixture()
        session.display_page_edits = copy.deepcopy(page_edits)
        session.display_page_boundary_overrides = copy.deepcopy(boundary_overrides)
        before_cues = copy.deepcopy(session.cues)
        before_history = copy.deepcopy(session.history)

        try:
            session.move_suffix_to_next(0, 2)
        except ManualFinalSubtitleEditError as exc:
            assert "实际分页" in str(exc)
        else:
            raise AssertionError("incomplete page ownership must reject the edit")

        assert session.cues == before_cues
        assert session.history == before_history
        assert session.display_page_edits == page_edits
        assert session.display_page_boundary_overrides == boundary_overrides


def test_edit_artifact_hash_and_embedded_ledger_are_both_verified_on_load():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        paths = session.save_to_source_folder()
        manifest_path = Path(paths["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        override = manifest["manual_final_override"]
        edit_path = Path(override["edit_artifact_path"])

        assert override["edit_artifact_sha256"] == file_sha256(edit_path)
        edit_payload = json.loads(edit_path.read_text(encoding="utf-8"))
        edit_payload["history"].append({"operation": "tampered"})
        _write_json(edit_path, edit_payload)
        try:
            ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        except ManualFinalSubtitleEditError:
            pass
        else:
            raise AssertionError("a tampered edit artifact must not load")

    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        paths = session.save_to_source_folder()
        manifest_path = Path(paths["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        override = manifest["manual_final_override"]
        edit_path = Path(override["edit_artifact_path"])
        edit_payload = json.loads(edit_path.read_text(encoding="utf-8"))
        edit_payload["word_ledger"][0]["surface"] = "Tampered."
        _write_json(edit_path, edit_payload)
        override["edit_artifact_sha256"] = file_sha256(edit_path)
        _write_json(manifest_path, manifest)
        try:
            ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        except ManualFinalSubtitleEditError:
            pass
        else:
            raise AssertionError("a foreign embedded word ledger must not load")


def test_blocked_checkpoint_reloads_unconfirmed_chinese_page_proposals():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 3)
        expected_rows = session.to_model_data()
        expected_english = [
            (
                row["display_page_id"],
                row["manual_cue_id"],
                row["word_start"],
                row["word_end"],
                row["original_subtitle"],
            )
            for row in expected_rows.values()
        ]
        assert all(row["translated_subtitle"] for row in expected_rows.values())
        assert "".join(
            row["translated_subtitle"] for row in expected_rows.values()
        ) == session.cues[0]["translated_subtitle"]
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            and row["display_page_chinese_draft_kind"]
            == "local_parent_split_proposal"
            for row in expected_rows.values()
        )

        blocked = session.save_to_source_folder()

        assert blocked["render_blocked"] is True
        assert blocked["render_block_reason"] == "manual_page_translation_required"
        assert blocked["display_page_srt_path"] == ""
        reloaded = ManualFinalSubtitleSession.load_from_manifest(
            blocked["manifest_path"]
        )
        reloaded_rows = reloaded.to_model_data()
        assert [
            (
                row["display_page_id"],
                row["manual_cue_id"],
                row["word_start"],
                row["word_end"],
                row["original_subtitle"],
            )
            for row in reloaded_rows.values()
        ] == expected_english
        assert [
            row["translated_subtitle"] for row in reloaded_rows.values()
        ] == [row["translated_subtitle"] for row in expected_rows.values()]
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in reloaded_rows.values()
        )
        assert reloaded.display_page_edits == session.display_page_edits
        assert (
            reloaded.display_page_boundary_overrides
            == session.display_page_boundary_overrides
        )


def test_complete_page_edits_recover_when_blocked_checkpoint_lost_page_artifact():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 3)
        first_save = session.save_to_source_folder()
        assert first_save["render_blocked"] is True
        assert first_save["manual_draft_ready"] is True

        manifest_path = Path(first_save["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = Path(manifest["display_page_translation_path"])
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["status"] = "ERROR"
        artifact["errors"] = [{"code": "manual_page_translation_required"}]
        artifact["parents"] = []
        artifact["render_plans"] = []
        _write_json(artifact_path, artifact)
        manifest["display_page_translation_sha256"] = file_sha256(artifact_path)
        draft_path = Path(manifest["manual_draft_page_plan_path"])
        draft_path.unlink()
        for owner in (manifest, manifest["manual_final_override"]):
            owner["manual_draft_page_plan_path"] = ""
            owner["manual_draft_page_plan_sha256"] = ""
        _write_json(manifest_path, manifest)

        recovered = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        expected_pages = [
            (
                str(item["display_page_id"]),
                str(item["parent_subtitle_id"]),
                int(item["word_start"]),
                int(item["word_end"]),
                str(item["english"]),
            )
            for item in recovered.display_page_edits
        ]

        recovered_rows = list(
            recovered.to_model_data(prefer_display_pages=True).values()
        )

        assert recovered.has_display_page_model() is True
        assert [
            (
                str(row["display_page_id"]),
                str(row["manual_cue_id"]),
                int(row["word_start"]),
                int(row["word_end"]),
                str(row["original_subtitle"]),
            )
            for row in recovered_rows
        ] == expected_pages

        second_save = recovered.save_to_source_folder()

        assert second_save["render_blocked"] is True
        assert second_save["render_block_reason"] == "manual_page_translation_required"
        assert second_save["manual_draft_ready"] is True
        assert Path(second_save["manual_draft_page_plan_path"]).is_file()
        reloaded = ManualFinalSubtitleSession.load_from_manifest(
            second_save["manifest_path"]
        )
        assert reloaded.has_display_page_model() is True
        assert [
            (
                str(row["display_page_id"]),
                str(row["manual_cue_id"]),
                int(row["word_start"]),
                int(row["word_end"]),
                str(row["original_subtitle"]),
            )
            for row in reloaded.to_model_data(prefer_display_pages=True).values()
        ] == expected_pages


def test_split_parent_into_two_three_four_pages_preserves_frozen_parent():
    for page_count in (2, 3, 4):
        with tempfile.TemporaryDirectory() as temp_dir:
            session, _, _ = _splittable_parent_session(Path(temp_dir))
            before = dict(session.cues[0])

            session.split_parent_into_display_pages("S0001", page_count)

            pages = list(session.to_model_data().values())
            assert [page["display_page_id"] for page in pages] == [
                f"S0001.P{index:02d}"
                for index in range(1, page_count + 1)
            ]
            assert all(page["manual_cue_id"] == "S0001" for page in pages)
            if page_count in {2, 3}:
                assert all(page["translated_subtitle"] for page in pages)
                assert "".join(
                    page["translated_subtitle"] for page in pages
                ) == before["translated_subtitle"]
                assert all(
                    page["display_page_chinese_stale"] is True
                    and page["display_page_chinese_confirmed"] is False
                    for page in pages
                )
            else:
                assert all(page["translated_subtitle"] == "" for page in pages)
            assert all(page["chinese_review_required"] is True for page in pages)
            assert all(
                page["end_time"] - page["start_time"] >= 900
                for page in pages
            )
            assert [page["word_start"] for page in pages[1:]] == (
                session.display_page_boundary_overrides["S0001"]
            )
            assert set(page["word_start"] for page in pages[1:]) <= {4, 8, 13}
            if page_count == 4:
                assert [page["word_start"] for page in pages[1:]] == [4, 8, 13]
            assert " ".join(page["original_subtitle"] for page in pages) == before[
                "original_subtitle"
            ]
            assert [
                (
                    session.cues[0][field]
                    if field != "source_subtitle_ids"
                    else list(session.cues[0][field])
                )
                for field in (
                    "cue_id",
                    "source_subtitle_ids",
                    "word_start",
                    "word_end",
                    "start_time",
                    "end_time",
                    "original_subtitle",
                )
            ] == [
                (
                    before[field]
                    if field != "source_subtitle_ids"
                    else list(before[field])
                )
                for field in (
                    "cue_id",
                    "source_subtitle_ids",
                    "word_start",
                    "word_end",
                    "start_time",
                    "end_time",
                    "original_subtitle",
                )
            ]


def test_split_parent_accepts_planner_review_boundary_without_changing_parent():
    """A review cut selected by manual planning must survive plan rebuilding."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        before = copy.deepcopy(session.cues[0])
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["boundaries"]["9"].update(
            {
                "hard_issues": ["preposition_object_split"],
                "soft_issues": [],
                "pause_ms": 0,
            }
        )
        _write_json(evidence_path, evidence)

        with patch.object(
            podcast_learning_video,
            "propose_article_manual_page_word_ranges",
            return_value=[(0, 8), (9, 16)],
        ):
            result = session.split_parent_into_display_pages("S0001", 2)

        assert result["changed"] is True
        pages = list(session.to_model_data().values())
        assert len(pages) == 2
        page_word_ids = [
            word_id
            for page in pages
            for word_id in range(page["word_start"], page["word_end"] + 1)
        ]
        assert page_word_ids == list(
            range(before["word_start"], before["word_end"] + 1)
        )
        assert [page["word_start"] for page in pages[1:]] == (
            session.display_page_boundary_overrides["S0001"]
        )
        assert all(
            session.cues[0][field] == before[field]
            for field in (
                "cue_id",
                "source_subtitle_ids",
                "word_start",
                "word_end",
                "start_time",
                "end_time",
                "original_subtitle",
                "translated_subtitle",
            )
        )


def test_candidate_workspace_maps_local_pages_to_global_word_ids_without_mutation():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        before_cues = copy.deepcopy(session.cues)
        with patch(
            "app.core.utils.podcast_learning_video.build_article_display_page_candidate_workspace",
            return_value={
                "status": "candidate_workspace",
                "parent_subtitle_id": "S0001",
                "preferred_page_count": 2,
                "candidate_mode": "strict",
                "candidates": [
                    {
                        "page_count": 2,
                        "quality_cost": 12,
                        "plan": {"font_size": {"english": 56}},
                        "pages": [
                            {"word_start": 0, "word_end": 7, "en": "first"},
                            {"word_start": 8, "word_end": 16, "en": "second"},
                        ],
                    }
                ],
            },
        ):
            workspace = session.build_display_page_candidate_workspace("S0001")
        assert workspace["candidates"][0]["global_word_ranges"] == [
            [0, 7],
            [8, 16],
        ]
        assert session.cues == before_cues


def test_candidate_workspace_explains_each_noninitial_boundary_in_chinese():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        with patch(
            "app.core.utils.podcast_learning_video.build_article_display_page_candidate_workspace",
            return_value={
                "status": "candidate_workspace",
                "parent_subtitle_id": "S0001",
                "preferred_page_count": 2,
                "candidate_mode": "forced_continuation",
                "candidates": [
                    {
                        "page_count": 2,
                        "quality_cost": 12,
                        "plan": {"font_size": {"english": 56}},
                        "pages": [
                            {"word_start": 0, "word_end": 7, "en": "first"},
                            {
                                "word_start": 8,
                                "word_end": 16,
                                "en": "second",
                                "boundary_before": {
                                    "classification": "review",
                                    "confidence": "high",
                                    "issue_codes": ["subject_predicate_split"],
                                    "forced_display_continuation": True,
                                    "pause_ms": 120,
                                },
                            },
                        ],
                    }
                ],
            },
        ):
            workspace = session.build_display_page_candidate_workspace("S0001")

        explanation = workspace["candidates"][0]["pages"][1][
            "boundary_explanation"
        ]
        assert explanation["classification"] == "review"
        assert explanation["requires_confirmation"] is True
        assert "主语和谓语" in explanation["summary_zh"]
        assert "subject_predicate_split" in explanation["rule_codes"]


def test_nearby_boundary_candidates_are_read_only_and_explain_grammar_risk():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        with patch.object(
            podcast_learning_video,
            "propose_article_manual_page_word_ranges",
            return_value=[(0, 7), (8, 16)],
        ):
            session.split_parent_into_display_pages("S0001", 2)
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["boundaries"]["7"].update(
            {
                "hard_issues": ["subject_finite_verb_split"],
                "soft_issues": [],
                "pause_ms": 100,
            }
        )
        for right_word in (6, 9):
            evidence["boundaries"][str(right_word)].update(
                {"hard_issues": [], "soft_issues": [], "pause_ms": 360}
            )
        evidence["boundaries"]["10"].update(
            {
                "hard_issues": [],
                "soft_issues": ["coordinated_constituent_split"],
                "pause_ms": 360,
            }
        )
        _write_json(evidence_path, evidence)
        before = {
            "cues": copy.deepcopy(session.cues),
            "edits": copy.deepcopy(session.display_page_edits),
            "overrides": copy.deepcopy(session.display_page_boundary_overrides),
            "history": copy.deepcopy(session.history),
            "redo": copy.deepcopy(session.redo_history),
            "ledger": copy.deepcopy(session.word_ledger),
        }

        candidates = session.preview_display_page_boundary_candidates(
            "S0001.P01",
            minimum_duration_ms=0,
        )

        by_boundary = {item["right_word_id"]: item for item in candidates}
        assert by_boundary[7]["applicable"] is False
        assert by_boundary[7]["recommendation"] == "blocked"
        assert "主语和谓语" in by_boundary[7]["rejection_reasons"][0]
        assert by_boundary[6]["applicable"] is True
        assert by_boundary[9]["applicable"] is True
        assert by_boundary[6]["recommendation"] == "recommended"
        assert by_boundary[9]["recommendation"] == "recommended"
        assert by_boundary[10]["recommendation"] == "review"
        assert "并列结构" in by_boundary[10]["boundary_explanation"]["summary_zh"]
        assert by_boundary[6]["left_english"]
        assert by_boundary[6]["right_english"]
        assert session.cues == before["cues"]
        assert session.display_page_edits == before["edits"]
        assert session.display_page_boundary_overrides == before["overrides"]
        assert session.history == before["history"]
        assert session.redo_history == before["redo"]
        assert session.word_ledger == before["ledger"]


def test_applying_candidate_ranges_preserves_matching_page_chinese_only():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 2)
        rows = session.to_model_data()
        first_row, second_row = rows["1"], rows["2"]
        first_row["translated_subtitle"] = "第一屏已确认"
        first_row["display_page_chinese_confirmed"] = True
        second_row["translated_subtitle"] = "第二屏已确认"
        second_row["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(rows)
        original_ranges = [
            [int(first_row["word_start"]), int(first_row["word_end"])],
            [int(second_row["word_start"]), int(second_row["word_end"])],
        ]
        result = session.split_parent_into_display_pages(
            "S0001",
            2,
            word_ranges=original_ranges,
            preserve_matching_page_chinese=True,
        )
        assert result["changed"] is False
        current = list(session.to_model_data().values())
        assert [row["translated_subtitle"] for row in current] == [
            "第一屏已确认",
            "第二屏已确认",
        ]


def test_split_parent_blocks_unconfirmed_page_proposals_then_saves_idempotently():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 3)

        blocked = session.save_to_source_folder()
        assert blocked["render_blocked"] is True
        assert blocked["render_block_reason"] == "manual_page_translation_required"
        assert blocked["display_page_srt_path"] == ""

        rows = session.to_model_data()
        assert [row["translated_subtitle"] for row in rows.values()] == [
            "甲，",
            "乙，",
            "丙",
        ]
        for row in rows.values():
            row["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(rows)
        saved = session.save_to_source_folder()
        assert saved["render_blocked"] is False
        assert Path(saved["display_page_srt_path"]).is_file()

        reloaded = ManualFinalSubtitleSession.load_from_manifest(saved["manifest_path"])
        expected_rows = reloaded.to_model_data()
        assert [row["translated_subtitle"] for row in expected_rows.values()] == [
            "甲，",
            "乙，",
            "丙",
        ]
        saved_again = reloaded.save_to_source_folder()
        reopened = ManualFinalSubtitleSession.load_from_manifest(
            saved_again["manifest_path"]
        )
        assert reopened.to_model_data() == expected_rows


def test_repeating_same_page_count_preserves_confirmed_page_chinese():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        first = session.split_parent_into_display_pages("S0001", 3)
        assert first["changed"] is True
        rows = session.to_model_data()
        for row in rows.values():
            row["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(rows)
        before_edits = copy.deepcopy(session.display_page_edits)
        before_overrides = copy.deepcopy(session.display_page_boundary_overrides)
        before_history = copy.deepcopy(session.history)

        repeated = session.split_parent_into_display_pages("S0001", 3)

        assert repeated["changed"] is False
        assert session.display_page_edits == before_edits
        assert session.display_page_boundary_overrides == before_overrides
        assert session.history == before_history
        repeated_rows = session.to_model_data()
        assert all(
            row["translated_subtitle"]
            and row["display_page_chinese_stale"] is False
            and row["display_page_chinese_confirmed"] is True
            for row in repeated_rows.values()
        )
        saved = session.save_to_source_folder()
        assert saved["render_blocked"] is False
        assert Path(saved["display_page_srt_path"]).is_file()


def test_confirm_one_display_page_chinese_is_scoped_and_persists_after_reload():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 3)
        initial_rows = list(session.to_model_data().values())
        page_ids = [str(row["display_page_id"]) for row in initial_rows]

        confirmed = session.confirm_display_page_chinese(page_ids[0])

        assert confirmed == {"changed": True, "display_page_id": page_ids[0]}
        rows = session.to_model_data()
        visible_rows = list(rows.values())
        assert visible_rows[0]["display_page_chinese_confirmed"] is True
        assert visible_rows[0]["chinese_review_required"] is False
        assert all(
            row["display_page_chinese_confirmed"] is False
            and row["chinese_review_required"] is True
            for row in visible_rows[1:]
        )

        # Editing the visible Chinese and marking it confirmed follows the same
        # model-data path as the dedicated confirmation command.
        rows["2"]["translated_subtitle"] = "人工确认的第二页"
        rows["2"]["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(rows, allow_incomplete_chinese=True)
        edited_rows = list(session.to_model_data().values())
        assert edited_rows[1]["translated_subtitle"] == "人工确认的第二页"
        assert edited_rows[1]["display_page_chinese_confirmed"] is True
        assert edited_rows[2]["display_page_chinese_confirmed"] is False

        session.confirm_display_page_chinese(page_ids[2])
        saved = session.save_to_source_folder()
        assert saved["render_blocked"] is False
        reloaded = ManualFinalSubtitleSession.load_from_manifest(
            Path(saved["manifest_path"])
        )
        reloaded_rows = list(reloaded.to_model_data().values())
        assert [row["display_page_id"] for row in reloaded_rows] == page_ids
        assert [row["display_page_chinese_confirmed"] for row in reloaded_rows] == [
            True,
            True,
            True,
        ]
        assert reloaded_rows[1]["translated_subtitle"] == "人工确认的第二页"


def test_boundary_confirmation_clears_only_review_and_rejects_hard():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["boundaries"]["4"].update(
            {
            "classification": "review",
            "hard_issues": [],
            "soft_issues": ["manual_short_page_review"],
            "issue_codes": ["manual_short_page_review"],
            "pause_ms": 120,
            }
        )
        _write_json(evidence_path, evidence)
        with patch.object(
            podcast_learning_video,
            "propose_article_manual_page_word_ranges",
            return_value=[(0, 3), (4, 7), (8, 16)],
        ):
            session.split_parent_into_display_pages("S0001", 3)

        rows = list(session.to_model_data().values())
        review_id = str(rows[1]["display_page_id"])
        assert rows[1]["display_page_review_required"] is True

        confirmed = session.confirm_display_page_boundary(review_id)
        assert confirmed == {"changed": True, "display_page_id": review_id}
        after_review = list(session.to_model_data().values())
        assert after_review[1]["display_page_boundary_acknowledged"] is True
        assert after_review[1]["display_page_review_required"] is False
        hard_row = copy.deepcopy(after_review[2])
        hard_row["display_page_boundary_classification"] = "hard"
        hard_row["display_page_review_required"] = True

        with patch.object(
            session,
            "_display_page_model_data",
            return_value={"3": hard_row},
        ):
            try:
                session.confirm_display_page_boundary(
                    str(hard_row["display_page_id"])
                )
            except ManualFinalSubtitleEditError as exc:
                assert "结构性硬错误" in str(exc)
            else:
                raise AssertionError("a HARD boundary must never be acknowledged")
        assert list(session.to_model_data().values())[2][
            "display_page_boundary_acknowledged"
        ] is False


def test_moving_page_boundary_confirms_new_boundary_and_invalidates_page_identity():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 2)
        rows = session.to_model_data()
        for row in rows.values():
            row["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(rows)
        before_rows = list(session.to_model_data().values())
        original_ranges = [
            (int(row["word_start"]), int(row["word_end"]))
            for row in before_rows
        ]
        target_start = int(before_rows[1]["word_start"]) - 1
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["boundaries"][str(target_start)].update(
            {"hard_issues": [], "soft_issues": ["manual_short_page_review"], "pause_ms": 120}
        )
        _write_json(evidence_path, evidence)

        moved = session.move_display_page_boundary(
            str(before_rows[0]["display_page_id"]), 1, move_to_next=True
        )

        after_rows = list(session.to_model_data().values())
        assert moved["right_page_id"] == after_rows[1]["display_page_id"]
        assert after_rows[1]["display_page_boundary_acknowledged"] is True
        assert [
            (int(row["word_start"]), int(row["word_end"]))
            for row in after_rows
        ] != original_ranges
        assert all(
            row["display_page_chinese_confirmed"] is False
            and row["chinese_review_required"] is True
            for row in after_rows
        )


def test_moving_page_boundary_preserves_visible_chinese_and_unaffected_pages():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        with patch.object(
            podcast_learning_video,
            "propose_article_manual_page_word_ranges",
            return_value=[(0, 5), (6, 11), (12, 16)],
        ):
            session.split_parent_into_display_pages("S0001", 3)

        rows = session.to_model_data()
        expected_chinese = ["人工第一页", "人工第二页", "人工第三页"]
        for row, chinese in zip(rows.values(), expected_chinese):
            row["translated_subtitle"] = chinese
            row["display_page_chinese_confirmed"] = True
            row["chinese_review_required"] = False
        session.apply_display_page_model_data(rows)

        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["boundaries"]["5"].update(
            {
                "classification": "review",
                "hard_issues": [],
                "soft_issues": ["manual_short_page_review"],
                "issue_codes": ["manual_short_page_review"],
                "pause_ms": 120,
            }
        )
        _write_json(evidence_path, evidence)

        session.move_display_page_boundary(
            "S0001.P01",
            1,
            move_to_next=True,
        )

        after_rows = list(session.to_model_data().values())
        assert [row["translated_subtitle"] for row in after_rows] == expected_chinese
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            and row["chinese_review_required"] is True
            for row in after_rows[:2]
        )
        assert after_rows[2]["display_page_chinese_stale"] is False
        assert after_rows[2]["display_page_chinese_confirmed"] is True
        assert after_rows[2]["chinese_review_required"] is False


def test_display_page_model_cache_is_isolated_and_invalidates_on_state_change():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 2)
        original_previews = session._display_page_previews

        with patch.object(
            session,
            "_display_page_previews",
            wraps=original_previews,
        ) as previews:
            first = session._display_page_model_data()
            second = session._display_page_model_data()
            assert previews.call_count == 1

            first["1"]["translated_subtitle"] = "不能污染缓存"
            assert second["1"]["translated_subtitle"] != "不能污染缓存"
            assert session._display_page_model_data()["1"][
                "translated_subtitle"
            ] != "不能污染缓存"
            assert previews.call_count == 1

            session.display_page_edits[0]["stale_chinese_draft"] = "状态已变化"
            session.display_page_edits[0]["chinese_stale_unconfirmed"] = True
            session._display_page_model_data()
            assert previews.call_count == 2

            evidence_path = (
                session.artifact_dir / "display-boundary-evidence.json"
            )
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["boundaries"]["1"]["pause_ms"] = 321
            _write_json(evidence_path, evidence)
            session._display_page_model_data()
            assert previews.call_count == 3


def test_bulk_confirmation_keeps_hard_boundary_blocking():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["boundaries"]["4"].update(
            {"hard_issues": [], "soft_issues": ["manual_short_page_review"], "pause_ms": 120}
        )
        _write_json(evidence_path, evidence)
        with patch.object(
            podcast_learning_video,
            "propose_article_manual_page_word_ranges",
            return_value=[(0, 3), (4, 7), (8, 16)],
        ):
            session.split_parent_into_display_pages("S0001", 3)

        rows = session.to_model_data()
        hard_row = rows["3"]
        hard_row["display_page_boundary_classification"] = "hard"
        hard_row["display_page_review_required"] = True
        with patch.object(session, "_display_page_model_data", return_value=rows), patch.object(
            session,
            "apply_display_page_model_data",
            return_value=True,
        ):
            result = session.confirm_all_nonblocking_display_page_reviews()

        assert result == {"changed": True, "chinese_count": 3, "boundary_count": 1}
        edits = {
            str(edit["display_page_id"]): edit for edit in session.display_page_edits
        }
        assert edits[str(rows["2"]["display_page_id"])][
            "boundary_review_acknowledged"
        ] is True
        assert edits[str(rows["3"]["display_page_id"])][
            "boundary_review_acknowledged"
        ] is False


def test_split_parent_undoes_once_and_rejects_when_no_legal_cut_exists():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        before_cue = dict(session.cues[0])
        before_pages = session.to_model_data()

        session.split_parent_into_display_pages("S0001", 4)
        assert len(session.to_model_data()) == 4
        assert session.undo() is True
        assert session.cues[0] == before_cue
        assert session.to_model_data() == before_pages

    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        before_cues = [dict(cue) for cue in session.cues]
        try:
            session.split_parent_into_display_pages("S0001", 4)
        except ManualFinalSubtitleEditError:
            pass
        else:
            raise AssertionError("a 900 ms parent cannot produce four legal pages")
        assert session.cues == before_cues
        assert session.display_page_boundary_overrides == {}


def test_manual_page_proposal_can_use_review_boundary_without_relaxing_strict_planning():
    text = (
        "Studying abroad no longer automatically translates into an ability "
        "to fit into a highly competitive domestic workplace."
    )
    words = text.split()
    timing_ms = (
        (40, 361),
        (421, 741),
        (821, 981),
        (1041, 1401),
        (1561, 2122),
        (2202, 2802),
        (2922, 3142),
        (3182, 3242),
        (3302, 3783),
        (3843, 3943),
        (4123, 4343),
        (4423, 4743),
        (4783, 4824),
        (4964, 5404),
        (5464, 6084),
        (6244, 6665),
        (6685, 7025),
    )
    pauses_ms = (60, 80, 60, 160, 80, 120, 40, 60, 60, 180, 80, 40, 140, 60, 160, 20)
    hard_issues = (
        ["dependency_phrase_entrance_split"],
        ["subject_finite_verb_split"],
        ["protected_syntax_cut", "subject_finite_verb_split"],
        ["subject_finite_verb_split"],
        ["dependency_phrase_entrance_split", "subject_finite_verb_split"],
        ["verb_preposition_complement_split"],
        ["preposition_object_split"],
        ["determiner_head_phrase_split", "protected_syntax_cut"],
        [],
        ["preposition_object_split", "protected_syntax_cut"],
        ["verb_preposition_complement_split"],
        ["preposition_object_split"],
        ["protected_syntax_cut"],
        ["dependency_phrase_entrance_split", "modifier_head_split", "protected_syntax_cut"],
        ["protected_syntax_cut"],
        ["protected_syntax_cut"],
    )
    first_word_id = 1129
    word_timing = [
        {
            "word_id": first_word_id + index,
            "surface": word,
            "start": start_ms / 1000.0,
            "end": end_ms / 1000.0,
        }
        for index, (word, (start_ms, end_ms)) in enumerate(zip(words, timing_ms))
    ]
    cue = podcast_learning_video.Cue(
        index=113,
        start=0.0,
        end=7.285,
        en=text,
        zh="出国留学不再自动等同于能够适应国内竞争激烈的工作环境。",
        speaker="manual",
        subtitle_id="S0114",
        word_timing=tuple(word_timing),
        display_boundary_evidence={
            str(first_word_id + index + 1): {
                "hard_issues": issues,
                "soft_issues": [],
                "pause_ms": pauses_ms[index],
            }
            for index, issues in enumerate(hard_issues)
        },
    )

    try:
        strict_ranges = podcast_learning_video.propose_article_manual_page_word_ranges(cue, 2)
    except podcast_learning_video.RenderStructuralOverflowError:
        strict_ranges = None
    expected_ranges = [(1129, 1137), (1138, 1145)]
    assert strict_ranges != expected_ranges

    ranges = podcast_learning_video.propose_article_manual_page_word_ranges(
        cue,
        2,
        allow_review_boundary=True,
    )

    assert ranges == expected_ranges
    assert " ".join(words[:9]).endswith("ability")
    assert " ".join(words[9:]).startswith("to fit")


def test_model_data_uses_validated_parent_chinese_instead_of_stale_render_plan():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["render_plans"][0]["chinese"] = "旧版中文"
        artifact["parents"][0]["aggregate_chinese"] = "中文一"
        _write_json(artifact_path, artifact)

        pages = list(session.to_model_data().values())[:2]

        assert [page["translated_subtitle"] for page in pages] == ["中", "文一"]
        assert "".join(page["translated_subtitle"] for page in pages) == session.cues[0][
            "translated_subtitle"
        ]


def test_legacy_parent_and_translations_conflict_fails_closed():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _, source_srt, manifest_path = _session_fixture(root)
        translations_path = manifest_path.parent / "output-artifacts" / "translations.json"
        translations = json.loads(translations_path.read_text(encoding="utf-8"))
        translations[0]["translated_text"] = "已经更新的新译文"
        _write_json(translations_path, translations)

        try:
            ManualFinalSubtitleSession.load_for_subtitle(
                source_srt,
                work_dir=root / "work",
                manifest_path=manifest_path,
            )
            assert False, "conflicting parent Chinese must not load by file priority"
        except ManualFinalSubtitleEditError as exc:
            assert "authoritative_parent_chinese_conflict" in str(exc)


def test_manual_save_publishes_one_parent_chinese_record_across_artifacts():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        rows = session.to_model_data(prefer_display_pages=False)
        rows["1"]["translated_subtitle"] = "人工确认后的中文一"
        assert session.apply_parent_model_data(rows) is True

        saved = session.save_to_source_folder()
        manifest = json.loads(Path(saved["manifest_path"]).read_text(encoding="utf-8"))
        authority_path = Path(manifest["parent_chinese_authority_path"])
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
        records = parent_chinese_records_by_id(authority)
        translations = json.loads(
            (Path(saved["artifact_dir"]) / "translations.json").read_text(
                encoding="utf-8"
            )
        )
        translated_by_id = {
            str(row["subtitle_id"]): row for row in translations
        }

        record = records["S0001"]
        assert record["chinese"] == "人工确认后的中文一"
        assert record["provenance"]["kind"] == "manual_override"
        assert translated_by_id["S0001"]["translated_text"] == record["chinese"]
        assert translated_by_id["S0001"]["parent_source_hash"] == record["source_hash"]
        assert translated_by_id["S0001"]["parent_record_hash"] == record["record_hash"]
        display_artifact = json.loads(
            (Path(saved["artifact_dir"]) / "display-page-translations.json").read_text(
                encoding="utf-8"
            )
        )
        validate_display_page_parent_records(display_artifact, records)

        reloaded = ManualFinalSubtitleSession.load_from_manifest(
            saved["manifest_path"]
        )
        assert reloaded.cues[0]["translated_subtitle"] == record["chinese"]


def test_page_chinese_source_parent_copy_allows_page_local_reordering():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["parents"][0]["source_parent_chinese"] = "中文一"
        artifact["parents"][0]["aggregate_chinese"] = "旧分页中文"
        artifact["parents"][0]["pages"][0]["zh"] = "旧"
        artifact["parents"][0]["pages"][1]["zh"] = "分页"
        _write_json(artifact_path, artifact)

        rows = session.to_model_data()

        assert [rows["1"]["translated_subtitle"], rows["2"]["translated_subtitle"]] == [
            "旧",
            "分页",
        ]
        assert rows["1"]["display_page_chinese_stale"] is False
        assert rows["2"]["display_page_chinese_stale"] is False


def test_legacy_page_chinese_aggregate_detects_stale_pages_without_source_parent_copy():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["parents"][0]["aggregate_chinese"] = "中文一"
        artifact["parents"][0]["pages"][0]["zh"] = "旧"
        artifact["parents"][0]["pages"][1]["zh"] = "分页"
        _write_json(artifact_path, artifact)

        rows = session.to_model_data()

        assert rows["1"]["display_page_chinese_stale"] is True
        assert rows["2"]["display_page_chinese_stale"] is True


def test_page_chinese_source_parent_copy_detects_true_parent_drift():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["parents"][0]["source_parent_chinese"] = "旧版父字幕"
        _write_json(artifact_path, artifact)

        rows = session.to_model_data()

        assert rows["1"]["display_page_chinese_stale"] is True
        assert rows["2"]["display_page_chinese_stale"] is True


def test_stale_single_page_uses_current_parent_chinese_without_confirmation():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        session.cues[1]["translated_subtitle"] = "新版中文二"

        rows = session.to_model_data()
        single_page = next(
            row for row in rows.values() if row.get("manual_cue_id") == "S0002"
        )

        assert single_page["translated_subtitle"] == "新版中文二"
        assert single_page["display_page_chinese_stale"] is False
        assert single_page["display_page_chinese_confirmed"] is True


def test_complete_manual_pages_replace_legacy_error_artifact_before_review():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        rows = session.to_model_data(prefer_display_pages=True)
        session.apply_display_page_model_data(rows, allow_incomplete_chinese=True)
        assert session.display_page_edits

        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact.update(
            {
                "status": "ERROR",
                "planner_version": "article-fixed-font-pages-v28",
                "errors": [
                    {
                        "code": "display_page_blueprint_invalid",
                        "parent_subtitle_id": "S0002",
                    }
                ],
            }
        )
        _write_json(artifact_path, artifact)
        session.cues[1]["chinese_review_required"] = True

        effective = session._effective_display_page_artifact()
        refreshed_rows = session.to_model_data(prefer_display_pages=True)
        single_page = next(
            row
            for row in refreshed_rows.values()
            if row.get("manual_cue_id") == "S0002"
        )

        assert effective["recovery_source"] == "complete_manual_page_edits"
        assert "display_page_blueprint_invalid" not in single_page[
            "display_page_issue_codes"
        ]
        assert single_page["display_page_review_required"] is False
        assert single_page["display_page_chinese_confirmed"] is True
        assert single_page["chinese_review_required"] is False


def test_stale_page_chinese_remains_visible_but_cannot_publish_until_confirmed():
    for artifact_status in ("PASS", "ERROR"):
        with tempfile.TemporaryDirectory() as temp_dir:
            session, _, _ = _session_fixture(Path(temp_dir))
            _write_display_page_preview_artifact(session)
            artifact_path = session.artifact_dir / "display-page-translations.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["status"] = artifact_status
            _write_json(artifact_path, artifact)
            session.cues[0]["translated_subtitle"] = "新版中文一"

            rows = session.to_model_data()

            assert [
                rows["1"]["translated_subtitle"],
                rows["2"]["translated_subtitle"],
            ] == ["中", "文一"]
            assert rows["1"]["display_page_chinese_stale"] is True
            assert rows["1"]["display_page_chinese_confirmed"] is False
            assert session.cues[0]["translated_subtitle"] == "新版中文一"

            session.apply_display_page_model_data(
                rows,
                allow_incomplete_chinese=True,
            )

            assert session.display_page_edits == []
            assert session.cues[0]["translated_subtitle"] == "新版中文一"

            rows["1"]["display_page_chinese_confirmed"] = True
            session.apply_display_page_model_data(
                rows,
                allow_incomplete_chinese=True,
            )

            assert session.cues[0]["translated_subtitle"] == "新版中文一"
            page_edits = {
                item["display_page_id"]: item
                for item in session.display_page_edits
            }
            assert page_edits["S0001.P01"]["chinese"] == "中"
            assert page_edits["S0001.P02"]["chinese"] == ""
            assert page_edits["S0001.P02"]["stale_chinese_draft"] == "文一"
            try:
                session._display_page_edit_translation_response(
                    artifact["parents"],
                    artifact["render_plans"],
                )
            except ManualFinalSubtitleEditError as exc:
                assert "manual_page_translation_required" in str(exc)
            else:
                raise AssertionError(
                    "unconfirmed stale page Chinese must block publication"
                )

            refreshed = session.to_model_data()
            assert refreshed["2"]["translated_subtitle"] == "文一"
            assert refreshed["2"]["display_page_chinese_stale"] is True


def test_reallocated_stale_page_chinese_can_become_authoritative():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["status"] = "ERROR"
        _write_json(artifact_path, artifact)
        session.cues[0]["translated_subtitle"] = "新版中文一"
        rows = session.to_model_data()
        rows["1"]["translated_subtitle"] = "新版中"
        rows["1"]["display_page_chinese_confirmed"] = True
        rows["2"]["translated_subtitle"] = "文一"
        rows["2"]["display_page_chinese_confirmed"] = True

        session.apply_display_page_model_data(rows, allow_incomplete_chinese=True)

        assert session.cues[0]["translated_subtitle"] == "新版中文一"
        response = session._display_page_edit_translation_response(
            artifact["parents"],
            artifact["render_plans"],
        )
        assert response is not None
        assert response["pages"][:2] == [
            {"display_page_id": "S0001.P01", "zh": "新版中"},
            {"display_page_id": "S0001.P02", "zh": "文一"},
        ]


def test_legacy_blank_page_edits_recover_visible_stale_chinese_drafts():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        session.cues[0]["translated_subtitle"] = "新版中文一"
        source_rows = session.to_model_data()
        session.display_page_edits = [
            {
                "display_page_id": str(source_rows[key]["display_page_id"]),
                "parent_subtitle_id": str(source_rows[key]["manual_cue_id"]),
                "word_start": int(source_rows[key]["word_start"]),
                "word_end": int(source_rows[key]["word_end"]),
                "english": str(source_rows[key]["original_subtitle"]),
                "chinese": "",
            }
            for key in ("1", "2")
        ]

        recovered_rows = session.to_model_data()

        assert [
            recovered_rows["1"]["translated_subtitle"],
            recovered_rows["2"]["translated_subtitle"],
        ] == ["中", "文一"]
        assert all(
            recovered_rows[key]["display_page_chinese_stale"] is True
            and recovered_rows[key]["display_page_chinese_confirmed"] is False
            for key in ("1", "2")
        )
        assert session.cues[0]["translated_subtitle"] == "新版中文一"
        assert all(
            not str(item.get("chinese") or "")
            for item in session.display_page_edits
        )


def test_blank_intermediate_page_edits_cannot_hide_recovered_stale_drafts():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        source_rows = session.to_model_data()
        session.display_page_edits = []
        session.recovered_stale_page_drafts = {}
        for key in ("1", "2"):
            row = source_rows[key]
            page_id = str(row["display_page_id"])
            session.display_page_edits.append(
                {
                    "display_page_id": page_id,
                    "parent_subtitle_id": str(row["manual_cue_id"]),
                    "word_start": int(row["word_start"]),
                    "word_end": int(row["word_end"]),
                    "english": str(row["original_subtitle"]),
                    "chinese": "",
                }
            )
            session.recovered_stale_page_drafts[page_id] = {
                "display_page_id": page_id,
                "parent_subtitle_id": str(row["manual_cue_id"]),
                "word_start": int(row["word_start"]),
                "word_end": int(row["word_end"]),
                "start_ms": int(row["start_time"]),
                "end_ms": int(row["end_time"]),
                "english": str(row["original_subtitle"]),
                "chinese": str(row["translated_subtitle"]),
            }

        recovered_rows = session.to_model_data()

        assert [
            recovered_rows["1"]["translated_subtitle"],
            recovered_rows["2"]["translated_subtitle"],
        ] == ["中", "文一"]
        assert all(
            recovered_rows[key]["display_page_chinese_stale"] is True
            and recovered_rows[key]["display_page_chinese_confirmed"] is False
            for key in ("1", "2")
        )
        assert session.cues[0]["translated_subtitle"] == "中文一"
        assert all(
            not str(item.get("chinese") or "")
            for item in session.display_page_edits
        )


def test_structural_rebuild_preserves_unconfirmed_stale_page_ownership():
    row = {
        "display_page_id": "S0001.P01",
        "manual_cue_id": "S0001",
        "word_start": 0,
        "word_end": 4,
        "original_subtitle": "Right. It means our mental model",
        "translated_subtitle": "这是一条待确认旧稿",
        "display_page_chinese_stale": True,
        "display_page_chinese_confirmed": False,
    }

    stale_edit = ManualFinalSubtitleSession._unchanged_display_page_edit_from_model_row(
        row
    )

    assert stale_edit["chinese"] == ""
    assert stale_edit["stale_chinese_draft"] == "这是一条待确认旧稿"
    assert stale_edit["chinese_stale_unconfirmed"] is True

    row["display_page_chinese_confirmed"] = True
    confirmed_edit = (
        ManualFinalSubtitleSession._unchanged_display_page_edit_from_model_row(row)
    )
    assert confirmed_edit["chinese"] == "这是一条待确认旧稿"
    assert "stale_chinese_draft" not in confirmed_edit
    assert "chinese_stale_unconfirmed" not in confirmed_edit


def test_manifest_lookup_uses_hash_and_prefers_manual_package_for_renamed_copy():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        manual_dir = root / "work" / "manual-package"
        ordinary_dir = root / "work" / "ordinary-checkpoint"
        external_dir = root / "external"
        manual_dir.mkdir(parents=True)
        ordinary_dir.mkdir(parents=True)
        external_dir.mkdir()
        manual_subtitle = manual_dir / "人工终稿字幕.srt"
        ordinary_subtitle = ordinary_dir / "stable-final-original-top.srt"
        copied_subtitle = external_dir / "renamed-copy.srt"
        _write_srt(manual_subtitle)
        shutil.copyfile(manual_subtitle, ordinary_subtitle)
        shutil.copyfile(manual_subtitle, copied_subtitle)
        subtitle_hash = file_sha256(copied_subtitle)

        manual_manifest = manual_dir / "stable-final-manifest.json"
        _write_json(
            manual_manifest,
            {
                "schema_version": 2,
                "paths": {"original_top_srt": str(manual_subtitle)},
                "paths_sha256": {"original_top_srt": subtitle_hash},
                "manual_final_override": {
                    "schema_version": 2,
                    "subtitle_path": str(manual_subtitle),
                    "subtitle_sha256": subtitle_hash,
                },
            },
        )
        ordinary_manifest = ordinary_dir / "stable-final-manifest.json"
        _write_json(
            ordinary_manifest,
            {
                "schema_version": 2,
                "paths": {"original_top_srt": str(ordinary_subtitle)},
                "paths_sha256": {"original_top_srt": subtitle_hash},
            },
        )
        os.utime(manual_manifest, (1, 1))
        os.utime(ordinary_manifest, (2, 2))

        resolved = ManualFinalSubtitleSession.find_manifest_for_subtitle(
            copied_subtitle,
            work_dir=root / "work",
        )

        assert resolved == manual_manifest
        assert ordinary_manifest.stat().st_mtime > manual_manifest.stat().st_mtime


def test_original_top_import_restarts_while_manual_final_import_continues():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _, source_srt, manifest_path = _session_fixture(root)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"test-audio-placeholder")
        result_dir = media_result_dir(source_media)
        result_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = result_dir / f"{source_media.stem}-原文在上双语字幕.srt"
        shutil.copyfile(source_srt, baseline_path)
        baseline_bytes = baseline_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_subtitle_paths"] = {
            "bilingual_original_top_srt": str(baseline_path)
        }
        manifest["source_subtitle_paths_sha256"] = {
            "bilingual_original_top_srt": file_sha256(baseline_path)
        }
        _write_json(manifest_path, manifest)
        session = ManualFinalSubtitleSession.load_for_subtitle(
            baseline_path,
            work_dir=root / "work",
        )
        session.move_suffix_to_next(0, 2)

        saved = session.save_to_source_folder(source_media_path=source_media)

        assert baseline_path.read_bytes() == baseline_bytes
        restarted = ManualFinalSubtitleSession.load_for_subtitle(
            baseline_path,
            work_dir=root / "work",
        )
        continued = ManualFinalSubtitleSession.load_for_subtitle(
            Path(saved["subtitle_path"]),
            work_dir=root / "work",
        )
        assert restarted.manifest_path == manifest_path
        assert restarted.history == []
        assert restarted.cues[1]["original_subtitle"] == "out of date."
        assert len(continued.history) == 1
        assert continued.cues[1]["original_subtitle"] == (
            "just completely out of date."
        )


def test_stale_actual_page_import_opens_current_parent_package_without_reusing_old_pages():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, _, _ = _splittable_parent_session(root)
        source_media = root / "source" / "节目.m4a"
        source_media.write_bytes(b"test-audio-placeholder")

        session.split_parent_into_display_pages("S0001", 3)
        first_rows = session.to_model_data()
        for row, chinese in zip(first_rows.values(), ("甲，", "乙，", "丙")):
            row["translated_subtitle"] = chinese
            row["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(first_rows)
        expected_page_path, expected_map_path = _write_immutable_source_page_snapshot(
            session,
            source_media,
        )
        first_save = session.save_to_source_folder(source_media_path=source_media)
        stale_page_path = Path(first_save["source_display_page_srt_path"])
        stale_map_path = Path(first_save["source_display_page_map_path"])
        assert stale_page_path == expected_page_path
        assert stale_map_path == expected_map_path
        stale_page_bytes = stale_page_path.read_bytes()
        stale_map_bytes = stale_map_path.read_bytes()

        session.split_parent_into_display_pages("S0001", 2)
        blocked_save = session.save_to_source_folder(source_media_path=source_media)
        assert blocked_save["render_blocked"] is True
        assert blocked_save["render_block_reason"] == "manual_page_translation_required"
        assert stale_page_path.read_bytes() == stale_page_bytes
        assert stale_map_path.read_bytes() == stale_map_bytes

        recovered = ManualFinalSubtitleSession.load_for_subtitle(
            stale_page_path,
            work_dir=root / "work",
        )

        assert recovered.manifest_path == Path(blocked_save["manifest_path"])
        assert recovered.loaded_subtitle_path == stale_page_path
        assert "已被后续保存淘汰" in recovered.import_notice
        assert recovered.display_page_boundary_overrides == {"S0001": [8]}
        recovered_pages = list(recovered.to_model_data().values())
        assert [page["display_page_id"] for page in recovered_pages] == [
            "S0001.P01",
            "S0001.P02",
        ]
        assert all(page["translated_subtitle"] for page in recovered_pages)
        assert "".join(
            page["translated_subtitle"] for page in recovered_pages
        ) == recovered.cues[0]["translated_subtitle"]
        assert all(
            page["display_page_chinese_stale"] is True
            and page["display_page_chinese_confirmed"] is False
            for page in recovered_pages
        )
        assert " ".join(
            page["original_subtitle"] for page in recovered_pages
        ) == recovered.cues[0]["original_subtitle"]

        stale_page_path.write_bytes(stale_page_bytes + b"\n")
        try:
            ManualFinalSubtitleSession.load_for_subtitle(
                stale_page_path,
                work_dir=root / "work",
            )
        except ManualFinalSubtitleEditError as exc:
            assert "分页映射不一致" in str(exc)
        else:
            raise AssertionError("a changed stale page file must not redirect to a current package")


def test_stale_actual_page_import_recovers_only_identity_matched_chinese_as_draft():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, _, _ = _splittable_parent_session(root)
        source_media = root / "source" / "节目.m4a"
        source_media.write_bytes(b"test-audio-placeholder")
        session.split_parent_into_display_pages("S0001", 3)
        first_rows = session.to_model_data()
        expected_chinese = ("甲，", "乙，", "丙")
        for row, chinese in zip(first_rows.values(), expected_chinese):
            row["translated_subtitle"] = chinese
            row["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(first_rows)
        _write_immutable_source_page_snapshot(session, source_media)
        first_save = session.save_to_source_folder(source_media_path=source_media)
        stale_page_path = Path(first_save["source_display_page_srt_path"])
        stale_page_hash = file_sha256(stale_page_path)

        current = ManualFinalSubtitleSession.load_from_manifest(
            Path(first_save["manifest_path"])
        )
        current.cues[0]["translated_subtitle"] = "新版父字幕中文"
        for edit in current.display_page_edits:
            edit["chinese"] = ""
        blocked_save = current.save_to_source_folder(
            source_media_path=source_media
        )
        assert blocked_save["render_blocked"] is True
        assert file_sha256(stale_page_path) == stale_page_hash

        recovered = ManualFinalSubtitleSession.load_for_subtitle(
            stale_page_path,
            work_dir=root / "work",
        )
        recovered_rows = list(recovered.to_model_data().values())

        assert recovered.manifest_path == Path(blocked_save["manifest_path"])
        assert [row["translated_subtitle"] for row in recovered_rows] == list(
            expected_chinese
        )
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in recovered_rows
        )
        assert recovered.cues[0]["translated_subtitle"] == "新版父字幕中文"
        assert all(
            not str(item.get("chinese") or "")
            for item in recovered.display_page_edits
        )
        assert file_sha256(stale_page_path) == stale_page_hash

        zero_confirm_save = recovered.save_to_source_folder(
            source_media_path=source_media
        )
        assert zero_confirm_save["render_blocked"] is True
        zero_confirm_reload = ManualFinalSubtitleSession.load_from_manifest(
            Path(zero_confirm_save["manifest_path"])
        )
        zero_confirm_rows = list(zero_confirm_reload.to_model_data().values())
        assert [row["translated_subtitle"] for row in zero_confirm_rows] == list(
            expected_chinese
        )
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in zero_confirm_rows
        )
        assert zero_confirm_reload.cues[0]["translated_subtitle"] == (
            "新版父字幕中文"
        )

        partial_rows = zero_confirm_reload.to_model_data()
        partial_rows["1"]["display_page_chinese_confirmed"] = True
        zero_confirm_reload.apply_display_page_model_data(
            partial_rows,
            allow_incomplete_chinese=True,
        )
        partial_save = zero_confirm_reload.save_to_source_folder(
            source_media_path=source_media
        )
        assert partial_save["render_blocked"] is True
        partial_reload = ManualFinalSubtitleSession.load_from_manifest(
            Path(partial_save["manifest_path"])
        )
        partial_reloaded_rows = list(partial_reload.to_model_data().values())
        assert [
            row["translated_subtitle"] for row in partial_reloaded_rows
        ] == list(expected_chinese)
        assert partial_reloaded_rows[0]["display_page_chinese_confirmed"] is True
        assert partial_reloaded_rows[0]["display_page_chinese_stale"] is False
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in partial_reloaded_rows[1:]
        )
        assert partial_reload.cues[0]["translated_subtitle"] == "新版父字幕中文"


def test_identity_matched_recovered_drafts_build_manual_draft_without_publication():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, _, _ = _splittable_parent_session(root)
        source_media = root / "source" / "episode.m4a"
        source_media.write_bytes(b"test-audio-placeholder")

        session.split_parent_into_display_pages("S0001", 3)
        first_rows = session.to_model_data()
        expected_chinese = ("甲，", "乙，", "丙")
        for row, chinese in zip(first_rows.values(), expected_chinese):
            row["translated_subtitle"] = chinese
            row["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(first_rows)
        _write_immutable_source_page_snapshot(session, source_media)
        first_save = session.save_to_source_folder(source_media_path=source_media)
        stale_page_path = Path(first_save["source_display_page_srt_path"])

        current = ManualFinalSubtitleSession.load_from_manifest(
            Path(first_save["manifest_path"])
        )
        for edit in current.display_page_edits:
            edit["chinese"] = ""
        blocked_save = current.save_to_source_folder(source_media_path=source_media)
        assert blocked_save["render_blocked"] is True
        assert blocked_save["render_block_reason"] == "manual_page_translation_required"

        recovered = ManualFinalSubtitleSession.load_for_subtitle(
            stale_page_path,
            work_dir=root / "work",
        )
        visible_rows = list(recovered.to_model_data().values())
        expected_pages = [
            (
                str(row["display_page_id"]),
                str(row["manual_cue_id"]),
                int(row["word_start"]),
                int(row["word_end"]),
                int(row["start_time"]),
                int(row["end_time"]),
                str(row["original_subtitle"]),
                str(row["translated_subtitle"]),
            )
            for row in visible_rows
        ]
        assert [page[-1] for page in expected_pages] == list(expected_chinese)
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in visible_rows
        )
        before_cues = copy.deepcopy(recovered.cues)
        before_ledger = copy.deepcopy(recovered.word_ledger)

        saved = recovered.save_to_source_folder(source_media_path=source_media)

        assert saved["render_blocked"] is True
        assert saved["render_block_reason"] == "manual_page_translation_required"
        assert saved["manual_draft_ready"] is True
        manifest_path = Path(saved["manifest_path"])
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        override = manifest["manual_final_override"]
        draft_path = Path(saved["manual_draft_page_plan_path"])
        draft_sha256 = str(saved["manual_draft_page_plan_sha256"])
        assert draft_path.is_file()
        assert manifest["manual_draft_page_plan_path"] == str(draft_path)
        assert override["manual_draft_page_plan_path"] == str(draft_path)
        assert manifest["manual_draft_page_plan_sha256"] == draft_sha256
        assert override["manual_draft_page_plan_sha256"] == draft_sha256
        assert file_sha256(draft_path) == draft_sha256
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        assert len(draft["render_plans"]) == 1
        assert len(draft["render_plans"][0]["pages"]) == 3
        draft_pages = [
            (
                str(page["display_page_id"]),
                "S0001",
                int(page["word_start"]),
                int(page["word_end"]),
                int(page["start_ms"]),
                int(page["end_ms"]),
                str(page["english"]),
                str(page["chinese"]),
            )
            for page in draft["render_plans"][0]["pages"]
        ]
        assert draft_pages == expected_pages
        assert "".join(page[-1] for page in draft_pages) == recovered.cues[0][
            "translated_subtitle"
        ]
        assert recovered.cues == before_cues
        assert recovered.word_ledger == before_ledger


def test_loader_rejects_incomplete_or_synthetic_fixed_id_checkpoint():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _, source_srt, manifest_path = _session_fixture(root)
        artifact_dir = manifest_path.parent / "output-artifacts"
        spans_path = artifact_dir / "subtitle-spans.json"
        spans = json.loads(spans_path.read_text(encoding="utf-8"))
        source_srt.write_text(
            "1\n00:00:00,000 --> 00:00:00,900\n"
            "Right. It means our mental model is just completely\n中文一\n",
            encoding="utf-8-sig",
        )
        _write_json(spans_path, spans[:1])

        try:
            ManualFinalSubtitleSession.load_for_subtitle(
                source_srt,
                work_dir=root / "work",
                manifest_path=manifest_path,
            )
        except ManualFinalSubtitleEditError as exc:
            assert "完整词级账本" in str(exc)
        else:
            raise AssertionError("a truncated checkpoint must not load as complete")

        _write_srt(source_srt)
        spans[0]["subtitle_id"] = ""
        _write_json(spans_path, spans)
        try:
            ManualFinalSubtitleSession.load_for_subtitle(
                source_srt,
                work_dir=root / "work",
                manifest_path=manifest_path,
            )
        except ManualFinalSubtitleEditError as exc:
            assert "固定字幕 ID" in str(exc)
        else:
            raise AssertionError("a checkpoint must not synthesize missing fixed IDs")


def test_move_prefix_and_undo_restore_exact_prior_boundary():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        before = session.to_model_data()

        session.move_prefix_to_previous(1, 2)
        assert session.cues[0]["original_subtitle"].endswith("out of")
        assert session.cues[1]["original_subtitle"] == "date."
        assert session.undo() is True

        assert session.to_model_data() == before


def test_undo_redo_round_trip_and_new_edit_truncates_redo_branch():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        before = session.state_fingerprint()
        session.move_suffix_to_next(0, 2)
        after = session.state_fingerprint()
        assert after != before
        assert session.undo() is True
        assert session.state_fingerprint() == before
        assert len(session.redo_history) == 1
        assert session.redo() is True
        assert session.state_fingerprint() == after
        assert not session.redo_history

        assert session.undo() is True
        session.move_suffix_to_next(0, 1)
        assert not session.redo_history
        assert session.redo() is False


def test_recovery_draft_round_trip_is_atomic_and_manifest_bound():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, manifest_path = _session_fixture(root)
        base = session.state_fingerprint()
        session.move_suffix_to_next(0, 2)
        edited = session.state_fingerprint()
        draft_path = session.save_recovery_draft()
        assert draft_path.is_file()

        restarted = ManualFinalSubtitleSession.load_for_subtitle(
            source_srt,
            work_dir=root / "work",
            manifest_path=manifest_path,
        )
        assert restarted.state_fingerprint() == base
        assert restarted.restore_recovery_draft() is True
        assert restarted.state_fingerprint() == edited
        assert restarted.import_notice.startswith("已恢复")
        assert restarted.undo() is True
        assert restarted.state_fingerprint() == base
        assert restarted.redo() is True
        assert restarted.state_fingerprint() == edited

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["unrelated_change"] = True
        _write_json(manifest_path, manifest)
        changed_base = ManualFinalSubtitleSession.load_for_subtitle(
            source_srt,
            work_dir=root / "work",
            manifest_path=manifest_path,
        )
        assert changed_base.restore_recovery_draft() is False


def test_recent_editable_manifest_discovery_finds_checkpoint_and_draft():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, _, manifest_path = _session_fixture(root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            {
                "attempt_id": "attempt-1",
                "stable_run_id": "run-1",
                "created_at": "2026-08-23T12:00:00",
                "editable_checkpoint": True,
                "render_blocked": True,
                "subtitle_count": 2,
            }
        )
        _write_json(manifest_path, manifest)
        session = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        session.move_suffix_to_next(0, 1)
        draft_path = session.save_recovery_draft()

        broken = root / "work" / "broken" / "stable-final-manifest.json"
        broken.parent.mkdir(parents=True)
        _write_json(broken, {"paths": {"original_top_srt": "missing.srt"}})

        records = ManualFinalSubtitleSession.discover_recent_editable_manifests(
            root / "work"
        )

        assert len(records) == 1
        assert Path(records[0]["manifest_path"]) == manifest_path.resolve()
        assert records[0]["state"] == "未保存草稿"
        assert records[0]["has_recovery_draft"] is True
        assert records[0]["subtitle_count"] == 2
        assert draft_path.is_file()


def test_merge_only_combines_adjacent_continuous_word_ranges():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))

        session.merge_adjacent(0, 1)

        assert len(session.cues) == 1
        merged = session.cues[0]
        assert merged["original_subtitle"] == "Right. It means our mental model is just completely out of date."
        assert merged["translated_subtitle"] == "中文一中文二"
        assert (merged["start_time"], merged["end_time"]) == (0, 1200)
        assert merged["source_subtitle_ids"] == ["S0001", "S0002"]


def test_manual_english_surface_edit_preserves_word_identity_time_and_reload():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        before_ledger = copy.deepcopy(session.word_ledger)
        rows = session.to_model_data(prefer_display_pages=False)
        rows["2"]["original_subtitle"] = "out of only as."

        assert session.apply_parent_model_data(rows) is True

        assert len(session.word_ledger) == len(before_ledger)
        assert [word["word_id"] for word in session.word_ledger] == [
            word["word_id"] for word in before_ledger
        ]
        assert [
            (word["start_ms"], word["end_ms"]) for word in session.word_ledger
        ] == [
            (word["start_ms"], word["end_ms"]) for word in before_ledger
        ]
        assert session.word_ledger[11]["surface"] == "only as."
        assert session.cues[1]["original_subtitle"] == "out of only as."
        assert session.history[-1]["operation"] == "edit_english_surface"
        assert "before_word_ledger" not in session.history[-1]
        assert [
            item["word_id"]
            for item in session.history[-1]["before_word_ledger_items"]
        ] == [11]

        edited_fingerprint = session.state_fingerprint()
        assert session.undo() is True
        assert session.word_ledger == before_ledger
        assert session.redo() is True
        assert session.state_fingerprint() == edited_fingerprint

        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"test-audio-placeholder")
        paths = session.save_to_source_folder(source_media_path=source_media)
        manual_srt = Path(paths["subtitle_path"])
        reloaded = ManualFinalSubtitleSession.load_for_subtitle(
            manual_srt,
            work_dir=root / "work",
        )

        assert reloaded.word_ledger[11]["surface"] == "only as."
        assert reloaded.cues[1]["original_subtitle"] == "out of only as."
        rendered_cues = parse_srt(manual_srt)
        assert attach_article_word_timing(rendered_cues, manual_srt) is True
        assert rendered_cues[1].en == "out of only as."
        assert rendered_cues[1].word_timing[-1]["word_id"] == 11
        assert rendered_cues[1].word_timing[-1]["surface"] == "only as."


def test_manual_english_surface_edit_rejects_changes_across_multiple_word_ids():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        rows = session.to_model_data(prefer_display_pages=False)
        rows["2"]["original_subtitle"] = "entirely different sentence."

        try:
            session.apply_parent_model_data(rows)
        except ManualFinalSubtitleEditError as exc:
            assert "只能修改一个冻结词" in str(exc)
        else:
            raise AssertionError("multi-word English rewrites must be rejected")


def test_manual_english_surface_span_preserves_raw_ledger_and_renderer_provenance():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        before_ledger = copy.deepcopy(session.word_ledger)

        assert session.replace_english_surface_span(
            parent_subtitle_id="S0002",
            word_start=9,
            word_end=10,
            replacement_text="outof",
        ) is True

        assert session.cues[1]["original_subtitle"] == "outof date."
        assert session.word_ledger == before_ledger
        assert session.english_surface_overrides == [
            {
                "word_start": 9,
                "word_end": 10,
                "expected_surfaces": ["out", "of"],
                "display_surface": "outof",
                "parent_subtitle_id": "S0002",
            }
        ]
        assert session.history[-1]["operation"] == "edit_english_surface_span"

        changed = session.state_fingerprint()
        assert session.undo() is True
        assert session.word_ledger == before_ledger
        assert session.cues[1]["original_subtitle"] == "out of date."
        assert session.redo() is True
        assert session.state_fingerprint() == changed

        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"test-audio-placeholder")
        paths = session.save_to_source_folder(source_media_path=source_media)
        manual_srt = Path(paths["subtitle_path"])
        reloaded = ManualFinalSubtitleSession.load_for_subtitle(
            manual_srt, work_dir=root / "work"
        )
        assert reloaded.english_surface_overrides == session.english_surface_overrides
        assert reloaded.word_ledger == before_ledger

        rendered_cues = parse_srt(manual_srt)
        assert attach_article_word_timing(rendered_cues, manual_srt) is True
        assert rendered_cues[1].en == "outof date."
        assert [span["surface"] for span in rendered_cues[1].display_word_spans] == [
            "outof", "date."
        ]
        assert [
            (span["word_start"], span["word_end"])
            for span in rendered_cues[1].display_word_spans
        ] == [(9, 10), (11, 11)]


def test_manual_english_surface_span_survives_single_word_edit_and_parent_merge():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        assert session.replace_english_surface_span(
            parent_subtitle_id="S0002",
            word_start=9,
            word_end=10,
            replacement_text="outof",
        ) is True

        rows = session.to_model_data(prefer_display_pages=False)
        rows["1"]["original_subtitle"] = (
            "Right. It means our mental model is just entirely"
        )
        assert session.apply_parent_model_data(rows) is True
        assert session.cues[1]["original_subtitle"] == "outof date."

        before_merge = session.state_fingerprint()
        session.merge_adjacent(0, 1)
        assert session.cues[0]["original_subtitle"].endswith("outof date.")
        assert session.english_surface_overrides[0]["parent_subtitle_id"] == "S0001"

        assert session.undo() is True
        assert session.state_fingerprint() == before_merge
        assert session.english_surface_overrides[0]["parent_subtitle_id"] == "S0002"


def test_tail_trim_preserves_or_removes_complete_english_surface_spans_atomically():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"audio-placeholder")
        session.source_media_path = source_media.resolve()
        assert session.replace_english_surface_span(
            parent_subtitle_id="S0002",
            word_start=9,
            word_end=10,
            replacement_text="outof",
        ) is True
        before = session.state_fingerprint()

        try:
            session._apply_tail_trim_decision(
                session._preview_tail_trim_at_word(10)
            )
        except ManualFinalSubtitleEditError as exc:
            assert "人工合并" in str(exc)
        else:
            raise AssertionError("tail trim must not split a display surface span")
        assert session.state_fingerprint() == before

        session._apply_tail_trim_decision(session._preview_tail_trim_at_word(11))
        assert session.cues[-1]["original_subtitle"] == "outof"
        assert session.english_surface_overrides[0]["word_end"] == 10
        assert session.undo() is True
        assert session.state_fingerprint() == before

        session._apply_tail_trim_decision(session._preview_tail_trim_at_word(9))
        assert session.english_surface_overrides == []
        assert session.undo() is True
        assert session.state_fingerprint() == before


def test_actual_page_english_surface_edit_updates_parent_without_moving_page_range():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        rows = session.to_model_data(prefer_display_pages=True)
        second_parent_key = next(
            key
            for key, row in rows.items()
            if row.get("manual_cue_id") == "S0002"
        )
        before_range = (
            rows[second_parent_key]["word_start"],
            rows[second_parent_key]["word_end"],
            rows[second_parent_key]["start_time"],
            rows[second_parent_key]["end_time"],
        )
        rows[second_parent_key]["original_subtitle"] = "out of only as."

        assert session.apply_display_page_model_data(rows) is True

        refreshed = session.to_model_data(prefer_display_pages=True)
        refreshed_row = next(
            row
            for row in refreshed.values()
            if row.get("manual_cue_id") == "S0002"
        )
        assert refreshed_row["original_subtitle"] == "out of only as."
        assert (
            refreshed_row["word_start"],
            refreshed_row["word_end"],
            refreshed_row["start_time"],
            refreshed_row["end_time"],
        ) == before_range
        assert session.cues[1]["chinese_review_required"] is True


def test_suppress_single_cue_hides_srt_but_keeps_full_timeline_and_audio():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"test-audio-placeholder")
        before_ledger = copy.deepcopy(session.word_ledger)

        result = session.set_cue_display_suppressed("S0002", True)

        assert result["changed"] is True
        assert session.cues[1]["display_suppressed"] is True
        assert session.word_ledger == before_ledger
        paths = session.save_to_source_folder(source_media_path=source_media)
        manual_srt = Path(paths["subtitle_path"])
        rendered_cues = parse_srt(manual_srt)
        timeline = json.loads(
            Path(paths["artifact_dir"], "final-cue-timeline.json").read_text(
                encoding="utf-8"
            )
        )

        assert len(rendered_cues) == 1
        assert "out of date." not in manual_srt.read_text(encoding="utf-8-sig")
        assert [record["subtitle_id"] for record in timeline["records"]] == [
            "S0001",
            "S0002",
        ]
        assert timeline["records"][1]["display_suppressed"] is True
        assert attach_article_word_timing(rendered_cues, manual_srt) is True
        assert Path(paths["source_media_path"]) == source_media.resolve()

        reloaded = ManualFinalSubtitleSession.load_for_subtitle(
            manual_srt,
            work_dir=root / "work",
        )
        assert reloaded.cues[1]["display_suppressed"] is True
        assert reloaded.set_cue_display_suppressed("S0002", False)["changed"] is True
        assert reloaded.cues[1]["display_suppressed"] is False


def test_hide_and_mute_cue_is_parent_scoped_and_can_precede_tail_trim():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"test-audio-placeholder")
        session.source_media_path = source_media.resolve()
        before_ledger = copy.deepcopy(session.word_ledger)

        result = session.set_cue_hidden_and_media_muted("S0002", True)

        assert result == {
            "changed": True,
            "subtitle_id": "S0002",
            "hidden_and_muted": True,
        }
        assert session.cues[1]["display_suppressed"] is True
        assert session.cues[1]["media_muted"] is True
        assert session.word_ledger == before_ledger
        rows = session.to_model_data(prefer_display_pages=True)
        muted_row = next(
            row for row in rows.values() if row.get("manual_cue_id") == "S0002"
        )
        assert muted_row["display_suppressed"] is True
        assert muted_row["media_muted"] is True

        assert session.can_undo_for_parent("S0002") is False
        try:
            session.undo_for_parent("S0002")
        except ManualFinalSubtitleEditError as exc:
            assert "整体撤销" in str(exc) or "音频" in str(exc)
        else:
            raise AssertionError("media mute must use document-scoped undo")
        assert session.undo() is True
        assert not session.cues[1].get("display_suppressed")
        assert not session.cues[1].get("media_muted")
        assert session.redo() is True
        assert session.cues[1]["display_suppressed"] is True
        assert session.cues[1]["media_muted"] is True

        assert session.set_cue_hidden_and_media_muted("S0002", False)[
            "changed"
        ] is True
        assert session.set_cue_hidden_and_media_muted("S0001", True)[
            "changed"
        ] is True
        trim = session.trim_tail_from_cue(1)
        assert trim["cut_ms"] > 0
        assert session.cues[0]["media_muted"] is True


def test_hide_and_mute_save_round_trip_binds_derived_audio_and_timeline():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"original-audio-placeholder")
        source_hash = file_sha256(source_media)
        before_ledger = copy.deepcopy(session.word_ledger)
        session.source_media_path = source_media.resolve()
        session.set_cue_hidden_and_media_muted("S0002", True)

        def materialize_fixture_audio(source_path, output_path, intervals):
            assert source_path.resolve() == source_media.resolve()
            assert intervals == [
                {
                    "subtitle_id": "S0002",
                    "start_ms": 900,
                    "end_ms": 1600,
                }
            ]
            shutil.copyfile(source_path, output_path)

        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "_materialize_media_mute_audio",
            side_effect=materialize_fixture_audio,
        ):
            paths = session.save_to_source_folder(source_media_path=source_media)

        manifest_path = Path(paths["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        derived_media = Path(paths["source_media_path"])
        derivation = manifest["media_derivation"]
        assert derived_media.is_file()
        assert derived_media.resolve() != source_media.resolve()
        assert derivation["mute_intervals"] == [
            {"subtitle_id": "S0002", "start_ms": 900, "end_ms": 1600}
        ]
        assert derivation["source_media_sha256"] == source_hash
        assert derivation["derived_media_sha256"] == file_sha256(derived_media)
        assert derivation["decision_hash"]
        assert not manifest.get("media_mute")
        assert manifest["manual_final_override"]["media_derivation"] == derivation
        assert file_sha256(source_media) == source_hash
        assert session.word_ledger == before_ledger
        assert [
            (cue["start_time"], cue["end_time"]) for cue in session.cues
        ] == [(0, 900), (900, 1600)]

        reloaded = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        assert reloaded.cues[1]["display_suppressed"] is True
        assert reloaded.cues[1]["media_muted"] is True
        assert reloaded.media_derivation == derivation
        resolved_media, resolved_manifest = resolve_synthesis_package_inputs(
            manifest_path,
            str(source_media),
        )
        assert Path(resolved_media).resolve() == derived_media.resolve()
        assert Path(resolved_manifest) == manifest_path
        assert reloaded.set_cue_hidden_and_media_muted("S0002", False)[
            "changed"
        ] is True
        assert reloaded.source_media_path.resolve() == source_media.resolve()
        assert reloaded.media_derivation == {}
        assert reloaded.undo() is True
        assert reloaded.cues[1]["media_muted"] is True
        assert reloaded.media_derivation == derivation
        assert reloaded.source_media_path.resolve() == derived_media.resolve()
        assert reloaded.redo() is True
        assert not reloaded.cues[1].get("media_muted")
        assert reloaded.media_derivation == {}
        assert reloaded.source_media_path.resolve() == source_media.resolve()

        derived_media.write_bytes(b"tampered")
        try:
            resolve_synthesis_package_inputs(manifest_path)
        except RuntimeError as exc:
            assert "媒体派生" in str(exc) and "哈希" in str(exc)
        else:
            raise AssertionError("tampered muted media must be rejected")


def test_materialized_media_mute_preserves_duration_and_silences_interval():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_media = root / "source.m4a"
        derived_media = root / "source-muted.m4a"
        _run_project_ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2.000",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-y",
            str(source_media),
        )
        source_hash = file_sha256(source_media)

        _materialize_media_mute_audio(
            source_media,
            derived_media,
            [{"subtitle_id": "S0002", "start_ms": 900, "end_ms": 1200}],
        )

        assert file_sha256(source_media) == source_hash
        assert abs(
            _project_ffmpeg_audio_duration_ms(derived_media)
            - _project_ffmpeg_audio_duration_ms(source_media)
        ) <= 120
        result = subprocess.run(
            [
                str(BIN_PATH / "ffmpeg.exe"),
                "-nostdin",
                "-hide_banner",
                "-ss",
                "0.950",
                "-t",
                "0.200",
                "-i",
                str(derived_media),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "NUL",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
        assert result.returncode == 0, result.stderr
        match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", result.stderr)
        assert match is not None, result.stderr
        assert float(match.group(1)) <= -60.0


def test_tail_trim_keeps_earlier_muted_cue_in_one_v2_derivation():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"original-audio-placeholder")
        session.source_media_path = source_media.resolve()
        session.set_cue_hidden_and_media_muted("S0001", True)
        decision = session._apply_tail_trim_decision(
            session._preview_tail_trim_at_word(10)
        )
        session.cues[1]["translated_subtitle"] = "中"
        session.cues[1]["chinese_review_required"] = False

        def materialize_fixture_audio(source_path, output_path, **kwargs):
            assert source_path.resolve() == source_media.resolve()
            assert kwargs["cut_ms"] == decision["cut_ms"]
            assert kwargs["mute_intervals"] == [
                {"subtitle_id": "S0001", "start_ms": 0, "end_ms": 900}
            ]
            shutil.copyfile(source_path, output_path)

        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "_materialize_media_derivation_audio",
            side_effect=materialize_fixture_audio,
        ):
            paths = session.save_to_source_folder(source_media_path=source_media)

        manifest_path = Path(paths["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        derivation = manifest["media_derivation"]
        assert not manifest.get("tail_trim")
        assert not manifest.get("media_mute")
        assert derivation["cut_ms"] == decision["cut_ms"]
        assert derivation["mute_intervals"] == [
            {"subtitle_id": "S0001", "start_ms": 0, "end_ms": 900}
        ]
        assert Path(paths["source_media_path"]).resolve() != source_media.resolve()
        reloaded = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        assert len(reloaded.cues) == 2
        assert reloaded.cues[0]["media_muted"] is True
        assert reloaded.media_derivation == derivation


def test_tail_trim_clips_muted_partial_parent_interval():
    with tempfile.TemporaryDirectory() as temp_dir:
        source_media = Path(temp_dir) / "episode.m4a"
        source_media.write_bytes(b"audio-placeholder")
        session, _, _ = _tail_trim_session_fixture(Path(temp_dir), source_media)
        _write_display_page_preview_artifact(session)
        decision = session.preview_tail_trim_from_display_page("S0001.P02")
        session.set_cue_hidden_and_media_muted("S0001", True)
        session._apply_tail_trim_decision(decision)

        assert decision["partial_parent_trim"] is True
        assert session._media_mute_intervals() == [
            {
                "subtitle_id": "S0001",
                "start_ms": 0,
                "end_ms": decision["cut_ms"],
            }
        ]


def test_tail_trim_source_prefers_legacy_mute_original_over_derived_media():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, _, _ = _session_fixture(root)
        original_media = root / "original.m4a"
        derived_media = root / "muted.m4a"
        original_media.write_bytes(b"original")
        derived_media.write_bytes(b"derived")
        session.source_media_path = derived_media.resolve()
        session.media_mute = {
            "source_media_path": str(original_media.resolve()),
            "source_media_sha256": file_sha256(original_media),
            "derived_media_path": str(derived_media.resolve()),
            "derived_media_sha256": file_sha256(derived_media),
        }

        assert session._tail_trim_source_media_path() == original_media.resolve()


def test_suppressed_cue_does_not_invalidate_visible_actual_page_edits():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        initial_rows = session.to_model_data(prefer_display_pages=True)
        session.apply_display_page_model_data(initial_rows)
        before_ledger = copy.deepcopy(session.word_ledger)
        before_hidden = copy.deepcopy(session.cues[1])

        session.set_cue_display_suppressed("S0002", True)
        rows = session.to_model_data(prefer_display_pages=True)
        hidden_rows = [
            row for row in rows.values() if row.get("display_suppressed")
        ]
        assert len(hidden_rows) == 1
        assert hidden_rows[0]["manual_cue_id"] == "S0002"
        assert hidden_rows[0]["display_page_id"] == ""

        second_page_key = next(
            key
            for key, row in rows.items()
            if row.get("display_page_id") == "S0001.P02"
        )
        rows[second_page_key]["original_subtitle"] = (
            "mental model is just only as"
        )
        assert session.apply_display_page_model_data(rows) is True
        assert [edit["display_page_id"] for edit in session.display_page_edits] == [
            "S0001.P01",
            "S0001.P02",
        ]

        moved = session.move_display_page_boundary(
            "S0001.P01",
            1,
            move_to_next=True,
        )
        assert moved["left_page_id"] == "S0001.P01"
        assert session.display_page_edits
        assert [word["word_id"] for word in session.word_ledger] == [
            word["word_id"] for word in before_ledger
        ]
        assert [
            (word["start_ms"], word["end_ms"]) for word in session.word_ledger
        ] == [
            (word["start_ms"], word["end_ms"]) for word in before_ledger
        ]
        assert session.cues[1]["word_start"] == before_hidden["word_start"]
        assert session.cues[1]["word_end"] == before_hidden["word_end"]
        assert session.cues[1]["display_suppressed"] is True
        assert session.word_ledger[8]["surface"] == "only as"
        recovered = session._recover_display_page_artifact_from_complete_edits()
        assert [
            plan["parent_subtitle_id"]
            for plan in recovered["render_plans"]
        ] == ["S0001"]

        restored = session.set_cue_display_suppressed("S0002", False)
        assert restored["changed"] is True
        restored_rows = session.to_model_data(prefer_display_pages=True)
        assert any(
            row.get("display_page_id") == "S0002.P01"
            for row in restored_rows.values()
        )


def test_renderer_attachment_accepts_a_suppressed_middle_timeline_record():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        subtitle = root / "manual.srt"
        subtitle.write_text(
            """1
00:00:00,000 --> 00:00:00,300
Alpha.
甲。

2
00:00:00,600 --> 00:00:00,900
Charlie.
丙。
""",
            encoding="utf-8-sig",
        )
        ledger = root / "word-ledger.json"
        timeline = root / "final-cue-timeline.json"
        _write_json(
            ledger,
            {
                "words": [
                    {"surface": "Alpha.", "start_ms": 0, "end_ms": 300},
                    {"surface": "Bravo.", "start_ms": 300, "end_ms": 600},
                    {"surface": "Charlie.", "start_ms": 600, "end_ms": 900},
                ]
            },
        )
        _write_json(
            timeline,
            {
                "records": [
                    {
                        "subtitle_id": "S0001",
                        "word_start": 0,
                        "word_end": 0,
                        "start_ms": 0,
                        "end_ms": 300,
                        "original": "Alpha.",
                        "display_suppressed": False,
                    },
                    {
                        "subtitle_id": "S0002",
                        "word_start": 1,
                        "word_end": 1,
                        "start_ms": 300,
                        "end_ms": 600,
                        "original": "Bravo.",
                        "display_suppressed": True,
                    },
                    {
                        "subtitle_id": "S0003",
                        "word_start": 2,
                        "word_end": 2,
                        "start_ms": 600,
                        "end_ms": 900,
                        "original": "Charlie.",
                        "display_suppressed": False,
                    },
                ]
            },
        )
        _write_json(
            root / "stable-final-manifest.json",
            {
                "paths": {"original_top_srt": str(subtitle)},
                "paths_sha256": {"original_top_srt": file_sha256(subtitle)},
                "final_cue_timeline_path": str(timeline),
                "final_cue_timeline_sha256": file_sha256(timeline),
                "word_ledger_path": str(ledger),
                "word_ledger_sha256": file_sha256(ledger),
            },
        )

        cues = parse_srt(subtitle)

        assert attach_article_word_timing(cues, subtitle) is True
        assert [cue.subtitle_id for cue in cues] == ["S0001", "S0003"]
        assert [cue.word_timing[0]["word_id"] for cue in cues] == [0, 2]


def test_merge_display_page_with_next_keeps_parent_timeline_and_combines_chinese():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        before_cues = copy.deepcopy(session.cues)
        before_ledger = copy.deepcopy(session.word_ledger)
        before_rows = copy.deepcopy(session.to_model_data())

        result = session.merge_display_page_with_next("S0001.P01")

        rows = list(session.to_model_data().values())
        first_parent = [
            row for row in rows if row["manual_cue_id"] == "S0001"
        ]
        second_parent = [
            row for row in rows if row["manual_cue_id"] == "S0002"
        ]
        assert result["parent_subtitle_id"] == "S0001"
        assert result["removed_boundary_word_id"] == 4
        assert len(first_parent) == 1
        assert first_parent[0]["display_page_id"] == "S0001.P01"
        assert (first_parent[0]["word_start"], first_parent[0]["word_end"]) == (
            0,
            8,
        )
        assert first_parent[0]["translated_subtitle"] == "中文一"
        assert len(second_parent) == 1
        assert second_parent[0]["display_page_id"] == "S0002.P01"
        assert second_parent[0]["translated_subtitle"] == "中文二"
        assert session.display_page_boundary_overrides == {"S0001": []}
        assert session.cues == before_cues
        assert session.word_ledger == before_ledger

        assert session.undo() is True
        assert session.to_model_data() == before_rows
        assert session.cues == before_cues
        assert session.word_ledger == before_ledger


def test_split_one_display_page_preserves_every_other_page_and_parent():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 2)
        initial_rows = session.to_model_data()
        for row in initial_rows.values():
            row["display_page_chinese_confirmed"] = True
        session.apply_display_page_model_data(initial_rows)

        before_cue = copy.deepcopy(session.cues[0])
        before_ledger = copy.deepcopy(session.word_ledger)
        before_rows = list(session.to_model_data().values())
        selected = copy.deepcopy(before_rows[0])
        untouched = copy.deepcopy(before_rows[1])

        result = session.split_display_page(str(selected["display_page_id"]))

        after_rows = list(session.to_model_data().values())
        selected_replacement = [
            row
            for row in after_rows
            if int(selected["word_start"])
            <= int(row["word_start"])
            <= int(row["word_end"])
            <= int(selected["word_end"])
        ]
        untouched_after = next(
            row
            for row in after_rows
            if (int(row["word_start"]), int(row["word_end"]))
            == (int(untouched["word_start"]), int(untouched["word_end"]))
        )

        assert result["changed"] is True
        assert result["page_count"] == 3
        assert len(selected_replacement) == 2
        assert selected_replacement[0]["word_start"] == selected["word_start"]
        assert selected_replacement[-1]["word_end"] == selected["word_end"]
        assert all(
            row["translated_subtitle"]
            and row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in selected_replacement
        )
        for field in (
            "word_start",
            "word_end",
            "start_time",
            "end_time",
            "original_subtitle",
            "translated_subtitle",
            "display_page_chinese_confirmed",
        ):
            assert untouched_after[field] == untouched[field]
        for field in (
            "cue_id",
            "source_subtitle_ids",
            "word_start",
            "word_end",
            "start_time",
            "end_time",
            "original_subtitle",
            "translated_subtitle",
        ):
            assert session.cues[0][field] == before_cue[field]
        assert session.cues[0]["chinese_review_required"] is True
        assert session.word_ledger == before_ledger
        assert session.history[-1]["operation"] == "split_display_page"

        assert session.undo() is True
        assert session.to_model_data() == {
            str(index): row for index, row in enumerate(before_rows, 1)
        }


def test_cross_parent_actual_page_merge_is_one_atomic_operation():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        before_cues = copy.deepcopy(session.cues)
        before_rows = copy.deepcopy(session.to_model_data())
        before_history_count = len(session.history)

        result = session.merge_adjacent_display_pages(
            "S0001.P02",
            "S0002.P01",
        )

        rows = list(session.to_model_data().values())
        assert result["parent_merge"] is True
        assert result["page_count"] == 2
        assert len(session.cues) == 1
        assert len(rows) == 2
        assert rows[0]["display_page_id"] == "S0001.P01"
        assert (rows[0]["word_start"], rows[0]["word_end"]) == (0, 3)
        assert (rows[1]["word_start"], rows[1]["word_end"]) == (4, 11)
        assert rows[1]["translated_subtitle"] == "文一中文二"
        assert len(session.history) == before_history_count + 1
        assert session.history[-1]["operation"] == "merge_adjacent_display_pages"

        assert session.undo() is True
        assert session.cues == before_cues
        assert session.to_model_data() == before_rows


def test_cross_parent_merge_does_not_copy_the_entire_existing_history():
    class ImmutableHistoryMarker:
        def __deepcopy__(self, _memo):
            raise AssertionError("existing history must remain append-only")

    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        marker = ImmutableHistoryMarker()
        prior_entry = {
            "operation": "existing_edit",
            "before_cues": [],
            "affected_parent_ids": ["S0001"],
            "marker": marker,
        }
        session.history.append(prior_entry)

        session.merge_adjacent_display_pages("S0001.P02", "S0002.P01")

        assert session.history[0] is prior_entry
        assert session.history[0]["marker"] is marker
        assert session.history[-1]["operation"] == "merge_adjacent_display_pages"


def test_save_snapshot_copies_current_state_but_reuses_immutable_history_entries():
    class ImmutableHistoryMarker:
        def __deepcopy__(self, _memo):
            raise AssertionError("save snapshot must not duplicate history payloads")

    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        marker = ImmutableHistoryMarker()
        prior_entry = {
            "operation": "existing_edit",
            "before_cues": [],
            "marker": marker,
        }
        session.history.append(prior_entry)

        snapshot = session.snapshot_for_save()

        assert snapshot is not session
        assert snapshot.history is not session.history
        assert snapshot.history[0] is prior_entry
        assert snapshot.history[0]["marker"] is marker
        snapshot.cues[0]["translated_subtitle"] = "快照中文"
        snapshot.word_ledger[0]["surface"] = "Snapshot."
        assert session.cues[0]["translated_subtitle"] != "快照中文"
        assert session.word_ledger[0]["surface"] != "Snapshot."


def test_cross_parent_actual_page_merge_rolls_back_every_owner_on_failure():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        before_cues = copy.deepcopy(session.cues)
        before_edits = copy.deepcopy(session.display_page_edits)
        before_overrides = copy.deepcopy(session.display_page_boundary_overrides)
        before_history = copy.deepcopy(session.history)
        before_tail_trim = copy.deepcopy(session.tail_trim)

        with patch.object(
            session,
            "merge_display_page_with_next",
            side_effect=ManualFinalSubtitleEditError("injected page merge failure"),
        ):
            try:
                session.merge_adjacent_display_pages(
                    "S0001.P02",
                    "S0002.P01",
                )
            except ManualFinalSubtitleEditError as exc:
                assert "injected page merge failure" in str(exc)
            else:
                raise AssertionError("a partial cross-parent merge must roll back")

        assert session.cues == before_cues
        assert session.display_page_edits == before_edits
        assert session.display_page_boundary_overrides == before_overrides
        assert session.history == before_history
        assert session.tail_trim == before_tail_trim


def test_parent_merge_reflows_only_merged_pages_and_undo_restores_page_state():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        before_rows = copy.deepcopy(session.to_model_data())
        before_ledger = copy.deepcopy(session.word_ledger)

        session.merge_adjacent(0, 1)

        rows = list(session.to_model_data().values())
        assert len(session.cues) == 1
        assert rows
        assert all(row["manual_cue_id"] == "S0001" for row in rows)
        assert [row["display_page_id"] for row in rows] == [
            f"S0001.P{index:02d}" for index in range(1, len(rows) + 1)
        ]
        assert rows[0]["word_start"] == 0
        assert rows[-1]["word_end"] == 11
        assert session.display_page_boundary_overrides.get("S0001")
        assert "S0002" not in session.display_page_boundary_overrides
        assert session.word_ledger == before_ledger

        assert session.undo() is True
        assert session.to_model_data() == before_rows
        assert session.word_ledger == before_ledger


def test_row_scoped_undo_rejects_an_unrelated_parent_without_popping_history():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        before_rows = copy.deepcopy(session.to_model_data())

        session.merge_display_page_with_next("S0001.P01")

        assert session.can_undo_for_parent("S0001") is True
        assert session.can_undo_for_parent("S0002") is False
        history_count = len(session.history)
        changed_rows = copy.deepcopy(session.to_model_data())
        try:
            session.undo_for_parent("S0002")
        except ManualFinalSubtitleEditError as exc:
            assert "当前字幕没有可撤销的最新调整" in str(exc)
        else:
            raise AssertionError("an unrelated row must not pop global history")
        assert len(session.history) == history_count
        assert session.to_model_data() == changed_rows

        assert session.undo_for_parent("S0001") is True
        assert session.to_model_data() == before_rows


def test_row_scoped_undo_skips_later_unrelated_parent_without_overwriting_it():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        before = copy.deepcopy(session.to_model_data())

        session.merge_display_page_with_next("S0001.P01")
        after_first = copy.deepcopy(session.to_model_data())
        rows = copy.deepcopy(after_first)
        s2_key = next(
            key
            for key, row in rows.items()
            if str(row.get("manual_cue_id") or "") == "S0002"
        )
        rows[s2_key]["translated_subtitle"] = "第二条后来人工改过"
        session.apply_display_page_model_data(rows)
        after_second = copy.deepcopy(session.to_model_data())

        assert session.can_undo_for_parent("S0001") is True
        assert session.undo_for_parent("S0001") is True
        restored = session.to_model_data()
        restored_s1 = [
            row
            for row in restored.values()
            if str(row.get("manual_cue_id") or "") == "S0001"
        ]
        original_s1 = [
            row
            for row in before.values()
            if str(row.get("manual_cue_id") or "") == "S0001"
        ]
        restored_s2 = next(
            row
            for row in restored.values()
            if str(row.get("manual_cue_id") or "") == "S0002"
        )
        assert restored_s1 == original_s1
        assert restored_s2["translated_subtitle"] == "第二条后来人工改过"
        assert after_second != restored


def test_row_scoped_undo_rejects_cross_parent_transactions():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        before = copy.deepcopy(session.to_model_data(prefer_display_pages=False))
        session.merge_adjacent(0, 1)

        assert session.can_undo_for_parent("S0001") is False
        try:
            session.undo_for_parent("S0001")
        except ManualFinalSubtitleEditError as exc:
            assert "跨字幕" in str(exc) or "整体撤销" in str(exc)
        else:
            raise AssertionError("cross-parent transaction must not be partially undone")
        assert len(session.cues) == 1
        assert session.undo() is True
        assert session.to_model_data(prefer_display_pages=False) == before


def test_row_scoped_undo_survives_recovery_draft_reload():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, manifest_path = _session_fixture(root)
        _write_display_page_preview_artifact(session)
        original = copy.deepcopy(session.to_model_data())
        session.merge_display_page_with_next("S0001.P01")
        changed = copy.deepcopy(session.to_model_data())
        assert changed != original
        session.save_recovery_draft()

        restarted = ManualFinalSubtitleSession.load_for_subtitle(
            source_srt,
            work_dir=root / "work",
            manifest_path=manifest_path,
        )
        assert restarted.restore_recovery_draft() is True
        assert restarted.to_model_data() == changed
        assert restarted.can_undo_for_parent("S0001") is True
        assert restarted.undo_for_parent("S0001") is True
        assert restarted.to_model_data() == original


def test_parent_scoped_history_uses_compact_parent_state_and_round_trips():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        before = copy.deepcopy(session.to_model_data())

        session.merge_display_page_with_next("S0001.P01")

        entry = session.history[-1]
        assert entry["operation"] == "merge_display_page_with_next"
        assert set(entry["before_parent_states"]) == {"S0001"}
        assert "before_cues" not in entry
        assert "before_display_page_edits" not in entry
        assert "before_display_page_boundary_overrides" not in entry
        assert len(json.dumps(entry, ensure_ascii=False)) < 12_000
        changed = copy.deepcopy(session.to_model_data())

        assert session.undo_for_parent("S0001") is True
        assert session.to_model_data() == before
        assert session.redo_for_parent("S0001") is True
        assert session.to_model_data() == changed


def test_legacy_parent_scoped_history_is_compacted_without_losing_undo():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        before = copy.deepcopy(session.to_model_data())
        session.merge_display_page_with_next("S0001.P01")
        compact_entry = session.history[-1]
        parent_state = compact_entry["before_parent_states"]["S0001"]
        legacy_entry = {
            key: copy.deepcopy(value)
            for key, value in compact_entry.items()
            if key not in {"before_parent_states", "history_schema_version"}
        }
        legacy_entry.update(
            {
                "before_cues": [copy.deepcopy(parent_state["cue"])],
                "before_display_page_edits": copy.deepcopy(
                    parent_state["display_page_edits"]
                ),
                "before_display_page_boundary_overrides": (
                    {
                        "S0001": copy.deepcopy(
                            parent_state["display_page_boundary_override"]
                        )
                    }
                    if parent_state[
                        "has_display_page_boundary_override"
                    ]
                    else {}
                ),
                "before_recovered_stale_page_drafts": copy.deepcopy(
                    parent_state["recovered_stale_page_drafts"]
                ),
                "before_tail_trim": {},
            }
        )
        session.history = [legacy_entry]

        assert session.compact_parent_scoped_history() == 1
        assert "before_parent_states" in session.history[0]
        assert "before_cues" not in session.history[0]
        assert session.undo_for_parent("S0001") is True
        assert session.to_model_data() == before


def test_legacy_english_history_is_compacted_to_changed_word_ids():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        before_ledger = copy.deepcopy(session.word_ledger)
        rows = session.to_model_data(prefer_display_pages=False)
        rows["2"]["original_subtitle"] = "out of only as."
        assert session.apply_parent_model_data(rows) is True
        edited_fingerprint = session.state_fingerprint()
        entry = copy.deepcopy(session.history[-1])
        entry.pop("before_word_ledger_items", None)
        entry["before_word_ledger"] = before_ledger
        session.history = [entry]

        assert session.compact_english_surface_history() == 1
        compact = session.history[0]
        assert "before_word_ledger" not in compact
        assert [
            item["word_id"]
            for item in compact["before_word_ledger_items"]
        ] == [11]
        assert session.undo() is True
        assert session.word_ledger == before_ledger
        assert session.redo() is True
        assert session.state_fingerprint() == edited_fingerprint


def test_mixed_legacy_and_compact_english_history_migrates_in_order():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        original_ledger = copy.deepcopy(session.word_ledger)
        first_rows = session.to_model_data(prefer_display_pages=False)
        first_rows["2"]["original_subtitle"] = "out of only as."
        assert session.apply_parent_model_data(first_rows) is True
        after_first_ledger = copy.deepcopy(session.word_ledger)
        first_entry = copy.deepcopy(session.history[0])
        first_entry.pop("before_word_ledger_items", None)
        first_entry["before_word_ledger"] = original_ledger

        second_rows = session.to_model_data(prefer_display_pages=False)
        second_rows["1"]["original_subtitle"] = second_rows["1"][
            "original_subtitle"
        ].replace("Right.", "Correct.", 1)
        assert session.apply_parent_model_data(second_rows) is True
        second_entry = copy.deepcopy(session.history[1])
        session.history = [first_entry, second_entry]

        assert session.compact_english_surface_history() == 1
        assert [
            item["word_id"]
            for item in session.history[0]["before_word_ledger_items"]
        ] == [11]
        assert [
            item["word_id"]
            for item in session.history[1]["before_word_ledger_items"]
        ] == [0]
        assert session.undo() is True
        assert session.word_ledger == after_first_ledger
        assert session.undo() is True
        assert session.word_ledger == original_ledger


def test_free_text_edit_cannot_be_used_as_a_fake_word_boundary_move():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        session.cues[0]["original_subtitle"] = "Right. It means something else."

        try:
            session.move_suffix_to_next(0, 1)
            assert False, "free text must not be silently aligned by word index"
        except ManualFinalSubtitleEditError as exc:
            assert "词级账本" in str(exc)


def test_tail_trim_preview_is_pure_and_trim_undo_preserves_frozen_prefix():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_media = root / "source" / "episode.m4a"
        session, _, _ = _tail_trim_session_fixture(root, source_media)
        source_media.write_bytes(b"audio-placeholder")
        before_cues = json.loads(json.dumps(session.cues))
        before_ledger = json.loads(json.dumps(session.word_ledger))
        before_history = json.loads(json.dumps(session.history))

        preview = session.preview_tail_trim(1)

        assert preview["safe_gap_start_ms"] == 900
        assert preview["safe_gap_end_ms"] == 1100
        assert preview["safe_gap_start_ms"] < preview["cut_ms"] < preview[
            "safe_gap_end_ms"
        ]
        assert preview["removed_subtitle_ids"] == ["S0002"]
        assert session.cues == before_cues
        assert session.word_ledger == before_ledger
        assert session.history == before_history
        assert session.tail_trim == {}

        decision = session.trim_tail_from_cue(1)

        assert decision["removed_subtitle_ids"] == ["S0002"]
        assert decision["first_removed_subtitle_id"] == "S0002"
        assert len(session.cues) == 1
        assert session.cues[0] == before_cues[0]
        assert session.word_ledger == before_ledger[:9]
        assert session.history[-1]["operation"] == "trim_tail_from_cue"
        assert session.tail_trim["decision_hash"]

        assert session.undo() is True
        assert session.cues == before_cues
        assert session.word_ledger == before_ledger
        assert session.history == before_history
        assert session.tail_trim == {}


def test_result_directory_recovers_one_exact_sibling_source_media():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_media = root / "episode.m4a"
        source_media.write_bytes(b"audio")
        manifest_path = (
            root
            / "episode-处理结果"
            / "人工终稿字幕包"
            / "stable-final-manifest.json"
        )
        manifest_path.parent.mkdir(parents=True)

        resolved = ManualFinalSubtitleSession._manifest_source_media_path(
            {},
            manifest_path,
        )

        assert resolved == source_media.resolve()

        (root / "episode.mp3").write_bytes(b"second-audio")
        assert (
            ManualFinalSubtitleSession._manifest_source_media_path(
                {},
                manifest_path,
            )
            is None
        )


def test_actual_page_tail_trim_keeps_prior_page_and_undo_restores_all():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_media = root / "episode.m4a"
        session, _, _ = _tail_trim_session_fixture(root, source_media)
        source_media.write_bytes(b"audio-placeholder")
        _write_display_page_preview_artifact(session)
        before_cues = copy.deepcopy(session.cues)
        before_ledger = copy.deepcopy(session.word_ledger)
        before_rows = copy.deepcopy(session.to_model_data())

        preview = session.preview_tail_trim_from_display_page("S0001.P02")

        assert preview["first_removed_word_id"] == 4
        assert preview["first_removed_display_page_id"] == "S0001.P02"
        assert preview["partial_parent_trim"] is True
        assert preview["kept_last_subtitle_id"] == "S0001"
        assert preview["removed_subtitle_ids"] == ["S0002"]

        decision = session.trim_tail_from_display_page("S0001.P02")

        assert decision["cut_ms"] == 400
        assert len(session.cues) == 1
        assert session.cues[0]["cue_id"] == "S0001"
        assert session.cues[0]["word_end"] == 3
        assert session.cues[0]["original_subtitle"] == "Right. It means our"
        assert session.cues[0]["translated_subtitle"] == "中"
        assert len(session.word_ledger) == 4
        kept_pages = list(session.display_page_edits)
        assert [row["display_page_id"] for row in kept_pages] == ["S0001.P01"]
        assert kept_pages[0]["word_end"] == 3

        assert session.can_undo_for_parent("S0001") is False
        try:
            session.undo_for_parent("S0001")
        except ManualFinalSubtitleEditError as exc:
            assert "音频" in str(exc) or "整体撤销" in str(exc)
        else:
            raise AssertionError("tail trim must remain a document/audio-scoped undo")
        assert session.undo() is True
        assert session.cues == before_cues
        assert session.word_ledger == before_ledger
        assert session.to_model_data() == before_rows


def test_tail_trim_reconciles_frozen_page_end_with_final_cue_and_media_cut():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_media = root / "episode.m4a"
        session, _, _ = _tail_trim_session_fixture(root, source_media)
        source_media.write_bytes(b"audio-placeholder")
        _write_display_page_preview_artifact(session)
        page_artifact_path = session.artifact_dir / "display-page-translations.json"
        page_artifact = json.loads(page_artifact_path.read_text(encoding="utf-8"))
        session.cues[0]["translated_subtitle"] = "示例一，示例二"
        page_artifact["parents"][0]["pages"][0]["zh"] = "示例一，"
        page_artifact["parents"][0]["pages"][1]["zh"] = "示例二"
        page_artifact["render_plans"][0]["chinese"] = "示例一，示例二"
        for plan in page_artifact["render_plans"]:
            for page in plan["pages"]:
                page["english_lines"] = [page["english"]]
                page["english_width"] = 1260
        plans_by_parent = {
            plan["parent_subtitle_id"]: plan
            for plan in page_artifact["render_plans"]
        }
        for parent in page_artifact["parents"]:
            plan_pages = plans_by_parent[parent["parent_subtitle_id"]]["pages"]
            for page, plan_page in zip(parent["pages"], plan_pages):
                page.update(
                    {
                        "word_start": plan_page["word_start"],
                        "word_end": plan_page["word_end"],
                        "english": plan_page["english"],
                    }
                )
        _write_json(page_artifact_path, page_artifact)

        decision = session.trim_tail_from_cue(1)
        timeline = session._rebuild_authoritative_cue_timeline()
        final_record = timeline["records"][-1]
        assert final_record["end_ms"] == decision["cut_ms"]
        assert final_record["end_ms"] >= final_record["word_envelope_end_ms"]

        blueprint = session._blueprint_from_frozen_display_page_edits()
        assert blueprint is not None
        final_page = blueprint["render_plans"][0]["pages"][-1]
        assert final_page["end_ms"] == session.cues[-1]["end_time"]
        assert final_page["end_ms"] == decision["cut_ms"]

        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "_materialize_tail_trim_audio",
            side_effect=lambda source, output, _cut: shutil.copyfile(source, output),
        ):
            saved = session.save_to_source_folder(source_media_path=source_media)
        saved_subtitle = Path(saved["subtitle_path"])
        render_cues = parse_srt(saved_subtitle)
        assert attach_article_word_timing(render_cues, saved_subtitle) is True
        loaded = load_article_display_page_translation_artifact(
            render_cues,
            saved_subtitle,
        )
        if not loaded:
            manifest = json.loads(
                Path(saved["manifest_path"]).read_text(encoding="utf-8")
            )
            artifact = json.loads(
                Path(manifest["display_page_translation_path"]).read_text(
                    encoding="utf-8"
                )
            )
            failures = []
            podcast_learning_video.apply_article_display_page_translation_artifact(
                render_cues,
                artifact,
                failure_items=failures,
            )
            raise AssertionError(
                "saved page artifact did not reload: "
                f"failures={failures} "
                f"schema={artifact.get('schema_version')} "
                f"status={artifact.get('status')} "
                f"planner={artifact.get('planner_version')} "
                f"errors={artifact.get('errors')} "
                f"parents={artifact.get('parents')}"
            )
        assert render_cues[-1].article_page_plan is not None
        assert round(render_cues[-1].article_page_plan["pages"][-1]["end"] * 1000) == (
            decision["cut_ms"]
        )


def test_tail_trim_save_materializes_real_audio_and_reuses_exact_decision():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_media = root / "source" / "episode.m4a"
        session, _, _ = _tail_trim_session_fixture(root, source_media)
        _run_project_ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2.000",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-y",
            str(source_media),
        )
        source_hash = file_sha256(source_media)
        decision = session.trim_tail_from_cue(1)

        paths = session.save_to_source_folder(source_media_path=source_media)

        derived_media = Path(paths["source_media_path"])
        manifest_path = Path(paths["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert derived_media.is_file()
        assert derived_media.suffix.lower() == ".m4a"
        assert derived_media.resolve() != source_media.resolve()
        assert file_sha256(source_media) == source_hash
        assert (
            abs(
                _project_ffmpeg_audio_duration_ms(derived_media)
                - decision["cut_ms"]
            )
            <= 120
        )
        assert manifest["source_media_path"] == str(derived_media.resolve())
        assert manifest["media_derivation"]["cut_ms"] == decision["cut_ms"]
        assert manifest["media_derivation"]["mute_intervals"] == []
        assert manifest["media_derivation"]["derived_media_sha256"] == file_sha256(
            derived_media
        )
        assert not manifest.get("tail_trim")
        assert manifest["manual_final_override"]["source_media_path"] == str(
            derived_media.resolve()
        )

        resolved_media, resolved_manifest = resolve_synthesis_package_inputs(
            manifest_path
        )
        assert Path(resolved_media).resolve() == derived_media.resolve()
        assert Path(resolved_manifest) == manifest_path
        stale_media, stale_manifest = resolve_synthesis_package_inputs(
            manifest_path,
            str(source_media),
        )
        assert Path(stale_media).resolve() == derived_media.resolve()
        assert Path(stale_manifest) == manifest_path

        ledger = json.loads(
            Path(manifest["word_ledger_path"]).read_text(encoding="utf-8")
        )["words"]
        timeline = json.loads(
            Path(manifest["final_cue_timeline_path"]).read_text(encoding="utf-8")
        )["records"]
        assert [word["word_id"] for word in ledger] == list(range(9))
        assert [record["subtitle_id"] for record in timeline] == ["S0001"]
        assert timeline[0]["word_start"] == 0
        assert timeline[0]["word_end"] == 8
        assert timeline[0]["original"] == session.cues[0]["original_subtitle"]

        derived_hash = file_sha256(derived_media)
        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "_materialize_tail_trim_audio",
            side_effect=AssertionError(
                "an identical trim decision must reuse the derived audio"
            ),
        ):
            saved_again = session.save_to_source_folder(
                source_media_path=source_media
            )
        second_derived_media = Path(saved_again["source_media_path"]).resolve()
        assert second_derived_media != derived_media.resolve()
        assert file_sha256(second_derived_media) == derived_hash
        assert file_sha256(derived_media) == derived_hash
        assert file_sha256(source_media) == source_hash


def test_reloaded_tail_trim_undo_restores_original_media_and_full_package():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_media = root / "source" / "episode.m4a"
        session, _, _ = _tail_trim_session_fixture(root, source_media)
        source_media.write_bytes(b"original-audio-placeholder")
        source_hash = file_sha256(source_media)
        before_cues = json.loads(json.dumps(session.cues))
        before_ledger = json.loads(json.dumps(session.word_ledger))

        session.trim_tail_from_cue(1)

        def materialize_fixture_audio(source_path, output_path, _cut_ms):
            shutil.copyfile(source_path, output_path)

        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "_materialize_tail_trim_audio",
            side_effect=materialize_fixture_audio,
        ):
            trimmed_paths = session.save_to_source_folder(
                source_media_path=source_media
            )

        trimmed_manifest_path = Path(trimmed_paths["manifest_path"])
        derived_media = Path(trimmed_paths["source_media_path"])
        reloaded = ManualFinalSubtitleSession.load_from_manifest(
            trimmed_manifest_path
        )
        assert reloaded.source_media_path.resolve() == derived_media.resolve()
        assert reloaded.tail_trim["cut_ms"] == session.tail_trim["cut_ms"]

        assert reloaded.undo() is True

        assert reloaded.cues == before_cues
        assert reloaded.word_ledger == before_ledger
        assert reloaded.source_media_path.resolve() == source_media.resolve()
        assert reloaded.tail_trim == {}
        assert reloaded.history == []

        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "_materialize_tail_trim_audio",
            side_effect=AssertionError(
                "saving an undone trim must not materialize trimmed audio"
            ),
        ):
            restored_paths = reloaded.save_to_source_folder()

        restored_manifest = json.loads(
            Path(restored_paths["manifest_path"]).read_text(encoding="utf-8")
        )
        restored_override = restored_manifest["manual_final_override"]
        assert (
            Path(restored_paths["source_media_path"]).resolve()
            == source_media.resolve()
        )
        assert (
            Path(restored_manifest["source_media_path"]).resolve()
            == source_media.resolve()
        )
        assert (
            Path(restored_override["source_media_path"]).resolve()
            == source_media.resolve()
        )
        assert not restored_manifest.get("tail_trim")
        assert not restored_override.get("tail_trim")
        assert file_sha256(source_media) == source_hash

        restored_ledger = json.loads(
            Path(restored_manifest["word_ledger_path"]).read_text(encoding="utf-8")
        )["words"]
        restored_timeline = json.loads(
            Path(restored_manifest["final_cue_timeline_path"]).read_text(
                encoding="utf-8"
            )
        )["records"]
        assert restored_ledger == before_ledger
        assert [record["subtitle_id"] for record in restored_timeline] == [
            "S0001",
            "S0002",
        ]


def test_save_persists_manual_override_and_synthesis_uses_it():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, source_srt, manifest_path = _session_fixture(Path(temp_dir))
        from_manifest = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        assert from_manifest.subtitle_path == source_srt
        session.move_suffix_to_next(0, 2)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"test-audio-placeholder")
        result_dir = media_result_dir(source_media)
        subtitle_dir = media_result_subtitle_dir(source_media)
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        named_source_subtitle = (
            subtitle_dir / f"{source_media.stem}-原文在上双语字幕.srt"
        )
        shutil.copyfile(source_srt, named_source_subtitle)
        named_source_before = named_source_subtitle.read_bytes()
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_manifest["source_subtitle_paths"] = {
            "bilingual_original_top_srt": str(named_source_subtitle)
        }
        source_manifest["source_subtitle_paths_sha256"] = {
            "bilingual_original_top_srt": file_sha256(named_source_subtitle)
        }
        _write_json(manifest_path, source_manifest)
        source_manifest_before = manifest_path.read_bytes()

        paths = session.save_to_source_folder(source_media_path=source_media)
        manual_manifest_path = Path(paths["manifest_path"])
        manual_manifest = json.loads(manual_manifest_path.read_text(encoding="utf-8"))
        override = Path(manual_manifest["manual_final_override"]["subtitle_path"])

        assert override == Path(paths["subtitle_path"])
        assert override.exists()
        assert named_source_subtitle.is_file()
        assert named_source_subtitle.read_bytes() == named_source_before
        assert named_source_subtitle.read_bytes() != override.read_bytes()
        assert manual_manifest["source_subtitle_paths"] == {
            "bilingual_original_top_srt": str(named_source_subtitle),
        }
        assert manual_manifest["source_subtitle_paths_sha256"] == {
            key: file_sha256(Path(value))
            for key, value in manual_manifest["source_subtitle_paths"].items()
        }
        assert manifest_path.read_bytes() == source_manifest_before
        reloaded = ManualFinalSubtitleSession.load_for_subtitle(
            override, work_dir=Path(temp_dir) / "work"
        )
        assert reloaded.cues[1]["original_subtitle"] == "just completely out of date."
        package_artifact_dir = Path(
            manual_manifest["manual_final_override"]["artifact_dir"]
        )
        assert reloaded.artifact_dir == package_artifact_dir
        assert package_artifact_dir == Path(paths["artifact_dir"])
        assert (package_artifact_dir / "translations.json").is_file()
        assert package_artifact_dir != session.artifact_dir
        assert manual_manifest_path == override.parents[2] / "stable-final-manifest.json"
        assert manual_manifest_path.parent == result_dir / "人工终稿字幕包"
        assert manual_manifest["render_blocked"] is False
        final_timeline_path = Path(manual_manifest["final_cue_timeline_path"])
        word_ledger_path = Path(manual_manifest["word_ledger_path"])
        assert final_timeline_path.is_file()
        assert word_ledger_path.is_file()
        assert manual_manifest["final_cue_timeline_sha256"] == file_sha256(
            final_timeline_path
        )
        assert manual_manifest["word_ledger_sha256"] == file_sha256(word_ledger_path)
        assert manual_manifest["manual_final_override"][
            "final_cue_timeline_sha256"
        ] == file_sha256(final_timeline_path)
        assert manual_manifest["manual_final_override"][
            "word_ledger_sha256"
        ] == file_sha256(word_ledger_path)
        assert Path(manual_manifest["display_page_translation_path"]).is_file()
        assert Path(paths["display_page_srt_path"]).is_file()
        assert Path(paths["display_page_map_path"]).is_file()
        page_map = json.loads(
            Path(paths["display_page_map_path"]).read_text(encoding="utf-8")
        )
        assert page_map["pages"]
        assert all(page["display_page_id"] for page in page_map["pages"])
        assert all(
            page["end_ms"] > page["start_ms"]
            for page in page_map["pages"]
        )
        named_page_subtitle = Path(paths["display_page_srt_path"])
        first_page_bytes = named_page_subtitle.read_bytes()
        page_session = ManualFinalSubtitleSession.load_for_subtitle(
            named_page_subtitle,
            work_dir=Path(temp_dir) / "work",
        )
        page_rows = page_session.to_model_data()
        assert len(page_rows) == len(page_map["pages"])
        assert [row["display_page_id"] for row in page_rows.values()] == [
            page["display_page_id"] for page in page_map["pages"]
        ]
        page_session.apply_display_page_model_data(page_rows)
        with patch.object(
            podcast_learning_video,
            "build_article_display_page_blueprint",
            side_effect=AssertionError(
                "a no-op page save must reuse the frozen page artifact"
            ),
        ):
            page_session.save_to_source_folder(source_media_path=source_media)
        page_rows["1"]["translated_subtitle"] = "人工修改"
        page_session.apply_display_page_model_data(page_rows)
        with patch.object(
            podcast_learning_video,
            "build_article_display_page_blueprint",
            side_effect=AssertionError(
                "saved page edits must reuse the frozen page artifact"
            ),
        ):
            saved_again = page_session.save_to_source_folder(
                source_media_path=source_media
            )
        assert saved_again["manifest_path"] == paths["manifest_path"]
        assert named_page_subtitle.read_bytes() == first_page_bytes
        assert "人工修改" in Path(saved_again["display_page_srt_path"]).read_text(
            encoding="utf-8-sig"
        )
        latest_override = Path(saved_again["subtitle_path"])
        manual_cues = parse_srt(latest_override)
        assert attach_article_word_timing(manual_cues, latest_override) is True
        assert load_article_display_page_translation_artifact(
            manual_cues, latest_override
        ) is True
        resolved_media, resolved_manifest = resolve_synthesis_package_inputs(
            paths["manifest_path"]
        )
        assert Path(resolved_media) == source_media.resolve()
        assert Path(resolved_manifest) == Path(paths["manifest_path"])
        resolved = resolve_podcast_template_subtitle(
            str(source_srt.with_suffix(".m4a")),
            str(manifest_path.parent / "output.ass"),
        )
        assert Path(resolved) == Path(
            json.loads(manifest_path.read_text(encoding="utf-8"))["paths"][
                "original_top_srt"
            ]
        )
        package_resolved = resolve_podcast_template_subtitle(
            str(source_srt.with_suffix(".m4a")),
            paths["manifest_path"],
        )
        assert Path(package_resolved) == latest_override


def test_saved_manual_package_reopens_after_the_whole_result_directory_moves():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        session.move_suffix_to_next(0, 2)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"portable-package-audio")

        paths = session.save_to_source_folder(source_media_path=source_media)
        original_package = Path(paths["manifest_path"]).parent
        original_result = original_package.parent
        moved_result = root / "archive" / original_result.name
        moved_result.parent.mkdir(parents=True)
        shutil.move(str(original_result), str(moved_result))

        moved_package = moved_result / original_package.name
        moved_manifest = moved_package / "stable-final-manifest.json"
        moved_manifest_payload = json.loads(
            moved_manifest.read_text(encoding="utf-8")
        )
        moved_generation = moved_package / Path(
            moved_manifest_payload["package_generation"]["relative_dir"]
        )
        moved_parent_srt = moved_generation / "人工终稿字幕.srt"
        moved_page_srt = moved_generation / "人工终稿分页双语字幕.srt"
        assert not original_package.exists()

        reopened = ManualFinalSubtitleSession.load_from_manifest(moved_manifest)
        assert reopened.subtitle_path == moved_parent_srt.resolve()
        assert reopened.manifest_path == moved_manifest.resolve()
        assert reopened.artifact_dir.parent == moved_generation.resolve()
        assert reopened.cues[1]["original_subtitle"] == (
            "just completely out of date."
        )

        reopened_from_parent = ManualFinalSubtitleSession.load_for_subtitle(
            moved_parent_srt
        )
        assert reopened_from_parent.state_fingerprint() == reopened.state_fingerprint()

        reopened_from_page = ManualFinalSubtitleSession.load_for_subtitle(
            moved_page_srt
        )
        assert reopened_from_page.loaded_subtitle_path == moved_page_srt.resolve()
        assert reopened_from_page.state_fingerprint() == reopened.state_fingerprint()


def test_generation_write_failure_preserves_previous_published_package():
    from app.core.subtitle_processor.stable_artifacts import (
        write_json_artifact as real_write_json_artifact,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        first = session.save_to_source_folder()
        manifest_path = Path(first["manifest_path"])
        before_manifest = manifest_path.read_bytes()
        before_session = ManualFinalSubtitleSession.load_from_manifest(manifest_path)

        def fail_generation_write(path, payload):
            candidate = Path(path)
            if candidate.name == "translations.json" and "generations" in candidate.parts:
                raise OSError("injected generation write failure")
            return real_write_json_artifact(candidate, payload)

        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "write_json_artifact",
            side_effect=fail_generation_write,
        ):
            try:
                before_session.save_to_source_folder()
                assert False, "a generation write failure must abort publication"
            except OSError as exc:
                assert "injected generation write failure" in str(exc)

        assert manifest_path.read_bytes() == before_manifest
        recovered = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        assert recovered.state_fingerprint() == before_session.state_fingerprint()


def test_generation_validation_failure_preserves_previous_published_package():
    from app.core.subtitle_processor.stable_artifacts import (
        resolve_manifest_owned_path as real_resolve_manifest_owned_path,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        first = session.save_to_source_folder()
        manifest_path = Path(first["manifest_path"])
        before_manifest = manifest_path.read_bytes()
        before_session = ManualFinalSubtitleSession.load_from_manifest(manifest_path)

        def fail_word_ledger_validation(
            candidate_manifest,
            manifest,
            declared,
            expected_sha256="",
            **kwargs,
        ):
            if (
                ".candidate.json" in Path(candidate_manifest).name
                and str(declared).endswith("word-ledger.json")
            ):
                return None
            return real_resolve_manifest_owned_path(
                candidate_manifest,
                manifest,
                declared,
                expected_sha256,
                **kwargs,
            )

        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "resolve_manifest_owned_path",
            side_effect=fail_word_ledger_validation,
        ):
            try:
                before_session.save_to_source_folder()
                assert False, "a failed generation validation must abort publication"
            except ManualFinalSubtitleEditError as exc:
                assert "word_ledger_path" in str(exc)

        assert manifest_path.read_bytes() == before_manifest
        recovered = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        assert recovered.state_fingerprint() == before_session.state_fingerprint()


def test_root_manifest_commit_failure_preserves_previous_generation():
    from app.core.subtitle_processor.stable_artifacts import (
        write_json_artifact as real_write_json_artifact,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        first = session.save_to_source_folder()
        manifest_path = Path(first["manifest_path"])
        before_manifest = manifest_path.read_bytes()
        before_session = ManualFinalSubtitleSession.load_from_manifest(manifest_path)

        def fail_root_commit(path, payload):
            candidate = Path(path)
            if candidate == manifest_path:
                raise OSError("injected root manifest commit failure")
            return real_write_json_artifact(candidate, payload)

        with patch(
            "app.core.subtitle_processor.manual_final_subtitle_editor."
            "write_json_artifact",
            side_effect=fail_root_commit,
        ):
            try:
                before_session.save_to_source_folder()
                assert False, "a root commit failure must abort publication"
            except OSError as exc:
                assert "injected root manifest commit failure" in str(exc)

        assert manifest_path.read_bytes() == before_manifest
        recovered = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        assert recovered.state_fingerprint() == before_session.state_fingerprint()


def test_manual_package_reuses_only_exact_source_display_page_spans():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_json(
            session.artifact_dir / "translations.json",
            [
                {
                    "subtitle_id": "S0001",
                    "text": "Right. It means our mental model is just completely",
                    "translated_text": "中文一",
                },
                {
                    "subtitle_id": "S0002",
                    "text": "out of date.",
                    "translated_text": "中文二",
                },
            ],
        )
        _write_json(
            session.artifact_dir / "display-page-translations.json",
            {
                "parents": [
                    {
                        "parent_subtitle_id": "S0001",
                        "pages": [
                            {
                                "word_start": 0,
                                "word_end": 3,
                                "english": "Right. It means our",
                                "zh": "中",
                            },
                            {
                                "word_start": 4,
                                "word_end": 8,
                                "english": "mental model is just completely",
                                "zh": "文一",
                            },
                        ],
                    }
                ]
            },
        )
        parents = [
            {
                "parent_subtitle_id": "S0001",
                "chinese": "中文一",
                "pages": [
                    {
                        "display_page_id": "S0001.P01",
                        "word_start": 0,
                        "word_end": 3,
                        "english": "Right. It means our",
                    },
                    {
                        "display_page_id": "S0001.P02",
                        "word_start": 4,
                        "word_end": 8,
                        "english": "mental model is just completely",
                    },
                ],
            }
        ]

        response = session._reuse_source_page_translations(parents)

        assert response == {
            "pages": [
                {"display_page_id": "S0001.P01", "zh": "中"},
                {"display_page_id": "S0001.P02", "zh": "文一"},
            ]
        }
        changed = json.loads(json.dumps(parents))
        changed[0]["pages"][0]["word_end"] = 4
        assert session._reuse_source_page_translations(changed) is None


def test_manual_package_blocks_cleanly_when_page_translation_validation_returns_error():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"test-audio-placeholder")
        session._reuse_source_page_translations = lambda _parents: {"pages": []}

        with patch.object(
            podcast_learning_video,
            "build_article_display_page_blueprint",
            return_value={
                "parents": [{"parent_subtitle_id": "S0001", "pages": [{}, {}]}],
                "render_plans": [],
            },
        ), patch.object(
            stable_display_page_contract,
            "build_display_page_contract",
            return_value={"contract_hash": "fixture-contract"},
        ), patch.object(
            stable_display_page_contract,
            "validate_page_translation_response",
            return_value={
                "status": "ERROR",
                "contract_hash": "fixture-contract",
                "errors": [{"code": "page_translation_chinese_token_split"}],
                "parents": [],
                "render_plans": [],
            },
        ):
            paths = session.save_to_source_folder(source_media_path=source_media)

        manifest = json.loads(Path(paths["manifest_path"]).read_text(encoding="utf-8"))
        artifact = json.loads(
            Path(manifest["display_page_translation_path"]).read_text(encoding="utf-8")
        )
        assert paths["render_blocked"] is True
        assert paths["render_block_reason"] == "manual_page_translation_invalid"
        assert paths["display_page_srt_path"] == ""
        assert paths["display_page_map_path"] == ""
        assert manifest["render_blocked"] is True
        assert manifest["validation_status"] == "failed"
        assert artifact["status"] == "ERROR"


def test_manual_package_persists_hash_bound_draft_pages_when_translation_is_required():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, source_srt, _ = _session_fixture(root)
        source_media = source_srt.with_suffix(".m4a")
        source_media.write_bytes(b"test-audio-placeholder")
        session._reuse_source_page_translations = lambda _parents: None
        draft_artifact = {
            "schema_version": 1,
            "status": "REVIEW",
            "render_plans": [
                {
                    "parent_subtitle_id": "S0001",
                    "english": "Right. It means our mental model is just completely",
                    "chinese": "中文一",
                    "english_font_size": 56,
                    "pages": [
                        {
                            "display_page_id": "S0001.P01",
                            "page_index": 1,
                            "english": "Right. It means our",
                            "chinese": "中",
                            "start_ms": 0,
                            "end_ms": 400,
                            "english_font_size": 56,
                        },
                        {
                            "display_page_id": "S0001.P02",
                            "page_index": 2,
                            "english": "mental model is just completely",
                            "chinese": "文一",
                            "start_ms": 400,
                            "end_ms": 900,
                            "english_font_size": 56,
                        },
                    ],
                },
                {
                    "parent_subtitle_id": "S0002",
                    "english": "out of date.",
                    "chinese": "中文二",
                    "english_font_size": 54,
                    "pages": [
                        {
                            "display_page_id": "S0002.P01",
                            "page_index": 1,
                            "english": "out of date.",
                            "chinese": "中文二",
                            "start_ms": 900,
                            "end_ms": 1200,
                            "english_font_size": 54,
                        }
                    ],
                },
            ],
        }
        blueprint = {
            "parents": [
                {
                    "parent_subtitle_id": "S0001",
                    "pages": [{"display_page_id": "S0001.P01"}, {"display_page_id": "S0001.P02"}],
                }
            ],
            "render_plans": draft_artifact["render_plans"],
        }

        with patch.object(
            podcast_learning_video,
            "build_article_display_page_blueprint",
            return_value=blueprint,
        ), patch.object(
            podcast_learning_video,
            "build_article_manual_draft_page_artifact",
            return_value=draft_artifact,
        ):
            paths = session.save_to_source_folder(source_media_path=source_media)

        manifest_path = Path(paths["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        override = manifest["manual_final_override"]
        draft_path = Path(manifest["manual_draft_page_plan_path"])
        draft_sha256 = manifest["manual_draft_page_plan_sha256"]

        assert paths["render_blocked"] is True
        assert paths["render_block_reason"] == "manual_page_translation_required"
        assert paths["manual_draft_ready"] is True
        assert draft_path.name == "manual-draft-page-plan.json"
        assert draft_path.parent.resolve() == Path(paths["artifact_dir"]).resolve()
        assert json.loads(draft_path.read_text(encoding="utf-8")) == draft_artifact
        assert override["manual_draft_page_plan_path"] == str(draft_path)
        assert override["manual_draft_page_plan_sha256"] == draft_sha256
        assert file_sha256(draft_path) == draft_sha256

        reloaded = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        expected_pages = {
            plan["parent_subtitle_id"]: [
                (
                    page["display_page_id"],
                    page["english"],
                    page["chinese"],
                    page["start_ms"],
                    page["end_ms"],
                    page["english_font_size"],
                )
                for page in plan["pages"]
            ]
            for plan in draft_artifact["render_plans"]
        }
        actual_pages = {}
        for row in reloaded.to_model_data().values():
            actual_pages.setdefault(row["manual_cue_id"], []).append(
                (
                    row["display_page_id"],
                    row["original_subtitle"],
                    row["translated_subtitle"],
                    row["start_time"],
                    row["end_time"],
                    row["english_font_size"],
                )
            )
        assert actual_pages == expected_pages

        draft_path.write_text(
            draft_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
        fallback_pages = {}
        for row in reloaded.to_model_data().values():
            fallback_pages.setdefault(row["manual_cue_id"], []).append(
                (
                    row["display_page_id"],
                    row["original_subtitle"],
                    row["translated_subtitle"],
                    row["start_time"],
                    row["end_time"],
                    row["english_font_size"],
                )
            )
        assert fallback_pages == expected_pages


def test_manual_draft_reuses_exact_frozen_semantic_page_chinese():
    cue = podcast_learning_video.Cue(
        index=1,
        start=0.0,
        end=1.2,
        en="One two three four",
        zh="中国毕业生",
        speaker="male",
        subtitle_id="S0001",
        word_timing=tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * 0.3,
                "end": (index + 1) * 0.3,
            }
            for index, word in enumerate(("One", "two", "three", "four"))
        ),
        display_page_translations={
            "S0001.P01": "中国",
            "S0001.P02": "毕业生",
        },
    )
    frozen_plan = {
        "parent_subtitle_id": "S0001",
        "english": cue.en,
        "chinese": cue.zh,
        "word_start": 0,
        "word_end": 3,
        "english_font_size": 56,
        "font_fallback": {"used": False},
        "pages": [
            {
                "display_page_id": "S0001.P01",
                "word_start": 0,
                "word_end": 0,
                "english": "One",
                "chinese": "中国",
            },
            {
                "display_page_id": "S0001.P02",
                "word_start": 1,
                "word_end": 3,
                "english": "two three four",
                "chinese": "毕业生",
            },
        ],
    }
    semantic_page_translations = {
        "S0001.P01": {
            "parent_subtitle_id": "S0001",
            "word_start": 0,
            "word_end": 0,
            "english": "One",
            "chinese": "中国",
        },
        "S0001.P02": {
            "parent_subtitle_id": "S0001",
            "word_start": 1,
            "word_end": 3,
            "english": "two three four",
            "chinese": "毕业生",
        },
    }
    validated_translations = {}

    def validate_frozen_plan(_cue, _frozen, translations, _draw):
        validated_translations.update(translations)
        return {"status": "ok"}

    with patch.object(
        podcast_learning_video,
        "_strict_split_chinese_visual_pages",
        side_effect=AssertionError(
            "exact frozen semantic page Chinese must not be proportionally split again"
        ),
    ), patch.object(
        podcast_learning_video,
        "_article_plan_from_frozen_artifact",
        side_effect=validate_frozen_plan,
    ):
        artifact = podcast_learning_video.build_article_manual_draft_page_artifact(
            [cue],
            [frozen_plan],
            semantic_page_translations,
        )

    assert validated_translations == {
        "S0001.P01": "中国",
        "S0001.P02": "毕业生",
    }
    assert [
        page["chinese"] for page in artifact["render_plans"][0]["pages"]
    ] == ["中国", "毕业生"]


def test_review_page_rows_preserve_boundary_metadata_for_editor_review():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["status"] = "REVIEW"
        review_page = artifact["render_plans"][0]["pages"][1]
        review_page["boundary_before"] = {
            "classification": "review",
            "issue_codes": ["manual_short_page_review"],
            "pause_ms": 120,
        }
        _write_json(artifact_path, artifact)

        rows = list(session.to_model_data().values())
        review_row = next(
            row for row in rows if row.get("display_page_id") == "S0001.P02"
        )

        assert review_row["display_page_unavailable"] is False
        assert review_row["display_page_review_required"] is True
        assert review_row["display_page_boundary_classification"] == "review"
        assert review_row["display_page_issue_codes"] == [
            "manual_short_page_review"
        ]


def test_partial_page_artifact_keeps_valid_pages_and_failed_parent_review_row():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        _write_display_page_preview_artifact(session)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["status"] = "ERROR"
        artifact["errors"] = [
            {
                "code": "page_translation_chinese_token_split",
                "parent_subtitle_id": "S0002",
            }
        ]
        failed_plan = next(
            plan
            for plan in artifact["render_plans"]
            if plan["parent_subtitle_id"] == "S0002"
        )
        failed_plan["pages"] = [
            {
                "display_page_id": "S0002.P01",
                "page_index": 1,
                "word_start": 9,
                "word_end": 9,
                "english": "out",
                "start_ms": 900,
                "end_ms": 1020,
                "english_font_size": 54,
            },
            {
                "display_page_id": "S0002.P02",
                "page_index": 2,
                "word_start": 10,
                "word_end": 11,
                "english": "of date.",
                "start_ms": 1020,
                "end_ms": 1200,
                "english_font_size": 54,
            },
        ]
        _write_json(artifact_path, artifact)

        rows = list(session.to_model_data().values())

        assert [row.get("display_page_id") for row in rows] == [
            "S0001.P01",
            "S0001.P02",
            "S0002.P01",
            "S0002.P02",
        ]
        failed_pages = rows[-2:]
        assert [row["original_subtitle"] for row in failed_pages] == [
            "out",
            "of date.",
        ]
        assert all(row["manual_cue_id"] == "S0002" for row in failed_pages)
        assert [row["translated_subtitle"] for row in failed_pages] == [
            "中文二",
            "",
        ]
        assert all(row["display_page_unavailable"] is False for row in failed_pages)
        assert all(row["display_page_review_required"] is True for row in failed_pages)
        assert [row["display_page_chinese_stale"] for row in failed_pages] == [
            True,
            False,
        ]
        assert failed_pages[0]["display_page_chinese_draft_kind"] == (
            "parent_chinese_fallback"
        )
        assert failed_pages[1]["display_page_chinese_draft_kind"] == ""
        assert [row["display_page_chinese_pending"] for row in failed_pages] == [
            False,
            True,
        ]
        assert all(
            "page_translation_chinese_token_split"
            in row["display_page_issue_codes"]
            for row in failed_pages
        )
        assert all(row["chinese_review_required"] is True for row in failed_pages)


def test_saved_reload_can_switch_between_parent_and_actual_page_rows():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        paths = session.save_to_source_folder()

        reloaded = ManualFinalSubtitleSession.load_from_manifest(
            Path(paths["manifest_path"])
        )
        page_rows = reloaded.to_model_data(prefer_display_pages=True)
        parent_rows = reloaded.to_model_data(prefer_display_pages=False)
        page_rows_again = reloaded.to_model_data(prefer_display_pages=True)

        assert reloaded.has_display_page_model() is True
        assert len(parent_rows) == len(reloaded.cues)
        assert all(
            "display_page_id" not in row for row in parent_rows.values()
        )
        assert page_rows_again == page_rows
        assert page_rows
        assert all(
            row.get("display_page_id") for row in page_rows.values()
        )


def test_manual_save_upgrades_old_page_layout_without_replanning_pages():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        session, _, _ = _splittable_parent_session(root)
        artifact_path = session.artifact_dir / "display-page-translations.json"
        source_artifact = session._effective_display_page_artifact()
        source_words = source_artifact["render_plans"][0]["english"].split()
        source_artifact["render_plans"][0]["pages"][0]["english_lines"] = [
            " ".join(source_words[:5]),
            " ".join(source_words[5:]),
        ]
        source_artifact["render_plans"][0]["pages"][0]["english_width"] = 1260
        _write_json(artifact_path, source_artifact)
        source_manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
        source_manifest["display_page_translation_sha256"] = file_sha256(
            artifact_path
        )
        _write_json(session.manifest_path, source_manifest)
        source_artifact = session._effective_display_page_artifact()
        source_plan = copy.deepcopy(source_artifact["render_plans"][0])

        with patch.object(
            podcast_learning_video,
            "reflow_article_frozen_page_plan_same_screen",
            wraps=podcast_learning_video.reflow_article_frozen_page_plan_same_screen,
        ) as reflow:
            render_contract = session._write_manual_render_contract(
                root / "v19-manual-artifacts"
            )

        assert render_contract["render_blocked"] is False
        assert reflow.call_count == len(session.cues)
        upgraded_artifact = render_contract["display_artifact"]
        assert (
            upgraded_artifact["planner_version"]
            == stable_display_page_contract.DISPLAY_PAGE_PLANNER_VERSION
        )
        upgraded_plan = upgraded_artifact["render_plans"][0]
        plan_keys = (
            "parent_subtitle_id",
            "english",
            "chinese",
            "word_start",
            "word_end",
        )
        page_keys = (
            "display_page_id",
            "word_start",
            "word_end",
            "english",
            "start_ms",
            "end_ms",
            "boundary_before",
        )
        assert {key: upgraded_plan[key] for key in plan_keys} == {
            key: source_plan[key] for key in plan_keys
        }
        assert [
            {key: page[key] for key in page_keys}
            for page in upgraded_plan["pages"]
        ] == [
            {key: page[key] for key in page_keys}
            for page in source_plan["pages"]
        ]


def test_unconfirmed_manual_split_proposals_can_move_boundary_but_save_stays_blocked():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        session.split_parent_into_display_pages("S0001", 2)
        before_rows = list(session.to_model_data().values())
        target_start = int(before_rows[1]["word_start"]) - 1
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["boundaries"][str(target_start)].update(
            {
                "hard_issues": [],
                "soft_issues": ["manual_short_page_review"],
                "pause_ms": 120,
            }
        )
        _write_json(evidence_path, evidence)

        move_result = session.move_display_page_boundary(
            "S0001.P01",
            1,
            move_to_next=True,
        )

        rows = list(session.to_model_data().values())
        assert all(row["translated_subtitle"] for row in rows)
        assert "".join(row["translated_subtitle"] for row in rows) == (
            session.cues[0]["translated_subtitle"]
        )
        assert all(
            row["display_page_chinese_stale"] is True
            and row["display_page_chinese_confirmed"] is False
            for row in rows
        )
        assert [(row["word_start"], row["word_end"]) for row in rows] == [
            (0, target_start - 1),
            (target_start, len(session.word_ledger) - 1),
        ]
        decision = move_result["warnings"][0]
        assert decision["classification"] == "review"
        assert "manual_short_page_review" in decision["issue_codes"]

        blocked = session.save_to_source_folder()
        assert blocked["render_blocked"] is True
        assert blocked["render_block_reason"] == "manual_page_translation_required"
        assert blocked["display_page_srt_path"] == ""


def test_parent_split_allows_explicit_high_risk_manual_fallback():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        for boundary in evidence["boundaries"].values():
            boundary["hard_issues"] = ["atomic_of_complement_split"]
            boundary["soft_issues"] = []
        _write_json(evidence_path, evidence)

        try:
            session.split_parent_into_display_pages("S0001", 2)
        except ManualFinalSubtitleEditError as exc:
            assert exc.code == "manual_high_risk_page_split_confirmation_required"
        else:
            raise AssertionError("a hard split must require explicit human approval")

        before_parent = copy.deepcopy(session.cues[0])
        result = session.split_parent_into_display_pages(
            "S0001",
            2,
            allow_high_risk=True,
        )
        rows = list(session.to_model_data().values())

        assert result["changed"] is True
        assert result["high_risk_override"] is True
        assert len(rows) == 2
        assert session.cues[0]["cue_id"] == before_parent["cue_id"]
        assert session.cues[0]["word_start"] == before_parent["word_start"]
        assert session.cues[0]["word_end"] == before_parent["word_end"]
        assert session.cues[0]["original_subtitle"] == before_parent["original_subtitle"]
        assert session.display_page_boundary_overrides["S0001"] == [
            int(rows[1]["word_start"])
        ]


def test_unrenderable_parent_seed_can_be_split_without_a_frozen_page_plan():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        cue = session.cues[0]
        seed_artifact = {
            "schema_version": 2,
            "status": "ERROR",
            "planner_version": (
                stable_display_page_contract.DISPLAY_PAGE_PLANNER_VERSION
            ),
            "layout_profile": (
                podcast_learning_video.article_display_page_layout_profile()
            ),
            "errors": [
                {
                    "code": "display_page_blueprint_invalid",
                    "parent_subtitle_id": "S0001",
                    "reason": "no_complete_normal_font_page_partition",
                }
            ],
            "parents": [],
            "render_plans": [
                {
                    "parent_subtitle_id": "S0001",
                    "english": cue["original_subtitle"],
                    "chinese": cue["translated_subtitle"],
                    "word_start": cue["word_start"],
                    "word_end": cue["word_end"],
                    "english_font_size": 52,
                    "font_fallback": {"used": False},
                    "editable_seed": True,
                    "renderable": False,
                    "pages": [
                        {
                            "display_page_id": "S0001.P01",
                            "word_start": cue["word_start"],
                            "word_end": cue["word_end"],
                            "english": cue["original_subtitle"],
                        }
                    ],
                }
            ],
        }
        seed_path = session.artifact_dir / "display-page-translations.json"
        _write_json(seed_path, seed_artifact)
        manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
        manifest["display_page_translation_path"] = str(seed_path)
        manifest["display_page_translation_sha256"] = file_sha256(seed_path)
        _write_json(session.manifest_path, manifest)

        before_rows = list(session.to_model_data().values())
        assert len(before_rows) == 1
        assert before_rows[0]["display_page_unavailable"] is False
        assert before_rows[0]["display_page_id"] == "S0001.P01"
        assert before_rows[0]["translated_subtitle"] == cue["translated_subtitle"]
        assert before_rows[0]["display_page_chinese_stale"] is True
        assert before_rows[0]["display_page_chinese_draft_kind"] == (
            "parent_chinese_fallback"
        )
        assert before_rows[0]["display_page_chinese_confirmed"] is False
        try:
            session.confirm_display_page_chinese("S0001.P01")
        except ManualFinalSubtitleEditError as exc:
            assert "父字幕中文预览" in str(exc)
        else:
            raise AssertionError("parent Chinese fallback must not be confirmed as page Chinese")

        result = session.split_parent_into_display_pages(
            "S0001",
            2,
            allow_high_risk=True,
        )
        rows = list(session.to_model_data().values())

        assert result["changed"] is True
        assert len(rows) == 2
        assert all(row["display_page_unavailable"] is False for row in rows)
        assert all(
            row["english_font_size"] in {56, 54, 52}
            for row in rows
        )
        assert " ".join(row["original_subtitle"] for row in rows) == (
            cue["original_subtitle"]
        )


def test_explicit_manual_parent_split_can_reach_six_pages():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        before = copy.deepcopy(session.cues[0])
        ranges = [(0, 2), (3, 5), (6, 8), (9, 11), (12, 14), (15, 16)]

        result = session.split_parent_into_display_pages(
            "S0001",
            6,
            word_ranges=ranges,
            allow_high_risk=True,
        )
        rows = [
            row
            for row in session.display_page_edits
            if str(row.get("parent_subtitle_id") or "") == "S0001"
        ]

        assert result["changed"] is True
        assert result["page_count"] == 6
        assert [row["display_page_id"] for row in rows] == [
            f"S0001.P{index:02d}" for index in range(1, 7)
        ]
        assert [
            (int(row["word_start"]), int(row["word_end"])) for row in rows
        ] == ranges
        assert session.cues[0]["cue_id"] == before["cue_id"]
        assert session.cues[0]["word_start"] == before["word_start"]
        assert session.cues[0]["word_end"] == before["word_end"]


def test_manual_page_soft_override_preserves_hard_page_invariants():
    text = "One two three four five six seven eight nine ten"
    timing = tuple(
        {
            "word_id": index,
            "surface": word,
            "start": index * 0.4,
            "end": index * 0.4 + 0.3,
        }
        for index, word in enumerate(text.split())
    )
    cue = podcast_learning_video.Cue(
        index=1,
        start=0.0,
        end=4.0,
        en=text,
        zh="中文",
        speaker="manual",
        subtitle_id="S9501",
        word_timing=timing,
        display_boundary_evidence={
            "5": {
                "hard_issues": [],
                "soft_issues": ["manual_short_page_review"],
                "pause_ms": 100,
            }
        },
    )
    frozen_plan = {
        "parent_subtitle_id": "S9501",
        "english": text,
        "chinese": "中文",
        "word_start": 0,
        "word_end": 9,
        "pages": [
            {"display_page_id": "S9501.P01"},
            {"display_page_id": "S9501.P02"},
        ],
    }
    translations = {"S9501.P01": "中", "S9501.P02": "文"}

    rebuilt = podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
        cue,
        frozen_plan,
        [(0, 4), (5, 9)],
        translations,
        allow_manual_review=True,
    )
    decision = rebuilt["pages"][1]["boundary_before"]
    assert decision["classification"] == "review"
    assert decision["manual_override"] is True
    assert "manual_short_page_review" in decision["issue_codes"]

    invalid_ranges = {
        "empty": [(0, -1), (0, 9)],
        "lost": [(0, 3), (5, 9)],
        "duplicate": [(0, 5), (5, 9)],
        "reordered": [(5, 9), (0, 4)],
    }
    for label, ranges in invalid_ranges.items():
        try:
            podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
                cue,
                frozen_plan,
                ranges,
                translations,
                allow_manual_review=True,
            )
        except podcast_learning_video.RenderStructuralOverflowError as exc:
            reasons = {str(item.get("reason") or "") for item in exc.errors}
            assert "manual_page_boundary_not_contiguous" in reasons, label
        else:
            raise AssertionError(f"{label} page ranges must be rejected")

    hard_cue = podcast_learning_video.Cue(
        index=1,
        start=0.0,
        end=4.0,
        en=text,
        zh="中文",
        speaker="manual",
        subtitle_id="S9501",
        word_timing=timing,
        display_boundary_evidence={
            "5": {
                "hard_issues": ["atomic_of_complement_split"],
                "soft_issues": [],
                "pause_ms": 0,
            }
        },
    )
    try:
        podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
            hard_cue,
            frozen_plan,
            [(0, 4), (5, 9)],
            translations,
        )
    except podcast_learning_video.RenderStructuralOverflowError as exc:
        reasons = {str(item.get("reason") or "") for item in exc.errors}
        assert "manual_page_boundary_is_hard" in reasons
    else:
        raise AssertionError("automatic planning must reject a hard syntax cut")

    reviewed = podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
        hard_cue,
        frozen_plan,
        [(0, 4), (5, 9)],
        translations,
        allow_manual_review=True,
    )
    reviewed_decision = reviewed["pages"][1]["boundary_before"]
    assert reviewed_decision["classification"] == "review"
    assert reviewed_decision["manual_override"] is True
    assert "atomic_of_complement_split" in reviewed_decision["issue_codes"]

    overflow_words = ("X" * 1000, "Y" * 1000)
    overflow_text = " ".join(overflow_words)
    overflow_cue = podcast_learning_video.Cue(
        index=2,
        start=0.0,
        end=2.2,
        en=overflow_text,
        zh="中文",
        speaker="manual",
        subtitle_id="S9502",
        word_timing=(
            {"word_id": 0, "surface": overflow_words[0], "start": 0.0, "end": 1.0},
            {"word_id": 1, "surface": overflow_words[1], "start": 1.1, "end": 2.2},
        ),
        display_boundary_evidence={
            "1": {"hard_issues": [], "soft_issues": [], "pause_ms": 100}
        },
    )
    overflow_plan = {
        "parent_subtitle_id": "S9502",
        "english": overflow_text,
        "chinese": "中文",
        "word_start": 0,
        "word_end": 1,
        "pages": [
            {"display_page_id": "S9502.P01"},
            {"display_page_id": "S9502.P02"},
        ],
    }
    try:
        podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
            overflow_cue,
            overflow_plan,
            [(0, 0), (1, 1)],
            {"S9502.P01": "中", "S9502.P02": "文"},
            allow_manual_review=True,
        )
    except podcast_learning_video.RenderStructuralOverflowError as exc:
        reasons = {str(item.get("reason") or "") for item in exc.errors}
        assert "manual_page_layout_overflow" in reasons
    else:
        raise AssertionError("an unrenderable manual cut must be rejected")

    unschedulable_cue = podcast_learning_video.Cue(
        index=3,
        start=0.0,
        end=1.5,
        en="Alpha beta",
        zh="中文",
        speaker="manual",
        subtitle_id="S9503",
        word_timing=(
            {"word_id": 0, "surface": "Alpha", "start": 0.0, "end": 1.0},
            {"word_id": 1, "surface": "beta", "start": 0.8, "end": 1.5},
        ),
        display_boundary_evidence={
            "1": {"hard_issues": [], "soft_issues": [], "pause_ms": 200}
        },
    )
    unschedulable_plan = {
        "parent_subtitle_id": "S9503",
        "english": "Alpha beta",
        "chinese": "中文",
        "word_start": 0,
        "word_end": 1,
        "pages": [
            {"display_page_id": "S9503.P01"},
            {"display_page_id": "S9503.P02"},
        ],
    }
    try:
        podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
            unschedulable_cue,
            unschedulable_plan,
            [(0, 0), (1, 1)],
            {"S9503.P01": "中", "S9503.P02": "文"},
            allow_manual_review=True,
        )
    except podcast_learning_video.RenderStructuralOverflowError as exc:
        reasons = {str(item.get("reason") or "") for item in exc.errors}
        assert "no_word_boundary_with_minimum_page_duration" in reasons
    else:
        raise AssertionError("a cut without a legal shared time boundary must fail")


def test_numeric_phrase_moves_as_one_unit_in_both_directions():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        replacement = {
            6: "740",
            7: "billion",
            8: "spend",
        }
        for word_id, surface in replacement.items():
            session.word_ledger[word_id]["surface"] = surface
            session.word_ledger[word_id]["normalized"] = surface.casefold()
        session.cues[0]["original_subtitle"] = session._words_text(
            session.word_ledger, 0, 8
        )

        session.move_suffix_to_next(0, 1)

        assert session.cues[0]["word_end"] == 5
        assert session.cues[1]["word_start"] == 6
        assert session.cues[1]["original_subtitle"].startswith(
            "740 billion spend"
        )
        assert session.history[-1]["word_count"] == 3

    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        replacement = {
            8: "740",
            9: "billion",
            10: "spend",
            11: "today.",
        }
        for word_id, surface in replacement.items():
            session.word_ledger[word_id]["surface"] = surface
            session.word_ledger[word_id]["normalized"] = surface.casefold().strip(".")
        session.cues[0].update(
            {
                "word_end": 7,
                "end_time": session._word_end_time(7),
                "original_subtitle": session._words_text(
                    session.word_ledger, 0, 7
                ),
            }
        )
        session.cues[1].update(
            {
                "word_start": 8,
                "start_time": session._word_start_time(8),
                "original_subtitle": session._words_text(
                    session.word_ledger, 8, 11
                ),
            }
        )

        session.move_prefix_to_previous(1, 1)

        assert session.cues[0]["original_subtitle"].endswith(
            "740 billion spend"
        )
        assert session.cues[1]["original_subtitle"] == "today."
        assert session.history[-1]["word_count"] == 3


def test_numeric_sentence_end_does_not_absorb_the_next_sentence():
    words = [
        {"surface": "in", "normalized": "in"},
        {"surface": "2019.", "normalized": "2019"},
        {"surface": "Right.", "normalized": "right"},
        {"surface": "Next", "normalized": "next"},
    ]

    assert ManualFinalSubtitleSession._expanded_numeric_boundary_word_count(
        words,
        left_word_start=0,
        left_word_end=1,
        right_word_start=2,
        right_word_end=3,
        requested_word_count=1,
        move_to_next=False,
    ) == 1


def test_numeric_clause_comma_does_not_absorb_the_following_article():
    words = [
        {"surface": "early", "normalized": "early"},
        {"surface": "2026,", "normalized": "2026"},
        {"surface": "the", "normalized": "the"},
        {"surface": "global", "normalized": "global"},
    ]

    assert ManualFinalSubtitleSession._expanded_numeric_boundary_word_count(
        words,
        left_word_start=0,
        left_word_end=1,
        right_word_start=2,
        right_word_end=3,
        requested_word_count=1,
        move_to_next=True,
    ) == 1


def test_long_caption_risk_queue_is_read_only_and_parent_scoped():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        before = session.state_fingerprint()
        queue = session.build_display_page_risk_queue()

        assert queue
        item = queue[0]
        assert item["parent_subtitle_id"] == "S0001"
        assert item["word_count"] > 16
        assert item["reasons"]
        assert item["candidate_count"] == 0
        assert session.state_fingerprint() == before


def test_long_caption_risk_queue_plans_candidates_only_for_lightweight_risks():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _splittable_parent_session(Path(temp_dir))
        long_cue = copy.deepcopy(session.cues[0])
        short_cues = [
            {
                **copy.deepcopy(long_cue),
                "cue_id": f"S{index:04d}",
                "word_start": index * 2,
                "word_end": index * 2 + 1,
                "start_time": index * 1000,
                "end_time": index * 1000 + 900,
                "original_subtitle": f"Safe caption {index}.",
                "translated_subtitle": f"普通字幕{index}。",
            }
            for index in range(2, 202)
        ]
        session.cues = [long_cue, *short_cues]
        page_rows = {
            "1": {
                "manual_cue_id": "S0001",
                "display_page_id": "S0001.P01",
                "translated_subtitle": "甲，乙，丙",
                "english_font_size": 56,
                "display_page_review_required": False,
                "display_page_chinese_confirmed": True,
                "display_page_chinese_stale": False,
            }
        }
        for index in range(2, 202):
            page_rows[str(index)] = {
                "manual_cue_id": f"S{index:04d}",
                "display_page_id": f"S{index:04d}.P01",
                "translated_subtitle": f"普通字幕{index}。",
                "english_font_size": 56,
                "display_page_review_required": False,
                "display_page_chinese_confirmed": True,
                "display_page_chinese_stale": False,
            }
        candidate_calls = []
        def tracked_workspace(parent_id, **kwargs):
            candidate_calls.append(parent_id)
            raise AssertionError("risk queue must not eagerly plan candidates")

        session._display_page_model_data = lambda: copy.deepcopy(page_rows)
        session.build_display_page_candidate_workspace = tracked_workspace

        queue = session.build_display_page_risk_queue()

        assert candidate_calls == []
        assert [item["parent_subtitle_id"] for item in queue] == ["S0001"]


if __name__ == "__main__":
    test_manual_page_export_requires_matching_complete_boundary_evidence()
    test_legacy_package_recovers_omitted_saved_cue_boundary_across_move_and_undo()
    test_missing_internal_boundary_evidence_still_fails_closed()
    test_saved_package_keeps_complete_evidence_after_reload_move_undo_and_resave()
    test_loader_rejects_incomplete_or_synthetic_fixed_id_checkpoint()
    test_move_suffix_updates_text_ranges_and_timing_from_word_ledger()
    test_formal_boundary_move_keeps_actual_pages_and_visible_chinese_drafts()
    test_formal_boundary_move_preserves_unaffected_page_identity_and_chinese()
    test_formal_boundary_reflow_failure_rolls_back_instead_of_clearing_pages()
    test_save_rejects_silent_collapse_of_recorded_manual_page_state()
    test_blank_current_pages_recover_only_exact_history_chinese_as_drafts()
    test_page_row_chinese_edits_preserve_parent_and_page_identity()
    test_parent_model_sync_rejects_row_order_drift_before_writing_chinese()
    test_parent_chinese_edit_is_undoable_without_discarding_valid_page_state()
    test_incomplete_page_state_rejects_structural_change_atomically()
    test_edit_artifact_hash_and_embedded_ledger_are_both_verified_on_load()
    test_blocked_checkpoint_reloads_unconfirmed_chinese_page_proposals()
    test_complete_page_edits_recover_when_blocked_checkpoint_lost_page_artifact()
    test_split_parent_into_two_three_four_pages_preserves_frozen_parent()
    test_split_parent_accepts_planner_review_boundary_without_changing_parent()
    test_nearby_boundary_candidates_are_read_only_and_explain_grammar_risk()
    test_split_parent_blocks_unconfirmed_page_proposals_then_saves_idempotently()
    test_repeating_same_page_count_preserves_confirmed_page_chinese()
    test_confirm_one_display_page_chinese_is_scoped_and_persists_after_reload()
    test_boundary_confirmation_clears_only_review_and_rejects_hard()
    test_moving_page_boundary_confirms_new_boundary_and_invalidates_page_identity()
    test_moving_page_boundary_preserves_visible_chinese_and_unaffected_pages()
    test_display_page_model_cache_is_isolated_and_invalidates_on_state_change()
    test_bulk_confirmation_keeps_hard_boundary_blocking()
    test_split_parent_undoes_once_and_rejects_when_no_legal_cut_exists()
    test_manual_page_proposal_can_use_review_boundary_without_relaxing_strict_planning()
    test_model_data_uses_validated_parent_chinese_instead_of_stale_render_plan()
    test_legacy_parent_and_translations_conflict_fails_closed()
    test_manual_save_publishes_one_parent_chinese_record_across_artifacts()
    test_page_chinese_source_parent_copy_allows_page_local_reordering()
    test_legacy_page_chinese_aggregate_detects_stale_pages_without_source_parent_copy()
    test_page_chinese_source_parent_copy_detects_true_parent_drift()
    test_stale_single_page_uses_current_parent_chinese_without_confirmation()
    test_stale_page_chinese_remains_visible_but_cannot_publish_until_confirmed()
    test_reallocated_stale_page_chinese_can_become_authoritative()
    test_legacy_blank_page_edits_recover_visible_stale_chinese_drafts()
    test_blank_intermediate_page_edits_cannot_hide_recovered_stale_drafts()
    test_structural_rebuild_preserves_unconfirmed_stale_page_ownership()
    test_manifest_lookup_uses_hash_and_prefers_manual_package_for_renamed_copy()
    test_original_top_import_restarts_while_manual_final_import_continues()
    test_stale_actual_page_import_opens_current_parent_package_without_reusing_old_pages()
    test_stale_actual_page_import_recovers_only_identity_matched_chinese_as_draft()
    test_move_prefix_and_undo_restore_exact_prior_boundary()
    test_save_rebuilds_short_gap_compensation_after_formal_boundary_move()
    test_undo_redo_round_trip_and_new_edit_truncates_redo_branch()
    test_recovery_draft_round_trip_is_atomic_and_manifest_bound()
    test_merge_only_combines_adjacent_continuous_word_ranges()
    test_manual_english_surface_edit_preserves_word_identity_time_and_reload()
    test_manual_english_surface_edit_rejects_changes_across_multiple_word_ids()
    test_manual_english_surface_span_preserves_raw_ledger_and_renderer_provenance()
    test_manual_english_surface_span_survives_single_word_edit_and_parent_merge()
    test_tail_trim_preserves_or_removes_complete_english_surface_spans_atomically()
    test_actual_page_english_surface_edit_updates_parent_without_moving_page_range()
    test_suppress_single_cue_hides_srt_but_keeps_full_timeline_and_audio()
    test_hide_and_mute_cue_is_parent_scoped_and_can_precede_tail_trim()
    test_hide_and_mute_save_round_trip_binds_derived_audio_and_timeline()
    test_materialized_media_mute_preserves_duration_and_silences_interval()
    test_tail_trim_keeps_earlier_muted_cue_in_one_v2_derivation()
    test_tail_trim_clips_muted_partial_parent_interval()
    test_tail_trim_source_prefers_legacy_mute_original_over_derived_media()
    test_suppressed_cue_does_not_invalidate_visible_actual_page_edits()
    test_renderer_attachment_accepts_a_suppressed_middle_timeline_record()
    test_merge_display_page_with_next_keeps_parent_timeline_and_combines_chinese()
    test_split_one_display_page_preserves_every_other_page_and_parent()
    test_cross_parent_actual_page_merge_is_one_atomic_operation()
    test_cross_parent_merge_does_not_copy_the_entire_existing_history()
    test_save_snapshot_copies_current_state_but_reuses_immutable_history_entries()
    test_cross_parent_actual_page_merge_rolls_back_every_owner_on_failure()
    test_parent_merge_reflows_only_merged_pages_and_undo_restores_page_state()
    test_row_scoped_undo_rejects_an_unrelated_parent_without_popping_history()
    test_free_text_edit_cannot_be_used_as_a_fake_word_boundary_move()
    test_tail_trim_preview_is_pure_and_trim_undo_preserves_frozen_prefix()
    test_result_directory_recovers_one_exact_sibling_source_media()
    test_actual_page_tail_trim_keeps_prior_page_and_undo_restores_all()
    test_tail_trim_reconciles_frozen_page_end_with_final_cue_and_media_cut()
    test_tail_trim_save_materializes_real_audio_and_reuses_exact_decision()
    test_reloaded_tail_trim_undo_restores_original_media_and_full_package()
    test_save_persists_manual_override_and_synthesis_uses_it()
    test_saved_manual_package_reopens_after_the_whole_result_directory_moves()
    test_generation_write_failure_preserves_previous_published_package()
    test_generation_validation_failure_preserves_previous_published_package()
    test_root_manifest_commit_failure_preserves_previous_generation()
    test_manual_package_reuses_only_exact_source_display_page_spans()
    test_manual_package_blocks_cleanly_when_page_translation_validation_returns_error()
    test_manual_package_persists_hash_bound_draft_pages_when_translation_is_required()
    test_manual_draft_reuses_exact_frozen_semantic_page_chinese()
    test_review_page_rows_preserve_boundary_metadata_for_editor_review()
    test_partial_page_artifact_keeps_valid_pages_and_failed_parent_review_row()
    test_saved_reload_can_switch_between_parent_and_actual_page_rows()
    test_manual_save_upgrades_old_page_layout_without_replanning_pages()
    test_unconfirmed_manual_split_proposals_can_move_boundary_but_save_stays_blocked()
    test_parent_split_allows_explicit_high_risk_manual_fallback()
    test_unrenderable_parent_seed_can_be_split_without_a_frozen_page_plan()
    test_explicit_manual_parent_split_can_reach_six_pages()
    test_manual_page_soft_override_preserves_hard_page_invariants()
    test_numeric_phrase_moves_as_one_unit_in_both_directions()
    test_numeric_sentence_end_does_not_absorb_the_next_sentence()
    test_numeric_clause_comma_does_not_absorb_the_following_article()
    test_long_caption_risk_queue_is_read_only_and_parent_scoped()
    test_long_caption_risk_queue_plans_candidates_only_for_lightweight_risks()
    print("Manual final subtitle editor tests passed.")
