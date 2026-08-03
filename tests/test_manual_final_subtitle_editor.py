import json
import tempfile
from pathlib import Path

from app.core.subtitle_processor.manual_final_subtitle_editor import (
    ManualFinalSubtitleEditError,
    ManualFinalSubtitleSession,
)
from app.thread.video_synthesis_thread import resolve_podcast_template_subtitle


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
    _write_json(
        artifact_dir / "word-ledger.json",
        {
            "words": [
                {
                    "word_id": index,
                    "surface": word,
                    "start_ms": index * 100,
                    "end_ms": (index + 1) * 100,
                }
                for index, word in enumerate(words)
            ]
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
    manifest_path = subtitle_dir / "stable-final-manifest.json"
    _write_json(
        manifest_path,
        {
            "coverage_report": str(subtitle_dir / "output-coverage-report.txt"),
            "paths": {"original_top_srt": str(stable_srt)},
            "source_subtitle_paths": {"bilingual_original_top_srt": str(source_srt)},
        },
    )
    session = ManualFinalSubtitleSession.load_for_subtitle(source_srt, work_dir=root / "work")
    return session, source_srt, manifest_path


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


def test_move_prefix_and_undo_restore_exact_prior_boundary():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        before = session.to_model_data()

        session.move_prefix_to_previous(1, 2)
        assert session.cues[0]["original_subtitle"].endswith("out of")
        assert session.cues[1]["original_subtitle"] == "date."
        assert session.undo() is True

        assert session.to_model_data() == before


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


def test_free_text_edit_cannot_be_used_as_a_fake_word_boundary_move():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, _, _ = _session_fixture(Path(temp_dir))
        session.cues[0]["original_subtitle"] = "Right. It means something else."

        try:
            session.move_suffix_to_next(0, 1)
            assert False, "free text must not be silently aligned by word index"
        except ManualFinalSubtitleEditError as exc:
            assert "词级账本" in str(exc)


def test_save_persists_manual_override_and_synthesis_uses_it():
    with tempfile.TemporaryDirectory() as temp_dir:
        session, source_srt, manifest_path = _session_fixture(Path(temp_dir))
        from_manifest = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        assert from_manifest.subtitle_path == source_srt
        session.move_suffix_to_next(0, 2)

        paths = session.save_to_source_folder()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        override = Path(manifest["manual_final_override"]["subtitle_path"])

        assert override == Path(paths["subtitle_path"])
        assert override.exists()
        reloaded = ManualFinalSubtitleSession.load_for_subtitle(
            override, work_dir=Path(temp_dir) / "work"
        )
        assert reloaded.cues[1]["original_subtitle"] == "just completely out of date."
        assert reloaded.artifact_dir == session.artifact_dir
        resolved = resolve_podcast_template_subtitle(
            str(source_srt.with_suffix(".m4a")),
            str(manifest_path.parent / "output.ass"),
        )
        assert Path(resolved) == override


if __name__ == "__main__":
    test_move_suffix_updates_text_ranges_and_timing_from_word_ledger()
    test_move_prefix_and_undo_restore_exact_prior_boundary()
    test_merge_only_combines_adjacent_continuous_word_ranges()
    test_free_text_edit_cannot_be_used_as_a_fake_word_boundary_move()
    test_save_persists_manual_override_and_synthesis_uses_it()
    print("Manual final subtitle editor tests passed.")
