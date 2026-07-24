import hashlib
import json
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

ARTICLE_CONTEXT_SCHEMA_VERSION = 1
ARTICLE_RAW_RESPONSE_KEY = "_raw_response"
ARTICLE_ANALYSIS_META_KEY = "_analysis_meta"
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
  "technical_terms": [],
  "numbers_and_dates": []
}

Each object in people, companies, brands, organisations, places, technical_terms, and numbers_and_dates must contain:
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


def empty_article_context() -> Dict[str, Any]:
    return {
        "schema_version": ARTICLE_CONTEXT_SCHEMA_VERSION,
        "title": "",
        "summary": "",
        "people": [],
        "companies": [],
        "brands": [],
        "organisations": [],
        "places": [],
        "technical_terms": [],
        "numbers_and_dates": [],
    }


def normalize_article_context(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return empty_article_context()
    result = empty_article_context()
    result["title"] = str(data.get("title", "") or "").strip()
    result["summary"] = str(data.get("summary", "") or "").strip()
    for key in (
        "people",
        "companies",
        "brands",
        "organisations",
        "places",
        "technical_terms",
        "numbers_and_dates",
    ):
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
    cache_key = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
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
    for key in (
        "people",
        "companies",
        "brands",
        "organisations",
        "places",
        "technical_terms",
        "numbers_and_dates",
    ):
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
    for key in (
        "people",
        "companies",
        "brands",
        "organisations",
        "places",
        "technical_terms",
        "numbers_and_dates",
    ):
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
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", re.IGNORECASE)
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
    for key in (
        "people",
        "companies",
        "brands",
        "organisations",
        "places",
        "technical_terms",
        "numbers_and_dates",
    ):
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

    corrected: List[ASRDataSeg] = []
    candidates: List[Dict[str, Any]] = []
    logs: List[Dict[str, Any]] = []
    index = 0
    max_window = min(8, max((term["max_tokens"] + 1 for term in terms), default=1))

    while index < len(segments):
        best = None
        for window_size in range(1, min(max_window, len(segments) - index) + 1):
            window = segments[index : index + window_size]
            original_text = _join_asr_words(seg.text for seg in window)
            if not re.search(r"[A-Za-z0-9]", original_text or ""):
                continue
            for term in terms:
                if window_size > term["max_tokens"] and _has_boundary_filler(window):
                    continue
                candidate = _score_correction_candidate(original_text, term)
                candidate["start_time"] = window[0].start_time
                candidate["end_time"] = window[-1].end_time
                candidate["segment_index"] = index + 1
                candidate["window_size"] = window_size
                candidate["context_match"] = False
                candidate["asr_confidence_low"] = None
                if _is_self_replacement_candidate(candidate):
                    continue
                if candidate["final_confidence"] >= review_confidence:
                    candidates.append(candidate)
                if best is None or candidate["final_confidence"] > best["final_confidence"]:
                    best = candidate

        if best and _should_apply_candidate(best, high_confidence):
            replacement = ASRDataSeg(
                best["corrected_text"],
                segments[index].start_time,
                segments[index + best["window_size"] - 1].end_time,
                segments[index].translated_text,
            )
            if hasattr(segments[index], "subtitle_id"):
                replacement.subtitle_id = getattr(segments[index], "subtitle_id")
            best["applied"] = True
            best["result"] = "replaced"
            best["reason"] = "high_confidence_article_glossary_match"
            corrected.append(replacement)
            logs.append(best)
            logger.info(
                "Article ASR correction applied: %s -> %s confidence=%.4f",
                best["original_text"],
                best["corrected_text"],
                best["final_confidence"],
            )
            index += best["window_size"]
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
        corrected.append(copied)
        index += 1

    for candidate in candidates:
        if "applied" not in candidate:
            candidate["applied"] = False
            candidate["result"] = "review_only"
            candidate["reason"] = _not_applied_reason(candidate, high_confidence)
            if candidate["final_confidence"] >= review_confidence:
                logs.append(candidate)
    return corrected, candidates, logs


def _glossary_match_terms(glossary: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    terms = []
    allowed_categories = {
        "person",
        "people",
        "company",
        "companies",
        "brand",
        "brands",
        "product",
        "products",
        "organisation",
        "organisations",
        "organization",
        "organizations",
        "place",
        "places",
        "location",
        "locations",
        "institution",
        "institutions",
        "list",
    }
    for term in glossary:
        if term.get("asr_correction_enabled") is False:
            continue
        canonical = str(term.get("canonical_name", "") or "").strip()
        if not canonical or not re.search(r"[A-Za-z0-9]", canonical):
            continue
        category = str(term.get("category", "") or "").strip().casefold()
        if category and category not in allowed_categories:
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
                "source": dict(term),
                "max_tokens": max(len(_word_tokens(variant)) for variant in variants),
            }
        )
    return terms


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


def _score_correction_candidate(original_text: str, term: Dict[str, Any]) -> Dict[str, Any]:
    original_norm = _compact_text(original_text)
    original_phone = _phonetic_key(original_text)
    canonical = term["canonical"]
    best_variant = ""
    best_string = 0.0
    best_phonetic = 0.0
    for variant in term["variants"]:
        string_similarity = SequenceMatcher(
            None, original_norm, _compact_text(variant)
        ).ratio()
        phonetic_similarity = SequenceMatcher(
            None, original_phone, _phonetic_key(variant)
        ).ratio()
        if (string_similarity, phonetic_similarity) > (best_string, best_phonetic):
            best_variant = variant
            best_string = string_similarity
            best_phonetic = phonetic_similarity
    final_confidence = max(best_string, best_phonetic * 0.98)
    conditions = ["candidate_in_article_glossary"]
    if best_variant and original_norm == _compact_text(best_variant):
        conditions.append("exact_alias_match")
    if best_string >= 0.78:
        conditions.append("spelling_similarity")
    if best_phonetic >= 0.82:
        conditions.append("phonetic_similarity")
    original_tokens = _word_tokens(original_text)
    canonical_tokens = _word_tokens(canonical)
    entity_gate = _entity_phrase_gate(original_text, canonical)
    return {
        "original_text": original_text,
        "suspicious_text": original_text,
        "corrected_text": _replacement_text_for_original(original_text, canonical),
        "candidate_text": canonical,
        "matched_variant": best_variant,
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
            "aliases": term["source"].get("aliases", []),
        },
    }


def _is_self_replacement_candidate(candidate: Dict[str, Any]) -> bool:
    original = str(candidate.get("original_text", "") or "")
    corrected = str(candidate.get("corrected_text", "") or "")
    return _surface_text_key(original) == _surface_text_key(corrected)


def _surface_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def _should_apply_candidate(candidate: Dict[str, Any], high_confidence: float) -> bool:
    if _is_self_replacement_candidate(candidate):
        return False
    if candidate["final_confidence"] < high_confidence:
        return False
    if not _candidate_stays_in_article_scope(candidate):
        return False
    return len(candidate.get("matched_conditions") or []) >= 2


def _not_applied_reason(candidate: Dict[str, Any], high_confidence: float) -> str:
    if _is_self_replacement_candidate(candidate):
        return "self_replacement_skipped"
    if candidate["final_confidence"] < high_confidence:
        return "below_high_confidence_threshold"
    if not _candidate_stays_in_article_scope(candidate):
        return "ordinary_text_not_article_proper_noun_scope"
    return "lower_scored_overlap_candidate"


def _candidate_stays_in_article_scope(candidate: Dict[str, Any]) -> bool:
    original = str(candidate.get("original_text", "") or "")
    corrected = str(candidate.get("candidate_text", "") or "")
    original_tokens = _word_tokens(original)
    corrected_tokens = _word_tokens(corrected)
    if not original_tokens or not corrected_tokens:
        return False

    if "exact_alias_match" in (candidate.get("matched_conditions") or []):
        return _exact_alias_can_auto_apply(candidate)

    if not candidate.get("entity_gate_passed"):
        return False

    if len(original_tokens) == 1 and len(corrected_tokens) == 1:
        if not _single_token_candidate_stays_in_scope(original_tokens[0], corrected_tokens[0], candidate):
            return False
    return True


def _exact_alias_can_auto_apply(candidate: Dict[str, Any]) -> bool:
    original = str(candidate.get("original_text", "") or "")
    corrected = str(candidate.get("candidate_text", "") or "")
    return _compact_text(original) == _compact_text(corrected)


def _entity_phrase_gate(original_text: str, canonical: str) -> Dict[str, Any]:
    original_tokens = _word_tokens(original_text)
    canonical_tokens = _word_tokens(canonical)
    if not original_tokens or not canonical_tokens:
        return _entity_gate_result(False, "empty_candidate")

    if len(canonical_tokens) > len(original_tokens) + 1:
        return _entity_gate_result(False, "candidate_would_expand_short_phrase")
    if len(original_tokens) > len(canonical_tokens) + 1:
        return _entity_gate_result(False, "candidate_would_delete_common_words")

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
    if same_initial and string_similarity >= 0.8:
        return True
    if original_token == original_token.lower() and not re.search(r"['&.-]", original_token):
        return False
    return False


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
    "yeah",
    "yet",
    "you",
    "your",
}


def _replacement_text_for_original(original_text: str, canonical: str) -> str:
    trailing_punctuation = ""
    match = re.search(r"([,.;:!?]+)$", original_text or "")
    if match and not str(canonical or "").endswith(match.group(1)):
        trailing_punctuation = match.group(1)
    if re.search(r"(?:'|’)s\b", original_text or "", re.IGNORECASE) and not re.search(
        r"(?:'|’)s\b", canonical or "", re.IGNORECASE
    ):
        return f"{canonical}'s{trailing_punctuation}"
    return f"{canonical}{trailing_punctuation}"


def _join_asr_words(words: Sequence[str]) -> str:
    text = " ".join(str(word or "").strip() for word in words if str(word or "").strip())
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def _word_tokens(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'&.-]*", text or "")


def _compact_text(text: str) -> str:
    return "".join(token.casefold() for token in _word_tokens(text))


def _phonetic_key(text: str) -> str:
    raw = _compact_text(text)
    raw = raw.replace("ph", "f")
    raw = raw.replace("ght", "t")
    raw = raw.replace("oo", "u")
    raw = raw.replace("ou", "u")
    raw = raw.replace("ee", "i")
    raw = raw.replace("ea", "i")
    raw = raw.replace("ck", "k")
    raw = re.sub(r"[aeiouy]+", "a", raw)
    raw = re.sub(r"(.)\1+", r"\1", raw)
    return raw


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
            if confidence >= high_confidence and _candidate_stays_in_article_scope(scored):
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
                reason = (
                    "low_confidence_review_only"
                    if _candidate_stays_in_article_scope(scored)
                    else "ordinary_text_not_article_proper_noun_scope"
                )
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
    return result, logs


def _candidate_phrases(text: str, canonical: str) -> List[str]:
    word_count = max(1, len(re.findall(r"[A-Za-z0-9]+", canonical)))
    tokens = list(re.finditer(r"[A-Za-z0-9][A-Za-z0-9'&.-]*", text or ""))
    phrases = []
    window_sizes = [word_count]
    if word_count >= 2:
        window_sizes = [word_count + 1, word_count]
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
