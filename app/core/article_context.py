import hashlib
import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from openai import OpenAI
from PyQt5.QtCore import QThread, pyqtSignal

from app.config import CACHE_PATH
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.storage.cache_manager import CacheManager
from app.core.utils import json_repair
from app.core.utils.logger import setup_logger

logger = setup_logger("article_context")

ARTICLE_CONTEXT_SCHEMA_VERSION = 2
ARTICLE_ASR_CORRECTION_POLICY_VERSION = "article-asr-correction-v2"
ARTICLE_RAW_RESPONSE_KEY = "_raw_response"
ARTICLE_ANALYSIS_META_KEY = "_analysis_meta"
ARTICLE_ENTITY_KEYS = (
    "people",
    "companies",
    "brands",
    "organisations",
    "places",
    "books_and_works",
    "awards",
    "media_outlets",
    "platforms",
    "technical_terms",
    "numbers_and_dates",
)
ARTICLE_CONTEXT_PROMPT = """
You analyze an English reference article for subtitle production.

The article is background context only. Do not rewrite the article.
Extract names and terms that may help ASR proper-noun correction and translation terminology consistency.
Return strict JSON only with these keys:
{
  "title": "",
  "summary": "",
  "people": [],
  "companies": [],
  "brands": [],
  "organisations": [],
  "places": [],
  "books_and_works": [],
  "awards": [],
  "media_outlets": [],
  "platforms": [],
  "technical_terms": [],
  "numbers_and_dates": []
}

Each object in people, companies, brands, organisations, places, books_and_works, awards, media_outlets, platforms, technical_terms, and numbers_and_dates must contain:
{
  "canonical_name": "",
  "chinese_name": "",
  "aliases": [],
  "category": ""
}

Rules:
- Keep canonical_name in English when the article uses English.
- chinese_name should be a concise Simplified Chinese rendering when obvious, otherwise "".
- aliases should include obvious abbreviations, spellings, or product shorthand found in the article.
- Extract all named people, books, poems, essays, memoirs, awards, media outlets, organisations, platforms, companies, and named products mentioned in the article.
- Put books, poetry collections, poems, essays, memoirs, films, programs, and article titles in books_and_works, not brands.
- Put literary prizes and other named awards in awards, not organisations.
- Put newspapers, broadcasters, magazines, and named media outlets in media_outlets.
- Put apps and social platforms in platforms unless they are clearly companies.
- numbers_and_dates includes numbers, years, percentages, currencies, valuations, and money amounts.
- Do not add facts not supported by the article.
- Do not output markdown.
"""


@dataclass
class ArticleLLMConfig:
    base_url: str
    api_key: str
    model: str


def clean_article_text(text: str, max_chars: int = 20000) -> str:
    text = (text or "").replace("\ufeff", "")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_chars]


def article_text_hash(text: str) -> str:
    cleaned = clean_article_text(text)
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest() if cleaned else ""


def empty_article_context() -> Dict[str, Any]:
    return {
        "schema_version": ARTICLE_CONTEXT_SCHEMA_VERSION,
        "title": "",
        "summary": "",
        **{key: [] for key in ARTICLE_ENTITY_KEYS},
    }


def normalize_article_context(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return empty_article_context()
    result = empty_article_context()
    result["title"] = str(data.get("title", "") or "").strip()
    result["summary"] = str(data.get("summary", "") or "").strip()
    for key in ARTICLE_ENTITY_KEYS:
        result[key] = [_normalize_term(item, key) for item in data.get(key, []) if isinstance(item, dict)]
    if data.get(ARTICLE_RAW_RESPONSE_KEY) is not None:
        result[ARTICLE_RAW_RESPONSE_KEY] = str(data.get(ARTICLE_RAW_RESPONSE_KEY) or "")
    if isinstance(data.get(ARTICLE_ANALYSIS_META_KEY), dict):
        result[ARTICLE_ANALYSIS_META_KEY] = dict(data.get(ARTICLE_ANALYSIS_META_KEY) or {})
    return result


def _normalize_term(item: Dict[str, Any], default_category: str) -> Dict[str, Any]:
    aliases = item.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list):
        aliases = []
    canonical = str(item.get("canonical_name", "") or "").strip()
    normalized_aliases = []
    for alias in aliases:
        alias_text = str(alias or "").strip()
        if alias_text and alias_text not in normalized_aliases and alias_text != canonical:
            normalized_aliases.append(alias_text)
    normalized = {
        "canonical_name": canonical,
        "chinese_name": str(item.get("chinese_name", "") or "").strip(),
        "aliases": normalized_aliases,
        "category": str(item.get("category", "") or default_category).strip() or default_category,
    }
    for key in (
        "source_key",
        "canonical_in_article",
        "evidence",
        "alias_details",
        "unsupported_aliases",
        "asr_correction_enabled",
        "asr_disabled_reason",
    ):
        if key in item:
            normalized[key] = item[key]
    return normalized


def analyze_article_text(
    article_text: str,
    llm_config: ArticleLLMConfig,
    *,
    cache_manager: Optional[CacheManager] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    cleaned = clean_article_text(article_text)
    if not cleaned:
        return empty_article_context()
    cache = cache_manager or CacheManager(str(CACHE_PATH))
    cache_key = article_text_hash(cleaned)
    cache_result = cache.get_llm_result(
        cache_key,
        llm_config.model,
        task="article_context_analysis",
        schema_version=ARTICLE_CONTEXT_SCHEMA_VERSION,
    )
    if cache_result:
        cached = normalize_article_context(json.loads(cache_result))
        meta = dict(cached.get(ARTICLE_ANALYSIS_META_KEY) or {})
        meta.update(
            {
                "model": llm_config.model,
                "cache_used": True,
                "prompt_hash": cache_key,
            }
        )
        cached[ARTICLE_ANALYSIS_META_KEY] = meta
        return cached

    client = OpenAI(base_url=llm_config.base_url, api_key=llm_config.api_key)
    response = client.chat.completions.create(
        model=llm_config.model,
        messages=[
            {"role": "system", "content": ARTICLE_CONTEXT_PROMPT},
            {"role": "user", "content": cleaned},
        ],
        temperature=0.0,
        timeout=timeout,
    )
    raw_response = response.choices[0].message.content or ""
    data = normalize_article_context(json_repair.loads(raw_response))
    data[ARTICLE_RAW_RESPONSE_KEY] = raw_response
    data[ARTICLE_ANALYSIS_META_KEY] = {
        "model": llm_config.model,
        "cache_used": False,
        "prompt_hash": cache_key,
    }
    cache.set_llm_result(
        cache_key,
        json.dumps(data, ensure_ascii=False),
        llm_config.model,
        task="article_context_analysis",
        schema_version=ARTICLE_CONTEXT_SCHEMA_VERSION,
    )
    return data


def save_article_artifacts(
    output_dir: str | Path,
    article_text: str,
    context: Dict[str, Any],
) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    cleaned = clean_article_text(article_text)
    normalized = enrich_article_context_with_evidence(context, cleaned)
    glossary = build_article_glossary(normalized)
    paths = {
        "article_source": root / "article_source.txt",
        "article_llm_raw_response": root / "article_llm_raw_response.txt",
        "article_context": root / "article_context.json",
        "article_glossary": root / "article_glossary.json",
        "article_context_audit": root / "article_context_audit.json",
    }
    paths["article_source"].write_text(cleaned, encoding="utf-8")
    paths["article_llm_raw_response"].write_text(
        str(context.get(ARTICLE_RAW_RESPONSE_KEY, "") or ""),
        encoding="utf-8",
    )
    paths["article_context"].write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["article_glossary"].write_text(
        json.dumps(glossary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["article_context_audit"].write_text(
        json.dumps(build_article_context_audit(normalized), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {key: str(path) for key, path in paths.items()}


def load_article_context(path: str | Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return empty_article_context()
    return normalize_article_context(json.loads(path.read_text(encoding="utf-8")))


def enrich_article_context_with_evidence(context: Dict[str, Any], article_text: str) -> Dict[str, Any]:
    normalized = normalize_article_context(context)
    cleaned = clean_article_text(article_text)
    for key in ARTICLE_ENTITY_KEYS:
        enriched_items = []
        for item in normalized.get(key, []):
            enriched = dict(item)
            canonical = str(enriched.get("canonical_name", "") or "")
            canonical_evidence = _find_article_evidence(cleaned, canonical)
            enriched["source_key"] = key
            enriched["canonical_in_article"] = canonical_evidence is not None
            enriched["evidence"] = canonical_evidence or {}
            alias_details = []
            for alias in enriched.get("aliases") or []:
                alias_evidence = _find_article_evidence(cleaned, str(alias or ""))
                alias_details.append(
                    {
                        "alias": alias,
                        "source": "llm",
                        "in_article": alias_evidence is not None,
                        "evidence": alias_evidence or {},
                    }
                )
            enriched["alias_details"] = alias_details
            enriched["unsupported_aliases"] = [
                detail["alias"] for detail in alias_details if not detail["in_article"]
            ]
            enriched_items.append(enriched)
        normalized[key] = enriched_items
    if context.get(ARTICLE_ANALYSIS_META_KEY):
        normalized[ARTICLE_ANALYSIS_META_KEY] = dict(context.get(ARTICLE_ANALYSIS_META_KEY) or {})
    return normalized


def build_article_context_audit(context: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_article_context(context)
    unsupported_entities = []
    unsupported_aliases = []
    category_counts: Dict[str, int] = {}
    for key in ARTICLE_ENTITY_KEYS:
        for item in normalized.get(key, []):
            category = str(item.get("category", "") or key)
            category_counts[category] = category_counts.get(category, 0) + 1
            if item.get("canonical_in_article") is False:
                unsupported_entities.append(
                    {
                        "canonical_name": item.get("canonical_name", ""),
                        "category": category,
                        "source_key": key,
                    }
                )
            for detail in item.get("alias_details") or []:
                if not detail.get("in_article"):
                    unsupported_aliases.append(
                        {
                            "canonical_name": item.get("canonical_name", ""),
                            "alias": detail.get("alias", ""),
                            "category": category,
                            "source_key": key,
                        }
                    )
    return {
        "schema_version": ARTICLE_CONTEXT_SCHEMA_VERSION,
        "category_counts": category_counts,
        "unsupported_entity_count": len(unsupported_entities),
        "unsupported_alias_count": len(unsupported_aliases),
        "unsupported_entities": unsupported_entities,
        "unsupported_aliases": unsupported_aliases,
    }


def _find_article_evidence(article_text: str, phrase: str) -> Optional[Dict[str, Any]]:
    phrase = str(phrase or "").strip()
    if not article_text or not phrase:
        return None
    article_text = _normalize_article_punctuation(article_text)
    phrase = _normalize_article_punctuation(phrase)
    pattern = re.compile(
        rf"(?<![A-Za-z0-9]){_article_phrase_pattern(phrase)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    match = pattern.search(article_text)
    if not match:
        return None
    sentence_start = max(article_text.rfind(".", 0, match.start()), article_text.rfind("\n", 0, match.start()))
    sentence_start = 0 if sentence_start < 0 else sentence_start + 1
    sentence_end_candidates = [
        pos for pos in (
            article_text.find(".", match.end()),
            article_text.find("\n", match.end()),
        )
        if pos >= 0
    ]
    sentence_end = min(sentence_end_candidates) + 1 if sentence_end_candidates else len(article_text)
    sentence = " ".join(article_text[sentence_start:sentence_end].split())
    return {
        "start_char": match.start(),
        "end_char": match.end(),
        "evidence_sentence": sentence,
    }


def _normalize_article_punctuation(text: str) -> str:
    return (
        str(text or "")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u9225\u6a9a", "'s")
        .replace("\u9225?", "'")
    )


def _glossary_term_for_matching(item: Dict[str, Any]) -> Dict[str, Any]:
    term = dict(item)
    supported_aliases = []
    for detail in term.get("alias_details") or []:
        if detail.get("in_article"):
            alias = str(detail.get("alias", "") or "").strip()
            if alias and alias not in supported_aliases:
                supported_aliases.append(alias)
    if term.get("canonical_in_article") is False and not supported_aliases:
        term["asr_correction_enabled"] = False
        term["asr_disabled_reason"] = "canonical_not_in_article"
    if term.get("alias_details"):
        term["aliases"] = supported_aliases
    return term


def build_article_glossary(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized = normalize_article_context(context)
    terms: List[Dict[str, Any]] = []
    seen = set()
    for key in ARTICLE_ENTITY_KEYS:
        for item in normalized.get(key, []):
            canonical = item.get("canonical_name", "")
            if not canonical:
                continue
            dedupe_key = canonical.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            terms.append(_glossary_term_for_matching(item))
    return terms


def build_translation_context_prompt(context: Dict[str, Any], max_terms: int = 80) -> str:
    normalized = normalize_article_context(context)
    glossary = build_article_glossary(normalized)[:max_terms]
    if not normalized.get("summary") and not glossary:
        return ""
    lines = [
        "Reference article context for terminology consistency only.",
        "Do not use the article to replace, add to, summarize, or reorganize ASR subtitles.",
        "Translate only the subtitle text provided by the current task.",
    ]
    if normalized.get("title"):
        lines.append(f"Article title: {normalized['title']}")
    if normalized.get("summary"):
        lines.append(f"Article summary: {normalized['summary']}")
    if glossary:
        lines.append("Preferred glossary:")
        for item in glossary:
            zh = item.get("chinese_name") or ""
            aliases = ", ".join(item.get("aliases") or [])
            suffix = f" -> {zh}" if zh else ""
            alias_text = f" (aliases: {aliases})" if aliases else ""
            lines.append(f"- {item.get('canonical_name', '')}{suffix}{alias_text}")
    return "\n".join(lines)


def apply_article_asr_corrections(
    asr_data: ASRData,
    context: Dict[str, Any],
    *,
    output_dir: str | Path,
    high_confidence: float = 0.82,
    review_confidence: float = 0.72,
) -> ASRData:
    glossary = build_article_glossary(context)
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    original_path = output_root / "asr-original-before-article-context.srt"
    asr_data.to_srt(save_path=str(original_path))

    if asr_data.is_word_timestamp():
        corrected_segments, candidates, logs = _correct_word_timestamp_segments(
            asr_data.segments,
            glossary,
            high_confidence=high_confidence,
            review_confidence=review_confidence,
        )
    else:
        candidates = []
        logs = []
        corrected_segments = []
        for seg in asr_data.segments:
            corrected_text, segment_logs = _correct_segment_text(
                seg.text,
                glossary,
                high_confidence=high_confidence,
                review_confidence=review_confidence,
            )
            corrected = ASRDataSeg(
                corrected_text,
                seg.start_time,
                seg.end_time,
                seg.translated_text,
            )
            if hasattr(seg, "subtitle_id"):
                corrected.subtitle_id = getattr(seg, "subtitle_id")
            corrected_segments.append(corrected)
            for item in segment_logs:
                item["start_time"] = seg.start_time
                item["end_time"] = seg.end_time
                logs.append(item)
                candidates.append(item)

    candidates_path = output_root / "correction_candidates.json"
    entity_candidates_path = output_root / "entity_candidates.json"
    log_path = output_root / "correction_log.json"
    rejected_path = output_root / "correction_rejected.json"
    compatibility_path = output_root / "article_asr_corrections.json"
    candidates_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    entity_candidates_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log_path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    rejected_path.write_text(
        json.dumps([item for item in logs if not item.get("applied")], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    compatibility_path.write_text(
        json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if logs:
        logger.info("Article context ASR correction candidates saved: %s", log_path)
    return ASRData(corrected_segments)


def _correct_word_timestamp_segments(
    segments: Sequence[ASRDataSeg],
    glossary: Sequence[Dict[str, Any]],
    *,
    high_confidence: float,
    review_confidence: float,
) -> tuple[List[ASRDataSeg], List[Dict[str, Any]], List[Dict[str, Any]]]:
    terms = _glossary_match_terms(glossary)
    if not terms:
        return list(segments), [], []

    candidates: List[Dict[str, Any]] = []
    logs: List[Dict[str, Any]] = []
    max_window = min(8, max((term["max_tokens"] + 1 for term in terms), default=1))
    terms_by_window_size = _glossary_terms_by_window_size(terms, max_window)

    candidate_seq = 0
    for index in range(len(segments)):
        for window_size in range(1, min(max_window, len(segments) - index) + 1):
            window = segments[index : index + window_size]
            if _window_crosses_sentence_boundary(window):
                continue
            original_text = _join_asr_words(seg.text for seg in window)
            if not re.search(r"[A-Za-z0-9]", original_text or ""):
                continue
            for term in terms_by_window_size.get(window_size, []):
                if window_size > term["max_tokens"] and _has_boundary_filler(window):
                    continue
                candidate = _score_correction_candidate(original_text, term)
                candidate["start_time"] = window[0].start_time
                candidate["end_time"] = window[-1].end_time
                candidate["segment_index"] = index + 1
                candidate["window_size"] = window_size
                candidate["start_word_index"] = index
                candidate["end_word_index"] = index + window_size
                candidate["original_words"] = [str(seg.text or "") for seg in window]
                candidate["canonical_name"] = term["source"].get("canonical_name", term["canonical"])
                candidate["category"] = term["source"].get("category", "")
                candidate["source_key"] = term["source"].get("source_key", "")
                candidate["evidence"] = term["source"].get("evidence", {})
                existing_span = _existing_canonical_span_near_candidate(
                    segments,
                    index,
                    index + window_size,
                    str(term.get("canonical") or ""),
                )
                if existing_span:
                    candidate["existing_canonical_span"] = existing_span
                candidate["candidate_id"] = f"article-correction-{candidate_seq:06d}"
                candidate_seq += 1
                context_evidence = _person_description_context_support(
                    segments,
                    index,
                    index + window_size,
                    candidate,
                )
                candidate["context_match"] = bool(context_evidence.get("matched"))
                candidate["context_evidence"] = context_evidence
                if candidate["context_match"]:
                    candidate["matched_conditions"].append(
                        "article_person_context_match"
                    )
                candidate["asr_confidence_low"] = None
                if _is_self_replacement_candidate(candidate):
                    continue
                if (
                    candidate["final_confidence"] >= review_confidence
                    or _context_supported_person_candidate(candidate)
                ):
                    if candidate.get("matched_variant_is_alias"):
                        alias_collision = _find_ambiguous_alias_canonical_collision(candidate, terms)
                        if alias_collision:
                            candidate["alias_canonical_collision"] = alias_collision
                    candidates.append(candidate)

    selected, overlap_rejections = _resolve_overlapping_article_correction_candidates(
        [candidate for candidate in candidates if _should_apply_candidate(candidate, high_confidence)]
    )
    selected_ids = {candidate["candidate_id"] for candidate in selected}
    overlap_rejected_ids = {
        item["rejected_candidate_id"]: item for item in overlap_rejections
    }

    for candidate in candidates:
        if candidate.get("candidate_id") in selected_ids:
            candidate["applied"] = True
            candidate["result"] = "replaced"
            candidate["reason"] = "high_confidence_article_glossary_match"
            logs.append(candidate)
        elif candidate.get("candidate_id") in overlap_rejected_ids:
            candidate["applied"] = False
            candidate["result"] = "rejected"
            candidate["reason"] = "overlapping_candidate"
            candidate["overlap_resolution"] = overlap_rejected_ids[candidate["candidate_id"]]
            logs.append(candidate)
        else:
            candidate["applied"] = False
            candidate["result"] = "review_only"
            candidate["reason"] = _not_applied_reason(candidate, high_confidence)
            if candidate["final_confidence"] >= review_confidence:
                logs.append(candidate)

    corrected = _apply_article_correction_candidates(segments, selected)
    corrected, dedupe_logs = _dedupe_adjacent_canonical_entity_overlap(corrected)
    logs.extend(dedupe_logs)
    for candidate in selected:
        logger.info(
            "Article ASR correction applied: %s -> %s confidence=%.4f",
            candidate["original_text"],
            candidate["corrected_text"],
            candidate["final_confidence"],
        )
    return corrected, candidates, logs


def _glossary_terms_by_window_size(
    terms: Sequence[Dict[str, Any]],
    max_window: int,
) -> Dict[int, List[Dict[str, Any]]]:
    terms_by_size: Dict[int, List[Dict[str, Any]]] = {
        size: [] for size in range(1, max_window + 1)
    }
    for term in terms:
        canonical_token_count = int(term.get("canonical_token_count") or 0)
        if canonical_token_count <= 0:
            continue
        for window_size in range(1, max_window + 1):
            if abs(window_size - canonical_token_count) <= 1:
                terms_by_size[window_size].append(term)
    return terms_by_size


def _resolve_overlapping_article_correction_candidates(
    candidates: Sequence[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    selected: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for candidate in sorted(candidates, key=_candidate_resolution_sort_key):
        conflicts = [
            kept
            for kept in selected
            if _candidate_ranges_overlap(candidate, kept)
        ]
        if not conflicts:
            selected.append(candidate)
            continue
        kept = sorted(conflicts, key=_candidate_resolution_sort_key)[0]
        rejected.append(
            {
                "reason": "overlapping_candidate",
                "kept_candidate_id": kept.get("candidate_id", ""),
                "rejected_candidate_id": candidate.get("candidate_id", ""),
                "kept_word_range": [
                    int(kept.get("start_word_index", 0)),
                    int(kept.get("end_word_index", 0)),
                ],
                "rejected_word_range": [
                    int(candidate.get("start_word_index", 0)),
                    int(candidate.get("end_word_index", 0)),
                ],
                "kept_score": float(kept.get("final_confidence") or 0.0),
                "rejected_score": float(candidate.get("final_confidence") or 0.0),
                "canonical_name": candidate.get("canonical_name", candidate.get("candidate_text", "")),
                "original_words": candidate.get("original_words", []),
            }
        )
    return sorted(selected, key=lambda item: int(item.get("start_word_index", 0))), rejected


def _candidate_resolution_sort_key(candidate: Dict[str, Any]) -> tuple:
    return (
        0 if _candidate_has_article_evidence(candidate) else 1,
        0 if str(candidate.get("reason", "") or "") != "review_only" else 1,
        -float(candidate.get("final_confidence") or 0.0),
        -int(candidate.get("end_word_index", 0)) + int(candidate.get("start_word_index", 0)),
        str(candidate.get("candidate_id", "")),
        int(candidate.get("start_word_index", 0)),
    )


def _candidate_has_article_evidence(candidate: Dict[str, Any]) -> bool:
    evidence = candidate.get("evidence")
    if isinstance(evidence, dict) and evidence.get("evidence_sentence"):
        return True
    source = candidate.get("source_glossary")
    if isinstance(source, dict) and source.get("evidence"):
        return True
    return bool(candidate.get("article_entity_present"))


def _candidate_ranges_overlap(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_start = int(left.get("start_word_index", 0))
    left_end = int(left.get("end_word_index", 0))
    right_start = int(right.get("start_word_index", 0))
    right_end = int(right.get("end_word_index", 0))
    return left_start < right_end and right_start < left_end


def _existing_canonical_span_near_candidate(
    segments: Sequence[ASRDataSeg],
    candidate_start: int,
    candidate_end: int,
    canonical: str,
) -> Dict[str, Any]:
    """Find an already-correct entity span touching a fuzzy candidate.

    A fuzzy window may include one neighbouring discourse word or title even
    though the complete canonical entity is already present inside or beside
    that window. Replacing the fuzzy window would delete source words. The
    glossary window-size contract differs by at most one token, so inspecting
    one segment on either side is sufficient and keeps this guard local.
    """
    canonical_tokens = _normalized_entity_tokens(_word_tokens(canonical))
    candidate_tokens = _normalized_entity_tokens(
        _word_tokens(
            _join_asr_words(
                segment.text
                for segment in segments[candidate_start:candidate_end]
            )
        )
    )
    if not canonical_tokens or len(candidate_tokens) < len(canonical_tokens):
        return {}
    context_start = max(0, int(candidate_start) - 1)
    context_end = min(len(segments), int(candidate_end) + 1)
    for span_start in range(context_start, context_end):
        for span_end in range(span_start + 1, context_end + 1):
            if span_start >= candidate_end or span_end <= candidate_start:
                continue
            if (span_start, span_end) == (candidate_start, candidate_end):
                continue
            span_tokens = _normalized_entity_tokens(
                _word_tokens(
                    _join_asr_words(
                        segment.text for segment in segments[span_start:span_end]
                    )
                )
            )
            if span_tokens == canonical_tokens:
                return {
                    "start_word_index": span_start,
                    "end_word_index": span_end,
                    "original_words": [
                        str(segment.text or "")
                        for segment in segments[span_start:span_end]
                    ],
                }
    return {}


def _apply_article_correction_candidates(
    segments: Sequence[ASRDataSeg],
    selected: Sequence[Dict[str, Any]],
) -> List[ASRDataSeg]:
    selected_by_start = {
        int(candidate.get("start_word_index", 0)): candidate for candidate in selected
    }
    corrected: List[ASRDataSeg] = []
    index = 0
    while index < len(segments):
        candidate = selected_by_start.get(index)
        if candidate:
            end_index = int(candidate.get("end_word_index", index + 1))
            replacement = ASRDataSeg(
                candidate["corrected_text"],
                segments[index].start_time,
                segments[end_index - 1].end_time,
                segments[index].translated_text,
            )
            if hasattr(segments[index], "subtitle_id"):
                replacement.subtitle_id = getattr(segments[index], "subtitle_id")
            replacement._article_word_range = (index, end_index)
            replacement._article_correction = candidate
            corrected.append(replacement)
            index = end_index
            continue
        original = segments[index]
        copied = ASRDataSeg(
            original.text,
            original.start_time,
            original.end_time,
            original.translated_text,
        )
        if hasattr(original, "subtitle_id"):
            copied.subtitle_id = getattr(original, "subtitle_id")
        copied._article_word_range = (index, index + 1)
        corrected.append(copied)
        index += 1
    _validate_corrected_word_ledger(corrected)
    return corrected


def _validate_corrected_word_ledger(segments: Sequence[ASRDataSeg]) -> None:
    previous_end: Optional[int] = None
    for segment in segments:
        word_range = getattr(segment, "_article_word_range", None)
        if not word_range:
            continue
        start, end = int(word_range[0]), int(word_range[1])
        if start >= end:
            raise ValueError("invalid_article_correction_word_range")
        if previous_end is not None and start < previous_end:
            raise ValueError("overlapping_article_correction_word_ledger")
        previous_end = end


def _dedupe_adjacent_canonical_entity_overlap(
    segments: Sequence[ASRDataSeg],
) -> tuple[List[ASRDataSeg], List[Dict[str, Any]]]:
    result = list(segments)
    logs: List[Dict[str, Any]] = []
    index = 0
    while index < len(result):
        current = result[index]
        correction = getattr(current, "_article_correction", None)
        if not correction:
            index += 1
            continue
        canonical = str(correction.get("canonical_name") or correction.get("candidate_text") or "")
        canonical_tokens = _word_tokens(canonical)
        current_tokens = _word_tokens(current.text)
        if not canonical_tokens or _normalized_entity_tokens(current_tokens) != _normalized_entity_tokens(
            canonical_tokens
        ):
            index += 1
            continue

        if index > 0 and _tokens_are_canonical_edge_overlap(
            _word_tokens(result[index - 1].text), canonical_tokens, prefix=True
        ):
            previous = result[index - 1]
            logs.append(
                _canonical_overlap_log(previous, current, canonical, correction, "prefix")
            )
            current.start_time = previous.start_time
            current._article_word_range = (
                getattr(previous, "_article_word_range", (0, 0))[0],
                getattr(current, "_article_word_range", (0, 0))[1],
            )
            del result[index - 1]
            index -= 1
            continue

        if index + 1 < len(result) and _tokens_are_canonical_edge_overlap(
            _word_tokens(result[index + 1].text), canonical_tokens, prefix=False
        ):
            following = result[index + 1]
            logs.append(
                _canonical_overlap_log(current, following, canonical, correction, "suffix")
            )
            current.end_time = following.end_time
            current.text = _carry_trailing_punctuation(current.text, following.text)
            current._article_word_range = (
                getattr(current, "_article_word_range", (0, 0))[0],
                getattr(following, "_article_word_range", (0, 0))[1],
            )
            del result[index + 1]
            continue
        index += 1
    _validate_corrected_word_ledger(result)
    return result, logs


def _tokens_are_canonical_edge_overlap(
    tokens: Sequence[str],
    canonical_tokens: Sequence[str],
    *,
    prefix: bool,
) -> bool:
    if not tokens or len(tokens) >= len(canonical_tokens):
        return False
    left = _normalized_entity_tokens(tokens)
    right = _normalized_entity_tokens(canonical_tokens)
    if prefix:
        return left == right[: len(left)]
    return left == right[-len(left) :]


def _canonical_overlap_log(
    left: ASRDataSeg,
    right: ASRDataSeg,
    canonical: str,
    correction: Dict[str, Any],
    overlap_side: str,
) -> Dict[str, Any]:
    left_range = getattr(left, "_article_word_range", (0, 0))
    right_range = getattr(right, "_article_word_range", (0, 0))
    after_text = (
        right.text
        if overlap_side == "prefix"
        else _carry_trailing_punctuation(left.text, right.text)
    )
    return {
        "original_text": _join_asr_words([left.text, right.text]),
        "before_words": [left.text, right.text],
        "corrected_text": after_text,
        "after_text": after_text,
        "word_range": [int(left_range[0]), int(right_range[1])],
        "start_word_index": int(left_range[0]),
        "end_word_index": int(right_range[1]),
        "start_time": left.start_time,
        "end_time": right.end_time,
        "canonical_name": canonical,
        "candidate_id": f"{correction.get('candidate_id', '')}:canonical-overlap-{overlap_side}",
        "source_candidate_id": correction.get("candidate_id", ""),
        "confidence": correction.get("confidence", correction.get("final_confidence", 0.0)),
        "final_confidence": correction.get("final_confidence", correction.get("confidence", 0.0)),
        "category": correction.get("category", ""),
        "source_key": correction.get("source_key", ""),
        "source_glossary": correction.get("source_glossary", {}),
        "applied": True,
        "result": "replaced",
        "reason": "adjacent_canonical_entity_overlap_deduped",
        "overlap_side": overlap_side,
    }


def _normalized_entity_tokens(tokens: Sequence[str]) -> List[str]:
    return [_normalize_entity_gate_token(token) for token in tokens if _normalize_entity_gate_token(token)]


def _carry_trailing_punctuation(text: str, source_text: str) -> str:
    match = re.search(r"([,.;:!?]+)$", str(source_text or "").strip())
    if not match or re.search(r"[,.;:!?]+$", str(text or "").strip()):
        return text
    return f"{text}{match.group(1)}"


def _glossary_match_terms(glossary: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    terms = []
    asr_source_keys = {
        "people",
        "companies",
        "brands",
        "organisations",
        "places",
        "books_and_works",
        "awards",
        "media_outlets",
        "platforms",
        "technical_terms",
    }
    allowed_categories = {
        "analyst",
        "app",
        "author",
        "award",
        "book",
        "books_and_works",
        "city",
        "company",
        "companies",
        "country",
        "essay",
        "historical figure",
        "institution",
        "institutions",
        "list",
        "literary award",
        "media outlet",
        "memoir",
        "organisation",
        "organisations",
        "organization",
        "organizations",
        "person",
        "people",
        "place",
        "places",
        "platform",
        "platforms",
        "poem",
        "poet",
        "poetry collection",
        "brand",
        "brands",
        "product",
        "products",
        "region",
        "research center",
        "social media platform",
        "think tank",
        "writer",
    }
    for term in glossary:
        if term.get("asr_correction_enabled") is False:
            continue
        canonical = str(term.get("canonical_name", "") or "").strip()
        if not canonical or not re.search(r"[A-Za-z0-9]", canonical):
            continue
        source_key = str(term.get("source_key", "") or "").strip().casefold()
        category = str(term.get("category", "") or "").strip().casefold()
        if source_key and source_key not in asr_source_keys:
            continue
        if source_key == "technical_terms" and not _technical_term_is_asr_eligible(term):
            continue
        if not source_key and category and category not in allowed_categories:
            continue
        variants = [canonical]
        for alias in term.get("aliases") or []:
            alias_text = str(alias or "").strip()
            if alias_text and alias_text not in variants:
                variants.append(alias_text)
        terms.append(
            {
                "canonical": canonical,
                "variants": variants,
                "variant_match_keys": [
                    {
                        "text": variant,
                        "compact": _compact_text(variant),
                        "phonetic": _phonetic_key(variant),
                    }
                    for variant in variants
                ],
                "source": dict(term),
                "max_tokens": max(len(_word_tokens(variant)) for variant in variants),
                "canonical_token_count": len(_word_tokens(canonical)),
            }
        )
    return terms


def _technical_term_is_asr_eligible(term: Dict[str, Any]) -> bool:
    """Admit only article-defined, distinctive domain terms to ASR correction."""
    canonical = str(term.get("canonical_name", "") or "").strip()
    canonical_tokens = _word_tokens(canonical)
    evidence = term.get("evidence") or {}
    supported_aliases = [
        str(alias or "").strip()
        for alias in term.get("aliases") or []
        if str(alias or "").strip()
    ]
    if (
        term.get("canonical_in_article") is not True
        or not isinstance(evidence, dict)
        or not evidence.get("evidence_sentence")
        or not canonical_tokens
    ):
        return False
    normalized = [_normalize_entity_gate_token(token) for token in canonical_tokens]
    if any(
        token in _COMMON_LOWERCASE_WORD_PROTECTION
        or token in _ENTITY_BLOCKING_FUNCTION_WORDS
        for token in normalized
    ):
        return False
    distinctive_surface = bool(
        re.search(r"[A-Z].*[A-Z]|[a-z][A-Z]|\d|[-.]", canonical)
    )
    return bool(supported_aliases or distinctive_surface)


def _has_boundary_filler(window: Sequence[ASRDataSeg]) -> bool:
    if not window:
        return False
    boundary_words = {
        "right",
        "yeah",
        "yes",
        "yep",
        "okay",
        "ok",
        "well",
        "so",
        "and",
        "or",
        "but",
        "on",
        "in",
        "at",
        "to",
        "from",
        "with",
        "by",
        "for",
        "of",
        "the",
        "a",
        "an",
        "based",
    }
    first = (_word_tokens(window[0].text) or [""])[0].casefold()
    last_tokens = _word_tokens(window[-1].text)
    last = (last_tokens[-1] if last_tokens else "").casefold()
    return first in boundary_words or last in boundary_words


def _window_crosses_sentence_boundary(window: Sequence[ASRDataSeg]) -> bool:
    if len(window) <= 1:
        return False
    return any(
        re.search(r"[.!?]+$", str(seg.text or "").strip())
        and _normalize_entity_gate_token(str(seg.text or ""))
        not in _ARTICLE_PERSON_TITLES
        for seg in window[:-1]
    )


def _score_correction_candidate(original_text: str, term: Dict[str, Any]) -> Dict[str, Any]:
    original_norm = _compact_text(original_text)
    original_phone = _phonetic_key(original_text)
    canonical = term["canonical"]
    best_variant = ""
    best_string = 0.0
    best_phonetic = 0.0
    variant_match_keys = term.get("variant_match_keys") or [
        {
            "text": variant,
            "compact": _compact_text(variant),
            "phonetic": _phonetic_key(variant),
        }
        for variant in term.get("variants", [])
    ]
    for variant_key in variant_match_keys:
        variant = str(variant_key.get("text") or "")
        string_similarity = SequenceMatcher(
            None, original_norm, str(variant_key.get("compact") or "")
        ).ratio()
        phonetic_similarity = SequenceMatcher(
            None, original_phone, str(variant_key.get("phonetic") or "")
        ).ratio()
        if (string_similarity, phonetic_similarity) > (best_string, best_phonetic):
            best_variant = variant
            best_string = string_similarity
            best_phonetic = phonetic_similarity
    final_confidence = max(best_string, best_phonetic * 0.98)
    conditions = ["candidate_in_article_glossary"]
    if (
        best_variant
        and _entity_phrase_key(original_text) == _entity_phrase_key(best_variant)
    ):
        conditions.append("exact_alias_match")
    if best_string >= 0.78:
        conditions.append("spelling_similarity")
    if best_phonetic >= 0.82:
        conditions.append("phonetic_similarity")
    original_tokens = _word_tokens(original_text)
    canonical_tokens = _word_tokens(canonical)
    entity_gate = _entity_phrase_gate(original_text, canonical)
    matched_variant_is_alias = bool(best_variant) and (
        _entity_phrase_key(best_variant) != _entity_phrase_key(canonical)
    )
    matched_alias_evidence = (
        _matched_alias_evidence(term["source"], best_variant)
        if matched_variant_is_alias
        else {}
    )
    return {
        "original_text": original_text,
        "suspicious_text": original_text,
        "corrected_text": _replacement_text_for_original(original_text, canonical),
        "candidate_text": canonical,
        "matched_variant": best_variant,
        "matched_variant_is_alias": matched_variant_is_alias,
        "matched_alias_evidence": matched_alias_evidence,
        "source": "article_glossary.json",
        "string_similarity": round(best_string, 4),
        "phonetic_similarity": round(best_phonetic, 4),
        "final_confidence": round(final_confidence, 4),
        "confidence": round(final_confidence, 4),
        "matched_conditions": conditions,
        "original_token_count": len(original_tokens),
        "candidate_token_count": len(canonical_tokens),
        "original_has_uppercase": bool(re.search(r"[A-Z]", original_text or "")),
        "original_is_all_lowercase": bool(original_text) and original_text == original_text.lower(),
        "article_entity_present": True,
        "entity_gate_passed": entity_gate["passed"],
        "entity_gate_reason": entity_gate["reason"],
        "grammar_validation": entity_gate["grammar_validation"],
        "source_glossary": {
            "canonical_name": term["source"].get("canonical_name", ""),
            "chinese_name": term["source"].get("chinese_name", ""),
            "category": term["source"].get("category", ""),
            "source_key": term["source"].get("source_key", ""),
            "aliases": term["source"].get("aliases", []),
            "canonical_in_article": term["source"].get("canonical_in_article"),
            "evidence": dict(term["source"].get("evidence") or {}),
        },
    }


_ARTICLE_PERSON_TITLES = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "doctor", "prof", "professor"}
)
_ARTICLE_PERSON_CONTEXT_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "because",
        "before",
        "being",
        "case",
        "could",
        "exactly",
        "from",
        "have",
        "into",
        "like",
        "more",
        "other",
        "said",
        "that",
        "their",
        "there",
        "these",
        "they",
        "this",
        "those",
        "when",
        "where",
        "which",
        "while",
        "with",
        "would",
    }
)


def _person_description_context_support(
    segments: Sequence[ASRDataSeg],
    start_index: int,
    end_index: int,
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """Require nearby article-description overlap before relaxing a person name."""
    if not _candidate_is_person_name(candidate):
        return {"matched": False, "reason": "not_person_entity"}
    evidence = candidate.get("evidence") or {}
    evidence_sentence = str(evidence.get("evidence_sentence") or "").strip()
    if not evidence_sentence:
        return {"matched": False, "reason": "missing_person_article_evidence"}

    original_tokens = _word_tokens(str(candidate.get("original_text") or ""))
    canonical_tokens = _word_tokens(str(candidate.get("candidate_text") or ""))
    if len(original_tokens) < 2 or len(original_tokens) != len(canonical_tokens):
        return {"matched": False, "reason": "person_name_shape_mismatch"}
    original_normalized = [_normalize_entity_gate_token(token) for token in original_tokens]
    canonical_normalized = [_normalize_entity_gate_token(token) for token in canonical_tokens]
    original_title = original_normalized[0] if original_normalized[0] in _ARTICLE_PERSON_TITLES else ""
    canonical_title = canonical_normalized[0] if canonical_normalized[0] in _ARTICLE_PERSON_TITLES else ""
    if not canonical_title or original_title != canonical_title:
        return {"matched": False, "reason": "person_title_mismatch"}

    original_surname = original_normalized[-1]
    canonical_surname = canonical_normalized[-1]
    surname_similarity = _entity_token_similarity(original_surname, canonical_surname)
    if (
        not original_surname
        or not canonical_surname
        or original_surname[0] != canonical_surname[0]
        or surname_similarity < 0.5
        or float(candidate.get("final_confidence") or 0.0) < 0.6
    ):
        return {"matched": False, "reason": "person_surname_similarity_too_low"}

    context_start = max(0, start_index - 24)
    context_end = min(len(segments), end_index + 24)
    nearby_text = _join_asr_words(
        segment.text for segment in segments[context_start:context_end]
    )
    excluded = set(canonical_normalized) | set(original_normalized) | _ARTICLE_PERSON_TITLES
    article_terms = _person_context_terms(evidence_sentence, excluded)
    nearby_terms = _person_context_terms(nearby_text, excluded)
    overlap = sorted(article_terms & nearby_terms)
    distinctive_overlap = [
        token for token in overlap if token.isdigit() or len(token) >= 6
    ]
    matched = len(overlap) >= 2 and bool(distinctive_overlap)
    return {
        "matched": matched,
        "reason": (
            "article_person_description_overlap"
            if matched
            else "insufficient_nearby_person_description_overlap"
        ),
        "surname_similarity": round(surname_similarity, 4),
        "overlap_terms": overlap,
        "context_word_range": [context_start, context_end],
    }


def _person_context_terms(text: str, excluded: set[str]) -> set[str]:
    terms = set()
    for token in _word_tokens(text):
        normalized = _normalize_entity_gate_token(token)
        if (
            not normalized
            or normalized in excluded
            or normalized in _ARTICLE_PERSON_CONTEXT_STOP_WORDS
            or normalized in _ENTITY_BLOCKING_FUNCTION_WORDS
            or (len(normalized) < 4 and not normalized.isdigit())
        ):
            continue
        terms.add(normalized)
    return terms


def _article_defined_technical_term_candidate(candidate: Dict[str, Any]) -> bool:
    source = candidate.get("source_glossary") or {}
    if str(source.get("source_key", "") or "").casefold() != "technical_terms":
        return False
    if not _technical_term_is_asr_eligible(source):
        return False
    original_tokens = _word_tokens(str(candidate.get("original_text", "") or ""))
    canonical_tokens = _word_tokens(str(candidate.get("candidate_text", "") or ""))
    if len(original_tokens) != 1 or len(canonical_tokens) != 1:
        return False
    original = _normalize_entity_gate_token(original_tokens[0])
    canonical = _normalize_entity_gate_token(canonical_tokens[0])
    if (
        len(original) < 4
        or len(canonical) < 4
        or original[:1] != canonical[:1]
        or original in _COMMON_LOWERCASE_WORD_PROTECTION
        or canonical in _COMMON_LOWERCASE_WORD_PROTECTION
    ):
        return False
    return (
        float(candidate.get("phonetic_similarity") or 0) >= 0.88
        and float(candidate.get("string_similarity") or 0) >= 0.5
    )


def _matched_alias_evidence(source: Dict[str, Any], matched_variant: str) -> Dict[str, Any]:
    matched_key = _compact_text(matched_variant)
    if not matched_key:
        return {}
    for detail in source.get("alias_details") or []:
        if _compact_text(str(detail.get("alias", "") or "")) != matched_key:
            continue
        evidence = detail.get("evidence")
        return dict(evidence) if isinstance(evidence, dict) else {}
    return {}


def _find_ambiguous_alias_canonical_collision(
    candidate: Dict[str, Any],
    terms: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Detect a short alias that is embedded in a different entity phrase.

    An article can legitimately contain both a short shared name and several
    longer institutions.  Similarity alone must not turn the distinct token in
    the ASR phrase into the target canonical's token.  This only rejects an
    automatic replacement when the original word window itself supports a
    competing glossary canonical.
    """
    matched_variant = str(candidate.get("matched_variant", "") or "")
    target_canonical = str(candidate.get("candidate_text", "") or "")
    original_tokens = _normalized_entity_tokens(_word_tokens(candidate.get("original_text", "")))
    alias_tokens = _normalized_entity_tokens(_word_tokens(matched_variant))
    target_tokens = _normalized_entity_tokens(_word_tokens(target_canonical))
    if (
        not original_tokens
        or not alias_tokens
        or not target_tokens
        or _compact_text(matched_variant) == _compact_text(target_canonical)
        or len(alias_tokens) >= len(target_tokens)
    ):
        return {}

    original_alias_starts = _token_subsequence_starts(original_tokens, alias_tokens)
    target_alias_starts = _token_subsequence_starts(target_tokens, alias_tokens)
    if not original_alias_starts or not target_alias_starts:
        return {}

    conflicts: List[Dict[str, Any]] = []
    seen_canonicals = set()
    target_key = _compact_text(target_canonical)
    for term in terms:
        conflicting_canonical = str(term.get("canonical", "") or "")
        conflicting_tokens = _normalized_entity_tokens(_word_tokens(conflicting_canonical))
        if (
            not conflicting_tokens
            or _compact_text(conflicting_canonical) == target_key
            or _compact_text(conflicting_canonical) in seen_canonicals
        ):
            continue
        conflicting_alias_starts = _token_subsequence_starts(conflicting_tokens, alias_tokens)
        if not conflicting_alias_starts:
            continue

        conflict = _find_alias_discriminator_conflict(
            original_tokens,
            target_tokens,
            conflicting_tokens,
            original_alias_starts,
            target_alias_starts,
            conflicting_alias_starts,
        )
        if not conflict:
            continue
        source = term.get("source") or {}
        conflicts.append(
            {
                "canonical_name": conflicting_canonical,
                "category": source.get("category", ""),
                "source_key": source.get("source_key", ""),
                "evidence": dict(source.get("evidence") or {}),
                **conflict,
            }
        )
        seen_canonicals.add(_compact_text(conflicting_canonical))

    if not conflicts:
        return {}
    return {
        "matched_variant": matched_variant,
        "target_canonical": target_canonical,
        "matched_alias_evidence": dict(candidate.get("matched_alias_evidence") or {}),
        "conflicting_canonicals": conflicts,
    }


def _token_subsequence_starts(tokens: Sequence[str], phrase: Sequence[str]) -> List[int]:
    if not tokens or not phrase or len(phrase) > len(tokens):
        return []
    return [
        start
        for start in range(len(tokens) - len(phrase) + 1)
        if list(tokens[start : start + len(phrase)]) == list(phrase)
    ]


def _find_alias_discriminator_conflict(
    original_tokens: Sequence[str],
    target_tokens: Sequence[str],
    conflicting_tokens: Sequence[str],
    original_alias_starts: Sequence[int],
    target_alias_starts: Sequence[int],
    conflicting_alias_starts: Sequence[int],
) -> Dict[str, Any]:
    for original_start in original_alias_starts:
        for target_start in target_alias_starts:
            for conflicting_start in conflicting_alias_starts:
                for original_index, original_token in enumerate(original_tokens):
                    relative_index = original_index - original_start
                    target_index = target_start + relative_index
                    conflicting_index = conflicting_start + relative_index
                    if not (0 <= conflicting_index < len(conflicting_tokens)):
                        continue
                    conflicting_token = conflicting_tokens[conflicting_index]
                    if _entity_token_similarity(original_token, conflicting_token) < 0.9:
                        continue
                    target_token = (
                        target_tokens[target_index]
                        if 0 <= target_index < len(target_tokens)
                        else ""
                    )
                    if target_token and _entity_token_similarity(original_token, target_token) >= 0.8:
                        continue
                    return {
                        "discriminator_word_offset": original_index,
                        "original_token": original_token,
                        "target_token": target_token,
                        "conflicting_token": conflicting_token,
                    }
    return {}


def _is_self_replacement_candidate(candidate: Dict[str, Any]) -> bool:
    original = str(candidate.get("original_text", "") or "")
    corrected = str(candidate.get("corrected_text", "") or "")
    return _surface_text_key(original) == _surface_text_key(corrected)


def _surface_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def _should_apply_candidate(candidate: Dict[str, Any], high_confidence: float) -> bool:
    if _is_self_replacement_candidate(candidate):
        return False
    near_threshold_person_edge = _near_threshold_person_edge_candidate(
        candidate, high_confidence
    )
    context_supported_person = _context_supported_person_candidate(candidate)
    if (
        candidate["final_confidence"] < high_confidence
        and not near_threshold_person_edge
        and not context_supported_person
    ):
        return False
    if _article_scope_rejection_reason(candidate):
        return False
    if near_threshold_person_edge or context_supported_person:
        return True
    return len(candidate.get("matched_conditions") or []) >= 2


def _not_applied_reason(candidate: Dict[str, Any], high_confidence: float) -> str:
    if _is_self_replacement_candidate(candidate):
        return "self_replacement_skipped"
    if (
        candidate["final_confidence"] < high_confidence
        and not _near_threshold_person_edge_candidate(candidate, high_confidence)
        and not _context_supported_person_candidate(candidate)
    ):
        return "below_high_confidence_threshold"
    scope_reason = _article_scope_rejection_reason(candidate)
    if scope_reason:
        return scope_reason
    return "lower_scored_overlap_candidate"


def _candidate_stays_in_article_scope(candidate: Dict[str, Any]) -> bool:
    return not _article_scope_rejection_reason(candidate)


def _article_scope_rejection_reason(candidate: Dict[str, Any]) -> str:
    original = str(candidate.get("original_text", "") or "")
    corrected = str(candidate.get("candidate_text", "") or "")
    original_tokens = _word_tokens(original)
    corrected_tokens = _word_tokens(corrected)
    if not original_tokens or not corrected_tokens:
        return "ordinary_text_not_article_proper_noun_scope"

    if candidate.get("alias_canonical_collision"):
        return "ambiguous_alias_canonical_collision"

    if _is_place_demonym_candidate(original_tokens, corrected_tokens, candidate):
        return "place_demonym_not_entity"

    if "exact_alias_match" in (candidate.get("matched_conditions") or []):
        return "" if _exact_alias_can_auto_apply(candidate) else "alias_would_degrade_canonical_match"

    conservative_reason = (
        ""
        if _context_supported_person_candidate(candidate)
        else _conservative_person_name_rejection_reason(candidate)
    )
    if conservative_reason:
        return conservative_reason

    if _article_defined_technical_term_candidate(candidate):
        return ""

    if (
        not candidate.get("entity_gate_passed")
        and not _context_supported_person_candidate(candidate)
    ):
        return str(candidate.get("entity_gate_reason") or "ordinary_text_not_article_proper_noun_scope")

    if candidate.get("existing_canonical_span"):
        return "canonical_entity_already_present_nearby"

    if len(original_tokens) == 1 and len(corrected_tokens) == 1:
        if not _single_token_candidate_stays_in_scope(original_tokens[0], corrected_tokens[0], candidate):
            return "ordinary_text_not_article_proper_noun_scope"
    return ""


def _is_place_demonym_candidate(
    original_tokens: Sequence[str],
    corrected_tokens: Sequence[str],
    candidate: Dict[str, Any],
) -> bool:
    """Keep place names separate from nationality and resident words.

    A place in an article is useful terminology, but its adjectival or plural
    demonym is ordinary sentence text. Similarity alone must not turn
    ``Americans`` into ``America``.
    """
    if len(original_tokens) != 1 or len(corrected_tokens) != 1:
        return False
    source = candidate.get("source_glossary") or {}
    source_key = str(source.get("source_key", candidate.get("source_key", "")) or "").casefold()
    category = str(source.get("category", candidate.get("category", "")) or "").casefold()
    if source_key != "places" and category not in {"place", "places", "location", "country", "city"}:
        return False
    original = _normalize_entity_gate_token(original_tokens[0])
    corrected = _normalize_entity_gate_token(corrected_tokens[0])
    if original == corrected or min(len(original), len(corrected)) < 4:
        return False
    prefix_length = len(os.path.commonprefix((original, corrected)))
    return prefix_length >= 3 and original.endswith(("an", "ans", "ian", "ians", "ese", "ish"))


def _candidate_tokens_fully_align_to_canonical(
    original_tokens: Sequence[str],
    canonical_tokens: Sequence[str],
) -> bool:
    """Accept only replacements whose complete source window maps to the entity.

    This permits structural ASR forms such as ``A Drift`` -> ``Adrift`` while
    rejecting a canonical entity followed by an ordinary word such as
    ``American Enterprise Institute details``. The caller has already applied
    the normal score threshold; this guard is solely about replacement range.
    """
    source = [_normalize_entity_gate_token(token) for token in original_tokens]
    canonical = [_normalize_entity_gate_token(token) for token in canonical_tokens]
    source = [token for token in source if token]
    canonical = [token for token in canonical if token]
    if not source or not canonical:
        return False
    if len(source) == 1 and len(canonical) == 1:
        return False

    source_index = 0
    canonical_index = 0
    while source_index < len(source) and canonical_index < len(canonical):
        if _entity_token_similarity(source[source_index], canonical[canonical_index]) >= 0.8:
            source_index += 1
            canonical_index += 1
            continue
        if (
            source_index + 1 < len(source)
            and _entity_token_similarity(
                "".join(source[source_index : source_index + 2]),
                canonical[canonical_index],
            ) >= 0.8
            and _source_tokens_contribute_to_canonical(
                source[source_index : source_index + 2],
                canonical[canonical_index],
            )
        ):
            source_index += 2
            canonical_index += 1
            continue
        if (
            canonical_index + 1 < len(canonical)
            and _entity_token_similarity(
                source[source_index],
                "".join(canonical[canonical_index : canonical_index + 2]),
            ) >= 0.8
        ):
            source_index += 1
            canonical_index += 2
            continue
        return False
    return source_index == len(source) and canonical_index == len(canonical)


def _source_tokens_contribute_to_canonical(
    source_tokens: Sequence[str], canonical_token: str
) -> bool:
    source_text = "".join(source_tokens)
    if not source_text or not canonical_token:
        return False
    matched = [False] * len(source_text)
    for block in SequenceMatcher(None, source_text, canonical_token).get_matching_blocks():
        for index in range(block.a, block.a + block.size):
            matched[index] = True
    offset = 0
    for token in source_tokens:
        token_end = offset + len(token)
        if not any(matched[offset:token_end]):
            return False
        offset = token_end
    return True


def _entity_token_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _conservative_person_name_rejection_reason(candidate: Dict[str, Any]) -> str:
    if not _candidate_is_person_name(candidate):
        return ""
    original_tokens = _word_tokens(str(candidate.get("original_text", "") or ""))
    corrected_tokens = _word_tokens(str(candidate.get("candidate_text", "") or ""))
    if not original_tokens or not corrected_tokens:
        return ""
    if len(original_tokens) < len(corrected_tokens):
        if not _single_token_is_canonical_edge(original_tokens, corrected_tokens):
            return "token_count_expansion_without_canonical_support"
    if _ambiguous_minor_person_spelling_change(original_tokens, corrected_tokens):
        return "capitalized_name_ambiguous"
    return ""


def _single_token_is_canonical_edge(
    original_tokens: Sequence[str],
    corrected_tokens: Sequence[str],
) -> bool:
    if len(original_tokens) != 1 or len(corrected_tokens) <= 1:
        return False
    original = _normalize_entity_gate_token(original_tokens[0])
    canonical_edges = {
        _normalize_entity_gate_token(corrected_tokens[0]),
        _normalize_entity_gate_token(corrected_tokens[-1]),
    }
    return bool(original) and original in canonical_edges


def _candidate_is_person_name(candidate: Dict[str, Any]) -> bool:
    source = candidate.get("source_glossary") or {}
    source_key = str(source.get("source_key", candidate.get("source_key", "")) or "").casefold()
    category = str(source.get("category", candidate.get("category", "")) or "").casefold()
    return source_key == "people" or category in {
        "analyst",
        "author",
        "historical figure",
        "person",
        "people",
        "poet",
        "writer",
    }


def _context_supported_person_candidate(candidate: Dict[str, Any]) -> bool:
    return bool(
        _candidate_is_person_name(candidate)
        and candidate.get("context_match")
        and float(candidate.get("final_confidence") or 0.0) >= 0.6
    )


def _near_threshold_person_edge_candidate(
    candidate: Dict[str, Any],
    high_confidence: float,
) -> bool:
    if not _candidate_is_person_name(candidate):
        return False
    if not _candidate_has_article_evidence(candidate):
        return False
    confidence = float(candidate.get("final_confidence") or 0.0)
    if confidence < high_confidence - 0.03:
        return False
    original_tokens = _word_tokens(str(candidate.get("original_text", "") or ""))
    corrected_tokens = _word_tokens(str(candidate.get("candidate_text", "") or ""))
    if len(original_tokens) < 2 or len(original_tokens) != len(corrected_tokens):
        return False
    if not all(_token_is_capitalized_name_piece(token) for token in original_tokens):
        return False
    original_last = _normalize_entity_gate_token(original_tokens[-1])
    corrected_last = _normalize_entity_gate_token(corrected_tokens[-1])
    if not original_last or original_last != corrected_last:
        return False
    string_similarity = float(candidate.get("string_similarity") or 0.0)
    phonetic_similarity = float(candidate.get("phonetic_similarity") or 0.0)
    same_initials = _entity_initials(original_tokens) == _entity_initials(corrected_tokens)
    return phonetic_similarity >= 0.8 or (same_initials and string_similarity >= 0.72)


def _ambiguous_minor_person_spelling_change(
    original_tokens: Sequence[str],
    corrected_tokens: Sequence[str],
) -> bool:
    if len(original_tokens) != len(corrected_tokens) or len(original_tokens) < 2:
        return False
    if _entity_initials(original_tokens) != _entity_initials(corrected_tokens):
        return False
    if not all(_token_is_capitalized_name_piece(token) for token in original_tokens + list(corrected_tokens)):
        return False
    changed = [
        (original, corrected)
        for original, corrected in zip(original_tokens, corrected_tokens)
        if _normalize_entity_gate_token(original) != _normalize_entity_gate_token(corrected)
    ]
    if len(changed) == 1:
        original, corrected = changed[0]
        return _edit_distance(
            _normalize_entity_gate_token(original),
            _normalize_entity_gate_token(corrected),
            max_distance=1,
        ) <= 1
    if len(changed) == 2:
        distances = [
            _edit_distance(
                _normalize_entity_gate_token(original),
                _normalize_entity_gate_token(corrected),
                max_distance=2,
            )
            for original, corrected in changed
        ]
        short_name_expanded = any(
            len(_normalize_entity_gate_token(original)) <= 2
            and len(_normalize_entity_gate_token(corrected)) > len(_normalize_entity_gate_token(original))
            for original, corrected in changed
        )
        return short_name_expanded and max(distances) <= 2
    return False


def _token_is_capitalized_name_piece(token: str) -> bool:
    core = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", token or "")
    core = re.sub(r"(?:'|\u2019)s$", "", core, flags=re.IGNORECASE)
    return bool(core) and core[:1].isupper() and re.search(r"[a-z]", core) is not None


def _edit_distance(left: str, right: str, *, max_distance: int = 2) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def _entity_initials(tokens: Sequence[str]) -> str:
    return "".join((token[:1] or "").casefold() for token in tokens if token)


def _exact_alias_can_auto_apply(candidate: Dict[str, Any]) -> bool:
    original = str(candidate.get("original_text", "") or "")
    corrected = str(candidate.get("candidate_text", "") or "")
    return _entity_phrase_key(original) == _entity_phrase_key(corrected)


def _entity_phrase_gate(original_text: str, canonical: str) -> Dict[str, Any]:
    original_tokens = _word_tokens(original_text)
    canonical_tokens = _word_tokens(canonical)
    if not original_tokens or not canonical_tokens:
        return _entity_gate_result(False, "empty_candidate")

    normalized_original = [
        _normalize_entity_gate_token(token) for token in original_tokens
    ]
    normalized_canonical = [
        _normalize_entity_gate_token(token) for token in canonical_tokens
    ]
    if (
        len(normalized_canonical) == 1
        and len(normalized_original) > 1
        and any(
            token in _ENTITY_BLOCKING_FUNCTION_WORDS
            for token in normalized_original
        )
        and "".join(normalized_original) != normalized_canonical[0]
    ):
        return _entity_gate_result(False, "candidate_would_merge_function_words")

    if _candidate_tokens_fully_align_to_canonical(original_tokens, canonical_tokens):
        return _entity_gate_result(True, "complete_source_window_maps_to_entity")

    if len(canonical_tokens) > len(original_tokens) + 1:
        return _entity_gate_result(False, "candidate_would_expand_short_phrase")
    if len(original_tokens) > len(canonical_tokens) + 1:
        return _entity_gate_result(False, "candidate_would_delete_common_words")
    if len(original_tokens) > len(canonical_tokens) and not all(
        _token_is_capitalized_name_piece(token) for token in original_tokens
    ):
        return _entity_gate_result(False, "candidate_would_delete_non_entity_token")

    normalized = [_normalize_entity_gate_token(token) for token in original_tokens]
    if any(token in _ENTITY_BLOCKING_FUNCTION_WORDS for token in normalized):
        return _entity_gate_result(False, "contains_function_word_or_discourse_marker")

    entity_like_count = sum(1 for token in original_tokens if _token_looks_entity_like(token))
    if len(original_tokens) == 1:
        if entity_like_count == 1:
            return _entity_gate_result(True, "single_token_entity_shape")
        return _entity_gate_result(False, "single_token_not_entity_like")

    if entity_like_count >= max(2, len(original_tokens) - 1):
        return _entity_gate_result(True, "multi_token_entity_shape")
    return _entity_gate_result(False, "multi_token_not_entity_like")


def _entity_gate_result(passed: bool, reason: str) -> Dict[str, Any]:
    return {
        "passed": passed,
        "reason": reason,
        "grammar_validation": "passed" if passed else "failed",
    }


def _normalize_entity_gate_token(token: str) -> str:
    core = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", token or "")
    core = re.sub(r"(?:'|\u2019)s$", "", core, flags=re.IGNORECASE)
    return core.casefold()


def _token_looks_entity_like(token: str) -> bool:
    core = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", token or "")
    core = re.sub(r"(?:'|\u2019)s$", "", core, flags=re.IGNORECASE)
    if not core:
        return False
    if core.casefold() in _ENTITY_BLOCKING_FUNCTION_WORDS:
        return False
    if re.search(r"[a-z][A-Z]", core):
        return True
    if re.search(r"[A-Z].*[A-Z]", core) and re.search(r"[a-z]", core):
        return True
    if core[:1].isupper() and len(core) >= 3:
        return True
    return False


def _single_token_candidate_stays_in_scope(
    original_token: str, corrected_token: str, candidate: Dict[str, Any]
) -> bool:
    compact_original = re.sub(r"(?:'|’)s$", "", original_token.casefold())
    if compact_original in _COMMON_LOWERCASE_WORD_PROTECTION:
        return False

    string_similarity = float(candidate.get("string_similarity") or 0)
    phonetic_similarity = float(candidate.get("phonetic_similarity") or 0)
    has_possessive = bool(re.search(r"(?:'|’)s$", original_token, re.IGNORECASE))
    has_inner_uppercase = bool(re.search(r"[a-z][A-Z]", original_token))
    same_initial = bool(original_token and corrected_token) and (
        original_token[0].casefold() == corrected_token[0].casefold()
    )

    if has_possessive and same_initial and phonetic_similarity >= 0.72:
        return True
    if has_inner_uppercase and phonetic_similarity >= 0.9:
        return True
    if (
        same_initial
        and _single_token_platform_candidate(candidate)
        and string_similarity >= 0.7
        and phonetic_similarity >= 0.95
    ):
        return True
    if same_initial and string_similarity >= 0.8:
        return True
    if original_token == original_token.lower() and not re.search(r"['&.-]", original_token):
        return False
    return False


def _single_token_platform_candidate(candidate: Dict[str, Any]) -> bool:
    source = candidate.get("source_glossary") or {}
    source_key = str(source.get("source_key", candidate.get("source_key", "")) or "").casefold()
    category = str(source.get("category", candidate.get("category", "")) or "").casefold()
    if source_key in {"platforms", "media_outlets"}:
        return True
    return category in {"platform", "platforms", "social media platform", "media outlet"}


_COMMON_LOWERCASE_WORD_PROTECTION = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "change",
    "changed",
    "changes",
    "changing",
    "china",
    "chinas",
    "chinese",
    "company",
    "companies",
    "consumer",
    "founder",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "list",
    "made",
    "make",
    "market",
    "of",
    "on",
    "or",
    "sell",
    "that",
    "the",
    "their",
    "they",
    "this",
    "to",
    "was",
    "were",
    "where",
    "with",
    "year",
}


_ENTITY_BLOCKING_FUNCTION_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "hers",
    "him",
    "his",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "mean",
    "might",
    "must",
    "now",
    "no",
    "not",
    "of",
    "oh",
    "on",
    "or",
    "our",
    "run",
    "she",
    "should",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "will",
    "with",
    "would",
    "yes",
    "yeah",
    "yet",
    "you",
    "your",
}


def _join_asr_words(words: Sequence[str]) -> str:
    text = " ".join(str(word or "").strip() for word in words if str(word or "").strip())
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def _word_tokens(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'&.-]*", text or "")


def _compact_text(text: str) -> str:
    return "".join(token.casefold() for token in _word_tokens(text))


def _entity_phrase_key(text: str) -> str:
    """Compare entity phrases without treating terminal punctuation as content."""
    return "".join(_normalized_entity_tokens(_word_tokens(text)))


def _phonetic_key(text: str) -> str:
    raw = _compact_text(text)
    raw = raw.replace("ph", "f")
    raw = raw.replace("ght", "t")
    raw = raw.replace("oo", "u")
    raw = raw.replace("ou", "u")
    raw = raw.replace("ee", "i")
    raw = raw.replace("ea", "i")
    raw = raw.replace("ck", "k")
    raw = raw.replace("z", "s")
    raw = re.sub(r"[aeiouy]+", "a", raw)
    raw = re.sub(r"(.)\1+", r"\1", raw)
    return raw


def _article_phrase_pattern(phrase: str) -> str:
    phrase = str(phrase or "")
    pieces = []
    index = 0
    while index < len(phrase):
        chunk = phrase[index : index + 2]
        if chunk.casefold() in {"'s", "?s"}:
            pieces.append(r"(?:'s|`s|\?s)")
            index += 2
            continue
        char = phrase[index]
        if char in {"'", "\u2019", "\u2018", "`"}:
            pieces.append(r"(?:['`])")
        elif char.isspace():
            pieces.append(r"\s+")
        else:
            pieces.append(re.escape(char))
        index += 1
    return "".join(pieces)


def _replacement_text_for_original(original_text: str, canonical: str) -> str:
    trailing_punctuation = ""
    match = re.search(r"([,.;:!?]+)$", original_text or "")
    if match and not str(canonical or "").endswith(match.group(1)):
        trailing_punctuation = match.group(1)
    possessive_pattern = r"(?:'|\u2019|\u2018|`)s\b"
    if re.search(possessive_pattern, original_text or "", re.IGNORECASE) and not re.search(
        possessive_pattern, canonical or "", re.IGNORECASE
    ):
        return f"{canonical}'s{trailing_punctuation}"
    return f"{canonical}{trailing_punctuation}"


def _remove_accidental_article_before_entity(text: str) -> str:
    # ASR may split a title such as "Adrift" into "A Drift"; after correction,
    # that can temporarily produce "A Adrift".
    return re.sub(
        r"\bA\s+(A[A-Za-z]+(?:\s+(?:and|for|from|in|of|on|the|to|with|[A-Z][A-Za-z]+)){0,8})\b",
        r"\1",
        text or "",
    )


def _correct_segment_text(
    text: str,
    glossary: Sequence[Dict[str, Any]],
    *,
    high_confidence: float,
    review_confidence: float,
) -> tuple[str, List[Dict[str, Any]]]:
    result = text or ""
    logs: List[Dict[str, Any]] = []
    for match_term in _glossary_match_terms(glossary):
        term = match_term["source"]
        canonical = str(match_term.get("canonical", "") or "").strip()
        if not canonical or not re.search(r"[A-Za-z0-9]", canonical):
            continue
        candidates = [canonical] + [str(alias) for alias in term.get("aliases", []) if str(alias).strip()]
        for candidate in candidates:
            if not candidate or candidate == canonical:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])", re.IGNORECASE)
            for match in list(pattern.finditer(result)):
                scored = _score_correction_candidate(match.group(0), match_term)
                confidence = float(scored["final_confidence"])
                replacement = scored["corrected_text"]
                if _should_apply_candidate(scored, high_confidence):
                    logs.append(
                        _replacement_log(
                            match.group(0),
                            replacement,
                            confidence,
                            "exact_alias_match",
                            term,
                            applied=True,
                            extra=scored,
                        )
                    )
                    result = result[: match.start()] + replacement + result[match.end() :]
                elif confidence >= review_confidence:
                    logs.append(
                        _replacement_log(
                            match.group(0),
                            canonical,
                            confidence,
                            _not_applied_reason(scored, high_confidence),
                            term,
                            applied=False,
                            extra=scored,
                        )
                    )

        for phrase in _candidate_phrases(result, canonical):
            if phrase.lower() == canonical.lower():
                continue
            scored = _score_correction_candidate(phrase, match_term)
            confidence = float(scored["final_confidence"])
            if _should_apply_candidate(scored, high_confidence):
                pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])")
                replacement = scored["corrected_text"]
                result, count = pattern.subn(replacement, result, count=1)
                if count:
                    logs.append(
                        _replacement_log(
                            phrase,
                            replacement,
                            confidence,
                            "high_confidence_name_similarity",
                            term,
                            applied=True,
                            extra=scored,
                        )
                    )
            elif confidence >= review_confidence:
                reason = _not_applied_reason(scored, high_confidence)
                if reason == "lower_scored_overlap_candidate":
                    reason = "low_confidence_review_only"
                logs.append(
                    _replacement_log(
                        phrase,
                        canonical,
                        confidence,
                        reason,
                        term,
                        applied=False,
                        extra=scored,
                    )
                )
    return _remove_accidental_article_before_entity(result), logs


def _candidate_phrases(text: str, canonical: str) -> List[str]:
    word_count = max(1, len(re.findall(r"[A-Za-z0-9]+", canonical)))
    tokens = list(re.finditer(r"[A-Za-z0-9][A-Za-z0-9'&.-]*", text or ""))
    phrases = []
    window_sizes = [word_count]
    if word_count >= 2:
        window_sizes = [word_count + 1, word_count]
    if word_count >= 3:
        window_sizes.append(word_count - 1)
    for window_size in window_sizes:
        for index in range(0, max(0, len(tokens) - window_size + 1)):
            phrase = text[tokens[index].start() : tokens[index + window_size - 1].end()]
            phrase_tokens = _word_tokens(phrase)
            if window_size > word_count and _phrase_has_boundary_filler(phrase_tokens, _word_tokens(canonical)):
                continue
            if len(phrase) >= max(4, len(canonical) - 2):
                phrases.append(phrase)
    return phrases


def _phrase_has_boundary_filler(tokens: Sequence[str], canonical_tokens: Sequence[str]) -> bool:
    if not tokens:
        return False
    boundary_words = {
        "a",
        "an",
        "and",
        "at",
        "based",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "the",
        "to",
        "with",
    }
    if tokens[0].casefold() in boundary_words or tokens[-1].casefold() in boundary_words:
        return True
    if not canonical_tokens:
        return True
    return not (
        _edge_token_similarity(tokens[0], canonical_tokens[0]) >= 0.55
        and _edge_token_similarity(tokens[-1], canonical_tokens[-1]) >= 0.55
    )


def _edge_token_similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None,
        _normalize_entity_gate_token(left),
        _normalize_entity_gate_token(right),
    ).ratio()


def _replacement_log(
    original: str,
    corrected: str,
    confidence: float,
    reason: str,
    term: Dict[str, Any],
    *,
    applied: bool,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = {
        "original_text": original,
        "corrected_text": corrected,
        "confidence": round(float(confidence), 4),
        "reason": reason,
        "source_glossary": {
            "canonical_name": term.get("canonical_name", ""),
            "chinese_name": term.get("chinese_name", ""),
            "category": term.get("category", ""),
            "source_key": term.get("source_key", ""),
            "aliases": term.get("aliases", []),
        },
        "applied": applied,
    }
    if extra:
        for key in (
            "string_similarity",
            "phonetic_similarity",
            "final_confidence",
            "matched_conditions",
            "article_entity_present",
            "entity_gate_passed",
            "entity_gate_reason",
            "grammar_validation",
            "original_token_count",
            "candidate_token_count",
        ):
            if key in extra:
                result[key] = extra[key]
    return result


class ArticleContextThread(QThread):
    finished = pyqtSignal(dict, dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        article_text: str,
        llm_config: ArticleLLMConfig,
        *,
        cache_manager: Optional[CacheManager] = None,
        timeout: int = 60,
        output_dir: str | Path | None = None,
    ):
        super().__init__()
        self.article_text = article_text
        self.llm_config = llm_config
        self.cache_manager = cache_manager
        self.timeout = timeout
        self.output_dir = output_dir

    def run(self):
        try:
            context = analyze_article_text(
                self.article_text,
                self.llm_config,
                cache_manager=self.cache_manager,
                timeout=self.timeout,
            )
            paths = {}
            if self.output_dir:
                paths = save_article_artifacts(self.output_dir, self.article_text, context)
            self.finished.emit(context, paths)
        except Exception as e:
            logger.warning("Article context analysis failed: %s", str(e))
            self.error.emit(str(e))
