import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.subtitle_processor.stable_display_page_contract import (
    DisplayPageContractError,
    build_display_page_contract,
    display_page_id,
    page_translation_cache_key,
    parent_chinese_by_id,
    validate_page_translation_response,
)
from app.core.utils import podcast_learning_video


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "stable_pages"
    / "page_translation_contract.json"
)


def _cases():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return {case["case_id"]: case for case in payload["cases"]}


def _timed_cue(case):
    cue = podcast_learning_video.Cue(
        int(case["subtitle_id"][1:]),
        float(case["start"]),
        float(case["end"]),
        case["english"],
        case["parent_chinese"],
        "male",
        subtitle_id=case["subtitle_id"],
    )
    words = cue.en.split()
    duration = cue.end - cue.start
    cue.word_timing = tuple(
        {
            "surface": word,
            "start": cue.start + duration * index / len(words),
            "end": cue.start + duration * (index + 1) / len(words),
        }
        for index, word in enumerate(words)
    )
    return cue


def _contract(case):
    pages = [
        {
            "display_page_id": display_page_id(case["subtitle_id"], index),
            "word_start": page["word_start"],
            "word_end": page["word_end"],
            "english": page["english"],
        }
        for index, page in enumerate(case["pages"], 1)
    ]
    return build_display_page_contract(
        [
            {
                "parent_subtitle_id": case["subtitle_id"],
                "english": case["english"],
                "chinese": case["parent_chinese"],
                "word_start": case["word_start"],
                "word_end": case["word_end"],
                "pages": pages,
            }
        ],
        layout_profile={
            "template": "article",
            "english_font_size": 58,
            "chinese_font_size": 46,
        },
    )


def _response(case, *, reverse=False):
    pages = [
        {
            "display_page_id": display_page_id(case["subtitle_id"], index),
            "zh": page["chinese"],
        }
        for index, page in enumerate(case["pages"], 1)
    ]
    if reverse:
        pages.reverse()
    return {"pages": pages}


def _error_codes(result):
    return {
        str(error.get("code") if isinstance(error, dict) else error)
        for error in result.get("errors", [])
    }


def _immutable_parent_snapshot(cue):
    return (
        cue.subtitle_id,
        cue.en,
        cue.start,
        cue.end,
        cue.word_timing,
    )


def _assert_exact_page_identity(plan, case):
    expected_ids = [
        display_page_id(case["subtitle_id"], index)
        for index in range(1, len(case["pages"]) + 1)
    ]
    assert [page["display_page_id"] for page in plan["pages"]] == expected_ids
    assert all(page_id != "S0000" for page_id in expected_ids)
    assert " ".join(page["en"] for page in plan["pages"]) == case["english"]


def _page_translations(artifact):
    return {
        page["display_page_id"]: page["zh"]
        for parent in artifact["parents"]
        for page in parent["pages"]
    }


def _word_entries_for_segments(segments):
    entries = []
    for segment in segments:
        words = segment.text.split()
        duration = segment.end_time - segment.start_time
        for index, word in enumerate(words):
            entries.append(
                {
                    "surface": word,
                    "start_time": segment.start_time + duration * index // len(words),
                    "end_time": segment.start_time + duration * (index + 1) // len(words),
                }
            )
    return entries


def _assert_preflight_fails_before_ffmpeg(cues, subtitle_path):
    with patch.object(podcast_learning_video.subprocess, "Popen") as popen:
        try:
            podcast_learning_video.prepare_article_visual_page_plans(cues, subtitle_path)
        except podcast_learning_video.RenderStructuralOverflowError as exc:
            assert any(
                error.get("reason")
                in {
                    "missing_or_invalid_display_page_translations",
                    "missing_or_invalid_display_page_translation_artifact",
                }
                for error in exc.errors
            )
        else:
            raise AssertionError("invalid page artifact must fail renderer preflight")
    assert not popen.called


def test_s0078_reordered_chinese_is_bound_by_page_id():
    case = _cases()["s0078_reordered_chinese"]
    contract = _contract(case)
    artifact = validate_page_translation_response(
        contract,
        _response(case, reverse=True),
    )

    expected_aggregate = "".join(page["chinese"] for page in case["pages"])
    assert artifact["status"] == "PASS"
    assert artifact["errors"] == []
    assert parent_chinese_by_id(artifact) == {case["subtitle_id"]: expected_aggregate}
    translations = _page_translations(artifact)
    page_ids = [display_page_id(case["subtitle_id"], index) for index in (1, 2)]
    first = translations[page_ids[0]]
    second = translations[page_ids[1]]
    assert "推出" in first and "模型" in first
    assert "投入" not in first and "算力" not in first
    assert "投入" in second and "算力" in second
    assert all(anchor in second for anchor in ("大量资金", "刻意降低", "算力总需求", "技术"))
    assert "推出" not in second


def test_s0252_monotonic_translation_remains_page_aligned():
    case = _cases()["s0252_monotonic_chinese"]
    contract = _contract(case)
    artifact = validate_page_translation_response(
        contract,
        _response(case, reverse=True),
    )

    assert artifact["status"] == "PASS"
    translations = _page_translations(artifact)
    ordered = [
        translations[display_page_id(case["subtitle_id"], index)]
        for index in range(1, 4)
    ]
    assert ordered == [page["chinese"] for page in case["pages"]]
    assert "人工智能" in ordered[0] and "制造业" not in ordered[0]
    assert all(anchor in ordered[1] for anchor in ("制造业", "农业", "本地服务业"))
    assert "数据中心" not in ordered[1]
    assert "5000亿美元" in ordered[2] and "数据中心" in ordered[2]


def test_page_translation_rejects_missing_duplicate_and_unknown_page_ids():
    case = _cases()["s0078_reordered_chinese"]
    contract = _contract(case)
    page_1 = display_page_id(case["subtitle_id"], 1)
    page_2 = display_page_id(case["subtitle_id"], 2)
    invalid_cases = [
        (
            {"pages": [{"display_page_id": page_1, "zh": "第一页"}]},
            {"page_translation_id_missing", "page_translation_cardinality_mismatch"},
        ),
        (
            {
                "pages": [
                    {"display_page_id": page_1, "zh": "第一页"},
                    {"display_page_id": page_1, "zh": "重复页"},
                    {"display_page_id": page_2, "zh": "第二页"},
                ]
            },
            {"page_translation_id_duplicate", "page_translation_cardinality_mismatch"},
        ),
        (
            {
                "pages": [
                    {"display_page_id": page_1, "zh": "第一页"},
                    {"display_page_id": "S9999.P01", "zh": "未知页"},
                ]
            },
            {
                "page_translation_id_unknown",
                "page_translation_id_missing",
            },
        ),
        (
            {
                "pages": [
                    {"display_page_id": "", "zh": "无标识页"},
                    {"display_page_id": page_2, "zh": "第二页"},
                ]
            },
            {"page_translation_id_missing", "page_translation_cardinality_mismatch"},
        ),
    ]

    for response, expected_codes in invalid_cases:
        artifact = validate_page_translation_response(contract, response)
        assert artifact["status"] == "ERROR"
        assert artifact["parents"] == []
        assert expected_codes <= _error_codes(artifact)
        try:
            parent_chinese_by_id(artifact)
        except DisplayPageContractError as exc:
            assert exc.code == "page_translation_artifact_invalid"
        else:
            raise AssertionError("invalid page rows must not partially update parents")


def test_page_translation_cache_key_invalidates_semantic_page_contract_changes():
    case = _cases()["s0078_reordered_chinese"]
    contract = _contract(case)

    def key(value, prompt="display-page-translation-v1", algorithm="page-id-v1"):
        return page_translation_cache_key(
            value,
            model="deepseek-v4-flash",
            target_language="简体中文",
            prompt_version=prompt,
            algorithm_version=algorithm,
        )

    assert key(contract) == key(copy.deepcopy(contract))

    changed_boundary = copy.deepcopy(contract)
    changed_boundary["parents"][0]["pages"][0]["word_end"] -= 1
    changed_boundary["parents"][0]["pages"][1]["word_start"] -= 1
    assert key(contract) != key(changed_boundary)

    changed_parent_chinese = copy.deepcopy(contract)
    changed_parent_chinese["parents"][0]["source_chinese"] += "补充"
    assert key(contract) != key(changed_parent_chinese)
    assert key(contract) != key(contract, prompt="display-page-translation-v2")
    assert key(contract) != key(contract, algorithm="page-id-v2")

    changed_timing = copy.deepcopy(contract)
    for page in changed_timing["parents"][0]["pages"]:
        page["start_ms"] = 100
        page["end_ms"] = 200
    assert key(contract) != key(changed_timing)


def test_page_translation_rejects_page_level_chinese_speed_overflow():
    case = _cases()["s0078_reordered_chinese"]
    contract = _contract(case)
    contract["parents"][0]["pages"][0]["start_ms"] = 0
    contract["parents"][0]["pages"][0]["end_ms"] = 900
    artifact = validate_page_translation_response(
        contract,
        {
            "pages": [
                {
                    "display_page_id": display_page_id(case["subtitle_id"], 1),
                    "zh": "这是一段明显无法在不到一秒内舒适读完的中文翻译内容",
                },
                {
                    "display_page_id": display_page_id(case["subtitle_id"], 2),
                    "zh": case["pages"][1]["chinese"],
                },
            ]
        },
    )
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)

    errors = editor._display_page_translation_quality_errors(contract, artifact)

    assert any(
        error.get("code") == "display_page_chinese_reading_speed_exceeded"
        for error in errors
    )


def test_page_level_continuation_fragment_is_review_not_blocker():
    contract = build_display_page_contract(
        [
            {
                "parent_subtitle_id": "S0111",
                "english": (
                    "Now, when you compare that to Alphabet talking about a 205 "
                    "billion spend for a much shorter time frame..."
                ),
                "chinese": "那么，把这个数字与Alphabet相比，它谈的是在更短时间内投入2050亿美元……",
                "word_start": 0,
                "word_end": 18,
                "pages": [
                    {
                        "display_page_id": "S0111.P01",
                        "word_start": 0,
                        "word_end": 7,
                        "english": "Now, when you compare that to Alphabet talking",
                        "start_ms": 0,
                        "end_ms": 2200,
                    },
                    {
                        "display_page_id": "S0111.P02",
                        "word_start": 8,
                        "word_end": 18,
                        "english": "about a 205 billion spend for a much shorter time frame...",
                        "start_ms": 2200,
                        "end_ms": 6000,
                    },
                ],
            }
        ],
        layout_profile={"template": "article", "max_lines": 2},
    )
    artifact = validate_page_translation_response(
        contract,
        {
            "pages": [
                {"display_page_id": "S0111.P01", "zh": "那么，当你把这个数字和Alphabet的说法相比："},
                {"display_page_id": "S0111.P02", "zh": "也就是在更短时间内投入2050亿美元……"},
            ]
        },
    )
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)

    errors = editor._display_page_translation_quality_errors(contract, artifact)

    assert errors == []
    reviews = editor._display_page_translation_reviews
    assert len(reviews) == 1
    assert reviews[0]["code"] == "display_page_continuation_review"
    assert reviews[0]["parent_subtitle_id"] == "S0111"
    assert reviews[0]["issue_codes"] == ["unnatural_chinese_fragment"]


def test_renderer_uses_valid_page_mapping_without_proportional_fallback():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    for case in _cases().values():
        cue = _timed_cue(case)
        contract = _contract(case)
        artifact = validate_page_translation_response(
            contract,
            _response(case, reverse=True),
        )
        cue.zh = parent_chinese_by_id(artifact)[case["subtitle_id"]]
        cue.display_page_translations = _page_translations(artifact)

        with patch.object(
            podcast_learning_video,
            "_strict_split_chinese_visual_pages",
            side_effect=AssertionError("proportional Chinese fallback is forbidden"),
        ):
            plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

        assert plan["status"] == "ok"
        assert plan["font_size"] == {"english": 58, "chinese": 46}
        _assert_exact_page_identity(plan, case)
        assert [page["zh"] for page in plan["pages"]] == [
            page["chinese"] for page in case["pages"]
        ]


def test_renderer_fails_closed_when_paginated_page_mapping_is_missing():
    case = _cases()["s0078_reordered_chinese"]
    cue = _timed_cue(case)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    with patch.object(
        podcast_learning_video,
        "_strict_split_chinese_visual_pages",
        side_effect=AssertionError("proportional Chinese fallback is forbidden"),
    ):
        plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "render_structural_overflow"
    assert plan["errors"][0]["reason"] == "missing_or_invalid_display_page_translations"


def test_page_translation_updates_parent_chinese_without_srt_structure_drift():
    case = _cases()["s0078_reordered_chinese"]
    cue = _timed_cue(case)
    before = _immutable_parent_snapshot(cue)
    contract = _contract(case)
    artifact = validate_page_translation_response(contract, _response(case))
    aggregate_chinese = parent_chinese_by_id(artifact)[case["subtitle_id"]]
    cue.zh = aggregate_chinese
    cue.display_page_translations = _page_translations(artifact)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    with tempfile.TemporaryDirectory() as raw:
        old_srt_path = Path(raw) / "old.srt"
        updated_srt_path = Path(raw) / "updated.srt"
        old_srt_path.write_text(
            "1\n00:05:05,025 --> 00:05:14,811\n"
            + case["english"]
            + "\n"
            + case["parent_chinese"]
            + "\n",
            encoding="utf-8",
        )
        updated_srt_path.write_text(
            "1\n00:05:05,025 --> 00:05:14,811\n"
            + case["english"]
            + "\n"
            + aggregate_chinese
            + "\n",
            encoding="utf-8",
        )

        with patch.object(
            podcast_learning_video,
            "_strict_split_chinese_visual_pages",
            side_effect=AssertionError("proportional Chinese fallback is forbidden"),
        ):
            plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

        old_srt_cue = podcast_learning_video.parse_srt(old_srt_path)[0]
        updated_srt_cue = podcast_learning_video.parse_srt(updated_srt_path)[0]
        assert (
            updated_srt_cue.index,
            updated_srt_cue.start,
            updated_srt_cue.end,
            updated_srt_cue.en,
        ) == (
            old_srt_cue.index,
            old_srt_cue.start,
            old_srt_cue.end,
            old_srt_cue.en,
        )
        assert old_srt_cue.zh == case["parent_chinese"]
        assert updated_srt_cue.zh == aggregate_chinese

    assert _immutable_parent_snapshot(cue) == before
    assert cue.zh == aggregate_chinese
    assert cue.zh != case["parent_chinese"]
    _assert_exact_page_identity(plan, case)


def test_screen_editor_applies_mocked_page_response_after_final_timing_only():
    case = _cases()["s0078_reordered_chinese"]
    paginated = ASRDataSeg(
        case["english"],
        int(case["start"] * 1000),
        int(case["end"] * 1000),
        case["parent_chinese"],
    )
    paginated.subtitle_id = case["subtitle_id"]
    paginated.word_start = 0
    paginated.word_end = len(paginated.text.split()) - 1
    single_page = ASRDataSeg(
        "That is the point.",
        paginated.end_time + 100,
        paginated.end_time + 1700,
        "这就是关键。",
    )
    single_page.subtitle_id = "S0079"
    single_page.word_start = paginated.word_end + 1
    single_page.word_end = single_page.word_start + len(single_page.text.split()) - 1
    asr_data = ASRData([paginated, single_page])

    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.enable_stable_mode = True
    editor._active_word_entries = _word_entries_for_segments(asr_data.segments)
    editor._active_source_segments_by_id = {}
    editor._last_semantic_groups = []
    editor._last_subtitle_items = []
    editor._display_page_translation_artifact = {}
    editor._display_page_translation_path = ""
    editor._display_page_external_request_count = 0
    editor.coverage_report_path = None

    def mocked_request(contract, *, retry_errors=None):
        assert retry_errors is None
        parents = list(contract.get("parents") or [])
        assert [parent["parent_subtitle_id"] for parent in parents] == [case["subtitle_id"]]
        pages = list(parents[0]["pages"])
        assert len(pages) == len(case["pages"])
        return (
            {
                "pages": [
                    {
                        "display_page_id": page["display_page_id"],
                        "zh": expected["chinese"],
                    }
                    for page, expected in zip(reversed(pages), reversed(case["pages"]))
                ]
            },
            False,
        )

    editor._request_display_page_translations = mocked_request
    editor._display_page_translation_quality_errors = lambda contract, artifact: []
    editor._record_display_page_translation_failure = lambda *args, **kwargs: None
    editor._report_subtitle_coverage_gaps = lambda *args, **kwargs: None
    editor._write_stable_pipeline_artifacts = lambda *args, **kwargs: None

    before = [
        (
            segment.subtitle_id,
            segment.text,
            segment.word_start,
            segment.word_end,
            segment.start_time,
            segment.end_time,
        )
        for segment in asr_data.segments
    ]
    old_single_chinese = single_page.translated_text

    result = editor.apply_display_page_translations_after_final_timing(asr_data)

    expected_chinese = "".join(page["chinese"] for page in case["pages"])
    assert result is asr_data
    assert paginated.translated_text == expected_chinese
    assert single_page.translated_text == old_single_chinese
    assert [
        (
            segment.subtitle_id,
            segment.text,
            segment.word_start,
            segment.word_end,
            segment.start_time,
            segment.end_time,
        )
        for segment in asr_data.segments
    ] == before
    artifact = editor._display_page_translation_artifact
    assert artifact["status"] == "PASS"
    assert parent_chinese_by_id(artifact) == {case["subtitle_id"]: expected_chinese}
    assert [parent["parent_subtitle_id"] for parent in artifact["parents"]] == [
        case["subtitle_id"]
    ]


def test_renderer_preflight_loads_manifest_page_artifact_and_rejects_missing_or_tampered():
    case = _cases()["s0078_reordered_chinese"]
    aggregate_chinese = "".join(page["chinese"] for page in case["pages"])
    words = case["english"].split()
    start_ms = int(case["start"] * 1000)
    end_ms = int(case["end"] * 1000)
    duration = end_ms - start_ms

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subtitle_path = root / "stable-final-original-top.srt"
        subtitle_path.write_text(
            "1\n00:05:05,025 --> 00:05:14,811\n"
            + case["english"]
            + "\n"
            + aggregate_chinese
            + "\n",
            encoding="utf-8",
        )
        artifact_dir = root / "styled-subtitles-artifacts"
        artifact_dir.mkdir()
        timeline_path = artifact_dir / "final-cue-timeline.json"
        timeline_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "subtitle_id": case["subtitle_id"],
                            "word_start": 0,
                            "word_end": len(words) - 1,
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (artifact_dir / "word-ledger.json").write_text(
            json.dumps(
                {
                    "words": [
                        {
                            "surface": word,
                            "start_ms": start_ms + duration * index // len(words),
                            "end_ms": start_ms + duration * (index + 1) // len(words),
                        }
                        for index, word in enumerate(words)
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        page_artifact_path = artifact_dir / "display-page-translations.json"
        manifest_path = root / "stable-final-manifest.json"
        manifest_path.write_text(
            json.dumps({"final_cue_timeline_path": str(timeline_path)}),
            encoding="utf-8",
        )
        source_cues = podcast_learning_video.parse_srt(subtitle_path)
        assert podcast_learning_video.attach_article_word_timing(source_cues, subtitle_path)
        blueprint = podcast_learning_video.build_article_display_page_blueprint(source_cues)
        contract = build_display_page_contract(
            blueprint["parents"],
            layout_profile=blueprint["layout_profile"],
            planner_version=blueprint["planner_version"],
        )
        expected_pages = list(contract["parents"][0]["pages"])
        artifact = validate_page_translation_response(
            contract,
            {
                "pages": [
                    {
                        "display_page_id": page["display_page_id"],
                        "zh": expected["chinese"],
                    }
                    for page, expected in zip(expected_pages, case["pages"])
                ]
            },
        )
        assert artifact["status"] == "PASS"
        page_artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(
                {
                    "final_cue_timeline_path": str(timeline_path),
                    "display_page_translation_path": str(page_artifact_path),
                    "display_page_translation_status": "PASS",
                    "display_page_translation_contract_hash": artifact["contract_hash"],
                    "display_page_translation_sha256": hashlib.sha256(
                        page_artifact_path.read_bytes()
                    ).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

        valid_cues = podcast_learning_video.parse_srt(subtitle_path)
        podcast_learning_video.prepare_article_visual_page_plans(valid_cues, subtitle_path)
        assert valid_cues[0].subtitle_id == case["subtitle_id"]
        assert valid_cues[0].article_page_plan["status"] == "ok"
        assert [page["zh"] for page in valid_cues[0].article_page_plan["pages"]] == [
            page["chinese"] for page in case["pages"]
        ]

        page_artifact_path.unlink()
        _assert_preflight_fails_before_ffmpeg(
            podcast_learning_video.parse_srt(subtitle_path),
            subtitle_path,
        )

        tampered = copy.deepcopy(artifact)
        tampered["parents"][0]["pages"][0]["display_page_id"] = "S9999.P01"
        page_artifact_path.write_text(
            json.dumps(tampered, ensure_ascii=False),
            encoding="utf-8",
        )
        _assert_preflight_fails_before_ffmpeg(
            podcast_learning_video.parse_srt(subtitle_path),
            subtitle_path,
        )

        contract_tampered = copy.deepcopy(artifact)
        contract_tampered["contract_hash"] = "0" * 64
        page_artifact_path.write_text(
            json.dumps(contract_tampered, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["display_page_translation_sha256"] = hashlib.sha256(
            page_artifact_path.read_bytes()
        ).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        _assert_preflight_fails_before_ffmpeg(
            podcast_learning_video.parse_srt(subtitle_path),
            subtitle_path,
        )


def test_stable_artifact_write_failure_is_not_reported_as_success():
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.coverage_report_path = ""
    with tempfile.TemporaryDirectory() as raw:
        editor.coverage_report_path = str(Path(raw) / "stable-coverage-report.txt")
        editor.model = "test-model"
        editor._llm_cache_used = False
        editor.target_language = "zh-CN"
        editor.max_cjk_chars = 28
        editor.max_english_words = 16
        editor.enable_chinese_polish = False
        editor.allocation_max_concurrency = 1
        editor.allocation_batch_size = 1
        editor._chinese_cache_contract = {}
        editor._llm_cache_stats = {}
        editor._allocation_runtime_stats = {}
        editor._active_word_entries = []
        editor._frozen_subtitle_ids = []
        editor._translation_structure_errors = []
        editor._display_coverage_repairs = []
        editor._display_coverage_unresolved = []
        editor._final_cue_timeline = {}
        editor._final_word_timing_reconciliations = []
        editor._display_page_translation_artifact = {"status": "PASS"}
        editor._final_cue_timeline_path = ""
        editor._display_page_translation_path = ""
        editor._display_page_translation_sha256 = ""
        editor._last_llm_raw_returns = []
        editor._last_full_translation_style_retry_log = []
        editor._last_allocation_inputs = []
        editor._last_allocation_raw_returns = []
        editor._last_allocation_validation = []
        editor._last_allocation_retry_log = []
        editor._last_allocation_unresolved = []
        editor._allocation_isolation_report = {}
        editor._last_semantic_group_debug = []
        editor._current_git_commit = lambda: "test"
        editor._word_ledger_payload = lambda source: {"words": []}
        editor._semantic_groups_payload = lambda groups: []
        editor._boundary_snapshot_payload = lambda: {}
        editor._english_boundary_audit_payload = lambda segments: {}
        editor._final_allocation_payload = lambda groups, items: []

        with patch(
            "app.core.subtitle_processor.screen_editor.write_json_artifact_set",
            side_effect=OSError("disk full"),
        ):
            try:
                editor._write_stable_pipeline_artifacts([], [], [], [])
            except RuntimeError as exc:
                assert "stable_artifact_write_failed" in str(exc)
            else:
                raise AssertionError("artifact write failure must block the stable pipeline")

        assert editor._display_page_translation_path == ""
        assert editor._display_page_translation_sha256 == ""


def test_golden_page_translations_pass_existing_fixed_id_semantic_gate():
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    for case in _cases().values():
        contract = _contract(case)
        artifact = validate_page_translation_response(contract, _response(case))

        assert artifact["status"] == "PASS"
        quality_errors = editor._display_page_translation_quality_errors(
            contract,
            artifact,
        )

        assert quality_errors == [], {
            "case_id": case["case_id"],
            "issue_codes": [
                issue_code
                for error in quality_errors
                for issue_code in error.get("issue_codes", [])
            ],
        }


if __name__ == "__main__":
    test_s0078_reordered_chinese_is_bound_by_page_id()
    test_s0252_monotonic_translation_remains_page_aligned()
    test_page_translation_rejects_missing_duplicate_and_unknown_page_ids()
    test_page_translation_cache_key_invalidates_semantic_page_contract_changes()
    test_page_translation_rejects_page_level_chinese_speed_overflow()
    test_page_level_continuation_fragment_is_review_not_blocker()
    test_renderer_uses_valid_page_mapping_without_proportional_fallback()
    test_renderer_fails_closed_when_paginated_page_mapping_is_missing()
    test_page_translation_updates_parent_chinese_without_srt_structure_drift()
    test_screen_editor_applies_mocked_page_response_after_final_timing_only()
    test_renderer_preflight_loads_manifest_page_artifact_and_rejects_missing_or_tampered()
    test_stable_artifact_write_failure_is_not_reported_as_success()
    test_golden_page_translations_pass_existing_fixed_id_semantic_gate()
    print("stable page translation contract tests passed")
