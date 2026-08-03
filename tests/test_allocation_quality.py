from app.core.subtitle_processor.allocation_quality import (
    compare_fixed_id_allocation_candidates,
)


def test_accepts_only_a_strict_high_confidence_improvement():
    result = compare_fixed_id_allocation_candidates(
        original_validation={"issue_codes": ["number_allocation_mismatch"]},
        candidate_validation={"issue_codes": []},
        expected_subtitle_ids=["S0001", "S0002"],
        regression_reasons=[],
    )

    assert result["accepted"]
    assert result["decision"] == "accept_retry"
    assert result["fixed_issue_codes"] == ["number_allocation_mismatch"]
    assert result["new_issue_codes"] == []


def test_rejects_a_candidate_that_introduces_a_high_confidence_issue():
    result = compare_fixed_id_allocation_candidates(
        original_validation={"issue_codes": []},
        candidate_validation={"issue_codes": ["entity_allocation_mismatch"]},
        expected_subtitle_ids=["S0001", "S0002"],
        regression_reasons=[],
    )

    assert not result["accepted"]
    assert result["decision"] == "keep_original"
    assert result["reasons"] == [
        "no_high_confidence_issue_fixed",
        "new_high_confidence_issue",
        "high_confidence_issue_count_regressed",
    ]


def test_selective_polish_can_keep_a_valid_non_regressive_candidate():
    result = compare_fixed_id_allocation_candidates(
        original_validation={"issue_codes": []},
        candidate_validation={"issue_codes": []},
        expected_subtitle_ids=["S0002", "S0001"],
        regression_reasons=[],
        require_high_confidence_fix=False,
    )

    assert result["accepted"]
    assert result["expected_subtitle_ids"] == ["S0002", "S0001"]


def test_regression_evidence_always_keeps_the_original_candidate():
    result = compare_fixed_id_allocation_candidates(
        original_validation={"issue_codes": ["number_allocation_mismatch"]},
        candidate_validation={"issue_codes": []},
        expected_subtitle_ids=["S0001"],
        regression_reasons=["adjacent_language_naturalness_regressed"],
    )

    assert not result["accepted"]
    assert result["reasons"] == ["adjacent_language_naturalness_regressed"]


if __name__ == "__main__":
    test_accepts_only_a_strict_high_confidence_improvement()
    test_rejects_a_candidate_that_introduces_a_high_confidence_issue()
    test_selective_polish_can_keep_a_valid_non_regressive_candidate()
    test_regression_evidence_always_keeps_the_original_candidate()
    print("allocation quality policy tests passed")
