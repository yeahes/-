"""Pure acceptance policy for fixed-ID Chinese allocation candidates.

The allocation orchestrator owns LLM calls, caching, retries, and ID-bound
writeback. This module owns only the deterministic decision of whether an
already validated candidate may replace the current allocation.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence


HIGH_CONFIDENCE_ALLOCATION_ISSUE_CODES = frozenset(
    {
        "adjacent_chinese_semantic_duplication",
        "cross_id_semantic_leakage",
        "group_allocation_information_omission",
        "entity_allocation_mismatch",
        "number_allocation_mismatch",
        "negation_allocation_mismatch",
        "unnatural_chinese_fragment",
        "translation_group_cardinality_mismatch",
    }
)


def compare_fixed_id_allocation_candidates(
    *,
    original_validation: Mapping[str, Any],
    candidate_validation: Mapping[str, Any],
    expected_subtitle_ids: Sequence[str],
    regression_reasons: Sequence[str],
    require_high_confidence_fix: bool = True,
) -> Dict[str, Any]:
    """Return the reproducible writeback decision for one fixed-ID candidate.

    Both validation payloads must describe the same frozen semantic group. The
    caller computes text-sensitive regression evidence before calling this
    function; keeping that dependency outside this module avoids coupling the
    policy to subtitle objects, cache state, or LLM infrastructure.
    """
    original_codes = set(original_validation.get("issue_codes") or [])
    candidate_codes = set(candidate_validation.get("issue_codes") or [])
    fixed_codes = sorted(
        (original_codes - candidate_codes) & HIGH_CONFIDENCE_ALLOCATION_ISSUE_CODES
    )
    new_codes = sorted(
        (candidate_codes - original_codes) & HIGH_CONFIDENCE_ALLOCATION_ISSUE_CODES
    )
    reasons = list(regression_reasons or [])
    if require_high_confidence_fix and not fixed_codes:
        reasons.insert(0, "no_high_confidence_issue_fixed")
    if new_codes:
        reasons.insert(
            1 if require_high_confidence_fix and not fixed_codes else 0,
            "new_high_confidence_issue",
        )

    original_issue_count = len(
        original_codes & HIGH_CONFIDENCE_ALLOCATION_ISSUE_CODES
    )
    candidate_issue_count = len(
        candidate_codes & HIGH_CONFIDENCE_ALLOCATION_ISSUE_CODES
    )
    if candidate_issue_count > original_issue_count:
        reasons.append("high_confidence_issue_count_regressed")

    accepted = not reasons
    return {
        "accepted": accepted,
        "decision": "accept_retry" if accepted else "keep_original",
        "fixed_issue_codes": fixed_codes,
        "new_issue_codes": new_codes,
        "original_issue_codes": sorted(original_codes),
        "retry_issue_codes": sorted(candidate_codes),
        "original_high_confidence_issue_count": original_issue_count,
        "retry_high_confidence_issue_count": candidate_issue_count,
        "expected_subtitle_ids": list(expected_subtitle_ids),
        "require_high_confidence_fix": require_high_confidence_fix,
        "reasons": reasons,
    }
