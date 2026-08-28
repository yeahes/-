from app.core.subtitle_processor.user_facing_issue_text import (
    issue_code_label,
    issue_codes_text,
    user_facing_issue_reason,
)


def test_known_internal_issue_codes_have_clear_chinese_labels():
    assert issue_code_label("final_timeline_display_duration_invalid") == (
        "字幕显示时间无法安全延长"
    )
    assert issue_codes_text(
        ["subject_finite_verb_split", "cue_duration_below_page_minimum"]
    ) == "主语和谓语被切开、分页显示时间过短"


def test_english_internal_reason_uses_chinese_explanation_and_keeps_position():
    text = user_facing_issue_reason(
        "render_structural_overflow: hard_page_boundary at S0003.P02",
        code="display_page_blueprint_invalid",
    )

    assert text == "字幕无法按当前字号安全排版；需要调整分页。位置：S0003.P02"
    assert "render_structural_overflow" not in text
    assert "hard_page_boundary" not in text


def test_unknown_internal_code_does_not_leak_into_user_prompt():
    assert issue_code_label("future_internal_validation_code") == (
        "未分类的字幕检查问题"
    )
    assert user_facing_issue_reason(
        "future_internal_validation_code",
        code="future_internal_validation_code",
    ) == "发现一项未分类问题；请根据标记位置复核。"


def test_existing_chinese_explanation_is_preserved():
    assert user_facing_issue_reason(
        "英文边界需要人工复核：most | likely",
        code="english_boundary_audit",
    ) == "英文边界需要人工复核：most | likely"


if __name__ == "__main__":
    test_known_internal_issue_codes_have_clear_chinese_labels()
    test_english_internal_reason_uses_chinese_explanation_and_keeps_position()
    test_unknown_internal_code_does_not_leak_into_user_prompt()
    test_existing_chinese_explanation_is_preserved()
    print("user-facing issue text tests passed")
