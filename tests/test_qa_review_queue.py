import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_qa_summary import write_qa_review_artifacts


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_review_queue_uses_final_times_and_excludes_invalid_audit_mapping():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        artifact_dir = root / "sample-artifacts"
        source_dir = root / "source"
        artifact_dir.mkdir()
        source_dir.mkdir()
        _write_json(
            artifact_dir / "run-manifest.json",
            {
                "subtitle_count": 2,
                "translation_model": "test-model",
                "code_commit": "test-commit",
            },
        )
        _write_json(
            artifact_dir / "subtitle-spans.json",
            [
                {"subtitle_id": "S0001", "original": "First line.", "translated": "第一句。"},
                {"subtitle_id": "S0002", "original": "Second line.", "translated": "第二句。"},
            ],
        )
        _write_json(
            artifact_dir / "translations.json",
            [
                {
                    "subtitle_id": "S0001",
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "text": "First line.",
                    "translated_text": "第一句。",
                },
                {
                    "subtitle_id": "S0002",
                    "start_ms": 2500,
                    "end_ms": 3500,
                    "text": "Second line.",
                    "translated_text": "第二句。",
                },
            ],
        )
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "allocation-unresolved.json", [])
        _write_json(artifact_dir / "allocation-retry-log.json", [])
        _write_json(
            artifact_dir / "validation-report.json",
            {
                "errors": [],
                "warnings": [
                    {
                        "code": "chinese_semantic_group_warning",
                        "items": [
                            {
                                "semantic_group_id": "G0001",
                                "subtitle_ids": ["S0001"],
                                "mapping_valid": False,
                                "reason": "audit_mapping_invalid",
                            }
                        ],
                    },
                    {
                        "code": "subtitle_duration_short_warning",
                        "items": [
                            {
                                "subtitle_id": "S0002",
                                "reason": "subtitle is too short",
                            }
                        ],
                    },
                ],
            },
        )

        result = write_qa_review_artifacts(artifact_dir, source_audio_dir=source_dir)

        queue_text = Path(result["qa_review_queue_srt"]).read_text(encoding="utf-8-sig")
        source_queue_text = Path(result["source_audio_qa_review_queue_srt"]).read_text(
            encoding="utf-8-sig"
        )
        assert result["queue_item_count"] == 1
        assert "00:00:02,500 --> 00:00:03,500" in queue_text
        assert "S0002 EN: Second line." in queue_text
        assert "audit_mapping_invalid" not in queue_text
        assert source_queue_text == queue_text


def test_review_queue_marks_only_cues_with_final_timeline_fallback_words():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir) / "sample-artifacts"
        artifact_dir.mkdir()
        _write_json(artifact_dir / "run-manifest.json", {"subtitle_count": 2})
        _write_json(
            artifact_dir / "subtitle-spans.json",
            [
                {"subtitle_id": "S0001", "original": "First aligned cue.", "translated": "第一条。"},
                {"subtitle_id": "S0002", "original": "Second aligned cue.", "translated": "第二条。"},
            ],
        )
        _write_json(artifact_dir / "translations.json", [])
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "allocation-unresolved.json", [])
        _write_json(artifact_dir / "allocation-retry-log.json", [])
        _write_json(artifact_dir / "validation-report.json", {"errors": [], "warnings": []})
        _write_json(
            artifact_dir / "word-ledger.json",
            {
                "words": [
                    {"word_id": 0, "alignment_source": "whisperx"},
                    {"word_id": 1, "alignment_source": "stable-ts-fallback"},
                    {"word_id": 2, "alignment_source": "whisperx"},
                    {"word_id": 3, "alignment_source": "whisperx"},
                ]
            },
        )
        _write_json(
            artifact_dir / "final-cue-timeline.json",
            {
                "alignment": {"applied_backend": "whisperx-time-only"},
                "validation": {"errors": []},
                "records": [
                    {
                        "subtitle_id": "S0001",
                        "word_start": 0,
                        "word_end": 1,
                        "start_ms": 1200,
                        "end_ms": 2100,
                        "word_alignment_sources": ["whisperx", "stable-ts-fallback"],
                    },
                    {
                        "subtitle_id": "S0002",
                        "word_start": 2,
                        "word_end": 3,
                        "start_ms": 2140,
                        "end_ms": 2900,
                        "word_alignment_sources": ["whisperx"],
                    },
                ],
            },
        )

        result = write_qa_review_artifacts(artifact_dir)
        queue_payload = json.loads(Path(result["qa_review_queue_json"]).read_text(encoding="utf-8"))
        queue_text = Path(result["qa_review_queue_srt"]).read_text(encoding="utf-8-sig")

        fallback_items = [
            item for item in queue_payload["items"] if item["code"] == "timeline_alignment_fallback"
        ]
        assert result["timeline_alignment_backend"] == "whisperx-time-only"
        assert result["timeline_fallback_cue_count"] == 1
        assert len(fallback_items) == 1
        assert fallback_items[0]["subtitle_ids"] == ["S0001"]
        assert fallback_items[0]["details"]["fallback_word_ids"] == [1]
        assert "00:00:01,200 --> 00:00:02,100" in queue_text
        assert "S0002 EN" not in queue_text


def test_review_queue_does_not_create_timing_review_for_full_whisperx_alignment():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir) / "sample-artifacts"
        artifact_dir.mkdir()
        _write_json(artifact_dir / "run-manifest.json", {"subtitle_count": 1})
        _write_json(
            artifact_dir / "subtitle-spans.json",
            [{"subtitle_id": "S0001", "original": "Fully aligned.", "translated": "完全对齐。"}],
        )
        _write_json(artifact_dir / "translations.json", [])
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "allocation-unresolved.json", [])
        _write_json(artifact_dir / "allocation-retry-log.json", [])
        _write_json(artifact_dir / "validation-report.json", {"errors": [], "warnings": []})
        _write_json(
            artifact_dir / "word-ledger.json",
            {"words": [{"word_id": 0, "alignment_source": "whisperx"}]},
        )
        _write_json(
            artifact_dir / "final-cue-timeline.json",
            {
                "alignment": {"applied_backend": "whisperx-time-only"},
                "validation": {"errors": []},
                "records": [
                    {
                        "subtitle_id": "S0001",
                        "word_start": 0,
                        "word_end": 0,
                        "start_ms": 1200,
                        "end_ms": 1800,
                        "word_alignment_sources": ["whisperx"],
                    }
                ],
            },
        )

        result = write_qa_review_artifacts(artifact_dir)
        queue_payload = json.loads(Path(result["qa_review_queue_json"]).read_text(encoding="utf-8"))

        assert result["timeline_fallback_cue_count"] == 0
        assert not [item for item in queue_payload["items"] if item["code"] == "timeline_alignment_fallback"]


def test_review_queue_keeps_all_actionable_items_by_default():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir) / "sample-artifacts"
        artifact_dir.mkdir()
        subtitle_spans = []
        translations = []
        warning_items = []
        for index in range(1, 16):
            subtitle_id = f"S{index:04d}"
            subtitle_spans.append(
                {
                    "subtitle_id": subtitle_id,
                    "original": f"Review line {index}.",
                    "translated": f"复核字幕{index}。",
                }
            )
            translations.append(
                {
                    "subtitle_id": subtitle_id,
                    "start_ms": index * 1000,
                    "end_ms": index * 1000 + 800,
                    "text": f"Review line {index}.",
                    "translated_text": f"复核字幕{index}。",
                }
            )
            warning_items.append(
                {
                    "subtitle_id": subtitle_id,
                    "reason": "subtitle is too short",
                }
            )
        _write_json(artifact_dir / "run-manifest.json", {"subtitle_count": 15})
        _write_json(artifact_dir / "subtitle-spans.json", subtitle_spans)
        _write_json(artifact_dir / "translations.json", translations)
        _write_json(artifact_dir / "translation-structure-errors.json", [])
        _write_json(artifact_dir / "allocation-unresolved.json", [])
        _write_json(artifact_dir / "allocation-retry-log.json", [])
        _write_json(
            artifact_dir / "validation-report.json",
            {
                "errors": [],
                "warnings": [
                    {
                        "code": "subtitle_duration_short_warning",
                        "items": warning_items,
                    }
                ],
            },
        )

        result = write_qa_review_artifacts(artifact_dir)
        queue_payload = json.loads(Path(result["qa_review_queue_json"]).read_text(encoding="utf-8"))

        assert result["queue_item_count"] == 15
        assert result["omitted_review_count"] == 0
        assert result["review_limit"] == 0
        assert len(queue_payload["items"]) == 15
        assert queue_payload["items"][-1]["subtitle_ids"] == ["S0015"]

        limited_result = write_qa_review_artifacts(artifact_dir, review_limit=12)
        limited_payload = json.loads(
            Path(limited_result["qa_review_queue_json"]).read_text(encoding="utf-8")
        )
        assert limited_result["queue_item_count"] == 12
        assert limited_result["omitted_review_count"] == 3
        assert limited_result["review_limit"] == 12
        assert len(limited_payload["items"]) == 12


if __name__ == "__main__":
    test_review_queue_uses_final_times_and_excludes_invalid_audit_mapping()
    test_review_queue_marks_only_cues_with_final_timeline_fallback_words()
    test_review_queue_does_not_create_timing_review_for_full_whisperx_alignment()
    test_review_queue_keeps_all_actionable_items_by_default()
    print("qa review queue tests passed")
