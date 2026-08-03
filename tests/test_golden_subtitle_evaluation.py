import json
import tempfile
from pathlib import Path

from scripts.evaluate_golden_subtitles import evaluate_golden_subtitles


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_run(root: Path, *, english: str = "We met Pop Mart in 2024.", chinese: str = "我们在2024年见到了泡泡玛特。", end_ms: int = 500) -> Path:
    artifacts = root / "sample-artifacts"
    artifacts.mkdir(parents=True)
    _write_json(
        artifacts / "subtitle-spans.json",
        [
            {
                "subtitle_id": "S0001",
                "word_start": 0,
                "word_end": 5,
                "original": english,
                "translated": chinese,
            },
            {
                "subtitle_id": "S0002",
                "word_start": 6,
                "word_end": 8,
                "original": "It grew quickly.",
                "translated": "它增长很快。",
            },
        ],
    )
    words = []
    for index, word in enumerate("We met Pop Mart in 2024 It grew quickly".split()):
        words.append(
            {
                "word_id": index,
                "surface": word,
                "start_ms": index * 100,
                "end_ms": end_ms if index == 5 else index * 100 + 90,
            }
        )
    _write_json(artifacts / "word-ledger.json", {"words": words, "source_segments": []})
    return artifacts


def _reference() -> dict:
    return {
        "schema_version": 1,
        "sample_id": "golden-smoke",
        "english_text": "We met Pop Mart in 2024. It grew quickly.",
        "entities": [{"canonical_name": "Pop Mart", "category": "brand"}],
        "boundaries_after_word_index": [5],
        "word_timings": [
            {"word_id": 0, "start_ms": 0, "end_ms": 90},
            {"word_id": 5, "start_ms": 500, "end_ms": 500},
        ],
        "chinese_anchors": [
            {
                "anchor_id": "brand-and-year",
                "subtitle_ids": ["S0001"],
                "must_contain_any": [["泡泡玛特"], ["2024"]],
                "must_not_contain": ["2025"],
            }
        ],
        "thresholds": {
            "max_word_error_rate": 0.03,
            "min_recall": 1.0,
            "min_f1": 1.0,
            "max_mean_absolute_error_ms": 1,
            "max_p90_absolute_error_ms": 1,
        },
    }


def test_golden_evaluation_passes_for_matching_run():
    with tempfile.TemporaryDirectory() as temp_dir:
        report = evaluate_golden_subtitles(_reference(), _write_run(Path(temp_dir)))

    assert report["status"] == "PASS"
    assert report["scores"]["english"]["word_error_rate"] == 0.0
    assert report["scores"]["entities"]["recall"] == 1.0
    assert report["scores"]["boundaries"]["f1"] == 1.0
    assert report["scores"]["timing"]["mean_absolute_error_ms"] == 0.0
    assert report["scores"]["chinese_anchors"]["failures"] == []


def test_golden_evaluation_reports_word_entity_timing_and_chinese_failures():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts = _write_run(
            Path(temp_dir),
            english="We met Popmark in 2024.",
            chinese="我们在2025年见到了这个品牌。",
            end_ms=900,
        )
        report = evaluate_golden_subtitles(_reference(), artifacts)

    codes = {failure["code"] for failure in report["failures"]}
    assert report["status"] == "FAIL"
    assert "english_word_error_rate_too_high" in codes
    assert "entities_recall_too_low" in codes
    assert "timing_mean_absolute_error_ms_too_high" in codes
    assert "chinese_fact_anchor_failed" in codes


if __name__ == "__main__":
    test_golden_evaluation_passes_for_matching_run()
    test_golden_evaluation_reports_word_entity_timing_and_chinese_failures()
    print("golden subtitle evaluation tests passed")
