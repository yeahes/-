import copy
import json
import tempfile
from pathlib import Path

from app.core.entities import SubtitleTask
from app.thread.subtitle_thread import SubtitleThread
from scripts.compare_frozen_mainline_runs import (
    STATUS_COMPARABLE,
    STATUS_INCOMPLETE,
    STATUS_ISOLATION_FAILED,
    compare_frozen_mainline_runs,
)


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _article_state(*, enabled: bool = False) -> dict:
    return {
        "schema_version": 1,
        "reference_text_present": enabled,
        "reference_text_hash": "reference-hash" if enabled else "",
        "normalized_context_hash": "context-hash" if enabled else "empty-context-hash",
        "glossary_hash": "glossary-hash" if enabled else "empty-glossary-hash",
        "use_article_reference_assist": enabled,
        "use_article_translation_terms": enabled,
        "article_reference_enabled": enabled,
        "correction_requested": enabled,
        "correction_ran": enabled,
        "correction_applied": enabled,
        "translation_terms_applied": enabled,
    }


def _write_run(
    root: Path,
    *,
    chinese: tuple[str, str] = ("中文一", "中文二"),
    corrected_text: str = "Pangram is correct.",
    first_english: str = "Pangram is correct.",
    first_end_ms: int = 900,
    full_translation: str = "全组中文。",
    article_enabled: bool = False,
    write_raw: bool = True,
    stale_glossary: bool = False,
) -> Path:
    artifacts = root / "sample-artifacts"
    artifacts.mkdir(parents=True)
    stable_srt = root / "stable-final-original-top.srt"
    stable_srt.write_text(
        "\n".join(
            [
                "1",
                f"00:00:00,000 --> 00:00:01,{first_end_ms:03d}",
                first_english,
                chinese[0],
                "",
                "2",
                "00:00:01,020 --> 00:00:02,000",
                "It has fixed IDs.",
                chinese[1],
                "",
            ]
        ),
        encoding="utf-8-sig",
    )
    spans = [
        {
            "subtitle_id": "S0001",
            "source_ids": [1],
            "word_start": 0,
            "word_end": 2,
            "original": first_english,
            "translated": chinese[0],
        },
        {
            "subtitle_id": "S0002",
            "source_ids": [2],
            "word_start": 3,
            "word_end": 6,
            "original": "It has fixed IDs.",
            "translated": chinese[1],
        },
    ]
    groups = [
        {
            "group_id": 1,
            "expected_subtitle_ids": ["S0001", "S0002"],
            "full_english": f"{first_english} It has fixed IDs.",
            "subtitle_parts": copy.deepcopy(spans),
        }
    ]
    raw = {"segments": [{"text": "Pangrum is correct.", "start_time": 0, "end_time": 1000}]}
    corrected = {"segments": [{"text": corrected_text, "start_time": 0, "end_time": 1000}]}
    if write_raw:
        _write_json(root / "asr_raw.json", raw)
    _write_json(root / "asr_corrected.json", corrected)
    _write_json(
        artifacts / "word-ledger.json",
        {
            "words": [
                {"word_id": 0, "surface": "Pangram", "start_ms": 0, "end_ms": 300},
                {"word_id": 1, "surface": "is", "start_ms": 301, "end_ms": 500},
            ],
            "source_segments": [{"index": 1, "text": "Pangram is correct."}],
        },
    )
    _write_json(artifacts / "subtitle-spans.json", spans)
    _write_json(artifacts / "semantic-groups.json", groups)
    _write_json(
        artifacts / "llm-raw-returns.json",
        [
            {
                "task": "screen_subtitle_semantic_full_translation_v3",
                "data": {"groups": [{"id": 1, "full_translation": full_translation}]},
            }
        ],
    )
    _write_json(
        artifacts / "allocation-inputs.json",
        [{"id": 1, "allocation_prompt_version": "semantic-allocation-v3"}],
    )
    _write_json(
        artifacts / "run-manifest.json",
        {
            "translation_model": "deepseek-v4-flash",
            "prompt_version": "global-subtitle-id-v2",
            "target_language": "简体中文",
            "max_cjk_chars": 24,
            "max_english_words": 16,
            "allocation_batch_size": 16,
            "allocation_max_concurrency": 2,
            "chinese_polish_enabled": False,
        },
    )
    _write_json(
        root / "stable-final-manifest.json",
        {
            "paths": {"original_top_srt": str(stable_srt)},
            "run_comparison": {
                "schema_version": 1,
                "article_reference": _article_state(enabled=article_enabled),
                "translation_runtime_config": {
                    "translation_model": "deepseek-v4-flash",
                    "prompt_version": "global-subtitle-id-v2",
                    "target_language": "简体中文",
                    "max_cjk_chars": 24,
                    "max_english_words": 16,
                    "allocation_batch_size": 16,
                    "allocation_max_concurrency": 2,
                    "chinese_polish_enabled": False,
                },
            },
        },
    )
    if stale_glossary:
        _write_json(artifacts / "article_glossary.json", [{"canonical_name": "Stale Article"}])
    return root


def test_chinese_only_change_is_comparable():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        baseline = _write_run(root / "baseline")
        candidate = _write_run(root / "candidate", chinese=("中文一已调整", "中文二"))

        report = compare_frozen_mainline_runs(baseline, candidate)

        assert report["status"] == STATUS_COMPARABLE
        assert report["chinese_changed_subtitle_ids"] == ["S0001"]


def test_corrected_asr_difference_rejects_allocation_only_claim():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        baseline = _write_run(root / "baseline")
        candidate = _write_run(root / "candidate", corrected_text="Pangrum is correct.")

        report = compare_frozen_mainline_runs(baseline, candidate)

        assert report["status"] == STATUS_ISOLATION_FAILED
        assert [item["key"] for item in report["changed_frozen_inputs"]] == [
            "corrected_english_hash"
        ]


def test_english_boundary_or_timing_difference_rejects_comparison():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        baseline = _write_run(root / "baseline")
        candidate = _write_run(root / "candidate", first_english="Pangram was corrected.", first_end_ms=980)

        report = compare_frozen_mainline_runs(baseline, candidate)

        assert report["status"] == STATUS_ISOLATION_FAILED
        assert "english_by_subtitle_id" in report["final_output_changes"]
        assert "timing_by_subtitle_id" in report["final_output_changes"]


def test_authoritative_full_translation_difference_rejects_comparison():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        baseline = _write_run(root / "baseline")
        candidate = _write_run(root / "candidate", full_translation="不同的完整中文。")

        report = compare_frozen_mainline_runs(baseline, candidate)

        assert report["status"] == STATUS_ISOLATION_FAILED
        assert [item["key"] for item in report["changed_frozen_inputs"]] == [
            "authoritative_full_translation_hash"
        ]


def test_article_assist_state_mismatch_rejects_even_when_text_is_same():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        baseline = _write_run(root / "baseline", article_enabled=True)
        candidate = _write_run(root / "candidate", article_enabled=False)

        report = compare_frozen_mainline_runs(baseline, candidate)

        assert report["status"] == STATUS_ISOLATION_FAILED
        assert report["changed_article_reference_state"]


def test_missing_required_artifact_is_not_silently_compared():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        baseline = _write_run(root / "baseline")
        candidate = _write_run(root / "candidate", write_raw=False)

        report = compare_frozen_mainline_runs(baseline, candidate)

        assert report["status"] == STATUS_INCOMPLETE
        assert "asr_raw.json" in report["candidate"]["missing"]


def test_stale_article_file_cannot_imply_article_assist_was_enabled():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        baseline = _write_run(root / "baseline", stale_glossary=True)
        candidate = _write_run(root / "candidate", stale_glossary=True)

        report = compare_frozen_mainline_runs(baseline, candidate)

        assert report["status"] == STATUS_COMPARABLE
        assert report["baseline"]["article_reference"]["article_reference_enabled"] is False
        assert report["candidate"]["article_reference"]["article_reference_enabled"] is False


def test_manifest_records_runtime_article_state_not_artifact_presence():
    class FakeScreenEditor:
        model = "deepseek-v4-flash"
        target_language = "简体中文"
        max_cjk_chars = 24
        max_english_words = 16
        allocation_batch_size = 16
        allocation_max_concurrency = 2
        enable_chinese_polish = False

        @staticmethod
        def manifest_metadata():
            return {"prompt_version": "global-subtitle-id-v2"}

    thread = SubtitleThread.__new__(SubtitleThread)
    thread.task = SubtitleTask(
        article_reference_text="Pangram is a reference article term.",
        use_article_reference_assist=True,
        use_article_translation_terms=False,
    )
    thread._stage_timings_seconds = {}
    thread._set_article_run_metadata(
        {
            "people": [],
            "companies": [{"canonical_name": "Pangram", "category": "company"}],
        },
        correction_ran=True,
        correction_applied=True,
    )

    metadata = thread._screen_manifest_metadata(FakeScreenEditor())
    article = metadata["run_comparison"]["article_reference"]

    assert article["article_reference_enabled"] is True
    assert article["correction_ran"] is True
    assert article["correction_applied"] is True
    assert article["reference_text_hash"]
    assert article["glossary_hash"]


if __name__ == "__main__":
    test_chinese_only_change_is_comparable()
    test_corrected_asr_difference_rejects_allocation_only_claim()
    test_english_boundary_or_timing_difference_rejects_comparison()
    test_authoritative_full_translation_difference_rejects_comparison()
    test_article_assist_state_mismatch_rejects_even_when_text_is_same()
    test_missing_required_artifact_is_not_silently_compared()
    test_stale_article_file_cannot_imply_article_assist_was_enabled()
    test_manifest_records_runtime_article_state_not_artifact_presence()
    print("Frozen run comparison tests passed.")
