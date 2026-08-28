import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bk_asr.asr_data import ASRDataSeg
from app.core.entities import LLMServiceEnum
from app.core.llm_service_config import LLMRuntimeConfig
from app.core.subtitle_processor.translation_quality_audit import (
    audit_fixed_id_translation_quality,
    build_translation_audit_rows,
)
from app.thread.subtitle_thread import SubtitleThread


def _segment(subtitle_id: str, english: str, chinese: str) -> ASRDataSeg:
    segment = ASRDataSeg(english, 0, 3000, chinese)
    segment.subtitle_id = subtitle_id
    return segment


def test_model_audit_is_id_bound_and_filters_false_parent_length_warning():
    rows = build_translation_audit_rows(
        [
            _segment("S0001", "The legal friction emerges", "法律摩擦才真正显现"),
            _segment("S0002", "when companies reorganize.", "当企业重组运营时。"),
            _segment("S0003", "A long parent cue.", "这是一条很长的父级中文字幕"),
            _segment("S0004", "An overloaded page.", "这是一条实际分页负载过高的中文字幕"),
        ],
        {
            "parents": [
                {
                    "parent_subtitle_id": "S0003",
                    "pages": [
                        {
                            "display_page_id": "S0003.P01",
                            "english": "A long parent cue.",
                            "zh": "分页后正常。",
                            "start_ms": 0,
                            "end_ms": 3000,
                        }
                    ],
                },
                {
                    "parent_subtitle_id": "S0004",
                    "pages": [
                        {
                            "display_page_id": "S0004.P01",
                            "english": "An overloaded page.",
                            "zh": "这是一条实际分页负载过高而且需要人工压缩的中文字幕内容",
                            "start_ms": 0,
                            "end_ms": 2000,
                        }
                    ],
                },
            ]
        },
    )

    def completion(request):
        ids = list(request["target_ids"])
        issues = []
        if "S0001" in ids:
            issues.append(
                {
                    "subtitle_ids": ["S0001", "S0002"],
                    "code": "adjacent_coherence",
                    "reason": "中文跨条语序不自然。",
                    "confidence": "high",
                }
            )
        for subtitle_id in ("S0003", "S0004"):
            if subtitle_id in ids:
                issues.append(
                    {
                        "subtitle_ids": [subtitle_id],
                        "code": "chinese_too_long",
                        "reason": "中文字幕负载过高。",
                        "confidence": "high",
                    }
                )
        return {"audited_ids": ids, "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
        batch_size=2,
    )

    assert result["status"] == "PASS"
    assert result["audited_subtitle_count"] == 4
    assert result["unaudited_subtitle_ids"] == []
    assert {
        (tuple(item["subtitle_ids"]), item["code"])
        for item in result["items"]
    } == {
        (("S0001", "S0002"), "adjacent_coherence"),
        (("S0004",), "chinese_too_long"),
    }


def test_model_audit_fails_closed_when_batch_ids_are_incomplete():
    rows = build_translation_audit_rows(
        [
            _segment("S0001", "One.", "一。"),
            _segment("S0002", "Two.", "二。"),
        ],
        {},
    )

    result = audit_fixed_id_translation_quality(
        rows,
        lambda _request: {"audited_ids": ["S0001"], "issues": []},
        model="deepseek-v4-flash",
    )

    assert result["status"] == "PARTIAL"
    assert result["audited_subtitle_count"] == 0
    assert result["unaudited_subtitle_ids"] == ["S0001", "S0002"]
    assert result["batch_errors"][0]["code"] == (
        "translation_quality_audit_binding_failed"
    )


def test_model_audit_ignores_preference_about_valid_short_response():
    rows = build_translation_audit_rows(
        [_segment("S0001", "No.", "没有。")],
        {},
    )

    def completion(request):
        return {
            "audited_ids": list(request["target_ids"]),
            "issues": [
                {
                    "subtitle_ids": ["S0001"],
                    "code": "english_chinese_mismatch",
                    "reason": "建议改成不是。",
                    "confidence": "high",
                }
            ],
        }

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert result["status"] == "PASS"
    assert result["items"] == []


def test_model_audit_has_dedicated_adjacent_mapping_pass():
    rows = build_translation_audit_rows(
        [
            _segment("S0001", "It applies to the goods", "它适用于货物"),
            _segment("S0002", "but not the services.", "但服务则会"),
        ],
        {},
    )
    observed_focuses = []

    def completion(request):
        focus = request["audit_focus"]
        observed_focuses.append(focus)
        if focus == "finding_verification":
            return {
                "decisions": [
                    {
                        "candidate_id": item["candidate_id"],
                        "verdict": "keep",
                        "reason": "跨条中文确实停在未完成的助动词上。",
                    }
                    for item in request["candidate_issues"]
                ]
            }
        issues = []
        if focus == "continuity_mapping":
            issues.append(
                {
                    "subtitle_ids": ["S0001", "S0002"],
                    "code": "adjacent_coherence",
                    "reason": "后一句中文停在未完成的助动词上。",
                    "confidence": "high",
                }
            )
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert observed_focuses == [
        "accuracy_asr",
        "fluency_page_load",
        "continuity_mapping",
        "finding_verification",
    ]
    assert result["status"] == "PASS"
    assert [(item["subtitle_ids"], item["code"]) for item in result["items"]] == [
        (["S0001", "S0002"], "adjacent_coherence")
    ]


def test_semantic_issue_requires_grounded_quote_and_ignores_optional_marker():
    rows = build_translation_audit_rows(
        [_segment("S0001", "Exactly. The motor matters.", "电机很重要。")],
        {},
    )

    def completion(request):
        issues = []
        if request["audit_focus"] == "accuracy_asr":
            issues = [
                {
                    "subtitle_ids": ["S0001"],
                    "code": "semantic_loss",
                    "source_quote": "Exactly.",
                    "claimed_missing_chinese": "没错",
                    "reason": "Exactly 未翻译。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0001"],
                    "code": "semantic_loss",
                    "source_quote": "Exactly. The motor matters.",
                    "claimed_missing_chinese": "没错",
                    "reason": "Exactly 未翻译。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0001"],
                    "code": "semantic_loss",
                    "source_quote": "not in the source",
                    "claimed_missing_chinese": "伪造内容",
                    "reason": "伪造的证据片段。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0001"],
                    "code": "semantic_loss",
                    "source_quote": "The motor matters.",
                    "claimed_missing_chinese": "关键性",
                    "reason": "核心信息缺失。",
                    "confidence": "high",
                },
            ]
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert [(item["source_quote"], item["code"]) for item in result["items"]] == [
        ("The motor matters.", "semantic_loss")
    ]


def test_semantic_issue_ignores_okay_marker_inside_longer_grounded_quote():
    rows = build_translation_audit_rows(
        [_segment("S0001", "Right. Okay. What happens next?", "接下来会怎样？")],
        {},
    )

    def completion(request):
        issues = []
        if request["audit_focus"] == "accuracy_asr":
            issues = [
                {
                    "subtitle_ids": ["S0001"],
                    "code": "semantic_loss",
                    "source_quote": "Right. Okay. What happens next?",
                    "claimed_missing_chinese": "对，好的",
                    "reason": "Right. Okay. 未翻译。",
                    "confidence": "high",
                }
            ]
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert result["items"] == []


def test_semantic_loss_is_rejected_when_claimed_concept_exists_in_current_or_adjacent_chinese():
    rows = build_translation_audit_rows(
        [
            _segment("S0001", "And trying to grow cacao", "在中国西南种植可可"),
            _segment("S0002", "in southwest China is difficult.", "很困难。"),
            _segment("S0003", "It lacks a behavioral hook.", "这不足以支撑。"),
        ],
        {},
    )

    def completion(request):
        issues = []
        if request["audit_focus"] == "accuracy_asr":
            issues = [
                {
                    "subtitle_ids": ["S0001"],
                    "code": "semantic_loss",
                    "source_quote": "grow cacao",
                    "claimed_missing_chinese": "可可",
                    "reason": "中文遗漏了可可。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0002"],
                    "code": "semantic_loss",
                    "source_quote": "southwest China",
                    "claimed_missing_chinese": "中国西南",
                    "reason": "中文遗漏了地点。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0003"],
                    "code": "semantic_loss",
                    "source_quote": "behavioral hook",
                    "claimed_missing_chinese": "行为钩子",
                    "reason": "中文遗漏了关键概念。",
                    "confidence": "high",
                },
            ]
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert [(item["subtitle_ids"], item["source_quote"]) for item in result["items"]] == [
        (["S0003"], "behavioral hook")
    ]


def test_candidate_verification_rejects_ellipsis_noise_and_keeps_real_error():
    rows = build_translation_audit_rows(
        [
            _segment("S0001", "By imposing tariffs,", "通过加征关税，"),
            _segment("S0002", "the administration changed the system.", "改变了这一体系。"),
            _segment("S0003", "This is legal fraud.", "这是合法避税。"),
        ],
        {},
    )

    def completion(request):
        if request["audit_focus"] == "finding_verification":
            assert [item["candidate_id"] for item in request["candidate_issues"]] == [
                "C0001",
            ]
            assert [item["code"] for item in request["candidate_issues"]] == [
                "translationese"
            ]
            return {
                "decisions": [
                    {
                        "candidate_id": "C0001",
                        "verdict": "reject",
                        "reason": "相邻条已形成完整承接，中文可省略主语。",
                    },
                ]
            }
        issues = []
        if request["audit_focus"] == "accuracy_asr":
            issues = [
                {
                    "subtitle_ids": ["S0002"],
                    "code": "translationese",
                    "source_quote": "",
                    "reason": "中文省略主语，表达略显生硬。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0003"],
                    "code": "meaning_error",
                    "source_quote": "legal fraud",
                    "reason": "fraud 被误译成避税。",
                    "confidence": "high",
                },
            ]
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert [(item["subtitle_ids"], item["code"]) for item in result["items"]] == [
        (["S0003"], "meaning_error")
    ]
    assert result["verification_errors"] == []


def test_number_audit_rejects_equivalent_scale_and_ungrounded_currency_claims():
    rows = build_translation_audit_rows(
        [
            _segment(
                "S0001",
                "Sales reached 160 million yuan.",
                "销售额达到1.6亿元人民币。",
            ),
            _segment(
                "S0002",
                "It went from zero to nearly 24 million",
                "从零做到近2400万",
            ),
            _segment(
                "S0003",
                "Sales reached 160 million yuan.",
                "销售额达到1.6亿美元。",
            ),
            _segment(
                "S0004",
                "You cannot remove the safeguard.",
                "你可以移除保障措施。",
            ),
        ],
        {},
    )

    def completion(request):
        issues = []
        if request["audit_focus"] == "accuracy_asr":
            issues = [
                {
                    "subtitle_ids": ["S0001"],
                    "code": "number_or_negation_error",
                    "source_quote": "160 million yuan",
                    "reason": "数值错误，应为1.6亿元。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0002"],
                    "code": "number_or_negation_error",
                    "source_quote": "nearly 24 million",
                    "reason": "缺少货币单位美元。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0003"],
                    "code": "number_or_negation_error",
                    "source_quote": "160 million yuan",
                    "reason": "人民币被误译为美元。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0004"],
                    "code": "number_or_negation_error",
                    "source_quote": "cannot",
                    "reason": "否定含义丢失，语义相反。",
                    "confidence": "high",
                },
            ]
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert [(item["subtitle_ids"], item["source_quote"]) for item in result["items"]] == [
        (["S0003"], "160 million yuan"),
        (["S0004"], "cannot"),
    ]


def test_adjacent_issue_requires_two_ids_and_can_use_context_neighbor():
    rows = build_translation_audit_rows(
        [
            _segment("S0001", "The friction emerges", "摩擦开始显现"),
            _segment("S0002", "when the rule applies.", "当规则生效时。"),
        ],
        {},
    )

    def completion(request):
        issues = []
        if (
            request["audit_focus"] == "continuity_mapping"
            and request["target_ids"] == ["S0001"]
        ):
            issues = [
                {
                    "subtitle_ids": ["S0001"],
                    "code": "adjacent_coherence",
                    "source_quote": "",
                    "reason": "单 ID 跨条证据无效。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0001", "S0002"],
                    "code": "adjacent_coherence",
                    "source_quote": "",
                    "reason": "两条中文需要连读复核。",
                    "confidence": "high",
                },
            ]
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
        batch_size=1,
    )

    assert [(item["subtitle_ids"], item["code"]) for item in result["items"]] == [
        (["S0001", "S0002"], "adjacent_coherence")
    ]


def test_model_audit_deduplicates_same_owned_problem_and_filters_marker_phrase():
    rows = build_translation_audit_rows(
        [_segment("S0001", "Yes, exactly.", "对。")],
        {},
    )

    def completion(request):
        issues = []
        if request["audit_focus"] in {"accuracy_asr", "continuity_mapping"}:
            issues.extend(
                [
                    {
                        "subtitle_ids": ["S0001"],
                        "code": "semantic_loss",
                        "source_quote": "Yes, exactly.",
                        "reason": "回应语未逐字翻译。",
                        "confidence": "high",
                    },
                    {
                        "subtitle_ids": ["S0001"],
                        "code": "meaning_error",
                        "source_quote": "Yes, exactly.",
                        "reason": "同一问题的不同措辞。",
                        "confidence": "high",
                    },
                ]
            )
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert result["items"] == []


def test_model_audit_filters_ordinary_cross_row_continuation_but_keeps_dangling_chinese():
    rows = build_translation_audit_rows(
        [
            _segment("S0001", "The market grew", "市场持续增长"),
            _segment("S0002", "as demand recovered.", "需求也逐步恢复。"),
            _segment("S0003", "It is less about price", "重点不在价格"),
            _segment("S0004", "and more about the fact that", "而在于，终于，"),
        ],
        {},
    )

    def completion(request):
        issues = []
        if request["audit_focus"] == "continuity_mapping":
            issues = [
                {
                    "subtitle_ids": ["S0001", "S0002"],
                    "code": "adjacent_coherence",
                    "reason": "两条中文需要连读。",
                    "confidence": "high",
                },
                {
                    "subtitle_ids": ["S0003", "S0004"],
                    "code": "adjacent_coherence",
                    "reason": "后半句中文明显悬空。",
                    "confidence": "high",
                },
            ]
        return {"audited_ids": list(request["target_ids"]), "issues": issues}

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model="deepseek-v4-flash",
    )

    assert [(item["subtitle_ids"], item["code"]) for item in result["items"]] == [
        (["S0003", "S0004"], "adjacent_coherence")
    ]


def test_subtitle_thread_audit_uses_selected_deepseek_runtime_and_cache_namespace():
    segment = _segment("S0001", "A fixed English cue.", "固定中文。")
    editor = SimpleNamespace(
        _display_page_translation_artifact={
            "status": "PASS",
            "parents": [
                {
                    "parent_subtitle_id": "S0001",
                    "pages": [
                        {
                            "display_page_id": "S0001.P01",
                            "english": "A fixed English cue.",
                            "zh": "固定中文。",
                            "start_ms": 0,
                            "end_ms": 3000,
                        }
                    ],
                }
            ],
        }
    )
    runtime = LLMRuntimeConfig(
        service=LLMServiceEnum.DEEPSEEK,
        base_url="https://api.deepseek.com/v1",
        api_key="deepseek-key",
        model="deepseek-chat",
        full_translation_model="deepseek-v4-pro",
    )
    audit_payload = {
        "status": "PASS",
        "source_subtitle_count": 1,
        "audited_subtitle_count": 1,
        "items": [],
        "batch_errors": [],
    }

    with tempfile.TemporaryDirectory() as temp_dir, patch(
        "app.thread.subtitle_thread.resolve_llm_service_config",
        return_value=runtime,
    ), patch("app.thread.subtitle_thread.OpenAI") as openai_factory, patch(
        "app.thread.subtitle_thread.audit_fixed_id_translation_quality",
        return_value=audit_payload,
    ) as audit, patch("app.thread.subtitle_thread.write_subtitle_review_ledger"):
        payload = SubtitleThread._run_translation_quality_audit(
            editor,
            SimpleNamespace(segments=[segment]),
            str(Path(temp_dir) / "coverage-report.txt"),
        )

    openai_factory.assert_called_once_with(
        base_url="https://api.deepseek.com/v1",
        api_key="deepseek-key",
        max_retries=0,
        timeout=90,
    )
    assert audit.call_args.kwargs["model"] == "deepseek-chat"
    assert Path(audit.call_args.kwargs["cache_dir"]).name == "deepseek"
    assert payload["service"] == "DeepSeek"
    assert payload["cache_namespace"] == "deepseek"


def test_subtitle_thread_audit_can_run_after_page_projection_failure_when_opted_in():
    segment = _segment("S0001", "A fixed English cue.", "固定中文。")
    editor = SimpleNamespace(
        _display_page_translation_artifact={
            "status": "ERROR",
            "errors": [{"code": "display_page_translation_request_failed"}],
        }
    )
    runtime = LLMRuntimeConfig(
        service=LLMServiceEnum.DEEPSEEK,
        base_url="https://api.deepseek.com/v1",
        api_key="deepseek-key",
        model="deepseek-chat",
        full_translation_model="deepseek-chat",
    )
    audit_payload = {
        "status": "PASS",
        "source_subtitle_count": 1,
        "audited_subtitle_count": 1,
        "items": [],
        "batch_errors": [],
    }

    with tempfile.TemporaryDirectory() as temp_dir, patch(
        "app.thread.subtitle_thread.resolve_llm_service_config",
        return_value=runtime,
    ), patch("app.thread.subtitle_thread.OpenAI") as openai_factory, patch(
        "app.thread.subtitle_thread.audit_fixed_id_translation_quality",
        return_value=audit_payload,
    ) as audit, patch("app.thread.subtitle_thread.write_json_artifact"), patch(
        "app.thread.subtitle_thread.write_subtitle_review_ledger"
    ):
        payload = SubtitleThread._run_translation_quality_audit(
            editor,
            SimpleNamespace(segments=[segment]),
            str(Path(temp_dir) / "coverage-report.txt"),
            allow_page_projection_failure=True,
        )

    openai_factory.assert_called_once()
    audit.assert_called_once()
    assert payload["status"] == "PASS"
    assert payload["audited_subtitle_count"] == 1


if __name__ == "__main__":
    test_model_audit_is_id_bound_and_filters_false_parent_length_warning()
    test_model_audit_fails_closed_when_batch_ids_are_incomplete()
    test_model_audit_ignores_preference_about_valid_short_response()
    test_model_audit_has_dedicated_adjacent_mapping_pass()
    test_semantic_issue_requires_grounded_quote_and_ignores_optional_marker()
    test_semantic_loss_is_rejected_when_claimed_concept_exists_in_current_or_adjacent_chinese()
    test_candidate_verification_rejects_ellipsis_noise_and_keeps_real_error()
    test_number_audit_rejects_equivalent_scale_and_ungrounded_currency_claims()
    test_adjacent_issue_requires_two_ids_and_can_use_context_neighbor()
    test_model_audit_deduplicates_same_owned_problem_and_filters_marker_phrase()
    test_model_audit_filters_ordinary_cross_row_continuation_but_keeps_dangling_chinese()
    test_subtitle_thread_audit_uses_selected_deepseek_runtime_and_cache_namespace()
    print("translation quality audit tests passed")
