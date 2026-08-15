import tempfile

from app.core.subtitle_processor.translation_review_suggestions import (
    apply_translation_review_suggestion,
    currency_unit_review_suggestions,
    current_chinese_hash,
    generate_translation_review_suggestions,
    validate_translation_review_suggestions,
)


def test_translation_suggestion_requires_exact_source_and_preserves_facts():
    expected = {
        "S0001": {
            "english": "They do not spend 2026 dollars.",
            "chinese": "他们不会花费2026美元。",
        }
    }
    good = validate_translation_review_suggestions(
        {
            "suggestions": [
                {
                    "subtitle_id": "S0001",
                    "source_english": "They do not spend 2026 dollars.",
                    "current_chinese_hash": current_chinese_hash(
                        "他们不会花费2026美元。"
                    ),
                    "suggested_chinese": "他们不会在2026年花这笔钱。",
                }
            ]
        },
        expected,
        require_complete=True,
    )
    assert good["valid"] is False
    assert good["accepted_ids"] == []
    assert good["errors"] == [
        {"code": "suggestion_lost_currency_unit", "subtitle_id": "S0001"}
    ]

    bad = validate_translation_review_suggestions(
        {
            "suggestions": [
                {
                    "subtitle_id": "S0001",
                    "source_english": "They spend dollars.",
                    "current_chinese_hash": current_chinese_hash(
                        "他们不会花费2026美元。"
                    ),
                    "suggested_chinese": "他们花钱。",
                }
            ]
        },
        expected,
        require_complete=True,
    )
    assert bad["valid"] is False
    assert any(
        error["code"] == "suggestion_source_echo_mismatch"
        for error in bad["errors"]
    )


def test_translation_suggestion_rejects_stale_current_chinese():
    expected = {
        "S0001": {
            "english": "The plan is not practical.",
            "chinese": "这个方案并不现实。",
        }
    }
    checked = validate_translation_review_suggestions(
        {
            "suggestions": [
                {
                    "subtitle_id": "S0001",
                    "source_english": "The plan is not practical.",
                    "current_chinese_hash": current_chinese_hash(
                        "这个方案并不可行。"
                    ),
                    "suggested_chinese": "这个方案并不切实际。",
                }
            ]
        },
        expected,
    )

    assert checked["valid"] is False
    assert checked["suggestions"] == []
    assert checked["errors"] == [
        {"code": "suggestion_current_chinese_mismatch", "subtitle_id": "S0001"}
    ]

    try:
        apply_translation_review_suggestion(
            {"1": {"manual_cue_id": "S0001", "translated_subtitle": "这个方案并不现实。"}},
            {
                "subtitle_id": "S0001",
                "current_chinese_hash": current_chinese_hash("这个方案并不可行。"),
                "suggested_chinese": "这个方案并不切实际。",
            },
        )
    except ValueError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale suggestion must not overwrite the current Chinese")


def test_translation_suggestion_apply_is_id_bound_and_copy_on_write():
    rows = {
        "1": {
            "manual_cue_id": "S0001",
            "translated_subtitle": "旧译文",
        }
    }
    result = apply_translation_review_suggestion(
        rows,
        {
            "subtitle_id": "S0001",
            "current_chinese_hash": current_chinese_hash("旧译文"),
            "suggested_chinese": "新译文",
        },
    )
    assert rows["1"]["translated_subtitle"] == "旧译文"
    assert result["1"]["translated_subtitle"] == "新译文"
    assert result["1"]["translation_suggestion_applied"] is True


def test_translation_suggestion_targets_exact_display_page_id():
    rows = {
        "1": {
            "manual_cue_id": "S0001",
            "display_page_id": "S0001.P01",
            "translated_subtitle": "第一页",
        },
        "2": {
            "manual_cue_id": "S0001",
            "display_page_id": "S0001.P02",
            "translated_subtitle": "第二页",
        },
    }
    result = apply_translation_review_suggestion(
        rows,
        {
            "subtitle_id": "S0001.P02",
            "current_chinese_hash": current_chinese_hash("第二页"),
            "suggested_chinese": "第二页新译文",
        },
    )
    assert result["1"]["translated_subtitle"] == "第一页"
    assert result["2"]["translated_subtitle"] == "第二页新译文"


def test_parent_translation_suggestion_rejects_ambiguous_page_rows():
    rows = {
        "1": {"manual_cue_id": "S0001", "display_page_id": "S0001.P01"},
        "2": {"manual_cue_id": "S0001", "display_page_id": "S0001.P02"},
    }
    try:
        apply_translation_review_suggestion(
            rows,
            {"subtitle_id": "S0001", "suggested_chinese": "整条父字幕"},
        )
    except ValueError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("a parent suggestion must not mutate the first page")


def test_currency_review_requires_money_context_and_unique_complete_occurrence():
    article = {
        "numbers_and_dates": [
            {
                "canonical_name": "75 dollars per session",
                "canonical_in_article": True,
                "evidence": {"evidence_sentence": "The fee is 75 dollars per session."},
            }
        ]
    }
    suggestions = currency_unit_review_suggestions(
        {
            "S0001": {"english": "The fee is 75 dollars per session.", "chinese": "每次75元。"},
            "S0002": {"english": "There were 75 sessions last year.", "chinese": "去年有75元。"},
            "S0003": {"english": "The fee is 75 dollars per session.", "chinese": "每次75元人民币。"},
            "S0004": {"english": "The fee is 75 dollars per session and 75 clients came.", "chinese": "每次收费75元，共接待75名客户。"},
            "S0005": {"english": "They paid 75 clients last year.", "chinese": "去年向75元付款。"},
        },
        article,
    )
    assert [item["subtitle_id"] for item in suggestions] == ["S0001"]
    assert suggestions[0]["suggested_chinese"] == "每次75美元。"
    assert suggestions[0]["current_chinese_hash"] == current_chinese_hash("每次75元。")


def test_translation_suggestion_protects_exact_entity_and_term_targets():
    expected = {
        "S0001": {
            "english": "Dr. Howe says fudaoke needs follow-up care.",
            "chinese": "何医生说，复导课需要后续照护。",
            "protected_anchors": {
                "terms": [
                    {"source": "Dr. Howe", "target": "何医生"},
                    {"source": "fudaoke", "target": "复导课"},
                ]
            },
        }
    }
    checked = validate_translation_review_suggestions(
        {
            "suggestions": [
                {
                    "subtitle_id": "S0001",
                    "source_english": "Dr. Howe says fudaoke needs follow-up care.",
                    "source_anchor_echo": ["Dr. Howe", "fudaoke"],
                    "current_chinese_hash": current_chinese_hash(expected["S0001"]["chinese"]),
                    "suggested_chinese": "何医生说，需要后续照护。",
                }
            ]
        },
        expected,
    )
    assert checked["valid"] is False
    assert checked["errors"] == [
        {"code": "suggestion_lost_protected_anchor", "subtitle_id": "S0001"}
    ]


def test_review_generator_is_cached_and_isolates_completion_failure(tmp_path):
    expected = {
        "S0001": {"english": "This is not optional.", "chinese": "这不是可选项。"},
        "S0002": {"english": "It costs 75 dollars.", "chinese": "费用是75美元。"},
    }
    calls: list[tuple[str, ...]] = []

    def completion(request):
        assert set(request) == {"model", "prompt_version", "entries"}
        entry = request["entries"][0]
        calls.append(tuple(item["subtitle_id"] for item in request["entries"]))
        if entry["subtitle_id"] == "S0002":
            raise RuntimeError("temporary failure")
        return {
            "reviews": [
                {
                    "subtitle_id": entry["subtitle_id"],
                    "source_english": entry["source_english"],
                    "current_chinese_hash": entry["current_chinese_hash"],
                    "action": "suggest",
                    "suggested_chinese": "这绝非可有可无。",
                }
            ]
        }

    first = generate_translation_review_suggestions(
        expected,
        completion,
        groups=[["S0001"], ["S0002"]],
        cache_dir=tmp_path,
        model="offline-test",
    )
    assert first["accepted_ids"] == ["S0001"]
    assert first["group_errors"] == [
        {"code": "translation_review_completion_failed", "subtitle_ids": ["S0002"]}
    ]
    second = generate_translation_review_suggestions(
        expected,
        completion,
        groups=[["S0001"]],
        cache_dir=tmp_path,
        model="offline-test",
    )
    assert second["accepted_ids"] == ["S0001"]
    assert calls == [("S0001",), ("S0002",)]


def test_review_generator_rejects_cardinality_mismatch_without_other_group_loss():
    expected = {
        "S0001": {"english": "First sentence.", "chinese": "第一句。"},
        "S0002": {"english": "Second sentence.", "chinese": "第二句。"},
        "S0003": {"english": "Third sentence.", "chinese": "第三句。"},
    }

    def completion(request):
        entries = request["entries"]
        if len(entries) == 2:
            entry = entries[0]
            return {"reviews": [{
                "subtitle_id": entry["subtitle_id"],
                "source_english": entry["source_english"],
                "current_chinese_hash": entry["current_chinese_hash"],
                "action": "keep",
            }]}
        entry = entries[0]
        return {"reviews": [{
            "subtitle_id": entry["subtitle_id"],
            "source_english": entry["source_english"],
            "current_chinese_hash": entry["current_chinese_hash"],
            "action": "suggest",
            "suggested_chinese": "第三句已经润色。",
        }]}

    result = generate_translation_review_suggestions(
        expected,
        completion,
        groups=[["S0001", "S0002"], ["S0003"]],
    )
    assert result["accepted_ids"] == ["S0003"]
    assert result["group_errors"] == [
        {"code": "translation_review_cardinality_mismatch", "subtitle_ids": ["S0001", "S0002"]}
    ]


def test_review_generator_rejects_only_invalid_suggestion_inside_complete_group():
    expected = {
        "S0001": {"english": "First sentence.", "chinese": "第一句。"},
        "S0002": {"english": "Second sentence.", "chinese": "第二句。"},
    }

    def completion(request):
        first, second = request["entries"]
        return {"reviews": [
            {
                "subtitle_id": first["subtitle_id"],
                "source_english": first["source_english"],
                "current_chinese_hash": first["current_chinese_hash"],
                "action": "suggest",
                "suggested_chinese": "第一句已经润色。",
            },
            {
                "subtitle_id": second["subtitle_id"],
                "source_english": "Wrong source.",
                "current_chinese_hash": second["current_chinese_hash"],
                "action": "suggest",
                "suggested_chinese": "第二句已经润色。",
            },
        ]}

    result = generate_translation_review_suggestions(expected, completion)
    assert result["accepted_ids"] == ["S0001"]
    assert result["group_errors"] == []
    assert result["entry_errors"] == [
        {"code": "translation_review_entry_validation_failed", "subtitle_ids": ["S0002"]}
    ]


def test_review_generator_rejects_keep_row_with_stale_binding():
    expected = {
        "S0001": {"english": "Keep this sentence.", "chinese": "保留这句话。"},
    }

    def completion(request):
        entry = request["entries"][0]
        return {"reviews": [{
            "subtitle_id": entry["subtitle_id"],
            "source_english": entry["source_english"],
            "current_chinese_hash": current_chinese_hash("过期译文。"),
            "action": "keep",
        }]}

    result = generate_translation_review_suggestions(expected, completion)
    assert result["accepted_ids"] == []
    assert result["group_errors"] == []
    assert result["entry_errors"] == [
        {"code": "translation_review_response_binding_failed", "subtitle_ids": ["S0001"]}
    ]


if __name__ == "__main__":
    test_translation_suggestion_requires_exact_source_and_preserves_facts()
    test_translation_suggestion_rejects_stale_current_chinese()
    test_translation_suggestion_apply_is_id_bound_and_copy_on_write()
    test_translation_suggestion_targets_exact_display_page_id()
    test_parent_translation_suggestion_rejects_ambiguous_page_rows()
    test_currency_review_requires_money_context_and_unique_complete_occurrence()
    test_translation_suggestion_protects_exact_entity_and_term_targets()
    with tempfile.TemporaryDirectory() as directory:
        from pathlib import Path

        test_review_generator_is_cached_and_isolates_completion_failure(Path(directory))
    test_review_generator_rejects_cardinality_mismatch_without_other_group_loss()
    test_review_generator_rejects_only_invalid_suggestion_inside_complete_group()
    test_review_generator_rejects_keep_row_with_stale_binding()
    print("Translation review suggestion tests passed.")
