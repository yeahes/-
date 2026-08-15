"""Chinese display text for internal subtitle validation codes.

Validation artifacts keep their stable English codes for machine contracts and
diagnostics.  UI callers use this module so those codes never become the only
explanation shown to the user.
"""

from __future__ import annotations

import re
from typing import Iterable


_POSITION_RE = re.compile(r"S\d{4}(?:\.P\d{2})?")
_INTERNAL_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9_]{3,}(?![A-Za-z0-9_])")
_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")


_ISSUE_LABELS = {
    "unknown": "未分类的字幕检查问题",
    "validation_error": "字幕检查未通过",
    "validation_item": "字幕检查项",
    "translation_structure_error": "中英文对应结构错误",
    "coverage_gap_unverified": "字幕覆盖空档待确认",
    "missing_translation": "缺少中文字幕",
    "overlong_english": "英文字幕超过长度上限",
    "structural_english_overflow": "完整英文长句无法安全切分",
    "invalid_timing": "字幕时间轴异常",
    "subtitle_duration_invalid": "字幕显示时间过短",
    "subtitle_duration_short_warning": "字幕显示时间偏短",
    "final_timeline_display_duration_invalid": "字幕显示时间无法安全延长",
    "reading_speed_error": "字幕阅读速度严重偏快",
    "reading_speed_warning": "字幕阅读速度偏快",
    "suspicious_cut": "英文切分可能不自然",
    "syntax_boundary_audit": "英文切分需要人工复核",
    "hard_english_boundary": "高置信英文切分错误",
    "translationese": "中文疑似翻译腔",
    "chinese_semantic_group_warning": "中文语义或表达需要复核",
    "duplicate_chinese": "相邻中文字幕可能重复",
    "asr_suspicious": "英文转录文本可疑",
    "discourse_marker_orphan": "英文口头连接词疑似孤立",
    "translation_id_missing": "缺少预期的中文字幕编号",
    "translation_id_duplicate": "中文字幕编号重复",
    "translation_id_unknown": "出现未知的中文字幕编号",
    "translation_group_cardinality_mismatch": "中文返回条数与英文字幕不一致",
    "final_translation_id_mismatch": "最终中英文字幕编号不一致",
    "allocation_quality_unresolved": "中文逐条对应仍需复核",
    "allocation_unresolved": "中文逐条对应仍需复核",
    "cross_id_semantic_leakage": "中文信息串到相邻字幕",
    "group_allocation_information_omission": "中文信息有遗漏",
    "entity_allocation_mismatch": "人名或术语对应错位",
    "number_allocation_mismatch": "数字信息对应错位",
    "negation_allocation_mismatch": "否定含义对应错位",
    "adjacent_chinese_semantic_duplication": "相邻中文字幕语义重复",
    "semantic_loss": "中文信息有遗漏",
    "entity_loss": "中文缺少人名或术语",
    "negation_loss": "中文缺少否定含义",
    "number_mismatch": "中英文数字不一致",
    "missing_predicate": "中文句子缺少谓语",
    "unnatural_chinese_fragment": "中文表达不完整或不自然",
    "final_cue_timeline_invalid": "最终字幕时间轴未通过检查",
    "final_timeline_invalid": "最终字幕时间轴未通过检查",
    "final_timeline_subtitle_id_invalid": "最终时间轴含无效字幕编号",
    "final_timeline_subtitle_id_duplicate": "最终时间轴含重复字幕编号",
    "final_timeline_subtitle_id_missing": "最终时间轴缺少字幕编号",
    "final_timeline_subtitle_id_unknown": "最终时间轴含未知字幕编号",
    "final_timeline_subtitle_order_mismatch": "最终字幕顺序不一致",
    "final_timeline_time_invalid": "最终字幕起止时间无效",
    "final_timeline_word_range_invalid": "字幕对应的词范围无效",
    "final_timeline_word_range_unknown": "字幕引用了不存在的词范围",
    "final_timeline_word_envelope_invalid": "字幕词时间范围无效",
    "final_timeline_word_envelope_mismatch": "字幕时间没有完整覆盖自己的语音",
    "final_timeline_word_time_invalid": "词级时间无效",
    "final_timeline_word_timing_density_invalid": "局部词级时间异常压缩",
    "final_timeline_word_id_set_mismatch": "最终词账本编号不完整",
    "final_timeline_word_overlap_unresolvable": "相邻词时间重叠且无法安全修复",
    "timeline_alignment_fallback": "词级时间使用了备用对齐结果",
    "display_page_unavailable": "当前字幕没有可用的实际分页",
    "display_page_review": "实际分页切点需要人工确认",
    "display_page_blueprint_invalid": "实际分页方案无法安全生成",
    "display_page_translation_invalid": "实际分页中文未通过检查",
    "display_page_translation_request_failed": "实际分页中文生成失败",
    "display_page_translation_retry_failed": "实际分页中文局部重试失败",
    "display_page_translation_retry_invalid": "实际分页中文重试后仍需人工复核",
    "display_page_artifact_blueprint_mismatch": "分页中文与当前分页方案不一致",
    "manual_page_translation_required": "实际分页中文尚未填写或确认",
    "manual_page_translation_invalid": "实际分页中文与分页结构不一致",
    "render_structural_overflow": "字幕无法按当前字号安全排版",
    "hard_page_boundary": "分页切点存在明确语法问题",
    "grammar_boundary_review": "分页切点需要检查语法完整性",
    "cue_duration_below_page_minimum": "分页显示时间过短",
    "compound_noun_split": "复合名词被切开",
    "modifier_head_split": "修饰语和中心词被切开",
    "object_attached_modifier_split": "宾语和后置修饰语被切开",
    "post_noun_participial_modifier_split": "名词和分词修饰语被切开",
    "relative_clause_subject_verb_split": "关系从句的主语和谓语被切开",
    "subject_finite_verb_split": "主语和谓语被切开",
    "subject_predicate_split": "主语和谓语部分被切开",
    "verb_complement_split": "动词和补语被切开",
    "verb_preposition_complement_split": "动词和介词补语被切开",
    "zero_relative_clause_split": "省略关系词的从句被切开",
    "dependency_phrase_entrance_split": "从句或依存短语入口被切开",
    "preposition_object_split": "介词和宾语被切开",
    "phrasal_verb_split": "短语动词被切开",
    "to_infinitive_split": "不定式结构被切开",
}


_ISSUE_EXPLANATIONS = {
    "subtitle_duration_invalid": "这条字幕显示时间太短；请试听并检查相邻字幕边界。",
    "final_timeline_display_duration_invalid": (
        "这条字幕太短，且相邻字幕之间没有足够空白可安全延长；"
        "请试听并调整边界。"
    ),
    "final_cue_timeline_invalid": (
        "最终字幕时间轴未通过检查；请试听标记字幕的首尾。"
    ),
    "final_timeline_invalid": "最终字幕时间轴未通过检查；请试听标记字幕的首尾。",
    "display_page_blueprint_invalid": "字幕无法按当前字号安全排版；需要调整分页。",
    "render_structural_overflow": "字幕无法按当前字号安全排版；需要调整分页。",
    "manual_page_translation_required": (
        "实际分页的中文尚未填写或确认；请补全后重新保存。"
    ),
    "manual_page_translation_invalid": (
        "实际分页的中文与分页结构不一致；请检查标记页面后重新保存。"
    ),
    "allocation_quality_unresolved": (
        "中文与固定英文字幕的逐条对应仍有疑点；请检查标记字幕。"
    ),
    "hard_english_boundary": (
        "英文切点存在明确语法问题；请在标记位置调整字幕边界。"
    ),
}


def issue_code_label(code: str) -> str:
    """Return a concise Chinese label without exposing an unknown code."""
    normalized = str(code or "").strip()
    return _ISSUE_LABELS.get(normalized, _ISSUE_LABELS["unknown"])


def issue_codes_text(codes: Iterable[str]) -> str:
    """Join unique issue labels for compact UI messages."""
    labels: list[str] = []
    for code in codes:
        label = issue_code_label(str(code or ""))
        if label not in labels:
            labels.append(label)
    return "、".join(labels)


def user_facing_issue_reason(
    reason: str,
    *,
    code: str = "",
    positions: Iterable[str] = (),
) -> str:
    """Convert artifact diagnostics into actionable Chinese UI text."""
    raw = str(reason or "").strip()
    normalized_code = str(code or "").strip()
    found_positions = list(
        dict.fromkeys(
            [
                *_POSITION_RE.findall(raw),
                *(
                    str(value)
                    for value in positions
                    if _POSITION_RE.fullmatch(str(value or ""))
                ),
            ]
        )
    )

    if _CHINESE_RE.search(raw):
        return _replace_known_internal_tokens(raw)

    explanation = _ISSUE_EXPLANATIONS.get(raw)
    if not explanation and raw in _ISSUE_LABELS:
        explanation = issue_code_label(raw) + "；请检查标记位置。"
    if not explanation:
        explanation = _ISSUE_EXPLANATIONS.get(normalized_code)
    if not explanation and raw in _ISSUE_EXPLANATIONS:
        explanation = _ISSUE_EXPLANATIONS[raw]
    if not explanation and normalized_code in _ISSUE_LABELS:
        explanation = issue_code_label(normalized_code) + "；请检查标记位置。"
    if not explanation:
        explanation = "发现一项未分类问题；请根据标记位置复核。"
    if found_positions:
        explanation = (
            explanation.rstrip("。") + "。位置：" + "、".join(found_positions)
        )
    return explanation


def _replace_known_internal_tokens(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return _ISSUE_LABELS.get(token, token)

    return _INTERNAL_TOKEN_RE.sub(replace, text)
