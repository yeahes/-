"""Regression tests for transactional video synthesis and cancellation."""

import io
import json
import shutil
import tempfile
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from app.core.entities import (
    BatchTaskType,
    SynthesisConfig,
    SynthesisTask,
    TranscribeTask,
)
from app.core.subtitle_processor.manual_final_subtitle_editor import (
    ManualFinalSubtitleSession,
)
from app.core.subtitle_processor.stable_artifacts import file_sha256
from app.core.task_factory import TaskFactory
from app.core.utils import podcast_learning_video, video_utils
from app.thread.batch_process_thread import BatchProcessThread, BatchTask
from app.thread.video_synthesis_thread import (
    VideoSynthesisThread,
    ensure_synthesis_subtitle_not_blocked,
    resolve_synthesis_package_inputs,
)
from app.view.video_synthesis_interface import VideoSynthesisInterface
from app.view.subtitle_interface import SubtitleInterface, SubtitleTableModel


class _Signal:
    def __init__(self):
        self.connections = []

    def connect(self, callback, *args):
        self.connections.append((callback, args))


class _LineEditDouble:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = str(value)

    def text(self):
        return self.value


class _ToggleDouble:
    def __init__(self):
        self.enabled = False
        self.visible = False
        self.tooltip = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setVisible(self, value):
        self.visible = bool(value)

    def setToolTip(self, value):
        self.tooltip = str(value)


class _StatusLabelDouble:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = str(value)


class _ThreadDouble:
    def __init__(self):
        self.progress = _Signal()
        self.error = _Signal()
        self.finished = _Signal()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FakeStdin:
    def __init__(self):
        self.closed = False
        self.frames = []

    def write(self, payload):
        self.frames.append(payload)

    def close(self):
        self.closed = True


class _ImmediateProcess:
    def __init__(self, return_code=0, stderr=""):
        self.return_code = return_code
        self.stderr = io.StringIO(stderr)
        self.stdin = _FakeStdin()
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.return_code

    def wait(self, timeout=None):
        return self.return_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _media_inputs(root: Path):
    source = root / "source.mp4"
    subtitle = root / "source.srt"
    source.write_bytes(b"source")
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello.\n\u4f60\u597d\u3002\n",
        encoding="utf-8",
    )
    return source, subtitle


def _blocked_manual_package(
    root: Path,
    reason: str,
    *,
    include_source_media: bool = False,
) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    subtitle = root / "人工终稿字幕.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello.\n\u4f60\u597d\u3002\n",
        encoding="utf-8",
    )
    artifact_dir = root / "人工终稿字幕-artifacts"
    artifact_dir.mkdir()
    timeline = artifact_dir / "final-cue-timeline.json"
    timeline.write_text('{"validation":{"status":"PASS"}}', encoding="utf-8")
    ledger = artifact_dir / "word-ledger.json"
    ledger.write_text(
        '{"words":[{"word_id":0,"surface":"Hello.","start_ms":0,"end_ms":1000}]}',
        encoding="utf-8",
    )
    (artifact_dir / "subtitle-spans.json").write_text(
        '[{"subtitle_id":"S0001","word_start":0,"word_end":0,"original":"Hello."}]',
        encoding="utf-8",
    )
    draft_page_plan = artifact_dir / "manual-draft-page-plan.json"
    draft_page_plan.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "REVIEW",
                "render_plans": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    draft_page_plan_hash = file_sha256(draft_page_plan)
    source_media = root / "source.m4a"
    if include_source_media:
        source_media.write_bytes(b"audio")
    subtitle_hash = file_sha256(subtitle)
    manifest = {
        "schema_version": 2,
        "stable_run_dir": str(root),
        "render_blocked": True,
        "validation_error_codes": [reason],
        "paths": {"original_top_srt": str(subtitle)},
        "paths_sha256": {"original_top_srt": subtitle_hash},
        "manual_draft_page_plan_path": str(draft_page_plan),
        "manual_draft_page_plan_sha256": draft_page_plan_hash,
        "manual_final_override": {
            "schema_version": 2,
            "subtitle_path": str(subtitle),
            "subtitle_sha256": subtitle_hash,
            "artifact_dir": str(artifact_dir),
            "final_cue_timeline_path": str(timeline),
            "final_cue_timeline_sha256": file_sha256(timeline),
            "word_ledger_path": str(ledger),
            "word_ledger_sha256": file_sha256(ledger),
            "manual_draft_page_plan_path": str(draft_page_plan),
            "manual_draft_page_plan_sha256": draft_page_plan_hash,
            "render_blocked": True,
            "render_block_reason": reason,
            "source_media_path": str(source_media) if include_source_media else "",
        },
        "source_media_path": str(source_media) if include_source_media else "",
    }
    manifest_path = root / "stable-final-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path, subtitle


def _synthesis_package(
    root: Path,
    *,
    with_tail_trim: bool,
) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    subtitle = root / "final.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello.\n\u4f60\u597d\u3002\n",
        encoding="utf-8",
    )
    source_media = root / "source.m4a"
    source_media.write_bytes(b"source audio")
    selected_media = source_media
    manifest = {
        "schema_version": 2,
        "stable_run_dir": str(root),
        "render_blocked": False,
        "paths": {"original_top_srt": str(subtitle)},
        "paths_sha256": {"original_top_srt": file_sha256(subtitle)},
        "source_media_path": str(source_media),
    }
    if with_tail_trim:
        selected_media = root / "source-tail-trimmed.m4a"
        selected_media.write_bytes(b"trimmed source audio")
        manifest["source_media_path"] = str(selected_media)
        manifest["tail_trim"] = {
            "derived_media_path": str(selected_media),
            "derived_media_sha256": file_sha256(selected_media),
        }
    manifest_path = root / "stable-final-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path, selected_media


def _expect_raises(exc_type, callback):
    try:
        callback()
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")


def test_add_subtitles_uses_unique_subtitle_copies_and_atomic_output():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source, subtitle = _media_inputs(root)
        outputs = [root / "first.mp4", root / "second.mp4"]
        seen_subtitles = []
        staged_outputs = []

        def fake_run(command, **_kwargs):
            subtitle_input = Path(command[command.index("-i", 3) + 1])
            staged_output = Path(command[-1])
            assert subtitle_input.exists()
            assert staged_output.parent == outputs[0].parent
            assert staged_output not in outputs
            seen_subtitles.append(subtitle_input)
            staged_outputs.append(staged_output)
            staged_output.write_bytes(b"complete-video")

        with patch.object(video_utils, "_run_ffmpeg_process", side_effect=fake_run):
            for output in outputs:
                video_utils.add_subtitles(
                    str(source), str(subtitle), str(output), soft_subtitle=True
                )

        assert len(set(seen_subtitles)) == 2
        assert all(not path.exists() for path in seen_subtitles)
        assert all(output.read_bytes() == b"complete-video" for output in outputs)
        assert all(not path.exists() for path in staged_outputs)


def test_soft_subtitle_failure_preserves_existing_output_and_stderr():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source, subtitle = _media_inputs(root)
        output = root / "final.mp4"
        output.write_bytes(b"previous-good-video")

        def fake_popen(command, **_kwargs):
            Path(command[-1]).write_bytes(b"partial")
            return _ImmediateProcess(7, "encoder exploded\n")

        with patch.object(video_utils.subprocess, "Popen", side_effect=fake_popen):
            exc = _expect_raises(
                RuntimeError,
                lambda: video_utils.add_subtitles(
                    str(source), str(subtitle), str(output), soft_subtitle=True
                ),
            )

        assert "encoder exploded" in str(exc)
        assert output.read_bytes() == b"previous-good-video"
        assert list(root.glob(".*.mp4")) == []


def test_video_to_audio_failure_preserves_existing_target():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.mp4"
        output = root / "source.wav"
        source.write_bytes(b"source")
        output.write_bytes(b"previous-good-audio")

        def fake_popen(command, **_kwargs):
            Path(command[-1]).write_bytes(b"partial")
            return _ImmediateProcess(8, "audio encoder failed\n")

        with patch.object(video_utils.subprocess, "Popen", side_effect=fake_popen):
            success = video_utils.video2audio(str(source), str(output))

        assert success is False
        assert output.read_bytes() == b"previous-good-audio"
        assert list(root.glob(".*.wav")) == []


def test_ffmpeg_start_failure_keeps_original_exception_and_existing_output():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source, subtitle = _media_inputs(root)
        output = root / "final.mp4"
        output.write_bytes(b"previous-good-video")

        with patch.object(video_utils, "check_cuda_available", return_value=False), patch.object(
            video_utils.subprocess,
            "Popen",
            side_effect=FileNotFoundError("ffmpeg executable missing"),
        ):
            exc = _expect_raises(
                RuntimeError,
                lambda: video_utils.add_subtitles(
                    str(source), str(subtitle), str(output), soft_subtitle=False
                ),
            )

        assert "ffmpeg executable missing" in str(exc)
        assert "process" not in str(exc).lower()
        assert output.read_bytes() == b"previous-good-video"


def test_podcast_renderer_failure_preserves_old_video_and_ffmpeg_error():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source, subtitle = _media_inputs(root)
        output = root / "podcast.mp4"
        output.write_bytes(b"previous-good-video")
        staged = []

        def fake_popen(command, **kwargs):
            staged_output = Path(command[-1])
            staged.append(staged_output)
            staged_output.write_bytes(b"partial")
            stderr_target = kwargs["stderr"]
            stderr_target.write(b"libx264 initialization failed\n")
            stderr_target.flush()
            return _ImmediateProcess(return_code=9)

        with patch.object(podcast_learning_video, "get_duration", return_value=1.0), patch.object(
            podcast_learning_video, "FPS", 1
        ), patch.object(
            podcast_learning_video, "load_or_generate_vocab_plan", return_value={}
        ), patch.object(
            podcast_learning_video, "make_base", return_value=Image.new("RGBA", (2, 2))
        ), patch.object(
            podcast_learning_video, "make_avatars", return_value=(None, None)
        ), patch.object(
            podcast_learning_video, "draw_frame", return_value=Image.new("RGB", (2, 2))
        ), patch.object(
            podcast_learning_video.subprocess, "Popen", side_effect=fake_popen
        ):
            exc = _expect_raises(
                RuntimeError,
                lambda: podcast_learning_video.render_podcast_learning_video(
                    str(source), str(subtitle), str(output)
                ),
            )

        assert "libx264 initialization failed" in str(exc)
        assert output.read_bytes() == b"previous-good-video"
        assert staged and all(not path.exists() for path in staged)


def test_podcast_broken_pipe_reports_ffmpeg_stderr():
    class _BrokenPipeStdin(_FakeStdin):
        def write(self, payload):
            raise BrokenPipeError("pipe closed")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source, subtitle = _media_inputs(root)
        output = root / "podcast.mp4"
        output.write_bytes(b"previous-good-video")

        def fake_popen(command, **kwargs):
            Path(command[-1]).write_bytes(b"partial")
            kwargs["stderr"].write(b"disk full while writing output\n")
            kwargs["stderr"].flush()
            process = _ImmediateProcess(return_code=5)
            process.stdin = _BrokenPipeStdin()
            return process

        with patch.object(podcast_learning_video, "get_duration", return_value=1.0), patch.object(
            podcast_learning_video, "FPS", 1
        ), patch.object(
            podcast_learning_video, "load_or_generate_vocab_plan", return_value={}
        ), patch.object(
            podcast_learning_video, "make_base", return_value=Image.new("RGBA", (2, 2))
        ), patch.object(
            podcast_learning_video, "make_avatars", return_value=(None, None)
        ), patch.object(
            podcast_learning_video, "draw_frame", return_value=Image.new("RGB", (2, 2))
        ), patch.object(
            podcast_learning_video.subprocess, "Popen", side_effect=fake_popen
        ):
            exc = _expect_raises(
                RuntimeError,
                lambda: podcast_learning_video.render_podcast_learning_video(
                    str(source), str(subtitle), str(output)
                ),
            )

        assert "disk full while writing output" in str(exc)
        assert output.read_bytes() == b"previous-good-video"


def test_video_synthesis_stop_terminates_registered_process():
    task = SynthesisTask(
        video_path="source.m4a",
        subtitle_path="source.srt",
        output_path="output.mp4",
        synthesis_config=SynthesisConfig(podcast_learning_template=True),
    )
    process = _ImmediateProcess()
    process.return_code = None
    thread = VideoSynthesisThread(task)

    def fake_render(*_args, **kwargs):
        kwargs["process_callback"](process)
        thread.stop()
        if kwargs["cancel_check"]():
            raise video_utils.MediaSynthesisCancelled("video synthesis cancelled")
        raise AssertionError("cancel_check must observe stop()")

    with patch(
        "app.thread.video_synthesis_thread.resolve_podcast_template_subtitle",
        return_value="source.srt",
    ), patch(
        "app.thread.video_synthesis_thread.render_podcast_learning_video",
        side_effect=fake_render,
    ):
        thread.run()

    assert process.terminated
    assert thread.is_cancelled()


def test_direct_srt_from_blocked_package_is_rejected_for_every_render_mode():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _, subtitle = _media_inputs(root)
        (root / "stable-final-manifest.json").write_text(
            '{"render_blocked":true,"paths":{"original_top_srt":"'
            + str(subtitle).replace("\\", "\\\\")
            + '"}}',
            encoding="utf-8",
        )

        exc = _expect_raises(
            RuntimeError,
            lambda: ensure_synthesis_subtitle_not_blocked(str(subtitle)),
        )

        assert "阻止合成" in str(exc)


def test_manual_draft_mode_is_explicit_and_uses_an_isolated_output_name():
    fake_cfg = MagicMock()
    fake_cfg.podcast_learning_template.value = True
    fake_cfg.podcast_template_style.value = "文章单词"
    fake_cfg.podcast_template_english_only.value = False
    fake_cfg.need_video.value = True
    fake_cfg.soft_subtitle.value = True

    with patch("app.core.task_factory.cfg", fake_cfg):
        formal_task = TaskFactory.create_synthesis_task(
            "episode.m4a",
            "stable-final-manifest.json",
        )
        draft_task = TaskFactory.create_synthesis_task(
            "episode.m4a",
            "stable-final-manifest.json",
            manual_draft_mode=True,
        )

    assert SynthesisConfig().manual_draft_mode is False
    assert formal_task.synthesis_config.manual_draft_mode is False
    assert draft_task.synthesis_config.manual_draft_mode is True
    assert Path(formal_task.output_path).name == "【文章单词模板】episode.mp4"
    assert Path(draft_task.output_path).name == "【人工草稿】episode.mp4"
    assert Path(formal_task.output_path) != Path(draft_task.output_path)


def test_english_only_podcast_tasks_use_isolated_output_names_for_both_templates():
    cases = (
        ("文章单词", "【文章单词模板-英文字幕版】episode.mp4"),
        ("暗色播客", "【英语学习模板-英文字幕版】episode.mp4"),
    )
    for template_style, expected_name in cases:
        fake_cfg = MagicMock()
        fake_cfg.podcast_learning_template.value = True
        fake_cfg.podcast_template_style.value = template_style
        fake_cfg.podcast_template_english_only.value = True
        fake_cfg.podcast_template_ai_vocab.value = True
        fake_cfg.need_video.value = True
        fake_cfg.soft_subtitle.value = True

        with patch("app.core.task_factory.cfg", fake_cfg):
            task = TaskFactory.create_synthesis_task(
                "episode.m4a",
                "stable-final-manifest.json",
            )

        assert Path(task.output_path).name == expected_name
        assert task.synthesis_config.podcast_template_english_only is True

    assert SynthesisConfig().podcast_template_english_only is False


def test_english_only_action_persists_and_enables_podcast_template():
    interface = SimpleNamespace(
        english_only_action=MagicMock(),
        podcast_learning_template_action=MagicMock(),
        need_video_action=MagicMock(),
        update_podcast_template_fields=MagicMock(),
    )
    fake_cfg = MagicMock()

    with patch("app.view.video_synthesis_interface.cfg", fake_cfg):
        VideoSynthesisInterface.on_english_only_changed(interface, True)

    fake_cfg.set.assert_any_call(fake_cfg.podcast_template_english_only, True)
    fake_cfg.set.assert_any_call(fake_cfg.podcast_learning_template, True)
    fake_cfg.set.assert_any_call(fake_cfg.need_video, True)
    interface.english_only_action.setChecked.assert_called_once_with(True)
    interface.podcast_learning_template_action.setChecked.assert_called_once_with(True)
    interface.need_video_action.setChecked.assert_called_once_with(True)
    interface.update_podcast_template_fields.assert_called_once_with()


def test_multiline_podcast_title_is_preserved_by_ui_and_task_snapshot():
    title = "中国年轻人为何\n不爱留学了？"
    title_input = MagicMock()
    title_input.toPlainText.return_value = title
    interface = SimpleNamespace(podcast_title_input=title_input)
    view_cfg = MagicMock()

    with patch("app.view.video_synthesis_interface.cfg", view_cfg):
        VideoSynthesisInterface.save_podcast_title(interface)

    view_cfg.set.assert_called_once_with(view_cfg.podcast_template_title, title)

    task_cfg = MagicMock()
    task_cfg.podcast_learning_template.value = True
    task_cfg.podcast_template_style.value = "文章单词"
    task_cfg.podcast_template_ai_vocab.value = True
    task_cfg.podcast_template_english_only.value = False
    task_cfg.podcast_template_title.value = title
    task_cfg.need_video.value = True
    task_cfg.soft_subtitle.value = True
    with patch("app.core.task_factory.cfg", task_cfg):
        task = TaskFactory.create_synthesis_task(
            "episode.m4a",
            "stable-final-manifest.json",
        )

    assert task.synthesis_config.podcast_template_title == title


def test_manual_draft_gate_only_allows_page_quality_blockers():
    allowed_reasons = (
        "render_structural_overflow",
        "manual_page_translation_required",
        "manual_page_translation_invalid",
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        for reason in allowed_reasons:
            manifest, subtitle = _blocked_manual_package(root / reason, reason)

            _expect_raises(
                RuntimeError,
                lambda manifest=manifest: resolve_synthesis_package_inputs(manifest),
            )
            _expect_raises(
                RuntimeError,
                lambda subtitle=subtitle: ensure_synthesis_subtitle_not_blocked(
                    subtitle
                ),
            )

            media, resolved_manifest = resolve_synthesis_package_inputs(
                manifest,
                allow_manual_draft=True,
            )
            assert media == ""
            assert Path(resolved_manifest) == manifest
            assert (
                ensure_synthesis_subtitle_not_blocked(
                    subtitle,
                    allow_manual_draft=True,
                )
                is None
            )


def test_manual_draft_gate_rejects_unknown_blockers_and_tampered_srt():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        unknown_manifest, unknown_subtitle = _blocked_manual_package(
            root / "unknown",
            "final_timeline_invalid",
        )
        for callback in (
            lambda: resolve_synthesis_package_inputs(
                unknown_manifest,
                allow_manual_draft=True,
            ),
            lambda: ensure_synthesis_subtitle_not_blocked(
                unknown_subtitle,
                allow_manual_draft=True,
            ),
        ):
            exc = _expect_raises(RuntimeError, callback)
            assert "拒绝合成" in str(exc)

        tampered_manifest, tampered_subtitle = _blocked_manual_package(
            root / "tampered",
            "manual_page_translation_required",
        )
        tampered_subtitle.write_text(
            tampered_subtitle.read_text(encoding="utf-8") + "tampered",
            encoding="utf-8",
        )
        for callback in (
            lambda: resolve_synthesis_package_inputs(
                tampered_manifest,
                allow_manual_draft=True,
            ),
            lambda: ensure_synthesis_subtitle_not_blocked(
                tampered_subtitle,
                allow_manual_draft=True,
            ),
        ):
            exc = _expect_raises(RuntimeError, callback)
            assert "哈希" in str(exc)


def test_manual_draft_gate_rejects_tampered_timeline_or_word_ledger():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        for artifact_key in ("final_cue_timeline_path", "word_ledger_path"):
            manifest_path, subtitle = _blocked_manual_package(
                root / artifact_key,
                "manual_page_translation_required",
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact_path = Path(manifest["manual_final_override"][artifact_key])
            artifact_path.write_text(
                artifact_path.read_text(encoding="utf-8") + "\ntampered",
                encoding="utf-8",
            )

            for callback in (
                lambda manifest_path=manifest_path: resolve_synthesis_package_inputs(
                    manifest_path,
                    allow_manual_draft=True,
                ),
                lambda subtitle=subtitle: ensure_synthesis_subtitle_not_blocked(
                    subtitle,
                    allow_manual_draft=True,
                ),
            ):
                exc = _expect_raises(RuntimeError, callback)
                assert "时间轴或词级账本哈希不一致" in str(exc)


def test_manual_draft_gate_rejects_missing_tampered_or_foreign_page_plan():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        for case in ("missing", "tampered", "foreign"):
            manifest_path, subtitle = _blocked_manual_package(
                root / case,
                "manual_page_translation_required",
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            draft_path = Path(manifest["manual_draft_page_plan_path"])

            if case == "missing":
                draft_path.unlink()
            elif case == "tampered":
                draft_path.write_text(
                    draft_path.read_text(encoding="utf-8") + "\ntampered",
                    encoding="utf-8",
                )
            else:
                foreign_path = root / "foreign-artifacts" / "manual-draft-page-plan.json"
                foreign_path.parent.mkdir(exist_ok=True)
                shutil.copyfile(draft_path, foreign_path)
                foreign_hash = file_sha256(foreign_path)
                manifest["manual_draft_page_plan_path"] = str(foreign_path)
                manifest["manual_draft_page_plan_sha256"] = foreign_hash
                manifest["manual_final_override"][
                    "manual_draft_page_plan_path"
                ] = str(foreign_path)
                manifest["manual_final_override"][
                    "manual_draft_page_plan_sha256"
                ] = foreign_hash
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            for callback in (
                lambda manifest_path=manifest_path: resolve_synthesis_package_inputs(
                    manifest_path,
                    allow_manual_draft=True,
                ),
                lambda subtitle=subtitle: ensure_synthesis_subtitle_not_blocked(
                    subtitle,
                    allow_manual_draft=True,
                ),
            ):
                exc = _expect_raises(RuntimeError, callback)
                assert "分页计划" in str(exc)


def test_video_synthesis_interface_tracks_only_explicit_manual_draft_inputs():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        media = root / "source.m4a"
        media.write_bytes(b"audio")
        manifest = root / "stable-final-manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        ordinary_subtitle = root / "ordinary.srt"
        ordinary_subtitle.write_text("subtitle", encoding="utf-8")
        interface = MagicMock()
        interface.subtitle_input = _LineEditDouble()
        interface.video_input = _LineEditDouble()
        interface._manual_draft_mode = False
        interface.tr.side_effect = lambda value: value

        with patch(
            "app.view.video_synthesis_interface.resolve_synthesis_package_inputs",
            return_value=(str(media), str(manifest)),
        ) as resolver:
            VideoSynthesisInterface.set_inputs(
                interface,
                str(media),
                str(manifest),
                manual_draft_mode=True,
            )

        resolver.assert_called_once_with(
            manifest,
            str(media),
            allow_manual_draft=True,
        )
        assert interface._manual_draft_mode is True
        assert interface.subtitle_input.text() == str(manifest)

        VideoSynthesisInterface.set_inputs(
            interface,
            str(media),
            str(ordinary_subtitle),
        )
        assert interface._manual_draft_mode is False
        assert interface.subtitle_input.text() == str(ordinary_subtitle)


def test_subtitle_editor_restores_manual_draft_for_renamed_subtitle_copy():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        manifest, manual_subtitle = _blocked_manual_package(
            root / "work" / "manual",
            "manual_page_translation_required",
        )
        copied_subtitle = root / "external" / "renamed-copy.srt"
        copied_subtitle.parent.mkdir()
        shutil.copyfile(manual_subtitle, copied_subtitle)
        interface = SimpleNamespace(
            manual_final_session=None,
            _manual_package_manifest_path="",
            _manual_review_mark_count=0,
            _review_mark_rows=[],
            _review_mark_request_id=0,
            _manual_save_request_id=0,
            _manual_save_in_progress=False,
            model=SubtitleTableModel({}),
            next_review_action=_ToggleDouble(),
            manual_final_save_action=_ToggleDouble(),
            manual_final_undo_action=_ToggleDouble(),
            manual_final_synthesis_action=_ToggleDouble(),
            manual_draft_synthesis_action=_ToggleDouble(),
            subtitle_table=_ToggleDouble(),
            subtitle_path="",
            status_label=_StatusLabelDouble(),
            tr=lambda value: value,
            _load_manual_final_review_marks=lambda _session: None,
            _set_manual_clean_checkpoint=lambda: None,
        )
        interface._invalidate_manual_final_save = MethodType(
            SubtitleInterface._invalidate_manual_final_save,
            interface,
        )
        interface._apply_manual_final_session = MethodType(
            SubtitleInterface._apply_manual_final_session,
            interface,
        )
        interface._restore_saved_manual_package_actions = MethodType(
            SubtitleInterface._restore_saved_manual_package_actions,
            interface,
        )
        fake_cfg = MagicMock()
        fake_cfg.work_dir.value = str(root / "work")

        with patch("app.view.subtitle_interface.cfg", fake_cfg):
            SubtitleInterface._load_manual_final_session(interface, copied_subtitle)

        assert interface.manual_final_session is not None
        assert interface.manual_final_session.subtitle_path == copied_subtitle.resolve()
        assert interface.manual_final_session.manifest_path == manifest.resolve()
        assert interface._manual_package_manifest_path == str(manifest.resolve())
        assert interface.manual_draft_synthesis_action.enabled is True
        assert interface.manual_draft_synthesis_action.visible is True
        assert interface.manual_final_synthesis_action.enabled is False


def test_video_synthesis_interface_auto_links_renamed_manual_subtitle_copy():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        manifest, manual_subtitle = _blocked_manual_package(
            root / "work" / "manual",
            "manual_page_translation_required",
            include_source_media=True,
        )
        source_media = manifest.parent / "source.m4a"
        copied_subtitle = root / "external" / "renamed-copy.srt"
        copied_subtitle.parent.mkdir()
        shutil.copyfile(manual_subtitle, copied_subtitle)
        interface = MagicMock()
        interface.subtitle_input = _LineEditDouble()
        interface.video_input = _LineEditDouble()
        interface._manual_draft_mode = False
        interface.tr.side_effect = lambda value: value
        fake_cfg = MagicMock()
        fake_cfg.work_dir.value = str(root / "work")

        with patch("app.view.video_synthesis_interface.cfg", fake_cfg), patch(
            "app.view.video_synthesis_interface.InfoBar.warning"
        ) as warning:
            VideoSynthesisInterface.set_inputs(interface, "", str(copied_subtitle))

        assert interface.subtitle_input.text() == str(manifest.resolve())
        assert interface.video_input.text() == str(source_media)
        assert interface._manual_draft_mode is True
        warning.assert_called_once()

        unknown_subtitle = root / "external" / "unknown.srt"
        unknown_subtitle.write_text("unrelated subtitle", encoding="utf-8")
        unknown_interface = MagicMock()
        unknown_interface.subtitle_input = _LineEditDouble()
        unknown_interface.video_input = _LineEditDouble()
        unknown_interface._manual_draft_mode = False
        unknown_interface.tr.side_effect = lambda value: value
        with patch("app.view.video_synthesis_interface.cfg", fake_cfg):
            VideoSynthesisInterface.set_inputs(
                unknown_interface,
                "",
                str(unknown_subtitle),
            )

        assert unknown_interface.subtitle_input.text() == str(unknown_subtitle)
        assert unknown_interface.video_input.text() == ""
        assert unknown_interface._manual_draft_mode is False


def test_registered_external_subtitle_with_mismatched_hash_is_not_auto_linked():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        manifest, manual_subtitle = _blocked_manual_package(
            root / "work" / "manual",
            "manual_page_translation_required",
            include_source_media=True,
        )
        external_subtitle = root / "external" / "registered-copy.srt"
        external_subtitle.parent.mkdir()
        shutil.copyfile(manual_subtitle, external_subtitle)
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_payload["source_subtitle_paths"] = {
            "bilingual_original_top_srt": str(external_subtitle)
        }
        manifest.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        external_subtitle.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nTampered.\n\u5df2\u7be1\u6539\u3002\n",
            encoding="utf-8",
        )

        resolved = ManualFinalSubtitleSession.find_manifest_for_subtitle(
            external_subtitle,
            work_dir=root / "work",
        )
        assert resolved is None

        interface = MagicMock()
        interface.subtitle_input = _LineEditDouble()
        interface.video_input = _LineEditDouble()
        interface._manual_draft_mode = False
        interface.tr.side_effect = lambda value: value
        fake_cfg = MagicMock()
        fake_cfg.work_dir.value = str(root / "work")

        with patch("app.view.video_synthesis_interface.cfg", fake_cfg):
            VideoSynthesisInterface.set_inputs(
                interface,
                "",
                str(external_subtitle),
            )

        assert interface.subtitle_input.text() == str(external_subtitle)
        assert interface.video_input.text() == ""
        assert interface._manual_draft_mode is False


def test_video_synthesis_thread_forwards_manual_draft_mode_to_safety_layers():
    task = SynthesisTask(
        video_path="source.m4a",
        subtitle_path="stable-final-manifest.json",
        output_path="【人工草稿】source.mp4",
        synthesis_config=SynthesisConfig(
            podcast_learning_template=True,
            podcast_template_style="文章单词",
            manual_draft_mode=True,
        ),
    )
    thread = VideoSynthesisThread(task)

    with patch(
        "app.thread.video_synthesis_thread.ensure_synthesis_subtitle_not_blocked"
    ) as ensure_gate, patch(
        "app.thread.video_synthesis_thread.resolve_podcast_template_subtitle",
        return_value="人工终稿字幕.srt",
    ) as resolver, patch(
        "app.thread.video_synthesis_thread.render_podcast_learning_video"
    ) as renderer:
        thread.run()

    ensure_gate.assert_called_once_with(
        "stable-final-manifest.json",
        allow_manual_draft=True,
    )
    resolver.assert_called_once_with(
        "source.m4a",
        "stable-final-manifest.json",
        allow_manual_draft=True,
    )
    assert renderer.call_args.kwargs["allow_manual_draft"] is True


def test_video_synthesis_thread_rejects_manual_draft_outside_article_template():
    invalid_configs = (
        SynthesisConfig(
            podcast_learning_template=False,
            podcast_template_style="文章单词",
            manual_draft_mode=True,
        ),
        SynthesisConfig(
            podcast_learning_template=True,
            podcast_template_style="暗色播客",
            manual_draft_mode=True,
        ),
    )
    for config in invalid_configs:
        task = SynthesisTask(
            video_path="source.m4a",
            subtitle_path="stable-final-manifest.json",
            output_path="【人工草稿】source.mp4",
            synthesis_config=config,
        )
        thread = VideoSynthesisThread(task)
        errors = []
        thread.error.connect(errors.append)

        with patch(
            "app.thread.video_synthesis_thread.ensure_synthesis_subtitle_not_blocked"
        ) as ensure_gate, patch(
            "app.thread.video_synthesis_thread.add_subtitles"
        ) as ordinary_renderer, patch(
            "app.thread.video_synthesis_thread.render_podcast_learning_video"
        ) as article_renderer:
            thread.run()

        assert errors == ["人工草稿只能使用文章单词模板合成。"]
        ensure_gate.assert_not_called()
        ordinary_renderer.assert_not_called()
        article_renderer.assert_not_called()


def test_video_synthesis_thread_rejects_tail_trim_outside_podcast_template():
    config = SynthesisConfig(
        podcast_learning_template=False,
        podcast_template_style="\u6587\u7ae0\u5355\u8bcd",
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        manifest_path, media_path = _synthesis_package(
            root / "ordinary",
            with_tail_trim=True,
        )
        task = SynthesisTask(
            video_path=str(media_path),
            subtitle_path=str(manifest_path),
            output_path=str(root / "ordinary.mp4"),
            synthesis_config=config,
        )
        thread = VideoSynthesisThread(task)
        errors = []
        thread.error.connect(errors.append)

        with patch(
            "app.thread.video_synthesis_thread.ensure_synthesis_subtitle_not_blocked"
        ) as ensure_gate, patch(
            "app.thread.video_synthesis_thread.resolve_podcast_template_subtitle"
        ) as resolver, patch(
            "app.thread.video_synthesis_thread.add_subtitles"
        ) as ordinary_renderer, patch(
            "app.thread.video_synthesis_thread.render_podcast_learning_video"
        ) as article_renderer:
            thread.run()

        assert errors == ["尾部裁剪终稿第一版只能使用静态播客模板合成。"]
        ensure_gate.assert_not_called()
        resolver.assert_not_called()
        ordinary_renderer.assert_not_called()
        article_renderer.assert_not_called()


def test_video_synthesis_thread_allows_tail_trim_for_podcast_templates():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        template_styles = ("文章单词", "暗色播客")
        for index, template_style in enumerate(template_styles):
            manifest_path, media_path = _synthesis_package(
                root / str(index),
                with_tail_trim=True,
            )
            task = SynthesisTask(
                video_path=str(media_path),
                subtitle_path=str(manifest_path),
                output_path=str(root / f"podcast-{index}.mp4"),
                synthesis_config=SynthesisConfig(
                    podcast_learning_template=True,
                    podcast_template_style=template_style,
                ),
            )
            thread = VideoSynthesisThread(task)
            errors = []
            thread.error.connect(errors.append)

            with patch(
                "app.thread.video_synthesis_thread.ensure_synthesis_subtitle_not_blocked"
            ) as ensure_gate, patch(
                "app.thread.video_synthesis_thread.resolve_podcast_template_subtitle",
                return_value="final.srt",
            ) as resolver, patch(
                "app.thread.video_synthesis_thread.add_subtitles"
            ) as ordinary_renderer, patch(
                "app.thread.video_synthesis_thread.render_podcast_learning_video"
            ) as article_renderer:
                thread.run()

            assert errors == []
            ensure_gate.assert_called_once_with(
                str(manifest_path),
                allow_manual_draft=False,
            )
            resolver.assert_called_once_with(
                str(media_path),
                str(manifest_path),
                allow_manual_draft=False,
            )
            ordinary_renderer.assert_not_called()
            article_renderer.assert_called_once()


def test_video_synthesis_thread_allows_ordinary_package_without_tail_trim():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        manifest_path, media_path = _synthesis_package(
            root / "ordinary",
            with_tail_trim=False,
        )
        task = SynthesisTask(
            video_path=str(media_path),
            subtitle_path=str(manifest_path),
            output_path=str(root / "ordinary.mp4"),
            synthesis_config=SynthesisConfig(podcast_learning_template=False),
        )
        thread = VideoSynthesisThread(task)
        errors = []
        thread.error.connect(errors.append)

        with patch(
            "app.thread.video_synthesis_thread.ensure_synthesis_subtitle_not_blocked"
        ) as ensure_gate, patch(
            "app.thread.video_synthesis_thread.add_subtitles"
        ) as ordinary_renderer, patch(
            "app.thread.video_synthesis_thread.render_podcast_learning_video"
        ) as article_renderer:
            thread.run()

        assert errors == []
        ensure_gate.assert_called_once_with(
            str(manifest_path),
            allow_manual_draft=False,
        )
        ordinary_renderer.assert_called_once()
        article_renderer.assert_not_called()


def test_batch_cancel_removes_only_target_task_from_queue():
    batch = BatchProcessThread()
    first = BatchTask("first.m4a", BatchTaskType.FULL_PROCESS)
    second = BatchTask("second.m4a", BatchTaskType.FULL_PROCESS)
    first.current_thread = _ThreadDouble()
    batch.current_tasks = {first.file_path: first, second.file_path: second}
    batch.task_queue.put(first)
    batch.task_queue.put(second)

    batch.stop_task(first.file_path)

    with batch.task_queue.mutex:
        queued_paths = [item.file_path for item in batch.task_queue.queue]
    assert queued_paths == [second.file_path]
    assert second.file_path in batch.current_tasks
    assert first.current_thread.stopped


def test_full_process_propagates_source_audio_and_article_state():
    batch = BatchProcessThread()
    batch_task = BatchTask("report-anchor.m4a", BatchTaskType.FULL_PROCESS)
    old_thread = _ThreadDouble()
    batch_task.current_thread = old_thread
    batch.threads = [old_thread]
    subtitle_task = MagicMock()
    batch.factory = MagicMock()
    batch.factory.create_subtitle_task.return_value = subtitle_task
    next_thread = _ThreadDouble()
    transcribe_task = TranscribeTask(output_path="transcript.srt")
    transcribe_task.source_audio_path = "original-source.m4a"
    transcribe_task.article_reference_text = "Reference article"
    transcribe_task.article_context_data = {"title": "Reference"}
    transcribe_task.use_article_reference_assist = True
    transcribe_task.use_article_translation_terms = True

    with patch(
        "app.thread.batch_process_thread.SubtitleThread", return_value=next_thread
    ):
        batch.on_full_process_finished(batch_task, transcribe_task)

    batch.factory.create_subtitle_task.assert_called_once_with(
        "transcript.srt",
        "report-anchor.m4a",
        need_next_task=True,
        source_audio_path="original-source.m4a",
        article_reference_text="Reference article",
        article_context_data={"title": "Reference"},
        use_article_reference_assist=True,
        use_article_translation_terms=True,
    )
    assert next_thread.started


if __name__ == "__main__":
    test_add_subtitles_uses_unique_subtitle_copies_and_atomic_output()
    test_soft_subtitle_failure_preserves_existing_output_and_stderr()
    test_video_to_audio_failure_preserves_existing_target()
    test_ffmpeg_start_failure_keeps_original_exception_and_existing_output()
    test_podcast_renderer_failure_preserves_old_video_and_ffmpeg_error()
    test_podcast_broken_pipe_reports_ffmpeg_stderr()
    test_video_synthesis_stop_terminates_registered_process()
    test_direct_srt_from_blocked_package_is_rejected_for_every_render_mode()
    test_manual_draft_mode_is_explicit_and_uses_an_isolated_output_name()
    test_english_only_podcast_tasks_use_isolated_output_names_for_both_templates()
    test_english_only_action_persists_and_enables_podcast_template()
    test_multiline_podcast_title_is_preserved_by_ui_and_task_snapshot()
    test_manual_draft_gate_only_allows_page_quality_blockers()
    test_manual_draft_gate_rejects_unknown_blockers_and_tampered_srt()
    test_manual_draft_gate_rejects_tampered_timeline_or_word_ledger()
    test_manual_draft_gate_rejects_missing_tampered_or_foreign_page_plan()
    test_video_synthesis_interface_tracks_only_explicit_manual_draft_inputs()
    test_subtitle_editor_restores_manual_draft_for_renamed_subtitle_copy()
    test_video_synthesis_interface_auto_links_renamed_manual_subtitle_copy()
    test_registered_external_subtitle_with_mismatched_hash_is_not_auto_linked()
    test_video_synthesis_thread_forwards_manual_draft_mode_to_safety_layers()
    test_video_synthesis_thread_rejects_manual_draft_outside_article_template()
    test_video_synthesis_thread_rejects_tail_trim_outside_podcast_template()
    test_video_synthesis_thread_allows_tail_trim_for_podcast_templates()
    test_video_synthesis_thread_allows_ordinary_package_without_tail_trim()
    test_batch_cancel_removes_only_target_task_from_queue()
    test_full_process_propagates_source_audio_and_article_state()
    print("video synthesis safety tests passed")
