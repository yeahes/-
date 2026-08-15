import copy
import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.subtitle_processor.authoritative_parent_chinese import (
    AuthoritativeParentChineseError,
    bind_display_page_parent_records,
    build_authoritative_parent_chinese_artifact,
    parent_chinese_records_by_id,
    validate_authoritative_parent_chinese_artifact,
    validate_display_page_parent_records,
)
from app.core.subtitle_processor.stable_display_page_contract import (
    DisplayPageContractError,
    build_display_page_contract,
    display_page_id,
    page_translation_cache_key,
    parent_chinese_by_id,
    validate_page_translation_response,
)
from app.core.subtitle_processor.stable_pipeline_contracts import (
    WORD_LEDGER_HASH_VERSION,
    canonical_word_ledger_hash,
)
from app.core.subtitle_processor.manual_final_subtitle_editor import (
    ManualFinalSubtitleSession,
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
            "word_id": int(case["word_start"]) + index,
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
            "source_english": page["english"],
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
                    "token": ScreenSubtitleEditor._word_tokens(word)[0],
                    "surface": word,
                    "start_time": segment.start_time + duration * index // len(words),
                    "end_time": segment.start_time + duration * (index + 1) // len(words),
                }
            )
    return entries


def _syntax_backed_page_cue(text, subtitle_id="S0001", *, seconds_per_word=0.32):
    words = text.split()
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = 16
    editor._active_word_entries = [
        {
            "token": ScreenSubtitleEditor._word_tokens(word)[0],
            "surface": word,
            "start_time": round(index * seconds_per_word * 1000),
            "end_time": round((index * seconds_per_word + 0.24) * 1000),
            "alignment_source": "fixture",
        }
        for index, word in enumerate(words)
    ]
    editor._active_source_word_spans = {1: (0, len(words) - 1)}
    editor._syntax_protected_cuts = set()
    editor._syntax_hard_cut_issues = {}
    editor._syntax_soft_cut_issues = {}
    editor._orphaned_finite_predicate_cache = {}
    editor._syntax_nlp = None
    editor._prepare_syntax_cut_hints()
    cue = podcast_learning_video.Cue(
        int(subtitle_id[1:]),
        0.0,
        len(words) * seconds_per_word,
        text,
        "测试字幕。",
        "male",
        subtitle_id=subtitle_id,
        word_timing=tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * seconds_per_word,
                "end": index * seconds_per_word + 0.24,
            }
            for index, word in enumerate(words)
        ),
        display_boundary_evidence=editor._display_boundary_evidence_for_span(
            0, len(words) - 1
        ),
    )
    return editor, cue


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


def _srt_timestamp_from_ms(value):
    milliseconds = int(value)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _write_persisted_manual_draft_package(root, case):
    subtitle_path = root / "manual-final.srt"
    artifact_dir = root / "manual-final-artifacts"
    artifact_dir.mkdir()
    timeline_path = artifact_dir / "final-cue-timeline.json"
    ledger_path = artifact_dir / "word-ledger.json"
    draft_artifact_path = artifact_dir / "manual-draft-page-plan.json"
    manifest_path = root / "stable-final-manifest.json"
    start_ms = round(float(case["start"]) * 1000)
    end_ms = round(float(case["end"]) * 1000)
    words = case["english"].split()
    chinese = str(case["parent_chinese"])
    subtitle_path.write_text(
        "1\n"
        f"{_srt_timestamp_from_ms(start_ms)} --> {_srt_timestamp_from_ms(end_ms)}\n"
        f"{case['english']}\n{chinese}\n",
        encoding="utf-8",
    )
    timeline_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "subtitle_id": case["subtitle_id"],
                        "word_start": 0,
                        "word_end": len(words) - 1,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "original": case["english"],
                        "translated": chinese,
                    }
                ],
                "validation": {"status": "PASS", "errors": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    duration = end_ms - start_ms
    ledger_path.write_text(
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

    manifest = {
        "schema_version": 2,
        "render_blocked": True,
        "validation_error_codes": ["manual_page_translation_required"],
        "paths": {"original_top_srt": str(subtitle_path)},
        "paths_sha256": {
            "original_top_srt": hashlib.sha256(
                subtitle_path.read_bytes()
            ).hexdigest()
        },
        "final_cue_timeline_path": str(timeline_path),
        "final_cue_timeline_sha256": hashlib.sha256(
            timeline_path.read_bytes()
        ).hexdigest(),
        "word_ledger_path": str(ledger_path),
        "word_ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    source_cues = podcast_learning_video.parse_srt(subtitle_path)
    assert podcast_learning_video.attach_article_word_timing(
        source_cues,
        subtitle_path,
    )
    blueprint = podcast_learning_video.build_article_display_page_blueprint(
        source_cues
    )
    frozen_render_plans = blueprint["render_plans"]
    frozen_plan = frozen_render_plans[0]
    manual_draft_chinese_pages = (
        "我是说，如果你能把一种能力很强、",
        "优化程度很高的人工智能，融入经济的每个领域，包括制造业、农业、",
        "本地服务业，而且不需要一个5000亿美元的数据中心来运行它。",
    )
    assert len(frozen_plan["pages"]) == len(manual_draft_chinese_pages)
    assert "".join(manual_draft_chinese_pages) == chinese
    semantic_page_translations = {
        page["display_page_id"]: {
            "parent_subtitle_id": frozen_plan["parent_subtitle_id"],
            "word_start": page["word_start"],
            "word_end": page["word_end"],
            "english": page["english"],
            "chinese": page_chinese,
        }
        for page, page_chinese in zip(
            frozen_plan["pages"],
            manual_draft_chinese_pages,
        )
    }
    draft_artifact = (
        podcast_learning_video.build_article_manual_draft_page_artifact(
            source_cues,
            frozen_render_plans=frozen_render_plans,
            semantic_page_translations=semantic_page_translations,
        )
    )
    assert draft_artifact["status"] == "REVIEW"
    draft_artifact_path.write_text(
        json.dumps(draft_artifact, ensure_ascii=False),
        encoding="utf-8",
    )
    draft_artifact_sha256 = hashlib.sha256(
        draft_artifact_path.read_bytes()
    ).hexdigest()
    manifest.update(
        {
            "manual_draft_page_plan_path": str(draft_artifact_path),
            "manual_draft_page_plan_sha256": draft_artifact_sha256,
            "manual_final_override": {
                "schema_version": 2,
                "subtitle_path": str(subtitle_path),
                "subtitle_sha256": hashlib.sha256(
                    subtitle_path.read_bytes()
                ).hexdigest(),
                "artifact_dir": str(artifact_dir),
                "manual_draft_page_plan_path": str(draft_artifact_path),
                "manual_draft_page_plan_sha256": draft_artifact_sha256,
            },
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "subtitle_path": subtitle_path,
        "manifest_path": manifest_path,
        "draft_artifact_path": draft_artifact_path,
        "draft_artifact": draft_artifact,
    }


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


def test_chinese_token_split_keeps_frozen_plans_and_unaffected_parent_pages():
    parents = [
        {
            "parent_subtitle_id": "S0001",
            "english": "A valid parent",
            "chinese": "甲乙",
            "word_start": 0,
            "word_end": 2,
            "pages": [
                {
                    "display_page_id": "S0001.P01",
                    "word_start": 0,
                    "word_end": 0,
                    "english": "A",
                },
                {
                    "display_page_id": "S0001.P02",
                    "word_start": 1,
                    "word_end": 2,
                    "english": "valid parent",
                },
            ],
        },
        {
            "parent_subtitle_id": "S0002",
            "english": "Students return",
            "chinese": "留学生",
            "word_start": 3,
            "word_end": 4,
            "pages": [
                {
                    "display_page_id": "S0002.P01",
                    "word_start": 3,
                    "word_end": 3,
                    "english": "Students",
                },
                {
                    "display_page_id": "S0002.P02",
                    "word_start": 4,
                    "word_end": 4,
                    "english": "return",
                },
            ],
        },
    ]
    render_plans = [
        {
            "parent_subtitle_id": parent["parent_subtitle_id"],
            "english": parent["english"],
            "chinese": parent["chinese"],
            "word_start": parent["word_start"],
            "word_end": parent["word_end"],
            "english_font_size": 56,
            "pages": [
                {
                    **dict(page),
                    "start_ms": int(page["word_start"]) * 1000,
                    "end_ms": (int(page["word_end"]) + 1) * 1000,
                    "english_lines": [str(page["english"])],
                    "english_font_size": 56,
                    "english_width": 100,
                }
                for page in parent["pages"]
            ],
        }
        for parent in parents
    ]
    contract = build_display_page_contract(
        parents,
        layout_profile={"template": "article"},
        render_plans=render_plans,
    )
    response = {
        "pages": [
            {"display_page_id": "S0001.P01", "zh": "甲"},
            {"display_page_id": "S0001.P02", "zh": "乙"},
            {"display_page_id": "S0002.P01", "zh": "留"},
            {"display_page_id": "S0002.P02", "zh": "学生"},
        ]
    }

    def boundaries(text):
        return {1, 2} if text == "甲乙" else {3}

    with patch(
        "app.core.subtitle_processor.stable_display_page_contract.chinese_token_boundaries",
        side_effect=boundaries,
    ):
        artifact = validate_page_translation_response(contract, response)

    assert artifact["status"] == "ERROR"
    assert artifact["render_plans"] == contract["render_plans"]
    assert [parent["parent_subtitle_id"] for parent in artifact["parents"]] == [
        "S0001"
    ]
    assert artifact["parents"][0]["aggregate_chinese"] == "甲乙"
    assert artifact["errors"] == [
        {
            "code": "page_translation_chinese_token_split",
            "parent_subtitle_id": "S0002",
            "display_page_id": "S0002.P01",
            "boundary_offset": 1,
        }
    ]


def test_page_translation_retry_contract_contains_only_failed_parent_pages():
    parents = [
        {
            "parent_subtitle_id": "S0186",
            "english": "A valid parent with two pages",
            "chinese": "有效父字幕",
            "word_start": 0,
            "word_end": 5,
            "pages": [
                {
                    "display_page_id": "S0186.P01",
                    "word_start": 0,
                    "word_end": 2,
                    "english": "A valid parent",
                },
                {
                    "display_page_id": "S0186.P02",
                    "word_start": 3,
                    "word_end": 5,
                    "english": "with two pages",
                },
            ],
        },
        {
            "parent_subtitle_id": "S0187",
            "english": "back from policy changes to the shift within you",
            "chinese": "从宏观政策巨变，拉回到作为个体的你内心的心理转变。",
            "word_start": 6,
            "word_end": 14,
            "pages": [
                {
                    "display_page_id": "S0187.P01",
                    "word_start": 6,
                    "word_end": 9,
                    "english": "back from policy changes",
                },
                {
                    "display_page_id": "S0187.P02",
                    "word_start": 10,
                    "word_end": 14,
                    "english": "to the shift within you",
                },
            ],
        },
    ]
    render_plans = []
    for parent in parents:
        render_plans.append(
            {
                "parent_subtitle_id": parent["parent_subtitle_id"],
                "english": parent["english"],
                "chinese": parent["chinese"],
                "word_start": parent["word_start"],
                "word_end": parent["word_end"],
                "english_font_size": 56,
                "pages": [
                    {
                        **dict(page),
                        "start_ms": int(page["word_start"]) * 1000,
                        "end_ms": (int(page["word_end"]) + 1) * 1000,
                        "english_lines": [page["english"]],
                        "english_font_size": 56,
                        "english_width": 100,
                    }
                    for page in parent["pages"]
                ],
            }
        )
    contract = build_display_page_contract(
        parents,
        layout_profile={"template": "article"},
        render_plans=render_plans,
    )

    retry_contract = ScreenSubtitleEditor._display_page_retry_contract(
        contract,
        [
            {
                "code": "page_translation_chinese_token_split",
                "parent_subtitle_id": "S0187",
                "display_page_id": "S0187.P01",
            }
        ],
    )

    assert [
        parent["parent_subtitle_id"] for parent in retry_contract["parents"]
    ] == ["S0187"]
    assert [
        plan["parent_subtitle_id"] for plan in retry_contract["render_plans"]
    ] == ["S0187"]
    assert [
        page["display_page_id"]
        for page in retry_contract["parents"][0]["pages"]
    ] == ["S0187.P01", "S0187.P02"]

    baseline = validate_page_translation_response(
        contract,
        {
            "pages": [
                {
                    "display_page_id": "S0186.P01",
                    "source_english": "A valid parent",
                    "zh": "有效",
                },
                {
                    "display_page_id": "S0186.P02",
                    "source_english": "with two pages",
                    "zh": "父字幕",
                },
                {
                    "display_page_id": "S0187.P01",
                    "source_english": "back from policy changes",
                    "zh": "从宏观政策巨变，拉回",
                },
                {
                    "display_page_id": "S0187.P02",
                    "source_english": "to the shift within you",
                    "zh": "到作为个体的你内心的心理转变。",
                },
            ]
        },
        require_source_echo=True,
    )
    assert baseline["status"] == "ERROR"
    assert [parent["parent_subtitle_id"] for parent in baseline["parents"]] == [
        "S0186"
    ]
    retry_artifact = validate_page_translation_response(
        retry_contract,
        {
            "pages": [
                {
                    "display_page_id": "S0187.P01",
                    "source_english": "back from policy changes",
                    "zh": "从宏观政策巨变",
                },
                {
                    "display_page_id": "S0187.P02",
                    "source_english": "to the shift within you",
                    "zh": "拉回到作为个体的你内心的心理转变。",
                },
            ]
        },
        require_source_echo=True,
    )
    assert retry_artifact["status"] == "PASS"

    merged = ScreenSubtitleEditor._merge_display_page_translation_artifacts(
        contract,
        baseline,
        retry_artifact,
    )

    assert merged["status"] == "PASS"
    assert parent_chinese_by_id(merged) == {
        "S0186": "有效父字幕",
        "S0187": "从宏观政策巨变拉回到作为个体的你内心的心理转变。",
    }


def test_structural_page_response_forces_full_contract_retry():
    case = _cases()["s0078_reordered_chinese"]
    contract = build_display_page_contract(
        [
            {
                "parent_subtitle_id": case["subtitle_id"],
                "english": case["english"],
                "chinese": case["parent_chinese"],
                "word_start": case["word_start"],
                "word_end": case["word_end"],
                "pages": [
                    {
                        "display_page_id": display_page_id(case["subtitle_id"], index),
                        "word_start": page["word_start"],
                        "word_end": page["word_end"],
                        "english": page["english"],
                    }
                    for index, page in enumerate(case["pages"], 1)
                ],
            },
            {
                "parent_subtitle_id": "S0187",
                "english": "A second parent",
                "chinese": "第二条父字幕",
                "word_start": 20,
                "word_end": 22,
                "pages": [
                    {
                        "display_page_id": "S0187.P01",
                        "word_start": 20,
                        "word_end": 20,
                        "english": "A",
                    },
                    {
                        "display_page_id": "S0187.P02",
                        "word_start": 21,
                        "word_end": 22,
                        "english": "second parent",
                    },
                ],
            },
        ],
        layout_profile={"template": "article"},
    )
    structural_errors = [
        {"code": "page_translation_id_missing", "ids": ["S0001.P02"]},
        {"code": "page_translation_cardinality_mismatch"},
    ]
    full_retry = ScreenSubtitleEditor._display_page_errors_require_full_retry(
        structural_errors
    )
    assert full_retry
    retry = (
        contract
        if full_retry
        else ScreenSubtitleEditor._display_page_retry_contract(
            contract, structural_errors
        )
    )
    assert [parent["parent_subtitle_id"] for parent in retry["parents"]] == [
        case["subtitle_id"],
        "S0187",
    ]


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

    changed_planner = copy.deepcopy(contract)
    changed_planner["planner_version"] = "article-fixed-font-pages-next"
    assert key(contract) != key(changed_planner)


def test_page_contract_and_cache_identity_include_frozen_font_and_boundary_evidence():
    case = _cases()["s0078_reordered_chinese"]
    cue = _timed_cue(case)
    cue.display_boundary_evidence = {
        str(case["pages"][1]["word_start"]): {
            "hard_issues": [],
            "soft_issues": ["dependency_phrase_entrance_split"],
            "boundary_score": 12.0,
            "pause_ms": 120,
        }
    }
    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])

    def build(render_plans):
        return build_display_page_contract(
            blueprint["parents"],
            layout_profile=blueprint["layout_profile"],
            planner_version=blueprint["planner_version"],
            render_plans=render_plans,
        )

    def key(contract):
        return page_translation_cache_key(
            contract,
            model="test-model",
            target_language="简体中文",
            prompt_version="display-page-translation-v2",
            algorithm_version="fixed-parent-page-allocation-v3",
        )

    baseline = build(blueprint["render_plans"])
    changed_font_plans = copy.deepcopy(blueprint["render_plans"])
    changed_font_plans[0]["english_font_size"] = 54
    changed_font_plans[0]["font_fallback"] = {
        "used": True,
        "from": 56,
        "to": 54,
        "reason": "test",
    }
    for page in changed_font_plans[0]["pages"]:
        page["english_font_size"] = 54
    changed_boundary_plans = copy.deepcopy(blueprint["render_plans"])
    changed_boundary_plans[0]["pages"][1]["boundary_before"] = {
        "classification": "hard",
        "confidence": "high",
        "issue_codes": ["test_atomic_boundary"],
    }

    changed_font = build(changed_font_plans)
    changed_boundary = build(changed_boundary_plans)

    assert baseline["contract_hash"] != changed_font["contract_hash"]
    assert baseline["contract_hash"] != changed_boundary["contract_hash"]
    assert key(baseline) != key(changed_font)
    assert key(baseline) != key(changed_boundary)


def test_article_english_font_fallback_has_a_strict_50px_floor():
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_FALLBACK_SIZES == (
        56,
        54,
        52,
        50,
    )
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_EMERGENCY_FALLBACK_SIZES == ()
    assert (
        podcast_learning_video.ARTICLE_SUBTITLE_EN_ALLOWED_SIZES
        == podcast_learning_video.ARTICLE_SUBTITLE_EN_FALLBACK_SIZES
    )
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE == 50
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_MIN_SIZE == 50


def test_screenshot_page_boundaries_consume_frozen_boundary_evidence():
    cases = [
        (
            "They're diverting those funds toward getting better results from accessible, some to much older hardware.",
            "results",
            "from",
        ),
        (
            "like write text or play chess, but can reason through completely novel problems across any discipline.",
            "reason",
            "through",
        ),
        (
            "But I'm looking at these sources, and they're arguing that being cut off from the most sophisticated chip-making gear is actually forcing these companies to become better engineers.",
            "they're",
            "arguing",
        ),
        (
            "And achieving that level of universal, human-like reasoning across every domain requires an almost infinite amount of computing power.",
            "every",
            "domain",
        ),
        (
            "You can't spend billions building an AGI model and expect to charge them a massive premium to use it.",
            "expect",
            "to",
        ),
        (
            "You have to build something highly efficient that delivers an immediate, undeniable, and cheap return on investment.",
            "immediate,",
            "undeniable,",
        ),
        (
            "We've actually seen reports in these sources that highly demanded AI services from Zipu AI,",
            "reports",
            "in",
        ),
        (
            "Because the global market, which initially rewarded America's tech giants with higher share prices for these aggressive AI spending plans, they're suddenly looking across the Pacific.",
            "share",
            "prices",
        ),
        (
            "relying on far less computing power, and completely avoiding these massive capital sinkholes.",
            "and",
            "completely",
        ),
        (
            "I mean, Chinese tech titans are projected to invest less than a tenth of that amount in data centers by 2026.",
            "invest",
            "less",
        ),
    ]
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    for case_index, (text, left_word, right_word) in enumerate(cases, 1):
        words = text.split()
        split = next(
            index
            for index in range(1, len(words))
            if words[index - 1] == left_word and words[index] == right_word
        )
        cue = podcast_learning_video.Cue(
            case_index,
            0.0,
            max(4.0, len(words) * 0.35),
            text,
            "测试字幕。",
            "male",
            subtitle_id=f"S{case_index:04d}",
        )
        cue.word_timing = tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * 0.3,
                "end": index * 0.3 + 0.22,
            }
            for index, word in enumerate(words)
        )
        cue.display_boundary_evidence = {
            str(split): {
                "hard_issues": ["test_atomic_boundary"],
                "soft_issues": [],
                "boundary_score": 0.0,
                "pause_ms": 80,
            }
        }

        plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

        assert plan["status"] == "ok", text
        assert split not in {page["word_start"] for page in plan["pages"][1:]}, text


def test_real_syntax_evidence_steers_results_from_without_injected_fixture_issue():
    text = (
        "They're diverting those funds toward getting better results from "
        "accessible, some to much older hardware."
    )
    editor, cue = _syntax_backed_page_cue(text, "S0066")
    words = text.split()
    split = words.index("from")
    evaluation = editor._evaluate_stable_cut_boundary(split - 1, split)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert "dependency_phrase_entrance_split" in evaluation["soft_issues"]
    assert plan["status"] == "ok"
    assert split not in {page["word_start"] for page in plan["pages"][1:]}
    assert words.index("some") in {
        page["word_start"] for page in plan["pages"][1:]
    }


def test_medium_review_page_boundary_can_beat_static_font_reduction_on_quality():
    text = (
        "We've actually seen reports in these sources that highly demanded AI "
        "services from Zipu AI,"
    )
    _, cue = _syntax_backed_page_cue(text, "S0221")
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 2
    assert plan["font_size"]["english"] == 56
    assert plan["font_fallback"] == {"used": False}
    assert plan["pages"][1]["boundary_before"]["classification"] == "review"
    assert plan["pages"][1]["boundary_before"]["confidence"] == "medium"
    assert " ".join(page["en"] for page in plan["pages"]) == text


def test_unsupported_tight_page_transition_loses_to_same_font_static_layout():
    text = (
        "Just to make the older machines do something they were never "
        "designed to do."
    )
    _, cue = _syntax_backed_page_cue(text, "S0150")
    words = text.split()
    split = words.index("they")
    decision = podcast_learning_video._article_display_boundary_decision(cue, split)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert decision["classification"] == "review"
    assert decision["confidence"] == "low"
    assert "unsupported_tight_page_transition" in decision["issue_codes"]
    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 1
    assert plan["font_size"]["english"] == 56


def test_complete_phrase_page_starts_remain_eligible_without_a_pause():
    cases = (
        (
            "So they literally have to invent entirely new ways to solve the same "
            "math problem out of pure survival.",
            "ways",
            "to",
        ),
        (
            "smaller Chinese AI firms aren't throwing their limited capital into a "
            "bottomless pit of cutting-edge chips to process raw data.",
            "capital",
            "into",
        ),
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    for case_index, (text, page_left, page_start) in enumerate(cases, 1):
        words = text.split()
        split = next(
            index
            for index in range(1, len(words))
            if words[index - 1] == page_left and words[index] == page_start
        )
        cue = podcast_learning_video.Cue(
            case_index,
            0.0,
            10.0,
            text,
            "测试字幕。",
            "male",
            subtitle_id=f"S{case_index:04d}",
            word_timing=tuple(
                {
                    "word_id": index,
                    "surface": word,
                    "start": index * 0.4,
                    "end": index * 0.4 + 0.4,
                }
                for index, word in enumerate(words)
            ),
        )

        plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

        assert plan["status"] == "ok", text
        assert plan["font_size"]["english"] == 56, text
        assert podcast_learning_video._article_page_break_score(
            cue,
            words,
            split,
            len(words) / 2,
            cue.word_timing,
        ) is not None, text


def test_atomic_of_and_dangling_coordinator_page_boundaries_are_hard():
    cases = (
        ("They underwrite half of a large data center.", "half", "of"),
        ("They reviewed the sources and they reached a conclusion.", "and", "they"),
    )

    for case_index, (text, left_word, right_word) in enumerate(cases, 1):
        _, cue = _syntax_backed_page_cue(text, f"S{case_index:04d}")
        words = text.split()
        split = next(
            index
            for index in range(1, len(words))
            if words[index - 1] == left_word and words[index] == right_word
        )

        decision = podcast_learning_video._article_display_boundary_decision(
            cue,
            split,
        )

        assert decision["classification"] == "hard", text
        assert decision["confidence"] == "high", text


def test_strong_pause_makes_clause_level_hard_page_boundary_reviewable():
    text = (
        "But I'm looking at these sources, and they're arguing that being cut "
        "off from the most sophisticated chip-making gear is actually forcing "
        "these companies to become better engineers."
    )
    editor, cue = _syntax_backed_page_cue(text, "S0120")
    words = text.split()
    cursor = 0.0
    timings = []
    for index, word in enumerate(words):
        if word == "being":
            cursor += 0.9
        elif word == "is":
            cursor += 0.8
        start = cursor
        end = start + 0.24
        timings.append(
            {
                "word_id": index,
                "surface": word,
                "start": start,
                "end": end,
            }
        )
        cursor = end + 0.04
    cue.word_timing = tuple(timings)
    cue.end = timings[-1]["end"] + 0.12
    cue.display_boundary_evidence = editor._display_boundary_evidence_for_span(
        0, len(words) - 1
    )
    for split in range(1, len(words)):
        evidence = cue.display_boundary_evidence.get(str(split))
        if evidence is not None:
            evidence["pause_ms"] = round(
                (timings[split]["start"] - timings[split - 1]["end"]) * 1000
            )

    split = words.index("is")
    decision = podcast_learning_video._article_display_boundary_decision(cue, split)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert "subject_finite_verb_split" in decision["issue_codes"]
    assert decision["classification"] == "review"
    assert decision["confidence"] == "high"
    assert decision["pause_ms"] >= 600
    assert plan["status"] == "ok"
    page_starts = {page["word_start"] for page in plan["pages"][1:]}
    assert words.index("and") in page_starts
    assert split in page_starts


def test_low_confidence_tight_transition_does_not_force_major_font_reduction():
    text = (
        "They're tasked with producing advanced chips domestically to replace "
        "the ones they can no longer import."
    )
    _, cue = _syntax_backed_page_cue(text, "S0126")
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert plan["font_size"]["english"] == 56


def test_page_context_prefers_whole_attached_phrases_over_atomic_inner_cuts():
    cases = (
        (
            "and then engineering a lightweight, highly aerodynamic four-cylinder "
            "engine that somehow wins the exact same race,",
            "somehow",
            "wins",
        ),
        (
            "They're forcing the domestic supply chain to communicate and optimize "
            "at a level they never would have reached if they could just easily "
            "import the hardware.",
            "they",
            "never",
        ),
        (
            "Because in America, you have dozens of incredibly well-funded firms "
            "locked in this expensive, almost existential race to develop AGI, "
            "artificial general intelligence.",
            "locked",
            "in",
        ),
        (
            "I mean, if you can integrate a highly capable, highly optimized AI "
            "into every facet of your economy, manufacturing, agriculture, local "
            "services, without requiring a 500 billion data center to run it.",
            "facet",
            "of",
        ),
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    for case_index, (text, bad_left, bad_right) in enumerate(cases, 1):
        _, cue = _syntax_backed_page_cue(
            text,
            f"S{case_index:04d}",
            seconds_per_word=0.4,
        )
        words = text.split()
        bad_split = next(
            index
            for index in range(1, len(words))
            if words[index - 1] == bad_left and words[index] == bad_right
        )

        plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

        assert plan["status"] == "ok", text
        assert bad_split not in {
            page["word_start"] for page in plan["pages"][1:]
        }, text


def test_structural_exception_can_use_actual_pixel_fit_above_sixteen_words():
    text = (
        "But the truly wild part of that leak is that NVIDIA's stock didn't "
        "soar on the news."
    )
    _, cue = _syntax_backed_page_cue(text, "S0002")
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert len(text.split()) == 17
    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 1
    assert plan["font_size"]["english"] == 56


def test_no_partition_failure_reports_deterministic_attempt_reasons():
    text = "Supercalifragilisticexpialidocious Pneumonoultramicroscopicsilicovolcanoconiosis"
    _, cue = _syntax_backed_page_cue(text, "S0999", seconds_per_word=0.2)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert plan["status"] == "render_structural_overflow"
    assert plan["errors"][0]["attempted_reasons"]
    assert "fixed_font_span_unreadable" in plan["errors"][0]["attempted_reasons"]


def test_invalid_page_translation_cache_is_replaced_only_after_validation():
    case = _cases()["s0078_reordered_chinese"]
    contract = _contract(case)
    invalid_cached = {
        "pages": [
            {
                "display_page_id": display_page_id(case["subtitle_id"], 1),
                "zh": case["pages"][0]["chinese"],
            }
        ]
    }
    valid_fresh = _response(case)

    class Cache:
        def __init__(self):
            self.writes = []

        def get_llm_result(self, *args, **kwargs):
            return json.dumps(invalid_cached, ensure_ascii=False)

        def set_llm_result(self, *args, **kwargs):
            self.writes.append(json.loads(args[1]))

    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.article_context_prompt = ""
    editor.model = "test-model"
    editor.target_language = "简体中文"
    editor.timeout = 5
    editor.cache_manager = Cache()
    editor._llm_cache_stats = {}
    editor._llm_cache_used = False
    editor._display_page_external_request_count = 0
    editor._display_page_translation_reviews = []
    editor.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps(valid_fresh, ensure_ascii=False)
                            )
                        )
                    ]
                )
            )
        )
    )

    result, cache_hit = editor._request_display_page_translations(contract)

    assert result == valid_fresh
    assert cache_hit is False
    assert editor.cache_manager.writes == [valid_fresh]
    assert editor._display_page_external_request_count == 1


def test_page_translation_source_echo_is_required_for_new_requests():
    case = _cases()["s0078_reordered_chinese"]
    contract = _contract(case)
    valid = _response(case)
    missing = json.loads(json.dumps(valid, ensure_ascii=False))
    missing["pages"][0].pop("source_english")
    mismatched = json.loads(json.dumps(valid, ensure_ascii=False))
    mismatched["pages"][0]["source_english"] = case["pages"][1]["english"]

    assert validate_page_translation_response(
        contract, valid, require_source_echo=True
    )["status"] == "PASS"
    missing_result = validate_page_translation_response(
        contract, missing, require_source_echo=True
    )
    mismatch_result = validate_page_translation_response(
        contract, mismatched, require_source_echo=True
    )
    assert "page_translation_source_echo_missing" in _error_codes(missing_result)
    assert "page_translation_source_echo_mismatch" in _error_codes(mismatch_result)


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
        blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])
        assert blueprint["parents"], case["case_id"]
        frozen_plan = blueprint["render_plans"][0]
        frozen_parent = blueprint["parents"][0]
        page_count = len(frozen_parent["pages"])
        chinese = case["parent_chinese"]
        page_word_counts = [
            int(page["word_end"]) - int(page["word_start"]) + 1
            for page in frozen_parent["pages"]
        ]
        expected_chinese = (
            podcast_learning_video._strict_split_chinese_visual_pages(
                chinese,
                page_count,
                page_word_counts,
                strict=True,
            )
        )
        assert expected_chinese is not None
        assert len(expected_chinese) == page_count
        contract = build_display_page_contract(
            [frozen_parent],
            layout_profile=blueprint["layout_profile"],
            planner_version=blueprint["planner_version"],
            render_plans=blueprint["render_plans"],
        )
        artifact = validate_page_translation_response(
            contract,
            {
                "pages": [
                    {
                        "display_page_id": page["display_page_id"],
                        "zh": zh,
                    }
                    for page, zh in reversed(
                        list(zip(frozen_parent["pages"], expected_chinese))
                    )
                ]
            },
        )
        cue.zh = parent_chinese_by_id(artifact)[case["subtitle_id"]]
        assert podcast_learning_video.apply_article_display_page_translation_artifact(
            [cue],
            artifact,
        )

        with patch.object(
            podcast_learning_video,
            "_strict_split_chinese_visual_pages",
            side_effect=AssertionError("proportional Chinese fallback is forbidden"),
        ):
            plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

        assert plan["status"] == "ok"
        assert plan["font_size"] == {
            "english": int(frozen_plan["english_font_size"]),
            "chinese": 46,
        }
        assert [page["display_page_id"] for page in plan["pages"]] == [
            page["display_page_id"] for page in frozen_plan["pages"]
        ]
        assert " ".join(page["en"] for page in plan["pages"]) == case["english"]
        assert [page["zh"] for page in plan["pages"]] == expected_chinese


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
        # The production contract now validates an exact per-page source echo.
        # This fixture returns that echo, so no retry should be necessary.
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
                        "source_english": page["english"],
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
    post_page_audits = []

    def capture_post_page_artifacts(*args, **kwargs):
        audit = editor._english_boundary_audit_payload(kwargs["final_segments"])
        post_page_audits.append(audit)

    editor._write_stable_pipeline_artifacts = capture_post_page_artifacts

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
    assert post_page_audits
    assert post_page_audits[-1]["schema_version"] == 2
    assert any(
        record.get("scope") == "display_page"
        for record in post_page_audits[-1]["records"]
    )


def test_screen_editor_records_visual_overflow_against_the_frozen_subtitle_id():
    text = (
        "the ultimate consequence of this AI-enabled independence is a massive "
        "redistribution of where economic value actually flows."
    )
    segment = ASRDataSeg(text, 1000, 8600, "这是完整中文。")
    segment.subtitle_id = "S0201"
    segment.word_start = 0
    segment.word_end = len(text.split()) - 1
    asr_data = ASRData([segment])
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.enable_stable_mode = True
    editor._active_word_entries = _word_entries_for_segments(asr_data.segments)
    editor._active_source_segments_by_id = {}
    editor._last_semantic_groups = []
    editor._last_subtitle_items = []
    editor._translation_structure_errors = []
    editor._display_page_translation_artifact = {}
    editor._display_page_translation_path = ""
    editor._display_page_external_request_count = 0
    editor.coverage_report_path = None
    editor._display_boundary_evidence_for_span = lambda *args, **kwargs: {}
    before = (segment.text, segment.translated_text, segment.start_time, segment.end_time)

    overflow = podcast_learning_video.RenderStructuralOverflowError(
        [{"cue_index": 1, "reason": "hard_page_boundary"}]
    )
    with patch(
        "app.core.utils.podcast_learning_video.build_article_display_page_blueprint",
        side_effect=overflow,
    ):
        try:
            editor.apply_display_page_translations_after_final_timing(asr_data)
        except RuntimeError as exc:
            assert "display_page_translation_invalid" in str(exc)
        else:
            raise AssertionError("visual overflow must remain render-blocking")

    issue = editor._translation_structure_errors[-1]
    assert issue["code"] == "display_page_blueprint_invalid"
    assert issue["subtitle_ids"] == ["S0201"]
    assert issue["items"] == [
        {
            "subtitle_id": "S0201",
            "cue_index": 1,
            "reason": "hard_page_boundary",
        }
    ]
    assert (segment.text, segment.translated_text, segment.start_time, segment.end_time) == before


def test_screen_editor_normalizes_page_errors_to_frozen_parent_ids():
    parents = [
        {
            "parent_subtitle_id": "S0201",
            "pages": [
                {"display_page_id": "S0201.P01"},
                {"display_page_id": "S0201.P02"},
            ],
        },
        {
            "parent_subtitle_id": "S0202",
            "pages": [{"display_page_id": "S0202.P01"}],
        },
    ]
    items = ScreenSubtitleEditor._display_page_failure_items(
        [
            {
                "code": "page_translation_chinese_token_split",
                "display_page_id": "S0201.P02",
            },
            {
                "code": "missing_display_page_ids",
                "ids": ["S0202.P01"],
            },
        ],
        parents,
        fallback_reason="display_page_translation_invalid",
    )

    assert items == [
        {
            "subtitle_id": "S0201",
            "display_page_id": "S0201.P02",
            "reason": "page_translation_chinese_token_split",
        },
        {
            "subtitle_id": "S0202",
            "display_page_id": "S0202.P01",
            "reason": "missing_display_page_ids",
        },
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
        stable_sha256 = hashlib.sha256(subtitle_path.read_bytes()).hexdigest()
        manifest_path.write_text(
            json.dumps(
                {
                    "paths": {"original_top_srt": str(subtitle_path)},
                    "paths_sha256": {"original_top_srt": stable_sha256},
                    "final_cue_timeline_path": str(timeline_path),
                }
            ),
            encoding="utf-8",
        )
        source_cues = podcast_learning_video.parse_srt(subtitle_path)
        assert podcast_learning_video.attach_article_word_timing(source_cues, subtitle_path)
        blueprint = podcast_learning_video.build_article_display_page_blueprint(source_cues)
        contract = build_display_page_contract(
            blueprint["parents"],
            layout_profile=blueprint["layout_profile"],
            planner_version=blueprint["planner_version"],
            render_plans=blueprint["render_plans"],
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
                    "paths": {"original_top_srt": str(subtitle_path)},
                    "paths_sha256": {"original_top_srt": stable_sha256},
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
        with patch.object(
            podcast_learning_video,
            "_build_article_english_page_plan",
            side_effect=AssertionError("renderer must consume the frozen plan"),
        ):
            podcast_learning_video.prepare_article_visual_page_plans(
                valid_cues,
                subtitle_path,
            )
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


def test_parse_srt_preserves_numeric_only_bilingual_line_order():
    cases = (
        ("90%?\n90%？", "90%?", "90%？"),
        ("90%？\n90%?", "90%?", "90%？"),
    )
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        for index, (payload, expected_english, expected_chinese) in enumerate(
            cases,
            1,
        ):
            subtitle_path = root / f"numeric-{index}.srt"
            subtitle_path.write_text(
                f"1\n00:00:00,000 --> 00:00:01,000\n{payload}\n",
                encoding="utf-8",
            )

            cue = podcast_learning_video.parse_srt(subtitle_path)[0]

            assert cue.en == expected_english
            assert cue.zh == expected_chinese


def test_attach_article_word_timing_restores_hash_bound_boundary_evidence():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subtitle_path = root / "stable-final-original-top.srt"
        timeline_path = root / "final-cue-timeline.json"
        ledger_path = root / "word-ledger.json"
        evidence_path = root / "display-boundary-evidence.json"
        manifest_path = root / "stable-final-manifest.json"
        english = "Models improve through feedback."
        chinese = "模型通过反馈改进。"
        subtitle_path.write_text(
            f"1\n00:00:00,000 --> 00:00:04,000\n{english}\n{chinese}\n",
            encoding="utf-8",
        )
        timeline_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "subtitle_id": "S0001",
                            "word_start": 0,
                            "word_end": 3,
                            "start_ms": 0,
                            "end_ms": 4000,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        ledger_path.write_text(
            json.dumps(
                {
                    "words": [
                        {"surface": word, "start_ms": index * 1000, "end_ms": (index + 1) * 1000}
                        for index, word in enumerate(english.split())
                    ]
                }
            ),
            encoding="utf-8",
        )
        boundaries = {
            "1": {"hard_issues": ["subject_predicate_split"], "soft_issues": [], "pause_ms": 0},
            "2": {"hard_issues": ["verb_preposition_complement_split"], "soft_issues": [], "pause_ms": 0},
            "3": {"hard_issues": [], "soft_issues": [], "pause_ms": 420},
        }
        evidence_path.write_text(
            json.dumps({"boundaries": boundaries}),
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(
                {
                    "paths": {"original_top_srt": str(subtitle_path)},
                    "paths_sha256": {
                        "original_top_srt": hashlib.sha256(
                            subtitle_path.read_bytes()
                        ).hexdigest()
                    },
                    "final_cue_timeline_path": str(timeline_path),
                    "final_cue_timeline_sha256": hashlib.sha256(
                        timeline_path.read_bytes()
                    ).hexdigest(),
                    "word_ledger_path": str(ledger_path),
                    "word_ledger_sha256": hashlib.sha256(
                        ledger_path.read_bytes()
                    ).hexdigest(),
                    "display_boundary_evidence_path": str(evidence_path),
                    "display_boundary_evidence_sha256": hashlib.sha256(
                        evidence_path.read_bytes()
                    ).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

        cues = podcast_learning_video.parse_srt(subtitle_path)
        assert podcast_learning_video.attach_article_word_timing(cues, subtitle_path)
        assert cues[0].display_boundary_evidence == boundaries

        evidence_path.write_text(
            json.dumps({"boundaries": {**boundaries, "2": {}}}),
            encoding="utf-8",
        )
        tampered = podcast_learning_video.parse_srt(subtitle_path)
        assert not podcast_learning_video.attach_article_word_timing(
            tampered,
            subtitle_path,
        )
        assert tampered[0].display_boundary_evidence is None


def test_manual_draft_page_artifact_is_loaded_only_from_manifest_hash_binding():
    case = _cases()["s0252_monotonic_chinese"]
    with tempfile.TemporaryDirectory() as raw:
        package = _write_persisted_manual_draft_package(Path(raw), case)
        manifest = json.loads(
            package["manifest_path"].read_text(encoding="utf-8")
        )
        override = manifest["manual_final_override"]
        assert manifest["manual_draft_page_plan_path"] == override[
            "manual_draft_page_plan_path"
        ]
        assert manifest["manual_draft_page_plan_sha256"] == override[
            "manual_draft_page_plan_sha256"
        ]
        assert override["artifact_dir"] == str(
            package["draft_artifact_path"].parent
        )
        assert package["draft_artifact"]["status"] == "REVIEW"
        assert all(
            "chinese" in page and "zh" not in page
            for plan in package["draft_artifact"]["render_plans"]
            for page in plan["pages"]
        )
        cues = podcast_learning_video.parse_srt(package["subtitle_path"])
        assert podcast_learning_video.attach_article_word_timing(
            cues,
            package["subtitle_path"],
        )

        assert podcast_learning_video.load_article_manual_draft_page_artifact(
            cues,
            package["subtitle_path"],
        )
        assert cues[0].article_page_plan["status"] == "ok"

        unbound_manifest = copy.deepcopy(manifest)
        unbound_manifest.pop("manual_draft_page_plan_sha256")
        package["manifest_path"].write_text(
            json.dumps(unbound_manifest, ensure_ascii=False),
            encoding="utf-8",
        )
        unbound_cues = podcast_learning_video.parse_srt(package["subtitle_path"])
        assert podcast_learning_video.attach_article_word_timing(
            unbound_cues,
            package["subtitle_path"],
        )
        assert not podcast_learning_video.load_article_manual_draft_page_artifact(
            unbound_cues,
            package["subtitle_path"],
        )

        mismatched_override = copy.deepcopy(manifest)
        mismatched_override["manual_final_override"][
            "manual_draft_page_plan_sha256"
        ] = "0" * 64
        package["manifest_path"].write_text(
            json.dumps(mismatched_override, ensure_ascii=False),
            encoding="utf-8",
        )
        mismatched_cues = podcast_learning_video.parse_srt(
            package["subtitle_path"]
        )
        assert podcast_learning_video.attach_article_word_timing(
            mismatched_cues,
            package["subtitle_path"],
        )
        assert not podcast_learning_video.load_article_manual_draft_page_artifact(
            mismatched_cues,
            package["subtitle_path"],
        )

        wrong_owner = copy.deepcopy(manifest)
        wrong_owner["manual_final_override"]["artifact_dir"] = str(
            package["subtitle_path"].parent
        )
        package["manifest_path"].write_text(
            json.dumps(wrong_owner, ensure_ascii=False),
            encoding="utf-8",
        )
        wrong_owner_cues = podcast_learning_video.parse_srt(
            package["subtitle_path"]
        )
        assert podcast_learning_video.attach_article_word_timing(
            wrong_owner_cues,
            package["subtitle_path"],
        )
        assert not podcast_learning_video.load_article_manual_draft_page_artifact(
            wrong_owner_cues,
            package["subtitle_path"],
        )


def test_manual_draft_preflight_consumes_frozen_artifact_without_replanning():
    case = _cases()["s0252_monotonic_chinese"]
    with tempfile.TemporaryDirectory() as raw:
        package = _write_persisted_manual_draft_package(Path(raw), case)
        cues = podcast_learning_video.parse_srt(package["subtitle_path"])

        with (
            patch.object(
                podcast_learning_video,
                "_build_article_english_page_plan",
                side_effect=AssertionError("frozen manual draft must not replan"),
            ) as strict_planner,
            patch.object(
                podcast_learning_video,
                "build_article_manual_draft_page_plan",
                side_effect=AssertionError("frozen manual draft must not fallback"),
            ) as fallback_planner,
        ):
            podcast_learning_video.prepare_article_visual_page_plans(
                cues,
                package["subtitle_path"],
                allow_manual_draft=True,
            )

        strict_planner.assert_not_called()
        fallback_planner.assert_not_called()
        assert cues[0].article_page_plan["status"] == "ok"


def test_manual_draft_preflight_rejects_missing_or_tampered_artifact_before_ffmpeg():
    case = _cases()["s0252_monotonic_chinese"]
    for mutation in ("missing", "tampered"):
        with tempfile.TemporaryDirectory() as raw:
            package = _write_persisted_manual_draft_package(Path(raw), case)
            if mutation == "missing":
                package["draft_artifact_path"].unlink()
            else:
                package["draft_artifact_path"].write_bytes(
                    package["draft_artifact_path"].read_bytes() + b"\n"
                )
            cues = podcast_learning_video.parse_srt(package["subtitle_path"])

            with (
                patch.object(
                    podcast_learning_video,
                    "_build_article_english_page_plan",
                    side_effect=AssertionError("invalid persisted draft must not replan"),
                ) as strict_planner,
                patch.object(
                    podcast_learning_video,
                    "build_article_manual_draft_page_plan",
                    side_effect=AssertionError("invalid persisted draft must not fallback"),
                ) as fallback_planner,
                patch.object(podcast_learning_video.subprocess, "Popen") as popen,
            ):
                try:
                    podcast_learning_video.prepare_article_visual_page_plans(
                        cues,
                        package["subtitle_path"],
                        allow_manual_draft=True,
                    )
                except podcast_learning_video.RenderStructuralOverflowError as exc:
                    assert any(
                        error.get("reason")
                        == "missing_or_invalid_manual_draft_page_artifact"
                        for error in exc.errors
                    )
                else:
                    raise AssertionError(
                        "missing or tampered manual draft artifact must fail preflight"
                    )

            strict_planner.assert_not_called()
            fallback_planner.assert_not_called()
            assert not popen.called


def test_loaded_manual_draft_pages_match_persisted_identity_text_timing_and_font():
    case = _cases()["s0252_monotonic_chinese"]
    with tempfile.TemporaryDirectory() as raw:
        package = _write_persisted_manual_draft_package(Path(raw), case)
        cues = podcast_learning_video.parse_srt(package["subtitle_path"])

        podcast_learning_video.prepare_article_visual_page_plans(
            cues,
            package["subtitle_path"],
            allow_manual_draft=True,
        )

        frozen_plan = package["draft_artifact"]["render_plans"][0]
        loaded_plan = cues[0].article_page_plan
        assert loaded_plan["source"] == "frozen_manual_draft_page_artifact"
        assert loaded_plan["font_size"]["english"] == frozen_plan[
            "english_font_size"
        ]
        assert len(loaded_plan["pages"]) == len(frozen_plan["pages"])
        for loaded, frozen in zip(loaded_plan["pages"], frozen_plan["pages"]):
            assert loaded["display_page_id"] == frozen["display_page_id"]
            assert loaded["parent_subtitle_id"] == frozen_plan[
                "parent_subtitle_id"
            ]
            assert loaded["en"] == frozen["english"]
            assert loaded["zh"] == frozen["chinese"]
            assert loaded["global_word_start"] == frozen["word_start"]
            assert loaded["global_word_end"] == frozen["word_end"]
            assert round(loaded["start"] * 1000) == frozen["start_ms"]
            assert round(loaded["end"] * 1000) == frozen["end_ms"]
            assert loaded["english_font_size"] == frozen["english_font_size"]
            assert loaded["en_lines"] == frozen["english_lines"]
            assert loaded["en_width"] == frozen["english_width"]


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


def test_frozen_artifact_mismatch_reports_the_exact_single_page_parent():
    cue = podcast_learning_video.Cue(
        199,
        0.0,
        3.0,
        "A complete short sentence.",
        "一条完整的短句。",
        "male",
        subtitle_id="S0199",
        word_timing=tuple(
            {
                "word_id": index,
                "surface": word,
                "start": index * 0.7,
                "end": index * 0.7 + 0.5,
            }
            for index, word in enumerate("A complete short sentence.".split())
        ),
    )
    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])
    artifact = {
        "schema_version": podcast_learning_video.DISPLAY_PAGE_SCHEMA_VERSION,
        "status": "PASS",
        "planner_version": blueprint["planner_version"],
        "layout_profile": blueprint["layout_profile"],
        "render_plans": blueprint["render_plans"],
        "parents": [],
    }
    failures = []

    with patch.object(
        podcast_learning_video,
        "_article_plan_from_frozen_artifact",
        return_value=None,
    ):
        applied = podcast_learning_video.apply_article_display_page_translation_artifact(
            [cue],
            artifact,
            failure_items=failures,
        )

    assert applied is False
    assert failures == [
        {
            "subtitle_id": "S0199",
            "reason": "display_page_artifact_blueprint_mismatch",
        }
    ]
    assert ScreenSubtitleEditor._display_page_failure_items(
        failures,
        [],
        render_plans=artifact["render_plans"],
        fallback_reason="display_page_artifact_blueprint_mismatch",
    ) == failures


def test_parent_chinese_authority_binds_exact_id_text_and_word_span():
    records = [
        {
            "subtitle_id": "S0057",
            "english": "A fixed English parent.",
            "chinese": "一条固定中文。",
            "word_start": 120,
            "word_end": 123,
            "provenance": {
                "kind": "automatic",
                "producer": "fixed_id_allocation",
            },
        }
    ]
    authority = build_authoritative_parent_chinese_artifact(
        records,
        source_word_ledger_hash="ledger-hash",
        producer="fixed_id_allocation",
    )

    validated = validate_authoritative_parent_chinese_artifact(
        authority,
        expected_parents=records,
        expected_word_ledger_hash="ledger-hash",
    )
    record = parent_chinese_records_by_id(validated)["S0057"]

    assert record["source_hash"]
    assert record["chinese_hash"]
    assert record["record_hash"]


def test_parent_chinese_authority_rejects_tampered_chinese_and_identity():
    records = [
        {
            "subtitle_id": "S0057",
            "english": "A fixed English parent.",
            "chinese": "一条固定中文。",
            "word_start": 120,
            "word_end": 123,
        }
    ]
    authority = build_authoritative_parent_chinese_artifact(
        records,
        source_word_ledger_hash="ledger-hash",
        producer="fixed_id_allocation",
    )
    tampered = copy.deepcopy(authority)
    tampered["records"][0]["chinese"] = "被替换的旧译文。"

    try:
        validate_authoritative_parent_chinese_artifact(tampered)
        assert False, "tampered Chinese must invalidate the authority record"
    except AuthoritativeParentChineseError as exc:
        assert exc.code == "authoritative_parent_chinese_hash_mismatch"

    wrong_span = [{**records[0], "word_end": 124}]
    try:
        validate_authoritative_parent_chinese_artifact(
            authority,
            expected_parents=wrong_span,
        )
        assert False, "a different frozen word span must be rejected"
    except AuthoritativeParentChineseError as exc:
        assert exc.code == "authoritative_parent_chinese_projection_mismatch"


def test_display_page_parent_must_reference_the_same_chinese_record():
    records = [
        {
            "subtitle_id": "S0057",
            "english": "A fixed English parent.",
            "chinese": "一条固定中文。",
            "word_start": 120,
            "word_end": 123,
        }
    ]
    authority = build_authoritative_parent_chinese_artifact(
        records,
        source_word_ledger_hash="ledger-hash",
        producer="stable_display_page_translation",
    )
    record = parent_chinese_records_by_id(authority)["S0057"]
    display_artifact = {
        "status": "PASS",
        "parents": [
            {
                "parent_subtitle_id": "S0057",
                "parent_english_hash": record["english_hash"],
                "word_start": 120,
                "word_end": 123,
                "aggregate_chinese": "一条固定中文。",
                "pages": [],
            }
        ],
    }
    bound = bind_display_page_parent_records(
        display_artifact,
        {"S0057": record},
    )
    validate_display_page_parent_records(bound, {"S0057": record})

    stale = copy.deepcopy(bound)
    stale["parents"][0]["aggregate_chinese"] = "旧版分页中文。"
    try:
        validate_display_page_parent_records(stale, {"S0057": record})
        assert False, "stale display-page Chinese must not become authoritative"
    except AuthoritativeParentChineseError as exc:
        assert exc.code == "authoritative_parent_chinese_page_conflict"


def test_word_ledger_hash_has_one_cross_module_owner():
    ledger = [
        {
            "word_id": 0,
            "surface": "Most",
            "normalized": "most",
            "start_ms": 100,
            "end_ms": 300,
        },
        {
            "word_id": 1,
            "surface": "likely,",
            "normalized": "likely",
            "start_ms": 320,
            "end_ms": 620,
        },
    ]
    expected = canonical_word_ledger_hash(ledger)

    assert WORD_LEDGER_HASH_VERSION == "canonical-word-ledger-v1"
    assert ManualFinalSubtitleSession._semantic_word_ledger_hash(ledger) == expected
    assert ManualFinalSubtitleSession._formal_word_ledger_hash(ledger) == expected

    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor._active_word_entries = [
        {
            "surface": row["surface"],
            "token": row["normalized"],
            "start_time": row["start_ms"],
            "end_time": row["end_ms"],
        }
        for row in ledger
    ]
    assert editor._word_ledger_hash() == expected

    tampered = copy.deepcopy(ledger)
    tampered[1]["end_ms"] += 1
    assert canonical_word_ledger_hash(tampered) != expected


if __name__ == "__main__":
    test_s0078_reordered_chinese_is_bound_by_page_id()
    test_s0252_monotonic_translation_remains_page_aligned()
    test_page_translation_rejects_missing_duplicate_and_unknown_page_ids()
    test_chinese_token_split_keeps_frozen_plans_and_unaffected_parent_pages()
    test_page_translation_retry_contract_contains_only_failed_parent_pages()
    test_structural_page_response_forces_full_contract_retry()
    test_page_translation_cache_key_invalidates_semantic_page_contract_changes()
    test_page_contract_and_cache_identity_include_frozen_font_and_boundary_evidence()
    test_article_english_font_fallback_has_a_strict_50px_floor()
    test_screenshot_page_boundaries_consume_frozen_boundary_evidence()
    test_real_syntax_evidence_steers_results_from_without_injected_fixture_issue()
    test_medium_review_page_boundary_can_beat_static_font_reduction_on_quality()
    test_unsupported_tight_page_transition_loses_to_same_font_static_layout()
    test_complete_phrase_page_starts_remain_eligible_without_a_pause()
    test_atomic_of_and_dangling_coordinator_page_boundaries_are_hard()
    test_strong_pause_makes_clause_level_hard_page_boundary_reviewable()
    test_low_confidence_tight_transition_does_not_force_major_font_reduction()
    test_page_context_prefers_whole_attached_phrases_over_atomic_inner_cuts()
    test_structural_exception_can_use_actual_pixel_fit_above_sixteen_words()
    test_no_partition_failure_reports_deterministic_attempt_reasons()
    test_invalid_page_translation_cache_is_replaced_only_after_validation()
    test_page_translation_rejects_page_level_chinese_speed_overflow()
    test_page_level_continuation_fragment_is_review_not_blocker()
    test_renderer_uses_valid_page_mapping_without_proportional_fallback()
    test_renderer_fails_closed_when_paginated_page_mapping_is_missing()
    test_page_translation_updates_parent_chinese_without_srt_structure_drift()
    test_screen_editor_applies_mocked_page_response_after_final_timing_only()
    test_screen_editor_records_visual_overflow_against_the_frozen_subtitle_id()
    test_screen_editor_normalizes_page_errors_to_frozen_parent_ids()
    test_renderer_preflight_loads_manifest_page_artifact_and_rejects_missing_or_tampered()
    test_parse_srt_preserves_numeric_only_bilingual_line_order()
    test_attach_article_word_timing_restores_hash_bound_boundary_evidence()
    test_manual_draft_page_artifact_is_loaded_only_from_manifest_hash_binding()
    test_manual_draft_preflight_consumes_frozen_artifact_without_replanning()
    test_manual_draft_preflight_rejects_missing_or_tampered_artifact_before_ffmpeg()
    test_loaded_manual_draft_pages_match_persisted_identity_text_timing_and_font()
    test_stable_artifact_write_failure_is_not_reported_as_success()
    test_golden_page_translations_pass_existing_fixed_id_semantic_gate()
    test_frozen_artifact_mismatch_reports_the_exact_single_page_parent()
    test_parent_chinese_authority_binds_exact_id_text_and_word_span()
    test_parent_chinese_authority_rejects_tampered_chinese_and_identity()
    test_display_page_parent_must_reference_the_same_chinese_record()
    test_word_ledger_hash_has_one_cross_module_owner()
    print("stable page translation contract tests passed")
