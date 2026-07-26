from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from app.core.subtitle_processor.text_metrics import (
    HARD_ENGLISH_WORD_LIMIT,
    word_count as shared_word_count,
)

SUBTITLE_DURATION_INVALID_MS = 150
SUBTITLE_DURATION_ERROR_MS = 250
SUBTITLE_DURATION_WARNING_MS = 500


TIME_RE = re.compile(
    r"(?P<sh>\d{2}):(?P<sm>\d{2}):(?P<ss>\d{2}),(?P<sms>\d{3})\s+-->\s+"
    r"(?P<eh>\d{2}):(?P<em>\d{2}):(?P<es>\d{2}),(?P<ems>\d{3})"
)


@dataclass(frozen=True)
class CaptionCue:
    index: int
    start_ms: int
    end_ms: int
    english: str
    chinese: str
    raw_lines: tuple[str, ...]

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def pick_bilingual_original_top_srt(subtitle_dir: Path) -> Path | None:
    manifest = subtitle_dir / "stable-final-manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            path = Path(data.get("paths", {}).get("original_top_srt", ""))
            if path.exists() and path.stat().st_size > 0:
                return path
        except Exception:
            pass

    candidates: list[Path] = []
    for path in subtitle_dir.glob("*.srt"):
        if path.name.startswith("stable-final") or path.name.endswith(
            ".bak-before-display-fix"
        ):
            continue
        text = path.read_text(encoding="utf-8-sig", errors="ignore")[:900]
        first_block = text.split("\n\n", 1)[0]
        lines = [line.strip() for line in first_block.splitlines() if line.strip()]
        if len(lines) >= 4 and has_english(lines[2]) and has_chinese(lines[3]):
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_srt(path: Path) -> list[CaptionCue]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: list[CaptionCue] = []
    for fallback_index, block in enumerate(blocks, 1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        time_line_index = next(
            (i for i, line in enumerate(lines) if "-->" in line),
            None,
        )
        if time_line_index is None:
            continue
        match = TIME_RE.search(lines[time_line_index])
        if not match:
            continue
        try:
            index = int(lines[0]) if time_line_index > 0 else fallback_index
        except ValueError:
            index = fallback_index
        body = tuple(lines[time_line_index + 1 :])
        english, chinese = split_bilingual_body(body)
        cues.append(
            CaptionCue(
                index=index,
                start_ms=_time_to_ms(match, "s"),
                end_ms=_time_to_ms(match, "e"),
                english=english,
                chinese=chinese,
                raw_lines=body,
            )
        )
    return cues


def audit_srt(
    path: Path,
    max_words: int = HARD_ENGLISH_WORD_LIMIT,
    gap_warning_ms: int = 1200,
    gap_error_ms: int = 1500,
    min_duration_ms: int = 900,
    english_wps_warning: float = 5.0,
    chinese_cps_warning: float = 9.0,
    chinese_cps_error: float = 11.0,
) -> dict:
    cues = parse_srt(path)
    issues = {
        "errors": [],
        "warnings": [],
        "info": [],
    }
    previous: CaptionCue | None = None
    for cue in cues:
        if cue.end_ms <= cue.start_ms:
            issues["errors"].append(
                _issue("invalid_timing", cue, "字幕结束时间不大于开始时间")
            )
        if previous is not None:
            gap_ms = cue.start_ms - previous.end_ms
            if gap_ms > gap_error_ms:
                issues["warnings"].append(
                    {
                        "code": "coverage_gap_unverified",
                        "index": cue.index,
                        "from_index": previous.index,
                        "gap_ms": gap_ms,
                        "from_ms": previous.end_ms,
                        "to_ms": cue.start_ms,
                        "message": f"相邻字幕间隔 {gap_ms}ms；未接入 VAD 证据，仅作为 WARNING",
                    }
                )
            elif gap_ms > gap_warning_ms:
                issues["warnings"].append(
                    {
                        "code": "coverage_gap_warning",
                        "index": cue.index,
                        "from_index": previous.index,
                        "gap_ms": gap_ms,
                        "from_ms": previous.end_ms,
                        "to_ms": cue.start_ms,
                        "message": f"相邻字幕间隔 {gap_ms}ms，建议检查",
                    }
                )
        simple_response = _is_simple_short_response(cue.english, cue.chinese)
        text_load = count_words(cue.english) + len(re.findall(r"[\u4e00-\u9fff]", cue.chinese))
        duration_invalid = 0 < cue.duration_ms < SUBTITLE_DURATION_INVALID_MS
        too_short_for_load = (
            0 < cue.duration_ms < SUBTITLE_DURATION_ERROR_MS
            and not simple_response
            and text_load > 4
        )
        if duration_invalid or too_short_for_load:
            issues["errors"].append(
                _issue(
                    "subtitle_duration_invalid",
                    cue,
                    f"字幕显示时长 {cue.duration_ms}ms，严重偏短",
                    threshold_ms=SUBTITLE_DURATION_INVALID_MS if duration_invalid else SUBTITLE_DURATION_ERROR_MS,
                    simple_response=simple_response,
                    text_load=text_load,
                )
            )
        elif 0 < cue.duration_ms < SUBTITLE_DURATION_WARNING_MS:
            issues["warnings"].append(
                _issue(
                    "subtitle_duration_too_short",
                    cue,
                    f"字幕显示时长 {cue.duration_ms}ms，低于 {SUBTITLE_DURATION_WARNING_MS}ms",
                    threshold_ms=SUBTITLE_DURATION_WARNING_MS,
                    simple_response=simple_response,
                    text_load=text_load,
                )
            )
        if 0 < cue.duration_ms < min_duration_ms:
            issues["warnings"].append(
                _issue(
                    "short_duration",
                    cue,
                    f"字幕显示时长 {cue.duration_ms}ms，低于 {min_duration_ms}ms",
                )
            )
        word_count = count_words(cue.english)
        if word_count > max_words:
            issues["errors"].append(
                _issue(
                    "overlong_english",
                    cue,
                    f"英文 {word_count} 词，超过 {max_words} 词硬上限",
                    word_count=word_count,
                    hard_limit=max_words,
                )
            )
        if cue.english and not cue.chinese:
            issues["errors"].append(_issue("missing_chinese", cue, "有英文但无中文"))
        _add_reading_speed_issues(
            cue,
            issues,
            english_wps_warning,
            chinese_cps_warning,
            chinese_cps_error,
        )
        previous = cue

    issues["warnings"].extend(_duplicate_chinese_issues(cues))
    asr_issues, invalid_asr_issues = _asr_suspicious_issues(cues)
    issues["warnings"].extend(asr_issues)
    issues["info"].extend(invalid_asr_issues)
    issues["warnings"].extend(_syntax_boundary_issues(cues))
    issues["warnings"].extend(_chinese_semantic_group_issues(cues, "WARNING"))
    issues["info"].extend(_chinese_semantic_group_issues(cues, "INFO"))
    word_counts = [count_words(cue.english) for cue in cues if cue.english]
    durations = [max(0, cue.duration_ms) for cue in cues]
    status = "ERROR" if issues["errors"] else ("WARNING" if issues["warnings"] else "PASS")
    return {
        "path": str(path),
        "status": status,
        "count": len(cues),
        "metrics": {
            "max_words": max(word_counts) if word_counts else 0,
            "avg_words": round(sum(word_counts) / len(word_counts), 2)
            if word_counts
            else 0,
            "avg_duration_ms": round(sum(durations) / len(durations), 2)
            if durations
            else 0,
        },
        **issues,
    }


def has_english(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def has_chinese_punctuation(text: str) -> bool:
    return bool(re.search(r"[\u3000-\u303f\uff00-\uffef]", text or ""))


def count_words(text: str) -> int:
    return shared_word_count(text)


def split_bilingual_body(body: Iterable[str]) -> tuple[str, str]:
    lines = [line.strip() for line in body if line.strip()]
    if not lines:
        return "", ""
    if len(lines) == 1:
        return (lines[0], "") if has_english(lines[0]) else ("", lines[0])

    first_chinese_index = next(
        (
            index
            for index, line in enumerate(lines)
            if has_chinese(line) or (has_chinese_punctuation(line) and not has_english(line))
        ),
        None,
    )
    if first_chinese_index is not None:
        english = " ".join(lines[:first_chinese_index]).strip()
        chinese = "".join(lines[first_chinese_index:]).strip()
        return english, chinese

    return " ".join(lines).strip(), ""


def normalize_zh(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "").strip()


def _is_simple_short_response(english: str, chinese: str = "") -> bool:
    english_norm = re.sub(r"[^a-z'\s]", " ", (english or "").lower()).strip()
    english_norm = re.sub(r"\s+", " ", english_norm)
    chinese_norm = normalize_zh(chinese)
    short_en = {
        "right",
        "yeah",
        "yes",
        "no",
        "okay",
        "ok",
        "really",
        "exactly",
        "sure",
        "why",
        "where",
        "how",
        "what",
    }
    short_zh = {
        "没错",
        "对",
        "是的",
        "真的吗",
        "真的",
        "好的",
        "为什么",
        "在哪里",
        "什么",
    }
    if english_norm in short_en:
        return True
    return bool(chinese_norm and chinese_norm in short_zh)


def _time_to_ms(match: re.Match[str], prefix: str) -> int:
    return (
        int(match.group(f"{prefix}h")) * 3_600_000
        + int(match.group(f"{prefix}m")) * 60_000
        + int(match.group(f"{prefix}s")) * 1000
        + int(match.group(f"{prefix}ms"))
    )


def _issue(code: str, cue: CaptionCue, message: str, **extra: object) -> dict:
    return {
        "code": code,
        "index": cue.index,
        "start_ms": cue.start_ms,
        "end_ms": cue.end_ms,
        "duration_ms": cue.duration_ms,
        "english": cue.english,
        "chinese": cue.chinese,
        "message": message,
        **extra,
    }


def _add_reading_speed_issues(
    cue: CaptionCue,
    issues: dict,
    english_wps_warning: float,
    chinese_cps_warning: float,
    chinese_cps_error: float,
) -> None:
    if cue.duration_ms <= 0:
        return
    duration_sec = cue.duration_ms / 1000.0
    words = count_words(cue.english)
    if words:
        wps = words / duration_sec
        if wps > english_wps_warning:
            issues["warnings"].append(
                _issue(
                    "english_speed_warning",
                    cue,
                    f"英文阅读速度 {wps:.2f} 词/秒，可能偏快",
                    wps=round(wps, 2),
                    word_count=words,
                )
            )
    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", cue.chinese))
    if zh_chars:
        cps = zh_chars / duration_sec
        severe_zh_speed = (
            cps > chinese_cps_error
            and cue.duration_ms >= 1200
            and zh_chars >= 12
        )
        if severe_zh_speed:
            issues["errors"].append(
                _issue(
                    "chinese_speed_error",
                    cue,
                    f"中文阅读速度 {cps:.2f} 字/秒，超过硬上限",
                    cps=round(cps, 2),
                    zh_chars=zh_chars,
                )
            )
        elif cps > chinese_cps_warning:
            issues["warnings"].append(
                _issue(
                    "chinese_speed_warning",
                    cue,
                    f"中文阅读速度 {cps:.2f} 字/秒，建议压缩",
                    cps=round(cps, 2),
                    zh_chars=zh_chars,
                )
            )


def _duplicate_chinese_issues(cues: Iterable[CaptionCue]) -> list[dict]:
    issues: list[dict] = []
    previous_text = ""
    previous_index = 0
    for cue in cues:
        current = normalize_zh(cue.chinese)
        if current and previous_text:
            similarity = SequenceMatcher(None, previous_text, current).ratio()
            if current == previous_text or (
                min(len(current), len(previous_text)) >= 6 and similarity >= 0.88
            ):
                issues.append(
                    {
                        "code": "duplicate_chinese",
                        "previous_index": previous_index,
                        "index": cue.index,
                        "similarity": round(similarity, 3),
                        "previous": previous_text,
                        "current": current,
                        "message": "相邻中文字幕疑似重复",
                    }
                )
        if current:
            previous_text = current
            previous_index = cue.index
    return issues


def _asr_suspicious_issues(cues: Iterable[CaptionCue]) -> tuple[list[dict], list[dict]]:
    cue_list = list(cues)
    issues: list[dict] = []
    invalid: list[dict] = []
    capitalized: dict[str, dict[str, list[int]]] = {}
    cue_by_index = {cue.index: cue for cue in cue_list}
    for cue in cue_list:
        text = cue.english
        lower = text.lower()
        if re.search(r"\b([A-Za-z]+)\s+\1\b", text, re.IGNORECASE):
            issues.append(
                _asr_issue(
                    "asr_repeated_word",
                    cue,
                    "??????????",
                    text,
                    "high",
                    "adjacent repeated English token",
                )
            )
        for pattern, rule_code, message, confidence in (
            (
                r"\btotal off guard\b",
                "asr_ungrammatical_collocation",
                "???????????caught me totally off guard",
                "high",
            ),
            (
                r"\bseeds?\s+away\s+the\s+mirror\b",
                "asr_semantic_nonsense",
                "???????????????????",
                "high",
            ),
            (
                r"\bpollution control trigger\b",
                "asr_subject_verb_agreement",
                "?????????????control trigger",
                "medium",
            ),
            (
                r"\bgeographing\s+arbitrage\b",
                "asr_semantic_nonsense",
                "疑似ASR把 geographic arbitrage 识别成不成立的表达",
                "high",
            ),
            (
                r"\bsafety\s+nuts\b",
                "asr_semantic_nonsense",
                "疑似ASR把 safety nets 识别成不成立的表达",
                "high",
            ),
            (
                r"\bstate-of\s+the-art\b|\bstate\s+of-the-art\b",
                "asr_hyphenation_suspicious",
                "疑似ASR或切分破坏了固定形容词 state-of-the-art",
                "medium",
            ),
            (
                r"\b(in|by)\s+20\d{2},\s+[^.?!]{0,80}\bban\b",
                "asr_tense_or_inflection_suspicious",
                "?????????????????????",
                "medium",
            ),
        ):
            if not re.search(pattern, lower):
                continue
            issues.append(
                _asr_issue(
                    rule_code,
                    cue,
                    message,
                    text,
                    confidence,
                    pattern,
                    recommended_review_window={
                        "start_ms": max(0, cue.start_ms - 1500),
                        "end_ms": cue.end_ms + 1500,
                    },
                )
            )
        tokens = re.findall(r"\b[A-Z][A-Za-z]{4,}\b", text)
        for token in tokens:
            capitalized.setdefault(token[:4].lower(), {}).setdefault(token, []).append(cue.index)
    for variants in capitalized.values():
        if len(variants) < 2:
            continue
        names = sorted(variants)
        pairs = []
        for i, left in enumerate(names):
            for right in names[i + 1 :]:
                ratio = SequenceMatcher(None, left.lower(), right.lower()).ratio()
                if 0.62 <= ratio < 1.0:
                    pairs.append((left, right, round(ratio, 3)))
        if pairs:
            indices = sorted({idx for name in names for idx in variants[name]})
            first_cue = cue_by_index.get(indices[0]) if indices else None
            issues.append(
                {
                    "code": "asr_capitalized_variant",
                    "index": indices[0] if indices else None,
                    "subtitle_id": f"S{indices[0]:04d}" if indices else "",
                    "time_range": f"{first_cue.start_ms} --> {first_cue.end_ms}" if first_cue else "",
                    "suspicious_text": first_cue.english if first_cue else "",
                    "rule_code": "asr_capitalized_variant",
                    "confidence": "medium",
                    "evidence": "similar capitalized variants in nearby subtitles",
                    "indices": indices,
                    "variants": [{"text": name, "indices": variants[name]} for name in names],
                    "pairs": pairs,
                    "message": "?????????????????????? ASR ??",
                }
            )

    valid: list[dict] = []
    for issue in issues:
        if _is_valid_asr_issue(issue):
            valid.append(issue)
        else:
            invalid.append(
                {
                    "code": "audit_issue_invalid",
                    "source_code": issue.get("code"),
                    "message": "ASR warning missing required structured fields and was not counted",
                    "issue": issue,
                }
            )
    return valid, invalid


def _asr_issue(
    code: str,
    cue: CaptionCue,
    message: str,
    suspicious_text: str,
    confidence: str,
    evidence: str,
    **extra: object,
) -> dict:
    return _issue(
        code,
        cue,
        message,
        subtitle_id=f"S{cue.index:04d}",
        time_range=f"{cue.start_ms} --> {cue.end_ms}",
        suspicious_text=suspicious_text,
        rule_code=code,
        confidence=confidence,
        evidence=evidence,
        **extra,
    )


def _is_valid_asr_issue(issue: dict) -> bool:
    required = ("subtitle_id", "time_range", "suspicious_text", "rule_code", "confidence", "evidence")
    return all(str(issue.get(key) or "").strip() for key in required)


def _chinese_semantic_group_issues(cues: Iterable[CaptionCue], level: str) -> list[dict]:
    cue_list = [cue for cue in cues if cue.english or cue.chinese]
    issues: list[dict] = []
    for group_index, group in enumerate(_semantic_cue_groups(cue_list), 1):
        english = " ".join(cue.english for cue in group).strip()
        parts = [cue.chinese.strip() for cue in group]
        chinese = "".join(parts).strip()
        if not english or not chinese:
            continue
        findings = _chinese_group_findings(chinese, parts)
        if not findings:
            continue
        high = _is_high_confidence_chinese_findings(findings)
        if level == "WARNING" and not high:
            continue
        if level == "INFO" and high:
            continue
        rule_codes = [item["code"] for item in findings]
        issues.append(
            {
                "code": "chinese_semantic_group_warning" if high else "chinese_semantic_group_info",
                "semantic_group_id": f"G{group_index:04d}",
                "subtitle_ids": [f"S{cue.index:04d}" for cue in group],
                "indices": [cue.index for cue in group],
                "start_ms": group[0].start_ms,
                "end_ms": group[-1].end_ms,
                "english": english,
                "chinese": chinese,
                "first_stage_full_translation": "",
                "mapping_valid": False,
                "rule_codes": rule_codes,
                "findings": findings,
                "confidence": "high" if high else "low",
                "suggest_llm_reallocation": False,
                "message": ("中文语义组高置信疑似病句" if high else "中文语义组低置信提示")
                + ": "
                + ", ".join(rule_codes),
            }
        )
    return issues


def _semantic_cue_groups(cues: list[CaptionCue]) -> list[list[CaptionCue]]:
    groups: list[list[CaptionCue]] = []
    current: list[CaptionCue] = []
    for cue in cues:
        current.append(cue)
        if len(current) >= 4 or re.search(r"[.!?]\s*$", cue.english.strip()):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _chinese_group_findings(chinese: str, parts: list[str]) -> list[dict]:
    compact = re.sub(r"\s+", "", chinese or "")
    findings: list[dict] = []
    if _has_clear_chinese_syntax_failure(compact):
        findings.append(
            {
                "code": "missing_predicate",
                "message": "整组中文拼接后句法不成立或缺少核心谓语",
                "confidence_score": 0.9,
            }
        )
    if _has_dangling_chinese_structure(compact, parts):
        findings.append(
            {
                "code": "dangling_preposition",
                "message": "中文存在悬空条件、介词结构或跨条残句",
                "confidence_score": 0.86,
            }
        )
    if _looks_like_english_order_zh(compact):
        findings.append(
            {
                "code": "english_word_order",
                "message": "中文疑似保留英文语序",
                "confidence_score": 0.78,
            }
        )
    return findings


def _is_high_confidence_chinese_findings(findings: list[dict]) -> bool:
    codes = {item["code"] for item in findings}
    if "missing_predicate" in codes and (
        "dangling_preposition" in codes or "english_word_order" in codes
    ):
        return True
    if "english_word_order" in codes and "dangling_preposition" in codes:
        return True
    return False


def _has_clear_chinese_syntax_failure(text: str) -> bool:
    if not text:
        return False
    if re.search(r"(久久|很久)(这次|此次|本次|这个|这种)", text):
        return True
    if re.search(r"明显改善的[。！？]?$", text):
        return True
    if re.search(r"退出通过.+(操纵|操作|控制)", text):
        return True
    if re.search(r"急剧飙升因为", text):
        return True
    return False


def _has_dangling_chinese_structure(text: str, parts: list[str]) -> bool:
    if re.search(r"如果.+在\d", text):
        return True
    if re.search(r"这让你，.+留下了.+(久久|很久).+结束后", text):
        return True
    for left, right in zip(parts, parts[1:]):
        left_clean = re.sub(r"[，。！？；：,.!?;:]+$", "", left or "")
        right_clean = right or ""
        if left_clean.endswith(("在", "通过", "因为", "对于", "关于")):
            return True
        if left_clean.endswith("的") and re.match(r"^[，。！？；：,.!?;:]", right_clean):
            return True
    return False


def _looks_like_english_order_zh(text: str) -> bool:
    patterns = (
        r"退出通过.+(操纵|操作|控制)",
        r"公共财政明显改善的",
        r"急剧飙升因为",
        r"如果你追踪.+类别在\d",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _syntax_boundary_issues(cues: Iterable[CaptionCue]) -> list[dict]:
    cue_list = list(cues)
    issues: list[dict] = []
    for previous, current in zip(cue_list, cue_list[1:]):
        reasons = _syntax_boundary_reasons(previous.english, current.english)
        if not reasons:
            continue
        previous_tokens = _word_tokens(previous.english)
        current_tokens = _word_tokens(current.english)
        confidence_score = min(0.95, 0.65 + 0.12 * len(reasons))
        issues.append(
            {
                "code": "syntax_boundary_audit",
                "index": current.index,
                "from_index": previous.index,
                "left_subtitle_id": f"S{previous.index:04d}",
                "right_subtitle_id": f"S{current.index:04d}",
                "rule_codes": reasons,
                "confidence": "high" if confidence_score >= 0.75 else "medium",
                "confidence_score": round(confidence_score, 2),
                "evidence": (
                    f"left_last={(previous_tokens[-1] if previous_tokens else '')}; "
                    f"right_first={(current_tokens[0] if current_tokens else '')}; "
                    f"left_tokens={previous_tokens[-4:]}; right_tokens={current_tokens[:4]}"
                ),
                "duplicates_legacy_bad_cut": False,
                "message": "英文句法边界疑似坏切点: " + "; ".join(reasons),
                "english": f"{previous.english} | {current.english}",
                "previous_english": previous.english,
                "current_english": current.english,
                "chinese": f"{previous.chinese}{current.chinese}",
            }
        )
    return issues


def _syntax_boundary_reasons(previous_text: str, current_text: str) -> list[str]:
    previous = (previous_text or "").strip()
    current = (current_text or "").strip()
    if not previous or not current or _is_safe_independent_boundary(previous, current):
        return []
    prev_tokens = _word_tokens(previous)
    cur_tokens = _word_tokens(current)
    if not prev_tokens or not cur_tokens:
        return []
    prev = prev_tokens[-1]
    cur = cur_tokens[0]
    prev2 = prev_tokens[-2] if len(prev_tokens) > 1 else ""
    reasons: list[str] = []
    if _is_abbreviation_name_boundary(previous, current):
        reasons.append("abbreviation_name_split")
    prepositions = {"into", "of", "for", "with", "without", "in", "on", "at", "by", "from", "to", "about", "around", "through", "over", "under", "between", "among", "against", "within", "across"}
    determiners = {"the", "a", "an", "this", "that", "these", "those", "our", "their", "its"}
    particles = {"down", "up", "out", "off", "in", "on", "away", "back", "over"}
    be_aux = {"am", "is", "are", "was", "were", "be", "been", "being", "we're", "they're", "it's", "that's"}
    auxiliaries = be_aux | {"can", "could", "will", "would", "should", "may", "might", "must", "do", "does", "did", "have", "has", "had"}
    object_verbs = {"force", "forces", "forced", "alter", "alters", "altered", "show", "shows", "showed", "raise", "raises", "raised", "put", "puts", "make", "makes", "made", "give", "gives", "gave", "take", "takes", "took", "create", "creates", "created"}
    adjectives = {"absolute", "extreme", "uncomfortable", "rapid", "massive", "structural", "financial", "corporate", "public", "private", "local", "global", "new", "old", "major", "regional", "economic", "entire", "empty", "really"}
    common_nouns = {"air", "look", "edge", "atmosphere", "world", "question", "solution", "solutions", "building", "government", "market", "markets", "policy", "data", "source", "sources"}
    if prev in prepositions:
        reasons.append("preposition_object_split")
    if prev in determiners:
        reasons.append("determiner_noun_split")
    if prev in auxiliaries and cur.endswith("ing"):
        reasons.append("auxiliary_predicate_split")
    if prev in be_aux and cur in {"to", "forced", "trying", "rapidly"}:
        reasons.append("be_complement_split")
    if prev in {"forced", "trying", "able", "going"} and cur == "to":
        reasons.append("to_infinitive_split")
    if prev.endswith("ing") and cur in particles:
        reasons.append("phrasal_verb_split")
    if prev in object_verbs and (cur in determiners or cur in adjectives or cur in common_nouns):
        reasons.append("verb_object_split")
    if prev in adjectives and (cur in adjectives or cur in common_nouns):
        reasons.append("modifier_head_split")
    if prev2 in be_aux and prev.endswith("ing") and cur in particles:
        reasons.append("verb_particle_split")
    if cur in {"are", "is", "was", "were"} and _previous_looks_like_subject(previous):
        reasons.append("subject_predicate_split")
    if prev.endswith("'s") or prev.endswith("s'"):
        reasons.append("possessive_head_split")
    return list(dict.fromkeys(reasons))


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)?|\d+(?:\.\d+)?", (text or "").lower())


def _is_safe_independent_boundary(previous: str, current: str) -> bool:
    if _is_abbreviation_name_boundary(previous, current):
        return False
    prev_words = _word_tokens(previous)
    cur_words = _word_tokens(current)
    cur_norm = re.sub(r"[^a-z'\s]", " ", current.lower()).strip()
    cur_norm = re.sub(r"\s+", " ", cur_norm)
    if re.search(r"[.!?]\s*$", previous):
        if cur_norm.startswith(("but ", "wow", "what do you mean", "well ")):
            return True
    if re.search(r"[.!?]\s*$", previous) and (len(prev_words) <= 5 or len(cur_words) <= 3):
        return True
    short_responses = {"right", "yeah", "yes", "no", "exactly", "precisely", "okay", "ok", "absolutely", "what question", "how so", "why"}
    prev_norm = re.sub(r"[^a-z'\s]", " ", previous.lower()).strip()
    return prev_norm in short_responses or cur_norm in short_responses


def _is_abbreviation_name_boundary(previous: str, current: str) -> bool:
    return bool(
        re.search(r"\b(?:St|Mt|Mr|Mrs|Ms|Dr|Prof|Jr|Sr)\.$", (previous or "").strip())
        and re.match(r"[A-Z][A-Za-z'-]{2,}\b", (current or "").strip())
    )


def _previous_looks_like_subject(text: str) -> bool:
    words = re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", text or "")
    if not words:
        return False
    tail = words[-3:]
    if len(tail) >= 2 and all(word[:1].isupper() for word in tail[-2:]):
        return True
    return tail[-1].lower() in {"we", "they", "you", "i", "he", "she", "it"}
