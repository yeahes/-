import hashlib
import json
import math
import os
import re
import builtins
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from string import Template
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from openai import OpenAI

from app.config import CACHE_PATH, RESOURCE_PATH
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.storage.cache_manager import CacheManager
from app.core.subtitle_processor.stable_pipeline_contracts import (
    FROZEN_PIPELINE_HASH_KEYS,
    FrozenPipelineSnapshot,
    stable_payload_hash,
)
from app.core.subtitle_processor.final_cue_timeline import (
    derive_final_cue_timeline,
    final_cue_timeline_artifact,
    reconcile_frozen_word_ledger,
)
from app.core.subtitle_processor.allocation_quality import (
    compare_fixed_id_allocation_candidates,
)
from app.core.subtitle_processor.stable_artifacts import (
    stable_artifact_dir,
    write_json_artifact,
    write_json_artifact_set,
)
from app.core.subtitle_processor.stable_english_boundaries import (
    finalize_stable_english_boundaries,
)
from app.core.subtitle_processor.text_metrics import (
    HARD_ENGLISH_WORD_LIMIT,
    is_allowed_discourse_overflow,
    word_count,
    word_tokens,
)
from app.core.utils import json_repair
from app.core.utils.logger import setup_logger

logger = setup_logger("screen_subtitle_editor")

DISPLAY_LEAD_IN_MS = 40
DISPLAY_TAIL_PADDING_MS = 260
DISPLAY_MIN_GAP_MS = 40
DISPLAY_MIN_DURATION_MS = 700
DISPLAY_BRIDGE_GAP_MS = 800
DISPLAY_SHORT_MERGE_MS = 700
DISPLAY_SHORT_MERGE_GAP_MS = 500
DISPLAY_SHORT_BRIDGE_GAP_MS = 2200
DISPLAY_COVERAGE_BRIDGE_MAX_MS = 800
DISPLAY_COVERAGE_WORD_PAUSE_MAX_MS = 450
COVERAGE_GAP_REPORT_MS = 1500
ABNORMAL_TIMING_GAP_MS = 1800
ABNORMAL_TIMING_CLUSTER_GAP_MS = 900
READ_MS_PER_EN_WORD = 260
CHINESE_CPS_WARNING = 9.0
# Above 9 chars/s is worth reviewing.  The 12.25 chars/s render gate gives
# fixed-width CJK counts a documented near-threshold tolerance without hiding
# sustained reading-speed overload.
CHINESE_CPS_ERROR = 12.25
ENGLISH_WPS_WARNING = 5.0
ADJACENT_ZH_DUPLICATE_SIMILARITY = 0.88
SUBTITLE_DURATION_INVALID_MS = 150
SUBTITLE_DURATION_ERROR_MS = 250
SUBTITLE_DURATION_WARNING_MS = 500
SCREEN_SUBTITLE_PROMPT_VERSION = "global-subtitle-id-v2"
SEMANTIC_ALLOCATION_PROMPT_VERSION = "semantic-allocation-v3"
SEMANTIC_FULL_TRANSLATION_PROMPT_VERSION = "semantic-full-translation-v4"
SEMANTIC_FULL_TRANSLATION_STYLE_RETRY_PROMPT_VERSION = "semantic-full-translation-style-retry-v1"
SEMANTIC_FRAGMENT_ALLOCATION_RETRY_PROMPT_VERSION = "semantic-allocation-fragment-retry-v1"
STABLE_CHINESE_CACHE_CONTRACT_VERSION = "stable-chinese-cache-v1"
FROZEN_ID_WORD_SPAN_CACHE_VERSION = "frozen-id-word-span-v1"
FIXED_ID_CHINESE_ALLOCATION_ALGORITHM_VERSION = "fixed-id-allocation-v4"
SEMANTIC_FULL_TRANSLATION_CACHE_TASK = "screen_subtitle_semantic_full_translation_v4"
SEMANTIC_FULL_TRANSLATION_STYLE_RETRY_CACHE_TASK = (
    "screen_subtitle_semantic_full_translation_style_retry_v1"
)
SEMANTIC_ALLOCATION_CACHE_TASK = "screen_subtitle_semantic_translation_allocation_v3"
SEMANTIC_ALLOCATION_RETRY_CACHE_TASK = "screen_subtitle_semantic_translation_allocation_retry_v3"
SEMANTIC_FRAGMENT_ALLOCATION_RETRY_CACHE_TASK = (
    "screen_subtitle_semantic_translation_allocation_fragment_retry_v1"
)
SEMANTIC_CHINESE_POLISH_PROMPT_VERSION = "semantic-chinese-polish-v3"
SEMANTIC_CHINESE_POLISH_CACHE_TASK = "screen_subtitle_semantic_chinese_polish_v3"
MAX_SELECTIVE_CHINESE_POLISH_GROUPS = 8
# These are visual review budgets for the 1080p bilingual templates, not
# translation or structural limits.  The existing 16-word hard contract stays
# authoritative when no grammatical visual split exists.
VISUAL_ENGLISH_WORD_SOFT_LIMIT = 12
VISUAL_ENGLISH_CHARACTER_SOFT_LIMIT = 68
# Temporal display pages are deliberately stricter than structural English
# cuts. They exist only for long cues whose spoken delivery supports two
# independently readable screens.
VISUAL_TEMPORAL_MIN_PAUSE_MS = 250
VISUAL_TEMPORAL_TERMINAL_MIN_PAUSE_MS = 120
VISUAL_TEMPORAL_MIN_DISPLAY_MS = 1100
VISUAL_TEMPORAL_MIN_MS_PER_WORD = 180
VISUAL_TEMPORAL_MIN_WORDS = 4


SCREEN_EDITOR_PROMPT = """
You are a professional bilingual video subtitle editor.

Your job is to convert raw subtitles into short bilingual on-screen subtitles for video podcasts.

# Core goal
Make subtitles similar to a human editor's "screen subtitle" version:
- Keep the original short subtitle rhythm.
- English subtitles must stay aligned with the audio.
- Do not polish, paraphrase, shorten, summarize, or rewrite the English.
- Preserve the original English wording and word order as much as possible.
- Preserve English punctuation from the source whenever possible, especially commas, periods, question marks, contractions, hyphenated terms, and decimal numbers such as 22.5.
- If an English line is too long, split the original words into shorter lines instead of rewriting them.
- Fix only obvious ASR errors when the correction is unambiguous from context. Do not guess names, platforms, places, organizations, or terms.
- If a Chinese translation is provided, improve it so it is natural and easy to read on screen.
- If the translation is empty or unusable, translate the English subtitle into ${target_language}.
- Chinese should read like concise magazine/journalistic narration: accurate, composed, explanatory, and polished, not casual livestream slang and not stiff machine translation.
- Prefer documentary, magazine, or editorial video narration style for Chinese.
- Split long subtitles mainly when the English line is too long for the screen.

# Screen subtitle rhythm
- Preserve the raw subtitle cadence by default. Do not merge just because two lines form one grammatical sentence.
- Merge only when a line is too tiny to be useful on screen or when the next/previous line is incomplete without it.
- Usually merge at most 2 adjacent source subtitles into one item.
- Prefer one compact idea per subtitle over a complete written sentence.
- The result should feel like readable bilingual video captions, not a polished article transcript.
- Do not remove discourse connectors such as "So", "Well", "But", or "Because" when they help the spoken flow.
- Preserve natural spoken markers such as "you know", "like", "well", "I mean", "actually", "basically", and "honestly" by default.
- Do not make the English cleaner or more written by deleting natural spoken markers. English-learning subtitles should remain close to the audio.
- For the English field, your safest action is to copy original words and only change line breaks.

# Filler and backchannel handling
- Preserve spoken backchannels by default; remove only clearly empty or duplicated content.

# Very important
Do NOT create paragraph-like long subtitles.
Do NOT summarize.
Do NOT add new facts.
Do NOT remove meaningful content.
Do NOT change the order.
Do NOT remove punctuation or convert decimal numbers such as 22.5 into 22 5.
Do NOT rewrite English into a shorter new sentence just to meet the word limit. Split it instead.
Do not remove "you know", "like", "well", "I mean", "actually", "basically", or "honestly" just to make the sentence cleaner.

# Length style
- English length is the main visual constraint. Most English subtitles should be 6-12 words, with 13-16 acceptable when it preserves a natural phrase or spoken beat.
- Chinese length is secondary. Make Chinese natural and compact, but do not split only because the Chinese line is long.
- Soft upper limits: English ${max_english_words} words, Chinese ${max_cjk_chars} Chinese characters.
- Treat ${max_english_words} English words as the hard maximum. Do not exceed it. Still, do not cut mechanically at the number; first choose a natural semantic, prepositional, contrastive, or clause boundary.
- You may exceed the Chinese limit when the English line is already short and splitting would make timing or meaning worse.
- Avoid leaving useless one-word tails alone; the program will also merge common dangling tails deterministically.

# Cutting logic
Prefer audio/intonation-like boundaries implied by punctuation, discourse markers, and meaning.
If there is no obvious boundary but the English line is long, force a cut at a readable semantic boundary:
- after time/place phrases
- before/after because, but, so, which, when, where, and similar markers
- around appositives and examples
- after complete subject-verb-object units
Do not force a cut for Chinese length alone.
If an English item is longer than ${max_english_words} words, split it into multiple items using the exact original words.
Do not split fixed phrases if another natural cut can keep every item within ${max_english_words} words.
Do not merge two complete English sentences into one item when the result becomes visually heavy.
Do not keep a long English item just because the source segment is long; split that source_id into multiple output items.

# Output format
Return pure JSON only:
{
  "items": [
    {
      "source_ids": [1, 2],
      "word_start": 120,
      "word_end": 130,
      "translated": "edited Chinese subtitle"
    }
  ]
}

source_ids must list the original subtitle numbers used by this item.
If you split one original subtitle into multiple items, repeat the same source_id in multiple items.
If you merge adjacent subtitles, include all source ids.
Choose word_start/word_end as the inclusive source word range for this item.
Do not return the English original field when word_start/word_end are available; the program will restore it locally from the word range.
Only return an "original" field when word indexes are unavailable for that source item. In that fallback case, copy exact source words and do not rewrite, shorten, polish, or paraphrase them.
Do not invent word indexes. The range must stay inside the provided source_ids.
"""

SEMANTIC_SUBTITLE_TRANSLATION_PROMPT = """
You are a professional English-to-Simplified-Chinese subtitle translator.

Translate for bilingual English-learning video subtitles.

Workflow:
1. Understand each full English sense group first.
2. Translate the meaning into natural Simplified Chinese.
3. Project that Chinese meaning back to the provided short English subtitle parts.

Rules:
- Do not change, summarize, omit, or reorder the English parts.
- Return one translation object for every subtitle_parts item.
- Keep exactly the same subtitle_id set as subtitle_parts.
- Chinese should sound like polished magazine/documentary narration.
- Avoid word-for-word English sentence shape.
- Preserve facts, negation, contrast, condition, numbers, names, modality, and speaker stance.
- Do not reveal information in an earlier part before the corresponding English part is spoken.
- Keep Chinese concise enough for on-screen subtitles.
- If a part is only a connector or incomplete fragment, translate it naturally according to the full sense group.

Return pure JSON only:
{
  "groups": [
    {
      "id": 1,
      "full_translation": "natural complete Chinese meaning",
      "part_translations": [
        {"subtitle_id": "S0001", "zh": "Chinese for part 1"},
        {"subtitle_id": "S0002", "zh": "Chinese for part 2"}
      ]
    }
  ]
}
"""

SEMANTIC_FULL_TRANSLATION_PROMPT = """
You are a professional English-to-Simplified-Chinese translator for bilingual English-learning video subtitles.

Task:
Translate each full English sense group into one complete, accurate, natural Simplified Chinese translation.

Rules:
- Translate the complete meaning, not the English word order.
- Use polished magazine/documentary/finance explainer narration.
- First identify the Chinese main subject, predicate, object, and logical relation; then write Chinese in that order.
- Rebuild English post-modifiers, relative clauses, and delayed predicates into normal Chinese assertions.
- A sentence led by a reporting verb such as "发现、表明、显示、指出" must complete what was found or shown. Do not leave a chained noun phrase in place of the main assertion.
- Keep facts, numbers, names, negation, contrast, conditions, modality, and speaker stance.
- Avoid stiff translationese and overly literal English sentence shape.
- Default to Chinese commas, full stops, colons, semicolons, or parentheses to organize a sentence.
- Do not use em dashes for ordinary explanations, examples, appositives, causes, or results.
- Use an em dash only for a clear spoken interruption, abrupt turn, or emphasis that cannot read naturally another way.
- Never leave an em dash at the beginning or end of a translation.
- Do not compress aggressively in this stage.
- Do not split into subtitle lines in this stage.

Return pure JSON only:
{
  "groups": [
    {
      "id": 1,
      "full_translation": "完整自然中文"
    }
  ]
}
"""

SEMANTIC_TRANSLATION_ALLOCATION_PROMPT = """
You are assigning a completed Chinese translation back to fixed English subtitle parts.

Version: semantic-allocation-v3

Task:
Given a full English sense group, its completed Chinese translation, and fixed subtitle parts, write one concise Chinese subtitle for each part.

Rules:
- Return one translation object for every subtitle_parts item.
- Keep exactly the same subtitle_id set as subtitle_parts.
- Do not change, omit, summarize, or reorder the English parts.
- Do not move information earlier than when the corresponding English part is spoken.
- Use the full_translation as the authority for Chinese wording and style.
- Treat full_translation as authoritative. Do not retranslate or rewrite the whole group from English.
- Split and lightly adapt only the provided full_translation so the concatenated part_translations preserve it.
- Keep each entity, number, negation, contrast marker, and core action near the subtitle_id where its English anchor appears.
- Do not duplicate the same core Chinese information in adjacent subtitle_ids.
- Do not leave obvious dangling Chinese fragments unless the English part itself is an incomplete fragment.
- Compress only enough for on-screen reading.
- Prefer natural Chinese video subtitle phrasing over word-for-word alignment.
- Preserve facts, numbers, names, negation, contrast, conditions, modality, and speaker stance.
- If a part is an incomplete English fragment, make the Chinese fragment natural in context.
- When an English subject receives its predicate in a later part, keep the Chinese subject-predicate relation readable across those parts. Add a minimal pronoun or connective when needed; do not copy English modifier order.
- Every subtitle_parts item includes target_zh_chars and absolute_max_zh_chars derived from its display duration. Treat target_zh_chars as a preferred reading budget, not a reason to omit meaning. If one part is too short, distribute the same completed Chinese meaning naturally across adjacent IDs in the same group.
- For comparisons, lists, and source attributions, rebuild the Chinese sentence first. Do not leave the final subtitle part as a bare list of publications, dates, or nouns without the comparison/action that governs it.

Return pure JSON only:
{
  "groups": [
    {
      "id": 1,
      "allocation_prompt_version": "semantic-allocation-v3",
      "part_translations": [
        {"subtitle_id": "S0001", "zh": "中文字幕1"},
        {"subtitle_id": "S0002", "zh": "中文字幕2"}
      ]
    }
  ]
}
"""

SEMANTIC_FULL_TRANSLATION_STYLE_RETRY_PROMPT = """
You are revising one completed Simplified Chinese translation for a bilingual video subtitle sense group.

Return a complete, accurate, natural replacement translation for each supplied group.

Hard rules:
- Preserve every fact, number, name, negation, contrast, condition, modality, and speaker stance from current_translation.
- Do not add facts or remove information.
- Keep concise magazine/documentary/finance explainer narration.
- Do not use em dashes for ordinary explanations, examples, appositives, causes, or results.
- Never begin or end the translation with an em dash.
- Prefer commas, full stops, colons, semicolons, or parentheses when they read naturally.

Return pure JSON only:
{
  "groups": [
    {
      "id": 1,
      "full_translation": "完整自然中文"
    }
  ]
}
"""

SEMANTIC_FRAGMENT_ALLOCATION_RETRY_PROMPT = """
You are repairing a failed fixed-ID Chinese subtitle allocation.

Return a complete replacement allocation only for the supplied semantic group.
The English subtitle IDs, order, timing, and word ownership are immutable.
Use full_translation as the authority; redistribute it only among the existing
subtitle_ids and do not move later information earlier than its English anchor.

The previous allocation contains a Chinese grammatical fragment. Every final
subtitle part must be independently readable when its English part is complete.
Do not end the final part with a bare modifier, possessive marker, place/name
modifier, or connective that lacks the noun or predicate it governs.
For a non-final English fragment, a Chinese continuation is allowed only when
the following existing subtitle_id completes that exact phrase naturally.

Preserve names, numbers, negation, contrast, conditions, modality, and core
actions. Return exactly the supplied subtitle_id set and no other IDs.

Return pure JSON only:
{"groups":[{"id":1,"part_translations":[{"subtitle_id":"S0001","zh":"中文字幕1"}]}]}
"""

SEMANTIC_CHINESE_POLISH_PROMPT = """
You are polishing fixed Simplified Chinese bilingual video subtitles.

For each supplied high-risk sense group, improve only the existing Chinese part_translations so they read as natural, concise magazine or documentary narration.

Hard rules:
- English, subtitle IDs, order, timing and subtitle count are immutable.
- Use full_translation as the authority for meaning. English only locates where meaning is spoken.
- Return exactly the same subtitle_id set for every group.
- Keep names, numbers, negation, contrast, causality, modality and core actions.
- Keep information near its English anchor. Do not move later information earlier.
- Redistribute Chinese only inside the same sense group.
- Keep current wording unchanged if it is already natural.
- Do not make text more literary at the cost of accuracy or clarity.
- Do not leave dangling clauses or split Chinese grammar unnaturally.

Return pure JSON only:
{"groups":[{"id":1,"part_translations":[{"subtitle_id":"S0001","zh":"中文字幕1"}]}]}
"""


@dataclass
class ScreenSubtitleItem:
    source_ids: List[int]
    original: str
    translated: str
    word_start: Optional[int] = None
    word_end: Optional[int] = None
    subtitle_id: Optional[str] = None


@dataclass
class AllocationBatchResult:
    batch_id: int
    expected_ids: List[int]
    translations: Dict[int, Dict[str, str]]
    complete: bool
    data: Optional[object]
    elapsed_seconds: float
    errors: List[Dict]
    debug: List[Dict]
    error_message: str = ""
    cache_hit: bool = False


class ScreenSubtitleEditor:
    """LLM-assisted editor for short bilingual on-screen subtitles."""

    EN_FILLER_RE = re.compile(
        r"^(?:right|yeah|yes|yep|exactly|definitely|okay|ok|sure|wow|jeez|ah|oh|mm|hmm)[.!?。？！…]*$",
        re.IGNORECASE,
    )
    ZH_FILLER_RE = re.compile(
        r"^(?:对|对的|没错|是的|当然|好吧|好的|嗯|啊|哦|哇|天哪|确实|没问题)[。.!！?？…]*$"
    )
    EN_LEADING_FILLER_RE = re.compile(
        r"^(?:right|yeah|yes|yep|exactly|definitely|okay|ok|sure|ah|oh)[,，.!。…\s]+",
        re.IGNORECASE,
    )
    ZH_LEADING_FILLER_RE = re.compile(
        r"^(?:对|对的|没错|是的|当然|好吧|好的|嗯|啊|哦|确实)[,，。.!！…\s]+"
    )

    def __init__(
        self,
        model: str,
        target_language: str = "简体中文",
        max_cjk_chars: int = 24,
        max_english_words: int = 16,
        batch_num: int = 24,
        thread_num: int = 4,
        temperature: float = 0.0,
        timeout: int = 90,
        enable_stable_mode: bool = True,
        enable_quality_check: bool = False,
        coverage_report_path: Optional[str] = None,
        article_context_prompt: str = "",
        update_callback: Optional[Callable[[Dict], None]] = None,
        progress_callback: Optional[Callable[[Dict], None]] = None,
        enable_safe_auto_repair: bool = False,
        enable_chinese_polish: bool = False,
        preserve_aligned_timing: bool = False,
        allocation_max_concurrency: int = 1,
        allocation_batch_size: int = 16,
    ):
        self.model = model
        self.target_language = target_language
        self.max_cjk_chars = max_cjk_chars
        self.max_english_words = max(HARD_ENGLISH_WORD_LIMIT, int(max_english_words or HARD_ENGLISH_WORD_LIMIT))
        self.batch_num = batch_num
        self.thread_num = thread_num
        self.temperature = temperature
        self.timeout = timeout
        self.enable_stable_mode = enable_stable_mode
        self.enable_quality_check = enable_quality_check
        self.coverage_report_path = coverage_report_path
        self.article_context_prompt = (article_context_prompt or "").strip()
        self.update_callback = update_callback
        self.progress_callback = progress_callback
        self.enable_safe_auto_repair = bool(enable_safe_auto_repair)
        self.enable_chinese_polish = bool(enable_chinese_polish)
        self.preserve_aligned_timing = bool(preserve_aligned_timing)
        self.allocation_max_concurrency = max(1, int(allocation_max_concurrency or 1))
        self.allocation_batch_size = min(24, max(1, int(allocation_batch_size or 16)))
        self.cache_manager = CacheManager(str(CACHE_PATH))
        self.client = self._init_client()
        self._active_word_entries: List[Dict] = []
        self._active_source_word_spans: Dict[int, tuple[int, int]] = {}
        self._active_source_segments_by_id: Dict[int, ASRDataSeg] = {}
        self._syntax_protected_cuts: set[tuple[int, int]] = set()
        self._syntax_hard_cut_issues: Dict[tuple[int, int], List[str]] = {}
        self._syntax_nlp = None
        self._last_semantic_full_translations: Dict[int, str] = {}
        self._last_semantic_group_audit_contexts: Dict[str, Dict] = {}
        self._last_semantic_group_id_by_subtitle_id: Dict[str, str] = {}
        self._last_semantic_groups: List[Dict] = []
        self._last_subtitle_items: List[ScreenSubtitleItem] = []
        self._discourse_marker_orphans: List[Dict] = []
        self._frozen_subtitle_ids: List[str] = []
        self._translation_structure_errors: List[Dict] = []
        self._last_llm_raw_returns: List[Dict] = []
        self._last_semantic_group_debug: List[Dict] = []
        self._last_allocation_inputs: List[Dict] = []
        self._last_allocation_raw_returns: List[Dict] = []
        self._last_allocation_validation: List[Dict] = []
        self._last_allocation_retry_log: List[Dict] = []
        self._last_allocation_final: List[Dict] = []
        self._last_allocation_unresolved: List[Dict] = []
        self._last_full_translation_style_retry_log: List[Dict] = []
        self._llm_cache_stats: Dict[str, Dict[str, int]] = {}
        self._allocation_runtime_stats: Dict[str, Any] = {}
        self._llm_cache_used: bool = False
        self._chinese_cache_contract: Dict[str, str] = {}
        self._boundary_snapshots: List[Dict] = []
        self._boundary_snapshot_changes: List[Dict] = []
        self._boundary_snapshot_item_sets: Dict[str, List[ScreenSubtitleItem]] = {}
        self._pre_id_boundary_repairs: List[Dict] = []
        self._allocation_isolation_before: Dict = {}
        self._allocation_isolation_after: Dict = {}
        self._allocation_isolation_report: Dict = {}
        self._safe_auto_repair_log: List[Dict] = []
        self._safe_auto_repair_candidates: List[Dict] = []
        self._display_coverage_repairs: List[Dict] = []
        self._display_coverage_unresolved: List[Dict] = []
        self._chinese_polish_log: List[Dict] = []
        self._qa_review_points_path: str = ""
        self._qa_review_points_count: int = 0
        self._final_cue_timeline: Dict[str, Any] = {}
        self._final_cue_timeline_seed_errors: List[Dict[str, Any]] = []
        self._final_cue_timeline_path: str = ""
        self._final_word_timing_reconciliations: List[Dict[str, Any]] = []
        self._final_timeline_alignment: Dict[str, Any] = {}
        self.last_validation_summary: Optional[Dict] = None

    def _compose_prompt(self, base_prompt: str) -> str:
        if not self.article_context_prompt:
            return base_prompt
        return f"{base_prompt}\n\n{self.article_context_prompt}"

    def _emit_progress_event(self, phase: str, **details: Any) -> None:
        """Report main-thread pipeline progress without mutating subtitle data."""
        callback = getattr(self, "progress_callback", None)
        if callback is None:
            return
        try:
            callback({"phase": phase, **details})
        except Exception as exc:
            logger.debug("Screen subtitle progress callback failed: %s", exc)

    @staticmethod
    def _init_client() -> OpenAI:
        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY")
        if not (base_url and api_key):
            raise ValueError("环境变量 OPENAI_BASE_URL 和 OPENAI_API_KEY 必须设置")
        return OpenAI(base_url=base_url, api_key=api_key)

    def edit(self, asr_data: ASRData, word_time_asr_data: Optional[ASRData] = None) -> ASRData:
        if not asr_data.segments:
            return asr_data

        has_word_ledger = bool(
            word_time_asr_data and word_time_asr_data.is_word_timestamp()
        )
        if self.enable_stable_mode:
            if not has_word_ledger:
                raise RuntimeError(
                    "稳定上屏模式需要完整词级账本，不能回退到旧 LLM 上屏编辑路径。"
                )
            self._active_word_entries = self._word_time_entries(word_time_asr_data.segments)
            self._active_source_word_spans = self._map_source_segments_to_word_entries(
                asr_data.segments, self._active_word_entries
            )
            if len(self._active_source_word_spans) != len(asr_data.segments):
                raise RuntimeError(
                    "稳定上屏模式需要完整词级账本源映射，不能回退到旧 LLM 上屏编辑路径。"
                )
            return self._edit_stable_word_timed(asr_data)
        if has_word_ledger:
            self._active_word_entries = self._word_time_entries(word_time_asr_data.segments)
            self._active_source_word_spans = self._map_source_segments_to_word_entries(
                asr_data.segments, self._active_word_entries
            )
        else:
            self._active_word_entries = []
            self._active_source_word_spans = {}

        chunks = self._chunk_segments(asr_data.segments)
        edited_by_index: Dict[int, List[ASRDataSeg]] = {}
        completed = 0
        max_workers = max(1, min(self.thread_num, len(chunks)))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._edit_chunk, chunk): (chunk_index, chunk)
                for chunk_index, chunk in enumerate(chunks, 1)
            }

            for future in as_completed(futures):
                chunk_index, chunk = futures[future]
                try:
                    items = future.result()
                except Exception as e:
                    logger.error("上屏字幕整理失败，保留原字幕块：%s", str(e))
                    items = [
                        ScreenSubtitleItem([idx], seg.text, seg.translated_text)
                        for idx, seg in chunk
                    ]
                edited_segments = self._items_to_segments(items, chunk)
                edited_by_index[chunk_index] = edited_segments
                completed += 1
                logger.info(
                    "[+]上屏字幕整理完成：%s/%s (%s - %s)",
                    completed,
                    len(chunks),
                    chunk[0][0],
                    chunk[-1][0],
                )
                if self.update_callback and edited_segments:
                    self.update_callback(
                        {
                            str(chunk[-1][0]): {
                                "original_subtitle": edited_segments[-1].text,
                                "translated_subtitle": edited_segments[
                                    -1
                                ].translated_text,
                            }
                        }
                    )

        edited_segments = []
        for chunk_index in sorted(edited_by_index):
            edited_segments.extend(edited_by_index[chunk_index])

        edited_segments = self._repair_global_segments(edited_segments)
        edited_segments = self._translate_missing_segments(edited_segments)
        edited_segments = self._align_segment_translation_punctuation(edited_segments)
        if word_time_asr_data and word_time_asr_data.is_word_timestamp():
            edited_segments = self._realign_segments_to_word_times(
                edited_segments, word_time_asr_data.segments
            )
            self._report_subtitle_coverage_gaps(asr_data.segments, edited_segments)
            edited_segments = self._apply_display_timing_padding(edited_segments)
            return ASRData(edited_segments)

        edited_data = ASRData(edited_segments).optimize_timing()
        self._report_subtitle_coverage_gaps(asr_data.segments, edited_data.segments)
        edited_data.segments = self._apply_display_timing_padding(edited_data.segments)
        return edited_data

    def _edit_stable_word_timed(self, asr_data: ASRData) -> ASRData:
        logger.info("Screen subtitle stable mode: local English cutting, LLM Chinese only")
        self._translation_structure_errors = []
        self._last_llm_raw_returns = []
        self._last_semantic_group_debug = []
        self._last_allocation_inputs = []
        self._last_allocation_raw_returns = []
        self._last_allocation_validation = []
        self._last_allocation_retry_log = []
        self._last_allocation_final = []
        self._last_allocation_unresolved = []
        self._last_full_translation_style_retry_log = []
        self._last_semantic_full_translations = {}
        self._last_semantic_group_audit_contexts = {}
        self._last_semantic_group_id_by_subtitle_id = {}
        self._last_semantic_groups = []
        self._last_subtitle_items = []
        self._discourse_marker_orphans = []
        self._boundary_snapshots = []
        self._boundary_snapshot_changes = []
        self._boundary_snapshot_item_sets = {}
        self._pre_id_boundary_repairs = []
        self._allocation_isolation_before = {}
        self._allocation_isolation_after = {}
        self._allocation_isolation_report = {}
        self._safe_auto_repair_log = []
        self._safe_auto_repair_candidates = []
        self._display_coverage_repairs = []
        self._display_coverage_unresolved = []
        self._chinese_polish_log = []
        self._llm_cache_stats = {}
        self._allocation_runtime_stats = {}
        self._chinese_cache_contract = {}
        self._final_cue_timeline = {}
        self._final_cue_timeline_seed_errors = []
        self._final_cue_timeline_path = ""
        self._final_word_timing_reconciliations = []
        self._final_timeline_alignment = {}
        self._active_source_segments_by_id = {
            index: seg for index, seg in enumerate(asr_data.segments, 1)
        }
        self._llm_cache_used = False
        self._emit_progress_event("english_boundaries", completed=0, total=1)
        items = self._finalize_stable_english_boundaries(asr_data.segments)
        items = self._assign_global_subtitle_ids(items)
        semantic_groups = self._semantic_translation_groups(items)
        self._emit_progress_event(
            "english_boundaries",
            completed=1,
            total=1,
            subtitle_count=len(items),
            semantic_group_count=len(semantic_groups),
        )
        self._last_semantic_groups = list(semantic_groups)
        self._last_subtitle_items = list(items)
        items = self._translate_semantic_subtitle_groups(items)
        self._last_subtitle_items = list(items)
        self._validate_final_item_translation_ids(items)
        items = self._validate_stable_items(items)
        segments = self._items_to_segments(
            items, list(enumerate(asr_data.segments, 1))
        )
        # Stable mode must not silently replace a missing ID-bound allocation
        # with a free single-line translation.  The ID validator below turns
        # that condition into a structural failure instead.
        segments = self._align_segment_translation_punctuation(segments)
        segments = self._repair_blocking_subtitle_issues(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=items,
        )
        if not self.preserve_aligned_timing:
            segments = self._repair_abnormal_timing_gaps(segments)
        segments = self._order_segments_by_frozen_subtitle_ids(segments)
        self._validate_final_segment_translation_ids(segments)
        self._allocation_isolation_after = self._allocation_isolation_snapshot(
            stage="before_export",
            source_segments=asr_data.segments,
            items=items,
            semantic_groups=semantic_groups,
            full_translations=self._last_semantic_full_translations,
            final_segments=segments,
        )
        self._allocation_isolation_report = self._build_allocation_isolation_report(
            self._allocation_isolation_before,
            self._allocation_isolation_after,
        )
        self._write_stable_pipeline_artifacts(
            source_segments=asr_data.segments,
            semantic_groups=semantic_groups,
            subtitle_items=items,
            final_segments=segments,
        )
        self._report_subtitle_coverage_gaps(asr_data.segments, segments)
        self._emit_progress_event("finalization", completed=1, total=1)
        return ASRData(segments)

    def _finalize_stable_english_boundaries(
        self, source_segments: Sequence[ASRDataSeg]
    ) -> List[ScreenSubtitleItem]:
        """Build the frozen language-owned English boundary set before IDs.

        Presentation templates receive the resulting cues and may wrap or scale
        their text, but they must not create or move subtitle boundaries.  This
        keeps the English, semantic groups, Chinese allocation, and manifest
        independent from the selected video template.
        """
        return finalize_stable_english_boundaries(
            source_segments,
            run_stage=lambda stage, items: getattr(self, stage)(items),
            capture_snapshot=lambda stage, items, changed_by, previous_items: self._capture_boundary_snapshot(
                stage,
                items,
                changed_by=changed_by,
                previous_items=previous_items,
            ),
            previous_snapshot_items=self._boundary_snapshot_items,
        )

    def repair_after_final_time_alignment(
        self,
        asr_data: ASRData,
        *,
        preserve_aligned_timing: Optional[bool] = None,
    ) -> ASRData:
        """Final local pass after WhisperX/frozen time mapping.

        English text, subtitle IDs and segment order are frozen at this point.
        Chinese post-processing is allowed, while a forced-alignment backend
        keeps ownership of cue timing.
        """
        if not asr_data or not asr_data.segments:
            return asr_data
        preserve_timing = (
            getattr(self, "preserve_aligned_timing", False)
            if preserve_aligned_timing is None
            else bool(preserve_aligned_timing)
        )
        before = list(asr_data.segments)
        # A forced-alignment backend owns the final cue boundaries.  Chinese
        # post-processing remains allowed, but it must never move cue times.
        segments = list(before) if preserve_timing else self._repair_final_short_subtitle_timings(before)
        segments = self._compress_fast_chinese_segments(
            segments,
            semantic_groups=getattr(self, "_last_semantic_groups", []) or None,
            subtitle_items=getattr(self, "_last_subtitle_items", []) or None,
        )
        segments = self._align_segment_translation_punctuation(segments)
        asr_data.segments = list(segments)
        source_map = getattr(self, "_active_source_segments_by_id", {}) or {}
        source_segments = list(source_map.values()) if isinstance(source_map, dict) else list(source_map)
        segments = self._reconcile_final_display_coverage(segments, source_segments)
        asr_data.segments = list(segments)
        self.refresh_final_cue_timeline_artifact(asr_data.segments)
        if source_segments:
            self._report_subtitle_coverage_gaps(source_segments, asr_data.segments)
        else:
            self._write_coverage_report([], self._translation_gaps(asr_data.segments), asr_data.segments)
        self._write_stable_pipeline_artifacts(
            source_segments=source_segments,
            semantic_groups=getattr(self, "_last_semantic_groups", []) or [],
            subtitle_items=getattr(self, "_last_subtitle_items", []) or [],
            final_segments=asr_data.segments,
        )
        return asr_data

    def _repair_final_short_subtitle_timings(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        if not segments:
            return []
        repaired = self._apply_display_timing_padding(segments)
        repaired = self._shift_next_for_loaded_short_final_segments(repaired)
        # Retained for direct legacy callers only; the current pipeline no longer enables it.
        if getattr(self, "enable_safe_auto_repair", False):
            repaired = self._repair_high_load_short_subtitle_timings(repaired)
        fixed = 0
        for old, new in zip(segments, repaired):
            if int(new.end_time) - int(new.start_time) > int(old.end_time) - int(old.start_time):
                fixed += 1
        if fixed:
            logger.info("最终时间轴短字幕补时: %s", fixed)
        return repaired

    def _reconcile_final_display_coverage(
        self,
        segments: Sequence[ASRDataSeg],
        source_segments: Sequence[ASRDataSeg],
    ) -> List[ASRDataSeg]:
        """Bridge only short, continuous speech gaps after final timing is frozen.

        The stable source spans are the available speech envelope at this
        stage.  A gap is eligible only when it stays inside one source span
        and the adjacent frozen word ranges have no meaningful pause.  The
        cue texts, IDs, word ranges, and ordering remain untouched.
        """
        result = [self._copy_segment(segment) for segment in segments]
        if len(result) < 2 or not source_segments:
            return result

        raw_source_intervals = sorted(
            (max(0, int(source.start_time)), max(int(source.end_time), int(source.start_time)))
            for source in source_segments
            if (source.text or "").strip() and int(source.end_time) > int(source.start_time)
        )
        source_intervals: List[tuple[int, int]] = []
        for start_ms, end_ms in raw_source_intervals:
            if (
                source_intervals
                and start_ms - source_intervals[-1][1] <= DISPLAY_COVERAGE_WORD_PAUSE_MAX_MS
            ):
                source_intervals[-1] = (source_intervals[-1][0], max(source_intervals[-1][1], end_ms))
            else:
                source_intervals.append((start_ms, end_ms))
        if not source_intervals:
            return result

        repairs = getattr(self, "_display_coverage_repairs", [])
        unresolved = getattr(self, "_display_coverage_unresolved", [])
        for index in range(len(result) - 1):
            previous = result[index]
            current = result[index + 1]
            gap_start = max(0, int(previous.end_time))
            gap_end = max(gap_start, int(current.start_time))
            gap_ms = gap_end - gap_start
            if gap_ms <= 0 or not self._source_interval_contains(source_intervals, gap_start, gap_end):
                continue

            evidence = self._display_coverage_bridge_evidence(previous, current)
            if gap_ms > DISPLAY_COVERAGE_BRIDGE_MAX_MS:
                unresolved.append(
                    self._display_coverage_gap_record(
                        previous,
                        current,
                        gap_start,
                        gap_end,
                        evidence,
                        "gap_exceeds_auto_repair_limit",
                    )
                )
                continue
            if not evidence["continuous"]:
                unresolved.append(
                    self._display_coverage_gap_record(
                        previous,
                        current,
                        gap_start,
                        gap_end,
                        evidence,
                        str(evidence["reason"]),
                    )
                )
                continue

            boundary = gap_start + gap_ms // 2
            before_previous_end = int(previous.end_time)
            before_current_start = int(current.start_time)
            result[index] = self._copy_segment(previous, end_time=boundary)
            result[index + 1] = self._copy_segment(current, start_time=boundary)
            repairs.append(
                {
                    "code": "continuous_source_coverage_bridge",
                    "left_subtitle_id": self._segment_subtitle_id(previous, index + 1),
                    "right_subtitle_id": self._segment_subtitle_id(current, index + 2),
                    "gap_start_ms": gap_start,
                    "gap_end_ms": gap_end,
                    "gap_ms": gap_ms,
                    "old_left_end_ms": before_previous_end,
                    "old_right_start_ms": before_current_start,
                    "new_boundary_ms": boundary,
                    "word_pause_ms": evidence["word_pause_ms"],
                    "left_english": previous.text,
                    "right_english": current.text,
                }
            )

        self._display_coverage_repairs = repairs
        self._display_coverage_unresolved = unresolved
        if repairs:
            logger.info("Final subtitle display coverage bridges applied: %s", len(repairs))
        if unresolved:
            logger.warning("Final subtitle display coverage gaps left unresolved: %s", len(unresolved))
        return result

    @staticmethod
    def _source_interval_contains(
        intervals: Sequence[tuple[int, int]],
        start_ms: int,
        end_ms: int,
    ) -> bool:
        return any(start <= start_ms and end >= end_ms for start, end in intervals)

    @staticmethod
    def _display_coverage_bridge_evidence(
        previous: ASRDataSeg,
        current: ASRDataSeg,
    ) -> Dict[str, Any]:
        previous_word_end = getattr(previous, "stable_word_end_ms", None)
        current_word_start = getattr(current, "stable_word_start_ms", None)
        if previous_word_end is None or current_word_start is None:
            return {
                "continuous": False,
                "reason": "missing_frozen_word_anchor",
                "word_pause_ms": None,
            }
        word_pause_ms = int(current_word_start) - int(previous_word_end)
        if word_pause_ms > DISPLAY_COVERAGE_WORD_PAUSE_MAX_MS:
            return {
                "continuous": False,
                "reason": "frozen_word_pause_exceeds_limit",
                "word_pause_ms": word_pause_ms,
            }
        return {
            "continuous": True,
            "reason": "continuous_frozen_word_ranges",
            "word_pause_ms": word_pause_ms,
        }

    def _display_coverage_gap_record(
        self,
        previous: ASRDataSeg,
        current: ASRDataSeg,
        gap_start: int,
        gap_end: int,
        evidence: Dict[str, Any],
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "code": "display_coverage_gap_unresolved",
            "reason": reason,
            "left_subtitle_id": self._segment_subtitle_id(previous, 0),
            "right_subtitle_id": self._segment_subtitle_id(current, 0),
            "gap_start_ms": gap_start,
            "gap_end_ms": gap_end,
            "gap_ms": gap_end - gap_start,
            "word_pause_ms": evidence.get("word_pause_ms"),
            "left_english": previous.text,
            "right_english": current.text,
        }

    def _shift_next_for_loaded_short_final_segments(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        result = list(segments)
        if len(result) < 2:
            return result
        shifted = 0
        for index in range(len(result) - 1):
            seg = result[index]
            nxt = result[index + 1]
            start = max(0, int(seg.start_time))
            end = max(start + 1, int(seg.end_time))
            duration_ms = end - start
            if duration_ms >= DISPLAY_MIN_DURATION_MS:
                continue
            original = self._normalize_text(seg.text)
            translated = self._normalize_text(seg.translated_text)
            if self._is_simple_short_response(original, translated):
                continue
            text_load = self._word_count(original) + len(re.findall(r"[\u4e00-\u9fff]", translated))
            if text_load <= 4:
                continue
            target_end = start + DISPLAY_MIN_DURATION_MS
            if target_end <= end:
                continue
            next_end = max(int(nxt.end_time), int(nxt.start_time) + 1)
            shifted_next_start = target_end + DISPLAY_MIN_GAP_MS
            if next_end - shifted_next_start < DISPLAY_MIN_DURATION_MS:
                continue
            result[index] = self._copy_segment(seg, start_time=start, end_time=target_end)
            result[index + 1] = self._copy_segment(
                nxt,
                start_time=shifted_next_start,
                end_time=next_end,
            )
            shifted += 1
        if shifted:
            logger.info("最终时间轴短字幕通过顺延下一条补时: %s", shifted)
        return result

    def _repair_high_load_short_subtitle_timings(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        result = list(segments)
        if not result:
            return result
        repaired = 0
        for index, seg in enumerate(result):
            if not self._is_high_load_short_subtitle(seg):
                continue
            target_duration = self._target_high_load_duration_ms(seg)
            start = max(0, int(seg.start_time))
            end = max(start + 1, int(seg.end_time))
            if end - start >= target_duration:
                continue
            target_end = start + target_duration
            if index + 1 < len(result):
                nxt = result[index + 1]
                next_end = max(int(nxt.end_time), int(nxt.start_time) + 1)
                shifted_next_start = target_end + DISPLAY_MIN_GAP_MS
                if next_end - shifted_next_start < DISPLAY_MIN_DURATION_MS:
                    continue
                result[index] = self._copy_segment(seg, start_time=start, end_time=target_end)
                result[index + 1] = self._copy_segment(
                    nxt,
                    start_time=shifted_next_start,
                    end_time=next_end,
                )
                self._record_safe_timing_repair(seg, result[index], index + 1, "high_load_short_timing_repaired")
                repaired += 1
            else:
                result[index] = self._copy_segment(seg, start_time=start, end_time=target_end)
                self._record_safe_timing_repair(seg, result[index], index + 1, "high_load_short_timing_repaired")
                repaired += 1
        if repaired:
            logger.info("高负载短字幕补时: %s", repaired)
        return result

    def _record_safe_timing_repair(
        self,
        old: ASRDataSeg,
        new: ASRDataSeg,
        index: int,
        code: str,
    ) -> None:
        if not getattr(self, "enable_safe_auto_repair", False):
            return
        if not hasattr(self, "_safe_auto_repair_log"):
            self._safe_auto_repair_log = []
        subtitle_id = self._segment_subtitle_id(new, index)
        key = (code, subtitle_id, int(old.start_time), int(old.end_time), int(new.start_time), int(new.end_time))
        for item in self._safe_auto_repair_log:
            if (
                item.get("code"),
                item.get("subtitle_id"),
                int(item.get("before_start_ms", -1)),
                int(item.get("before_end_ms", -1)),
                int(item.get("after_start_ms", -1)),
                int(item.get("after_end_ms", -1)),
            ) == key:
                return
        self._safe_auto_repair_log.append(
            {
                "stage": "final_timing",
                "code": code,
                "index": index,
                "subtitle_id": subtitle_id,
                "start": self._format_ms(new.start_time),
                "end": self._format_ms(new.end_time),
                "english": new.text,
                "before_chinese": old.translated_text,
                "after_chinese": new.translated_text,
                "before_start_ms": int(old.start_time),
                "before_end_ms": int(old.end_time),
                "after_start_ms": int(new.start_time),
                "after_end_ms": int(new.end_time),
            }
        )

    def _is_high_load_short_subtitle(self, seg: ASRDataSeg) -> bool:
        original = self._normalize_text(seg.text)
        translated = self._normalize_text(seg.translated_text)
        if self._is_simple_short_response(original, translated):
            return False
        duration_ms = max(1, int(seg.end_time) - int(seg.start_time))
        word_count = self._word_count(original)
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", translated))
        if duration_ms <= 900 and word_count >= 8 and chinese_chars >= 10:
            return True
        if duration_ms <= 800 and word_count >= 10:
            return True
        if duration_ms <= 800 and word_count >= 4 and chinese_chars >= 16:
            return True
        weighted_load = word_count * 1.35 + chinese_chars
        return (
            duration_ms <= 900
            and word_count >= 5
            and chinese_chars >= 10
            and weighted_load / (duration_ms / 1000.0) > 24
        )

    def _target_high_load_duration_ms(self, seg: ASRDataSeg) -> int:
        word_count = self._word_count(self._normalize_text(seg.text))
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", self._normalize_text(seg.translated_text)))
        english_budget = int(math.ceil((word_count / max(ENGLISH_WPS_WARNING, 1.0)) * 1000)) if word_count else 0
        chinese_budget = int(math.ceil((chinese_chars / max(CHINESE_CPS_WARNING, 1.0)) * 1000)) if chinese_chars else 0
        return min(1800, max(DISPLAY_MIN_DURATION_MS, english_budget, chinese_budget))

    def _repair_abnormal_timing_gaps(
        self,
        segments: Sequence[ASRDataSeg],
        gap_ms: int = ABNORMAL_TIMING_GAP_MS,
        cluster_gap_ms: int = ABNORMAL_TIMING_CLUSTER_GAP_MS,
    ) -> List[ASRDataSeg]:
        if len(segments) < 2:
            return list(segments)

        ordered = self._sort_segments_by_time(list(segments))
        repaired: List[ASRDataSeg] = []
        index = 0
        repair_count = 0

        while index < len(ordered):
            if not repaired:
                repaired.append(ordered[index])
                index += 1
                continue

            previous = repaired[-1]
            current = ordered[index]
            gap = current.start_time - previous.end_time
            if gap < gap_ms:
                repaired.append(current)
                index += 1
                continue

            cluster_end = index
            while (
                cluster_end + 1 < len(ordered)
                and ordered[cluster_end + 1].start_time - ordered[cluster_end].end_time
                <= cluster_gap_ms
            ):
                cluster_end += 1

            cluster = ordered[index : cluster_end + 1]
            if not self._should_repair_timing_cluster(previous, cluster, gap):
                repaired.append(current)
                index += 1
                continue

            next_start = (
                ordered[cluster_end + 1].start_time
                if cluster_end + 1 < len(ordered)
                else cluster[-1].end_time
            )
            window_start = previous.end_time + DISPLAY_MIN_GAP_MS
            window_end = max(cluster[-1].end_time, next_start - DISPLAY_MIN_GAP_MS)
            if window_end <= window_start:
                repaired.append(current)
                index += 1
                continue

            repaired_cluster = self._redistribute_timing_cluster(
                cluster, window_start, window_end
            )
            repaired.extend(repaired_cluster)
            repair_count += 1
            index = cluster_end + 1

        if repair_count:
            logger.warning(
                "Screen subtitle abnormal timing gaps repaired: %s",
                repair_count,
            )
        return repaired

    def _should_repair_timing_cluster(
        self,
        previous: ASRDataSeg,
        cluster: Sequence[ASRDataSeg],
        gap: int,
    ) -> bool:
        if not cluster or gap < ABNORMAL_TIMING_GAP_MS:
            return False
        first = cluster[0]
        if not re.search(r"[A-Za-z]", first.text or ""):
            return False

        cluster_words = sum(self._word_count(seg.text) for seg in cluster)
        cluster_duration = max(1, cluster[-1].end_time - first.start_time)
        estimated_duration = cluster_words * READ_MS_PER_EN_WORD

        first_too_compressed = (
            self._word_count(first.text) >= 8
            and (first.end_time - first.start_time)
            < self._word_count(first.text) * 150
        )
        cluster_too_compressed = (
            cluster_words >= 12 and cluster_duration < estimated_duration * 0.7
        )
        previous_complete = bool(re.search(r"[.!?]\s*$", previous.text or ""))
        return previous_complete and (first_too_compressed or cluster_too_compressed)

    def _redistribute_timing_cluster(
        self,
        cluster: Sequence[ASRDataSeg],
        window_start: int,
        window_end: int,
    ) -> List[ASRDataSeg]:
        available = max(1, window_end - window_start)
        weights = [
            max(
                seg.end_time - seg.start_time,
                self._word_count(seg.text) * READ_MS_PER_EN_WORD,
                500,
            )
            for seg in cluster
        ]
        total_weight = max(1, sum(weights))
        result: List[ASRDataSeg] = []
        cursor = window_start
        for index, seg in enumerate(cluster):
            weight = weights[index]
            if index == len(cluster) - 1:
                end_time = window_end
            else:
                end_time = window_start + int(available * sum(weights[: index + 1]) / total_weight)
            end_time = max(end_time, cursor + 1)
            result.append(
                self._copy_segment(
                    seg,
                    start_time=cursor,
                    end_time=end_time,
                )
            )
            cursor = end_time + DISPLAY_MIN_GAP_MS
            if cursor >= window_end:
                cursor = window_end
        return result

    def _merge_short_display_segments(
        self,
        segments: Sequence[ASRDataSeg],
        short_ms: int = DISPLAY_SHORT_MERGE_MS,
        merge_gap_ms: int = DISPLAY_SHORT_MERGE_GAP_MS,
    ) -> List:
        if len(segments) < 2:
            return list(segments)
        if isinstance(segments[0], ScreenSubtitleItem):
            return self._merge_short_display_items(
                segments,
                short_ms=short_ms,
                merge_gap_ms=merge_gap_ms,
            )

        ordered = self._sort_segments_by_time(list(segments))
        merged: List[ASRDataSeg] = []
        index = 0
        merge_count = 0

        while index < len(ordered):
            current = ordered[index]
            if (
                index + 1 < len(ordered)
                and not (
                    getattr(current, "subtitle_id", None)
                    and getattr(ordered[index + 1], "subtitle_id", None)
                )
                and self._should_merge_short_display_segment(
                    current, ordered[index + 1], short_ms, merge_gap_ms
                )
            ):
                next_seg = ordered[index + 1]
                merged.append(
                    self._copy_segment(
                        current,
                        text=self._join_subtitle_text(current.text, next_seg.text),
                        translated_text=self._join_subtitle_text(
                            current.translated_text, next_seg.translated_text
                        ),
                        start_time=min(current.start_time, next_seg.start_time),
                        end_time=max(current.end_time, next_seg.end_time),
                        subtitle_id=getattr(current, "subtitle_id", None)
                        or getattr(next_seg, "subtitle_id", None),
                    )
                )
                merge_count += 1
                index += 2
                continue
            merged.append(current)
            index += 1

        if merge_count:
            logger.info("Screen subtitle short display segments merged: %s", merge_count)
        return merged

    def _merge_short_display_items(
        self,
        items: Sequence[ScreenSubtitleItem],
        short_ms: int = DISPLAY_SHORT_MERGE_MS,
        merge_gap_ms: int = DISPLAY_SHORT_MERGE_GAP_MS,
    ) -> List[ScreenSubtitleItem]:
        ordered = self._sort_items_by_word_span(list(items))
        merged: List[ScreenSubtitleItem] = []
        index = 0
        merge_count = 0
        while index < len(ordered):
            current = ordered[index]
            previous_item = merged[-1] if merged else None
            next_item = ordered[index + 1] if index + 1 < len(ordered) else None
            if (
                previous_item
                and self._should_attach_short_backchannel_to_previous(
                    previous_item,
                    current,
                    next_item,
                    short_ms=short_ms,
                    merge_gap_ms=merge_gap_ms,
                )
            ):
                merged[-1] = self._merge_subtitle_items(previous_item, current)
                merge_count += 1
                index += 1
                continue
            if index + 1 < len(ordered) and self._should_merge_short_display_item(
                current,
                ordered[index + 1],
                short_ms,
                merge_gap_ms,
            ):
                balanced = self._balanced_two_item_split(
                    current,
                    ordered[index + 1],
                    require_left_not_marker_only=True,
                )
                if balanced:
                    merged.extend(balanced)
                else:
                    direct_merge = self._safe_direct_short_item_merge(
                        current,
                        ordered[index + 1],
                    )
                    if direct_merge:
                        merged.append(direct_merge)
                    else:
                        self._record_pre_id_boundary_repair(
                            repaired_by="_merge_short_display_segments",
                            old_items=[current, ordered[index + 1]],
                            new_items=None,
                            evaluation=self._evaluate_item_boundary(
                                current,
                                ordered[index + 1],
                            ),
                            repair_reason="short_display_merge_no_legal_boundary",
                            candidates_considered=[],
                        )
                        merged.append(current)
                        index += 1
                        continue
                merge_count += 1
                index += 2
                continue
            merged.append(current)
            index += 1
        if merge_count:
            logger.info("Screen subtitle short display items merged before ids: %s", merge_count)
        return merged

    def _should_attach_short_backchannel_to_previous(
        self,
        previous_item: ScreenSubtitleItem,
        current: ScreenSubtitleItem,
        next_item: Optional[ScreenSubtitleItem],
        *,
        short_ms: int,
        merge_gap_ms: int,
    ) -> bool:
        """Keep a tiny acknowledgement with its preceding completed thought.

        This applies only before IDs are assigned and only when the same
        short backchannel cannot be an independent answer.  It prevents a
        one-word acknowledgement from forcing the following sentence past the
        display limit while preserving the frozen word order and timing ledger.
        """
        if not self._is_short_backchannel_text(current.original):
            return False
        if self._is_independent_discourse_answer(current, previous_item, next_item):
            return False
        timing = self._item_word_timing(current)
        if not timing or timing[1] - timing[0] >= short_ms:
            return False
        if not self._can_attach_discourse_marker(previous_item, current, merge_gap_ms):
            return False
        return self._word_count(
            self._join_subtitle_text(previous_item.original, current.original)
        ) <= self.max_english_words

    def _safe_direct_short_item_merge(
        self,
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
    ) -> Optional[ScreenSubtitleItem]:
        if left.subtitle_id or right.subtitle_id:
            return None
        if not self._items_are_continuous(left, right):
            return None
        if self._items_cross_speaker(left, right):
            return None
        merged = self._merge_subtitle_items(left, right)
        if self._word_count(merged.original) > self.max_english_words:
            return None
        return merged

    def _should_merge_short_display_item(
        self,
        current: ScreenSubtitleItem,
        next_item: ScreenSubtitleItem,
        short_ms: int,
        merge_gap_ms: int,
    ) -> bool:
        if current.subtitle_id or next_item.subtitle_id:
            return False
        timing = self._item_word_timing(current)
        next_timing = self._item_word_timing(next_item)
        if not timing or not next_timing:
            return False
        duration = max(0, timing[1] - timing[0])
        gap = max(0, next_timing[0] - timing[1])
        if duration >= short_ms or gap > merge_gap_ms:
            return False
        if not self._items_are_continuous(current, next_item):
            return False
        if self._items_cross_speaker(current, next_item):
            return False
        current_words = self._word_tokens(current.original)
        if not current_words or len(current_words) > 4:
            return False
        combined_words = self._word_tokens(
            self._join_subtitle_text(current.original, next_item.original)
        )
        is_short_bridge = self._is_short_bridge_text(current.original)
        if len(combined_words) > max(1, self.max_english_words):
            return bool(
                is_short_bridge
                and
                self._balanced_two_item_split(
                    current,
                    next_item,
                    require_left_not_marker_only=True,
                )
            )
        return is_short_bridge

    def _should_merge_short_display_segment(
        self,
        current: ASRDataSeg,
        next_seg: ASRDataSeg,
        short_ms: int,
        merge_gap_ms: int,
    ) -> bool:
        duration = max(0, current.end_time - current.start_time)
        gap = max(0, next_seg.start_time - current.end_time)
        if duration >= short_ms or gap > merge_gap_ms:
            return False
        current_words = self._word_tokens(current.text)
        if not current_words or len(current_words) > 4:
            return False
        combined_words = self._word_tokens(
            self._join_subtitle_text(current.text, next_seg.text)
        )
        if len(combined_words) > max(1, self.max_english_words):
            return False
        return self._is_short_bridge_text(current.text)

    @staticmethod
    def _is_short_backchannel_text(text: str) -> bool:
        normalized = re.sub(r"[^a-z'\s]", " ", text.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized in {
            "yeah",
            "right",
            "exactly",
            "precisely",
            "okay",
            "ok",
            "wow",
            "oh right",
            "oh really",
            "how so",
            "it is",
            "it does",
            "they are",
            "they really are",
        }

    @classmethod
    def _is_short_bridge_text(cls, text: str) -> bool:
        normalized = re.sub(r"[^a-z'\s]", " ", text.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized == "though" or cls._is_short_backchannel_text(text)

    @staticmethod
    def _join_subtitle_text(left: str, right: str) -> str:
        left = (left or "").strip()
        right = (right or "").strip()
        if left and right:
            return f"{left} {right}"
        return left or right

    def _stable_cut_items(
        self, source_segments: Sequence[ASRDataSeg]
    ) -> List[ScreenSubtitleItem]:
        items: List[ScreenSubtitleItem] = []
        if self._active_word_entries:
            self._prepare_syntax_cut_hints()
            for source_span in self._stable_sentence_word_spans():
                for word_start, word_end in self._stable_word_ranges_for_span(source_span):
                    original = self._text_from_word_span(word_start, word_end)
                    if not original:
                        continue
                    items.append(
                        ScreenSubtitleItem(
                            source_ids=self._source_ids_for_word_range(word_start, word_end),
                            original=original,
                            translated="",
                            word_start=word_start,
                            word_end=word_end,
                        )
                    )
            logger.info("Screen subtitle stable mode items: %s", len(items))
            return items

        for source_id, seg in enumerate(source_segments, 1):
            items.append(
                ScreenSubtitleItem(
                    source_ids=[source_id],
                    original=self._normalize_text(seg.text),
                    translated=self._normalize_text(seg.translated_text),
                )
            )
        logger.info("Screen subtitle stable mode items: %s", len(items))
        return items

    def _merge_standalone_discourse_markers(
        self,
        items: Sequence[ScreenSubtitleItem],
        merge_gap_ms: int = DISPLAY_SHORT_MERGE_GAP_MS,
    ) -> List[ScreenSubtitleItem]:
        ordered = self._sort_items_by_word_span(list(items))
        if len(ordered) < 2:
            return ordered
        result: List[ScreenSubtitleItem] = []
        index = 0
        merged_count = 0
        while index < len(ordered):
            item = ordered[index]
            marker = self._standalone_discourse_marker(item.original)
            if not marker:
                result.append(item)
                index += 1
                continue

            previous_item = result[-1] if result else None
            next_item = ordered[index + 1] if index + 1 < len(ordered) else None
            if (
                next_item
                and not self._is_independent_discourse_answer(item, previous_item, next_item)
                and self._can_attach_discourse_marker(item, next_item, merge_gap_ms)
            ):
                merged, remainder = self._attach_marker_to_next_item(item, next_item)
                if merged:
                    result.append(merged)
                    if remainder:
                        ordered[index + 1] = remainder
                        index += 1
                    else:
                        index += 2
                    merged_count += 1
                    continue
            if (
                previous_item
                and not self._is_independent_discourse_answer(item, previous_item, next_item)
                and self._can_attach_discourse_marker(previous_item, item, merge_gap_ms)
            ):
                merged, remainder = self._attach_marker_to_previous_item(previous_item, item)
                if merged:
                    if remainder:
                        result[-1] = remainder
                        result.append(merged)
                    else:
                        result[-1] = merged
                    index += 1
                    merged_count += 1
                    continue

            self._record_discourse_marker_orphan(item, marker)
            result.append(item)
            index += 1
        if merged_count:
            logger.info("Standalone discourse markers merged before ids: %s", merged_count)
        return result

    @classmethod
    def _standalone_discourse_marker(cls, text: str) -> str:
        normalized = cls._normalize_text(text)
        normalized = re.sub(r"[^a-z]+", " ", normalized.lower()).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        if normalized in {"i mean", "you know", "i guess", "well i mean", "plus"}:
            return normalized
        return ""

    def _can_attach_discourse_marker(
        self,
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
        merge_gap_ms: int,
    ) -> bool:
        if left.subtitle_id or right.subtitle_id:
            return False
        if not self._items_are_continuous(left, right):
            return False
        if self._items_cross_speaker(left, right):
            return False
        left_timing = self._item_word_timing(left)
        right_timing = self._item_word_timing(right)
        if left_timing and right_timing:
            gap = right_timing[0] - left_timing[1]
            if gap < 0 or gap > merge_gap_ms:
                return False
        return True

    def _can_keep_one_word_discourse_overflow(
        self,
        marker: ScreenSubtitleItem,
        combined: ScreenSubtitleItem,
        combined_words: int,
    ) -> bool:
        """Keep a complete connector-led sense unit over one isolated marker.

        The configured English value is a soft display target.  This narrow
        exception is only for a one-word ``Plus,`` lead-in where splitting
        would leave the connector alone and the complete unit exceeds the
        target by exactly one word.
        """
        return bool(
            self._standalone_discourse_marker(marker.original) == "plus"
            and combined_words == self.max_english_words + 1
            and re.search(r"[.!?][\"')\]]*\s*$", combined.original or "")
        )

    def _attach_marker_to_next_item(
        self,
        marker: ScreenSubtitleItem,
        next_item: ScreenSubtitleItem,
    ) -> tuple[Optional[ScreenSubtitleItem], Optional[ScreenSubtitleItem]]:
        combined = self._merge_subtitle_items(marker, next_item)
        combined_words = self._word_count(combined.original)
        if (
            combined_words <= self.max_english_words
            or self._can_keep_one_word_discourse_overflow(marker, combined, combined_words)
        ):
            return combined, None
        if next_item.word_start is None or next_item.word_end is None:
            return None, None
        balanced = self._balanced_two_item_split(
            marker,
            next_item,
            require_left_not_marker_only=True,
        )
        if not balanced:
            return None, None
        return balanced[0], balanced[1] if len(balanced) > 1 else None

    def _attach_marker_to_previous_item(
        self,
        previous_item: ScreenSubtitleItem,
        marker: ScreenSubtitleItem,
    ) -> tuple[Optional[ScreenSubtitleItem], Optional[ScreenSubtitleItem]]:
        combined = self._merge_subtitle_items(previous_item, marker)
        if self._word_count(combined.original) <= self.max_english_words:
            return combined, None
        if previous_item.word_start is None or previous_item.word_end is None:
            return None, None
        balanced = self._balanced_two_item_split(previous_item, marker)
        if not balanced:
            return None, None
        if len(balanced) == 1:
            return balanced[0], None
        return balanced[1], balanced[0]

    def _rebalance_edge_discourse_markers(
        self,
        items: Sequence[ScreenSubtitleItem],
        merge_gap_ms: int = DISPLAY_SHORT_MERGE_GAP_MS,
    ) -> List[ScreenSubtitleItem]:
        ordered = self._sort_items_by_word_span(list(items))
        if len(ordered) < 2:
            return ordered
        result: List[ScreenSubtitleItem] = []
        index = 0
        changed = 0
        while index < len(ordered):
            current = ordered[index]
            if index + 1 < len(ordered):
                next_item = ordered[index + 1]
                if (
                    self._has_trailing_discourse_marker(current.original)
                    and self._can_attach_discourse_marker(current, next_item, merge_gap_ms)
                    and not self._is_independent_discourse_answer(current, result[-1] if result else None, next_item)
                ):
                    balanced = self._balanced_two_item_split(
                        current,
                        next_item,
                        require_left_not_trailing_marker=True,
                        force_two_items=True,
                    )
                    if balanced:
                        result.extend(balanced)
                        index += 2
                        changed += 1
                        continue
            result.append(current)
            index += 1
        if changed:
            logger.info("Edge discourse markers rebalanced before ids: %s", changed)
        return result

    def _balanced_two_item_split(
        self,
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
        *,
        require_left_not_marker_only: bool = False,
        require_left_not_trailing_marker: bool = False,
        force_two_items: bool = False,
    ) -> List[ScreenSubtitleItem]:
        if left.word_start is None or left.word_end is None:
            return []
        if right.word_start is None or right.word_end is None:
            return []
        if right.word_start != left.word_end + 1:
            return []
        if left.subtitle_id or right.subtitle_id:
            return []
        merged = self._merge_subtitle_items(left, right)
        total_words = self._word_count(merged.original)
        if total_words <= self.max_english_words and not force_two_items:
            if require_left_not_marker_only and self._standalone_discourse_marker(merged.original):
                return []
            if require_left_not_trailing_marker and self._has_trailing_discourse_marker(merged.original):
                return []
            return [merged]

        best: Optional[tuple[float, float, int, int, int, List[ScreenSubtitleItem]]] = None
        span_start = left.word_start
        span_end = right.word_end
        original_boundary = left.word_end
        for cut in range(span_start, span_end):
            left_item = self._item_from_word_span(span_start, cut)
            right_item = self._item_from_word_span(cut + 1, span_end)
            if not left_item or not right_item:
                continue
            left_words = self._word_count(left_item.original)
            right_words = self._word_count(right_item.original)
            if left_words > self.max_english_words or right_words > self.max_english_words:
                continue
            if (
                require_left_not_marker_only
                and (
                    self._standalone_discourse_marker(left_item.original)
                    or self._is_short_backchannel_text(left_item.original)
                )
            ):
                continue
            if self._is_ordinary_one_word_fragment(left_item.original) or self._is_ordinary_one_word_fragment(right_item.original):
                continue
            if self._splits_discourse_marker(left_item.original, right_item.original):
                continue
            if (
                require_left_not_trailing_marker
                and self._has_weak_edge_discourse_marker(left_item.original)
            ):
                continue
            boundary = self._evaluate_stable_cut_boundary(
                cut,
                cut + 1,
                source_start=span_start,
                source_end=span_end,
            )
            if not boundary["legal"]:
                continue
            candidate_gate = self._can_apply_pre_id_repair_candidate(
                [left, right],
                [left_item, right_item],
            )
            if not candidate_gate["accepted"]:
                continue
            score = (
                len(boundary["soft_issues"]),
                float(boundary["boundary_score"]),
                abs(left_words - right_words),
                abs(cut - original_boundary),
                left_words + right_words,
            )
            if best is None or score < best[:5]:
                best = (score[0], score[1], score[2], score[3], score[4], [left_item, right_item])
        return best[5] if best else []

    def _item_from_word_span(
        self,
        word_start: int,
        word_end: int,
        *,
        require_alpha: bool = True,
    ) -> Optional[ScreenSubtitleItem]:
        text = self._text_from_word_span(word_start, word_end)
        if not text or (require_alpha and not re.search(r"[A-Za-z]", text)):
            return None
        return ScreenSubtitleItem(
            source_ids=self._source_ids_for_word_range(word_start, word_end),
            original=text,
            translated="",
            word_start=word_start,
            word_end=word_end,
        )

    def _merge_subtitle_items(
        self, left: ScreenSubtitleItem, right: ScreenSubtitleItem
    ) -> ScreenSubtitleItem:
        word_start = left.word_start
        if word_start is None or (
            right.word_start is not None and right.word_start < word_start
        ):
            word_start = right.word_start
        word_end = right.word_end
        if word_end is None or (left.word_end is not None and left.word_end > word_end):
            word_end = left.word_end
        return ScreenSubtitleItem(
            source_ids=sorted(set(left.source_ids + right.source_ids)),
            original=(
                self._text_from_word_span(word_start, word_end)
                if word_start is not None and word_end is not None
                else self._join_subtitle_text(left.original, right.original)
            ),
            translated=self._join_subtitle_text(left.translated, right.translated),
            word_start=word_start,
            word_end=word_end,
            subtitle_id=left.subtitle_id or right.subtitle_id,
        )

    @classmethod
    def _has_trailing_discourse_marker(cls, text: str) -> bool:
        normalized = cls._normalize_text(text)
        return bool(
            re.search(
                r"(?:^|[,;:\s])(?:i\s+mean|you\s+know|i\s+guess|well\s+i\s+mean)[,;:.!?]*$",
                normalized,
                flags=re.IGNORECASE,
            )
        )

    @classmethod
    def _has_weak_edge_discourse_marker(cls, text: str) -> bool:
        if cls._has_trailing_discourse_marker(text):
            return True
        tokens = [word.lower() for word in cls._word_tokens(text)]
        marker_phrases = (
            ("i", "mean"),
            ("you", "know"),
            ("i", "guess"),
            ("well", "i", "mean"),
        )
        for phrase in marker_phrases:
            phrase_len = len(phrase)
            for start in range(0, len(tokens) - phrase_len + 1):
                if tuple(tokens[start:start + phrase_len]) != phrase:
                    continue
                words_after_marker = len(tokens) - (start + phrase_len)
                if words_after_marker <= 1:
                    return True
        return False

    @classmethod
    def _is_ordinary_one_word_fragment(cls, text: str) -> bool:
        if cls._word_count(text) != 1:
            return False
        if cls._standalone_discourse_marker(text) or cls._is_short_backchannel_text(text):
            return False
        return True

    @classmethod
    def _splits_discourse_marker(cls, left_text: str, right_text: str) -> bool:
        left_words = cls._word_tokens(left_text)
        right_words = cls._word_tokens(right_text)
        if not left_words or not right_words:
            return False
        combined = [word.lower() for word in left_words[-3:] + right_words[:3]]
        boundary = min(3, len(left_words))
        marker_phrases = (
            ("i", "mean"),
            ("you", "know"),
            ("i", "guess"),
            ("well", "i", "mean"),
        )
        for phrase in marker_phrases:
            phrase_len = len(phrase)
            for start in range(0, len(combined) - phrase_len + 1):
                end = start + phrase_len
                if tuple(combined[start:end]) != phrase:
                    continue
                if start < boundary < end:
                    return True
        return False

    @staticmethod
    def _items_are_continuous(left: ScreenSubtitleItem, right: ScreenSubtitleItem) -> bool:
        if (
            left.word_end is not None
            and right.word_start is not None
            and right.word_start != left.word_end + 1
        ):
            return False
        if left.source_ids and right.source_ids and min(right.source_ids) - max(left.source_ids) > 1:
            return False
        return True

    def _items_cross_speaker(
        self, left: ScreenSubtitleItem, right: ScreenSubtitleItem
    ) -> bool:
        by_id = getattr(self, "_active_source_segments_by_id", {}) or {}
        left_speakers = {
            self._segment_speaker(by_id[source_id])
            for source_id in left.source_ids
            if source_id in by_id and self._segment_speaker(by_id[source_id])
        }
        right_speakers = {
            self._segment_speaker(by_id[source_id])
            for source_id in right.source_ids
            if source_id in by_id and self._segment_speaker(by_id[source_id])
        }
        return bool(left_speakers and right_speakers and left_speakers.isdisjoint(right_speakers))

    def _item_speaker(self, item: ScreenSubtitleItem) -> str:
        by_id = getattr(self, "_active_source_segments_by_id", {}) or {}
        speakers = [
            self._segment_speaker(by_id[source_id])
            for source_id in item.source_ids
            if source_id in by_id and self._segment_speaker(by_id[source_id])
        ]
        return speakers[0] if speakers else ""

    @staticmethod
    def _segment_speaker(seg: ASRDataSeg) -> str:
        for attr in ("speaker", "speaker_id", "speaker_name"):
            value = getattr(seg, attr, None)
            if value not in (None, ""):
                return str(value)
        return ""

    @classmethod
    def _is_independent_discourse_answer(
        cls,
        marker: ScreenSubtitleItem,
        previous_item: Optional[ScreenSubtitleItem],
        next_item: Optional[ScreenSubtitleItem],
    ) -> bool:
        text = cls._normalize_text(marker.original)
        if not re.search(r"[.!?]\s*$", text):
            return False
        previous_question = bool(previous_item and re.search(r"\?\s*$", previous_item.original or ""))
        next_question = bool(next_item and re.search(r"\?\s*$", next_item.original or ""))
        return previous_question or next_question

    def _record_discourse_marker_orphan(
        self, item: ScreenSubtitleItem, marker: str
    ) -> None:
        timing = self._item_word_timing(item)
        issue = {
            "code": "discourse_marker_orphan",
            "marker": marker,
            "text": self._normalize_text(item.original),
            "source_ids": list(item.source_ids),
            "word_start": item.word_start,
            "word_end": item.word_end,
        }
        if timing:
            issue["start"] = self._format_ms(timing[0])
            issue["end"] = self._format_ms(timing[1])
        self._discourse_marker_orphans.append(issue)

    def _validate_and_repair_final_pre_id_boundaries(
        self,
        items: Sequence[ScreenSubtitleItem],
    ) -> List[ScreenSubtitleItem]:
        result = self._split_internal_sentence_transition_items(
            self._sort_items_by_word_span(list(items))
        )
        safety_iterations = 0
        index = 0
        while index < len(result):
            safety_iterations += 1
            if safety_iterations > max(1000, len(result) * 8):
                logger.warning("Final pre-ID boundary repair stopped by safety iteration guard")
                break
            if index >= len(result) - 1:
                break
            left = result[index]
            right = result[index + 1]
            evaluation = self._evaluate_item_pair_for_final_boundary(
                left,
                right,
                result[index - 1] if index > 0 else None,
            )
            if evaluation["legal"]:
                index += 1
                continue
            repaired = self._repair_pre_id_boundary_window(result, index, evaluation)
            if repaired is None:
                self._record_pre_id_boundary_repair(
                    repaired_by="_validate_and_repair_final_pre_id_boundaries",
                    old_items=[left, right],
                    new_items=None,
                    evaluation=evaluation,
                    repair_reason="unresolved_hard_issue",
                    candidates_considered=[],
                )
                index += 1
                continue
            start, end, new_items, candidates = repaired
            old_items = result[start:end]
            self._record_pre_id_boundary_repair(
                repaired_by="_validate_and_repair_final_pre_id_boundaries",
                old_items=old_items,
                new_items=new_items,
                evaluation=evaluation,
                repair_reason=(
                    "forced_overflow_syntax_split"
                    if any(
                        candidate.get("selected")
                        and candidate.get("forced_overflow_fallback")
                        for candidate in candidates
                    )
                    else "hard_syntax_boundary_repaired"
                ),
                candidates_considered=candidates,
            )
            result[start:end] = new_items
            index = max(0, start - 1)
        result = self._validate_final_display_fragments(result)
        result = self._repair_final_overlong_display_items(result)
        # A safe overflow split can expose a local short fragment only after
        # its neighboring boundary has changed. Re-run the same fragment gate
        # before IDs freeze rather than leaving the new boundary unchecked.
        result = self._validate_final_display_fragments(result)
        # This final local rebalance has a parser-verified exception for an
        # ellipted non-finite condition ending in ``to,``. Running it after the
        # generic boundary loop prevents its lexical preposition fallback from
        # undoing the already validated move.
        result = self._rebalance_leading_nonfinite_dependent_prefixes(result)
        return result

    def _rebalance_leading_nonfinite_dependent_prefixes(
        self,
        items: Sequence[ScreenSubtitleItem],
    ) -> List[ScreenSubtitleItem]:
        """Move a short leading non-finite condition back to its prior clause.

        A stable cut can legally fall before a complete right-hand cue even
        though that cue starts with a short ellipted condition such as
        ``unless forced to,``. That condition semantically completes the
        preceding action, while the complete clause after its comma belongs on
        the following screen. Rebalance only this parser-confirmed local
        shape; finite conditional introductions remain untouched.
        """
        result = list(items)
        for index in range(len(result) - 1):
            left = result[index]
            right = result[index + 1]
            prefix_end = self._leading_nonfinite_dependent_prefix_end(right)
            if prefix_end is None:
                continue
            if (
                left.subtitle_id
                or right.subtitle_id
                or not self._items_are_continuous(left, right)
                or self._items_cross_speaker(left, right)
                or re.search(r"[.!?][\"')\]]*\s*$", self._normalize_text(left.original))
            ):
                continue
            pause_ms = self._boundary_pause_ms(left, right)
            if pause_ms is not None and pause_ms >= 450:
                continue
            if (
                left.word_start is None
                or right.word_end is None
                or prefix_end >= right.word_end
            ):
                continue
            new_left = self._item_from_word_span(left.word_start, prefix_end)
            new_right = self._item_from_word_span(prefix_end + 1, right.word_end)
            if not new_left or not new_right:
                continue
            if (
                self._word_count(new_left.original) > self.max_english_words
                or self._word_count(new_right.original) > self.max_english_words
                or self._word_count(new_right.original) < VISUAL_TEMPORAL_MIN_WORDS
            ):
                continue
            right_shape = self._visual_temporal_clause_shape(new_right)
            boundary = self._evaluate_item_pair_for_final_boundary(new_left, new_right)
            # ``unless forced to,`` ends in an ellipted infinitive, not a
            # preposition waiting for the next cue's object. The shared lexical
            # fallback cannot see that comma-scoped parse, so relax only this
            # one false positive after the non-finite-prefix parser gate above.
            relaxed_hard_issues = [
                issue
                for issue in list(boundary.get("hard_issues") or [])
                if issue == "preposition_object_split"
            ]
            disallowed_hard_issues = [
                issue
                for issue in list(boundary.get("hard_issues") or [])
                if issue not in relaxed_hard_issues
            ]
            new_left_fragment = self._evaluate_final_display_fragment(
                new_left,
                result[index - 1] if index > 0 else None,
                new_right,
            )
            new_right_fragment = self._evaluate_final_display_fragment(
                new_right,
                new_left,
                result[index + 2] if index + 2 < len(result) else None,
            )
            candidates = [{
                "prefix_word_range": [right.word_start, prefix_end],
                "prefix_text": self._text_from_word_span(right.word_start, prefix_end),
                "new_boundary": [prefix_end, prefix_end + 1],
                "new_left": new_left.original,
                "new_right": new_right.original,
                "pause_ms": pause_ms,
                "right_complete_main_clause": right_shape["complete_main_clause"],
                "hard_issues": disallowed_hard_issues,
                "relaxed_hard_issues": relaxed_hard_issues,
                "hard_fragment_issues": list(
                    dict.fromkeys(
                        list(new_left_fragment.get("hard_fragment_issues") or [])
                        + list(new_right_fragment.get("hard_fragment_issues") or [])
                    )
                ),
            }]
            if (
                not right_shape["complete_main_clause"]
                or disallowed_hard_issues
                or new_left_fragment.get("hard_fragment_issues")
                or new_right_fragment.get("hard_fragment_issues")
            ):
                continue
            candidate_gate = self._can_apply_pre_id_repair_candidate(
                [left, right],
                [new_left, new_right],
                previous_item=result[index - 1] if index > 0 else None,
                next_item=result[index + 2] if index + 2 < len(result) else None,
                allowed_hard_issues=relaxed_hard_issues,
            )
            if not candidate_gate["accepted"]:
                continue
            candidates[0]["candidate_gate"] = candidate_gate
            self._record_pre_id_boundary_repair(
                repaired_by="_rebalance_leading_nonfinite_dependent_prefixes",
                old_items=[left, right],
                new_items=[new_left, new_right],
                evaluation={
                    "legal": False,
                    "hard_issues": ["leading_nonfinite_dependent_prefix"],
                    "allowed_hard_issues": relaxed_hard_issues,
                    "soft_issues": [],
                    "boundary_score": boundary.get("boundary_score", 0.0),
                    "protected_syntax": False,
                    "pause_ms": pause_ms,
                    "fragment_type": "leading_nonfinite_dependent_prefix",
                },
                repair_reason="leading_nonfinite_dependent_prefix_rebalanced",
                candidates_considered=candidates,
                unresolved_is_hard=False,
            )
            result[index:index + 2] = [new_left, new_right]
        return result

    def _leading_nonfinite_dependent_prefix_end(
        self,
        item: ScreenSubtitleItem,
    ) -> Optional[int]:
        """Return a short comma-terminated non-finite condition prefix end."""
        if (
            item.word_start is None
            or item.word_end is None
            or item.word_end - item.word_start < 5
        ):
            return None
        nlp = self._load_syntax_nlp()
        if not nlp:
            return None
        prefix_end = None
        max_prefix_end = min(item.word_start + 5, item.word_end - VISUAL_TEMPORAL_MIN_WORDS)
        for word_index in range(item.word_start + 1, max_prefix_end + 1):
            surface = str(self._active_word_entries[word_index].get("surface") or "")
            if re.search(r",\s*$", surface):
                prefix_end = word_index
                break
        if prefix_end is None:
            return None
        prefix = self._text_from_word_span(item.word_start, prefix_end)
        try:
            doc = nlp(self._normalize_text(prefix))
        except Exception as exc:
            logger.debug("Leading non-finite prefix parse skipped: %s", exc)
            return None
        root = next((token for token in doc if token.dep_ == "ROOT"), None)
        if root is None:
            return None
        has_clause_marker = any(
            token.pos_ == "SCONJ" or token.dep_ == "mark"
            for token in doc
        )
        has_subject = any(token.dep_ in {"nsubj", "nsubjpass", "csubj"} for token in doc)
        root_is_nonfinite = (
            root.pos_ in {"VERB", "AUX"}
            and root.tag_ in {"VB", "VBG", "VBN"}
        )
        return prefix_end if has_clause_marker and root_is_nonfinite and not has_subject else None

    def _repair_final_overlong_display_items(
        self,
        items: Sequence[ScreenSubtitleItem],
    ) -> List[ScreenSubtitleItem]:
        """Split only overlong pre-ID items that have a fully legal local cut."""
        result = list(items)
        index = 0
        while index < len(result):
            item = result[index]
            if self._word_count(item.original) <= self.max_english_words:
                index += 1
                continue
            repaired, candidates = self._safe_overlong_item_split(item)
            if not repaired:
                index += 1
                continue
            candidate_gate = self._can_apply_pre_id_repair_candidate(
                [item],
                repaired,
                previous_item=result[index - 1] if index > 0 else None,
                next_item=result[index + 1] if index + 1 < len(result) else None,
            )
            selected_candidate = next(
                (candidate for candidate in candidates if candidate.get("cuts")),
                None,
            )
            if selected_candidate is not None:
                selected_candidate["candidate_gate"] = candidate_gate
            if not candidate_gate["accepted"]:
                index += 1
                continue
            self._record_pre_id_boundary_repair(
                repaired_by="_repair_final_overlong_display_items",
                old_items=[item],
                new_items=repaired,
                evaluation={
                    "legal": False,
                    "hard_issues": ["overlong_english"],
                    "soft_issues": [],
                    "boundary_score": 0.0,
                    "protected_syntax": False,
                    "pause_ms": None,
                    "fragment_type": "",
                },
                repair_reason="safe_overlong_item_split",
                candidates_considered=candidates,
            )
            result[index:index + 1] = repaired
            index = max(0, index - 1)
        return result

    @classmethod
    def _visible_english_character_count(cls, text: str) -> int:
        """Count rendered English characters after normalizing source spacing."""
        return len(re.sub(r"\s+", " ", cls._normalize_text(text)))

    def _visual_reading_budget(self, item: ScreenSubtitleItem) -> Dict[str, int | bool]:
        word_count = self._word_count(item.original)
        character_count = self._visible_english_character_count(item.original)
        return {
            "word_count": word_count,
            "character_count": character_count,
            "word_limit": VISUAL_ENGLISH_WORD_SOFT_LIMIT,
            "character_limit": VISUAL_ENGLISH_CHARACTER_SOFT_LIMIT,
            "exceeds": (
                word_count > VISUAL_ENGLISH_WORD_SOFT_LIMIT
                or character_count > VISUAL_ENGLISH_CHARACTER_SOFT_LIMIT
            ),
        }

    def _apply_visual_reading_budget(
        self,
        items: Sequence[ScreenSubtitleItem],
    ) -> List[ScreenSubtitleItem]:
        """Legacy offline visual-boundary diagnostic helper.

        Stable production deliberately does not invoke this helper. Formal
        subtitle boundaries are owned by language/timing stages only; visual
        pagination is a renderer-only projection after subtitle IDs and
        Chinese allocation are frozen. The helper remains available to inspect
        historical boundary evidence without becoming a production writer.
        """
        result: List[ScreenSubtitleItem] = []
        source_items = list(items)
        for index, item in enumerate(source_items):
            budget = self._visual_reading_budget(item)
            if not budget["exceeds"]:
                result.append(item)
                continue
            split_items, candidates = self._safe_visual_temporal_item_split(item)
            if not split_items:
                result.append(item)
                continue
            selected = next(
                (candidate for candidate in candidates if candidate.get("selected")),
                {},
            )
            candidate_gate = self._can_apply_pre_id_repair_candidate(
                [item],
                split_items,
                previous_item=source_items[index - 1] if index > 0 else None,
                next_item=source_items[index + 1] if index + 1 < len(source_items) else None,
            )
            selected["candidate_gate"] = candidate_gate
            if not candidate_gate["accepted"]:
                result.append(item)
                continue
            evaluation = dict(selected.get("evaluation") or {})
            evaluation["visual_reading_budget"] = budget
            evaluation["visual_temporal_category"] = selected.get("category", "")
            evaluation["display_durations_ms"] = list(selected.get("display_durations_ms") or [])
            self._record_pre_id_boundary_repair(
                repaired_by="_apply_visual_reading_budget",
                old_items=[item],
                new_items=split_items,
                evaluation=evaluation,
                repair_reason="visual_temporal_display_unit_split",
                candidates_considered=candidates,
                unresolved_is_hard=False,
            )
            result.extend(split_items)
        return result

    def _safe_visual_temporal_item_split(
        self,
        item: ScreenSubtitleItem,
    ) -> tuple[List[ScreenSubtitleItem], List[Dict]]:
        """Select one deterministic, readable visual time split for a long cue."""
        if (
            item.subtitle_id
            or item.word_start is None
            or item.word_end is None
            or item.word_end - item.word_start + 1 < VISUAL_TEMPORAL_MIN_WORDS * 2
        ):
            return [], []
        if not self._load_syntax_nlp():
            # Visual time splitting is optional. Without local syntax evidence
            # the renderer still wraps the original frozen cue.
            return [], []

        candidates: List[Dict] = []
        best: Optional[tuple] = None
        first_cut = item.word_start + VISUAL_TEMPORAL_MIN_WORDS - 1
        last_cut = item.word_end - VISUAL_TEMPORAL_MIN_WORDS
        for cut in range(first_cut, last_cut + 1):
            left = self._item_from_word_span(item.word_start, cut)
            right = self._item_from_word_span(cut + 1, item.word_end)
            if not left or not right:
                continue
            candidate = self._evaluate_visual_temporal_split_candidate(left, right)
            candidates.append(candidate)
            if not candidate["eligible"]:
                continue
            score = (
                int(candidate["category_rank"]),
                -int(candidate["pause_ms"]),
                abs(int(candidate["word_counts"][0]) - int(candidate["word_counts"][1])),
                abs(int(candidate["character_counts"][0]) - int(candidate["character_counts"][1])),
                int(cut),
            )
            if best is None or score < best[:5]:
                best = (*score, left, right, candidate)

        if best is None:
            return [], candidates
        selected = best[7]
        selected["selected"] = True
        return [best[5], best[6]], candidates

    def _evaluate_visual_temporal_split_candidate(
        self,
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
    ) -> Dict:
        """Evaluate a candidate as a visual display boundary, not a text wrap.

        A valid result is one of three generic shapes: a sentence terminal,
        two complete clauses, or a punctuated non-finite introduction followed
        by its complete main clause. Subject-to-finite-verb cuts intentionally
        remain structural hard failures in this first pass.
        """
        evaluation = self._evaluate_item_pair_for_final_boundary(left, right)
        pause_ms = int(evaluation.get("pause_ms") or 0)
        word_counts = [self._word_count(left.original), self._word_count(right.original)]
        character_counts = [
            self._visible_english_character_count(left.original),
            self._visible_english_character_count(right.original),
        ]
        display_durations_ms = [
            self._short_item_duration_ms(left),
            self._short_item_duration_ms(right),
        ]
        left_shape = self._visual_temporal_clause_shape(left)
        right_shape = self._visual_temporal_clause_shape(right)
        left_issues = self._visual_split_display_unit_issues(left, None, right)
        right_issues = self._visual_split_display_unit_issues(right, left, None)
        left_terminal = bool(re.search(r"[.!?][\"')\]]*\s*$", self._normalize_text(left.original)))
        left_comma_boundary = bool(re.search(r"[,;:]\s*$", self._normalize_text(left.original)))
        duration_floor = [
            max(VISUAL_TEMPORAL_MIN_DISPLAY_MS, count * VISUAL_TEMPORAL_MIN_MS_PER_WORD)
            for count in word_counts
        ]
        base_reasons: List[str] = []
        if evaluation.get("hard_issues"):
            base_reasons.append("hard_syntax_issue")
        if not self._items_are_continuous(left, right):
            base_reasons.append("non_continuous_word_range")
        if self._items_cross_speaker(left, right):
            base_reasons.append("speaker_change")
        if any(count < VISUAL_TEMPORAL_MIN_WORDS for count in word_counts):
            base_reasons.append("short_display_unit")
        if any(count > VISUAL_ENGLISH_WORD_SOFT_LIMIT for count in word_counts):
            base_reasons.append("word_budget_exceeded")
        if any(count > VISUAL_ENGLISH_CHARACTER_SOFT_LIMIT for count in character_counts):
            base_reasons.append("character_budget_exceeded")
        if any(duration < floor for duration, floor in zip(display_durations_ms, duration_floor)):
            base_reasons.append("display_duration_too_short")

        category = ""
        category_rank = 99
        allowed_left_issues: set[str] = set()
        if (
            left_terminal
            and left_shape["complete_main_clause"]
            and right_shape["complete_main_clause"]
            and pause_ms >= VISUAL_TEMPORAL_TERMINAL_MIN_PAUSE_MS
        ):
            category = "sentence_terminal"
            category_rank = 0
        elif (
            left_comma_boundary
            and left_shape["complete_main_clause"]
            and right_shape["complete_main_clause"]
            and pause_ms >= VISUAL_TEMPORAL_MIN_PAUSE_MS
        ):
            category = "complete_clause_boundary"
            category_rank = 1
        elif (
            left_comma_boundary
            and left_shape["fronted_nonfinite_introduction"]
            and right_shape["complete_main_clause"]
            and pause_ms >= VISUAL_TEMPORAL_MIN_PAUSE_MS
        ):
            category = "fronted_introduction_boundary"
            category_rank = 2
            allowed_left_issues = {
                "visual_open_phrase_fragment",
                "visual_short_subject_or_connector_fragment",
                "visual_connector_led_noun_phrase_fragment",
            }
        else:
            base_reasons.append("no_supported_display_unit_boundary")

        disallowed_display_issues = [
            issue for issue in left_issues if issue not in allowed_left_issues
        ] + [
            issue
            for issue in right_issues
            if not (
                right_shape["complete_main_clause"]
                and issue == "visual_connector_led_noun_phrase_fragment"
            )
        ]
        if disallowed_display_issues:
            base_reasons.append("display_fragment")

        return {
            "cuts": [[left.word_end, right.word_start]],
            "word_counts": word_counts,
            "character_counts": character_counts,
            "display_durations_ms": display_durations_ms,
            "display_duration_floors_ms": duration_floor,
            "pause_ms": pause_ms,
            "category": category,
            "category_rank": category_rank,
            "left": left.original,
            "right": right.original,
            "hard_issues": list(evaluation.get("hard_issues") or []),
            "soft_issues": list(evaluation.get("soft_issues") or []),
            "hard_fragment_issues": disallowed_display_issues,
            "left_display_issues": left_issues,
            "right_display_issues": right_issues,
            "left_clause_shape": left_shape,
            "right_clause_shape": right_shape,
            "evaluation": evaluation,
            "rejection_reasons": list(dict.fromkeys(base_reasons)),
            "eligible": not base_reasons,
            "selected": False,
        }

    def _visual_temporal_clause_shape(self, item: ScreenSubtitleItem) -> Dict[str, bool]:
        """Classify one local display unit with the existing local spaCy model."""
        nlp = self._load_syntax_nlp()
        if not nlp:
            return {
                "complete_main_clause": False,
                "fronted_nonfinite_introduction": False,
            }
        doc = nlp(self._normalize_text(item.original))
        root = next((token for token in doc if token.dep_ == "ROOT"), None)
        if root is None:
            return {
                "complete_main_clause": False,
                "fronted_nonfinite_introduction": False,
            }
        root_is_finite = (
            root.pos_ in {"VERB", "AUX"}
            and root.tag_ not in {"VB", "VBG", "VBN"}
        )
        root_has_finite_auxiliary = bool(
            root.pos_ == "VERB"
            and root.tag_ in {"VB", "VBG", "VBN"}
            and any(
                child.dep_ in {"aux", "auxpass"}
                and child.tag_ in {"MD", "VBD", "VBP", "VBZ"}
                for child in root.children
            )
        )
        leading_subordinator = any(
            token.i < root.i
            and (token.dep_ == "mark" or token.pos_ == "SCONJ")
            for token in doc
        )
        normalized = self._normalize_text(item.original)
        # spaCy uses VB for both a bare infinitive and an imperative.  A
        # terminal imperative such as "Consider the evidence." is a complete
        # display unit, while "To consider the evidence" is not.  Keep the
        # distinction local to this visual stage: no source text, timing, or
        # structural-cut rule is changed.
        root_is_imperative = bool(
            root.pos_ == "VERB"
            and root.tag_ == "VB"
            and not leading_subordinator
            and bool(re.search(r"[.!?][\"')\]]*\s*$", normalized))
            and not any(
                child.dep_ in {"nsubj", "nsubjpass", "csubj", "expl"}
                for child in root.children
            )
            and not any(
                token.i < root.i
                and token.lower_ == "to"
                and token.head == root
                and token.dep_ in {"aux", "mark"}
                for token in doc
            )
        )
        comma_terminated = bool(re.search(r"[,;:]\s*$", normalized))
        has_nonfinite_action = any(
            token.pos_ in {"VERB", "AUX"}
            and token.tag_ in {"VB", "VBG", "VBN"}
            for token in doc
        )
        fronted_nonfinite = (
            comma_terminated
            and root.pos_ in {"VERB", "AUX", "ADP"}
            and not root_is_finite
            and not root_has_finite_auxiliary
            and has_nonfinite_action
            and not leading_subordinator
        )
        return {
            "complete_main_clause": bool(
                (root_is_finite or root_has_finite_auxiliary or root_is_imperative)
                and not leading_subordinator
            ),
            "fronted_nonfinite_introduction": bool(fronted_nonfinite),
        }

    def _safe_overlong_item_split(
        self,
        item: ScreenSubtitleItem,
    ) -> tuple[List[ScreenSubtitleItem], List[Dict]]:
        return self._safe_item_split_for_budget(
            item,
            word_limit=self.max_english_words,
            reject_orphaned_finite_predicate=True,
        )

    def _safe_item_split_for_budget(
        self,
        item: ScreenSubtitleItem,
        *,
        word_limit: int,
        character_limit: Optional[int] = None,
        require_independent_display_units: bool = False,
        reject_orphaned_finite_predicate: bool = False,
    ) -> tuple[List[ScreenSubtitleItem], List[Dict]]:
        if item.subtitle_id or item.word_start is None or item.word_end is None:
            return [], []
        if item.word_end <= item.word_start:
            return [], []
        candidates_considered: List[Dict] = []
        best: Optional[tuple] = None
        for cut in range(item.word_start + 3, item.word_end - 2):
            left = self._item_from_word_span(item.word_start, cut)
            right = self._item_from_word_span(cut + 1, item.word_end)
            if not left or not right:
                continue
            word_counts = [self._word_count(left.original), self._word_count(right.original)]
            evaluation = self._evaluate_item_pair_for_final_boundary(left, right)
            right_fragment = self._evaluate_final_display_fragment(right, left, None)
            hard_fragment_issues = list(
                dict.fromkeys(
                    list(evaluation.get("hard_fragment_issues") or [])
                    + list(right_fragment.get("hard_fragment_issues") or [])
                )
            )
            character_counts = [
                self._visible_english_character_count(left.original),
                self._visible_english_character_count(right.original),
            ]
            visual_display_issues: List[str] = []
            continuation_display_issues: List[str] = []
            if require_independent_display_units:
                visual_display_issues = list(
                    dict.fromkeys(
                        self._visual_split_display_unit_issues(left, None, right)
                        + self._visual_split_display_unit_issues(right, left, None)
                    )
                )
            if reject_orphaned_finite_predicate:
                continuation_display_issues = self._pre_id_continuation_display_issues(
                    left,
                    right,
                )
            candidate = {
                "cuts": [[cut, cut + 1]],
                "word_counts": word_counts,
                "character_counts": character_counts,
                "word_limit": word_limit,
                "character_limit": character_limit,
                "hard_issues": list(evaluation.get("hard_issues") or []),
                "hard_fragment_issues": hard_fragment_issues,
                "visual_display_issues": visual_display_issues,
                "continuation_display_issues": continuation_display_issues,
                "boundary_scores": [float(evaluation.get("boundary_score") or 0.0)],
            }
            candidates_considered.append(candidate)
            if (
                candidate["hard_issues"]
                or candidate["hard_fragment_issues"]
                or candidate["visual_display_issues"]
                or candidate["continuation_display_issues"]
                or any(count > word_limit for count in word_counts)
                or (
                    character_limit is not None
                    and any(count > character_limit for count in character_counts)
                )
                or not self._items_are_continuous(left, right)
                or self._items_cross_speaker(left, right)
                or self._internal_sentence_transition_word_index(left) is not None
                or self._internal_sentence_transition_word_index(right) is not None
            ):
                continue
            score = (
                len(evaluation.get("soft_issues") or []),
                float(candidate["boundary_scores"][0]),
                abs(word_counts[0] - word_counts[1]),
                abs(character_counts[0] - character_counts[1]),
                abs(word_counts[0] - 9),
                cut,
            )
            if best is None or score < best[:6]:
                best = (*score, [left, right])
        return (best[6], candidates_considered) if best else ([], candidates_considered)

    def _orphaned_finite_predicate_issues(
        self,
        item: ScreenSubtitleItem,
    ) -> List[str]:
        """Reject a repair that puts a finite predicate in a subjectless cue."""
        nlp = self._load_syntax_nlp()
        if not nlp:
            return []
        text = self._normalize_text(item.original)
        if not text:
            return []
        try:
            doc = nlp(text)
        except Exception:
            return []
        root = next((token for token in doc if token.dep_ == "ROOT"), None)
        if root is None:
            return []
        has_subject = any(
            child.dep_ in {"nsubj", "nsubjpass", "csubj", "expl"}
            for child in root.children
        )
        root_is_finite = (
            root.pos_ in {"VERB", "AUX"}
            and root.tag_ not in {"VB", "VBG", "VBN"}
        )
        root_has_finite_auxiliary = bool(
            root.pos_ == "VERB"
            and root.tag_ in {"VB", "VBG", "VBN"}
            and any(
                child.dep_ in {"aux", "auxpass"}
                and child.tag_ in {"MD", "VBD", "VBP", "VBZ"}
                for child in root.children
            )
        )
        imperative = bool(
            root.pos_ == "VERB"
            and root.tag_ == "VB"
            and re.search(r"[.!?][\"')\]]*\s*$", text)
            and not has_subject
        )
        if (root_is_finite or root_has_finite_auxiliary) and not has_subject and not imperative:
            return ["right_orphaned_finite_predicate"]
        return []

    def _pre_id_continuation_display_issues(
        self,
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
    ) -> List[str]:
        """Keep pre-ID repairs from creating a continuation-only display cue."""
        issues: List[str] = []
        left_display_issues = self._visual_split_display_unit_issues(
            left,
            None,
            right,
        )
        right_display_issues = self._visual_split_display_unit_issues(
            right,
            left,
            None,
        )
        if "visual_connector_led_noun_phrase_fragment" in left_display_issues:
            issues.append("left_connector_led_noun_phrase_fragment")
        if "visual_preposition_led_fragment" in right_display_issues:
            issues.append("right_preposition_led_fragment")
        issues.extend(self._orphaned_finite_predicate_issues(right))
        return list(dict.fromkeys(issues))

    def _is_parallel_prepositional_list_continuation(
        self,
        item: ScreenSubtitleItem,
        previous_item: Optional[ScreenSubtitleItem],
    ) -> bool:
        """Keep a comma-delimited parallel prepositional list readable."""
        if previous_item is None:
            return False
        current_words = [word.casefold() for word in self._word_tokens(item.original)]
        if not current_words:
            return False
        previous_text = self._normalize_text(previous_item.original)
        if not re.search(r",[\"')\]]*\s*$", previous_text):
            return False
        previous_words = {
            word.casefold()
            for word in self._word_tokens(previous_text)
        }
        return current_words[0] in previous_words

    def _visual_split_display_unit_issues(
        self,
        item: ScreenSubtitleItem,
        previous_item: Optional[ScreenSubtitleItem],
        next_item: Optional[ScreenSubtitleItem],
    ) -> List[str]:
        """Reject visual-only splits that leave a non-readable display unit.

        The structural cut gate intentionally permits some short phrases when
        they are necessary for the 16-word hard limit.  The visual budget is
        optional, so it has a stricter contract: it may split only when both
        new cues can stand on screen as independently readable units.
        """
        fragment = self._evaluate_final_display_fragment(
            item,
            previous_item,
            next_item,
        )
        issues = list(fragment.get("hard_fragment_issues") or [])
        if fragment.get("is_independent_response"):
            return issues

        text = self._normalize_text(item.original)
        words = [word.casefold() for word in self._word_tokens(text)]
        if not words:
            return issues
        word_count = len(words)
        has_finite_predicate = bool(fragment.get("has_finite_predicate"))
        has_terminal_punctuation = bool(re.search(r"[.!?]\s*$", text))
        leading_prepositions = {
            "about", "after", "around", "at", "before", "between", "by",
            "for", "from", "in", "into", "of", "on", "over", "through",
            "to", "under", "with", "without",
        }
        leading_connectors = {"and", "but", "or", "so", "yet"}

        # A short preposition-led phrase, or an unfinished phrase ending with
        # comma-like punctuation, reads as a continuation even when the
        # structural syntax gate has no hard dependency to protect.
        if not has_finite_predicate and words[0] in leading_prepositions:
            issues.append("visual_preposition_led_fragment")
        if word_count <= 5 and not has_finite_predicate:
            if re.search(r"[,;:]\s*$", text):
                issues.append("visual_open_phrase_fragment")
            if words[0] in leading_connectors or self._looks_like_subject_without_predicate(words):
                issues.append("visual_short_subject_or_connector_fragment")
            if words[0] in {"how", "what", "why", "when", "where", "whether"}:
                issues.append("visual_open_clause_fragment")

        # A connector followed by a determiner-led noun phrase remains an
        # unfinished display until its main clause is reached.  This stays
        # deliberately short-range so ordinary multi-clause sentences remain
        # eligible for a visual split at a genuine clause boundary.
        if (
            word_count <= 8
            and not has_finite_predicate
            and words[0] in leading_connectors
            and any(word in self._stable_determiners() for word in words[1:4])
        ):
            issues.append("visual_connector_led_noun_phrase_fragment")

        # Keep embedded question/degree clauses intact.  A split inside
        # "how fast this is evolving" can leave two grammatical-looking but
        # incomplete displays, so detect the local clause shape rather than a
        # sample-specific phrase.
        if (
            previous_item is not None
            and word_count <= 4
            and words[0] in {"this", "that", "it", "they", "we", "you", "he", "she"}
        ):
            previous_words = [
                word.casefold()
                for word in self._word_tokens(previous_item.original)
            ]
            if any(word in {"how", "what", "why", "when", "where", "whether"} for word in previous_words[-3:]):
                issues.append("visual_embedded_clause_fragment")

        # Do not use a visual-only split to end a cue on a preposition or an
        # auxiliary.  The final fragment gate catches many of these already;
        # this keeps the visual stage self-contained when it evaluates a
        # candidate before the final gate runs.
        if not has_terminal_punctuation:
            if words[-1] in {"how", "what", "why", "when", "where", "whether"}:
                issues.append("visual_trailing_clause_intro_fragment")
            if words[-1] in leading_prepositions:
                issues.append("visual_trailing_preposition_fragment")
            if words[-1] in {
                "am", "is", "are", "was", "were", "be", "been", "being",
                "do", "does", "did", "have", "has", "had",
                "can", "could", "will", "would", "shall", "should", "may", "might", "must",
            }:
                issues.append("visual_trailing_auxiliary_fragment")

        return list(dict.fromkeys(issues))

    def _validate_final_display_fragments(
        self,
        items: Sequence[ScreenSubtitleItem],
    ) -> List[ScreenSubtitleItem]:
        result = list(items)
        index = 0
        safety_iterations = 0
        while index < len(result):
            safety_iterations += 1
            if safety_iterations > max(1000, len(result) * 8):
                logger.warning("Final pre-ID fragment repair stopped by safety iteration guard")
                break
            previous_item = result[index - 1] if index > 0 else None
            next_item = result[index + 1] if index < len(result) - 1 else None
            fragment = self._evaluate_final_display_fragment(
                result[index],
                previous_item,
                next_item,
            )
            if fragment["is_valid"]:
                index += 1
                continue
            boundary_index = index if next_item is not None else index - 1
            if boundary_index < 0:
                self._record_pre_id_boundary_repair(
                    repaired_by="_validate_final_display_fragments",
                    old_items=[result[index]],
                    new_items=None,
                    evaluation={
                        "hard_issues": fragment["hard_fragment_issues"],
                        "soft_issues": fragment["soft_fragment_issues"],
                        "fragment_type": fragment["fragment_type"],
                    },
                    repair_reason="unresolved_final_fragment_issue",
                    candidates_considered=[],
                )
                index += 1
                continue
            repaired = self._repair_pre_id_boundary_window(
                result,
                boundary_index,
                {
                    "hard_issues": fragment["hard_fragment_issues"],
                    "soft_issues": fragment["soft_fragment_issues"],
                    "fragment_type": fragment["fragment_type"],
                    "pause_ms": None,
                    "boundary_score": 0.0,
                },
            )
            if repaired is None:
                self._record_pre_id_boundary_repair(
                    repaired_by="_validate_final_display_fragments",
                    old_items=[result[index]],
                    new_items=None,
                    evaluation={
                        "hard_issues": fragment["hard_fragment_issues"],
                        "soft_issues": fragment["soft_fragment_issues"],
                        "fragment_type": fragment["fragment_type"],
                    },
                    repair_reason="unresolved_final_fragment_issue",
                    candidates_considered=[],
                )
                index += 1
                continue
            start, end, new_items, candidates = repaired
            old_items = result[start:end]
            self._record_pre_id_boundary_repair(
                repaired_by="_validate_final_display_fragments",
                old_items=old_items,
                new_items=new_items,
                evaluation={
                    "hard_issues": fragment["hard_fragment_issues"],
                    "soft_issues": fragment["soft_fragment_issues"],
                    "fragment_type": fragment["fragment_type"],
                },
                repair_reason=(
                    "forced_overflow_syntax_split"
                    if any(
                        candidate.get("selected")
                        and candidate.get("forced_overflow_fallback")
                        for candidate in candidates
                    )
                    else "hard_fragment_repaired"
                ),
                candidates_considered=candidates,
            )
            result[start:end] = new_items
            index = max(0, start - 1)
        return result

    def _split_internal_sentence_transition_items(
        self,
        items: Sequence[ScreenSubtitleItem],
    ) -> List[ScreenSubtitleItem]:
        result: List[ScreenSubtitleItem] = []
        source_items = list(items)
        for index, item in enumerate(source_items):
            transition_index = self._internal_sentence_transition_word_index(item)
            if transition_index is None or item.word_start is None or item.word_end is None:
                result.append(item)
                continue
            left = self._item_from_word_span(
                item.word_start,
                transition_index - 1,
                require_alpha=False,
            )
            right = self._item_from_word_span(transition_index, item.word_end)
            if not left or not right:
                result.append(item)
                continue
            candidate_gate = self._can_apply_pre_id_repair_candidate(
                [item],
                [left, right],
                previous_item=source_items[index - 1] if index > 0 else None,
                next_item=source_items[index + 1] if index + 1 < len(source_items) else None,
            )
            if not candidate_gate["accepted"]:
                result.append(item)
                continue
            self._record_pre_id_boundary_repair(
                repaired_by="_validate_and_repair_final_pre_id_boundaries",
                old_items=[item],
                new_items=[left, right],
                evaluation={
                    "legal": False,
                    "hard_issues": ["transition_attached_to_previous_sentence"],
                    "soft_issues": [],
                    "boundary_score": 0.0,
                    "protected_syntax": False,
                    "pause_ms": None,
                    "fragment_type": "",
                    "candidate_gate": candidate_gate,
                },
                repair_reason="internal_transition_split",
                candidates_considered=[],
            )
            result.extend([left, right])
        return result

    def _internal_sentence_transition_word_index(
        self,
        item: ScreenSubtitleItem,
    ) -> Optional[int]:
        if item.word_start is None or item.word_end is None:
            return None
        if item.word_end <= item.word_start:
            return None
        entries = self._active_word_entries
        for index in range(item.word_start + 1, item.word_end + 1):
            token = self._clean_boundary_token(entries[index].get("token") or "")
            if token not in self._sentence_transition_tokens():
                continue
            surface = str(entries[index].get("surface") or "")
            previous_surface = str(entries[index - 1].get("surface") or "")
            if surface[:1].isupper() or re.search(r"[.!?]\s*$", previous_surface):
                return index
        return None

    def _evaluate_item_boundary(
        self,
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
    ) -> Dict:
        if left.word_end is None or right.word_start is None:
            return {
                "legal": True,
                "hard_issues": [],
                "soft_issues": [],
                "boundary_score": 0.0,
                "protected_syntax": False,
                "pause_ms": None,
            }
        return self._evaluate_stable_cut_boundary(
            left.word_end,
            right.word_start,
            source_start=min(left.word_start, right.word_start),
            source_end=max(left.word_end, right.word_end),
        )

    def _evaluate_item_pair_for_final_boundary(
        self,
        left: ScreenSubtitleItem,
        right: Optional[ScreenSubtitleItem],
        previous_item: Optional[ScreenSubtitleItem] = None,
    ) -> Dict:
        if right is None:
            evaluation = {
                "legal": True,
                "hard_issues": [],
                "soft_issues": [],
                "boundary_score": 0.0,
                "protected_syntax": False,
                "pause_ms": None,
            }
        else:
            evaluation = self._evaluate_item_boundary(left, right)
        hard_issues = list(evaluation.get("hard_issues") or [])
        continuation_display_issues = (
            self._orphaned_finite_predicate_issues(right)
            if right is not None
            else []
        )
        for issue in continuation_display_issues:
            if issue not in hard_issues:
                hard_issues.append(issue)
        fragment_evaluation = self._evaluate_final_display_fragment(
            left,
            previous_item,
            right,
        )
        for issue in fragment_evaluation["hard_fragment_issues"]:
            if issue not in hard_issues:
                hard_issues.append(issue)
        result = dict(evaluation)
        result["hard_issues"] = hard_issues
        result["hard_fragment_issues"] = fragment_evaluation["hard_fragment_issues"]
        result["soft_fragment_issues"] = fragment_evaluation["soft_fragment_issues"]
        result["fragment_type"] = fragment_evaluation["fragment_type"]
        result["continuation_display_issues"] = continuation_display_issues
        result["legal"] = not hard_issues
        return result

    def _evaluate_final_display_fragment(
        self,
        item: ScreenSubtitleItem,
        previous_item: Optional[ScreenSubtitleItem],
        next_item: Optional[ScreenSubtitleItem],
    ) -> Dict:
        text = self._normalize_text(item.original)
        words = [word.casefold() for word in self._word_tokens(text)]
        word_count = len(words)
        duration_ms = self._short_item_duration_ms(item)
        speaker_id = self._item_speaker(item)
        result = {
            "is_valid": True,
            "hard_fragment_issues": [],
            "soft_fragment_issues": [],
            "fragment_type": "",
            "word_count": word_count,
            "duration_ms": duration_ms,
            "has_finite_predicate": self._fragment_has_finite_predicate(words),
            "has_independent_meaning": False,
            "is_independent_response": False,
            "speaker_id": speaker_id,
            "word_start": item.word_start,
            "word_end": item.word_end,
            "repairable_with_neighbors": False,
        }
        if item.subtitle_id or not words:
            return result
        if self._is_allowed_independent_short_item(item, previous_item, next_item):
            result["is_independent_response"] = True
            result["has_independent_meaning"] = True
            return result

        can_attach_next = bool(
            next_item is not None
            and self._items_are_continuous(item, next_item)
            and not self._items_cross_speaker(item, next_item)
            and not (
                (pause := self._boundary_pause_ms(item, next_item)) is not None
                and pause >= 450
            )
        )
        can_attach_previous = bool(
            previous_item is not None
            and self._items_are_continuous(previous_item, item)
            and not self._items_cross_speaker(previous_item, item)
            and not (
                (previous_pause := self._boundary_pause_ms(previous_item, item)) is not None
                and previous_pause >= 450
            )
        )
        result["repairable_with_neighbors"] = can_attach_next or can_attach_previous
        if not result["repairable_with_neighbors"]:
            return result

        issues: List[str] = []
        if word_count == 1 and words[0] in {"we", "they", "he", "she", "it", "i", "you"}:
            issues.append("pronoun_only_fragment")
        if word_count == 1 and words[0] in self._stable_determiners():
            issues.append("incomplete_short_fragment")
        if self._is_standalone_transition_text(text):
            issues.append("standalone_transition_fragment")
        if word_count == 1 and words[0] in {"and", "but", "or", "so"}:
            issues.append("standalone_connector_fragment")
        if word_count == 1 and words[0] in {"itself", "himself", "herself", "themselves", "ourselves"}:
            issues.append("trailing_reflexive_fragment")
        if self._internal_sentence_transition_word_index(item) is not None:
            issues.append("transition_attached_to_previous_sentence")
        if word_count == 1 and self._is_plain_content_word(words[0]):
            issues.append("incomplete_short_fragment")
        if 1 <= word_count <= 2 and all(self._token_is_numeric_like(word) for word in words):
            issues.append("incomplete_short_fragment")
        if (
            word_count <= 3
            and not result["has_finite_predicate"]
            and self._looks_like_subject_without_predicate(words)
        ):
            issues.append("weak_subject_fragment")
        if word_count <= 4 and self._looks_like_incomplete_interrogative_fragment(words):
            issues.append("incomplete_interrogative_fragment")
        if self._looks_like_negation_or_emphasis_fragment(words):
            issues.append("negation_or_emphasis_fragment")
        if (
            previous_item is not None
            and words[0] in {"of", "for", "with", "by", "from", "at", "in", "on", "around", "as", "to"}
            and not result["has_finite_predicate"]
            and not self._is_parallel_prepositional_list_continuation(
                item,
                previous_item,
            )
        ):
            issues.append("leading_prepositional_fragment")
        if self._looks_like_incomplete_bare_verb_fragment(item, words, next_item):
            issues.append("incomplete_short_fragment")
        trailing_issue = self._trailing_dependent_fragment_issue(item, next_item)
        if trailing_issue:
            issues.append(trailing_issue)

        hard = list(dict.fromkeys(issues))
        result["hard_fragment_issues"] = hard
        result["fragment_type"] = hard[0] if hard else ""
        result["is_valid"] = not hard
        result["has_independent_meaning"] = bool(result["has_finite_predicate"] and word_count >= 4)
        return result

    def _trailing_dependent_fragment_issue(
        self,
        item: ScreenSubtitleItem,
        next_item: Optional[ScreenSubtitleItem],
    ) -> str:
        if next_item is None:
            return ""
        if item.subtitle_id or next_item.subtitle_id:
            return ""
        if not self._items_are_continuous(item, next_item):
            return ""
        if self._items_cross_speaker(item, next_item):
            return ""
        pause = self._boundary_pause_ms(item, next_item)
        if pause is not None and pause >= 450:
            return ""
        words = [word.casefold() for word in self._word_tokens(item.original)]
        next_words = [word.casefold() for word in self._word_tokens(next_item.original)]
        if not words or not next_words:
            return ""
        last = words[-1]
        next_first = next_words[0]
        surface = self._normalize_text(item.original)
        if re.search(r"[.!?]\s*$", surface):
            return ""
        if self._is_protected_named_phrase_split(last, next_first):
            return "trailing_protected_named_phrase_fragment"
        if self._is_protected_phrasal_boundary(last, next_first):
            return "trailing_protected_phrasal_fragment"
        if last in {"and", "but", "or", "so"}:
            return "trailing_connector_fragment"
        if last in {
            "am", "is", "are", "was", "were", "be", "been", "being",
            "do", "does", "did", "have", "has", "had",
            "can", "could", "will", "would", "shall", "should", "may", "might", "must",
            "it's", "that's", "there's", "he's", "she's", "what's",
        }:
            return "trailing_auxiliary_fragment"
        if last.endswith("'s") and self._token_looks_noun_like(next_first):
            return "trailing_possessive_fragment"
        if last in {"all", "both", "either", "neither"} and (
            next_first in self._stable_determiners() or self._token_looks_noun_like(next_first)
        ):
            return "trailing_quantifier_fragment"
        if (
            self._looks_like_adjective_before_noun(last, next_first)
            and not self._looks_like_allowed_sentence_final_adjective(last)
        ):
            return "trailing_modifier_fragment"
        return ""

    def _weak_fragment_issues(
        self,
        item: ScreenSubtitleItem,
        previous_item: Optional[ScreenSubtitleItem],
        next_item: Optional[ScreenSubtitleItem],
    ) -> List[str]:
        return list(
            self._evaluate_final_display_fragment(
                item,
                previous_item,
                next_item,
            ).get("hard_fragment_issues", [])
        )

    def _is_allowed_independent_short_item(
        self,
        item: ScreenSubtitleItem,
        previous_item: Optional[ScreenSubtitleItem],
        next_item: Optional[ScreenSubtitleItem],
    ) -> bool:
        text = self._normalize_text(item.original)
        normalized = re.sub(r"[^a-z?\s]", " ", text.casefold())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        normalized_words = normalized.rstrip("?")
        if normalized_words in {"yes", "no", "really", "right", "exactly", "okay", "ok"} and re.search(r"[.!?]\s*$", text):
            return True
        if previous_item and self._items_cross_speaker(previous_item, item):
            return True
        if next_item and self._items_cross_speaker(item, next_item):
            return True
        return False

    @classmethod
    def _is_standalone_transition_text(cls, text: str) -> bool:
        normalized = re.sub(r"[^a-z\s]", " ", (text or "").casefold())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        transition_phrases = {
            "so",
            "and",
            "but",
            "alternatively",
            "however",
            "therefore",
            "instead",
            "meanwhile",
            "in fact",
            "for example",
            "on the other hand",
        }
        return normalized in transition_phrases

    @staticmethod
    def _is_plain_content_word(token: str) -> bool:
        return bool(token) and token not in {
            "yes", "no", "really", "right", "exactly", "okay", "ok",
            "so", "and", "but", "or",
        }

    @staticmethod
    def _looks_like_subject_without_predicate(words: Sequence[str]) -> bool:
        if not words:
            return False
        finite_or_aux = {
            "am", "is", "are", "was", "were", "be", "been", "being",
            "do", "does", "did", "have", "has", "had",
            "can", "could", "will", "would", "shall", "should", "may", "might", "must",
            "isn't", "aren't", "wasn't", "weren't", "haven't", "hasn't", "hadn't",
            "don't", "doesn't", "didn't", "can't", "couldn't", "won't", "wouldn't",
            "tend", "tends", "need", "needs", "needed",
        }
        if any(word in finite_or_aux for word in words):
            return False
        if words[0] in {"yeah", "so", "well", "and", "but"} and len(words) >= 2:
            return True
        if words[0] in {"a", "an", "the", "this", "that", "these", "those"}:
            return True
        if words[-1] in {"i", "you", "we", "they", "he", "she", "it"}:
            return True
        return len(words) <= 3 and words[0] in {"i", "you", "we", "they", "he", "she", "it", "this", "that", "those"}

    @classmethod
    def _fragment_has_finite_predicate(cls, words: Sequence[str]) -> bool:
        finite_or_aux = {
            "am", "is", "are", "was", "were", "be", "been", "being",
            "do", "does", "did", "have", "has", "had",
            "can", "could", "will", "would", "shall", "should", "may", "might", "must",
            "isn't", "aren't", "wasn't", "weren't", "haven't", "hasn't", "hadn't",
            "don't", "doesn't", "didn't", "can't", "couldn't", "won't", "wouldn't",
            "tend", "tends", "need", "needs", "needed",
        }
        common_past_or_present_verbs = {
            "changed", "worked", "reported", "started", "ended", "matters",
            "matter", "happened", "became", "felt", "seemed",
        }
        return any(
            word in finite_or_aux
            or word in common_past_or_present_verbs
            or word.endswith("n't")
            for word in words
        )

    @staticmethod
    def _looks_like_incomplete_interrogative_fragment(words: Sequence[str]) -> bool:
        if not words:
            return False
        if words[0] not in {"how", "what", "why", "where", "when", "who", "which"}:
            return False
        finite_or_aux = {
            "am", "is", "are", "was", "were", "do", "does", "did",
            "can", "could", "will", "would", "should", "have", "has", "had",
        }
        return not any(word in finite_or_aux for word in words)

    @staticmethod
    def _looks_like_negation_or_emphasis_fragment(words: Sequence[str]) -> bool:
        if not words:
            return False
        return all(word in {"never", "ever", "not"} for word in words)

    def _looks_like_incomplete_bare_verb_fragment(
        self,
        item: ScreenSubtitleItem,
        words: Sequence[str],
        next_item: Optional[ScreenSubtitleItem],
    ) -> bool:
        if next_item is None or not words or len(words) > 4:
            return False
        if not self._items_are_continuous(item, next_item) or self._items_cross_speaker(item, next_item):
            return False
        pause = self._boundary_pause_ms(item, next_item)
        if pause is not None and pause >= 450:
            return False
        surface = self._normalize_text(item.original)
        if re.search(r"[.!?]\s*$", surface):
            return False
        bare_verbs = {
            "open", "build", "make", "take", "create", "turn", "move", "put",
            "bring", "keep", "hold", "push", "pull", "drive",
        }
        if words[0] not in bare_verbs:
            return False
        if words[-1] in self._stable_determiners():
            return True
        if re.search(r"[,;:]\s*$", surface) and not self._fragment_has_finite_predicate(words):
            return True
        next_words = [word.casefold() for word in self._word_tokens(next_item.original)]
        return bool(next_words and self._looks_like_adjective_before_noun(words[-1], next_words[0]))

    def _short_item_duration_ms(self, item: ScreenSubtitleItem) -> int:
        timing = self._item_word_timing(item)
        if not timing:
            return 0
        return max(0, int(timing[1]) - int(timing[0]))

    def _repair_pre_id_boundary_window(
        self,
        items: Sequence[ScreenSubtitleItem],
        boundary_index: int,
        evaluation: Dict,
    ) -> Optional[tuple[int, int, List[ScreenSubtitleItem], List[Dict]]]:
        if boundary_index < 0 or boundary_index >= len(items) - 1:
            return None
        target_boundary = self._pre_id_boundary_pair(
            items[boundary_index],
            items[boundary_index + 1],
        )
        if target_boundary is None:
            return None
        is_fragment_repair = bool(
            evaluation.get("fragment_type") or evaluation.get("hard_fragment_issues")
        )
        attempts = [
            (boundary_index, boundary_index + 2),
            (max(0, boundary_index - 1), boundary_index + 1),
            (max(0, boundary_index - 1), min(len(items), boundary_index + 2)),
            (boundary_index, min(len(items), boundary_index + 3)),
        ]
        seen = set()
        for start, end in attempts:
            if end - start < 2 or (start, end) in seen:
                continue
            seen.add((start, end))
            window = list(items[start:end])
            if (
                not is_fragment_repair
                and target_boundary not in self._pre_id_boundary_pairs(window)
            ):
                continue
            allowed_long_pause_boundary = (
                target_boundary
                if "right_orphaned_finite_predicate"
                in (evaluation.get("continuation_display_issues") or [])
                else None
            )
            if not self._can_repair_pre_id_window(
                window,
                allowed_long_pause_boundary=allowed_long_pause_boundary,
            ):
                continue
            direct = self._direct_merge_weak_fragment_window(window, evaluation)
            if direct and self._pre_id_repair_resolves_target_boundary(
                window,
                direct,
                target_boundary,
                require_target_removal=not is_fragment_repair,
            ):
                gate = self._can_apply_pre_id_repair_candidate(
                    window,
                    direct,
                    previous_item=items[start - 1] if start > 0 else None,
                    next_item=items[end] if end < len(items) else None,
                    allowed_hard_issues=evaluation.get("allowed_hard_issues") or (),
                    structural_overflow_fragment_issues=(
                        evaluation.get("hard_issues") or ()
                    ),
                )
                direct_candidate = {
                    "cuts": [],
                    "word_counts": [self._word_count(item.original) for item in direct],
                    "hard_issues": [],
                    "hard_fragment_issues": [],
                    "boundary_scores": [],
                    "candidate_gate": gate,
                }
                if gate["accepted"]:
                    return start, end, direct, [
                        direct_candidate
                    ]
                # A rejected direct merge can still leave a legal repartition
                # inside this same window.  Continue with the existing local
                # candidate search instead of treating the merge rejection as
                # a window-level failure.
            repaired, candidates = self._repartition_pre_id_window(window)
            if not repaired and self._requires_forced_overflow_repartition(window, evaluation):
                repaired, forced_candidates = self._repartition_pre_id_window(
                    window,
                    allowed_hard_issues={
                        "verb_complement_split",
                        "short_verb_complement_split",
                        "short_verb_object_split",
                    },
                    forced_overflow_fallback=True,
                )
                candidates.extend(forced_candidates)
                if repaired:
                    selected_cuts = {
                        (left.word_end, right.word_start)
                        for left, right in zip(repaired, repaired[1:])
                    }
                    for candidate in forced_candidates:
                        candidate_cuts = {
                            tuple(cut)
                            for cut in candidate.get("cuts", [])
                            if len(cut) == 2
                        }
                        candidate["selected"] = candidate_cuts == selected_cuts
            if not repaired:
                continue
            if self._pre_id_repair_resolves_target_boundary(
                window,
                repaired,
                target_boundary,
                require_target_removal=not is_fragment_repair,
            ):
                accepted = False
                for candidate in candidates:
                    candidate_cuts = {
                        tuple(cut)
                        for cut in candidate.get("cuts", [])
                        if isinstance(cut, (list, tuple)) and len(cut) == 2
                    }
                    repaired_cuts = {
                        (left.word_end, right.word_start)
                        for left, right in zip(repaired, repaired[1:])
                    }
                    if candidate_cuts == repaired_cuts:
                        gate = self._can_apply_pre_id_repair_candidate(
                            window,
                            repaired,
                            previous_item=items[start - 1] if start > 0 else None,
                            next_item=items[end] if end < len(items) else None,
                            allowed_hard_issues=evaluation.get("allowed_hard_issues") or (),
                        )
                        candidate["candidate_gate"] = gate
                        accepted = bool(gate["accepted"])
                        break
                if accepted:
                    return start, end, repaired, candidates
        return None

    def _can_apply_pre_id_repair_candidate(
        self,
        old_items: Sequence[ScreenSubtitleItem],
        new_items: Sequence[ScreenSubtitleItem],
        *,
        previous_item: Optional[ScreenSubtitleItem] = None,
        next_item: Optional[ScreenSubtitleItem] = None,
        allowed_hard_issues: Sequence[str] = (),
        structural_overflow_fragment_issues: Sequence[str] = (),
    ) -> Dict:
        """Validate a pre-ID candidate before it can replace frozen word spans.

        The candidate is evaluated against the original word ledger.  This is
        the single write gate for local boundary repairs: it verifies exact
        coverage, checks every new internal and edge boundary, and checks each
        newly created display item with the same fragment evaluator used by
        final validation.
        """
        allowed = set(allowed_hard_issues or ())
        allows_structural_overflow = self._is_allowed_pre_id_structural_overflow_merge(
            old_items,
            new_items,
            structural_overflow_fragment_issues,
        )
        reasons: List[str] = []
        hard_issues: List[str] = []
        fragment_issues: List[str] = []

        if not new_items:
            reasons.append("empty_candidate")
        if any(item.subtitle_id for item in new_items):
            reasons.append("subtitle_id_already_assigned")
        if self._items_word_tokens(old_items) != self._items_word_tokens(new_items):
            reasons.append("word_order_changed")
        if self._items_word_range(old_items) != self._items_word_range(new_items):
            reasons.append("word_coverage_changed")

        for left, right in zip(new_items, new_items[1:]):
            if not self._items_are_continuous(left, right):
                reasons.append("non_continuous_word_range")
            if self._items_cross_speaker(left, right):
                reasons.append("speaker_change")
            evaluation = self._evaluate_item_pair_for_final_boundary(left, right)
            hard_issues.extend(evaluation.get("hard_issues") or [])

        # The first and last edge boundaries were not internal to the
        # candidate, but a repartition can still change their neighboring
        # text. Only evaluate an edge when its word-range boundary is new;
        # otherwise an unrelated pre-existing audit warning would veto a
        # candidate that did not touch that edge.
        old_context = list(old_items)
        if previous_item is not None:
            old_context.insert(0, previous_item)
        if next_item is not None:
            old_context.append(next_item)
        old_context_boundaries = self._pre_id_boundary_pairs(old_context)
        edge_pairs = []
        if previous_item is not None and new_items:
            edge_pairs.append((previous_item, new_items[0]))
        if next_item is not None and new_items:
            edge_pairs.append((new_items[-1], next_item))
        for left, right in edge_pairs:
            if self._pre_id_boundary_pair(left, right) in old_context_boundaries:
                continue
            if not self._items_are_continuous(left, right):
                reasons.append("non_continuous_word_range")
            if self._items_cross_speaker(left, right):
                reasons.append("speaker_change")
            hard_issues.extend(
                self._evaluate_item_boundary(left, right).get("hard_issues") or []
            )

        for index, item in enumerate(new_items):
            fragment = self._evaluate_final_display_fragment(
                item,
                new_items[index - 1] if index > 0 else previous_item,
                new_items[index + 1] if index + 1 < len(new_items) else next_item,
            )
            fragment_issues.extend(fragment.get("hard_fragment_issues") or [])
            if self._is_ordinary_one_word_fragment(item.original):
                reasons.append("ordinary_one_word_fragment")
            if (
                self._word_count(item.original) > self.max_english_words
                and not allows_structural_overflow
            ):
                reasons.append("max_english_words_exceeded")

        hard_issues = list(dict.fromkeys(issue for issue in hard_issues if issue not in allowed))
        fragment_issues = list(dict.fromkeys(fragment_issues))
        reasons.extend(hard_issues)
        reasons.extend(fragment_issues)
        reasons = list(dict.fromkeys(reasons))
        return {
            "accepted": not reasons,
            "reasons": reasons,
            "hard_issues": hard_issues,
            "hard_fragment_issues": fragment_issues,
            "allowed_hard_issues": sorted(allowed),
            "structural_english_overflow_exception": allows_structural_overflow,
            "old_word_range": self._items_word_range(old_items),
            "new_word_range": self._items_word_range(new_items),
            "old_word_count": len(self._items_word_tokens(old_items)),
            "new_word_count": len(self._items_word_tokens(new_items)),
        }

    def _is_allowed_pre_id_structural_overflow_merge(
        self,
        old_items: Sequence[ScreenSubtitleItem],
        new_items: Sequence[ScreenSubtitleItem],
        fragment_issues: Sequence[str],
    ) -> bool:
        """Allow one complete 17-19 word cue only while removing a hard fragment.

        This is deliberately narrower than the final validation warning: it is
        only available to the direct two-cue fragment merge path before IDs
        exist.  The shared structural-overflow check proves that no legal
        normal-limit split exists, so the exception cannot grant a visual or
        general repartitioning path permission to create an overlong cue.
        """
        high_confidence_fragment_issues = {
            "weak_subject_fragment",
            "incomplete_interrogative_fragment",
            "trailing_modifier_fragment",
            "trailing_protected_named_phrase_fragment",
            "trailing_protected_phrasal_fragment",
            "leading_prepositional_fragment",
            "right_orphaned_finite_predicate",
            "trailing_possessive_fragment",
            "trailing_quantifier_fragment",
        }
        if (
            len(old_items) != 2
            or len(new_items) != 1
            or not set(fragment_issues or ()).intersection(high_confidence_fragment_issues)
        ):
            return False
        merged = new_items[0]
        if (
            merged.subtitle_id
            or merged.word_start is None
            or merged.word_end is None
        ):
            return False
        text = self._normalize_text(merged.original)
        word_count = self._word_count(text)
        if word_count <= self.max_english_words or word_count > self.max_english_words + 3:
            return False
        segment = ASRDataSeg(text, 0, 0, "")
        segment.word_start = merged.word_start
        segment.word_end = merged.word_end
        return self._is_allowed_structural_english_overflow(
            segment,
            text,
            word_count,
            self.max_english_words,
        )

    def _requires_forced_overflow_repartition(
        self,
        items: Sequence[ScreenSubtitleItem],
        evaluation: Dict,
    ) -> bool:
        """Permit one auditable least-bad split only for an unsplittable tail.

        A strict grammar boundary can occasionally conflict with the finite
        display limit, producing a long line followed by a dependent 1-3 word
        tail.  This narrow fallback never applies to ordinary prose or an
        independent short response: it is limited to a continuous two-item
        window whose strict repartition has already failed.
        """
        if len(items) != 2 or not (evaluation.get("hard_issues") or []):
            return False
        counts = [self._word_count(item.original) for item in items]
        return bool(
            max(counts, default=0) > self.max_english_words
            and min(counts, default=0) <= 3
            and sum(counts) <= self.max_english_words * 2
        )

    @staticmethod
    def _pre_id_boundary_pair(
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
    ) -> Optional[tuple[int, int]]:
        if left.word_end is None or right.word_start is None:
            return None
        return int(left.word_end), int(right.word_start)

    @classmethod
    def _pre_id_boundary_pairs(
        cls,
        items: Sequence[ScreenSubtitleItem],
    ) -> set[tuple[int, int]]:
        return {
            pair
            for pair in (
                cls._pre_id_boundary_pair(left, right)
                for left, right in zip(items, items[1:])
            )
            if pair is not None
        }

    @classmethod
    def _pre_id_repair_resolves_target_boundary(
        cls,
        old_items: Sequence[ScreenSubtitleItem],
        new_items: Sequence[ScreenSubtitleItem],
        target_boundary: tuple[int, int],
        *,
        require_target_removal: bool,
    ) -> bool:
        """Reject no-op repairs while allowing a fragment to merge left or right."""
        old_boundaries = cls._pre_id_boundary_pairs(old_items)
        new_boundaries = cls._pre_id_boundary_pairs(new_items)
        if old_boundaries == new_boundaries:
            return False
        if not require_target_removal:
            return True
        return target_boundary in old_boundaries and target_boundary not in new_boundaries

    def _direct_merge_weak_fragment_window(
        self,
        items: Sequence[ScreenSubtitleItem],
        evaluation: Dict,
    ) -> List[ScreenSubtitleItem]:
        weak_codes = {
            "weak_subject_fragment",
            "standalone_transition_fragment",
            "incomplete_short_fragment",
            "pronoun_only_fragment",
            "incomplete_interrogative_fragment",
            "negation_or_emphasis_fragment",
            "standalone_connector_fragment",
            "trailing_reflexive_fragment",
            "trailing_connector_fragment",
            "trailing_auxiliary_fragment",
            "trailing_possessive_fragment",
            "trailing_quantifier_fragment",
            "trailing_modifier_fragment",
            "trailing_protected_named_phrase_fragment",
            "trailing_protected_phrasal_fragment",
            "leading_prepositional_fragment",
            "right_orphaned_finite_predicate",
        }
        if len(items) != 2:
            return []
        candidate_issues = list(evaluation.get("hard_issues") or [])
        candidate_issues.extend(evaluation.get("hard_fragment_issues") or [])
        if not any(issue in weak_codes for issue in candidate_issues):
            return []
        merged = self._merge_subtitle_items(items[0], items[1])
        if (
            self._word_count(merged.original) > self.max_english_words
            and not self._is_allowed_pre_id_structural_overflow_merge(
                items,
                [merged],
                candidate_issues,
            )
        ):
            return []
        if self._internal_sentence_transition_word_index(merged) is not None:
            return []
        if self._ends_with_dependent_boundary_token(merged.original):
            return []
        if self._weak_fragment_issues(merged, None, None):
            return []
        return [merged]

    @classmethod
    def _ends_with_dependent_boundary_token(cls, text: str) -> bool:
        if re.search(r"[.!?]\s*$", text or ""):
            return False
        words = [word.casefold() for word in cls._word_tokens(text)]
        if not words:
            return False
        last = words[-1]
        if last in {"and", "but", "or", "so"}:
            return True
        if last in cls._stable_determiners():
            return True
        return last in {
            "am", "is", "are", "was", "were", "be", "been", "being",
            "do", "does", "did", "have", "has", "had",
            "can", "could", "will", "would", "shall", "should", "may", "might", "must",
            "it's", "that's", "there's", "he's", "she's", "what's",
        }

    def _can_repair_pre_id_window(
        self,
        items: Sequence[ScreenSubtitleItem],
        *,
        allowed_long_pause_boundary: Optional[tuple[int, int]] = None,
    ) -> bool:
        if len(items) < 2 or len(items) > 3:
            return False
        if any(item.subtitle_id for item in items):
            return False
        for left, right in zip(items, items[1:]):
            if not self._items_are_continuous(left, right):
                return False
            if self._items_cross_speaker(left, right):
                return False
            pause = self._boundary_pause_ms(left, right)
            boundary = self._pre_id_boundary_pair(left, right)
            if (
                pause is not None
                and pause >= 450
                and boundary != allowed_long_pause_boundary
            ):
                return False
        return True

    def _repartition_pre_id_window(
        self,
        items: Sequence[ScreenSubtitleItem],
        *,
        allowed_hard_issues: Optional[set[str]] = None,
        forced_overflow_fallback: bool = False,
    ) -> tuple[List[ScreenSubtitleItem], List[Dict]]:
        span_start = items[0].word_start
        span_end = items[-1].word_end
        if span_start is None or span_end is None or span_end <= span_start:
            return [], []
        target_count = len(items)
        candidates_considered: List[Dict] = []
        allowed_hard_issues = set(allowed_hard_issues or set())
        best: Optional[tuple[int, float, float, float, List[ScreenSubtitleItem]]] = None
        if target_count == 2:
            candidate_cuts = [(cut,) for cut in range(span_start, span_end)]
        else:
            candidate_cuts = [
                (left_cut, right_cut)
                for left_cut in range(span_start, span_end - 1)
                for right_cut in range(left_cut + 1, span_end)
            ]
        for cuts in candidate_cuts:
            ranges = self._ranges_from_cuts(span_start, span_end, cuts)
            parts = [self._item_from_word_span(start, end) for start, end in ranges]
            if any(part is None for part in parts):
                continue
            candidate_items = [part for part in parts if part is not None]
            word_counts = [self._word_count(item.original) for item in candidate_items]
            hard_issues: List[str] = []
            hard_fragment_issues: List[str] = []
            continuation_display_issues: List[str] = []
            boundary_scores: List[float] = []
            for boundary_index, (left, right) in enumerate(zip(candidate_items, candidate_items[1:])):
                evaluation = self._evaluate_item_pair_for_final_boundary(
                    left,
                    right,
                    candidate_items[boundary_index - 1] if boundary_index > 0 else None,
                )
                hard_issues.extend(evaluation["hard_issues"])
                hard_fragment_issues.extend(evaluation.get("hard_fragment_issues", []))
                continuation_display_issues.extend(
                    self._pre_id_continuation_display_issues(left, right)
                )
                boundary_scores.append(float(evaluation["boundary_score"]))
            if candidate_items:
                trailing_evaluation = self._evaluate_item_pair_for_final_boundary(
                    candidate_items[-1],
                    None,
                    candidate_items[-2] if len(candidate_items) > 1 else None,
                )
                hard_issues.extend(trailing_evaluation["hard_issues"])
                hard_fragment_issues.extend(trailing_evaluation.get("hard_fragment_issues", []))
            candidate_record = {
                "cuts": [list(cut) for cut in zip(cuts, [cut + 1 for cut in cuts])],
                "word_counts": word_counts,
                "hard_issues": list(dict.fromkeys(hard_issues)),
                "hard_fragment_issues": list(dict.fromkeys(hard_fragment_issues)),
                "continuation_display_issues": list(
                    dict.fromkeys(continuation_display_issues)
                ),
                "boundary_scores": boundary_scores,
            }
            relaxed_hard_issues = [
                issue
                for issue in candidate_record["hard_issues"]
                if issue in allowed_hard_issues
            ]
            if relaxed_hard_issues:
                candidate_record["relaxed_hard_issues"] = relaxed_hard_issues
                candidate_record["forced_overflow_fallback"] = forced_overflow_fallback
            candidates_considered.append(candidate_record)
            disallowed_hard_issues = [
                issue
                for issue in candidate_record["hard_issues"]
                if issue not in allowed_hard_issues
            ]
            if (
                disallowed_hard_issues
                or hard_fragment_issues
                or continuation_display_issues
            ):
                continue
            if any(count > self.max_english_words for count in word_counts):
                continue
            if any(self._internal_sentence_transition_word_index(item) is not None for item in candidate_items):
                continue
            if any(self._is_ordinary_one_word_fragment(item.original) for item in candidate_items):
                continue
            if any(
                self._splits_discourse_marker(left.original, right.original)
                for left, right in zip(candidate_items, candidate_items[1:])
            ):
                continue
            balance = max(word_counts) - min(word_counts)
            score = (
                len(relaxed_hard_issues),
                balance,
                sum(boundary_scores),
                sum(abs(count - self.max_english_words * 0.72) for count in word_counts),
            )
            if best is None or score < best[:4]:
                best = (score[0], score[1], score[2], score[3], candidate_items)
        return (best[4], candidates_considered) if best else ([], candidates_considered)

    @staticmethod
    def _ranges_from_cuts(
        span_start: int,
        span_end: int,
        cuts: Sequence[int],
    ) -> List[tuple[int, int]]:
        ranges: List[tuple[int, int]] = []
        cursor = span_start
        for cut in cuts:
            ranges.append((cursor, cut))
            cursor = cut + 1
        ranges.append((cursor, span_end))
        return ranges

    def _record_pre_id_boundary_repair(
        self,
        *,
        repaired_by: str,
        old_items: Sequence[ScreenSubtitleItem],
        new_items: Optional[Sequence[ScreenSubtitleItem]],
        evaluation: Dict,
        repair_reason: str,
        candidates_considered: Sequence[Dict],
        unresolved_is_hard: bool = True,
    ) -> None:
        old_cut = (
            [old_items[0].word_end, old_items[1].word_start]
            if len(old_items) >= 2
            else None
        )
        new_cuts = [
            [left.word_end, right.word_start]
            for left, right in zip(new_items or [], (new_items or [])[1:])
        ]
        allowed_hard_issues = set(evaluation.get("allowed_hard_issues") or [])
        hard_after = [
            [
                issue
                for issue in self._evaluate_item_pair_for_final_boundary(
                    left,
                    right,
                    (new_items or [])[index - 1] if index > 0 else None,
                ).get("hard_issues", [])
                if issue not in allowed_hard_issues
            ]
            for index, (left, right) in enumerate(zip(new_items or [], (new_items or [])[1:]))
        ]
        hard_fragment_after = [
            self._evaluate_final_display_fragment(
                item,
                (new_items or [])[index - 1] if index > 0 else None,
                (new_items or [])[index + 1] if index + 1 < len(new_items or []) else None,
            ).get("hard_fragment_issues", [])
            for index, item in enumerate(new_items or [])
        ]
        self._pre_id_boundary_repairs.append(
            {
                "repaired_by": repaired_by,
                "old_cut_word_index": old_cut,
                "new_cut_word_index": new_cuts,
                "repair_reason": repair_reason,
                "fragment_type": evaluation.get("fragment_type", ""),
                "hard_issues": list(evaluation.get("hard_issues") or []),
                "allowed_hard_issues": sorted(allowed_hard_issues),
                "soft_issues": list(evaluation.get("soft_issues") or []),
                "hard_fragment_issues": list(evaluation.get("hard_fragment_issues") or []),
                "soft_fragment_issues": list(evaluation.get("soft_fragment_issues") or []),
                "visual_reading_budget": dict(evaluation.get("visual_reading_budget") or {}),
                "visual_temporal_category": str(evaluation.get("visual_temporal_category") or ""),
                "display_durations_ms": list(evaluation.get("display_durations_ms") or []),
                "hard_issues_before": list(evaluation.get("hard_issues") or []),
                "hard_issues_after": hard_after,
                "hard_fragment_issues_after": hard_fragment_after,
                "pause_ms": evaluation.get("pause_ms"),
                "boundary_score": evaluation.get("boundary_score"),
                "created_by_stage": repaired_by,
                "old_boundary": old_cut,
                "new_boundary": new_cuts,
                "fragment_index": None,
                "fragment_text": self._normalize_text(old_items[0].original) if len(old_items) == 1 else "",
                "neighbor_indices": [
                    [item.word_start, item.word_end]
                    for item in old_items
                ],
                "old_items": [
                    self._item_to_span_dict(index, item)
                    for index, item in enumerate(old_items, 1)
                ],
                "new_items": [
                    self._item_to_span_dict(index, item)
                    for index, item in enumerate(new_items or [], 1)
                ],
                "local_items_before": [
                    self._item_to_span_dict(index, item)
                    for index, item in enumerate(old_items, 1)
                ],
                "local_items_after": [
                    self._item_to_span_dict(index, item)
                    for index, item in enumerate(new_items or [], 1)
                ],
                "candidate_boundaries_considered": list(candidates_considered),
                "candidate_splits": list(candidates_considered),
                "chosen_split": new_cuts,
                "rejected_candidates": [
                    candidate
                    for candidate in candidates_considered
                    if candidate.get("hard_issues") or candidate.get("hard_fragment_issues")
                ],
                "created_new_issue": any(bool(issue) for issue in hard_after + hard_fragment_after),
                "word_order_preserved": self._items_word_tokens(old_items) == self._items_word_tokens(new_items or old_items),
                "word_coverage_preserved": self._items_word_range(old_items) == self._items_word_range(new_items or old_items),
                "timestamp_preserved": True,
                "speaker_boundary_preserved": True,
                "repair_attempted": True,
                "repair_succeeded": new_items is not None,
                "unresolved_hard_issue": new_items is None and unresolved_is_hard,
                "unresolved_visual_warning": new_items is None and not unresolved_is_hard,
                "unresolved_reason": "" if new_items is not None else repair_reason,
            }
        )

    def _items_word_tokens(self, items: Sequence[ScreenSubtitleItem]) -> List[str]:
        return [
            token.casefold()
            for item in items
            for token in self._word_tokens(item.original)
        ]

    @staticmethod
    def _items_word_range(items: Sequence[ScreenSubtitleItem]) -> Optional[List[int]]:
        starts = [item.word_start for item in items if item.word_start is not None]
        ends = [item.word_end for item in items if item.word_end is not None]
        if not starts or not ends:
            return None
        return [min(starts), max(ends)]

    def _assign_global_subtitle_ids(
        self, items: Sequence[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        assigned: List[ScreenSubtitleItem] = []
        self._frozen_subtitle_ids = []
        for index, item in enumerate(items, 1):
            subtitle_id = item.subtitle_id or f"S{index:04d}"
            self._frozen_subtitle_ids.append(subtitle_id)
            assigned.append(
                ScreenSubtitleItem(
                    source_ids=item.source_ids,
                    original=item.original,
                    translated=item.translated,
                    word_start=item.word_start,
                    word_end=item.word_end,
                    subtitle_id=subtitle_id,
                )
            )
        self._set_chinese_cache_contract(assigned)
        return assigned

    def _capture_boundary_snapshot(
        self,
        stage: str,
        items: Sequence[ScreenSubtitleItem],
        *,
        changed_by: str,
        previous_items: Optional[Sequence[ScreenSubtitleItem]],
    ) -> None:
        ordered = self._sort_items_by_word_span(list(items))
        self._boundary_snapshot_item_sets[stage] = list(ordered)
        boundaries = self._boundary_records_for_items(ordered, created_by=changed_by)
        snapshot = {
            "stage": stage,
            "created_by": changed_by,
            "item_count": len(ordered),
            "boundary_count": len(boundaries),
            "boundaries": boundaries,
        }
        self._boundary_snapshots.append(snapshot)
        if previous_items is None:
            self._boundary_snapshot_changes.append(
                {
                    "stage": stage,
                    "created_by": changed_by,
                    "change_type": "initial_dp_boundaries",
                    "changes": [
                        {
                            "old_cut": None,
                            "new_cut": record.get("cut"),
                            "old_boundary": None,
                            "new_boundary": record,
                        }
                        for record in boundaries
                    ],
                }
            )
            return
        changes = self._boundary_changes_between_items(
            previous_items,
            ordered,
            changed_by=changed_by,
        )
        self._boundary_snapshot_changes.append(
            {
                "stage": stage,
                "created_by": changed_by,
                "change_type": "postprocess_boundary_delta",
                "changes": changes,
            }
        )

    def _boundary_snapshot_items(self, stage: str) -> List[ScreenSubtitleItem]:
        return list((getattr(self, "_boundary_snapshot_item_sets", {}) or {}).get(stage, []))

    def _boundary_changes_between_items(
        self,
        previous_items: Sequence[ScreenSubtitleItem],
        current_items: Sequence[ScreenSubtitleItem],
        *,
        changed_by: str,
    ) -> List[Dict]:
        previous_records = self._boundary_records_for_items(previous_items, created_by=changed_by)
        current_records = self._boundary_records_for_items(current_items, created_by=changed_by)
        previous_by_cut = {tuple(record["cut"]): record for record in previous_records}
        current_by_cut = {tuple(record["cut"]): record for record in current_records}
        removed_cuts = [cut for cut in previous_by_cut if cut not in current_by_cut]
        added_cuts = [cut for cut in current_by_cut if cut not in previous_by_cut]
        changes: List[Dict] = []
        paired_added: set = set()
        for removed_cut in removed_cuts:
            old_record = previous_by_cut[removed_cut]
            matching_added = [
                cut
                for cut in added_cuts
                if cut not in paired_added
                and self._boundary_ranges_overlap(old_record, current_by_cut[cut])
            ]
            if matching_added:
                new_cut = min(matching_added, key=lambda cut: abs(int(cut[0]) - int(removed_cut[0])))
                paired_added.add(new_cut)
                changes.append(
                    {
                        "old_cut": removed_cut,
                        "new_cut": new_cut,
                        "old_boundary": old_record,
                        "new_boundary": current_by_cut[new_cut],
                        "created_or_modified_by": changed_by,
                        "change_type": "modified_boundary",
                    }
                )
            else:
                changes.append(
                    {
                        "old_cut": removed_cut,
                        "new_cut": None,
                        "old_boundary": old_record,
                        "new_boundary": None,
                        "created_or_modified_by": changed_by,
                        "change_type": "removed_boundary",
                    }
                )
        for added_cut in added_cuts:
            if added_cut in paired_added:
                continue
            changes.append(
                {
                    "old_cut": None,
                    "new_cut": added_cut,
                    "old_boundary": None,
                    "new_boundary": current_by_cut[added_cut],
                    "created_or_modified_by": changed_by,
                    "change_type": "created_boundary",
                }
            )
        return changes

    @staticmethod
    def _boundary_ranges_overlap(left: Dict, right: Dict) -> bool:
        left_range = left.get("combined_word_range") or []
        right_range = right.get("combined_word_range") or []
        if len(left_range) != 2 or len(right_range) != 2:
            return False
        return int(left_range[0]) <= int(right_range[1]) and int(right_range[0]) <= int(left_range[1])

    def _boundary_records_for_items(
        self,
        items: Sequence[ScreenSubtitleItem],
        *,
        created_by: str,
    ) -> List[Dict]:
        records: List[Dict] = []
        ordered = self._sort_items_by_word_span(list(items))
        for index, (left, right) in enumerate(zip(ordered, ordered[1:]), 1):
            if left.word_end is None or right.word_start is None:
                continue
            left_text = self._normalize_text(left.original)
            right_text = self._normalize_text(right.original)
            cut = (int(left.word_end), int(right.word_start))
            evaluation = self._evaluate_item_pair_for_final_boundary(
                left,
                right,
                ordered[index - 2] if index > 1 else None,
            )
            boundary_evaluation = self._evaluate_stable_cut_boundary(
                cut[0],
                cut[1],
                source_start=min(left.word_start, right.word_start),
                source_end=max(left.word_end, right.word_end),
            )
            bad_reasons = self._boundary_bad_cut_reasons(left_text, right_text)
            syntax_reasons = self._syntax_boundary_reasons(left_text, right_text)
            confidence_score = min(0.95, 0.65 + 0.12 * len(syntax_reasons)) if syntax_reasons else 0.0
            records.append(
                {
                    "index": index,
                    "cut": list(cut),
                    "created_or_modified_by": created_by,
                    "left_english": left_text,
                    "right_english": right_text,
                    "left_word_range": [left.word_start, left.word_end],
                    "right_word_range": [right.word_start, right.word_end],
                    "combined_word_range": [
                        min(left.word_start, right.word_start),
                        max(left.word_end, right.word_end),
                    ],
                    "left_word_count": self._word_count(left_text),
                    "right_word_count": self._word_count(right_text),
                    "pause_ms": evaluation["pause_ms"],
                    "boundary_score": evaluation["boundary_score"],
                    "legal": evaluation["legal"],
                    "hard_issues": evaluation["hard_issues"],
                    "soft_issues": evaluation["soft_issues"],
                    "fragment_type": evaluation.get("fragment_type", ""),
                    "repair_attempted": False,
                    "repair_succeeded": False,
                    "unresolved_reason": "",
                    "bad_cut_reasons": bad_reasons,
                    "syntax_boundary_reasons": syntax_reasons,
                    "protected_syntax_cut": boundary_evaluation["protected_syntax"],
                    "high_confidence_syntax_bad_cut": bool(syntax_reasons and confidence_score >= 0.75),
                    "syntax_confidence_score": round(confidence_score, 2),
                }
            )
        return records

    def _boundary_pause_ms(
        self,
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
    ) -> Optional[int]:
        left_timing = self._item_word_timing(left)
        right_timing = self._item_word_timing(right)
        if not left_timing or not right_timing:
            return None
        return int(right_timing[0] - left_timing[1])

    def _boundary_score_for_items(
        self,
        left: ScreenSubtitleItem,
        right: ScreenSubtitleItem,
    ) -> Optional[float]:
        if left.word_start is None or left.word_end is None:
            return None
        if right.word_start is None or right.word_end is None:
            return None
        return round(
            float(
                self._cut_boundary_score(
                    left.word_end,
                    right.word_start,
                    source_start=min(left.word_start, right.word_start),
                    source_end=max(left.word_end, right.word_end),
                )
            ),
            3,
        )

    def _boundary_bad_cut_reasons(self, left_text: str, right_text: str) -> List[str]:
        if not left_text or not right_text:
            return []
        left_words = left_text.split()
        right_words = right_text.split()
        if not left_words or not right_words:
            return []
        previous_last = self._clean_boundary_token(left_words[-1])
        current_first = self._clean_boundary_token(right_words[0])
        return self._bad_cut_reasons(previous_last, current_first)

    @staticmethod
    def _item_subtitle_id(item: ScreenSubtitleItem, fallback_index: int) -> str:
        return item.subtitle_id or f"S{fallback_index:04d}"

    @staticmethod
    def _segment_subtitle_id(seg: ASRDataSeg, fallback_index: int) -> str:
        return str(getattr(seg, "subtitle_id", "") or f"S{fallback_index:04d}")

    @classmethod
    def _copy_segment(
        cls,
        seg: ASRDataSeg,
        *,
        text: Optional[str] = None,
        translated_text: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        subtitle_id: Optional[str] = None,
    ) -> ASRDataSeg:
        copied = ASRDataSeg(
            text=seg.text if text is None else text,
            translated_text=seg.translated_text if translated_text is None else translated_text,
            start_time=seg.start_time if start_time is None else start_time,
            end_time=seg.end_time if end_time is None else end_time,
        )
        source_id = subtitle_id if subtitle_id is not None else getattr(seg, "subtitle_id", None)
        if source_id:
            copied.subtitle_id = source_id
        for attr in (
            "word_start",
            "word_end",
            "stable_word_start_ms",
            "stable_word_end_ms",
        ):
            if hasattr(seg, attr):
                setattr(copied, attr, getattr(seg, attr))
        return copied

    def rebuild_final_cue_timeline(
        self,
        asr_data: ASRData,
        word_ledger: ASRData,
        *,
        alignment_backend: str,
    ) -> ASRData:
        """Build the sole final cue timeline from frozen ID-bound word spans.

        This is intentionally after Chinese allocation and before export.  It
        changes no English, Chinese, subtitle IDs, word ranges, or ordering;
        it only updates ledger word times and derives each cue range from the
        exact frozen words that cue owns.
        """
        alignment_state = dict(getattr(self, "_final_timeline_alignment", {}) or {})
        if not alignment_state:
            alignment_state = {
                "requested_backend": str(alignment_backend or "stable-ts"),
                "applied_backend": str(alignment_backend or "stable-ts"),
                "fallback_used": False,
                "fallback_reason": "",
            }
        else:
            alignment_state["applied_backend"] = str(alignment_backend or "stable-ts")
        self._final_timeline_alignment = alignment_state

        self._final_cue_timeline_seed_errors = self._replace_frozen_word_timing(
            word_ledger,
            alignment_backend=alignment_backend,
        )
        self._final_cue_timeline_seed_errors.extend(
            self._reconcile_final_word_timing()
        )
        cues = self._final_timeline_cue_payload(asr_data.segments)
        words = self._final_timeline_word_payload()
        timeline = derive_final_cue_timeline(
            cues,
            words,
            expected_subtitle_ids=list(self._frozen_subtitle_ids),
            lead_in_ms=DISPLAY_LEAD_IN_MS,
            tail_padding_ms=DISPLAY_TAIL_PADDING_MS,
        )
        validation = final_cue_timeline_artifact(
            timeline.get("records") or [],
            words,
            expected_subtitle_ids=list(self._frozen_subtitle_ids),
            prior_errors=self._final_cue_timeline_seed_errors,
        ).get("validation") or {}
        timeline["validation"] = validation
        timeline["word_timing_reconciliations"] = list(
            getattr(self, "_final_word_timing_reconciliations", []) or []
        )
        timeline["alignment"] = dict(self._final_timeline_alignment)
        self._final_cue_timeline = timeline

        records_by_id = {
            str(record.get("subtitle_id") or ""): record
            for record in timeline.get("records") or []
        }
        segments_by_id: Dict[str, ASRDataSeg] = {}
        unexpected_segments: List[ASRDataSeg] = []
        for segment in asr_data.segments:
            subtitle_id = str(getattr(segment, "subtitle_id", "") or "")
            if subtitle_id in segments_by_id or subtitle_id not in self._frozen_subtitle_ids:
                unexpected_segments.append(segment)
                continue
            segments_by_id[subtitle_id] = segment

        rebuilt: List[ASRDataSeg] = []
        for subtitle_id in self._frozen_subtitle_ids:
            segment = segments_by_id.get(subtitle_id)
            if segment is None:
                continue
            record = records_by_id.get(subtitle_id)
            if record is None:
                rebuilt.append(self._copy_segment(segment))
                continue
            rebuilt_segment = self._copy_segment(
                segment,
                start_time=int(record["start_ms"]),
                end_time=int(record["end_ms"]),
            )
            rebuilt_segment.stable_word_start_ms = int(record["word_envelope_start_ms"])
            rebuilt_segment.stable_word_end_ms = int(record["word_envelope_end_ms"])
            rebuilt_segment.timing_backend = str(alignment_backend or "stable-ts")
            rebuilt.append(rebuilt_segment)
        # Keep invalid inputs visible to the final ID validator. They cannot
        # silently replace or reorder a frozen cue, and export is blocked.
        rebuilt.extend(self._copy_segment(segment) for segment in unexpected_segments)

        logger.info(
            "Final cue timeline rebuilt from frozen ledger: cues=%s errors=%s backend=%s",
            len(rebuilt),
            int(validation.get("error_count") or 0),
            alignment_backend,
        )
        return ASRData(rebuilt)

    def refresh_final_cue_timeline_artifact(
        self,
        segments: Sequence[ASRDataSeg],
    ) -> Dict[str, Any]:
        """Validate the exact final cue objects used by SRT and ASS writers."""
        artifact = final_cue_timeline_artifact(
            self._final_timeline_cue_payload(segments),
            self._final_timeline_word_payload(),
            expected_subtitle_ids=list(self._frozen_subtitle_ids),
            prior_errors=getattr(self, "_final_cue_timeline_seed_errors", []) or [],
        )
        artifact["word_timing_reconciliations"] = list(
            getattr(self, "_final_word_timing_reconciliations", []) or []
        )
        artifact["alignment"] = dict(
            getattr(self, "_final_timeline_alignment", {}) or {}
        )
        self._final_cue_timeline = artifact
        return artifact

    def record_final_timeline_alignment(
        self,
        *,
        requested_backend: str,
        applied_backend: str,
        fallback_reason: str = "",
        local_timing_fallbacks: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> None:
        """Record the selected and actual timing backend for final artifacts."""
        self._final_timeline_alignment = {
            "requested_backend": str(requested_backend or "stable-ts"),
            "applied_backend": str(applied_backend or "stable-ts"),
            "fallback_used": bool(fallback_reason or local_timing_fallbacks),
            "fallback_reason": str(fallback_reason or ""),
        }
        if local_timing_fallbacks:
            self._final_timeline_alignment["local_timing_fallbacks"] = [
                dict(item) for item in local_timing_fallbacks
            ]

    def _reconcile_final_word_timing(self) -> List[Dict[str, Any]]:
        """Resolve only adjacent word-envelope overlap before cue derivation."""
        result = reconcile_frozen_word_ledger(self._final_timeline_word_payload())
        self._final_word_timing_reconciliations = list(result.get("reconciliations") or [])
        for word in result.get("words") or []:
            word_id = int(word["word_id"])
            if word_id < 0 or word_id >= len(self._active_word_entries):
                continue
            self._active_word_entries[word_id]["start_time"] = int(word["start_ms"])
            self._active_word_entries[word_id]["end_time"] = int(word["end_ms"])
            self._active_word_entries[word_id]["alignment_source"] = str(
                word.get("alignment_source") or "stable-ts"
            )
        return list(result.get("errors") or [])

    def _replace_frozen_word_timing(
        self,
        word_ledger: ASRData,
        *,
        alignment_backend: str,
    ) -> List[Dict[str, Any]]:
        """Update timing fields only after proving the ledger identity is unchanged."""
        errors: List[Dict[str, Any]] = []
        by_word_id: Dict[int, ASRDataSeg] = {}
        for position, segment in enumerate(getattr(word_ledger, "segments", []) or []):
            try:
                word_id = int(getattr(segment, "word_id", position))
            except (TypeError, ValueError):
                errors.append({"code": "final_timeline_word_id_invalid", "position": position})
                continue
            if word_id in by_word_id:
                errors.append({"code": "final_timeline_word_id_duplicate", "word_id": word_id})
                continue
            by_word_id[word_id] = segment

        expected_word_ids = set(range(len(self._active_word_entries)))
        if set(by_word_id) != expected_word_ids:
            errors.append(
                {
                    "code": "final_timeline_word_id_set_mismatch",
                    "expected_word_count": len(expected_word_ids),
                    "returned_word_count": len(by_word_id),
                }
            )
            return errors

        for word_id in sorted(expected_word_ids):
            segment = by_word_id[word_id]
            entries = self._word_time_entries([segment])
            if len(entries) != 1:
                errors.append(
                    {
                        "code": "final_timeline_word_ledger_token_invalid",
                        "word_id": word_id,
                        "text": segment.text,
                    }
                )
                continue
            replacement = entries[0]
            current = self._active_word_entries[word_id]
            if replacement.get("token") != current.get("token"):
                errors.append(
                    {
                        "code": "final_timeline_word_ledger_text_mismatch",
                        "word_id": word_id,
                        "expected": current.get("surface") or current.get("token") or "",
                        "returned": replacement.get("surface") or replacement.get("token") or "",
                    }
                )
                continue
            current["start_time"] = int(replacement["start_time"])
            current["end_time"] = int(replacement["end_time"])
            current["alignment_source"] = str(
                getattr(segment, "alignment_source", "") or alignment_backend or "stable-ts"
            )
        return errors

    def _final_timeline_word_payload(self) -> List[Dict[str, Any]]:
        return [
            {
                "word_id": word_id,
                "surface": entry.get("surface") or entry.get("token") or "",
                "start_ms": int(entry.get("start_time") or 0),
                "end_ms": int(entry.get("end_time") or 0),
                "alignment_source": str(entry.get("alignment_source") or "stable-ts"),
            }
            for word_id, entry in enumerate(self._active_word_entries)
        ]

    def export_frozen_word_ledger(self) -> ASRData:
        """Export the authoritative final word ledger as one segment per word.

        Stable cutting expands source ASR segments into display words. Any
        alignment backend that runs after that expansion must consume these
        exact word IDs, rather than the coarser source ASR segment list.
        """
        words: List[ASRDataSeg] = []
        for word_id, entry in enumerate(self._active_word_entries):
            surface = str(entry.get("surface") or entry.get("token") or "").strip()
            if not surface:
                continue
            segment = ASRDataSeg(
                text=surface,
                start_time=int(entry.get("start_time") or 0),
                end_time=max(
                    int(entry.get("end_time") or 0),
                    int(entry.get("start_time") or 0) + 1,
                ),
            )
            segment.word_id = word_id
            segment.alignment_source = str(entry.get("alignment_source") or "stable-ts")
            segment.source_segment_ids = self._source_ids_for_word_range(word_id, word_id)
            words.append(segment)
        return ASRData(words)

    def _final_timeline_cue_payload(
        self,
        segments: Sequence[ASRDataSeg],
    ) -> List[Dict[str, Any]]:
        payload: List[Dict[str, Any]] = []
        for segment in segments:
            word_start = getattr(segment, "word_start", None)
            word_end = getattr(segment, "word_end", None)
            envelope_start = None
            envelope_end = None
            sources: List[str] = []
            if (
                isinstance(word_start, int)
                and isinstance(word_end, int)
                and 0 <= word_start <= word_end < len(self._active_word_entries)
            ):
                envelope_start = int(self._active_word_entries[word_start].get("start_time") or 0)
                envelope_end = int(self._active_word_entries[word_end].get("end_time") or 0)
                sources = sorted(
                    {
                        str(self._active_word_entries[index].get("alignment_source") or "stable-ts")
                        for index in range(word_start, word_end + 1)
                    }
                )
            payload.append(
                {
                    "subtitle_id": str(getattr(segment, "subtitle_id", "") or ""),
                    "word_start": word_start,
                    "word_end": word_end,
                    "word_envelope_start_ms": envelope_start,
                    "word_envelope_end_ms": envelope_end,
                    "start_ms": int(segment.start_time),
                    "end_ms": int(segment.end_time),
                    "word_alignment_sources": sources,
                }
            )
        return payload

    @classmethod
    def _segment_index_by_subtitle_id(
        cls, segments: Sequence[ASRDataSeg]
    ) -> Dict[str, int]:
        return {
            cls._segment_subtitle_id(seg, index): index - 1
            for index, seg in enumerate(segments, 1)
        }

    @staticmethod
    def _current_git_commit() -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def manifest_metadata(self) -> Dict:
        metadata = {
            "translation_model": self.model,
            "code_commit": self._current_git_commit(),
            "cache_used": self._llm_cache_used,
            "prompt_version": SCREEN_SUBTITLE_PROMPT_VERSION,
            "allocation_max_concurrency": self.allocation_max_concurrency,
            "allocation_batch_size": self.allocation_batch_size,
            "stable_chinese_cache_contract": dict(
                getattr(self, "_chinese_cache_contract", {}) or {}
            ),
            "llm_cache_stats": self._llm_cache_stats,
            "allocation_runtime_stats": self._allocation_runtime_stats,
            "qa_review_points_count": self._qa_review_points_count,
            "chinese_polish_enabled": bool(getattr(self, "enable_chinese_polish", False)),
            "chinese_polish_count": len(
                [item for item in getattr(self, "_chinese_polish_log", []) if item.get("decision") == "applied"]
            ),
            "chinese_polish_log": list(getattr(self, "_chinese_polish_log", []) or [])[:200],
            "final_cue_timeline_path": str(getattr(self, "_final_cue_timeline_path", "") or ""),
            "final_cue_timeline_validation": dict(
                (getattr(self, "_final_cue_timeline", {}) or {}).get("validation", {}) or {}
            ),
            "final_timeline_alignment": dict(
                getattr(self, "_final_timeline_alignment", {}) or {}
            ),
        }
        if self._qa_review_points_path:
            metadata["qa_review_points_srt"] = self._qa_review_points_path
        return metadata

    def _record_llm_cache_stat(self, task: str, hit: bool) -> None:
        key = str(task or "unknown")
        stats = self._llm_cache_stats.setdefault(key, {"hit": 0, "miss": 0})
        stats["hit" if hit else "miss"] += 1

    def _record_allocation_runtime_stat(self, key: str, value: Any) -> None:
        self._allocation_runtime_stats[str(key)] = value

    def _record_allocation_structure_attempt(
        self,
        errors: Sequence[Dict],
        *,
        stage: str,
        expected_group_ids: Sequence[int],
        batch_id: Optional[int] = None,
    ) -> None:
        """Preserve retryable fixed-ID response failures without blocking export.

        A successful retry replaces only the candidate allocation, never the
        evidence that the preceding model response violated the fixed-ID
        protocol.  Final ``translation_structure_errors`` remains reserved for
        failures that still affect the final subtitle timeline.
        """
        if not errors:
            return
        record = {
            "record_type": "allocation_structure_attempt",
            "status": "retry_required",
            "stage": str(stage),
            "expected_semantic_group_ids": [int(group_id) for group_id in expected_group_ids],
            "errors": [dict(error) for error in errors],
        }
        if batch_id is not None:
            record["batch_id"] = int(batch_id)
        self._last_allocation_validation.append(record)

    def _group_expected_subtitle_ids(self, group: Dict) -> List[str]:
        return [
            self._item_subtitle_id(item, int(group.get("start_index") or 0) + offset)
            for offset, item in enumerate(group.get("items") or [], 1)
        ]

    def _record_translation_structure_error(
        self,
        code: str,
        *,
        group_id: Optional[int] = None,
        expected_ids: Optional[Sequence[str]] = None,
        returned_ids: Optional[Sequence[str]] = None,
        duplicate_ids: Optional[Sequence[str]] = None,
        unknown_ids: Optional[Sequence[str]] = None,
        missing_ids: Optional[Sequence[str]] = None,
        message: str = "",
    ) -> None:
        issue = {
            "code": code,
            "message": message or code,
            "semantic_group_id": f"G{group_id:04d}" if group_id else "",
            "expected_subtitle_ids": list(expected_ids or []),
            "returned_subtitle_ids": list(returned_ids or []),
            "duplicate_subtitle_ids": list(duplicate_ids or []),
            "unknown_subtitle_ids": list(unknown_ids or []),
            "missing_subtitle_ids": list(missing_ids or []),
        }
        self._translation_structure_errors.append(issue)

    @staticmethod
    def _append_translation_structure_error(
        target: List[Dict],
        code: str,
        *,
        group_id: Optional[int] = None,
        expected_ids: Optional[Sequence[str]] = None,
        returned_ids: Optional[Sequence[str]] = None,
        duplicate_ids: Optional[Sequence[str]] = None,
        unknown_ids: Optional[Sequence[str]] = None,
        missing_ids: Optional[Sequence[str]] = None,
        message: str = "",
    ) -> None:
        target.append(
            {
                "code": code,
                "message": message or code,
                "semantic_group_id": f"G{group_id:04d}" if group_id else "",
                "expected_subtitle_ids": list(expected_ids or []),
                "returned_subtitle_ids": list(returned_ids or []),
                "duplicate_subtitle_ids": list(duplicate_ids or []),
                "unknown_subtitle_ids": list(unknown_ids or []),
                "missing_subtitle_ids": list(missing_ids or []),
            }
        )

    def _parse_id_bound_translations(
        self,
        group: Dict,
        expected_ids: Sequence[str],
        raw_parts: object,
    ) -> Dict[str, str]:
        return self._parse_id_bound_translations_into(
            group,
            expected_ids,
            raw_parts,
            self._translation_structure_errors,
            self._last_semantic_group_debug,
        )

    def _parse_id_bound_translations_into(
        self,
        group: Dict,
        expected_ids: Sequence[str],
        raw_parts: object,
        errors: List[Dict],
        debug: List[Dict],
    ) -> Dict[str, str]:
        group_id = int(group.get("id") or 0)
        expected_set = set(expected_ids)
        result: Dict[str, str] = {}
        returned_ids: List[str] = []
        duplicate_ids: List[str] = []
        unknown_ids: List[str] = []

        if not isinstance(raw_parts, list):
            self._append_translation_structure_error(
                errors,
                "translation_group_cardinality_mismatch",
                group_id=group_id,
                expected_ids=expected_ids,
                returned_ids=[],
                missing_ids=expected_ids,
                message="LLM returned no id-bound part_translations list.",
            )
            return result

        for part in raw_parts:
            if not isinstance(part, dict):
                self._append_translation_structure_error(
                    errors,
                    "translation_group_cardinality_mismatch",
                    group_id=group_id,
                    expected_ids=expected_ids,
                    returned_ids=returned_ids,
                    message="LLM returned legacy positional part_translations.",
                )
                continue
            subtitle_id = str(part.get("subtitle_id") or "").strip()
            chinese = str(
                part.get("zh")
                or part.get("chinese")
                or part.get("translation")
                or part.get("translated_text")
                or ""
            ).strip()
            if not subtitle_id:
                self._append_translation_structure_error(
                    errors,
                    "translation_id_missing",
                    group_id=group_id,
                    expected_ids=expected_ids,
                    returned_ids=returned_ids,
                    message="LLM returned a translation item without subtitle_id.",
                )
                continue
            returned_ids.append(subtitle_id)
            if subtitle_id in result:
                duplicate_ids.append(subtitle_id)
                self._append_translation_structure_error(
                    errors,
                    "translation_id_duplicate",
                    group_id=group_id,
                    expected_ids=expected_ids,
                    returned_ids=returned_ids,
                    duplicate_ids=[subtitle_id],
                    message=f"Duplicate translation subtitle_id: {subtitle_id}",
                )
                continue
            if subtitle_id not in expected_set:
                unknown_ids.append(subtitle_id)
                self._append_translation_structure_error(
                    errors,
                    "translation_id_unknown",
                    group_id=group_id,
                    expected_ids=expected_ids,
                    returned_ids=returned_ids,
                    unknown_ids=[subtitle_id],
                    message=f"Unknown translation subtitle_id: {subtitle_id}",
                )
                continue
            result[subtitle_id] = chinese

        missing_ids = [subtitle_id for subtitle_id in expected_ids if subtitle_id not in result]
        debug.append(
            {
                "semantic_group_id": f"G{group_id:04d}" if group_id else "",
                "expected_subtitle_ids": list(expected_ids),
                "returned_subtitle_ids": list(returned_ids),
                "mapped_subtitle_ids": list(result.keys()),
                "duplicate_subtitle_ids": list(duplicate_ids),
                "unknown_subtitle_ids": list(unknown_ids),
                "missing_subtitle_ids": list(missing_ids),
            }
        )
        if missing_ids:
            self._append_translation_structure_error(
                errors,
                "translation_id_missing",
                group_id=group_id,
                expected_ids=expected_ids,
                returned_ids=returned_ids,
                missing_ids=missing_ids,
                message="Missing translation subtitle_id(s).",
            )
        if set(returned_ids) != expected_set or duplicate_ids or unknown_ids:
            self._append_translation_structure_error(
                errors,
                "translation_group_cardinality_mismatch",
                group_id=group_id,
                expected_ids=expected_ids,
                returned_ids=returned_ids,
                duplicate_ids=duplicate_ids,
                unknown_ids=unknown_ids,
                missing_ids=missing_ids,
                message="Returned subtitle_id set does not match expected subtitle_id set.",
            )
        return result

    def _validate_final_item_translation_ids(
        self, items: Sequence[ScreenSubtitleItem]
    ) -> None:
        english_ids = [
            self._item_subtitle_id(item, index)
            for index, item in enumerate(items, 1)
        ]
        chinese_ids = [
            self._item_subtitle_id(item, index)
            for index, item in enumerate(items, 1)
            if (item.translated or "").strip()
        ]
        duplicate_ids = sorted(
            subtitle_id for subtitle_id in set(english_ids) if english_ids.count(subtitle_id) > 1
        )
        unknown_ids = sorted(set(chinese_ids) - set(english_ids))
        missing_ids = [subtitle_id for subtitle_id in english_ids if subtitle_id not in chinese_ids]
        expected = set(self._frozen_subtitle_ids or english_ids)
        if (
            set(english_ids) != expected
            or set(english_ids) != set(chinese_ids)
            or len(english_ids) != len(chinese_ids)
            or duplicate_ids
            or unknown_ids
            or missing_ids
        ):
            self._record_translation_structure_error(
                "final_translation_id_mismatch",
                expected_ids=english_ids,
                returned_ids=chinese_ids,
                duplicate_ids=duplicate_ids,
                unknown_ids=unknown_ids,
                missing_ids=missing_ids,
                message="Final English subtitle_id set and Chinese subtitle_id set do not match.",
            )

    def _validate_final_segment_translation_ids(
        self, segments: Sequence[ASRDataSeg]
    ) -> None:
        expected_ids = list(self._frozen_subtitle_ids)
        if not expected_ids:
            return
        segment_ids = [
            str(getattr(seg, "subtitle_id", "") or "").strip()
            for seg in segments
        ]
        if segment_ids and all(segment_ids):
            duplicate_ids = sorted(
                subtitle_id
                for subtitle_id in set(segment_ids)
                if segment_ids.count(subtitle_id) > 1
            )
            unknown_ids = sorted(set(segment_ids) - set(expected_ids))
            missing_ids = [subtitle_id for subtitle_id in expected_ids if subtitle_id not in segment_ids]
            mismatch = (
                set(segment_ids) != set(expected_ids)
                or len(segment_ids) != len(expected_ids)
                or duplicate_ids
                or unknown_ids
                or missing_ids
            )
        else:
            duplicate_ids = []
            unknown_ids = []
            missing_ids = (
                expected_ids[len(segments):]
                if len(segments) < len(expected_ids)
                else []
            )
            mismatch = len(segments) != len(expected_ids)
        if mismatch:
            self._record_translation_structure_error(
                "final_translation_id_mismatch",
                expected_ids=expected_ids,
                returned_ids=segment_ids,
                duplicate_ids=duplicate_ids,
                unknown_ids=unknown_ids,
                missing_ids=missing_ids,
                message="Final rendered subtitle segments do not preserve frozen subtitle_id coverage.",
            )

    def _order_segments_by_frozen_subtitle_ids(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        if not self._frozen_subtitle_ids:
            return list(segments)
        index_map = {subtitle_id: index for index, subtitle_id in enumerate(self._frozen_subtitle_ids)}
        return sorted(
            list(segments),
            key=lambda seg: (
                index_map.get(self._segment_subtitle_id(seg, 0), len(index_map)),
                seg.start_time,
                seg.end_time,
            ),
        )

    def _source_ids_for_word_range(self, word_start: int, word_end: int) -> List[int]:
        ids = [
            source_id
            for source_id, (span_start, span_end) in self._active_source_word_spans.items()
            if span_start <= word_end and span_end >= word_start
        ]
        return ids or [1]

    def _stable_sentence_word_spans(self) -> List[tuple[int, int]]:
        entries = self._active_word_entries
        if not entries:
            return []
        spans: List[tuple[int, int]] = []
        start = 0
        for index, entry in enumerate(entries):
            surface = str(entry.get("surface") or "")
            token = self._clean_boundary_token(entry.get("token") or "")
            count = index - start + 1
            if not re.search(r"[.!?]\s*$", surface):
                continue
            if count <= 2 and token in {"right", "yeah", "yes", "yep", "exactly", "okay", "ok", "wow"}:
                continue
            spans.append((start, index))
            start = index + 1
        if start < len(entries):
            spans.append((start, len(entries) - 1))
        return spans

    def _stable_word_ranges_for_span(
        self, span: tuple[int, int], target_words: Optional[int] = None
    ) -> List[tuple[int, int]]:
        # The configured value is a preferred display length, not a grammar
        # override. Normal cues stay within 16 words; 17-20 is reserved for a
        # rare structural exception when a shorter cut would be ungrammatical.
        target = max(1, min(target_words or self.max_english_words, 16))
        emergency = 20
        start, end = span
        if end < start:
            return []
        count = end - start + 1
        if count <= target:
            return [(start, end)]
        return self._stable_greedy_ranges(start, end, target, emergency)

    @staticmethod
    def _segment_length_score(length: int, target: int, emergency: int) -> float:
        score = abs(length - target) * 1.2
        if length <= 2:
            score += 28
        elif length <= 4:
            score += 8
        if length > target:
            score += (length - target) * 2.5
        if length > emergency:
            score += 10_000
        return score

    def _segment_boundary_score(
        self, left: int, right: int, source_start: int, source_end: int
    ) -> float:
        entries = self._active_word_entries
        if not entries:
            return 0.0
        score = 0.0
        first = self._clean_boundary_token(entries[left]["token"])
        last = self._clean_boundary_token(entries[right]["token"])
        prev_token = (
            self._clean_boundary_token(entries[left - 1]["token"])
            if left > source_start
            else ""
        )
        next_token = (
            self._clean_boundary_token(entries[right + 1]["token"])
            if right < source_end
            else ""
        )
        surface = str(entries[right].get("surface") or "")

        if right < source_end:
            gap = entries[right + 1]["start_time"] - entries[right]["end_time"]
            if gap >= 450:
                score -= 18
            elif gap >= 260:
                score -= 8
            elif gap <= 80:
                score += 2

            if re.search(r"[.!?]\s*$", surface):
                score -= 32
            elif re.search(r"[,;:]\s*$", surface):
                score -= 12

            if next_token in {"but", "however", "yet", "because", "although", "though", "if", "when", "where", "while"}:
                score -= 8
            if last in self._dangerous_segment_end_tokens():
                score += 32
            if next_token in self._dangerous_segment_start_tokens():
                score += 20
            if self._is_bad_boundary_pair(last, next_token):
                score += 45
            if (right, right + 1) in self._syntax_protected_cuts:
                score += 80

        if left > source_start:
            if first in self._dangerous_segment_start_tokens():
                score += 14
            if self._is_bad_boundary_pair(prev_token, first):
                score += 36
        return score

    def _cut_boundary_score(
        self, left: int, right: int, source_start: int, source_end: int
    ) -> float:
        entries = self._active_word_entries
        if not entries or left < source_start or right > source_end:
            return 0.0
        left_token = self._clean_boundary_token(entries[left]["token"])
        right_token = self._clean_boundary_token(entries[right]["token"])
        prev_token = (
            self._clean_boundary_token(entries[left - 1]["token"])
            if left > source_start
            else ""
        )
        left_surface = str(entries[left].get("surface") or "")
        gap = entries[right]["start_time"] - entries[left]["end_time"]
        score = 0.0
        if gap >= 450:
            score -= 28
        elif gap >= 260:
            score -= 12
        elif gap <= 80:
            score += 6

        if re.search(r"[.!?]\s*$", left_surface):
            score -= 52
        elif re.search(r"[,;:]\s*$", left_surface):
            score -= 18

        if right_token in {"but", "however", "yet", "because", "although", "though", "if", "when", "where", "while"}:
            score -= 10
        comma_before = bool(re.search(r"[,;:]\s*$", left_surface))
        if right_token in {"which", "who", "that"} and not comma_before:
            score += 20
        if left_token in self._dangerous_segment_end_tokens():
            score += 60
        if right_token in self._dangerous_segment_start_tokens() and not (
            comma_before and right_token in {"which", "who", "that"}
        ):
            score += 36
        if self._is_bad_boundary_pair(left_token, right_token):
            score += 160
        if self._looks_like_adjective_before_noun(left_token, right_token):
            score += 140
        if (left, right) in self._syntax_protected_cuts:
            score += 220
        if prev_token == "to" and right_token:
            score += 90
        if left_token.isdigit() and right_token:
            score += 70
        if left_token in {"right", "yeah", "yes", "yep", "exactly", "okay", "ok"} and re.search(r"[.!?]\s*$", left_surface):
            score += 24
        return score

    def _evaluate_stable_cut_boundary(
        self,
        left: int,
        right: int,
        *,
        source_start: Optional[int] = None,
        source_end: Optional[int] = None,
    ) -> Dict:
        entries = self._active_word_entries
        if not entries or left < 0 or right >= len(entries) or right != left + 1:
            return {
                "legal": True,
                "hard_issues": [],
                "soft_issues": [],
                "boundary_score": 0.0,
                "protected_syntax": False,
                "pause_ms": None,
            }
        if source_start is None:
            source_start = max(0, left - 8)
        if source_end is None:
            source_end = min(len(entries) - 1, right + 8)
        pause_ms = self._word_pause_ms(left, right)
        boundary_score = self._cut_boundary_score(
            left,
            right,
            source_start=source_start,
            source_end=source_end,
        )
        hard_issues = self._hard_stable_cut_issues(left, right, pause_ms)
        soft_issues = self._soft_stable_cut_issues(left, right)
        protected_syntax = (left, right) in self._syntax_protected_cuts
        if protected_syntax and "protected_syntax_cut" not in hard_issues:
            hard_issues.append("protected_syntax_cut")
        return {
            "legal": not hard_issues,
            "hard_issues": hard_issues,
            "soft_issues": soft_issues,
            "boundary_score": round(float(boundary_score), 3),
            "protected_syntax": protected_syntax,
            "pause_ms": pause_ms,
        }

    def _hard_stable_cut_issues(
        self,
        left: int,
        right: int,
        pause_ms: Optional[int],
    ) -> List[str]:
        entries = self._active_word_entries
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        prepositions = {
            "into", "of", "for", "with", "without", "in", "on", "at", "by",
            "from", "to", "about", "around", "through", "over", "under",
            "between", "among", "against", "within", "across",
        }
        # Some prepositions also occur as sentence-final adverbs or
        # complements (for example, "the era is over.").  A terminal
        # punctuation mark is an explicit sentence boundary and must win over
        # the token-only preposition heuristic.
        left_surface = str(entries[left].get("surface") or "")
        right_surface = str(entries[right].get("surface") or "")
        if self._is_unambiguous_sentence_terminal(left_surface, right_surface):
            return []
        left_is_open_preposition = (
            left_token in prepositions
            and right_token
            and not re.search(r"[.!?]\s*$", left_surface)
        )
        # A recognisable pause is useful evidence for ordinary clause
        # boundaries, but it cannot make an unbreakable phrase boundary legal.
        # Forced-alignment gaps around function words are common enough that
        # allowing them here produces visible function-word stranded cuts.
        strict_issues: List[str] = []
        if left_is_open_preposition:
            strict_issues.append("preposition_object_split")
        context_start = max(0, left - 4)
        context_end = min(len(entries) - 1, right + 4)
        context = [
            self._clean_boundary_token(entries[index].get("token") or "")
            for index in range(context_start, context_end + 1)
        ]
        boundary_offset = left - context_start
        if self._boundary_inside_determiner_numeric_noun(context, boundary_offset):
            strict_issues.append("determiner_numeric_noun_split")
        if self._boundary_inside_quantifier_phrase(context, boundary_offset):
            strict_issues.append("quantifier_phrase_split")
        if self._is_numeric_unit_or_noun_split(left, right):
            strict_issues.append("numeric_unit_or_noun_split")
        if self._is_numeric_magnitude_split(left, right):
            strict_issues.append("numeric_magnitude_split")
        if self._is_compound_preposition_split(left_token, right_token):
            strict_issues.append("compound_preposition_split")
        if self._is_auxiliary_predicate_split(left_token, right_token):
            strict_issues.append("auxiliary_predicate_split")
        if self._is_determiner_head_phrase_split(left_token, right_token):
            strict_issues.append("determiner_head_phrase_split")
        if self._is_time_range_continuation_split(left, right):
            strict_issues.append("time_range_continuation_split")
        parser_issues = list(
            (getattr(self, "_syntax_hard_cut_issues", {}) or {}).get((left, right), [])
        )
        if strict_issues:
            return list(dict.fromkeys(strict_issues + parser_issues))
        # A forced-alignment pause is evidence for a clause boundary, not a
        # permission slip to split a parser-confirmed dependency.
        if parser_issues:
            return parser_issues
        if pause_ms is not None and pause_ms >= 450:
            return []

        issues: List[str] = []
        if left_is_open_preposition:
            issues.append("preposition_object_split")
        if self._boundary_inside_determiner_numeric_noun(context, boundary_offset):
            issues.append("determiner_numeric_noun_split")
        if self._boundary_inside_quantifier_phrase(context, boundary_offset):
            issues.append("quantifier_phrase_split")
        if self._is_numeric_unit_or_noun_split(left, right):
            issues.append("numeric_unit_or_noun_split")
        if self._is_comparative_complement_split(left_token, right_token):
            issues.append("comparative_complement_split")
        if self._is_intensifier_particle_split(left_token, right_token):
            issues.append("intensifier_particle_split")
        if self._is_hyphenated_measure_noun_split(left, right):
            issues.append("hyphenated_measure_noun_split")
        if self._is_auxiliary_predicate_split(left_token, right_token):
            issues.append("auxiliary_predicate_split")
        if self._is_subject_finite_verb_boundary(left_token, right_token):
            issues.append("subject_finite_verb_split")
        if self._is_determiner_head_phrase_split(left_token, right_token):
            issues.append("determiner_head_phrase_split")
        if self._is_particle_or_preposition_complement_split(left_token, right_token):
            issues.append("particle_or_preposition_complement_split")
        if self._is_time_range_continuation_split(left, right):
            issues.append("time_range_continuation_split")
        elif self._is_stranded_leading_complement_split(left, right, pause_ms):
            issues.append("stranded_leading_complement_split")
        if self._is_negation_or_emphasis_boundary(left_token, right_token):
            issues.append("negation_or_emphasis_fragment")
        if self._is_adverb_adjective_boundary(left_token, right_token, pause_ms):
            issues.append("adverb_adjective_split")
        if self._is_modifier_chain_split(left, right, pause_ms):
            issues.append("modifier_chain_split")
        if self._is_high_confidence_modifier_head_boundary(left_token, right_token):
            issues.append("high_confidence_modifier_head_split")
        if self._is_protected_named_phrase_split(left_token, right_token):
            issues.append("protected_named_phrase_split")
        if self._is_protected_phrasal_boundary(left_token, right_token):
            issues.append("protected_phrasal_boundary_split")
        if self._is_coordinated_modifier_split(left, right, pause_ms):
            issues.append("coordinated_modifier_split")
        if self._is_transition_attached_to_previous_sentence(left, right, pause_ms):
            issues.append("transition_attached_to_previous_sentence")
        for issue in parser_issues:
            if issue not in issues:
                issues.append(issue)
        return issues

    def _soft_stable_cut_issues(self, left: int, right: int) -> List[str]:
        entries = self._active_word_entries
        if self._is_unambiguous_sentence_terminal(
            str(entries[left].get("surface") or ""),
            str(entries[right].get("surface") or ""),
        ):
            return []
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        issues: List[str] = []
        if left_token in {"you", "than"} and right_token:
            issues.append("comparative_clause_split")
        if self._is_short_verb_object_split(left_token, right_token):
            issues.append("short_verb_object_split")
        if self._is_verb_complement_split(left_token, right_token):
            issues.append("verb_complement_split")
        if self._is_compound_noun_split(left_token, right_token):
            issues.append("compound_noun_split")
        if self._is_modifier_noun_head_split(left_token, right_token):
            issues.append("modifier_noun_head_split")
        if self._is_phrasal_verb_particle_split(left_token, right_token):
            issues.append("phrasal_verb_particle_split")
        return issues

    @classmethod
    def _is_unambiguous_sentence_terminal(
        cls,
        left_surface: str,
        right_surface: str,
    ) -> bool:
        """Recognize a true sentence terminal before token-only cut heuristics.

        A period after a title or an initial is not a sentence boundary, so it
        remains subject to the normal abbreviation/name guard.  Otherwise an
        explicit terminal mark must not be reinterpreted as a determiner,
        modifier, or preposition merely because its final word has another
        possible part of speech.
        """
        left = str(left_surface or "").strip()
        right = str(right_surface or "").strip()
        if re.search(r"[!?]\s*$", left):
            return True
        if not re.search(r"\.\s*$", left):
            return False
        title = re.sub(r"[^A-Za-z]", "", left).casefold()
        if title in {"st", "mt", "mr", "mrs", "ms", "dr", "prof", "jr", "sr"}:
            return not bool(re.match(r"[A-Z][A-Za-z'-]{2,}\b", right))
        if re.fullmatch(r"(?:[A-Za-z]\.){1,}", left):
            return False
        return True

    def _is_transition_attached_to_previous_sentence(
        self,
        left: int,
        right: int,
        pause_ms: Optional[int],
    ) -> bool:
        if pause_ms is not None and pause_ms >= 450:
            return False
        entries = self._active_word_entries
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        if left_token not in self._sentence_transition_tokens() or not right_token:
            return False
        if left == 0:
            return False
        previous_surface = str(entries[left - 1].get("surface") or "")
        left_surface = str(entries[left].get("surface") or "")
        return bool(re.search(r"[.!?]\s*$", previous_surface) or re.search(r"[,;:]\s*$", left_surface))

    def _is_coordinated_modifier_split(
        self,
        left: int,
        right: int,
        pause_ms: Optional[int],
    ) -> bool:
        if pause_ms is not None and pause_ms >= 450:
            return False
        entries = self._active_word_entries
        if not entries or right + 1 >= len(entries):
            return False
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        next_token = self._clean_boundary_token(entries[right + 1].get("token") or "")
        if right_token not in {"and", "or"} or not left_token or not next_token:
            return False
        if next_token in self._stable_determiners():
            return False
        if not (
            self._looks_like_adjective_before_noun(left_token, next_token)
            or self._looks_like_adjective_before_noun(next_token, "pressure")
            or left_token in {"economic", "social", "financial", "political", "cultural", "structural"}
        ):
            return False
        return next_token in {
            "social", "economic", "financial", "political", "cultural", "structural",
            "public", "private", "global", "local", "massive", "major",
        } or self._token_looks_noun_like(next_token)

    def _is_modifier_chain_split(
        self,
        left: int,
        right: int,
        pause_ms: Optional[int],
    ) -> bool:
        if pause_ms is not None and pause_ms >= 450:
            return False
        entries = self._active_word_entries
        if not entries or right + 1 >= len(entries):
            return False
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        next_token = self._clean_boundary_token(entries[right + 1].get("token") or "")
        modifier_tokens = {
            "massive", "major", "minor", "huge", "small", "large", "deep",
            "economic", "social", "financial", "political", "cultural",
            "structural", "public", "private", "global", "local",
            "traditional", "modern", "invisible", "aggressive",
        }
        if left_token not in modifier_tokens or right_token not in modifier_tokens:
            return False
        return next_token in modifier_tokens or next_token in {"and", "or"} or self._token_looks_noun_like(next_token)

    @staticmethod
    def _sentence_transition_tokens() -> set:
        return {
            "alternatively",
            "however",
            "therefore",
            "instead",
            "meanwhile",
        }

    def _word_pause_ms(self, left: int, right: int) -> Optional[int]:
        entries = self._active_word_entries
        if not entries or left < 0 or right >= len(entries):
            return None
        return int(entries[right]["start_time"] - entries[left]["end_time"])

    @classmethod
    def _contains_determiner_numeric_noun(cls, tokens: Sequence[str]) -> bool:
        for index in range(0, len(tokens) - 2):
            if (
                tokens[index] in cls._stable_determiners()
                and cls._token_is_numeric_like(tokens[index + 1])
                and cls._token_looks_noun_like(tokens[index + 2])
            ):
                return True
        return False

    @classmethod
    def _boundary_inside_determiner_numeric_noun(
        cls,
        tokens: Sequence[str],
        boundary_offset: int,
    ) -> bool:
        for index in range(0, len(tokens) - 2):
            if not (
                tokens[index] in cls._stable_determiners()
                and cls._token_is_numeric_like(tokens[index + 1])
                and cls._token_looks_noun_like(tokens[index + 2])
            ):
                continue
            if index <= boundary_offset < index + 2:
                return True
        return False

    @classmethod
    def _contains_quantifier_phrase(cls, tokens: Sequence[str]) -> bool:
        return any(cls._boundary_inside_quantifier_phrase(tokens, offset) for offset in range(len(tokens) - 1))

    @classmethod
    def _boundary_inside_quantifier_phrase(
        cls,
        tokens: Sequence[str],
        boundary_offset: int,
    ) -> bool:
        phrase_lengths = (4, 3, 2)
        for length in phrase_lengths:
            for index in range(0, len(tokens) - length + 1):
                phrase = tuple(tokens[index:index + length])
                if not cls._is_quantifier_phrase_tokens(phrase):
                    continue
                if index <= boundary_offset < index + length - 1:
                    return True
        return False

    @staticmethod
    def _stable_determiners() -> set:
        return {"the", "a", "an", "this", "that", "these", "those", "our", "their", "its"}

    @staticmethod
    def _token_is_numeric_like(token: str) -> bool:
        return bool(re.match(r"^(?:\d+(?:[.,]\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|billion)$", token or ""))

    @staticmethod
    def _token_is_digits_like(token: str) -> bool:
        return bool(re.match(r"^\d+(?:[.,]\d+)?$", token or ""))

    @staticmethod
    def _token_looks_noun_like(token: str) -> bool:
        if not token:
            return False
        return not token.endswith("ly") and token not in {"and", "or", "but", "to", "of", "in", "on", "for", "with"}

    def _is_numeric_unit_or_noun_split(self, left: int, right: int) -> bool:
        entries = self._active_word_entries
        left_surface = str(entries[left].get("surface") or "")
        # A number ending an explicit sentence is not the first half of a
        # numeric noun phrase.  Treating ``2019. / Right.`` as one caused the
        # final boundary repair to move a correct sentence boundary into the
        # following clause.
        if re.search(r"[.!?][\"')\]]*\s*$", left_surface):
            return False
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        if not right_token or not self._token_looks_noun_like(right_token):
            return False
        if self._token_is_numeric_like(left_token) or self._token_is_digits_like(left_token):
            return True
        if left > 0:
            previous_token = self._clean_boundary_token(entries[left - 1].get("token") or "")
            if self._token_is_digits_like(previous_token) and self._token_is_digits_like(left_token):
                return True
        return False

    def _is_numeric_magnitude_split(self, left: int, right: int) -> bool:
        """Keep a spoken number and its magnitude together across ASR timings."""
        entries = self._active_word_entries
        left_surface = str(entries[left].get("surface") or "")
        if re.search(r"[.!?][\"')\]]*\s*$", left_surface):
            return False
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        magnitude_tokens = {"hundred", "thousand", "million", "billion", "trillion"}
        return left_token in magnitude_tokens and right_token in magnitude_tokens

    @staticmethod
    def _is_compound_preposition_split(left: str, right: str) -> bool:
        """Detect fixed multiword prepositions without treating all starts as errors."""
        return (left, right) in {
            ("according", "to"),
            ("because", "of"),
            ("instead", "of"),
            ("out", "of"),
        }

    @staticmethod
    def _is_comparative_complement_split(left: str, right: str) -> bool:
        return right in {"than", "as"} and left in {
            "more", "less", "rather", "better", "worse", "other",
        }

    @staticmethod
    def _is_intensifier_particle_split(left: str, right: str) -> bool:
        return left.endswith("ly") and right in {"out", "off", "away", "up", "down"}

    def _is_hyphenated_measure_noun_split(self, left: int, right: int) -> bool:
        """Keep measured modifier phrases such as ``three long em-dashes`` intact."""
        if left <= 0:
            return False
        entries = self._active_word_entries
        previous = self._clean_boundary_token(entries[left - 1].get("token") or "")
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_surface = str(entries[right].get("surface") or "")
        return (
            self._token_is_numeric_like(previous)
            and left_token in {"long", "short", "wide", "narrow", "high", "low"}
            and "-" in right_surface
        )

    def _auditable_atomic_boundary_issues(self, left: int, right: int) -> List[str]:
        """Retain atomic evidence when a real pause makes automatic repair unsafe."""
        entries = self._active_word_entries
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        issues: List[str] = []
        if self._is_numeric_magnitude_split(left, right):
            issues.append("numeric_magnitude_split")
        if self._is_compound_preposition_split(left_token, right_token):
            issues.append("compound_preposition_split")
        if self._is_comparative_complement_split(left_token, right_token):
            issues.append("comparative_complement_split")
        if self._is_intensifier_particle_split(left_token, right_token):
            issues.append("intensifier_particle_split")
        if self._is_hyphenated_measure_noun_split(left, right):
            issues.append("hyphenated_measure_noun_split")
        return issues

    @staticmethod
    def _is_auxiliary_predicate_split(left: str, right: str) -> bool:
        auxiliaries = {
            "am", "is", "are", "was", "were", "be", "been", "being",
            "do", "does", "did", "don't", "doesn't", "didn't",
            "have", "has", "had", "haven't", "hasn't", "hadn't",
            "can", "can't", "could", "couldn't", "will", "won't", "would",
            "wouldn't", "shall", "should", "shouldn't", "may", "might", "must",
        }
        predicate_starts = {
            "be", "been", "being", "have", "do", "go", "make", "take", "get",
            "work", "build", "hire", "view", "know", "automated", "upending",
        }
        return left in auxiliaries and bool(right) and (
            right in predicate_starts
            or right.endswith("ed")
            or right.endswith("ing")
        )

    @staticmethod
    def _is_subject_finite_verb_boundary(left: str, right: str) -> bool:
        short_subjects = {"i", "you", "we", "they", "he", "she", "it", "ai"}
        finite_verbs = {
            "am", "is", "are", "was", "were", "do", "does", "did",
            "have", "has", "had", "can", "could", "will", "would",
            "should", "need", "needed", "needs", "tend", "tends",
        }
        return left in short_subjects and right in finite_verbs

    @staticmethod
    def _is_short_verb_object_split(left: str, right: str) -> bool:
        if not left or not right:
            return False
        likely_transitive = {
            "issued", "helped", "made", "make", "makes", "cause", "causes",
            "taking", "build", "building", "hire", "hired", "expose", "exposed",
        }
        return (
            left in likely_transitive or left.endswith("ed")
        ) and right in {"a", "an", "the", "this", "that", "these", "those", "his", "her", "its", "their", "our"}

    @staticmethod
    def _is_verb_complement_split(left: str, right: str) -> bool:
        if not left or not right:
            return False
        complement_heads = {
            "expose", "hire", "view", "know", "build", "building", "automated",
            "extinct", "available", "possible", "necessary",
        }
        catenative_or_linking = {
            "helped", "help", "helps", "make", "makes", "made", "seems", "feels",
        }
        complement_adjectives = {"extinct", "heavy", "available", "possible", "necessary"}
        return (
            left in catenative_or_linking
            and (right in complement_heads or right.endswith("ly"))
        ) or (left.endswith("s") and right in complement_adjectives)

    @staticmethod
    def _is_compound_noun_split(left: str, right: str) -> bool:
        if not left or not right:
            return False
        compound_heads = {
            "job", "jobs", "displacement", "building", "market", "markets",
            "hours", "journalist", "warning", "tradeoff", "profession", "professions",
        }
        compound_modifiers = {
            "skill", "corporate", "job", "prize-winning", "pulitzer", "large-scale",
            "high-paying", "public", "career", "market",
        }
        return right in compound_heads and (
            left in compound_modifiers
            or "-" in left
            or (left.endswith("ing") and right in compound_heads)
        )

    def _is_modifier_noun_head_split(self, left: str, right: str) -> bool:
        return self._looks_like_adjective_before_noun(left, right)

    @staticmethod
    def _is_high_confidence_modifier_head_boundary(left: str, right: str) -> bool:
        protected_pairs = {
            ("loaded", "motorized"),
            ("dense", "chaotic"),
            ("secretive", "regional"),
            ("healthy", "cash"),
            ("corporate", "solvency"),
            ("strategic", "pathway"),
            ("traditional", "high"),
            ("traditional", "fast"),
            ("long-term", "regional"),
            ("economic", "miracle"),
            ("subsequent", "slowdown"),
            ("deep", "physical"),
            ("creative", "drive"),
        }
        if (left, right) in protected_pairs:
            return True
        if left.endswith("'s") or left.endswith("s'"):
            return True
        return False

    @staticmethod
    def _is_protected_named_phrase_split(left: str, right: str) -> bool:
        protected_pairs = {
            ("wall", "street"),
            ("south", "korea"),
            ("north", "korea"),
            ("new", "york"),
            ("silicon", "valley"),
            ("sk", "hynix"),
            ("goldman", "sachs"),
            ("federal", "reserve"),
            ("united", "states"),
            ("saudi", "arabia"),
            ("elon", "musk"),
            ("jensen", "huang"),
            ("world", "bank"),
        }
        return (left, right) in protected_pairs

    @staticmethod
    def _is_protected_phrasal_boundary(left: str, right: str) -> bool:
        protected_pairs = {
            ("look", "at"),
            ("looks", "at"),
            ("looked", "at"),
            ("looking", "at"),
            ("refer", "to"),
            ("refers", "to"),
            ("referred", "to"),
            ("referring", "to"),
            ("focus", "on"),
            ("focuses", "on"),
            ("focused", "on"),
            ("focusing", "on"),
            ("deal", "with"),
            ("deals", "with"),
            ("dealt", "with"),
            ("dealing", "with"),
            ("relate", "to"),
            ("relates", "to"),
            ("related", "to"),
            ("relating", "to"),
            ("pricing", "in"),
            ("priced", "in"),
            ("price", "in"),
            ("hunkering", "down"),
            ("forced", "to"),
            ("trying", "to"),
            ("able", "to"),
            ("going", "to"),
        }
        return (left, right) in protected_pairs

    def _is_determiner_head_phrase_split(self, left: str, right: str) -> bool:
        return left in self._stable_determiners() and self._token_looks_noun_like(right)

    @staticmethod
    def _is_particle_or_preposition_complement_split(left: str, right: str) -> bool:
        if not left or not right:
            return False
        prepositions = {
            "into", "onto", "through", "across", "around", "over", "under",
            "up", "down", "out", "off", "away",
        }
        adverbial_particles = {"straight", "directly", "right"}
        return left in adverbial_particles and right in prepositions

    @staticmethod
    def _is_phrasal_verb_particle_split(left: str, right: str) -> bool:
        if not left or not right:
            return False
        phrasal_pairs = {
            ("look", "at"),
            ("looks", "at"),
            ("looked", "at"),
            ("looking", "at"),
            ("refer", "to"),
            ("refers", "to"),
            ("referred", "to"),
            ("referring", "to"),
            ("focus", "on"),
            ("focuses", "on"),
            ("focused", "on"),
            ("focusing", "on"),
            ("deal", "with"),
            ("deals", "with"),
            ("dealt", "with"),
            ("dealing", "with"),
            ("relate", "to"),
            ("relates", "to"),
            ("related", "to"),
            ("relating", "to"),
        }
        return (left, right) in phrasal_pairs

    def _is_time_range_continuation_split(self, left: int, right: int) -> bool:
        entries = self._active_word_entries
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        if right_token != "to":
            return False
        if left_token not in {"m", "am", "pm", "a.m", "p.m"}:
            return False
        if right + 1 >= len(entries):
            return False
        next_token = self._clean_boundary_token(entries[right + 1].get("token") or "")
        return self._token_is_numeric_like(next_token) or self._token_is_digits_like(next_token)

    def _is_stranded_leading_complement_split(
        self,
        left: int,
        right: int,
        pause_ms: Optional[int],
    ) -> bool:
        if pause_ms is not None and pause_ms >= 450:
            return False
        entries = self._active_word_entries
        left_surface = str(entries[left].get("surface") or "")
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        if right_token not in {"of", "with", "about", "to"}:
            return False
        if re.search(r"[.!?]\s*$", left_surface or ""):
            return False
        if right_token == "to":
            return self._right_boundary_starts_infinitive_phrase(right)
        if right_token == "with":
            return self._left_boundary_takes_with_complement(left_token)
        return bool(left_token) and self._token_looks_noun_like(left_token)

    def _right_boundary_starts_infinitive_phrase(self, right: int) -> bool:
        entries = self._active_word_entries
        if right + 1 >= len(entries):
            return False
        next_token = self._clean_boundary_token(entries[right + 1].get("token") or "")
        if not next_token:
            return False
        common_infinitive_verbs = {
            "be", "build", "construct", "create", "do", "earn", "explain",
            "get", "go", "hire", "keep", "make", "move", "read", "see",
            "take", "use", "work", "write",
        }
        return next_token in common_infinitive_verbs or next_token.endswith("e")

    @staticmethod
    def _left_boundary_takes_with_complement(left_token: str) -> bool:
        return left_token in {
            "met",
            "filled",
            "dealing",
            "faced",
            "facing",
            "popular",
            "concerned",
        } or left_token.endswith("ed")

    @staticmethod
    def _is_negation_or_emphasis_boundary(left: str, right: str) -> bool:
        return (left, right) in {("never", "ever"), ("not", "ever")}

    @staticmethod
    def _is_quantifier_phrase_tokens(tokens: Sequence[str]) -> bool:
        phrase = tuple(tokens)
        if len(phrase) == 3 and phrase[:2] in {("a", "few"), ("one", "few")}:
            return True
        if len(phrase) == 4 and phrase[:3] == ("a", "couple", "of"):
            return True
        if len(phrase) == 2 and phrase in {("few", "thousand"), ("few", "hundred"), ("several", "thousand")}:
            return True
        return False

    @staticmethod
    def _is_adverb_adjective_boundary(
        left_token: str,
        right_token: str,
        pause_ms: Optional[int],
    ) -> bool:
        if pause_ms is not None and pause_ms > 180:
            return False
        if not left_token.endswith("ly") or not right_token:
            return False
        adjective_endings = (
            "able", "ible", "al", "ed", "ent", "ant", "ful", "ic",
            "ive", "less", "ous", "ary", "ory",
        )
        common_adjectives = {"valuable", "concerned", "important", "likely", "clear", "specific", "heavy", "good"}
        return right_token in common_adjectives or right_token.endswith(adjective_endings)

    @staticmethod
    def _looks_like_adjective_before_noun(left: str, right: str) -> bool:
        if not left or not right:
            return False
        if right in {"and", "or", "but", "of", "to", "in", "on", "for", "with"}:
            return False
        if "-" in left and ScreenSubtitleEditor._token_looks_noun_like(right):
            return True
        adjective_endings = (
            "al", "ful", "ive", "ous", "ic", "ary", "ory", "less", "able", "ible",
            "ent", "ant", "ed", "ing",
        )
        common_nouns = {
            "area", "asset", "assets", "budget", "category", "city", "cities",
            "economy", "ecosystem", "harbors", "holdings", "market", "markets",
            "pedestrian", "policy", "power", "province", "provinces", "revenue",
            "industry", "life", "resources", "shift", "space", "state", "systems",
            "tower", "value", "wealth",
            "economy", "expansion", "optimization",
            "sector", "job", "jobs", "day", "days", "shift", "shifts",
            "graduate", "graduates", "future", "present",
            "majority", "capital", "thing", "trajectory", "investor", "investors",
            "wait", "scooter", "traffic", "pitch", "solvency", "pathway",
            "miracle", "slowdown", "drive", "memory", "funds", "monopolies",
        }
        common_adjectives = {
            "complete", "existing", "grueling", "high-tech", "intensive",
            "massive", "outward", "own", "private", "publicly", "recurring",
            "relentless", "sprawling", "state", "structural", "sustainable",
            "today's", "vast", "corporate", "exact", "same", "largest", "strict",
            "loaded", "motorized", "dense", "chaotic", "secretive", "regional",
            "healthy", "strategic", "traditional", "fast", "long-term",
            "economic", "subsequent", "deep", "physical", "creative",
        }
        noun_modifiers = {
            "asset", "assets", "budget", "cash", "land", "private", "public",
            "sector", "state", "usage", "waterfront",
        }
        if left in common_adjectives and right in common_adjectives:
            return True
        if left in common_adjectives and right in common_nouns:
            return True
        if left in noun_modifiers and right in common_nouns:
            return True
        return right in common_nouns and left.endswith(adjective_endings)

    @staticmethod
    def _looks_like_allowed_sentence_final_adjective(token: str) -> bool:
        return token in {
            "clear", "specific", "important", "good", "bad", "true", "false",
            "right", "wrong", "possible", "necessary", "available", "ready",
        }

    @staticmethod
    def _dangerous_segment_end_tokens() -> set:
        return {
            "a", "an", "the", "my", "your", "his", "her", "its", "our", "their",
            "to", "of", "for", "with", "by", "from", "at", "in", "between",
            "on", "around", "as", "that", "which", "who", "what", "where", "when", "because", "although",
            "if", "and", "or", "but", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "could", "would", "should", "might",
            "must", "will", "can", "do", "does", "did",
            "just", "this",
        }

    @staticmethod
    def _dangerous_segment_start_tokens() -> set:
        return {
            "of", "for", "with", "by", "from", "at", "in", "on", "around", "as", "to",
            "that", "which", "who", "what", "where", "when", "though", "too", "either",
            "also", "anymore",
        }

    @staticmethod
    def _is_bad_boundary_pair(left: str, right: str) -> bool:
        if not left or not right:
            return False
        bad_pairs = {
            ("of", "*"), ("for", "*"), ("with", "*"), ("by", "*"), ("to", "*"),
            ("around", "*"),
            ("a", "*"), ("an", "*"), ("the", "*"),
            ("my", "*"), ("your", "*"), ("his", "*"), ("her", "*"), ("its", "*"),
            ("our", "*"), ("their", "*"),
            ("could", "*"), ("would", "*"), ("should", "*"), ("might", "*"),
            ("will", "*"), ("can", "*"), ("must", "*"),
            ("used", "to"), ("have", "to"), ("has", "to"), ("had", "to"),
            ("having", "to"), ("going", "to"), ("need", "to"), ("needs", "to"),
            ("look", "at"), ("rely", "on"), ("defined", "by"), ("sense", "of"),
            ("right", "around"),
            ("all", "triggered"),
            ("private", "sector"), ("sector", "job"),
            ("hour", "day"), ("hour", "days"),
            ("12", "hour"), ("twelve", "hour"),
            ("weekend", "shift"), ("weekend", "shifts"),
            ("between", "*"), ("this", "*"),
            ("just", "*"),
            ("side", "of"), ("because", "*"), ("which", "*"), ("that", "*"), ("what", "*"),
        }
        return (left, right) in bad_pairs or (left, "*") in bad_pairs

    def _stable_greedy_ranges(
        self, start: int, end: int, target: int, emergency: int
    ) -> List[tuple[int, int]]:
        ranges = []
        cursor = start
        while cursor <= end:
            remaining = end - cursor + 1
            if remaining <= target:
                ranges.append((cursor, end))
                break

            # First search within the normal display limit. Only if every
            # candidate is structurally illegal do we use the 17-19 exception.
            best: Optional[int] = None
            best_score = float("inf")
            max_length = min(target, remaining - 1)
            for candidate in range(cursor + 4, cursor + max_length):
                boundary = self._evaluate_stable_cut_boundary(
                    candidate,
                    candidate + 1,
                    source_start=cursor,
                    source_end=end,
                )
                if not boundary["legal"]:
                    continue
                if not self._stable_greedy_candidate_display_safe(cursor, candidate, end):
                    continue
                length = candidate - cursor + 1
                score = float(boundary["boundary_score"]) + abs(length - target) * 1.5
                if score < best_score:
                    best_score = score
                    best = candidate

            if best is None:
                max_length = min(emergency, remaining - 1)
                for candidate in range(cursor + target - 1, cursor + max_length):
                    boundary = self._evaluate_stable_cut_boundary(
                        candidate,
                        candidate + 1,
                        source_start=cursor,
                        source_end=end,
                    )
                    if not boundary["legal"]:
                        continue
                    if not self._stable_greedy_candidate_display_safe(cursor, candidate, end):
                        continue
                    length = candidate - cursor + 1
                    if (
                        length > target
                        and not self._is_complete_pre_id_structural_overflow_range(
                            cursor,
                            candidate,
                        )
                    ):
                        continue
                    score = float(boundary["boundary_score"]) + (length - target) * 12.0
                    if score < best_score:
                        best_score = score
                        best = candidate

            if best is None:
                # This method receives one terminal source-sentence span. A
                # forced 19-word cut here can only create an incomplete cue
                # that the final validator must later reject. Keep the
                # remaining complete sentence frozen and let the renderer own
                # its line wrapping; it remains an audited structural warning.
                ranges.append((cursor, end))
                break
            right = best
            ranges.append((cursor, right))
            cursor = right + 1
        return self._merge_tiny_stable_ranges(ranges, target, emergency)

    def _stable_greedy_candidate_display_safe(
        self, start: int, cut: int, end: int
    ) -> bool:
        """Reject pre-ID cuts that create a non-displayable cue on either side."""
        if not hasattr(self, "_active_source_word_spans"):
            self._active_source_word_spans = {}
        left = self._item_from_word_span(start, cut)
        right = self._item_from_word_span(cut + 1, end)
        if not left or not right:
            return False
        if not self._evaluate_item_pair_for_final_boundary(left, right)["legal"]:
            return False
        return not self._evaluate_final_display_fragment(
            right, left, None
        )["hard_fragment_issues"]

    def _is_complete_pre_id_structural_overflow_range(
        self,
        word_start: int,
        word_end: int,
    ) -> bool:
        """Permit a 17-20 word exception only for a complete local cue."""
        text = self._text_from_word_span(word_start, word_end)
        if re.search(r"[.!?][\"')\]]*\s*$", text or ""):
            return True
        if self._is_parser_confirmed_comma_subordinate_clause(text):
            return True
        item = self._item_from_word_span(word_start, word_end)
        if not item or not re.search(r",[\"')\]]*\s*$", text or ""):
            return False
        return bool(self._visual_temporal_clause_shape(item).get("complete_main_clause"))

    def _merge_tiny_stable_ranges(
        self, ranges: List[tuple[int, int]], target: int, emergency: int
    ) -> List[tuple[int, int]]:
        if len(ranges) <= 1:
            return ranges
        result: List[tuple[int, int]] = []
        for current in ranges:
            length = current[1] - current[0] + 1
            if result and length <= 2:
                prev = result[-1]
                merged_len = current[1] - prev[0] + 1
                if merged_len <= emergency:
                    result[-1] = (prev[0], current[1])
                    continue
            result.append(current)
        return result

    def _prepare_syntax_cut_hints(self) -> None:
        self._syntax_protected_cuts = set()
        self._syntax_hard_cut_issues = {}
        if not self._active_word_entries:
            return
        nlp = self._load_syntax_nlp()
        if not nlp:
            return

        protected: set[tuple[int, int]] = set()
        for span_start, span_end in self._stable_sentence_word_spans():
            surfaces = [
                str(self._active_word_entries[index].get("surface") or "")
                for index in range(span_start, span_end + 1)
            ]
            words = [surface for surface in surfaces if surface.strip()]
            if not words:
                continue
            text = self._normalize_text(" ".join(words))
            if not text:
                continue
            try:
                doc = nlp(text)
            except Exception as exc:
                logger.debug("spaCy syntax parse skipped: %s", exc)
                continue

            doc_to_word = self._align_doc_tokens_to_word_entries(doc, span_start, span_end)
            if not doc_to_word:
                continue

            for chunk in getattr(doc, "noun_chunks", []):
                word_indices = [
                    doc_to_word[token.i]
                    for token in chunk
                    if token.i in doc_to_word
                ]
                self._protect_internal_boundaries(word_indices, protected)
                self._protect_hard_noun_phrase_boundaries(chunk, doc_to_word)

            protected_deps = {
                "amod", "compound", "det", "nummod", "poss", "quantmod",
                "aux", "auxpass", "neg", "case", "mark", "fixed", "flat",
            }
            for token in doc:
                if token.dep_ not in protected_deps:
                    continue
                if token.i not in doc_to_word or token.head.i not in doc_to_word:
                    continue
                left = min(doc_to_word[token.i], doc_to_word[token.head.i])
                right = max(doc_to_word[token.i], doc_to_word[token.head.i])
                if right - left <= 3:
                    self._protect_internal_boundaries(range(left, right + 1), protected)
            self._protect_short_verb_complement_boundaries(doc, doc_to_word)
            self._protect_short_dative_object_chains(doc, doc_to_word)
            self._protect_verb_particle_boundaries(doc, doc_to_word)
            self._protect_short_gerundial_modifier_boundaries(doc, doc_to_word)
            self._protect_clause_introducer_boundaries(doc, doc_to_word)
            self._protect_preposition_object_boundaries(doc, doc_to_word)
            self._protect_verb_preposition_complement_boundaries(doc, doc_to_word)
            self._protect_verb_adverb_preposition_boundaries(doc, doc_to_word)
            self._protect_verb_numeric_result_boundaries(doc, doc_to_word)
            self._protect_numeric_range_boundaries(doc, doc_to_word)
            self._protect_subject_verb_boundaries(doc, doc_to_word)
            self._protect_coordinated_subject_boundaries(doc, doc_to_word)
            self._protect_compact_coordination_boundaries(doc, doc_to_word)
            self._protect_object_content_clause_boundaries(doc, doc_to_word)
            self._protect_object_attached_modifier_boundaries(doc, doc_to_word)
            self._protect_comma_bracketed_adverb_boundaries(doc, doc_to_word)
            self._protect_modifier_head_boundaries(doc, doc_to_word)

        self._syntax_protected_cuts = protected
        if protected:
            logger.info("Screen subtitle syntax cut hints: protected=%s", len(protected))

    def _protect_hard_noun_phrase_boundaries(self, chunk, doc_to_word: Dict[int, int]) -> None:
        word_indices = sorted(
            doc_to_word[token.i]
            for token in chunk
            if token.i in doc_to_word
        )
        if len(word_indices) < 2 or len(word_indices) > 5:
            return
        tokens = [
            self._clean_boundary_token(self._active_word_entries[index].get("token") or "")
            for index in word_indices
        ]
        if self._contains_determiner_numeric_noun(tokens):
            self._record_syntax_hard_issue_for_indices(
                word_indices,
                "determiner_numeric_noun_split",
            )
        if self._contains_quantifier_phrase(tokens):
            self._record_syntax_hard_issue_for_indices(
                word_indices,
                "quantifier_phrase_split",
            )
        for left_index, right_index in zip(word_indices, word_indices[1:]):
            left = self._clean_boundary_token(self._active_word_entries[left_index].get("token") or "")
            right = self._clean_boundary_token(self._active_word_entries[right_index].get("token") or "")
            if self._is_numeric_unit_or_noun_split(left_index, right_index):
                self._record_syntax_hard_issue_for_indices([left_index, right_index], "numeric_unit_or_noun_split")
            if self._is_compound_noun_split(left, right):
                self._record_syntax_hard_issue_for_indices([left_index, right_index], "compound_noun_split")
            if self._is_modifier_noun_head_split(left, right):
                self._record_syntax_hard_issue_for_indices([left_index, right_index], "modifier_noun_head_split")
            if self._is_determiner_head_phrase_split(left, right):
                self._record_syntax_hard_issue_for_indices([left_index, right_index], "determiner_head_phrase_split")

    def _protect_short_verb_complement_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        complement_deps = {"obj", "dobj", "attr", "oprd", "prt", "xcomp", "ccomp", "acomp"}
        for token in doc:
            if token.dep_ not in complement_deps:
                continue
            head = token.head
            if head.i not in doc_to_word or token.i not in doc_to_word:
                continue
            if getattr(head, "pos_", "") not in {"VERB", "AUX"}:
                continue
            head_index = doc_to_word[head.i]
            subtree_indices = sorted(
                doc_to_word[item.i]
                for item in token.subtree
                if item.i in doc_to_word
            )
            if not subtree_indices:
                continue
            complement_start = min(subtree_indices)
            if complement_start <= head_index:
                continue
            between_indices = range(head_index + 1, complement_start)
            # Allow only a phrasal-verb particle between a verb and its direct
            # complement. A long object may follow it, but the boundary before
            # the object is still grammatically inseparable.
            if any(
                item.i in doc_to_word
                and getattr(item, "dep_", "") not in {"prt", "aux", "auxpass", "neg", "advmod"}
                for item in doc
                if doc_to_word.get(item.i) in between_indices
            ):
                continue
            issue = "short_verb_object_split" if token.dep_ in {"obj", "dobj"} else "verb_complement_split"
            protected_indices = list(range(head_index, complement_start + 1))
            self._record_syntax_hard_issue_for_indices(protected_indices, issue)
            self._record_syntax_hard_issue_for_indices(protected_indices, "short_verb_complement_split")

    def _protect_short_dative_object_chains(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a compact verb-dative-object start together.

        The ordinary object guard starts at the direct object.  In a short
        ``give you a ...`` shape, that leaves the boundary after the dative
        open and can strand the object's determiner on the next cue.
        """
        object_deps = {"obj", "dobj"}
        for verb in doc:
            if getattr(verb, "pos_", "") not in {"VERB", "AUX"}:
                continue
            if verb.i not in doc_to_word:
                continue
            dative_children = [
                child for child in verb.children
                if getattr(child, "dep_", "") == "dative" and child.i in doc_to_word
            ]
            object_children = [
                child for child in verb.children
                if getattr(child, "dep_", "") in object_deps and child.i in doc_to_word
            ]
            if not dative_children or not object_children:
                continue
            verb_index = doc_to_word[verb.i]
            for dative in dative_children:
                dative_index = doc_to_word[dative.i]
                if dative_index != verb_index + 1:
                    continue
                object_indices = sorted(
                    doc_to_word[item.i]
                    for object_child in object_children
                    for item in object_child.subtree
                    if item.i in doc_to_word
                )
                if not object_indices:
                    continue
                object_start = min(object_indices)
                if object_start <= dative_index or object_start - dative_index > 2:
                    continue
                pauses = [
                    self._word_pause_ms(index, index + 1)
                    for index in range(verb_index, object_start)
                ]
                if any(pause is not None and pause >= 450 for pause in pauses):
                    continue
                self._record_syntax_hard_issue_for_indices(
                    range(verb_index, object_start + 1),
                    "short_verb_complement_split",
                )

    def _protect_verb_particle_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Protect a direct verb-particle shape when no object follows it."""
        for particle in doc:
            if (
                getattr(particle, "dep_", "") not in {"prep", "prt"}
                or particle.i not in doc_to_word
                or getattr(particle, "pos_", "") not in {"ADP", "ADV"}
            ):
                continue
            verb = particle.head
            if (
                getattr(verb, "pos_", "") not in {"VERB", "AUX"}
                or verb.i not in doc_to_word
            ):
                continue
            verb_index = doc_to_word[verb.i]
            particle_index = doc_to_word[particle.i]
            if particle_index != verb_index + 1:
                continue
            if re.search(r"[.!?]\s*$", str(particle.text or "")):
                continue
            if any(
                getattr(child, "dep_", "") in {"pobj", "pcomp"}
                for child in particle.children
            ):
                continue
            pause = self._word_pause_ms(verb_index, particle_index)
            if pause is not None and pause >= 450:
                continue
            self._record_syntax_hard_issue_for_indices(
                [verb_index, particle_index],
                "verb_particle_split",
            )

    def _protect_short_gerundial_modifier_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a compact unpunctuated VBG modifier with the action it completes.

        A participial manner phrase such as ``spot the pattern using your own
        eyes`` is often parsed as ``VERB -> VBG/advcl`` after the main verb's
        object. It is not an independent display beat when it has no leading
        punctuation, no meaningful pause, and only a short local complement.
        The visual pass must leave a 13-16 word sentence intact in that case,
        rather than create a four-word gerundial tail solely for character
        budget reasons.
        """
        for token in doc:
            if (
                getattr(token, "pos_", "") != "VERB"
                or getattr(token, "tag_", "") != "VBG"
                or getattr(token, "dep_", "") != "advcl"
                or token.i not in doc_to_word
            ):
                continue
            head = token.head
            if (
                getattr(head, "pos_", "") not in {"VERB", "AUX"}
                or head.i not in doc_to_word
            ):
                continue
            modifier_indices = sorted(
                doc_to_word[item.i]
                for item in token.subtree
                if item.i in doc_to_word
            )
            if not modifier_indices or len(modifier_indices) > 4:
                continue
            modifier_start = min(modifier_indices)
            if modifier_start <= 0:
                continue
            previous_surface = str(self._active_word_entries[modifier_start - 1].get("surface") or "")
            if re.search(r"[,;:.!?]\s*$", previous_surface):
                continue
            pause_ms = self._word_pause_ms(modifier_start - 1, modifier_start)
            if pause_ms is not None and pause_ms >= 450:
                continue
            self._record_syntax_hard_issue_for_indices(
                [modifier_start - 1, modifier_start],
                "short_gerundial_modifier_split",
            )

    def _protect_clause_introducer_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        for token in doc:
            if token.i not in doc_to_word:
                continue
            if getattr(token, "dep_", "") != "mark" and getattr(token, "pos_", "") != "SCONJ":
                continue
            head = token.head
            if head.i not in doc_to_word:
                continue
            token_index = doc_to_word[token.i]
            head_index = doc_to_word[head.i]
            if head_index <= token_index or token_index + 1 >= len(self._active_word_entries):
                continue
            # A subordinate-clause introducer belongs to the clause that
            # follows it. Splitting immediately after it creates a visible
            # dangling "if / how / because / that" subtitle.
            self._record_syntax_hard_issue_for_indices(
                [token_index, token_index + 1],
                "clause_introducer_split",
            )

    def _protect_preposition_object_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Protect a parser-confirmed preposition from its local complement.

        Lexical fallback rules cover common prepositions, but a noun-attached
        example phrase such as ``clues like excessive em dashes`` is parsed as
        ``NOUN -> ADP/prep -> NOUN/pobj``. The ADP is not itself a noun-chunk
        member, so the generic noun-phrase guard does not own its following
        boundary. This parser-backed rule supplies that missing ownership for
        every continuous ``prep -> pobj/pcomp`` relation.
        """
        for token in doc:
            if getattr(token, "dep_", "") != "prep" or token.i not in doc_to_word:
                continue
            prep_index = doc_to_word[token.i]
            complement_indices = []
            for child in token.children:
                if getattr(child, "dep_", "") not in {"pobj", "pcomp"}:
                    continue
                complement_indices.extend(
                    doc_to_word[item.i]
                    for item in child.subtree
                    if item.i in doc_to_word
                )
            if not complement_indices:
                continue
            complement_start = min(complement_indices)
            if complement_start <= prep_index:
                continue
            self._record_syntax_hard_issue_for_indices(
                range(prep_index, complement_start + 1),
                "preposition_object_split",
            )

    def _protect_verb_preposition_complement_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        for token in doc:
            if getattr(token, "dep_", "") != "prep":
                continue
            head = token.head
            if token.i not in doc_to_word or head.i not in doc_to_word:
                continue
            if getattr(head, "pos_", "") not in {"VERB", "AUX"}:
                continue
            head_index = doc_to_word[head.i]
            prep_index = doc_to_word[token.i]
            if prep_index != head_index + 1:
                continue
            if not any(getattr(child, "dep_", "") in {"pobj", "pcomp"} for child in token.children):
                continue
            self._record_syntax_hard_issue_for_indices(
                [head_index, prep_index],
                "verb_preposition_complement_split",
            )

    def _protect_verb_adverb_preposition_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a verb's directional adverb and following preposition together.

        spaCy can parse ``come back to`` as VERB -> ADV -> ADP rather than a
        verb directly governing the preposition. The existing verb-preposition
        protection intentionally does not cover that shape. Protect the whole
        contiguous VERB/ADV/ADP chain when there is no meaningful pause, so a
        repair cannot merely move a bad cut from ``back / to`` to
        ``coming / back``.
        """
        for token in doc:
            if getattr(token, "dep_", "") != "prep" or token.i not in doc_to_word:
                continue
            adverb = token.head
            verb = adverb.head
            if (
                getattr(adverb, "pos_", "") != "ADV"
                or getattr(adverb, "dep_", "") not in {"advmod", "prt"}
                or getattr(verb, "pos_", "") not in {"VERB", "AUX"}
                or adverb.i not in doc_to_word
                or verb.i not in doc_to_word
            ):
                continue
            verb_index = doc_to_word[verb.i]
            adverb_index = doc_to_word[adverb.i]
            prep_index = doc_to_word[token.i]
            if adverb_index != verb_index + 1 or prep_index != adverb_index + 1:
                continue
            pauses = (
                self._word_pause_ms(verb_index, adverb_index),
                self._word_pause_ms(adverb_index, prep_index),
            )
            if any(pause_ms is not None and pause_ms >= 450 for pause_ms in pauses):
                continue
            self._record_syntax_hard_issue_for_indices(
                [verb_index, adverb_index, prep_index],
                "verb_adverb_preposition_split",
            )

    def _protect_verb_numeric_result_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a verb attached to its compact numeric result expression.

        This covers constructions such as ``fell 52% from its peak``.  The
        numeric object is part of the action's result, not an independent
        subtitle unit.  Long ordinary objects remain eligible for a cut;
        only direct numeric-result objects are protected here.
        """
        result_deps = {"obj", "dobj", "attr", "oprd", "npadvmod"}
        for token in doc:
            # Some ASR word ledgers preserve ``52%`` as one word while spaCy
            # parses it as NUM + NOUN. In that case the mapped NUM is attached
            # to an unmapped unit token (``%``); use that unit as the result
            # head while retaining the mapped numeric token as the boundary.
            result_token = token
            numeric_anchor = token
            if (
                getattr(token, "pos_", "") == "NUM"
                and getattr(token, "dep_", "") in {"nummod", "quantmod"}
                and getattr(token.head, "dep_", "") in result_deps
            ):
                result_token = token.head
            elif getattr(token, "dep_", "") not in result_deps:
                continue

            head = result_token.head
            if (
                numeric_anchor.i not in doc_to_word
                or getattr(head, "pos_", "") not in {"VERB", "AUX"}
                or head.i not in doc_to_word
            ):
                continue
            has_numeric_result = (
                getattr(numeric_anchor, "like_num", False)
                or getattr(numeric_anchor, "pos_", "") == "NUM"
                or any(
                    getattr(child, "dep_", "") in {"nummod", "quantmod"}
                    or getattr(child, "like_num", False)
                    for child in result_token.children
                )
            )
            if not has_numeric_result:
                continue
            # Keep the numeric core compact, but do not turn every following
            # prepositional or relative modifier into an unbreakable span.
            # "sold 100 homes in three cities" may safely break after homes;
            # "fell 52% from its peak" is handled below as a one-boundary
            # qualifier attachment.
            result_indices = []
            for item in result_token.subtree:
                if item.i not in doc_to_word:
                    continue
                ancestor = item
                belongs_to_modifier = False
                while (
                    ancestor.i != result_token.i
                    and ancestor.head.i != ancestor.i
                ):
                    if getattr(ancestor, "dep_", "") in {"prep", "relcl", "acl", "advcl"}:
                        belongs_to_modifier = True
                        break
                    ancestor = ancestor.head
                if not belongs_to_modifier:
                    result_indices.append(doc_to_word[item.i])
            result_indices = sorted(set(result_indices))
            if not result_indices:
                continue
            verb_index = doc_to_word[head.i]
            result_start = min(result_indices)
            result_end = max(result_indices)
            if result_start <= verb_index or result_start - verb_index > 2:
                continue
            self._record_syntax_hard_issue_for_indices(
                range(verb_index, result_end + 1),
                "verb_numeric_result_split",
            )

            # A following source/baseline preposition belongs to the numeric
            # result as well: "fell 52% from ...", "rose 10% to ...".
            following_preps = [
                child
                for child in head.children
                if getattr(child, "dep_", "") == "prep"
                and child.i in doc_to_word
                and doc_to_word[child.i] == result_end + 1
                and self._clean_boundary_token(child.text) in {"from", "to", "by", "at"}
            ]
            for prep in following_preps:
                self._record_syntax_hard_issue_for_indices(
                    [result_end, doc_to_word[prep.i]],
                    "numeric_result_qualifier_split",
                )

    def _protect_numeric_range_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep parser-confirmed ``from number to number`` ranges intact."""
        for from_token in doc:
            if (
                self._clean_boundary_token(getattr(from_token, "text", "")) != "from"
                or getattr(from_token, "dep_", "") != "prep"
                or from_token.i not in doc_to_word
            ):
                continue
            head = from_token.head
            if (
                getattr(head, "pos_", "") not in {"VERB", "AUX"}
                or head.i not in doc_to_word
            ):
                continue
            from_index = doc_to_word[from_token.i]
            to_tokens = [
                token for token in from_token.subtree
                if token.i in doc_to_word
                and self._clean_boundary_token(getattr(token, "text", "")) == "to"
            ]
            if not to_tokens:
                continue
            to_token = min(to_tokens, key=lambda token: token.i)
            numeric_before_to = [
                token for token in from_token.subtree
                if token.i in doc_to_word
                and from_token.i < token.i < to_token.i
                and (getattr(token, "like_num", False) or getattr(token, "pos_", "") == "NUM")
            ]
            if not numeric_before_to:
                continue
            numeric_after_to = [
                token for token in to_token.subtree
                if token.i in doc_to_word
                and (getattr(token, "like_num", False) or getattr(token, "pos_", "") == "NUM")
            ]
            if not numeric_after_to:
                continue
            start = min(doc_to_word[head.i], from_index)
            end = max(doc_to_word[token.i] for token in numeric_after_to)
            if end <= start or end - start > 8:
                continue
            pauses = [
                self._word_pause_ms(index, index + 1)
                for index in range(start, end)
            ]
            if any(pause is not None and pause >= 450 for pause in pauses):
                continue
            self._record_syntax_hard_issue_for_indices(
                range(start, end + 1),
                "numeric_range_split",
            )

    def _protect_subject_verb_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        for token in doc:
            if token.dep_ not in {"nsubj", "nsubjpass", "expl"}:
                continue
            head = token.head
            if head.i not in doc_to_word or token.i not in doc_to_word:
                continue
            if getattr(head, "pos_", "") not in {"VERB", "AUX"}:
                continue
            subject_indices = sorted(
                doc_to_word[item.i]
                for item in token.subtree
                if item.i in doc_to_word
            )
            if not subject_indices:
                continue
            subject_end = max(subject_indices)
            verb_index = doc_to_word[head.i]
            if verb_index <= subject_end:
                continue
            if verb_index - subject_end > 4:
                continue
            if self._word_pause_ms(subject_end, subject_end + 1) is not None:
                pauses = [
                    self._word_pause_ms(index, index + 1)
                    for index in range(subject_end, verb_index)
                ]
                if any(pause is not None and pause >= 450 for pause in pauses):
                    continue
            issue = (
                "relative_clause_subject_verb_split"
                if getattr(head, "dep_", "") == "relcl" or getattr(token, "dep_", "") == "nsubj"
                and any(getattr(ancestor, "dep_", "") == "relcl" for ancestor in head.ancestors)
                else "subject_finite_verb_split"
            )
            self._record_syntax_hard_issue_for_indices(
                list(range(subject_end, verb_index + 1)),
                issue,
            )

    def _protect_coordinated_subject_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a compact coordinated subject from being split internally."""
        for subject in doc:
            if (
                getattr(subject, "dep_", "") not in {"nsubj", "nsubjpass", "expl"}
                or subject.i not in doc_to_word
            ):
                continue
            subtree = [token for token in subject.subtree if token.i in doc_to_word]
            if not any(getattr(token, "dep_", "") == "conj" for token in subtree):
                continue
            indices = sorted(doc_to_word[token.i] for token in subtree)
            if not indices or indices[-1] - indices[0] > 7:
                continue
            if any(
                self._word_pause_ms(index, index + 1) is not None
                and self._word_pause_ms(index, index + 1) >= 450
                for index in range(indices[0], indices[-1])
            ):
                continue
            self._record_syntax_hard_issue_for_indices(
                range(indices[0], indices[-1] + 1),
                "coordinated_subject_split",
            )

    def _protect_compact_coordination_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a short parser-confirmed coordination from being visually fragmented."""
        for token in doc:
            if getattr(token, "dep_", "") != "conj" or token.i not in doc_to_word:
                continue
            head = token.head
            if head.i not in doc_to_word:
                continue
            start = min(doc_to_word[head.i], doc_to_word[token.i])
            end = max(doc_to_word[head.i], doc_to_word[token.i])
            if end <= start or end - start > 12:
                continue
            clause_connector = next(
                (
                    candidate
                    for candidate in doc
                    if candidate.i in doc_to_word
                    and start <= doc_to_word[candidate.i] <= end
                    and getattr(candidate, "dep_", "") == "cc"
                    and self._clean_boundary_token(getattr(candidate, "text", ""))
                    in {"but", "or", "so", "yet"}
                    and doc_to_word[candidate.i] > start
                    and re.search(
                        r"[,;:]\s*$",
                        str(
                            self._active_word_entries[
                                doc_to_word[candidate.i] - 1
                            ].get("surface") or ""
                        ),
                    )
                ),
                None,
            )
            if clause_connector is not None:
                continue
            pauses = [
                self._word_pause_ms(index, index + 1)
                for index in range(start, end)
            ]
            if any(pause is not None and pause >= 450 for pause in pauses):
                continue
            self._record_syntax_hard_issue_for_indices(
                range(start, end + 1),
                "coordinated_constituent_split",
            )

    def _protect_object_content_clause_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a verb's final object attached to its following content clause."""
        for marker in doc:
            if (
                getattr(marker, "dep_", "") != "mark"
                or marker.i not in doc_to_word
                or self._clean_boundary_token(getattr(marker, "text", ""))
                not in {"if", "whether", "that", "how", "what", "why", "where", "when"}
            ):
                continue
            marker_index = doc_to_word[marker.i]
            previous = next(
                (
                    token
                    for token in doc
                    if doc_to_word.get(token.i) == marker_index - 1
                ),
                None,
            )
            if (
                previous is None
                or getattr(previous, "dep_", "") not in {"dobj", "obj", "iobj"}
                or previous.head.i not in doc_to_word
                or getattr(previous.head, "pos_", "") not in {"VERB", "AUX"}
            ):
                continue
            previous_index = doc_to_word[previous.i]
            pause_ms = self._word_pause_ms(previous_index, marker_index)
            if pause_ms is not None and pause_ms >= 450:
                continue
            self._record_syntax_hard_issue_for_indices(
                [previous_index, marker_index],
                "object_content_clause_split",
            )

    def _protect_object_attached_modifier_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a verb-attached post-object modifier with its object phrase."""
        for modifier in doc:
            if (
                getattr(modifier, "dep_", "") != "prep"
                or modifier.i not in doc_to_word
                or getattr(modifier.head, "pos_", "") not in {"VERB", "AUX"}
            ):
                continue
            modifier_index = doc_to_word[modifier.i]
            previous = next(
                (
                    token
                    for token in doc
                    if doc_to_word.get(token.i) == modifier_index - 1
                ),
                None,
            )
            if (
                previous is None
                or getattr(previous, "dep_", "") not in {"dobj", "obj", "attr", "oprd"}
                or previous.head != modifier.head
            ):
                continue
            previous_index = doc_to_word[previous.i]
            pause_ms = self._word_pause_ms(previous_index, modifier_index)
            if pause_ms is not None and pause_ms >= 450:
                continue
            self._record_syntax_hard_issue_for_indices(
                [previous_index, modifier_index],
                "object_attached_modifier_split",
            )

    def _protect_comma_bracketed_adverb_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        """Keep a comma-bracketed sentence adverb off a new cue's first word.

        A word-ledger entry owns adjacent punctuation, so a structure such as
        ``for me, really, for anyone`` appears as three adjacent entries.  If
        spaCy confirms that the middle word is an adverb modifying the
        following preposition, splitting immediately before it produces a
        visually orphaned sentence-internal aside.  Keep that adverb with the
        preceding list item; the next cue may begin at the following complete
        prepositional phrase.  This is intentionally limited to a local,
        punctuation-bracketed dependency and does not affect sentence-initial
        adverbs or ordinary adverb-verb boundaries.
        """
        for token in doc:
            if (
                getattr(token, "pos_", "") != "ADV"
                or getattr(token, "dep_", "") != "advmod"
                or token.i not in doc_to_word
            ):
                continue
            head = token.head
            if (
                getattr(head, "pos_", "") != "ADP"
                or head.i not in doc_to_word
            ):
                continue
            adverb_index = doc_to_word[token.i]
            head_index = doc_to_word[head.i]
            if head_index != adverb_index + 1 or adverb_index <= 0:
                continue
            previous_surface = str(self._active_word_entries[adverb_index - 1].get("surface") or "")
            adverb_surface = str(self._active_word_entries[adverb_index].get("surface") or "")
            if not (
                re.search(r"[,;:]\s*$", previous_surface)
                and re.search(r"[,;:]\s*$", adverb_surface)
            ):
                continue
            pause_ms = self._word_pause_ms(adverb_index - 1, adverb_index)
            if pause_ms is not None and pause_ms >= 450:
                continue
            self._record_syntax_hard_issue_for_indices(
                [adverb_index - 1, adverb_index],
                "comma_bracketed_adverb_split",
            )

    def _protect_modifier_head_boundaries(self, doc, doc_to_word: Dict[int, int]) -> None:
        for token in doc:
            if token.dep_ not in {"advmod", "amod"}:
                continue
            head = token.head
            if token.i not in doc_to_word or head.i not in doc_to_word:
                continue
            if getattr(token, "pos_", "") != "ADV":
                continue
            if getattr(head, "pos_", "") not in {"ADJ", "ADV", "VERB"}:
                continue
            left = doc_to_word[token.i]
            right = doc_to_word[head.i]
            if right != left + 1:
                continue
            pause = self._word_pause_ms(left, right)
            if pause is not None and pause > 180:
                continue
            self._record_syntax_hard_issue_for_indices(
                [left, right],
                "modifier_head_split",
            )

    def _record_syntax_hard_issue_for_indices(
        self,
        word_indices: Sequence[int],
        issue: str,
    ) -> None:
        ordered = sorted(set(int(index) for index in word_indices))
        for left, right in zip(ordered, ordered[1:]):
            if right != left + 1:
                continue
            self._syntax_hard_cut_issues.setdefault((left, right), [])
            if issue not in self._syntax_hard_cut_issues[(left, right)]:
                self._syntax_hard_cut_issues[(left, right)].append(issue)

    def _load_syntax_nlp(self):
        if self._syntax_nlp is not None:
            return self._syntax_nlp
        try:
            original_import = builtins.__import__

            def import_without_torch_probe(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "torch" or name.startswith("torch."):
                    raise ImportError("Torch probing disabled for spaCy syntax loading")
                return original_import(name, globals, locals, fromlist, level)

            builtins.__import__ = import_without_torch_probe
            try:
                import spacy  # type: ignore
            finally:
                builtins.__import__ = original_import
        except Exception as exc:
            self._syntax_nlp = False
            logger.info("spaCy not installed; syntax-assisted subtitle cutting disabled: %s", exc)
            return None
        for model_name in ("en_core_web_sm", "en_core_web_md"):
            try:
                self._syntax_nlp = spacy.load(model_name, disable=["ner", "textcat"])
                logger.info("spaCy syntax-assisted subtitle cutting enabled: %s", model_name)
                return self._syntax_nlp
            except Exception:
                continue
        self._syntax_nlp = False
        logger.info("spaCy English model not found; syntax-assisted subtitle cutting disabled")
        return None

    def _align_doc_tokens_to_word_entries(
        self, doc, span_start: int, span_end: int
    ) -> Dict[int, int]:
        mapping: Dict[int, int] = {}
        cursor = span_start
        last_entry_token = ""
        for token in doc:
            if getattr(token, "is_punct", False):
                continue
            normalized = self._clean_boundary_token(token.text)
            if not normalized:
                continue
            # The word ledger keeps ASR tokens intact (for example
            # ``six-fold``), while spaCy may split the same surface into
            # ``six``, ``-`` and ``fold``. Once a sub-token has consumed the
            # ledger word, ignore later sub-tokens from that same compound so
            # they cannot advance the cursor and misalign the rest of the
            # sentence.
            if (
                last_entry_token
                and normalized != last_entry_token
                and normalized in last_entry_token
                and bool(re.search(r"[-/'’]", last_entry_token))
            ):
                continue
            while cursor <= span_end:
                entry_token = self._clean_boundary_token(
                    self._active_word_entries[cursor].get("token") or ""
                )
                if entry_token == normalized:
                    mapping[token.i] = cursor
                    last_entry_token = entry_token
                    cursor += 1
                    break
                if normalized in entry_token or entry_token in normalized:
                    mapping[token.i] = cursor
                    last_entry_token = entry_token
                    cursor += 1
                    break
                cursor += 1
        return mapping

    @staticmethod
    def _protect_internal_boundaries(
        word_indices: Sequence[int], protected: set[tuple[int, int]]
    ) -> None:
        unique = sorted(set(int(index) for index in word_indices))
        for left, right in zip(unique, unique[1:]):
            if right == left + 1:
                protected.add((left, right))

    def _validate_stable_items(
        self, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        ordered = self._sort_items_by_word_span(items)
        seen: set[int] = set()
        for item in ordered:
            if item.word_start is None or item.word_end is None:
                continue
            for index in range(item.word_start, item.word_end + 1):
                if index in seen:
                    raise ValueError(f"稳定模式英文词重复: {index}")
                seen.add(index)
        return ordered

    def _report_subtitle_coverage_gaps(
        self,
        source_segments: Sequence[ASRDataSeg],
        final_segments: Sequence[ASRDataSeg],
        min_gap_ms: int = COVERAGE_GAP_REPORT_MS,
    ) -> None:
        if not source_segments or not final_segments:
            self._write_coverage_report([], [], final_segments)
            return

        translation_gaps = self._translation_gaps(final_segments)
        final_intervals = sorted(
            (
                max(0, seg.start_time),
                max(seg.end_time, seg.start_time),
            )
            for seg in final_segments
            if (seg.text or "").strip()
        )
        if not final_intervals:
            self._write_coverage_report([], translation_gaps, final_segments)
            return

        gaps: List[Dict] = []
        for index, source in enumerate(source_segments, 1):
            source_text = self._normalize_text(source.text)
            if not source_text:
                continue
            source_start = max(0, source.start_time)
            source_end = max(source.end_time, source_start)
            source_duration = source_end - source_start
            if source_duration <= 0:
                continue

            uncovered_intervals = self._uncovered_intervals_ms(
                source_start, source_end, final_intervals
            )
            reportable_gaps = [
                (gap_start, gap_end)
                for gap_start, gap_end in uncovered_intervals
                if gap_end - gap_start >= min_gap_ms
            ]
            if not reportable_gaps:
                continue
            missing_ms = max(gap_end - gap_start for gap_start, gap_end in reportable_gaps)

            gap = {
                "source": index,
                "start": self._format_ms(source_start),
                "end": self._format_ms(source_end),
                "missing_ms": missing_ms,
                "missing_ranges": [
                    {
                        "start": self._format_ms(gap_start),
                        "end": self._format_ms(gap_end),
                        "duration_ms": gap_end - gap_start,
                    }
                    for gap_start, gap_end in reportable_gaps
                ],
                "text": source_text,
            }
            gaps.append(gap)
            logger.warning(
                "上屏字幕覆盖缺口 / Screen subtitle coverage gap: source=%s start=%s end=%s missing_ms=%s text=%s",
                index,
                gap["start"],
                gap["end"],
                missing_ms,
                source_text[:180],
            )

        if gaps:
            logger.warning("检测到上屏字幕覆盖缺口 / Coverage gaps detected: %s", len(gaps))
        else:
            logger.info("上屏字幕覆盖检查通过 / Coverage check passed")
        if translation_gaps:
            logger.warning(
                "检测到上屏字幕缺译文 / Missing translated subtitles detected: %s",
                len(translation_gaps),
            )
        self._write_coverage_report(gaps, translation_gaps, final_segments)

    def _write_coverage_report(
        self,
        gaps: Sequence[Dict],
        translation_gaps: Optional[Sequence[Dict]] = None,
        final_segments: Optional[Sequence[ASRDataSeg]] = None,
    ) -> None:
        translation_gaps = translation_gaps or []
        health = self._subtitle_health_issues(final_segments or [])
        validation_summary = self._validation_summary(
            gaps, translation_gaps, health, final_segments or []
        )
        final_timeline_errors = list(
            (getattr(self, "_final_cue_timeline", {}) or {}).get("validation", {}).get("errors", [])
            or []
        )
        self.last_validation_summary = validation_summary
        if not self.coverage_report_path:
            return
        try:
            report_path = Path(self.coverage_report_path)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            has_failures = bool(
                gaps
                or translation_gaps
                or health["overlong_english"]
                or health.get("structural_english_overflow", [])
                or health["bad_cuts"]
                or health["translationese"]
                or health["reading_speed_errors"]
                or health["reading_speed_warnings"]
                or health["duration_errors"]
                or health["duration_warnings"]
                or health["duplicate_chinese"]
                or health["asr_suspicious"]
                or health["discourse_marker_orphans"]
                or health["syntax_boundary_audit"]
                or health["chinese_semantic_group_warnings"]
                or health["chinese_semantic_group_info"]
                or final_timeline_errors
            )
            lines = [
                "字幕体检报告",
                "状态：发现需要人工检查的问题" if has_failures else "状态：通过，未发现明显问题",
                f"验证等级：{validation_summary['status']}",
                f"ERROR 数量：{len(validation_summary['errors'])}",
                f"WARNING 数量：{len(validation_summary['warnings'])}",
                f"INFO 数量：{len(validation_summary['info'])}",
                f"覆盖缺口数量：{len(gaps)}",
                f"最终显示连续化修复数量：{len(getattr(self, '_display_coverage_repairs', []))}",
                f"未自动修复的显示空档数量：{len(getattr(self, '_display_coverage_unresolved', []))}",
                f"缺中文字幕数量：{len(translation_gaps)}",
                f"英文超长数量：{len(health['overlong_english'])}",
                f"英文结构性超长警告数量：{len(health.get('structural_english_overflow', []))}",
                f"疑似坏切点数量：{len(health['bad_cuts'])}",
                f"疑似翻译腔数量：{len(health['translationese'])}",
                f"阅读速度严重问题数量：{len(health['reading_speed_errors'])}",
                f"阅读速度警告数量：{len(health['reading_speed_warnings'])}",
                f"字幕时长严重问题数量：{len(health['duration_errors'])}",
                f"字幕时长警告数量：{len(health['duration_warnings'])}",
                f"相邻中文疑似重复数量：{len(health['duplicate_chinese'])}",
                f"ASR 可疑文本数量：{len(health['asr_suspicious'])}",
                f"最终词账本时间轴错误数量：{len(final_timeline_errors)}",
                "",
            ]
            if validation_summary["errors"]:
                lines.append("零、ERROR（建议禁止自动合成）")
                for issue in validation_summary["errors"]:
                    lines.extend([f"- {issue['message']}", ""])
            if validation_summary["warnings"]:
                lines.append("零点五、WARNING（允许合成，但建议人工抽查）")
                for issue in validation_summary["warnings"]:
                    lines.extend([f"- {issue['message']}", ""])
            if gaps:
                lines.append("一、覆盖缺口")
                for gap in gaps:
                    lines.extend(
                        [
                            f"原始字幕编号：{gap['source']}",
                            f"时间：{gap['start']} --> {gap['end']}",
                            f"缺失时长：{gap['missing_ms']} 毫秒",
                            f"原文：{gap['text']}",
                            "",
                        ]
                    )
            if translation_gaps:
                lines.append("二、缺中文字幕")
                for gap in translation_gaps:
                    lines.extend(
                        [
                            f"时间：{gap['start']} --> {gap['end']}",
                            f"原文：{gap['text']}",
                            "",
                        ]
                    )
            if health["overlong_english"]:
                lines.append("三、英文超长")
                for issue in health["overlong_english"]:
                    lines.extend(
                        [
                            f"时间：{issue['start']} --> {issue['end']}",
                            f"词数：{issue['word_count']}，上限：{self.max_english_words}",
                            f"英文：{issue['text']}",
                            "",
                        ]
                    )
            if health.get("structural_english_overflow", []):
                lines.append("三点五、英文结构性超长警告")
                for issue in health.get("structural_english_overflow", []):
                    lines.extend(
                        [
                            f"时间：{issue['start']} --> {issue['end']}",
                            f"词数：{issue['word_count']}，正常上限：{issue['hard_limit']}",
                            f"原文：{issue['text']}",
                            "说明：所有不超过正常上限的内部切点都会破坏受保护句法；保留完整句并建议人工复核。",
                            "",
                        ]
                    )
            if health["bad_cuts"]:
                lines.append("四、疑似坏切点")
                for issue in health["bad_cuts"]:
                    lines.extend(
                        [
                            f"时间：{issue['start']} --> {issue['end']}",
                            f"原因：{issue['reason']}",
                            f"上一条：{issue['previous']}",
                            f"下一条：{issue['current']}",
                            f"建议：{issue['suggestion']}",
                            "",
                        ]
                    )
            if health["translationese"]:
                lines.append("五、疑似翻译腔")
                for issue in health["translationese"]:
                    lines.extend(
                        [
                            f"时间：{issue['start']} --> {issue['end']}",
                            f"原因：{issue['reason']}",
                            f"英文：{issue['original']}",
                            f"中文：{issue['translated']}",
                            "",
                        ]
                    )
            if health["reading_speed_errors"] or health["reading_speed_warnings"]:
                lines.append("六、阅读速度问题")
                for issue in list(health["reading_speed_errors"]) + list(health["reading_speed_warnings"]):
                    lines.extend(
                        [
                            f"级别：{issue['level']}",
                            f"序号：{issue['index']}",
                            f"时间：{issue['start']} --> {issue['end']}",
                            f"原因：{issue['reason']}",
                            f"英文：{issue.get('original', '')}",
                            f"中文：{issue.get('translated', '')}",
                            "",
                        ]
                    )
            if health["duration_errors"] or health["duration_warnings"]:
                lines.append("六点五、字幕持续时间问题")
                for issue in list(health["duration_errors"]) + list(health["duration_warnings"]):
                    lines.extend(
                        [
                            f"级别：{issue['level']}",
                            f"错误代码：{issue['code']}",
                            f"序号：{issue['index']}",
                            f"时间：{issue['start']} --> {issue['end']}",
                            f"持续时间：{issue['duration_ms']} ms",
                            f"触发阈值：{issue['threshold_ms']} ms",
                            f"英文：{issue.get('original', '')}",
                            f"中文：{issue.get('translated', '')}",
                            "",
                        ]
                    )
            if health["duplicate_chinese"]:
                lines.append("七、相邻中文疑似重复")
                for issue in health["duplicate_chinese"]:
                    lines.extend(
                        [
                            f"序号：{issue['previous_index']} / {issue['current_index']}",
                            f"相似度：{issue['similarity']}",
                            f"上一条：{issue['previous']}",
                            f"下一条：{issue['current']}",
                            "",
                        ]
                    )
            if health["asr_suspicious"]:
                lines.append("八、ASR 可疑文本")
                for issue in health["asr_suspicious"]:
                    lines.extend(
                        [
                            f"序号：{issue.get('index', '')}",
                            f"时间：{issue.get('start', '')} --> {issue.get('end', '')}",
                            f"原因：{issue['reason']}",
                            f"英文：{issue.get('text', '')}",
                            "",
                        ]
                    )
            if health["syntax_boundary_audit"]:
                lines.append("九、英文句法边界审计")
                for issue in health["syntax_boundary_audit"]:
                    lines.extend(
                        [
                            f"左字幕ID：{issue.get('left_subtitle_id', '')}",
                            f"右字幕ID：{issue.get('right_subtitle_id', '')}",
                            f"时间：{issue.get('start', '')} --> {issue.get('end', '')}",
                            f"规则代码：{', '.join(issue.get('rule_codes', []))}",
                            f"置信度：{issue.get('confidence', '')}",
                            f"依据：{issue.get('evidence', '')}",
                            f"是否与旧坏切点规则重复：{issue.get('duplicates_legacy_bad_cut', False)}",
                            f"左英文：{issue.get('previous_english', '')}",
                            f"右英文：{issue.get('current_english', '')}",
                            "",
                        ]
                    )
            if health["chinese_semantic_group_warnings"]:
                lines.append("十、中文语义组高置信审计")
                for issue in health["chinese_semantic_group_warnings"]:
                    lines.extend(
                        [
                            f"语义组ID：{issue.get('semantic_group_id', '')}",
                            f"字幕ID：{', '.join(issue.get('subtitle_ids', []))}",
                            f"时间：{issue.get('start', '')} --> {issue.get('end', '')}",
                            f"规则代码：{', '.join(issue.get('rule_codes', []))}",
                            f"置信度：{issue.get('confidence', '')}",
                            f"建议局部修复：{issue.get('suggest_llm_reallocation', False)}",
                            f"当前中文拼接：{issue.get('chinese', '')}",
                            f"第一阶段完整译文：{issue.get('full_translation', '')}",
                            f"英文语义组：{issue.get('english', '')}",
                            "",
                        ]
                    )
            if not has_failures:
                lines.append("未发现覆盖缺口、缺中文字幕、英文超长、明显坏切点、常见翻译腔、阅读速度异常、中文重复或 ASR 可疑文本。")
            report_path.write_text("\n".join(lines), encoding="utf-8")
            self._write_validation_artifact(report_path, validation_summary)
            self._write_editor_review_points_srt(report_path, final_segments or [])
            logger.info("上屏字幕覆盖报告已保存 / Coverage report saved: %s", report_path)
        except Exception as e:
            logger.warning("上屏字幕覆盖报告保存失败 / Coverage report save failed: %s", str(e))

    def _write_editor_review_points_srt(
        self,
        report_path: Path,
        final_segments: Sequence[ASRDataSeg],
    ) -> None:
        points = self._editor_review_points(final_segments)
        self._qa_review_points_count = len(points)
        srt_path = report_path.parent / "qa-review-points.srt"
        artifact_dir = stable_artifact_dir(report_path)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_srt_path = artifact_dir / "qa-review-points.srt"
        artifact_json_path = artifact_dir / "qa-review-points.json"
        self._qa_review_points_path = str(srt_path)
        srt_text = self._review_points_to_srt(points)
        try:
            srt_path.write_text(srt_text, encoding="utf-8-sig")
            artifact_srt_path.write_text(srt_text, encoding="utf-8-sig")
            write_json_artifact(artifact_json_path, points)
        except Exception as e:
            logger.warning("剪辑检查点字幕保存失败 / QA review SRT save failed: %s", str(e))

    def _editor_review_points(self, final_segments: Sequence[ASRDataSeg]) -> List[Dict]:
        segments_by_id = {
            self._segment_subtitle_id(segment, index): segment
            for index, segment in enumerate(final_segments, 1)
        }
        points: List[Dict] = []
        for record in getattr(self, "_last_allocation_unresolved", []) or []:
            issue_codes = [str(code) for code in record.get("issue_codes") or []]
            if not self._is_editor_visible_allocation_issue(record, issue_codes):
                continue
            allocation = record.get("allocation") if isinstance(record.get("allocation"), dict) else {}
            subtitle_ids = sorted(
                [str(subtitle_id) for subtitle_id in allocation if re.fullmatch(r"S\d{4}", str(subtitle_id))],
                key=lambda subtitle_id: int(subtitle_id[1:]),
            )
            if not subtitle_ids:
                continue
            first_segment = segments_by_id.get(subtitle_ids[0])
            if first_segment is None:
                continue
            context = []
            for subtitle_id in subtitle_ids:
                segment = segments_by_id.get(subtitle_id)
                if segment is None:
                    continue
                context.append(
                    {
                        "subtitle_id": subtitle_id,
                        "start_ms": int(segment.start_time),
                        "end_ms": int(segment.end_time),
                        "english": segment.text,
                        "chinese": segment.translated_text,
                    }
                )
            if not context:
                continue
            points.append(
                {
                    "code": "long_split_allocation_review",
                    "semantic_group_id": record.get("semantic_group_id", ""),
                    "subtitle_ids": subtitle_ids,
                    "issue_codes": issue_codes,
                    "reason": record.get("reason", ""),
                    "start_ms": int(first_segment.start_time),
                    "end_ms": int(context[-1].get("end_ms") or first_segment.end_time),
                    "full_english": record.get("full_english", ""),
                    "full_translation": record.get("full_translation", ""),
                    "context": context,
                }
            )
        points.sort(key=lambda point: int(point["subtitle_ids"][0][1:]) if point.get("subtitle_ids") else 0)
        return points

    def _is_editor_visible_allocation_issue(
        self,
        record: Dict,
        issue_codes: Sequence[str],
    ) -> bool:
        relevant_codes = {
            "cross_id_semantic_leakage",
            "group_allocation_information_omission",
            "entity_allocation_mismatch",
            "number_allocation_mismatch",
            "negation_allocation_mismatch",
            "adjacent_chinese_semantic_duplication",
        }
        if not (set(issue_codes) & relevant_codes):
            return False
        full_english = str(record.get("full_english") or "")
        allocation = record.get("allocation") if isinstance(record.get("allocation"), dict) else {}
        return len(allocation) >= 2 or word_count(full_english) >= self.max_english_words * 2

    def _review_points_to_srt(self, points: Sequence[Dict]) -> str:
        blocks: List[str] = []
        for index, point in enumerate(points, 1):
            subtitle_ids = self._compact_subtitle_id_list(point.get("subtitle_ids") or [])
            issue_codes = " / ".join(
                self._editor_review_issue_label(str(code))
                for code in point.get("issue_codes") or []
            )
            context = point.get("context") or []
            lines = [
                f"[QA] {subtitle_ids} 中英对应待检查",
                f"类型：{issue_codes}",
            ]
            if point.get("semantic_group_id"):
                lines.append(f"组：{point.get('semantic_group_id')}")
            for item in context[:3]:
                subtitle_id = str(item.get("subtitle_id") or "")
                english = self._clip_review_text(str(item.get("english") or ""), 54)
                chinese = self._clip_review_text(str(item.get("chinese") or ""), 54)
                lines.append(f"{subtitle_id} EN：{english}")
                lines.append(f"{subtitle_id} ZH：{chinese}")
            if len(context) > 3:
                lines.append(f"... 另 {len(context) - 3} 条见 qa-review-points.json")
            blocks.append(
                "\n".join(
                    [
                        str(index),
                        f"{ASRDataSeg._ms_to_srt_time(int(point.get('start_ms') or 0))} --> {ASRDataSeg._ms_to_srt_time(int(point.get('end_ms') or 0))}",
                        *lines,
                    ]
                )
            )
        return "\n\n".join(blocks) + ("\n" if blocks else "")

    @staticmethod
    def _clip_review_text(text: str, max_chars: int) -> str:
        compact = " ".join(str(text or "").split())
        if len(compact) <= max_chars:
            return compact
        return compact[: max(0, max_chars - 1)].rstrip() + "…"

    @staticmethod
    def _compact_subtitle_id_list(subtitle_ids: Sequence[str]) -> str:
        ids = [str(subtitle_id) for subtitle_id in subtitle_ids if re.fullmatch(r"S\d{4}", str(subtitle_id))]
        if len(ids) >= 2:
            numbers = [int(subtitle_id[1:]) for subtitle_id in ids]
            if numbers == list(range(numbers[0], numbers[-1] + 1)):
                return f"{ids[0]}-{ids[-1]}"
        return ",".join(ids)

    @staticmethod
    def _editor_review_issue_label(issue_code: str) -> str:
        labels = {
            "cross_id_semantic_leakage": "信息串条",
            "group_allocation_information_omission": "信息遗漏",
            "entity_allocation_mismatch": "实体错位",
            "number_allocation_mismatch": "数字错位",
            "negation_allocation_mismatch": "否定错位",
            "adjacent_chinese_semantic_duplication": "相邻重复",
        }
        return labels.get(issue_code, issue_code)

    def has_blocking_validation_errors(self) -> bool:
        final_timeline_errors = list(
            (getattr(self, "_final_cue_timeline", {}) or {}).get("validation", {}).get("errors", [])
            or []
        )
        hard_boundary_errors = [
            group
            for group in ((getattr(self, "last_validation_summary", {}) or {}).get("errors", []) or [])
            if group.get("code") == "hard_english_boundary"
        ]
        return bool(
            self._translation_structure_errors
            or final_timeline_errors
            or hard_boundary_errors
        )

    def blocking_validation_message(self) -> str:
        errors = list(self._translation_structure_errors or [])
        errors.extend(
            (getattr(self, "_final_cue_timeline", {}) or {}).get("validation", {}).get("errors", [])
            or []
        )
        errors.extend(
            group
            for group in ((getattr(self, "last_validation_summary", {}) or {}).get("errors", []) or [])
            if group.get("code") == "hard_english_boundary"
        )
        if not errors:
            return ""
        messages = [str(error.get("message") or error.get("code") or "未知错误") for error in errors]
        return "；".join(messages)

    def _validation_summary(
        self,
        gaps: Sequence[Dict],
        translation_gaps: Sequence[Dict],
        health: Dict[str, List[Dict]],
        final_segments: Sequence[ASRDataSeg],
    ) -> Dict:
        errors: List[Dict] = []
        warnings: List[Dict] = []
        info: List[Dict] = []

        if gaps:
            warnings.append(
                {
                    "code": "coverage_gap_unverified",
                    "message": f"存在 {len(gaps)} 处字幕覆盖空档；未接入 VAD 证据，仅作为 WARNING。",
                    "items": list(gaps),
                }
            )
        if translation_gaps:
            errors.append(
                {
                    "code": "missing_translation",
                    "message": f"存在 {len(translation_gaps)} 条英文字幕缺少中文字幕。",
                    "items": list(translation_gaps),
                }
            )
        if health["overlong_english"]:
            errors.append(
                {
                    "code": "overlong_english",
                    "message": f"存在 {len(health['overlong_english'])} 条英文字幕超过硬上限。",
                    "items": health["overlong_english"],
                }
            )
        if health.get("structural_english_overflow", []):
            warnings.append(
                {
                    "code": "structural_english_overflow",
                    "message": f"存在 {len(health.get('structural_english_overflow', []))} 条无法安全缩至正常上限的完整英文句。",
                    "items": health.get("structural_english_overflow", []),
                }
            )

        timing_errors = self._timing_validation_issues(final_segments)
        if timing_errors:
            errors.append(
                {
                    "code": "invalid_timing",
                    "message": f"存在 {len(timing_errors)} 处时间轴异常。",
                    "items": timing_errors,
                }
            )
        if health["reading_speed_errors"]:
            errors.append(
                {
                    "code": "reading_speed_error",
                    "message": f"存在 {len(health['reading_speed_errors'])} 条字幕阅读速度严重超限。",
                    "items": health["reading_speed_errors"],
                }
            )
        if health["duration_errors"]:
            errors.append(
                {
                    "code": "subtitle_duration_invalid",
                    "message": f"存在 {len(health['duration_errors'])} 条字幕显示时间严重异常。",
                    "items": health["duration_errors"],
                }
            )

        if self._translation_structure_errors:
            errors.extend(self._translation_structure_errors)

        final_timeline_errors = list(
            (getattr(self, "_final_cue_timeline", {}) or {}).get("validation", {}).get("errors", [])
            or []
        )
        if final_timeline_errors:
            errors.append(
                {
                    "code": "final_cue_timeline_invalid",
                    "message": f"最终字幕词账本时间轴存在 {len(final_timeline_errors)} 处契约错误。",
                    "items": final_timeline_errors,
                }
            )

        if health["bad_cuts"]:
            warnings.append(
                {
                    "code": "suspicious_cut",
                    "message": f"存在 {len(health['bad_cuts'])} 处疑似机器感切点。",
                    "items": health["bad_cuts"],
                }
            )
        if health["translationese"]:
            warnings.append(
                {
                    "code": "translationese",
                    "message": f"存在 {len(health['translationese'])} 处疑似翻译腔。",
                    "items": health["translationese"],
                }
            )
        if health["reading_speed_warnings"]:
            warnings.append(
                {
                    "code": "reading_speed_warning",
                    "message": f"存在 {len(health['reading_speed_warnings'])} 条字幕阅读速度偏快。",
                    "items": health["reading_speed_warnings"],
                }
            )
        if health["duration_warnings"]:
            warnings.append(
                {
                    "code": "subtitle_duration_short_warning",
                    "message": f"存在 {len(health['duration_warnings'])} 条字幕显示时间低于 {SUBTITLE_DURATION_WARNING_MS}ms。",
                    "items": health["duration_warnings"],
                }
            )
        if health["duplicate_chinese"]:
            warnings.append(
                {
                    "code": "duplicate_chinese",
                    "message": f"存在 {len(health['duplicate_chinese'])} 处相邻中文字幕疑似重复。",
                    "items": health["duplicate_chinese"],
                }
            )
        if health["asr_suspicious"]:
            warnings.append(
                {
                    "code": "asr_suspicious",
                    "message": f"存在 {len(health['asr_suspicious'])} 处 ASR 可疑文本。",
                    "items": health["asr_suspicious"],
                }
            )
        if health["discourse_marker_orphans"]:
            warnings.append(
                {
                    "code": "discourse_marker_orphan",
                    "message": f"存在 {len(health['discourse_marker_orphans'])} 处无法安全归并的孤立口头标记。",
                    "items": health["discourse_marker_orphans"],
                }
            )

        hard_boundary_issues = [
            issue
            for issue in health["syntax_boundary_audit"]
            if issue.get("classification") == "hard"
        ]
        review_boundary_issues = [
            issue
            for issue in health["syntax_boundary_audit"]
            if issue.get("classification") == "review"
        ]
        if hard_boundary_issues:
            errors.append(
                {
                    "code": "hard_english_boundary",
                    "message": f"存在 {len(hard_boundary_issues)} 处未被预 ID 修复的高置信英文边界错误。",
                    "items": hard_boundary_issues,
                }
            )
        if review_boundary_issues:
            warnings.append(
                {
                    "code": "syntax_boundary_audit",
                    "message": f"存在 {len(review_boundary_issues)} 处需要人工复核的英文边界。",
                    "items": review_boundary_issues,
                }
            )
        if health["chinese_semantic_group_warnings"]:
            warnings.append(
                {
                    "code": "chinese_semantic_group_warning",
                    "message": f"存在 {len(health['chinese_semantic_group_warnings'])} 处中文语义组疑似病句或语义不完整。",
                    "items": health["chinese_semantic_group_warnings"],
                }
            )
        if health["chinese_semantic_group_info"]:
            info.append(
                {
                    "code": "chinese_semantic_group_info",
                    "message": f"存在 {len(health['chinese_semantic_group_info'])} 处中文语义组低置信提示。",
                    "items": health["chinese_semantic_group_info"],
                }
            )

        english_segments = [
            seg
            for seg in final_segments
            if self._normalize_text(seg.text) and re.search(r"[A-Za-z]", seg.text)
        ]
        if english_segments:
            word_counts = [self._word_count(seg.text) for seg in english_segments]
            durations = [
                max(0, seg.end_time - seg.start_time) for seg in english_segments
            ]
            info.append(
                {
                    "code": "subtitle_stats",
                    "message": "字幕统计信息。",
                    "items": {
                        "english_segments": len(english_segments),
                        "max_words": max(word_counts),
                        "avg_words": round(sum(word_counts) / len(word_counts), 2),
                        "avg_duration_ms": round(sum(durations) / len(durations), 2),
                    },
                }
            )

        summary = {
            "status": "ERROR" if errors else ("WARNING" if warnings else "PASS"),
            "errors": errors,
            "warnings": warnings,
            "info": info,
        }
        summary["review"] = self._validation_review_summary(errors, warnings, info)
        return summary

    def _validation_review_summary(
        self,
        errors: Sequence[Dict],
        warnings: Sequence[Dict],
        info: Sequence[Dict],
    ) -> Dict:
        entries: List[Dict] = []
        for source_level, groups in (
            ("error", errors),
            ("warning", warnings),
            ("info", info),
        ):
            for group in groups:
                code = str(group.get("code") or "unknown")
                items = group.get("items")
                item_count = len(items) if isinstance(items, list) else (1 if items else 0)
                severity = self._validation_review_severity(code, source_level)
                affected_payload = items if items is not None else group
                entries.append(
                    {
                        "severity": severity,
                        "source_level": source_level,
                        "code": code,
                        "message": group.get("message", ""),
                        "item_count": item_count,
                        "action_required": severity in {"BLOCKER", "REVIEW"},
                        "why_review": self._validation_review_reason(code, severity),
                        "affected_subtitle_ids": self._validation_affected_subtitle_ids(affected_payload),
                        "semantic_group_ids": self._validation_affected_semantic_group_ids(affected_payload),
                    }
                )

        allocation_unresolved = list(getattr(self, "_last_allocation_unresolved", []) or [])
        for record in allocation_unresolved:
            issue_codes = [str(code) for code in record.get("issue_codes") or []]
            severity = "BLOCKER" if self._allocation_unresolved_has_high_confidence_issue(issue_codes) else "REVIEW"
            entries.append(
                {
                    "severity": severity,
                    "source_level": "allocation_quality",
                    "code": "allocation_quality_unresolved",
                    "message": record.get("reason", ""),
                    "item_count": 1,
                    "action_required": True,
                    "why_review": self._validation_review_reason("allocation_quality_unresolved", severity),
                    "affected_subtitle_ids": self._validation_affected_subtitle_ids(record.get("allocation")),
                    "semantic_group_ids": self._validation_affected_semantic_group_ids(record),
                    "issue_codes": issue_codes,
                }
            )

        counts = {"BLOCKER": 0, "REVIEW": 0, "INFO": 0}
        for entry in entries:
            counts[entry["severity"]] = counts.get(entry["severity"], 0) + int(entry.get("item_count") or 1)
        return {
            "schema_version": 2,
            "summary": {
                "blocker_count": counts.get("BLOCKER", 0),
                "review_count": counts.get("REVIEW", 0),
                "info_count": counts.get("INFO", 0),
                "actionable_count": counts.get("BLOCKER", 0) + counts.get("REVIEW", 0),
            },
            "items": entries,
        }

    @staticmethod
    def _validation_review_severity(code: str, source_level: str) -> str:
        blocker_codes = {
            "missing_translation",
            "overlong_english",
            "invalid_timing",
            "subtitle_duration_invalid",
            "translation_id_missing",
            "translation_id_duplicate",
            "translation_id_unknown",
            "translation_group_cardinality_mismatch",
            "final_translation_id_mismatch",
            "final_cue_timeline_invalid",
            "hard_english_boundary",
            "allocation_quality_unresolved",
        }
        review_codes = {
            "coverage_gap_unverified",
            "reading_speed_error",
            "suspicious_cut",
            "translationese",
            "reading_speed_warning",
            "subtitle_duration_short_warning",
            "duplicate_chinese",
            "asr_suspicious",
            "discourse_marker_orphan",
            "syntax_boundary_audit",
            "chinese_semantic_group_warning",
        }
        if code in blocker_codes or code.startswith("translation_id_"):
            return "BLOCKER"
        if code in review_codes or source_level == "warning":
            return "REVIEW"
        return "INFO"

    @staticmethod
    def _validation_review_reason(code: str, severity: str) -> str:
        reasons = {
            "missing_translation": "Chinese text is missing for one or more frozen subtitle IDs.",
            "overlong_english": "English text exceeds the hard subtitle word limit.",
            "structural_english_overflow": "A complete English sentence has no safe internal cut within the normal word limit.",
            "invalid_timing": "Subtitle timestamps are invalid or overlapping.",
            "subtitle_duration_invalid": "Subtitle duration is below the hard display limit.",
            "translation_id_missing": "LLM allocation omitted an expected subtitle ID.",
            "translation_id_duplicate": "LLM allocation returned the same subtitle ID more than once.",
            "translation_id_unknown": "LLM allocation returned a subtitle ID outside the frozen set.",
            "translation_group_cardinality_mismatch": "Returned allocation ID set differs from the expected group ID set.",
            "final_translation_id_mismatch": "Final writeback ID set differs from frozen English subtitle IDs.",
            "final_cue_timeline_invalid": "Final cue timing does not match the frozen subtitle ID and word-ledger contract.",
            "hard_english_boundary": "A high-confidence English boundary survived the pre-ID automatic repair stage.",
            "allocation_quality_unresolved": "A high-confidence allocation issue remained after retry or retry was rejected.",
            "reading_speed_error": "A subtitle likely needs manual shortening or timing review.",
            "suspicious_cut": "English boundary may split a phrase unnaturally.",
            "syntax_boundary_audit": "A syntax-aware boundary rule flagged this cut.",
            "chinese_semantic_group_warning": "Chinese group audit found a possible semantic or fluency issue.",
            "asr_suspicious": "ASR text contains a suspicious token pattern.",
            "duplicate_chinese": "Adjacent Chinese subtitles may repeat the same content.",
        }
        return reasons.get(code, f"{severity} validation item; inspect the grouped evidence.")

    @staticmethod
    def _validation_affected_subtitle_ids(payload) -> List[str]:
        found: set[str] = set()

        def collect(value) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(key, str) and re.fullmatch(r"S\d{4}", key):
                        found.add(key)
                    if key in {
                        "subtitle_id",
                        "left_subtitle_id",
                        "right_subtitle_id",
                    } and isinstance(item, str):
                        found.add(item)
                    elif key in {
                        "subtitle_ids",
                        "expected_subtitle_ids",
                        "returned_subtitle_ids",
                        "mapped_subtitle_ids",
                        "missing_subtitle_ids",
                        "duplicate_subtitle_ids",
                        "unknown_subtitle_ids",
                    } and isinstance(item, list):
                        for subtitle_id in item:
                            if isinstance(subtitle_id, str):
                                found.add(subtitle_id)
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        return sorted(subtitle_id for subtitle_id in found if re.fullmatch(r"S\d{4}", subtitle_id))

    @staticmethod
    def _validation_affected_semantic_group_ids(payload) -> List[str]:
        found: set[str] = set()

        def collect(value) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "semantic_group_id" and isinstance(item, str):
                        found.add(item)
                    elif key == "semantic_group_ids" and isinstance(item, list):
                        for group_id in item:
                            if isinstance(group_id, str):
                                found.add(group_id)
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        return sorted(group_id for group_id in found if re.fullmatch(r"G\d{4}", group_id))

    @staticmethod
    def _allocation_unresolved_has_high_confidence_issue(issue_codes: Sequence[str]) -> bool:
        high_confidence_codes = {
            "adjacent_chinese_semantic_duplication",
            "cross_id_semantic_leakage",
            "group_allocation_information_omission",
            "entity_allocation_mismatch",
            "number_allocation_mismatch",
            "negation_allocation_mismatch",
            "unnatural_chinese_fragment",
            "translation_group_cardinality_mismatch",
        }
        return bool(set(issue_codes) & high_confidence_codes)

    @staticmethod
    def _timing_validation_issues(segments: Sequence[ASRDataSeg]) -> List[Dict]:
        issues: List[Dict] = []
        previous_end: Optional[int] = None
        for index, seg in enumerate(segments, 1):
            start = max(0, int(seg.start_time))
            end = int(seg.end_time)
            if end <= start:
                issues.append(
                    {
                        "index": index,
                        "reason": "字幕结束时间不大于开始时间",
                        "start_ms": start,
                        "end_ms": end,
                    }
                )
            if previous_end is not None and start < previous_end - 5:
                issues.append(
                    {
                        "index": index,
                        "reason": "字幕时间轴重叠",
                        "start_ms": start,
                        "previous_end_ms": previous_end,
                    }
                )
            previous_end = max(previous_end or 0, end)
        return issues

    def _write_validation_artifact(self, report_path: Path, summary: Dict) -> None:
        try:
            artifact_dir = stable_artifact_dir(report_path)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            write_json_artifact(artifact_dir / "validation-report.json", summary)
        except Exception as e:
            logger.warning("验证 JSON 保存失败 / Validation JSON save failed: %s", str(e))

    def _write_stable_pipeline_artifacts(
        self,
        source_segments: Sequence[ASRDataSeg],
        semantic_groups: Sequence[Dict],
        subtitle_items: Sequence[ScreenSubtitleItem],
        final_segments: Sequence[ASRDataSeg],
    ) -> None:
        if not self.coverage_report_path:
            return
        try:
            report_path = Path(self.coverage_report_path)
            artifact_dir = stable_artifact_dir(report_path)
            artifact_dir.mkdir(parents=True, exist_ok=True)

            manifest = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "pipeline": "screen_subtitle_stable",
                "model": self.model,
                "translation_model": self.model,
                "code_commit": self._current_git_commit(),
                "cache_used": self._llm_cache_used,
                "prompt_version": SCREEN_SUBTITLE_PROMPT_VERSION,
                "target_language": self.target_language,
                "max_cjk_chars": self.max_cjk_chars,
                "max_english_words": self.max_english_words,
                "chinese_polish_enabled": self.enable_chinese_polish,
                "allocation_max_concurrency": self.allocation_max_concurrency,
                "allocation_batch_size": self.allocation_batch_size,
                "stable_chinese_cache_contract": dict(
                    getattr(self, "_chinese_cache_contract", {}) or {}
                ),
                "llm_cache_stats": self._llm_cache_stats,
                "allocation_runtime_stats": self._allocation_runtime_stats,
                "source_segment_count": len(source_segments),
                "word_count": len(self._active_word_entries),
                "subtitle_count": len(final_segments),
                "frozen_subtitle_ids": list(self._frozen_subtitle_ids),
                "translation_structure_error_count": len(self._translation_structure_errors),
                "display_coverage_bridge_count": len(getattr(self, "_display_coverage_repairs", [])),
                "display_coverage_unresolved_count": len(getattr(self, "_display_coverage_unresolved", [])),
                "final_cue_timeline_validation_status": str(
                    (getattr(self, "_final_cue_timeline", {}) or {}).get("validation", {}).get("status")
                    or "NOT_BUILT"
                ),
                "final_cue_timeline_error_count": int(
                    (getattr(self, "_final_cue_timeline", {}) or {}).get("validation", {}).get("error_count")
                    or 0
                ),
                "final_word_timing_reconciliation_count": len(
                    getattr(self, "_final_word_timing_reconciliations", []) or []
                ),
                "artifact_schema_version": 2,
            }
            final_timeline_path = artifact_dir / "final-cue-timeline.json"
            self._final_cue_timeline_path = str(final_timeline_path)
            write_json_artifact_set(
                artifact_dir,
                (
                    ("run-manifest.json", manifest),
                    (
                        "transcript.json",
                        [
                            self._segment_to_dict(index, seg)
                            for index, seg in enumerate(source_segments, 1)
                        ],
                    ),
                    ("word-ledger.json", self._word_ledger_payload(source_segments)),
                    (
                        "final-cue-timeline.json",
                        getattr(self, "_final_cue_timeline", {}) or {},
                    ),
                    ("semantic-groups.json", self._semantic_groups_payload(semantic_groups)),
                    (
                        "subtitle-spans.json",
                        [
                            self._item_to_span_dict(index, item)
                            for index, item in enumerate(subtitle_items, 1)
                        ],
                    ),
                    ("stable-boundary-snapshots.json", self._boundary_snapshot_payload()),
                    (
                        "english-boundary-audit.json",
                        self._english_boundary_audit_payload(final_segments),
                    ),
                    (
                        "translations.json",
                        [
                            self._segment_to_dict(index, seg)
                            for index, seg in enumerate(final_segments, 1)
                        ],
                    ),
                    ("llm-raw-returns.json", self._last_llm_raw_returns),
                    (
                        "full-translation-style-retry-log.json",
                        getattr(self, "_last_full_translation_style_retry_log", []),
                    ),
                    ("allocation-inputs.json", self._last_allocation_inputs),
                    ("allocation-raw-returns.json", self._last_allocation_raw_returns),
                    ("allocation-validation.json", self._last_allocation_validation),
                    ("allocation-retry-log.json", self._last_allocation_retry_log),
                    (
                        "allocation-final.json",
                        self._final_allocation_payload(semantic_groups, subtitle_items),
                    ),
                    ("allocation-unresolved.json", self._last_allocation_unresolved),
                    ("allocation-isolation-report.json", self._allocation_isolation_report),
                    ("semantic-group-debug.json", self._last_semantic_group_debug),
                    ("translation-structure-errors.json", self._translation_structure_errors),
                    (
                        "display-coverage-repairs.json",
                        getattr(self, "_display_coverage_repairs", []),
                    ),
                    (
                        "display-coverage-unresolved.json",
                        getattr(self, "_display_coverage_unresolved", []),
                    ),
                ),
            )
            logger.info("稳定模式中间产物已保存 / Stable artifacts saved: %s", artifact_dir)
        except Exception as e:
            logger.warning("稳定模式中间产物保存失败 / Stable artifacts save failed: %s", str(e))

    def _boundary_snapshot_payload(self) -> Dict:
        focus_phrases = [
            "founder of a non-profit",
            "made it to the top",
            "highly valuable",
            "those 200 economists",
            "a few thousand",
            "better than you found it",
            "navigated his way",
            "straight into the absolute tundra",
            "issued this stark public warning",
            "entire professions extinct",
            "helped expose the crimes",
            "work doesn't have to be a tradeoff",
            "a Pulitzer Prize-winning journalist",
            "the vast majority of people",
            "How on earth do you know",
            "never ever be automated",
            "a high-paying corporate job",
            "feels incredibly heavy",
            "80 000 hours",
            "what you are actually good at",
            "skill building",
            "large-scale job displacement",
        ]
        repairs = getattr(self, "_pre_id_boundary_repairs", [])
        final_boundary_issue_count = 0
        for snapshot in self._boundary_snapshots[-1:]:
            for boundary in snapshot.get("boundaries", []):
                final_boundary_issue_count += len(boundary.get("hard_issues") or [])
        final_fragment_issue_count = sum(
            len(repair.get("hard_fragment_issues") or [])
            for repair in repairs
        )
        return {
            "schema_version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "word_ledger_hash": self._word_ledger_hash(),
            "max_english_words": self.max_english_words,
            "visual_reading_budget": {
                "word_limit": VISUAL_ENGLISH_WORD_SOFT_LIMIT,
                "character_limit": VISUAL_ENGLISH_CHARACTER_SOFT_LIMIT,
            },
            "stages": self._boundary_snapshots,
            "changes": self._boundary_snapshot_changes,
            "pre_id_boundary_repairs": repairs,
            "stats": {
                "final_hard_boundary_issue_count": final_boundary_issue_count,
                "final_soft_boundary_issue_count": 0,
                "final_hard_fragment_issue_count": final_fragment_issue_count,
                "final_soft_fragment_issue_count": 0,
                "unresolved_final_boundary_issue_count": sum(
                    1
                    for repair in repairs
                    if repair.get("unresolved_hard_issue")
                    and repair.get("repair_reason") != "unresolved_final_fragment_issue"
                ),
                "unresolved_final_fragment_issue_count": sum(
                    1
                    for repair in repairs
                    if repair.get("unresolved_hard_issue")
                    and repair.get("repair_reason") == "unresolved_final_fragment_issue"
                ),
                "unresolved_visual_reading_budget_count": sum(
                    1
                    for repair in repairs
                    if repair.get("unresolved_visual_warning")
                    and repair.get("repair_reason") == "visual_budget_unresolved"
                ),
            },
            "focus_phrases": self._boundary_focus_phrase_report(focus_phrases),
        }

    def _boundary_focus_phrase_report(self, phrases: Sequence[str]) -> List[Dict]:
        reports: List[Dict] = []
        for phrase in phrases:
            phrase_tokens = [token.casefold() for token in self._word_tokens(phrase)]
            if not phrase_tokens:
                continue
            occurrences = self._find_word_token_occurrences(phrase_tokens)
            phrase_report = {
                "phrase": phrase,
                "occurrences": [],
            }
            for start, end in occurrences:
                occurrence = {
                    "word_range": [start, end],
                    "surface": self._text_from_word_span(start, end),
                    "stage_boundaries": [],
                    "first_split_stage": "",
                    "first_split_by": "",
                }
                for snapshot in self._boundary_snapshots:
                    boundaries = [
                        record
                        for record in snapshot.get("boundaries", [])
                        if start <= int(record.get("cut", [-1, -1])[0]) < end
                    ]
                    if boundaries and not occurrence["first_split_stage"]:
                        occurrence["first_split_stage"] = snapshot.get("stage", "")
                        occurrence["first_split_by"] = snapshot.get("created_by", "")
                    occurrence["stage_boundaries"].append(
                        {
                            "stage": snapshot.get("stage", ""),
                            "split_inside_phrase": bool(boundaries),
                            "boundaries": boundaries,
                        }
                    )
                phrase_report["occurrences"].append(occurrence)
            reports.append(phrase_report)
        return reports

    def _find_word_token_occurrences(self, phrase_tokens: Sequence[str]) -> List[tuple[int, int]]:
        ledger_tokens = [
            self._clean_boundary_token(entry.get("token") or entry.get("surface") or "")
            for entry in self._active_word_entries
        ]
        targets = [self._clean_boundary_token(token) for token in phrase_tokens]
        result: List[tuple[int, int]] = []
        size = len(targets)
        if not ledger_tokens or not targets:
            return result
        for index in range(0, len(ledger_tokens) - size + 1):
            if ledger_tokens[index:index + size] == targets:
                result.append((index, index + size - 1))
        return result

    def _word_ledger_payload(self, source_segments: Sequence[ASRDataSeg]) -> Dict:
        return {
            "schema_version": 1,
            "hash": self._word_ledger_hash(),
            "words": [
                {
                    "word_id": index,
                    "surface": entry.get("surface") or entry.get("token") or "",
                    "normalized": entry.get("token") or "",
                    "start_ms": int(entry.get("start_time") or 0),
                    "end_ms": int(entry.get("end_time") or 0),
                    "alignment_source": str(entry.get("alignment_source") or "stable-ts"),
                    "source_segment_ids": self._source_ids_for_word_range(index, index),
                }
                for index, entry in enumerate(self._active_word_entries)
            ],
            "source_segments": [
                self._segment_to_dict(index, seg)
                for index, seg in enumerate(source_segments, 1)
            ],
        }

    def _word_ledger_hash(self) -> str:
        payload = [
            [
                entry.get("surface") or entry.get("token") or "",
                entry.get("token") or "",
                int(entry.get("start_time") or 0),
                int(entry.get("end_time") or 0),
            ]
            for entry in self._active_word_entries
        ]
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _allocation_isolation_snapshot(
        self,
        *,
        stage: str,
        source_segments: Sequence[ASRDataSeg],
        items: Sequence[ScreenSubtitleItem],
        semantic_groups: Sequence[Dict],
        full_translations: Dict[int, str],
        final_segments: Optional[Sequence[ASRDataSeg]] = None,
    ) -> Dict:
        source_payload = [
            {
                "index": index,
                "start_ms": int(seg.start_time),
                "end_ms": int(seg.end_time),
                "text": seg.text,
            }
            for index, seg in enumerate(source_segments or [], 1)
        ]
        item_payload = [
            {
                "subtitle_id": item.subtitle_id or f"S{index:04d}",
                "original": item.original,
                "word_start": item.word_start,
                "word_end": item.word_end,
            }
            for index, item in enumerate(items or [], 1)
        ]
        item_time_payload = [
            {
                "subtitle_id": item.subtitle_id or f"S{index:04d}",
                "word_start": item.word_start,
                "word_end": item.word_end,
                "start_ms": self._item_boundary_time_ms(item, "start"),
                "end_ms": self._item_boundary_time_ms(item, "end"),
            }
            for index, item in enumerate(items or [], 1)
        ]
        final_time_payload = [
            {
                "subtitle_id": self._segment_subtitle_id(seg, index),
                "start_ms": int(seg.start_time),
                "end_ms": int(seg.end_time),
                "text": seg.text,
            }
            for index, seg in enumerate(final_segments or [], 1)
        ]
        group_payload = [
            {
                "semantic_group_id": f"G{int(group.get('id') or 0):04d}",
                "expected_subtitle_ids": self._group_expected_subtitle_ids(group),
                "full_english": " ".join(item.original for item in group.get("items", [])),
            }
            for group in semantic_groups or []
        ]
        full_translation_payload = [
            {
                "semantic_group_id": f"G{int(group_id):04d}",
                "full_translation": text or "",
            }
            for group_id, text in sorted((full_translations or {}).items())
        ]
        word_timing_payload = [
            [
                index,
                entry.get("surface") or entry.get("token") or "",
                int(entry.get("start_time") or 0),
                int(entry.get("end_time") or 0),
            ]
            for index, entry in enumerate(self._active_word_entries)
        ]
        return FrozenPipelineSnapshot.build(
            stage=stage,
            source_segments=source_payload,
            subtitle_items=item_payload,
            subtitle_id_times=item_time_payload,
            semantic_groups=group_payload,
            full_translations=full_translation_payload,
            word_timing=word_timing_payload,
            word_ledger_hash=self._word_ledger_hash(),
            final_segments=final_time_payload,
            include_final_segment_timing=final_segments is not None,
        ).to_artifact()

    def _build_allocation_isolation_report(self, before: Dict, after: Dict) -> Dict:
        before_snapshot = FrozenPipelineSnapshot(
            stage=str(before.get("stage") or ""),
            hashes={key: str(before.get(key) or "") for key in FROZEN_PIPELINE_HASH_KEYS},
            payloads=dict(before.get("payloads") or {}),
        )
        after_snapshot = FrozenPipelineSnapshot(
            stage=str(after.get("stage") or ""),
            hashes={key: str(after.get(key) or "") for key in FROZEN_PIPELINE_HASH_KEYS},
            payloads=dict(after.get("payloads") or {}),
        )
        changed_keys = before_snapshot.changed_frozen_keys(after_snapshot)
        first_differences = {
            key: self._allocation_isolation_first_difference(before, after, key)
            for key in changed_keys
        }
        return {
            "schema_version": 1,
            "status": "allocation_isolation_failed" if changed_keys else "passed",
            "changed_keys": changed_keys,
            "before": {key: before.get(key, "") for key in FROZEN_PIPELINE_HASH_KEYS},
            "after": {key: after.get(key, "") for key in FROZEN_PIPELINE_HASH_KEYS},
            "first_differences": first_differences,
        }

    def _allocation_isolation_first_difference(self, before: Dict, after: Dict, key: str) -> Dict:
        payload_key = {
            "asr_text_hash": "source_segments",
            "corrected_english_hash": "source_segments",
            "english_text_hash": "subtitle_items",
            "subtitle_id_time_hash": "subtitle_id_times",
            "semantic_group_input_hash": "semantic_groups",
            "authoritative_full_translation_hash": "full_translations",
            "word_timing_hash": "word_timing",
            "word_ledger_hash": "word_timing",
        }.get(key, "")
        left = list((before.get("payloads") or {}).get(payload_key) or [])
        right = list((after.get("payloads") or {}).get(payload_key) or [])
        for index, (left_item, right_item) in enumerate(zip(left, right), 1):
            if left_item != right_item:
                return {
                    "payload": payload_key,
                    "index": index,
                    "before": left_item,
                    "after": right_item,
                }
        if len(left) != len(right):
            return {
                "payload": payload_key,
                "index": min(len(left), len(right)) + 1,
                "before_count": len(left),
                "after_count": len(right),
            }
        return {"payload": payload_key, "reason": "hash_changed_but_first_difference_not_found"}

    def _item_boundary_time_ms(self, item: ScreenSubtitleItem, side: str) -> int:
        if not self._active_word_entries:
            return 0
        word_index = item.word_start if side == "start" else item.word_end
        if word_index is None or word_index < 0 or word_index >= len(self._active_word_entries):
            return 0
        entry = self._active_word_entries[word_index]
        key = "start_time" if side == "start" else "end_time"
        return int(entry.get(key) or 0)

    def _semantic_groups_payload(self, groups: Sequence[Dict]) -> List[Dict]:
        payload: List[Dict] = []
        for group in groups:
            items = group.get("items", [])
            payload.append(
                {
                    "group_id": group.get("id"),
                    "start_index": group.get("start_index"),
                    "subtitle_count": len(items),
                    "expected_subtitle_ids": self._group_expected_subtitle_ids(group),
                    "full_english": " ".join(item.original for item in items),
                    "subtitle_parts": [
                        self._item_to_span_dict(index, item)
                        for index, item in enumerate(items, 1)
                    ],
                }
            )
        return payload

    def _final_allocation_payload(
        self,
        groups: Sequence[Dict],
        subtitle_items: Sequence[ScreenSubtitleItem],
    ) -> List[Dict]:
        """Serialize the final Chinese mapping from the actual ID-bound writeback.

        Allocation attempts are useful provenance, but an unresolved retry must
        not make the final artifact omit IDs that were retained in the final
        subtitle items.  This artifact therefore follows the same fixed-ID
        Chinese values that export receives.
        """
        chinese_by_id = {
            self._item_subtitle_id(item, index): item.translated
            for index, item in enumerate(subtitle_items, 1)
        }
        attempted_by_group = {
            str(record.get("semantic_group_id") or ""): record
            for record in self._last_allocation_final
            if isinstance(record, dict)
        }
        payload: List[Dict] = []
        for group in groups:
            group_id = int(group.get("id") or 0)
            semantic_group_id = f"G{group_id:04d}"
            subtitle_ids = self._group_expected_subtitle_ids(group)
            allocation = {
                subtitle_id: str(chinese_by_id.get(subtitle_id, "") or "")
                for subtitle_id in subtitle_ids
            }
            attempted = attempted_by_group.get(semantic_group_id)
            if attempted and attempted.get("allocation") == allocation:
                source = str(attempted.get("source") or "initial")
            elif attempted:
                source = "final_subtitle_items"
            else:
                source = "unresolved_final_subtitle_items"
            payload.append(
                {
                    "semantic_group_id": semantic_group_id,
                    "subtitle_ids": subtitle_ids,
                    "allocation": allocation,
                    "source": source,
                }
            )
        return payload

    @staticmethod
    def _item_to_span_dict(index: int, item: ScreenSubtitleItem) -> Dict:
        return {
            "subtitle_id": item.subtitle_id or f"S{index:04d}",
            "source_ids": item.source_ids,
            "word_start": item.word_start,
            "word_end": item.word_end,
            "original": item.original,
            "translated": item.translated,
        }

    @staticmethod
    def _segment_to_dict(index: int, seg: ASRDataSeg) -> Dict:
        return {
            "id": index,
            "subtitle_id": str(getattr(seg, "subtitle_id", "") or f"S{index:04d}"),
            "start_ms": int(seg.start_time),
            "end_ms": int(seg.end_time),
            "text": seg.text,
            "translated_text": seg.translated_text,
        }

    def _subtitle_health_issues(
        self, final_segments: Sequence[ASRDataSeg]
    ) -> Dict[str, List[Dict]]:
        english_segments = [
            seg
            for seg in final_segments
            if self._normalize_text(seg.text) and re.search(r"[A-Za-z]", seg.text)
        ]
        return {
            "overlong_english": self._overlong_english_issues(english_segments),
            "structural_english_overflow": self._structural_english_overflow_issues(english_segments),
            "bad_cuts": self._bad_cut_issues(english_segments),
            "translationese": self._translationese_issues(final_segments),
            "reading_speed_errors": self._reading_speed_issues(final_segments, "ERROR"),
            "reading_speed_warnings": self._reading_speed_issues(final_segments, "WARNING"),
            "duration_errors": self._subtitle_duration_issues(final_segments, "ERROR"),
            "duration_warnings": self._subtitle_duration_issues(final_segments, "WARNING"),
            "duplicate_chinese": self._duplicate_chinese_issues(final_segments),
            "asr_suspicious": self._asr_suspicious_issues(final_segments),
            "discourse_marker_orphans": list(getattr(self, "_discourse_marker_orphans", []) or []),
            "syntax_boundary_audit": self._syntax_boundary_audit_issues(english_segments),
            "chinese_semantic_group_warnings": self._chinese_semantic_group_audit_issues(final_segments, "WARNING"),
            "chinese_semantic_group_info": self._chinese_semantic_group_audit_issues(final_segments, "INFO"),
        }

    def _overlong_english_issues(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[Dict]:
        issues: List[Dict] = []
        hard_limit = max(int(self.max_english_words or 0), HARD_ENGLISH_WORD_LIMIT)
        for seg in segments:
            text = self._normalize_text(seg.text)
            word_count = self._word_count(text)
            if self._is_allowed_plus_discourse_overflow(text, word_count, hard_limit):
                continue
            if self._is_allowed_structural_english_overflow(seg, text, word_count, hard_limit):
                continue
            if word_count <= hard_limit:
                continue
            issues.append(
                {
                    "start": self._format_ms(seg.start_time),
                    "end": self._format_ms(seg.end_time),
                    "word_count": word_count,
                    "hard_limit": hard_limit,
                    "text": text,
                }
            )
        return issues

    def _bad_cut_issues(self, segments: Sequence[ASRDataSeg]) -> List[Dict]:
        issues: List[Dict] = []
        for previous, current in zip(segments, segments[1:]):
            previous_text = self._normalize_text(previous.text)
            current_text = self._normalize_text(current.text)
            if not previous_text or not current_text:
                continue
            previous_last = self._clean_boundary_token(previous_text.split()[-1])
            current_first = self._clean_boundary_token(current_text.split()[0])
            reasons = self._bad_cut_reasons(previous_last, current_first)
            reasons = [
                reason
                for reason in reasons
                if not self._boundary_has_audited_issue_exception(previous, current, reason)
            ]
            if not reasons:
                continue
            combined_words = self._word_count(f"{previous_text} {current_text}")
            if combined_words > max(self.max_english_words + 4, 18):
                continue
            issues.append(
                {
                    "start": self._format_ms(previous.start_time),
                    "end": self._format_ms(current.end_time),
                    "reason": "；".join(reasons),
                    "previous": previous_text,
                    "current": current_text,
                    "suggestion": "人工检查是否应合并，或把切点移动到更完整的意群边界。",
                }
            )
        return issues

    def _syntax_boundary_audit_issues(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[Dict]:
        return [
            record
            for record in self._scan_final_english_boundaries(segments)
            if record["classification"] != "allow"
        ]

    def _english_boundary_audit_payload(
        self,
        segments: Sequence[ASRDataSeg],
    ) -> Dict:
        records = self._scan_final_english_boundaries(segments)
        counts = {
            classification: sum(
                1 for record in records if record["classification"] == classification
            )
            for classification in ("hard", "review", "allow")
        }
        return {
            "schema_version": 1,
            "policy_version": "formal-boundary-evidence-v1",
            "word_ledger_hash": self._word_ledger_hash(),
            "summary": {
                "boundary_count": len(records),
                **counts,
            },
            "records": records,
        }

    def _scan_final_english_boundaries(
        self,
        segments: Sequence[ASRDataSeg],
    ) -> List[Dict]:
        """Classify every final English boundary without mutating the timeline.

        The pre-ID finalizer owns automatic repair. This whole-file pass proves
        that its remaining boundaries are either structurally sound, supported
        by timing/speaker evidence, or explicitly queued for human review.
        """
        items_by_id = {
            item.subtitle_id or f"S{index:04d}": item
            for index, item in enumerate(getattr(self, "_last_subtitle_items", []) or [], 1)
        }
        records: List[Dict] = []
        for index, (previous, current) in enumerate(zip(segments, segments[1:]), 1):
            previous_text = self._normalize_text(previous.text)
            current_text = self._normalize_text(current.text)
            if not previous_text or not current_text:
                continue
            left_id = self._segment_subtitle_id(previous, index)
            right_id = self._segment_subtitle_id(current, index + 1)
            left_item = items_by_id.get(left_id)
            right_item = items_by_id.get(right_id)
            word_continuity = bool(
                left_item
                and right_item
                and left_item.word_end is not None
                and right_item.word_start is not None
                and right_item.word_start == left_item.word_end + 1
            )
            speaker_change = bool(
                word_continuity and self._items_cross_speaker(left_item, right_item)
            )
            pause_ms: Optional[int] = None
            hard_issues: List[str] = []
            soft_issues: List[str] = []
            fallback_reasons: List[str] = []
            if word_continuity:
                evaluation = self._evaluate_stable_cut_boundary(
                    left_item.word_end,
                    right_item.word_start,
                    source_start=left_item.word_start,
                    source_end=right_item.word_end,
                )
                pause_ms = evaluation.get("pause_ms")
                hard_issues = list(evaluation.get("hard_issues") or [])
                soft_issues = list(dict.fromkeys(
                    list(evaluation.get("soft_issues") or [])
                    + self._auditable_atomic_boundary_issues(
                        left_item.word_end,
                        right_item.word_start,
                    )
                ))
            else:
                fallback_reasons = [
                    reason
                    for reason in self._syntax_boundary_reasons(previous_text, current_text)
                    if not self._boundary_has_audited_issue_exception(previous, current, reason)
                ]
                soft_issues = list(fallback_reasons)
                pause_ms = max(0, int(current.start_time) - int(previous.end_time))

            sentence_terminal = self._is_unambiguous_sentence_terminal(
                previous_text,
                current_text,
            )
            has_contrary_evidence = (
                speaker_change
                or sentence_terminal
                or (pause_ms is not None and pause_ms >= 450)
                or not word_continuity
            )
            rule_codes = list(dict.fromkeys(hard_issues + soft_issues))
            if hard_issues and not has_contrary_evidence:
                classification = "hard"
                confidence = "high"
                confidence_score = 0.95
                recommended_action = "pre_id_auto_repair_required"
            elif rule_codes:
                classification = "review"
                confidence = "medium"
                confidence_score = 0.62 if has_contrary_evidence else 0.72
                recommended_action = "manual_review"
            else:
                classification = "allow"
                confidence = "low"
                confidence_score = 0.2
                recommended_action = "keep"

            previous_last = self._clean_boundary_token(previous_text.split()[-1])
            current_first = self._clean_boundary_token(current_text.split()[0])
            legacy_reasons = self._bad_cut_reasons(previous_last, current_first)
            records.append(
                {
                    "index": index,
                    "left_subtitle_id": left_id,
                    "right_subtitle_id": right_id,
                    "classification": classification,
                    "recommended_action": recommended_action,
                    "reason": "; ".join(rule_codes) or "boundary supported by context",
                    "rule_codes": rule_codes,
                    "confidence": confidence,
                    "confidence_score": confidence_score,
                    "evidence": {
                        "word_continuity": word_continuity,
                        "word_boundary": (
                            [left_item.word_end, right_item.word_start]
                            if word_continuity else []
                        ),
                        "pause_ms": pause_ms,
                        "speaker_change": speaker_change,
                        "sentence_terminal": sentence_terminal,
                        "left_last": previous_last,
                        "right_first": current_first,
                        "fallback_text_only": bool(fallback_reasons),
                    },
                    "duplicates_legacy_bad_cut": bool(legacy_reasons),
                    "legacy_rule_codes": legacy_reasons,
                    "start": self._format_ms(previous.start_time),
                    "end": self._format_ms(current.end_time),
                    "previous": previous_text,
                    "current": current_text,
                    "previous_english": previous_text,
                    "current_english": current_text,
                    "boundary": f"{previous_text} | {current_text}",
                }
            )
        return records

    def _syntax_boundary_reasons(self, previous_text: str, current_text: str) -> List[str]:
        if self._is_safe_independent_boundary(previous_text, current_text):
            return []
        previous_tokens = self._word_tokens(previous_text)
        current_tokens = self._word_tokens(current_text)
        if not previous_tokens or not current_tokens:
            return []
        prev = previous_tokens[-1]
        cur = current_tokens[0]
        nxt = current_tokens[1] if len(current_tokens) > 1 else ""
        prev2 = previous_tokens[-2] if len(previous_tokens) > 1 else ""
        reasons: List[str] = []
        if self._is_abbreviation_name_boundary(previous_text, current_text):
            reasons.append("abbreviation_name_split")
        if self._is_protected_named_phrase_split(prev, cur):
            reasons.append("protected_named_phrase_split")
        if self._is_protected_phrasal_boundary(prev, cur):
            reasons.append("protected_phrasal_boundary_split")

        prepositions = {
            "into", "of", "for", "with", "without", "in", "on", "at", "by",
            "from", "to", "about", "around", "through", "over", "under",
            "between", "among", "against", "within", "across",
        }
        determiners = {"the", "a", "an", "this", "that", "these", "those", "our", "their", "its"}
        particles = {"down", "up", "out", "off", "in", "on", "away", "back", "over"}
        be_aux = {"am", "is", "are", "was", "were", "be", "been", "being", "we're", "they're", "it's", "that's"}
        auxiliaries = be_aux | {"can", "could", "will", "would", "should", "may", "might", "must", "do", "does", "did", "have", "has", "had"}
        object_verbs = {
            "force", "forces", "forced", "alter", "alters", "altered", "show",
            "shows", "showed", "raise", "raises", "raised", "put", "puts",
            "make", "makes", "made", "give", "gives", "gave", "take", "takes",
            "took", "create", "creates", "created", "look", "looks", "looked",
        }
        adjectives = {
            "absolute", "extreme", "uncomfortable", "rapid", "massive", "structural",
            "financial", "corporate", "public", "private", "local", "global",
            "new", "old", "major", "regional", "economic", "entire", "empty",
            "really", "loaded", "dense", "chaotic", "secretive", "healthy",
            "strategic", "traditional", "high-tech", "mind-bending", "working",
            "motorized",
            "short-term", "long-term", "impenetrable", "physical", "personal",
        }
        common_nouns = {
            "air", "look", "edge", "atmosphere", "world", "question", "solution",
            "solutions", "building", "government", "market", "markets", "policy",
            "data", "source", "sources", "scooter", "traffic", "pitch",
            "funds", "memory", "monopolies", "standards", "trainers",
            "industry", "miracle", "slowdown", "art",
        }

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
        if prev in {"look", "looks", "looked"} and cur == "at":
            reasons.append("verb_preposition_split")
        if prev in adjectives and (cur in adjectives or cur in common_nouns):
            reasons.append("modifier_head_split")
        if prev2 in be_aux and prev.endswith("ing") and cur in particles:
            reasons.append("verb_particle_split")
        if cur in {"are", "is", "was", "were"} and self._previous_looks_like_subject(previous_text):
            reasons.append("subject_predicate_split")
        if prev.endswith("'s") or prev.endswith("s'"):
            reasons.append("possessive_head_split")

        return list(dict.fromkeys(reasons))

    def _is_safe_independent_boundary(self, previous_text: str, current_text: str) -> bool:
        previous = previous_text.strip()
        current = current_text.strip()
        if not previous or not current:
            return True
        if self._is_abbreviation_name_boundary(previous, current):
            return False
        previous_words = self._word_tokens(previous)
        current_words = self._word_tokens(current)
        normalized_current = re.sub(r"[^a-z'\s]", " ", current.lower()).strip()
        normalized_current = re.sub(r"\s+", " ", normalized_current)
        if re.search(r"[.!?]\s*$", previous):
            if normalized_current.startswith(("but ", "wow", "what do you mean", "well ")):
                return True
        if re.search(r"[.!?]\s*$", previous):
            if len(previous_words) <= 5 or len(current_words) <= 3:
                return True
        normalized_previous = re.sub(r"[^a-z'\s]", " ", previous.lower()).strip()
        short_responses = {
            "right", "yeah", "yes", "no", "exactly", "precisely", "okay",
            "ok", "absolutely", "what question", "how so", "why",
        }
        return normalized_previous in short_responses or normalized_current in short_responses

    @staticmethod
    def _is_abbreviation_name_boundary(previous_text: str, current_text: str) -> bool:
        previous = (previous_text or "").strip()
        current = (current_text or "").strip()
        if not previous or not current:
            return False
        return bool(
            re.search(r"\b(?:St|Mt|Mr|Mrs|Ms|Dr|Prof|Jr|Sr)\.$", previous)
            and re.match(r"[A-Z][A-Za-z'-]{2,}\b", current)
        )

    @staticmethod
    def _previous_looks_like_subject(text: str) -> bool:
        words = re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", text or "")
        if not words:
            return False
        tail = words[-3:]
        if len(tail) >= 2 and all(word[:1].isupper() for word in tail[-2:]):
            return True
        return tail[-1].lower() in {"we", "they", "you", "i", "he", "she", "it"}

    @classmethod
    def _bad_cut_reasons(cls, previous_last: str, current_first: str) -> List[str]:
        reasons: List[str] = []
        if cls._is_protected_named_phrase_split(previous_last, current_first):
            reasons.append("固定专名被切开")
        if cls._is_protected_phrasal_boundary(previous_last, current_first):
            reasons.append("固定短语被切开")
        protected_pairs = {
            ("corporate", "division"): "固定名词短语被切开",
            ("because", "that"): "because that 从句被切开",
            ("audits", "of"): "名词和 of 短语被切开",
            ("audit", "of"): "名词和 of 短语被切开",
            ("road", "anymore"): "固定表达被切开",
            ("sense", "of"): "sense of 结构被切开",
            ("side", "of"): "side of 结构被切开",
            ("look", "at"): "动词短语 look at 被切开",
            ("defined", "by"): "defined by 结构被切开",
            ("rely", "on"): "动词短语 rely on 被切开",
        }
        if (previous_last, current_first) in protected_pairs:
            reasons.append(protected_pairs[(previous_last, current_first)])

        bad_end = {
            "a",
            "an",
            "the",
            "to",
            "of",
            "in",
            "on",
            "at",
            "by",
            "from",
            "with",
            "without",
            "for",
            "about",
            "around",
            "because",
            "but",
            "and",
            "or",
            "so",
            "that",
            "which",
            "who",
            "where",
            "when",
            "whether",
            "are",
            "is",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "having",
            "do",
            "does",
            "did",
            "just",
            "even",
            "very",
            "really",
            "corporate",
            "massive",
            "painful",
            "structural",
            "financial",
            "municipal",
            "public",
            "private",
            "local",
            "new",
            "old",
            "major",
            "regional",
            "economic",
        }
        bad_start = {
            "of",
            "for",
            "with",
            "without",
            "in",
            "on",
            "at",
            "by",
            "from",
            "to",
            "about",
            "around",
            "that",
            "which",
            "who",
            "anymore",
            "though",
            "too",
            "either",
            "also",
            "instead",
        }
        if previous_last in bad_end:
            reasons.append("上一条结尾不适合作为字幕终点")
        if current_first in bad_start:
            reasons.append("下一条开头不适合作为字幕起点")
        return reasons

    def _translationese_issues(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[Dict]:
        patterns = [
            (re.compile(r"深度挖掘"), "deep dive 常被直译，可考虑改为“本期节目/这一期/深度解读”"),
            (re.compile(r"市政府的金库|市政金库"), "municipal coffers 建议译为“市财政/地方财政”"),
            (re.compile(r"实体体现|具体的、实体的体现"), "manifestation 直译偏硬，可考虑“具体呈现/看得见的变化”"),
            (re.compile(r"我们的任务是审视"), "our mission is to examine 偏机器翻译，可改为“这一期我们要看的是”"),
            (re.compile(r"由.*定义"), "defined by 结构直译偏硬，可考虑按中文语序重写"),
        ]
        issues: List[Dict] = []
        for seg in segments:
            translated = self._normalize_text(seg.translated_text)
            if not translated:
                continue
            for pattern, reason in patterns:
                if not pattern.search(translated):
                    continue
                issues.append(
                    {
                        "start": self._format_ms(seg.start_time),
                        "end": self._format_ms(seg.end_time),
                        "reason": reason,
                        "original": self._normalize_text(seg.text),
                        "translated": translated,
                    }
                )
                break
        return issues

    def _chinese_semantic_group_audit_issues(
        self, segments: Sequence[ASRDataSeg], level: str = "WARNING"
    ) -> List[Dict]:
        issues: List[Dict] = []
        mapping_issues = self._semantic_audit_mapping_issues(segments)
        if level == "WARNING":
            issues.extend(mapping_issues)
        for group_index, (start, end) in enumerate(self._semantic_segment_groups(segments), 1):
            group_segments = list(segments[start:end])
            if not group_segments:
                continue
            english = self._normalize_text(" ".join(seg.text for seg in group_segments))
            chinese_parts = [self._normalize_text(seg.translated_text) for seg in group_segments]
            chinese = self._normalize_text("".join(chinese_parts))
            if not english or not chinese:
                continue
            subtitle_ids = [
                self._segment_subtitle_id(seg, start + offset + 1)
                for offset, seg in enumerate(group_segments)
            ]
            mapping = self._semantic_audit_context_for_group(english, subtitle_ids)
            mapping_valid = bool(mapping.get("mapping_valid"))
            full_translation = str(mapping.get("full_translation") or "")
            findings = self._chinese_group_quality_findings(
                english,
                chinese,
                chinese_parts,
                full_translation=full_translation,
                mapping_valid=mapping_valid,
            )
            if not findings:
                continue
            high_confidence = self._is_high_confidence_chinese_group_issue(findings)
            if level == "WARNING" and not high_confidence:
                continue
            if level == "INFO" and high_confidence:
                continue
            rule_codes = [finding["code"] for finding in findings]
            confidence_score = max(float(finding.get("confidence_score", 0.0)) for finding in findings)
            issues.append(
                {
                    "group_index": group_index,
                    "semantic_group_id": mapping.get("semantic_group_id") or "",
                    "subtitle_ids": subtitle_ids,
                    "start_index": start + 1,
                    "end_index": end,
                    "start": self._format_ms(group_segments[0].start_time),
                    "end": self._format_ms(group_segments[-1].end_time),
                    "reason": "; ".join(rule_codes),
                    "rule_codes": rule_codes,
                    "findings": findings,
                    "confidence": "high" if high_confidence else "low",
                    "confidence_score": round(confidence_score, 2),
                    "suggest_llm_reallocation": high_confidence,
                    "mapping_valid": mapping_valid,
                    "english": english,
                    "chinese": chinese,
                    "full_translation": full_translation,
                    "parts": chinese_parts,
                }
            )
        return issues

    def _semantic_segment_groups(
        self, segments: Sequence[ASRDataSeg], max_group_size: int = 4
    ) -> List[tuple[int, int]]:
        groups: List[tuple[int, int]] = []
        start = 0
        for index, seg in enumerate(segments):
            text = self._normalize_text(seg.text)
            count = index - start + 1
            if count >= max_group_size or re.search(r"[.!?]\s*$", text):
                groups.append((start, index + 1))
                start = index + 1
        if start < len(segments):
            groups.append((start, len(segments)))
        return groups

    def _semantic_group_audit_contexts(
        self, groups: Sequence[Dict], full_translations: Dict[int, str]
    ) -> Dict[str, Dict]:
        contexts: Dict[str, Dict] = {}
        subtitle_id_to_group_id: Dict[str, str] = {}
        seen_ids: set[int] = set()
        for group in groups:
            group_id = int(group.get("id") or 0)
            english = self._normalize_text(" ".join(item.original for item in group.get("items", [])))
            signature = self._semantic_audit_signature(english)
            expected_ids = self._group_expected_subtitle_ids(group)
            if not group_id or not signature or group_id in seen_ids:
                continue
            seen_ids.add(group_id)
            semantic_group_id = f"G{group_id:04d}"
            contexts[semantic_group_id] = {
                "semantic_group_id": semantic_group_id,
                "group_id": group_id,
                "full_english": english,
                "full_english_signature": signature,
                "expected_subtitle_ids": expected_ids,
                "full_translation": full_translations.get(group_id, ""),
                "mapping_valid": bool(full_translations.get(group_id)),
            }
            for subtitle_id in expected_ids:
                if subtitle_id in subtitle_id_to_group_id:
                    subtitle_id_to_group_id[subtitle_id] = ""
                else:
                    subtitle_id_to_group_id[subtitle_id] = semantic_group_id
        self._last_semantic_group_id_by_subtitle_id = {
            subtitle_id: semantic_group_id
            for subtitle_id, semantic_group_id in subtitle_id_to_group_id.items()
            if semantic_group_id
        }
        return contexts

    def _semantic_audit_context_for_english(self, english: str) -> Dict:
        signature = self._semantic_audit_signature(english)
        matches = [
            context
            for context in (getattr(self, "_last_semantic_group_audit_contexts", {}) or {}).values()
            if context.get("full_english_signature") == signature
        ]
        if len(matches) != 1:
            return {"mapping_valid": False}
        return dict(matches[0])

    def _semantic_audit_context_for_group(
        self, english: str, subtitle_ids: Sequence[str]
    ) -> Dict:
        contexts = getattr(self, "_last_semantic_group_audit_contexts", {}) or {}
        if not contexts:
            return {"mapping_valid": False}
        subtitle_ids = [str(subtitle_id) for subtitle_id in subtitle_ids if subtitle_id]
        if not subtitle_ids:
            return {"mapping_valid": False}
        id_map = getattr(self, "_last_semantic_group_id_by_subtitle_id", {}) or {}
        candidate_ids = [id_map.get(subtitle_id, "") for subtitle_id in subtitle_ids]
        unique_ids = {candidate_id for candidate_id in candidate_ids if candidate_id}
        if len(candidate_ids) != len(subtitle_ids) or len(unique_ids) != 1:
            return {
                "mapping_valid": False,
                "mapping_failure_reason": "subtitle_id_set_does_not_map_to_unique_semantic_group",
            }
        semantic_group_id = next(iter(unique_ids))
        context = contexts.get(semantic_group_id)
        if not context:
            return {
                "mapping_valid": False,
                "semantic_group_id": semantic_group_id,
                "mapping_failure_reason": "semantic_group_id_not_found",
            }
        signature = self._semantic_audit_signature(english)
        expected_ids = list(context.get("expected_subtitle_ids") or [])
        if (
            str(context.get("semantic_group_id") or "") != semantic_group_id
            or expected_ids != list(subtitle_ids)
            or str(context.get("full_english_signature") or "") != signature
        ):
            return {
                "mapping_valid": False,
                "semantic_group_id": semantic_group_id,
                "expected_subtitle_ids": expected_ids,
                "returned_subtitle_ids": list(subtitle_ids),
                "mapping_failure_reason": "semantic_group_identity_mismatch",
            }
        mapped = dict(context)
        mapped["mapping_valid"] = bool(context.get("full_translation"))
        return mapped

    def _semantic_audit_mapping_issues(self, segments: Sequence[ASRDataSeg]) -> List[Dict]:
        contexts = getattr(self, "_last_semantic_group_audit_contexts", {}) or {}
        if not contexts:
            return []
        issues: List[Dict] = []
        seen_mapped_ids: set[str] = set()
        for _, (start, end) in enumerate(self._semantic_segment_groups(segments), 1):
            english = self._normalize_text(" ".join(seg.text for seg in segments[start:end]))
            subtitle_ids = [
                self._segment_subtitle_id(seg, start + offset + 1)
                for offset, seg in enumerate(segments[start:end])
            ]
            if not self._semantic_audit_signature(english):
                continue
            mapping = self._semantic_audit_context_for_group(english, subtitle_ids)
            semantic_group_id = str(mapping.get("semantic_group_id") or "")
            if mapping.get("mapping_valid") and semantic_group_id:
                if semantic_group_id in seen_mapped_ids:
                    issues.append(
                        {
                            "reason": "duplicate_reconstructed_semantic_group_id",
                            "rule_codes": ["audit_mapping_invalid"],
                            "semantic_group_id": semantic_group_id,
                            "subtitle_ids": subtitle_ids,
                            "mapping_valid": False,
                            "english": english,
                        }
                    )
                seen_mapped_ids.add(semantic_group_id)
                continue
            if not mapping.get("mapping_valid"):
                issues.append(
                    {
                        "reason": mapping.get("mapping_failure_reason") or "semantic_group_mapping_invalid",
                        "rule_codes": ["audit_mapping_invalid"],
                        "semantic_group_id": semantic_group_id,
                        "subtitle_ids": subtitle_ids,
                        "mapping_valid": False,
                        "english": english,
                    }
                )
        return issues

    @staticmethod
    def _semantic_audit_signature(text: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
        return re.sub(r"\s+", " ", normalized)

    def _chinese_group_quality_reasons(
        self, english: str, chinese: str, parts: Sequence[str]
    ) -> List[str]:
        return [finding["code"] for finding in self._chinese_group_quality_findings(english, chinese, parts)]

    def _chinese_group_quality_findings(
        self,
        english: str,
        chinese: str,
        parts: Sequence[str],
        full_translation: str = "",
        mapping_valid: bool = False,
    ) -> List[Dict]:
        findings: List[Dict] = []
        reasons: List[str] = []
        if self._is_simple_short_response(english, chinese):
            return findings
        single_complete_cue = len(parts) == 1 and bool(
            re.search(r"[。！？.!?]$", str(parts[0] or "").strip())
        )
        if mapping_valid and not single_complete_cue and self._is_incomplete_chinese_group(chinese):
            findings.append(
                {
                    "code": "missing_predicate",
                    "message": "整组中文疑似缺少明确谓语或完整判断",
                    "confidence_score": 0.62,
                }
            )
        if mapping_valid and full_translation and self._has_core_semantic_loss(
            chinese, full_translation, english
        ):
            findings.append(
                {
                    "code": "semantic_loss",
                    "message": "相较英文语义组疑似丢失核心动作或逻辑",
                    "confidence_score": 0.9,
                }
            )
        if mapping_valid and not single_complete_cue:
            bad_fragments = [
                index + 1 for index, part in enumerate(parts) if self._is_bad_chinese_fragment(part)
            ]
            if bad_fragments:
                findings.append(
                    {
                        "code": "dangling_preposition",
                        "message": f"第 {bad_fragments} 条中文疑似悬空片段",
                        "confidence_score": 0.72,
                        "segment_offsets": bad_fragments,
                    }
                )
        if self._looks_like_english_order_chinese(chinese):
            findings.append(
                {
                    "code": "english_word_order",
                    "message": "整组中文疑似保留英文语序或翻译腔结构",
                    "confidence_score": 0.66,
                }
            )
        if self._has_chinese_modifier_break(parts):
            findings.append(
                {
                    "code": "modifier_head_split",
                    "message": "相邻中文字幕疑似切开修饰语、条件结构或中心词",
                    "confidence_score": 0.7,
                }
            )
        if self._has_punctuation_discontinuity(parts):
            findings.append(
                {
                    "code": "punctuation_discontinuity",
                    "message": "中文标点显示句子可能未完成",
                    "confidence_score": 0.58,
                }
            )
        return findings

    @staticmethod
    def _is_high_confidence_chinese_group_issue(findings: Sequence[Dict]) -> bool:
        codes = {str(finding.get("code", "")) for finding in findings}
        if "semantic_loss" in codes:
            return True
        if "missing_predicate" in codes and (
            "dangling_preposition" in codes
            or "modifier_head_split" in codes
            or "punctuation_discontinuity" in codes
        ):
            return True
        if "dangling_preposition" in codes and "punctuation_discontinuity" in codes:
            return True
        return len(codes) >= 2 and any(
            code in codes
            for code in {
                "missing_predicate",
                "dangling_preposition",
                "modifier_head_split",
                "english_word_order",
            }
        )

    @staticmethod
    def _has_punctuation_discontinuity(parts: Sequence[str]) -> bool:
        if len(parts) < 2:
            return False
        for left, right in zip(parts, parts[1:]):
            left_clean = (left or "").strip()
            right_clean = (right or "").strip()
            if not left_clean or not right_clean:
                continue
            if re.search(r"[，、：；]$", left_clean) and re.match(r"^[。！？；，、]", right_clean):
                return True
            if left_clean.endswith(("如果", "因为", "对于", "关于", "在")):
                return True
        return False

    @staticmethod
    def _looks_like_english_order_chinese(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        patterns = [
            r"\u88ab.+\u901a\u8fc7",
            r"\u7531.+\u5b9a\u4e49",
            r"\u662f.+\u7684.+\u95ee\u9898",
            r"\u5b83.+\u662f.+\u7684",
            r"\u5982\u679c\u4f60\u8ffd\u8e2a.+\u7c7b\u522b\u5728\d",
        ]
        return any(re.search(pattern, normalized) for pattern in patterns)

    @staticmethod
    def _has_chinese_modifier_break(parts: Sequence[str]) -> bool:
        if len(parts) < 2:
            return False
        dangling_suffixes = (
            "\u7684",  # 的
            "\u4e4b",  # 之
            "\u5bf9\u4e8e",  # 对于
            "\u5173\u4e8e",  # 关于
            "\u5982\u679c",  # 如果
            "\u56e0\u4e3a",  # 因为
            "\u5728",  # 在
        )
        for left, right in zip(parts, parts[1:]):
            left_clean = re.sub(r"[，。！？；：、,.!?;:]+$", "", left or "")
            right_clean = right or ""
            if left_clean.endswith(dangling_suffixes):
                return True
            if left_clean.endswith("\u65f6") and not re.search(r"[\u60f3\u770b\u8bf4\u95ee\u5f15\u53d1\u5bfc\u81f4]", right_clean):
                return True
        return False

    def _subtitle_duration_issues(
        self, segments: Sequence[ASRDataSeg], level: str
    ) -> List[Dict]:
        issues: List[Dict] = []
        for index, seg in enumerate(segments, 1):
            duration_ms = max(0, int(seg.end_time) - int(seg.start_time))
            if duration_ms <= 0:
                continue
            original = self._normalize_text(seg.text)
            translated = self._normalize_text(seg.translated_text)
            simple_response = self._is_simple_short_response(original, translated)
            text_load = self._word_count(original) + len(re.findall(r"[\u4e00-\u9fff]", translated))
            is_invalid = duration_ms < SUBTITLE_DURATION_INVALID_MS
            is_too_short_for_load = duration_ms < SUBTITLE_DURATION_ERROR_MS and not simple_response and text_load > 4
            is_high_load_short = self._is_high_load_short_subtitle(seg)
            is_error = is_invalid or is_too_short_for_load
            is_warning = (
                not is_error
                and (
                    is_high_load_short
                    or
                    duration_ms < SUBTITLE_DURATION_ERROR_MS
                    or duration_ms < SUBTITLE_DURATION_WARNING_MS
                )
            )
            if level == "ERROR" and not is_error:
                continue
            if level == "WARNING" and not is_warning:
                continue
            threshold = (
                SUBTITLE_DURATION_INVALID_MS
                if is_invalid
                else (
                    SUBTITLE_DURATION_ERROR_MS
                    if is_error
                    else (self._target_high_load_duration_ms(seg) if is_high_load_short else SUBTITLE_DURATION_WARNING_MS)
                )
            )
            code = "subtitle_duration_invalid" if is_error else "subtitle_duration_too_short"
            reason = f"字幕显示时间 {duration_ms}ms，低于 {threshold}ms 阈值"
            if is_high_load_short and not is_error:
                code = "subtitle_high_load_too_short"
                reason = f"字幕显示时间 {duration_ms}ms，但文本负载较高，建议至少 {threshold}ms"
            issues.append(
                {
                    "code": code,
                    "level": "ERROR" if is_error else "WARNING",
                    "index": index,
                    "start": self._format_ms(seg.start_time),
                    "end": self._format_ms(seg.end_time),
                    "duration_ms": duration_ms,
                    "threshold_ms": threshold,
                    "reason": reason,
                    "simple_response": simple_response,
                    "text_load": text_load,
                    "original": original,
                    "translated": translated,
                }
            )
        return issues

    @staticmethod
    def _is_simple_short_response(original: str, translated: str = "") -> bool:
        original_norm = re.sub(r"[^a-z'\s]", " ", (original or "").lower()).strip()
        original_norm = re.sub(r"\s+", " ", original_norm)
        translated_norm = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", translated or "")
        short_en = {
            "right",
            "yeah",
            "oh yeah",
            "yes",
            "no",
            "okay",
            "ok",
            "really",
            "exactly",
            "sure",
            "good question",
            "in a way yeah",
            "unbelievable",
            "why",
            "where",
            "how",
            "what",
        }
        short_zh = {
            "\u6ca1\u9519",
            "\u5bf9",
            "\u662f\u7684",
            "\u95ee\u5f97\u597d",
            "\u54e6\u662f\u7684",
            "\u5728\u67d0\u79cd\u7a0b\u5ea6\u4e0a\u662f\u7684",
            "\u96be\u4ee5\u7f6e\u4fe1",
            "\u8fd8\u6709\u66f4\u5389\u5bb3\u7684",
            "\u771f\u7684\u5417",
            "\u771f\u7684",
            "\u597d\u7684",
            "\u4e3a\u4ec0\u4e48",
            "\u5728\u54ea\u91cc",
            "\u4ec0\u4e48",
        }
        if original_norm in short_en:
            return True
        return bool(translated_norm and translated_norm in short_zh)

    def _reading_speed_issues(
        self, segments: Sequence[ASRDataSeg], level: str
    ) -> List[Dict]:
        issues: List[Dict] = []
        for index, seg in enumerate(segments, 1):
            duration_ms = max(1, int(seg.end_time) - int(seg.start_time))
            if duration_ms < SUBTITLE_DURATION_INVALID_MS:
                continue
            duration_sec = duration_ms / 1000.0
            original = self._normalize_text(seg.text)
            translated = self._normalize_text(seg.translated_text)

            zh_chars = len(re.findall(r"[\u4e00-\u9fff]", translated))
            if zh_chars:
                cps = zh_chars / duration_sec
                severe_zh_speed = (
                    cps > CHINESE_CPS_ERROR
                    and duration_ms >= 1200
                    and zh_chars >= 12
                )
                if level == "ERROR" and severe_zh_speed:
                    issues.append(
                        {
                            "level": "ERROR",
                            "index": index,
                            "start": self._format_ms(seg.start_time),
                            "end": self._format_ms(seg.end_time),
                            "duration_ms": duration_ms,
                            "zh_chars": zh_chars,
                            "cps": round(cps, 2),
                            "reason": f"中文字幕阅读速度 {cps:.2f} 字/秒，超过 {CHINESE_CPS_ERROR:.1f} 字/秒硬上限",
                            "original": original,
                            "translated": translated,
                        }
                    )
                elif (
                    level == "WARNING"
                    and cps > CHINESE_CPS_WARNING
                    and not severe_zh_speed
                ):
                    issues.append(
                        {
                            "level": "WARNING",
                            "index": index,
                            "start": self._format_ms(seg.start_time),
                            "end": self._format_ms(seg.end_time),
                            "duration_ms": duration_ms,
                            "zh_chars": zh_chars,
                            "cps": round(cps, 2),
                            "reason": f"中文字幕阅读速度 {cps:.2f} 字/秒，超过 {CHINESE_CPS_WARNING:.1f} 字/秒建议值",
                            "original": original,
                            "translated": translated,
                        }
                    )

            if level != "WARNING" or not original:
                continue
            word_count = self._word_count(original)
            if not word_count:
                continue
            wps = word_count / duration_sec
            if wps > ENGLISH_WPS_WARNING:
                issues.append(
                    {
                        "level": "WARNING",
                        "index": index,
                        "start": self._format_ms(seg.start_time),
                        "end": self._format_ms(seg.end_time),
                        "duration_ms": duration_ms,
                        "word_count": word_count,
                        "wps": round(wps, 2),
                        "reason": f"英文字幕阅读速度 {wps:.2f} 词/秒，可能偏快",
                        "original": original,
                        "translated": translated,
                    }
                )
        return issues

    def _duplicate_chinese_issues(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[Dict]:
        issues: List[Dict] = []
        previous_text = ""
        previous_index = 0
        for index, seg in enumerate(segments, 1):
            current = self._normalize_chinese_for_compare(seg.translated_text)
            if not current:
                continue
            if previous_text:
                similarity = SequenceMatcher(None, previous_text, current).ratio()
                if (
                    current == previous_text
                    or (
                        min(len(current), len(previous_text)) >= 6
                        and similarity >= ADJACENT_ZH_DUPLICATE_SIMILARITY
                    )
                ):
                    issues.append(
                        {
                            "previous_index": previous_index,
                            "current_index": index,
                            "similarity": round(similarity, 3),
                            "previous": previous_text,
                            "current": current,
                        }
                    )
            previous_text = current
            previous_index = index
        return issues

    def _asr_suspicious_issues(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[Dict]:
        issues: List[Dict] = []
        for index, seg in enumerate(segments, 1):
            text = self._normalize_text(seg.text)
            if not text:
                continue
            lower = text.lower()
            tokens = [
                self._clean_boundary_token(token)
                for token in re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)?", text)
            ]
            if len(tokens) == 1 and tokens[0] in {"uh", "um", "hmm", "mm"}:
                issues.append(
                    {
                        "index": index,
                        "start": self._format_ms(seg.start_time),
                        "end": self._format_ms(seg.end_time),
                        "reason": "疑似只包含无意义语气词，建议人工确认 ASR 是否漏识别周围语音",
                        "text": text,
                    }
                )
            if re.search(r"\b([A-Za-z]+)\s+\1\b", text, re.IGNORECASE):
                issues.append(
                    {
                        "index": index,
                        "start": self._format_ms(seg.start_time),
                        "end": self._format_ms(seg.end_time),
                        "reason": "英文中存在相邻重复词，可能是 ASR 或切分异常",
                        "text": text,
                    }
                )
            for pattern, rule_code, reason, confidence in (
                (
                    r"\btotal off guard\b",
                    "asr_ungrammatical_collocation",
                    "疑似固定搭配识别错误：常见表达应接近 caught me totally off guard",
                    "high",
                ),
                (
                    r"\bseeds?\s+away\s+the\s+mirror\b",
                    "asr_semantic_nonsense",
                    "疑似语义不成立的英文片段，建议回听确认",
                    "high",
                ),
                (
                    r"\bpollution control trigger\b",
                    "asr_subject_verb_agreement",
                    "疑似单复数或谓语形态异常：control trigger",
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
                    r"\belectric\s+cess\b",
                    "asr_semantic_nonsense",
                    "疑似ASR把 electric fence 识别成不成立的表达",
                    "high",
                ),
                (
                    r"\b[a-z][a-z]{1,8}s?\s+surname\b",
                    "asr_name_suspicious",
                    "疑似专名所有格识别异常：surname 前的人名建议结合文章上下文回听确认",
                    "medium",
                ),
                (
                    r"\bamerica\s+respondents\b",
                    "asr_adjective_form_suspicious",
                    "疑似国家名形容词形式错误：常见表达应接近 American respondents",
                    "medium",
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
                    "时间状语附近出现可疑动词原形，建议回听确认",
                    "medium",
                ),
            ):
                if not re.search(pattern, lower):
                    continue
                issues.append(
                    {
                        "index": index,
                        "subtitle_id": f"S{index:04d}",
                        "start": self._format_ms(seg.start_time),
                        "end": self._format_ms(seg.end_time),
                        "time_range": f"{self._format_ms(seg.start_time)} --> {self._format_ms(seg.end_time)}",
                        "rule_code": rule_code,
                        "confidence": confidence,
                        "reason": reason,
                        "suspicious_text": text,
                        "recommended_review_window": {
                            "start": self._format_ms(max(0, int(seg.start_time) - 1500)),
                            "end": self._format_ms(int(seg.end_time) + 1500),
                        },
                        "text": text,
                    }
                )
        issues.extend(self._capitalized_variant_issues(segments))
        return issues

    def _capitalized_variant_issues(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[Dict]:
        buckets: Dict[str, Dict[str, List[int]]] = {}
        segment_by_index = {index: seg for index, seg in enumerate(segments, 1)}
        for index, seg in enumerate(segments, 1):
            text = self._normalize_text(seg.text)
            words = re.findall(r"\b[A-Z][A-Za-z]{4,}\b", text)
            for word in words:
                key = word[:4].lower()
                buckets.setdefault(key, {}).setdefault(word, []).append(index)

        issues: List[Dict] = []
        for variants in buckets.values():
            if len(variants) < 2:
                continue
            names = sorted(variants)
            similar_pairs = []
            for i, left in enumerate(names):
                for right in names[i + 1 :]:
                    ratio = SequenceMatcher(None, left.lower(), right.lower()).ratio()
                    if self._is_expected_capitalized_variant_pair(left, right):
                        continue
                    if 0.62 <= ratio < 1.0:
                        similar_pairs.append((left, right, round(ratio, 3)))
            if not similar_pairs:
                continue
            indices = sorted({idx for name in names for idx in variants[name]})
            first_index = indices[0] if indices else 0
            first_seg = segment_by_index.get(first_index)
            if not first_seg:
                continue
            first_text = self._normalize_text(first_seg.text)
            issues.append(
                {
                    "index": first_index,
                    "subtitle_id": f"S{first_index:04d}",
                    "start": self._format_ms(first_seg.start_time),
                    "end": self._format_ms(first_seg.end_time),
                    "time_range": f"{self._format_ms(first_seg.start_time)} --> {self._format_ms(first_seg.end_time)}",
                    "suspicious_text": first_text,
                    "rule_code": "asr_capitalized_variant",
                    "confidence": "medium",
                    "evidence": "similar capitalized variants in nearby subtitles",
                    "reason": "同一批字幕中出现相近的大写词变体，可能是专名 ASR 漂移",
                    "variants": [
                        {"text": name, "indices": variants[name]} for name in names
                    ],
                    "pairs": similar_pairs,
                }
            )
        return issues

    @staticmethod
    def _is_expected_capitalized_variant_pair(left: str, right: str) -> bool:
        pair = tuple(sorted((left.lower(), right.lower())))
        return pair in {
            ("china", "chinese"),
            ("america", "american"),
            ("insta", "instead"),
        }

    @staticmethod
    def _normalize_chinese_for_compare(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text).strip()

    def _translation_gaps(self, final_segments: Sequence[ASRDataSeg]) -> List[Dict]:
        gaps: List[Dict] = []
        for seg in final_segments:
            original = self._normalize_text(seg.text)
            if not original or not re.search(r"[A-Za-z]", original):
                continue
            if (seg.translated_text or "").strip():
                continue
            gaps.append(
                {
                    "start": self._format_ms(max(0, seg.start_time)),
                    "end": self._format_ms(max(seg.end_time, seg.start_time)),
                    "text": original,
                }
            )
        return gaps

    @staticmethod
    def _covered_duration_ms(
        start_time: int,
        end_time: int,
        intervals: Sequence[tuple[int, int]],
    ) -> int:
        covered = 0
        cursor = start_time
        for interval_start, interval_end in intervals:
            if interval_end <= cursor:
                continue
            if interval_start >= end_time:
                break
            overlap_start = max(cursor, interval_start, start_time)
            overlap_end = min(end_time, interval_end)
            if overlap_end > overlap_start:
                covered += overlap_end - overlap_start
                cursor = overlap_end
                if cursor >= end_time:
                    break
        return covered

    @staticmethod
    def _uncovered_intervals_ms(
        start_time: int,
        end_time: int,
        intervals: Sequence[tuple[int, int]],
    ) -> List[tuple[int, int]]:
        gaps: List[tuple[int, int]] = []
        cursor = start_time
        for interval_start, interval_end in intervals:
            if interval_end <= cursor:
                continue
            if interval_start >= end_time:
                break
            if interval_start > cursor:
                gaps.append((cursor, min(interval_start, end_time)))
            cursor = max(cursor, min(interval_end, end_time))
            if cursor >= end_time:
                break
        if cursor < end_time:
            gaps.append((cursor, end_time))
        return gaps

    @staticmethod
    def _format_ms(ms: int) -> str:
        ms = max(0, int(ms))
        hours = ms // 3_600_000
        minutes = (ms % 3_600_000) // 60_000
        seconds = (ms % 60_000) // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"

    @staticmethod
    def _apply_display_timing_padding(
        segments: Sequence[ASRDataSeg],
        lead_in_ms: int = DISPLAY_LEAD_IN_MS,
        tail_padding_ms: int = DISPLAY_TAIL_PADDING_MS,
        min_gap_ms: int = DISPLAY_MIN_GAP_MS,
        min_duration_ms: int = DISPLAY_MIN_DURATION_MS,
        bridge_gap_ms: int = DISPLAY_BRIDGE_GAP_MS,
        short_bridge_gap_ms: int = DISPLAY_SHORT_BRIDGE_GAP_MS,
    ) -> List[ASRDataSeg]:
        if not segments:
            return []

        adjusted: List[ASRDataSeg] = []
        lead_count = 0
        tail_count = 0

        for index, seg in enumerate(segments):
            original_start = max(0, seg.start_time)
            original_end = max(seg.end_time, original_start + 1)
            previous_end = adjusted[-1].end_time if adjusted else None
            next_start = (
                max(0, segments[index + 1].start_time)
                if index + 1 < len(segments)
                else None
            )

            start_time = original_start
            wanted_start = max(0, original_start - lead_in_ms)
            if previous_end is None or wanted_start >= previous_end + min_gap_ms:
                start_time = wanted_start
                if start_time < original_start:
                    lead_count += 1

            end_time = original_end + tail_padding_ms
            if next_start is not None:
                end_time = min(end_time, next_start - min_gap_ms)
            if end_time < original_end:
                end_time = original_end
            if (
                next_start is not None
                and 0 < next_start - original_end <= bridge_gap_ms
            ):
                end_time = max(end_time, next_start - min_gap_ms)
            if (
                next_start is not None
                and original_end - original_start < min_duration_ms
                and 0 < next_start - original_end <= short_bridge_gap_ms
            ):
                end_time = max(end_time, next_start - min_gap_ms)
            target_end = start_time + min_duration_ms
            if end_time < target_end:
                max_end = next_start - min_gap_ms if next_start is not None else target_end
                end_time = min(target_end, max(end_time, max_end))
            if end_time - start_time < min_duration_ms:
                target_start = end_time - min_duration_ms
                min_start = previous_end + min_gap_ms if previous_end is not None else 0
                if target_start >= min_start and target_start <= start_time:
                    start_time = target_start
            if end_time <= start_time:
                end_time = start_time + 1
            if end_time > original_end:
                tail_count += 1

            adjusted.append(
                ScreenSubtitleEditor._copy_segment(
                    seg,
                    start_time=start_time,
                    end_time=end_time,
                )
            )

        logger.info(
            "Screen subtitle display timing padding: lead=%s tail=%s",
            lead_count,
            tail_count,
        )
        return adjusted

    def _chunk_segments(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[List[tuple[int, ASRDataSeg]]]:
        numbered = list(enumerate(segments, 1))
        return [
            numbered[i : i + self.batch_num]
            for i in range(0, len(numbered), self.batch_num)
        ]

    def _repair_global_segments(self, segments: List[ASRDataSeg]) -> List[ASRDataSeg]:
        repaired: List[ASRDataSeg] = []
        i = 0
        while i < len(segments):
            seg = segments[i]
            if getattr(seg, "subtitle_id", None):
                repaired.append(seg)
                i += 1
                continue
            structural_parts = self._split_structural_phrases(seg.text)
            if len(structural_parts) > 1:
                repaired.extend(self._segments_from_parts(seg, structural_parts))
                i += 1
                continue

            if (
                i + 1 < len(segments)
                and self._needs_following_preposition(seg.text)
                and re.match(
                    r"^(?:for|of|in|on|at|to|from|with|about|around)\b",
                    segments[i + 1].text,
                    flags=re.IGNORECASE,
                )
            ):
                combined_text = self._normalize_text(
                    f"{seg.text} {segments[i + 1].text}"
                )
                parts = self._split_required_prepositional_head(
                    combined_text, self.max_english_words
                )
                span = ASRDataSeg(
                    text=combined_text,
                    translated_text="",
                    start_time=seg.start_time,
                    end_time=segments[i + 1].end_time,
                )
                repaired.extend(self._segments_from_parts(span, parts))
                i += 2
                continue

            repaired.append(seg)
            i += 1
        return repaired

    def _quality_check_candidate_segments(
        self, segments: List[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        if any(getattr(seg, "subtitle_id", None) for seg in segments):
            return list(segments)
        result: List[ASRDataSeg] = []
        i = 0
        reviewed_count = 0
        max_reviews = 24
        while i < len(segments):
            if (
                i + 1 < len(segments)
                and reviewed_count < max_reviews
                and self._needs_quality_review(segments[i], segments[i + 1])
            ):
                replacement = self._review_quality_span(
                    segments[max(0, i - 1)] if i > 0 else None,
                    [segments[i], segments[i + 1]],
                    segments[i + 2] if i + 2 < len(segments) else None,
                )
                reviewed_count += 1
                if replacement:
                    result.extend(replacement)
                    i += 2
                    continue
            result.append(segments[i])
            i += 1
        return result

    def _needs_quality_review(self, current: ASRDataSeg, next_seg: ASRDataSeg) -> bool:
        current_text = self._normalize_text(current.text)
        next_text = self._normalize_text(next_seg.text)
        if not current_text or not next_text:
            return False
        if self._word_count(current_text) > self.max_english_words:
            return True
        if re.search(
            r"\b(?:has the potential|on par with,?|guarantee is that|access to|"
            r"connected to|get|began with|started with|the reality|a question|"
            r"the compute|these models|those models)\.?$",
            current_text,
            flags=re.IGNORECASE,
        ):
            return True
        if (
            re.match(
                r"^(?:to|for|of|as|which|that|who|where|when|while|because|and)\b",
                next_text,
                flags=re.IGNORECASE,
            )
            and self._word_count(current_text) >= 6
            and not re.search(r"[.!?]\s*$", current_text)
        ):
            return True
        return False

    def _review_quality_span(
        self,
        previous: Optional[ASRDataSeg],
        span: List[ASRDataSeg],
        next_seg: Optional[ASRDataSeg],
    ) -> List[ASRDataSeg]:
        originals = [seg.text for seg in span]
        prompt = (
            "You are checking English-learning video subtitles. "
            "Only fix awkward line breaks where a subtitle ends before the phrase is meaningful. "
            "Endings such as 'has the potential', 'on par with', or 'the guarantee is that' are usually awkward "
            "unless the following completion appears in the same subtitle. "
            "You may split or rebalance the provided target lines, but you must use exactly the same English words "
            "in the same order. Do not rewrite, remove, add, or paraphrase English. "
            f"Every returned English line must be {self.max_english_words} words or fewer. "
            "If the current cut is acceptable, return action keep. "
            "Return pure JSON only: "
            "{\"action\":\"keep\"} or {\"action\":\"replace\",\"items\":[\"line 1\",\"line 2\"]}."
        )
        payload = {
            "previous_context": previous.text if previous else "",
            "target_lines": originals,
            "next_context": next_seg.text if next_seg else "",
        }
        cache_key = self._cache_key("quality_check_candidates:" + prompt, [payload])
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=0.0,
            task="screen_subtitle_quality_check",
        )
        try:
            if cache_result:
                self._llm_cache_used = True
                data = json.loads(cache_result)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    temperature=0.0,
                    timeout=self.timeout,
                )
                data = json_repair.loads(response.choices[0].message.content)
                self.cache_manager.set_llm_result(
                    cache_key,
                    json.dumps(data, ensure_ascii=False),
                    self.model,
                    temperature=0.0,
                    task="screen_subtitle_quality_check",
                )
        except Exception as e:
            logger.warning("上屏字幕候选质检失败，保留原切点：%s", str(e))
            return []

        if not isinstance(data, dict) or data.get("action") != "replace":
            return []
        items = data.get("items")
        if not isinstance(items, list) or not 1 < len(items) <= 3:
            return []
        parts = [self._normalize_text(str(item)) for item in items if str(item).strip()]
        if len(parts) != len(items):
            return []
        if any(self._word_count(part) > self.max_english_words for part in parts):
            return []
        source_tokens = self._word_tokens(" ".join(originals))
        result_tokens = self._word_tokens(" ".join(parts))
        if source_tokens != result_tokens:
            return []

        translations = self._translate_split_parts(parts)
        start_time = span[0].start_time
        end_time = span[-1].end_time
        duration = max(end_time - start_time, len(parts))
        result: List[ASRDataSeg] = []
        for index, part in enumerate(parts):
            part_start = start_time + int(duration * index / len(parts))
            part_end = start_time + int(duration * (index + 1) / len(parts))
            result.append(
                ASRDataSeg(
                    text=part,
                    translated_text=(
                        translations[index] if index < len(translations) else ""
                    ),
                    start_time=part_start,
                    end_time=max(part_end, part_start + 300),
                )
            )
        return result

    def _repair_blocking_subtitle_issues(
        self,
        segments: Sequence[ASRDataSeg],
        semantic_groups: Optional[Sequence[Dict]] = None,
        subtitle_items: Optional[Sequence[ScreenSubtitleItem]] = None,
    ) -> List[ASRDataSeg]:
        # Stable-mode English is already frozen by this stage.  Chinese speed
        # repair happens once, after the final timing backend has completed.
        return self._repair_overlong_english_segments_local(segments)

    def _safe_auto_repair_segments(
        self,
        segments: Sequence[ASRDataSeg],
        semantic_groups: Optional[Sequence[Dict]] = None,
        subtitle_items: Optional[Sequence[ScreenSubtitleItem]] = None,
        stage: str = "unknown",
    ) -> List[ASRDataSeg]:
        if not getattr(self, "enable_safe_auto_repair", False):
            return list(segments)
        before = [self._copy_segment(seg) for seg in segments]
        self._record_safe_auto_repair_candidates(before, stage)
        before_guard = self._safe_auto_repair_guard_summary(before)
        repaired = [self._copy_segment(seg) for seg in segments]
        repaired = self._translate_missing_segments(repaired)
        repaired = self._align_segment_translation_punctuation(repaired)
        repaired = self._repair_exact_duplicate_chinese_segments(repaired)
        repaired = self._compress_fast_chinese_segments(
            repaired,
            semantic_groups=semantic_groups,
            subtitle_items=subtitle_items,
        )
        repaired = self._repair_high_confidence_chinese_candidates_with_llm(
            repaired,
            semantic_groups=semantic_groups,
            subtitle_items=subtitle_items,
            stage=stage,
        )
        after_guard = self._safe_auto_repair_guard_summary(repaired)
        if not self._safe_auto_repair_guard_passes(before_guard, after_guard):
            self._safe_auto_repair_log.append(
                {
                    "stage": stage,
                    "code": "safe_repair_guard_rejected",
                    "before": before_guard,
                    "after": after_guard,
                }
            )
            return before
        self._record_safe_auto_repair_diff(before, repaired, stage)
        return repaired

    def _repair_high_confidence_chinese_candidates_with_llm(
        self,
        segments: Sequence[ASRDataSeg],
        semantic_groups: Optional[Sequence[Dict]] = None,
        subtitle_items: Optional[Sequence[ScreenSubtitleItem]] = None,
        stage: str = "unknown",
    ) -> List[ASRDataSeg]:
        if stage != "after_final_time_alignment":
            return list(segments)
        if not semantic_groups or not subtitle_items:
            return list(segments)
        targets: List[tuple[int, ASRDataSeg]] = []
        seen_group_ids: set = set()
        for index, seg in enumerate(segments):
            chinese = self._normalize_text(seg.translated_text)
            if not chinese or not self._is_high_confidence_chinese_fragment_candidate(chinese):
                continue
            context = self._semantic_context_for_segment_index(
                index,
                segments,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            parts = context.get("parts") or []
            group_key = context.get("group_id")
            if not parts or len(parts) > 5 or group_key in seen_group_ids:
                continue
            seen_group_ids.add(group_key)
            targets.append((index, seg))
        if not targets:
            return list(segments)

        payload = []
        for index, seg in targets[:12]:
            item = self._chinese_compression_payload_item(
                index,
                seg,
                segments,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            item["candidate_reason"] = "high_confidence_chinese_fragment"
            item["repair_scope"] = "same_sense_group_chinese_only"
            payload.append(item)
        prompt = (
            "Repair only high-confidence Simplified Chinese subtitle fragments inside each provided sense_group.\n"
            "Do not change English, subtitle IDs, order, timing, or subtitle count.\n"
            "Use full_translation as the authority. English is only for locating meaning.\n"
            "Only rewrite Chinese for existing subtitle_id values in sense_group.parts when it makes the group more complete and natural.\n"
            "Keep facts, numbers, names, negation, contrast, causality, modality, and core conclusions.\n"
            "Avoid creating new dangling clauses, repeated Chinese, or text that is too long for the subtitle duration.\n"
            "If no safe improvement exists for a target, return no segments for it.\n"
            "Return pure JSON: {\"groups\":[{\"target_subtitle_id\":\"S0001\",\"segments\":[{\"subtitle_id\":\"S0001\",\"zh\":\"中文\"}]}]}"
        )
        try:
            data = self._request_chinese_compression(
                prompt,
                payload,
                task="screen_subtitle_high_confidence_chinese_candidate_repair",
                temperature=0.0,
            )
        except Exception as exc:
            logger.warning("高置信中文候选局部修复失败，保留原字幕: %s", str(exc))
            return list(segments)

        allocations = self._parse_chinese_group_allocations(data, segments)

        retry_payload = []
        for index, seg in targets[:12]:
            target_id = self._segment_subtitle_id(seg, index + 1)
            allocation = allocations.get(target_id, {})
            context = self._semantic_context_for_segment_index(
                index,
                segments,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            if allocation and self._is_valid_group_chinese_allocation_by_id(
                allocation,
                segments,
                context,
            ):
                continue
            retry_item = self._chinese_compression_payload_item(
                index,
                seg,
                segments,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            retry_item["candidate_reason"] = "high_confidence_chinese_fragment"
            retry_item["repair_scope"] = "same_sense_group_chinese_only"
            retry_item["rejected_group_segments"] = allocation
            retry_item["retry_reason"] = (
                "missing_safe_allocation" if not allocation else "allocation_validation_failed"
            )
            retry_payload.append(retry_item)

        if retry_payload:
            retry_prompt = (
                "Conservatively repair Simplified Chinese subtitle allocation inside each fixed sense_group.\n"
                "The first attempt was missing or invalid. Use full_translation as the only authority for Chinese meaning.\n"
                "Do not translate freely from English. English only locates which meaning belongs to which fixed subtitle ID.\n"
                "You may rewrite the target and adjacent same-group Chinese lines, but only existing subtitle_id values are allowed.\n"
                "Do not change English, IDs, order, timing, or subtitle count.\n"
                "Prefer short, direct, complete Chinese expressions. Preserve core actions, facts, numbers, names, negation, contrast, and causality.\n"
                "Reject dangling clauses such as 当...时, 如果..., 因为..., 对于..., 在..., 把..., 将..., 意味着..., 的...\n"
                "If no safe complete improvement exists, return no segments for that group.\n"
                "Return pure JSON: {\"groups\":[{\"target_subtitle_id\":\"S0001\",\"segments\":[{\"subtitle_id\":\"S0001\",\"zh\":\"中文\"}]}]}"
            )
            try:
                retry_data = self._request_chinese_compression(
                    retry_prompt,
                    retry_payload,
                    task="screen_subtitle_high_confidence_chinese_candidate_repair_retry",
                    temperature=0.0,
                )
                retry_allocations = self._parse_chinese_group_allocations(
                    retry_data,
                    segments,
                )
                allocations.update(retry_allocations)
            except Exception as exc:
                logger.warning("高置信中文候选保守重试失败，保留原字幕: %s", str(exc))

        result = list(segments)
        index_by_id = self._segment_index_by_subtitle_id(result)
        changed = 0
        for index, seg in targets[:12]:
            target_id = self._segment_subtitle_id(seg, index + 1)
            allocation = allocations.get(target_id, {})
            if not allocation:
                self._safe_auto_repair_log.append(
                    {
                        "stage": stage,
                        "code": "llm_chinese_candidate_repair_skipped",
                        "subtitle_id": target_id,
                        "reason": "no_safe_allocation_returned",
                    }
                )
                continue
            context = self._semantic_context_for_segment_index(
                index,
                result,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            if not self._is_valid_group_chinese_allocation_by_id(allocation, result, context):
                self._safe_auto_repair_log.append(
                    {
                        "stage": stage,
                        "code": "llm_chinese_candidate_repair_rejected",
                        "subtitle_id": target_id,
                        "reason": "validation_failed",
                        "allocation": allocation,
                    }
                )
                continue
            for subtitle_id, text in allocation.items():
                item_index = index_by_id.get(subtitle_id)
                if item_index is None:
                    continue
                old = result[item_index]
                normalized = self._normalize_text(text)
                if not normalized or old.translated_text == normalized:
                    continue
                result[item_index] = self._copy_segment(old, translated_text=normalized)
                changed += 1
                self._safe_auto_repair_log.append(
                    {
                        "stage": stage,
                        "code": "llm_chinese_candidate_repaired",
                        "index": item_index + 1,
                        "subtitle_id": subtitle_id,
                        "start": self._format_ms(old.start_time),
                        "end": self._format_ms(old.end_time),
                        "english": old.text,
                        "before_chinese": old.translated_text,
                        "after_chinese": normalized,
                        "before_start_ms": int(old.start_time),
                        "before_end_ms": int(old.end_time),
                        "after_start_ms": int(old.start_time),
                        "after_end_ms": int(old.end_time),
                    }
                )
        if not changed:
            return list(segments)
        result = self._restore_invalid_postprocess_allocations(
            before_segments=segments,
            after_segments=result,
            semantic_groups=semantic_groups,
            subtitle_items=subtitle_items,
        )
        return result

    def _record_safe_auto_repair_candidates(
        self,
        segments: Sequence[ASRDataSeg],
        stage: str,
    ) -> None:
        if not hasattr(self, "_safe_auto_repair_candidates"):
            self._safe_auto_repair_candidates = []
        existing = {
            (
                item.get("stage"),
                item.get("code"),
                item.get("subtitle_id"),
                item.get("right_subtitle_id", ""),
            )
            for item in self._safe_auto_repair_candidates
        }
        for index, seg in enumerate(segments, 1):
            subtitle_id = self._segment_subtitle_id(seg, index)
            if self._is_high_load_short_subtitle(seg):
                self._append_safe_auto_repair_candidate(
                    existing,
                    {
                        "stage": stage,
                        "code": "candidate_high_load_short_subtitle",
                        "subtitle_id": subtitle_id,
                        "start": self._format_ms(seg.start_time),
                        "end": self._format_ms(seg.end_time),
                        "english": self._normalize_text(seg.text),
                        "chinese": self._normalize_text(seg.translated_text),
                        "decision": "repair_timing_only_when_safe_auto_repair_is_enabled_and_neighbor_has_room",
                    },
                )
            chinese = self._normalize_text(seg.translated_text)
            if chinese and self._is_high_confidence_chinese_fragment_candidate(chinese):
                self._append_safe_auto_repair_candidate(
                    existing,
                    {
                        "stage": stage,
                        "code": "candidate_chinese_fragment_review_only",
                        "subtitle_id": subtitle_id,
                        "start": self._format_ms(seg.start_time),
                        "end": self._format_ms(seg.end_time),
                        "english": self._normalize_text(seg.text),
                        "chinese": chinese,
                        "decision": "not_auto_repaired_due_to_false_positive_risk",
                    },
                )
        for index, (left, right) in enumerate(zip(segments, segments[1:]), 1):
            left_tokens = self._word_tokens(left.text)
            right_tokens = self._word_tokens(right.text)
            if not left_tokens or not right_tokens:
                continue
            left_last = self._clean_boundary_token(left_tokens[-1])
            right_first = self._clean_boundary_token(right_tokens[0])
            codes: List[str] = []
            if self._is_protected_named_phrase_split(left_last, right_first):
                codes.append("candidate_protected_named_phrase_split")
            if self._is_protected_phrasal_boundary(left_last, right_first):
                codes.append("candidate_protected_phrasal_boundary_split")
            for code in codes:
                self._append_safe_auto_repair_candidate(
                    existing,
                    {
                        "stage": stage,
                        "code": code,
                        "subtitle_id": self._segment_subtitle_id(left, index),
                        "right_subtitle_id": self._segment_subtitle_id(right, index + 1),
                        "start": self._format_ms(left.start_time),
                        "end": self._format_ms(right.end_time),
                        "left_english": self._normalize_text(left.text),
                        "right_english": self._normalize_text(right.text),
                        "decision": "prevented_in_new_local_cutting_or_reported_for_existing_output",
                    },
                )

    @staticmethod
    def _is_high_confidence_chinese_fragment_candidate(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if not normalized:
            return False
        stripped = re.sub(r"[。！？!?…]+$", "", normalized)
        if not stripped:
            return False
        hard_dangling_suffixes = (
            "因为",
            "如果",
            "由于",
            "对于",
            "关于",
            "以及",
            "并且",
            "而",
            "但",
            "把",
            "将",
            "意味着",
            "导致",
            "开始",
            "正在",
        )
        if stripped.endswith(hard_dangling_suffixes):
            return True
        if stripped.endswith("在") and len(stripped) <= 18:
            return True
        if stripped.endswith("时") and not re.search(r"(想|看|说|问|思考|考虑|引发|导致|发生|出现|结束)$", stripped):
            return True
        return False

    def _append_safe_auto_repair_candidate(self, existing: set, item: Dict) -> None:
        key = (
            item.get("stage"),
            item.get("code"),
            item.get("subtitle_id"),
            item.get("right_subtitle_id", ""),
        )
        if key in existing:
            return
        existing.add(key)
        self._safe_auto_repair_candidates.append(item)

    def _safe_auto_repair_guard_summary(self, segments: Sequence[ASRDataSeg]) -> Dict[str, int]:
        return {
            "count": len(segments),
            "missing_chinese": len(self._translation_gaps(segments)),
            "severe_chinese_speed": sum(1 for seg in segments if self._is_severe_chinese_speed(seg)),
            "duration_errors": len(self._subtitle_duration_issues(segments, "ERROR")),
            "duplicate_chinese": len(self._duplicate_chinese_issues(segments)),
            "overlong_english": len(self._overlong_english_issues(segments)),
        }

    @staticmethod
    def _safe_auto_repair_guard_passes(before: Dict[str, int], after: Dict[str, int]) -> bool:
        if int(after.get("count", 0)) != int(before.get("count", 0)):
            return False
        guarded_keys = (
            "missing_chinese",
            "severe_chinese_speed",
            "duration_errors",
            "duplicate_chinese",
            "overlong_english",
        )
        return all(int(after.get(key, 0)) <= int(before.get(key, 0)) for key in guarded_keys)

    def _repair_exact_duplicate_chinese_segments(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        targets: List[int] = []
        for index in range(1, len(segments)):
            previous = segments[index - 1]
            current = segments[index]
            previous_zh = self._normalize_chinese_for_compare(previous.translated_text)
            current_zh = self._normalize_chinese_for_compare(current.translated_text)
            if not previous_zh or previous_zh != current_zh or len(current_zh) < 8:
                continue
            previous_en = self._normalize_text(previous.text)
            current_en = self._normalize_text(current.text)
            if not previous_en or not current_en:
                continue
            if self._normalize_text(previous_en).lower() == self._normalize_text(current_en).lower():
                continue
            if self._is_simple_short_response(previous_en, previous.translated_text) or self._is_simple_short_response(
                current_en, current.translated_text
            ):
                continue
            targets.append(index)

        if not targets:
            return list(segments)

        originals = [segments[index].text for index in targets]
        try:
            translations = self._translate_split_parts(originals)
        except Exception as exc:
            logger.warning("精确重复中文字幕重译失败，保留原字幕: %s", str(exc))
            return list(segments)
        if len(translations) != len(targets):
            logger.warning("精确重复中文字幕重译数量不一致，保留原字幕")
            return list(segments)

        result = list(segments)
        changed = 0
        for offset, index in enumerate(targets):
            old = result[index]
            translated = self._normalize_text(str(translations[offset] or ""))
            if not translated:
                continue
            if self._normalize_chinese_for_compare(translated) == self._normalize_chinese_for_compare(old.translated_text):
                continue
            if self._is_translation_too_fast_for_segment(translated, old):
                continue
            result[index] = self._copy_segment(old, translated_text=translated)
            changed += 1
        if changed:
            logger.info("自动修复精确重复中文字幕: %s", changed)
        return result

    def _is_translation_too_fast_for_segment(self, translated: str, seg: ASRDataSeg) -> bool:
        zh_chars = len(re.findall(r"[\u4e00-\u9fff]", translated or ""))
        if zh_chars < 12:
            return False
        duration_ms = max(1, int(seg.end_time) - int(seg.start_time))
        cps = zh_chars / (duration_ms / 1000.0)
        return cps > CHINESE_CPS_ERROR

    def _record_safe_auto_repair_diff(
        self,
        before: Sequence[ASRDataSeg],
        after: Sequence[ASRDataSeg],
        stage: str,
    ) -> None:
        if not hasattr(self, "_safe_auto_repair_log"):
            self._safe_auto_repair_log = []
        if len(before) != len(after):
            self._safe_auto_repair_log.append(
                {
                    "stage": stage,
                    "code": "safe_repair_count_changed_rejected",
                    "before_count": len(before),
                    "after_count": len(after),
                }
            )
            return
        for index, (old, new) in enumerate(zip(before, after), 1):
            if (
                old.text == new.text
                and old.translated_text == new.translated_text
                and int(old.start_time) == int(new.start_time)
                and int(old.end_time) == int(new.end_time)
            ):
                continue
            code = self._safe_auto_repair_change_code(old, new)
            self._safe_auto_repair_log.append(
                {
                    "stage": stage,
                    "code": code,
                    "index": index,
                    "subtitle_id": self._segment_subtitle_id(new, index),
                    "start": self._format_ms(new.start_time),
                    "end": self._format_ms(new.end_time),
                    "english": new.text,
                    "before_chinese": old.translated_text,
                    "after_chinese": new.translated_text,
                    "before_start_ms": int(old.start_time),
                    "before_end_ms": int(old.end_time),
                    "after_start_ms": int(new.start_time),
                    "after_end_ms": int(new.end_time),
                }
            )

    def _safe_auto_repair_change_code(self, old: ASRDataSeg, new: ASRDataSeg) -> str:
        if not self._normalize_text(old.translated_text) and self._normalize_text(new.translated_text):
            return "missing_chinese_filled"
        old_norm = self._normalize_chinese_for_compare(old.translated_text)
        new_norm = self._normalize_chinese_for_compare(new.translated_text)
        if old_norm != new_norm:
            if self._is_severe_chinese_speed(old) and not self._is_severe_chinese_speed(new):
                return "severe_chinese_speed_repaired"
            return "chinese_text_repaired"
        if int(old.start_time) != int(new.start_time) or int(old.end_time) != int(new.end_time):
            return "timing_padding_repaired"
        return "safe_repair_changed"

    def _repair_overlong_english_segments_local(
        self, segments: Sequence[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        result: List[ASRDataSeg] = []
        changed = 0
        for seg in segments:
            if getattr(seg, "subtitle_id", None):
                result.append(seg)
                continue
            text = self._normalize_text(seg.text)
            if self._word_count(text) <= self.max_english_words:
                result.append(seg)
                continue
            parts = self._split_english_text(text, self.max_english_words)
            if len(parts) <= 1 or any(
                self._word_count(part) > self.max_english_words for part in parts
            ):
                result.append(seg)
                continue
            zh_parts = self._split_translated_text(seg.translated_text, len(parts))
            if len(zh_parts) != len(parts):
                zh_parts = [seg.translated_text if index == 0 else "" for index in range(len(parts))]
            timings = self._proportional_segment_timings(seg, parts)
            for offset, part in enumerate(parts):
                translated = zh_parts[offset] if offset < len(zh_parts) else ""
                start_ms, end_ms = timings[offset]
                result.append(
                    ASRDataSeg(
                        text=part,
                        translated_text=translated,
                        start_time=start_ms,
                        end_time=end_ms,
                    )
                )
            changed += 1
        if changed:
            logger.info("本地修复英文超长字幕: %s", changed)
        return result

    def _compress_fast_chinese_segments(
        self,
        segments: Sequence[ASRDataSeg],
        semantic_groups: Optional[Sequence[Dict]] = None,
        subtitle_items: Optional[Sequence[ScreenSubtitleItem]] = None,
    ) -> List[ASRDataSeg]:
        targets = [
            (index, seg)
            for index, seg in enumerate(segments)
            if self._is_severe_chinese_speed(seg)
        ]
        if not targets:
            return list(segments)

        data = {"items": []}
        if targets:
            payload = [
                self._chinese_compression_payload_item(
                    index,
                    seg,
                    segments,
                    semantic_groups=semantic_groups,
                    subtitle_items=subtitle_items,
                )
                for index, seg in targets
            ]
            prompt = (
                "You compress Simplified Chinese subtitles for fixed bilingual video subtitles.\n"
                "Only rewrite target Chinese subtitles. Do not change English, IDs, order, or timing.\n"
                "Use full_translation as the authority. English is only for locating meaning.\n"
                "Read the whole sense_group and adjacent parts before compressing the target.\n"
                "The target Chinese must be natural, concise, and independently understandable when possible.\n"
                "If the target is overloaded and an adjacent same-group subtitle is much shorter, prefer moving dependent meaning into that adjacent subtitle.\n"
                "Avoid title-like fragments and dangling clauses such as 而若..., 如果..., 因为..., 对于..., 在..., 把..., 将..., 意味着..., 的..., 以及...\n"
                "Keep facts, numbers, names, negation, contrast, causality, modality, and core conclusions.\n"
                "Return pure JSON using the existing subtitle_id only:\n"
                "{\"items\":[{\"subtitle_id\":\"S0001\",\"chinese\":\"压缩后的中文\"}]}"
            )
            try:
                data = self._request_chinese_compression(
                    prompt,
                    payload,
                    task="screen_subtitle_chinese_speed_compress",
                    temperature=0.1,
                )
            except Exception as e:
                logger.warning("中文字幕超速压缩失败，保留原字幕: %s", str(e))
                return list(segments)

        by_id: Dict[str, str] = {}
        id_to_index = self._segment_index_by_subtitle_id(segments)
        for item in data.get("items", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            subtitle_id = str(item.get("subtitle_id") or "").strip()
            if not subtitle_id:
                self._record_translation_structure_error(
                    "translation_id_missing",
                    message="Compression returned an item without subtitle_id.",
                )
                continue
            index = id_to_index.get(subtitle_id)
            if index is None:
                self._record_translation_structure_error(
                    "translation_id_unknown",
                    returned_ids=[subtitle_id],
                    message=f"Compression returned unknown subtitle_id: {subtitle_id}",
                )
                continue
            text = str(item.get("chinese", "")).strip()
            if text:
                by_id[subtitle_id] = text

        group_reallocation_payload = []
        for index, seg in targets:
            subtitle_id = self._segment_subtitle_id(seg, index + 1)
            compressed = by_id.get(subtitle_id, "")
            context = self._semantic_context_for_segment_index(
                index,
                segments,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            if compressed and self._is_valid_chinese_compression(
                compressed, seg, segments, index, context=context
            ):
                continue
            item = self._chinese_compression_payload_item(
                index, seg, segments, semantic_groups=semantic_groups, subtitle_items=subtitle_items
            )
            item["rejected_single_chinese"] = compressed
            group_reallocation_payload.append(item)

        group_allocations: Dict[str, Dict[str, str]] = {}
        if group_reallocation_payload:
            group_prompt = (
                "Reallocate Simplified Chinese subtitles only inside the provided sense_group.\n"
                "Use full_translation as the authority. English is only for locating meaning.\n"
                "You may rewrite the target and adjacent same-group Chinese subtitles only when single-line compression fails.\n"
                "Do not change English, IDs, order, timing, or subtitle count.\n"
                "Return only existing subtitle_id values from sense_group.parts. Keep every returned line natural and readable.\n"
                "The concatenated group Chinese must preserve the core meaning and form a complete Chinese sentence.\n"
                "Balance Chinese reading load across the same-group subtitles according to each part duration.\n"
                "Return pure JSON using existing subtitle_id values only: "
                "{\"groups\":[{\"target_subtitle_id\":\"S0001\",\"segments\":[{\"subtitle_id\":\"S0001\",\"zh\":\"中文\"}]}]}"
            )
            try:
                allocation_data = self._request_chinese_compression(
                    group_prompt,
                    group_reallocation_payload,
                    task="screen_subtitle_chinese_group_reallocate",
                    temperature=0.1,
                )
                group_allocations = self._parse_chinese_group_allocations(
                    allocation_data, segments
                )
            except Exception as e:
                logger.warning("中文字幕同组重分配失败: %s", str(e))

        retry_payload = []
        for index, seg in targets:
            context = self._semantic_context_for_segment_index(
                index,
                segments,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            subtitle_id = self._segment_subtitle_id(seg, index + 1)
            if subtitle_id in group_allocations and self._is_valid_group_chinese_allocation_by_id(
                group_allocations[subtitle_id],
                segments,
                context,
            ):
                continue
            compressed = by_id.get(subtitle_id, "")
            if compressed and self._is_valid_chinese_compression(
                compressed, seg, segments, index, context=context
            ):
                continue
            retry_item = self._chinese_compression_payload_item(
                index, seg, segments, semantic_groups=semantic_groups, subtitle_items=subtitle_items
            )
            retry_item["rejected_single_chinese"] = compressed
            retry_item["rejected_group_segments"] = group_allocations.get(subtitle_id, {})
            retry_payload.append(retry_item)

        if retry_payload:
            conservative_prompt = (
                "Conservatively reallocate only same-group Simplified Chinese subtitles.\n"
                "Use full_translation as the authority. Do not translate freely from English.\n"
                "Do not change English, IDs, order, timing, or subtitle count.\n"
                "Prefer direct complete Chinese sentences. Keep core actions and conclusions.\n"
                "Balance overloaded Chinese lines into adjacent same-group subtitle IDs when that preserves meaning better than overcompressing one line.\n"
                "Return pure JSON using existing subtitle_id values only: "
                "{\"groups\":[{\"target_subtitle_id\":\"S0001\",\"segments\":[{\"subtitle_id\":\"S0001\",\"zh\":\"中文\"}]}]}"
            )
            try:
                retry_data = self._request_chinese_compression(
                    conservative_prompt,
                    retry_payload,
                    task="screen_subtitle_chinese_group_reallocate_retry",
                    temperature=0.0,
                )
                group_allocations.update(
                    self._parse_chinese_group_allocations(retry_data, segments)
                )
            except Exception as e:
                logger.warning("中文字幕同组保守重分配重试失败: %s", str(e))

        result = list(segments)
        changed = 0
        for index, seg in targets:
            context = self._semantic_context_for_segment_index(
                index,
                segments,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            subtitle_id = self._segment_subtitle_id(seg, index + 1)
            allocation = group_allocations.get(subtitle_id, {})
            if allocation and self._is_valid_group_chinese_allocation_by_id(
                allocation,
                result,
                context,
            ):
                index_by_id = self._segment_index_by_subtitle_id(result)
                for item_id, text in allocation.items():
                    item_index = index_by_id.get(item_id)
                    if item_index is None:
                        self._record_translation_structure_error(
                            "translation_id_unknown",
                            returned_ids=[item_id],
                            message=f"Compression allocation references unknown subtitle_id: {item_id}",
                        )
                        continue
                    old = result[item_index]
                    if old.translated_text == text:
                        continue
                    result[item_index] = self._copy_segment(
                        old,
                        translated_text=text,
                    )
                    changed += 1
                continue
            compressed = by_id.get(subtitle_id, "")
            if not compressed:
                continue
            if not self._is_valid_chinese_compression(
                compressed,
                seg,
                segments,
                index,
                context=context,
            ):
                continue
            result[index] = self._copy_segment(
                seg,
                translated_text=compressed,
            )
            changed += 1
        if changed:
            result = self._restore_invalid_postprocess_allocations(
                before_segments=segments,
                after_segments=result,
                semantic_groups=semantic_groups,
                subtitle_items=subtitle_items,
            )
            logger.info("局部压缩中文字幕阅读速度: %s", changed)
        return result

    def _restore_invalid_postprocess_allocations(
        self,
        *,
        before_segments: Sequence[ASRDataSeg],
        after_segments: Sequence[ASRDataSeg],
        semantic_groups: Optional[Sequence[Dict]],
        subtitle_items: Optional[Sequence[ScreenSubtitleItem]],
    ) -> List[ASRDataSeg]:
        if not semantic_groups or not subtitle_items:
            return list(after_segments)
        result = list(after_segments)
        for group in semantic_groups:
            start = int(group.get("start_index") or 0)
            count = len(group.get("items") or [])
            end = start + count
            if count <= 0 or end > len(result) or end > len(before_segments):
                continue
            if all(
                before_segments[index].translated_text == result[index].translated_text
                for index in range(start, end)
            ):
                continue
            entry = self._allocation_entry_from_group_segments(group, result[start:end])
            before_entry = self._allocation_entry_from_group_segments(group, before_segments[start:end])
            after_allocation = {
                self._segment_subtitle_id(result[index], index + 1): result[index].translated_text
                for index in range(start, end)
            }
            before_allocation = {
                self._segment_subtitle_id(before_segments[index], index + 1): before_segments[index].translated_text
                for index in range(start, end)
            }
            before_validation = self._validate_group_chinese_allocation(
                before_entry,
                before_allocation,
            )
            after_validation = self._validate_group_chinese_allocation(entry, after_allocation)
            candidate_decision = self._decide_id_bound_allocation_candidate(
                original_allocation=before_allocation,
                candidate_allocation=after_allocation,
                group_context=entry,
                original_validation=before_validation,
                candidate_validation=after_validation,
                candidate_source="compression_or_reallocation",
                require_high_confidence_fix=False,
            )
            candidate_comparison = candidate_decision["quality_comparison"]
            before_speed_pressure = self._group_chinese_speed_pressure(
                before_segments[start:end]
            )
            after_speed_pressure = self._group_chinese_speed_pressure(
                result[start:end]
            )
            before_severe_count = sum(
                1 for segment in before_segments[start:end]
                if self._is_severe_chinese_speed(segment)
            )
            after_severe_count = sum(
                1 for segment in result[start:end]
                if self._is_severe_chinese_speed(segment)
            )
            speed_improved = (
                after_speed_pressure + 0.01 < before_speed_pressure
                or (
                    after_severe_count < before_severe_count
                    and after_speed_pressure <= before_speed_pressure + 0.01
                )
            )
            candidate_comparison.update(
                {
                    "postprocess_stage": "compression_or_reallocation",
                    "before_speed_pressure": round(before_speed_pressure, 3),
                    "after_speed_pressure": round(after_speed_pressure, 3),
                    "before_severe_count": before_severe_count,
                    "after_severe_count": after_severe_count,
                    "speed_improved": speed_improved,
                }
            )
            self._last_allocation_validation.append(
                {
                    **after_validation,
                    "postprocess_stage": "compression_or_reallocation",
                    "candidate_comparison": candidate_comparison,
                }
            )
            if not candidate_decision["accepted"] or not speed_improved:
                for index in range(start, end):
                    result[index] = before_segments[index]
                if not candidate_comparison["accepted"]:
                    self._last_allocation_unresolved.append(
                        {
                            "semantic_group_id": f"G{int(group.get('id') or 0):04d}",
                            "reason": "postprocess_allocation_quality_regression_restored",
                            "issue_codes": after_validation["issue_codes"],
                            "candidate_comparison": candidate_comparison,
                        }
                    )
        return result

    def _group_chinese_speed_pressure(
        self,
        segments: Sequence[ASRDataSeg],
    ) -> float:
        """Measure local reading-load excess without changing any threshold."""
        pressure = 0.0
        for segment in segments:
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", segment.translated_text or ""))
            duration_seconds = max(
                0.1,
                (int(segment.end_time) - int(segment.start_time)) / 1000.0,
            )
            pressure += max(0.0, chinese_chars / duration_seconds - CHINESE_CPS_WARNING)
        return pressure

    def _allocation_entry_from_group_segments(
        self,
        group: Dict,
        segments: Sequence[ASRDataSeg],
    ) -> Dict:
        group_id = int(group.get("id") or 0)
        items = list(group.get("items") or [])
        parts = []
        for offset, item in enumerate(items):
            seg = segments[offset] if offset < len(segments) else None
            parts.append(
                {
                    "subtitle_id": self._item_subtitle_id(
                        item,
                        int(group.get("start_index") or 0) + offset + 1,
                    ),
                    "english": item.original,
                    "duration_ms": (
                        max(1, int(seg.end_time) - int(seg.start_time))
                        if seg is not None
                        else None
                    ),
                    "max_zh_chars": self.max_cjk_chars,
                }
            )
        return {
            "id": group_id,
            "allocation_prompt_version": SEMANTIC_ALLOCATION_PROMPT_VERSION,
            "full_english": " ".join(item.original for item in items),
            "full_translation": self._last_semantic_full_translations.get(group_id, ""),
            "subtitle_parts": parts,
        }

    def _request_chinese_compression(
        self,
        prompt: str,
        payload: Sequence[Dict],
        task: str,
        temperature: float,
    ) -> Dict:
        cache_key = self._semantic_chinese_cache_key(prompt, payload, task)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=temperature,
            task=task,
        )
        if cache_result:
            self._llm_cache_used = True
            return json.loads(cache_result)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=temperature,
            timeout=self.timeout,
        )
        data = json_repair.loads(response.choices[0].message.content)
        self.cache_manager.set_llm_result(
            cache_key,
            json.dumps(data, ensure_ascii=False),
            self.model,
            temperature=temperature,
            task=task,
        )
        return data

    def _parse_chinese_group_allocations(
        self, data: Dict, segments: Sequence[ASRDataSeg]
    ) -> Dict[str, Dict[str, str]]:
        result: Dict[str, Dict[str, str]] = {}
        groups = data.get("groups", []) if isinstance(data, dict) else []
        id_to_index = self._segment_index_by_subtitle_id(segments)
        for group in groups:
            if not isinstance(group, dict):
                continue
            target_id = str(group.get("target_subtitle_id") or "").strip()
            if target_id not in id_to_index:
                self._record_translation_structure_error(
                    "translation_id_missing" if not target_id else "translation_id_unknown",
                    returned_ids=[target_id] if target_id else [],
                    message=(
                        "Group reallocation returned no target_subtitle_id."
                        if not target_id
                        else f"Group reallocation returned unknown target_subtitle_id: {target_id}"
                    ),
                )
                continue
            allocation: Dict[str, str] = {}
            for item in group.get("segments", []):
                if not isinstance(item, dict):
                    continue
                subtitle_id = str(item.get("subtitle_id") or "").strip()
                if subtitle_id not in id_to_index:
                    self._record_translation_structure_error(
                        "translation_id_missing" if not subtitle_id else "translation_id_unknown",
                        returned_ids=[subtitle_id] if subtitle_id else [],
                        message=(
                            "Group reallocation returned a segment without subtitle_id."
                            if not subtitle_id
                            else f"Group reallocation returned unknown subtitle_id: {subtitle_id}"
                        ),
                    )
                    continue
                text = str(item.get("zh", item.get("chinese", ""))).strip()
                if text:
                    allocation[subtitle_id] = text
            if allocation:
                result[target_id] = allocation
        return result

    def _is_valid_group_chinese_allocation_by_id(
        self,
        allocation: Dict[str, str],
        segments: Sequence[ASRDataSeg],
        context: Dict,
    ) -> bool:
        if not allocation:
            return False
        id_to_index = self._segment_index_by_subtitle_id(segments)
        index_allocation: Dict[int, str] = {}
        for subtitle_id, text in allocation.items():
            index = id_to_index.get(subtitle_id)
            if index is None:
                return False
            index_allocation[index] = text
        return self._is_valid_group_chinese_allocation(index_allocation, segments, context)

    def _chinese_compression_payload_item(
        self,
        index: int,
        seg: ASRDataSeg,
        segments: Sequence[ASRDataSeg],
        semantic_groups: Optional[Sequence[Dict]] = None,
        subtitle_items: Optional[Sequence[ScreenSubtitleItem]] = None,
    ) -> Dict:
        context = self._semantic_context_for_segment_index(
            index,
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=subtitle_items,
        )
        return {
            "subtitle_id": self._segment_subtitle_id(seg, index + 1),
            "target": {
                "subtitle_id": self._segment_subtitle_id(seg, index + 1),
                "english": self._normalize_text(seg.text),
                "current_chinese": self._normalize_text(seg.translated_text),
                "duration_ms": max(1, int(seg.end_time) - int(seg.start_time)),
                "target_chars": self._target_zh_chars_for_duration(seg),
                "absolute_max_chars": self._absolute_zh_chars_for_duration(seg),
            },
            "sense_group": context,
        }

    def _semantic_context_for_segment_index(
        self,
        index: int,
        segments: Sequence[ASRDataSeg],
        semantic_groups: Optional[Sequence[Dict]] = None,
        subtitle_items: Optional[Sequence[ScreenSubtitleItem]] = None,
    ) -> Dict:
        groups = semantic_groups or []
        items = list(subtitle_items or [])
        for group in groups:
            start = int(group.get("start_index") or 0)
            count = len(group.get("items") or [])
            end = start + count
            if not (start <= index < end):
                continue
            group_segments = list(segments[start:end])
            group_items = items[start:end] if len(items) >= end else []
            parts = []
            for offset, group_seg in enumerate(group_segments):
                part_item = group_items[offset] if offset < len(group_items) else None
                parts.append(
                    {
                        "index": start + offset,
                        "english": self._normalize_text(group_seg.text),
                        "current_chinese": self._normalize_text(group_seg.translated_text),
                        "duration_ms": max(
                            1, int(group_seg.end_time) - int(group_seg.start_time)
                        ),
                        "word_start": getattr(part_item, "word_start", None),
                        "word_end": getattr(part_item, "word_end", None),
                        "subtitle_id": self._segment_subtitle_id(group_seg, start + offset + 1),
                    }
                )
            group_id = int(group.get("id") or 0)
            return {
                "group_id": group_id,
                "full_english": " ".join(part["english"] for part in parts).strip(),
                "full_translation": self._last_semantic_full_translations.get(group_id)
                or "".join(part["current_chinese"] for part in parts),
                "parts": parts,
            }

        left = max(0, index - 1)
        right = min(len(segments), index + 2)
        parts = [
            {
                "index": pos,
                "english": self._normalize_text(segments[pos].text),
                "current_chinese": self._normalize_text(segments[pos].translated_text),
                "duration_ms": max(
                    1, int(segments[pos].end_time) - int(segments[pos].start_time)
                ),
            }
            for pos in range(left, right)
        ]
        return {
            "group_id": None,
            "full_english": " ".join(part["english"] for part in parts).strip(),
            "full_translation": "".join(part["current_chinese"] for part in parts),
            "parts": parts,
        }

    def _is_valid_chinese_compression(
        self,
        text: str,
        seg: ASRDataSeg,
        segments: Sequence[ASRDataSeg],
        index: int,
        context: Optional[Dict] = None,
    ) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        if len(re.findall(r"[\u4e00-\u9fff]", normalized)) > self._absolute_zh_chars_for_duration(seg):
            return False
        test_seg = ASRDataSeg(
            text=seg.text,
            translated_text=normalized,
            start_time=seg.start_time,
            end_time=seg.end_time,
        )
        if self._is_severe_chinese_speed(test_seg):
            return False
        if self._is_bad_chinese_fragment(normalized):
            return False
        if index + 1 < len(segments):
            next_text = self._normalize_text(segments[index + 1].translated_text)
            if next_text and self._normalize_chinese_for_compare(normalized) == self._normalize_chinese_for_compare(next_text):
                return False
        if context and not self._is_valid_group_chinese_allocation(
            {index: normalized},
            segments,
            context,
        ):
            return False
        return True

    def _is_valid_group_chinese_allocation(
        self,
        allocation: Dict[int, str],
        segments: Sequence[ASRDataSeg],
        context: Dict,
    ) -> bool:
        parts = context.get("parts") or []
        if not parts:
            return True
        allowed_indices = {int(part["index"]) for part in parts if "index" in part}
        if not allocation or any(index not in allowed_indices for index in allocation):
            return False

        merged_parts: List[str] = []
        for part in parts:
            index = int(part["index"])
            if index < 0 or index >= len(segments):
                return False
            text = self._normalize_text(allocation.get(index, segments[index].translated_text))
            if not text:
                return False
            test_seg = ASRDataSeg(
                text=segments[index].text,
                translated_text=text,
                start_time=segments[index].start_time,
                end_time=segments[index].end_time,
            )
            if self._is_severe_chinese_speed(test_seg):
                return False
            if self._is_bad_chinese_fragment(text):
                return False
            merged_parts.append(text)

        merged = self._normalize_text("".join(merged_parts))
        full_translation = self._normalize_text(context.get("full_translation", ""))
        full_english = self._normalize_text(context.get("full_english", ""))
        part_ids = [
            str(part.get("subtitle_id") or part.get("index") or offset)
            for offset, part in enumerate(parts)
        ]
        if self._detect_adjacent_chinese_duplication(part_ids, merged_parts):
            return False
        if self._detect_unnatural_adjacent_chinese_boundary(merged_parts):
            return False
        if self._is_incomplete_chinese_group(merged):
            return False
        if self._has_core_semantic_loss(merged, full_translation, full_english):
            return False
        return True

    @staticmethod
    def _detect_unnatural_adjacent_chinese_boundary(texts: Sequence[str]) -> bool:
        normalized = [
            re.sub(r"\s+", "", text or "").strip()
            for text in texts
        ]
        for left, right in zip(normalized, normalized[1:]):
            left = re.sub(r"[，。！？；：、,.!?;:]+$", "", left)
            right = re.sub(r"^[，。！？；：、,.!?;:]+", "", right)
            if not left or not right:
                continue
            if re.search(r"(锚定|定位|归入|投入|放入|置于|固定|连接|链接)(它|其|这|那|这个|这一点)$", left) and right.startswith(
                ("到", "在", "于", "向", "至")
            ):
                return True
            if left.endswith(("它", "其", "这个", "这一点")) and right.startswith(
                ("到一", "到某", "到古", "到新", "到旧", "在一", "于一")
            ):
                return True
        return False

    @staticmethod
    def _is_incomplete_chinese_group(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        normalized = re.sub(r"[，。！？；：、,.!?;:]+$", "", normalized)
        if not normalized:
            return True
        if normalized in {
            "\u597d\u7684",
            "\u6ca1\u9519",
            "\u5bf9",
            "\u662f\u7684",
            "\u771f\u7684",
            "\u771f\u7684\u5417",
            "对吧",
            "是吧",
            "好吧",
            "嗯",
            "啊",
            "哦",
            "哇",
            "\u5728\u54ea\u91cc",
            "\u4e3a\u4ec0\u4e48",
            "\u4ec0\u4e48\u95ee\u9898",
        }:
            return False
        if re.search(r"[\u5417\u5462\u5427\u554a]$", normalized):
            return False
        if normalized.endswith("\u4f60\u61c2\u7684"):
            return False
        dangling_endings = (
            "\u65f6",  # 时
            "\u4e4b\u540e",  # 之后
            "\u4ee5\u540e",  # 以后
            "\u7684",  # 的
            "\u56e0\u4e3a",  # 因为
            "\u5982\u679c",  # 如果
        )
        if normalized.endswith(dangling_endings):
            return True
        has_action = bool(
            re.search(
                r"[\u60f3\u770b\u95ee\u8bf4\u8ba9\u4f7f\u6210\u4e3a\u5e26\u6765\u5f15\u53d1\u9762\u4e34\u89e3\u91ca\u601d\u8003\u77e5\u9053\u6253\u7834\u62ff\u8d70\u662f\u6709\u80fd\u4f1a\u8981\u5fc5\u987b\u5f00\u59cb\u8ba8\u8bba\u8bbe\u8ba1\u5173\u6ce8]",
                normalized,
            )
        )
        return not has_action

    @staticmethod
    def _is_bad_chinese_fragment(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        normalized = re.sub(r"[，。！？；：、,.!?;:]+$", "", normalized)
        if normalized in {
            "\u597d\u7684",
            "\u6ca1\u9519",
            "\u5bf9",
            "\u662f\u7684",
            "\u771f\u7684",
            "\u771f\u7684\u5417",
            "\u5728\u54ea\u91cc",
            "\u4e3a\u4ec0\u4e48",
            "\u4ec0\u4e48\u95ee\u9898",
        }:
            return False
        # Sentence-final 是的/对的/好的 are complete response forms; their final
        # 的 must not be treated as a dangling modifier by the group audit.
        if normalized.endswith(("\u662f\u7684", "\u5bf9\u7684", "\u597d\u7684", "\u6ca1\u9519", "\u5f53\u7136")):
            return False
        if normalized.startswith("\u5982\u679c") and re.search(r"[\u5c31\u4f1a\u8981\u80fd\u53ef\u5fc5\u987b]", normalized):
            return False
        if normalized.endswith("\u4f60\u61c2\u7684"):
            return False
        bad_prefixes = (
            "而若",
            "若",
            "如果",
            "因为",
            "对于",
            "在",
            "将",
            "把",
            "意味着",
            "以及",
        )
        bad_suffixes = (
            "的",
            "以及",
            "因为",
            "如果",
            "对于",
            "在",
            "将",
            "把",
            "意味着",
        )
        if normalized in {"那么", "而且", "然后", "所以", "不过", "但是", "此外"}:
            return False
        if normalized.startswith(bad_prefixes):
            return True
        if normalized.endswith(bad_suffixes):
            return True
        return False

    @staticmethod
    def _has_core_semantic_loss(
        merged_chinese: str,
        full_translation: str,
        full_english: str,
    ) -> bool:
        merged = re.sub(r"\s+", "", merged_chinese or "")
        full_zh = re.sub(r"\s+", "", full_translation or "")
        full_en = (full_english or "").lower()

        # Chinese negation can be written as “并非”; account for it before
        # treating an otherwise complete allocation as a semantic-loss risk.
        semantic_markers = [
            ("ponder", ("\u60f3", "\u601d\u8003", "\u7422\u78e8")),
            ("think", ("\u60f3", "\u601d\u8003")),
            ("question", ("\u95ee\u9898", "\u7591\u95ee", "\u8d28\u7591")),
            ("not ", ("\u4e0d", "\u6ca1", "\u65e0", "\u975e")),
            ("because", ("\u56e0\u4e3a", "\u56e0", "\u6240\u4ee5")),
            ("but", ("\u4f46", "\u4e0d\u8fc7", "\u800c")),
        ]
        for english_marker, zh_options in semantic_markers:
            if english_marker in full_en and not any(option in merged for option in zh_options):
                return True

        zh_marker_groups = [
            ("\u601d\u8003", "\u60f3", "\u7422\u78e8"),
            ("\u95ee\u9898", "\u7591\u95ee", "\u8d28\u7591"),
        ]
        for options in zh_marker_groups:
            if any(option in full_zh for option in options) and not any(
                option in merged for option in options
            ):
                return True
        return False

    def _is_severe_chinese_speed(self, seg: ASRDataSeg) -> bool:
        translated = self._normalize_text(seg.translated_text)
        zh_chars = len(re.findall(r"[\u4e00-\u9fff]", translated))
        duration_ms = max(1, int(seg.end_time) - int(seg.start_time))
        if duration_ms < 900 or zh_chars < 12:
            return False
        return zh_chars / (duration_ms / 1000.0) > CHINESE_CPS_ERROR

    @staticmethod
    def _target_zh_chars_for_duration(seg: ASRDataSeg) -> int:
        duration_sec = max(0.1, (int(seg.end_time) - int(seg.start_time)) / 1000.0)
        return max(4, int(duration_sec * 8))

    @staticmethod
    def _absolute_zh_chars_for_duration(seg: ASRDataSeg) -> int:
        duration_sec = max(0.1, (int(seg.end_time) - int(seg.start_time)) / 1000.0)
        return max(6, int(duration_sec * CHINESE_CPS_ERROR))

    def _chinese_display_budget(self, duration_ms: Optional[int]) -> Dict[str, int]:
        """Return advisory Chinese budgets without changing the fixed cue time."""
        duration_sec = max(0.1, int(duration_ms or 0) / 1000.0)
        configured_limit = max(4, int(self.max_cjk_chars or 0))
        return {
            "target_zh_chars": min(configured_limit, max(4, int(duration_sec * 8))),
            "absolute_max_zh_chars": min(
                configured_limit,
                max(6, int(duration_sec * CHINESE_CPS_ERROR)),
            ),
        }

    def _proportional_segment_timings(
        self, seg: ASRDataSeg, parts: Sequence[str]
    ) -> List[tuple[int, int]]:
        start = int(seg.start_time)
        end = max(start + len(parts), int(seg.end_time))
        duration = end - start
        weights = [max(1, self._word_count(part)) for part in parts]
        total = max(1, sum(weights))
        timings: List[tuple[int, int]] = []
        cursor = start
        consumed = 0
        for index, weight in enumerate(weights):
            consumed += weight
            if index == len(weights) - 1:
                part_end = end
            else:
                part_end = start + int(duration * consumed / total)
            part_end = max(cursor + 1, part_end)
            timings.append((cursor, min(part_end, end)))
            cursor = min(part_end, end)
        return timings

    def _segments_from_parts(self, seg: ASRDataSeg, parts: List[str]) -> List[ASRDataSeg]:
        if getattr(seg, "subtitle_id", None):
            return [seg]
        translations = self._translate_split_parts(parts)
        duration = max(seg.end_time - seg.start_time, len(parts))
        result: List[ASRDataSeg] = []
        for index, part in enumerate(parts):
            start_time = seg.start_time + int(duration * index / len(parts))
            end_time = seg.start_time + int(duration * (index + 1) / len(parts))
            result.append(
                ASRDataSeg(
                    text=part,
                    translated_text=(
                        translations[index] if index < len(translations) else ""
                    ),
                    start_time=start_time,
                    end_time=max(end_time, start_time + 300),
                )
            )
        return result

    def _edit_chunk(self, chunk: List[tuple[int, ASRDataSeg]]) -> List[ScreenSubtitleItem]:
        logger.info(
            "[+]正在整理上屏字幕：%s - %s",
            chunk[0][0],
            chunk[-1][0],
        )
        payload = [
            {
                "id": idx,
                "original": seg.text,
                "translated": seg.translated_text,
                "word_range": self._active_source_word_spans.get(idx),
                "words": self._payload_words_for_source(idx),
            }
            for idx, seg in chunk
        ]

        prompt = self._compose_prompt(
            Template(SCREEN_EDITOR_PROMPT).safe_substitute(
                target_language=self.target_language,
                max_cjk_chars=self.max_cjk_chars,
                max_english_words=self.max_english_words,
            )
        )
        cache_key = self._cache_key(prompt, payload)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=self.temperature,
            task="screen_subtitle_editor",
        )
        if cache_result:
            self._llm_cache_used = True
            data = json.loads(cache_result)
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                temperature=self.temperature,
                timeout=self.timeout,
            )
            data = json_repair.loads(response.choices[0].message.content)
            self.cache_manager.set_llm_result(
                cache_key,
                json.dumps(data, ensure_ascii=False),
                self.model,
                temperature=self.temperature,
                task="screen_subtitle_editor",
            )

        return self._parse_items(data, chunk)

    def _parse_items(
        self, data: Dict, chunk: List[tuple[int, ASRDataSeg]]
    ) -> List[ScreenSubtitleItem]:
        valid_ids = {idx for idx, _ in chunk}
        by_id = {idx: seg for idx, seg in chunk}
        items = data.get("items", data if isinstance(data, list) else [])
        parsed: List[ScreenSubtitleItem] = []

        for raw in items:
            try:
                source_ids = [int(x) for x in raw.get("source_ids", [])]
                source_ids = [x for x in source_ids if x in valid_ids]
                translated = str(raw.get("translated", "")).strip()
                word_start = self._safe_int(raw.get("word_start"))
                word_end = self._safe_int(raw.get("word_end"))
                original = str(raw.get("original", "")).strip()
                if not original:
                    original = self._text_from_valid_item_word_range(
                        source_ids, word_start, word_end
                    )
                if not source_ids or not original:
                    continue
                original = self._normalize_text(original)
                translated = self._normalize_text(translated)
                if not original:
                    continue
                source_original = self._source_original_text(source_ids, by_id)
                if source_original and not self._is_word_subsequence(
                    original, source_original
                ):
                    original = source_original
                elif source_original:
                    original = self._restore_source_surface(original, source_original)
                parsed.append(
                    ScreenSubtitleItem(
                        source_ids=source_ids,
                        original=original,
                        translated=translated,
                        word_start=word_start,
                        word_end=word_end,
                    )
                )
            except Exception:
                continue

        if not parsed:
            logger.warning("上屏字幕整理结果为空，保留原字幕块")
            return [
                ScreenSubtitleItem([idx], seg.text, seg.translated_text)
                for idx, seg in chunk
            ]

        parsed = self._restore_missing_source_items(parsed, chunk)
        parsed.sort(
            key=lambda item: (
                min(item.source_ids),
                self._source_word_start(
                    item.original, self._source_original_text(item.source_ids, by_id)
                ),
                len(item.source_ids),
            )
        )
        parsed = self._restore_disallowed_omissions(parsed, by_id)
        parsed = self._postprocess_items(parsed)
        return self._assign_item_word_spans(parsed)

    def _restore_missing_source_items(
        self,
        items: List[ScreenSubtitleItem],
        chunk: List[tuple[int, ASRDataSeg]],
    ) -> List[ScreenSubtitleItem]:
        covered_ids = {
            source_id
            for item in items
            for source_id in item.source_ids
        }
        restored = list(items)
        missing_count = 0
        for source_id, seg in chunk:
            if source_id in covered_ids:
                continue
            original = self._normalize_text(seg.text)
            if not original:
                continue
            restored.append(
                ScreenSubtitleItem(
                    source_ids=[source_id],
                    original=original,
                    translated=self._normalize_text(seg.translated_text),
                )
            )
            missing_count += 1

        if missing_count:
            logger.warning(
                "Screen subtitle restored missing source items: %s",
                missing_count,
            )
        return restored

    def _restore_disallowed_omissions(
        self, items: List[ScreenSubtitleItem], by_id: Dict[int, ASRDataSeg]
    ) -> List[ScreenSubtitleItem]:
        source_use_count: Dict[int, int] = {}
        for item in items:
            for source_id in item.source_ids:
                source_use_count[source_id] = source_use_count.get(source_id, 0) + 1

        restored: List[ScreenSubtitleItem] = []
        for item in items:
            source_original = self._source_original_text(item.source_ids, by_id)
            if (
                source_original
                and all(source_use_count.get(source_id, 0) == 1 for source_id in item.source_ids)
                and self._is_word_subsequence(item.original, source_original)
                and not self._has_only_allowed_omissions(item.original, source_original)
            ):
                restored.append(
                    ScreenSubtitleItem(
                        source_ids=item.source_ids,
                        original=source_original,
                        translated=item.translated,
                    )
                )
            else:
                restored.append(item)
        return restored

    @classmethod
    def _has_only_allowed_omissions(cls, text: str, source_text: str) -> bool:
        words = cls._word_tokens(text)
        source_words = cls._word_tokens(source_text)
        allowed_omissions = {
            "right",
            "yeah",
            "yes",
            "yep",
            "exactly",
            "definitely",
            "okay",
            "ok",
            "sure",
        }
        word_index = 0
        omitted: List[str] = []
        for source_word in source_words:
            if word_index < len(words) and source_word == words[word_index]:
                word_index += 1
            else:
                omitted.append(source_word)
        return all(word in allowed_omissions for word in omitted)

    def _items_to_segments(
        self,
        items: List[ScreenSubtitleItem],
        chunk: List[tuple[int, ASRDataSeg]],
    ) -> List[ASRDataSeg]:
        items = self._sort_items_by_word_span(items)
        by_id = {idx: seg for idx, seg in chunk}
        split_counts: Dict[tuple[int, ...], int] = {}
        split_positions: Dict[tuple[int, ...], int] = {}
        for item in items:
            key = tuple(item.source_ids)
            split_counts[key] = split_counts.get(key, 0) + 1

        result: List[ASRDataSeg] = []
        last_end_time: Optional[int] = None
        for item in items:
            source_segments = [by_id[idx] for idx in item.source_ids if idx in by_id]
            if not source_segments:
                continue

            word_timing = self._item_word_timing(item)
            if word_timing:
                start_time, end_time = word_timing
                original = self._text_from_word_span(item.word_start, item.word_end)
            else:
                start_time = source_segments[0].start_time
                end_time = source_segments[-1].end_time
                original = item.original

            key = tuple(item.source_ids)
            if not word_timing and split_counts.get(key, 0) > 1:
                position = split_positions.get(key, 0)
                split_positions[key] = position + 1
                count = split_counts[key]
                span_start = source_segments[0].start_time
                span_end = source_segments[-1].end_time
                duration = max(span_end - span_start, count)
                start_time = span_start + int(duration * position / count)
                end_time = span_start + int(duration * (position + 1) / count)

            if last_end_time is not None and start_time < last_end_time:
                start_time = last_end_time
            if end_time <= start_time:
                end_time = start_time + 500
            last_end_time = end_time

            segment = ASRDataSeg(
                text=original,
                translated_text=item.translated,
                start_time=start_time,
                end_time=end_time,
            )
            segment.subtitle_id = item.subtitle_id
            if item.word_start is not None and item.word_end is not None:
                segment.word_start = item.word_start
                segment.word_end = item.word_end
                if word_timing:
                    segment.stable_word_start_ms = int(word_timing[0])
                    segment.stable_word_end_ms = int(word_timing[1])
            result.append(segment)

        return result

    @staticmethod
    def _sort_items_by_word_span(
        items: List[ScreenSubtitleItem],
    ) -> List[ScreenSubtitleItem]:
        return sorted(
            items,
            key=lambda item: (
                item.word_start is None,
                item.word_start if item.word_start is not None else 10**12,
                min(item.source_ids) if item.source_ids else 10**12,
                item.word_end if item.word_end is not None else 10**12,
            ),
        )

    def _item_word_timing(self, item: ScreenSubtitleItem) -> Optional[tuple[int, int]]:
        if (
            item.word_start is None
            or item.word_end is None
            or not self._active_word_entries
            or item.word_start < 0
            or item.word_end >= len(self._active_word_entries)
            or item.word_end < item.word_start
        ):
            return None
        return (
            self._active_word_entries[item.word_start]["start_time"],
            self._active_word_entries[item.word_end]["end_time"],
        )

    def _text_from_word_span(
        self, word_start: Optional[int], word_end: Optional[int]
    ) -> str:
        if (
            word_start is None
            or word_end is None
            or word_start < 0
            or word_end >= len(self._active_word_entries)
            or word_end < word_start
        ):
            return ""
        text = " ".join(
            self._active_word_entries[index].get("surface")
            or self._active_word_entries[index]["token"]
            for index in range(word_start, word_end + 1)
        )
        return self._normalize_text(text)

    def _realign_segments_to_word_times(
        self, segments: List[ASRDataSeg], word_segments: Sequence[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        entries = self._word_time_entries(word_segments)
        if not entries:
            return segments

        aligned: List[ASRDataSeg] = []
        cursor = 0
        aligned_count = 0
        fallback_count = 0
        last_end_time: Optional[int] = None

        for seg in segments:
            match = self._find_word_time_span(seg.text, entries, cursor)
            if match:
                start_index, end_index = match
                start_time = entries[start_index]["start_time"]
                end_time = entries[end_index]["end_time"]
                cursor = end_index + 1
                aligned_count += 1
            else:
                start_time = seg.start_time
                end_time = seg.end_time
                while cursor < len(entries) and entries[cursor]["end_time"] <= end_time:
                    cursor += 1
                fallback_count += 1

            if last_end_time is not None and start_time < last_end_time:
                if end_time > last_end_time:
                    start_time = last_end_time
                else:
                    start_time = last_end_time
                    end_time = start_time + 300
            if end_time <= start_time:
                end_time = start_time + 300
            last_end_time = end_time

            aligned.append(
                self._copy_segment(
                    seg,
                    start_time=start_time,
                    end_time=end_time,
                )
            )

        logger.info(
            "Screen subtitle word-time realignment: aligned=%s fallback=%s",
            aligned_count,
            fallback_count,
        )
        aligned = self._sort_segments_by_time(aligned)
        aligned = self._restore_missing_word_time_ranges(aligned, entries)
        return aligned

    @staticmethod
    def _sort_segments_by_time(segments: List[ASRDataSeg]) -> List[ASRDataSeg]:
        return sorted(segments, key=lambda seg: (seg.start_time, seg.end_time))

    def _restore_missing_word_time_ranges(
        self,
        segments: List[ASRDataSeg],
        entries: List[Dict],
        min_missing_ms: int = 700,
        max_missing_words: int = 18,
    ) -> List[ASRDataSeg]:
        if not segments or not entries:
            return segments

        restored: List[ASRDataSeg] = []
        restored_count = 0
        cursor = 0
        sorted_segments = self._sort_segments_by_time(segments)

        for seg in sorted_segments:
            while cursor < len(entries) and entries[cursor]["end_time"] <= seg.start_time:
                cursor += 1
            gap_start = cursor
            while cursor < len(entries) and entries[cursor]["start_time"] < seg.start_time:
                cursor += 1
            if gap_start < cursor:
                restored_segments = self._segments_from_missing_word_entries(
                    entries[gap_start:cursor],
                    min_missing_ms=min_missing_ms,
                    max_missing_words=max_missing_words,
                )
                if restored_segments:
                    restored.extend(restored_segments)
                    restored_count += len(restored_segments)

            restored.append(seg)
            while cursor < len(entries) and entries[cursor]["end_time"] <= seg.end_time:
                cursor += 1

        if cursor < len(entries):
            restored_segments = self._segments_from_missing_word_entries(
                entries[cursor:],
                min_missing_ms=min_missing_ms,
                max_missing_words=max_missing_words,
            )
            if restored_segments:
                restored.extend(restored_segments)
                restored_count += len(restored_segments)

        if restored_count:
            logger.warning(
                "Screen subtitle restored missing word-time ranges: %s",
                restored_count,
            )
            restored = self._translate_missing_segments(restored)
            restored = self._align_segment_translation_punctuation(restored)
        return self._sort_segments_by_time(restored)

    def _segments_from_missing_word_entries(
        self,
        entries: Sequence[Dict],
        min_missing_ms: int,
        max_missing_words: int,
    ) -> List[ASRDataSeg]:
        if not entries:
            return []
        duration = entries[-1]["end_time"] - entries[0]["start_time"]
        if duration < min_missing_ms:
            return []
        words = [
            entry.get("surface") or entry.get("token") or ""
            for entry in entries
            if entry.get("surface") or entry.get("token")
        ]
        if not words:
            return []
        result: List[ASRDataSeg] = []
        for start in range(0, len(entries), max_missing_words):
            chunk = entries[start : start + max_missing_words]
            text = self._normalize_text(
                " ".join(entry.get("surface") or entry.get("token") or "" for entry in chunk)
            )
            if not text:
                continue
            result.append(
                ASRDataSeg(
                    text=text,
                    translated_text="",
                    start_time=chunk[0]["start_time"],
                    end_time=chunk[-1]["end_time"],
                )
            )
        return result

    @classmethod
    def _word_time_entries(cls, word_segments: Sequence[ASRDataSeg]) -> List[Dict]:
        entries: List[Dict] = []
        for seg in word_segments:
            surfaces = [match.group(0) for match in cls._word_token_matches(seg.text)]
            tokens = [
                token
                for surface in surfaces
                for token in cls._word_tokens(surface)
            ]
            if not tokens:
                tokens = cls._word_tokens(seg.text)
                surfaces = tokens
            if len(surfaces) != len(tokens):
                surfaces = tokens
            if not tokens:
                continue
            token_count = len(tokens)
            duration = max(seg.end_time - seg.start_time, token_count)
            for index, token in enumerate(tokens):
                start_time = seg.start_time + int(duration * index / token_count)
                end_time = seg.start_time + int(duration * (index + 1) / token_count)
                entries.append(
                    {
                        "token": token,
                        "surface": surfaces[index],
                        "start_time": start_time,
                        "end_time": max(end_time, start_time + 1),
                    }
                )
        return entries

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except Exception:
            return None

    def _payload_words_for_source(self, source_id: int) -> List[Dict]:
        span = self._active_source_word_spans.get(source_id)
        if not span or not self._active_word_entries:
            return []
        start, end = span
        return [
            {"index": index, "word": self._active_word_entries[index]["token"]}
            for index in range(start, min(end + 1, len(self._active_word_entries)))
        ]

    def _map_source_segments_to_word_entries(
        self, segments: Sequence[ASRDataSeg], entries: List[Dict]
    ) -> Dict[int, tuple[int, int]]:
        spans: Dict[int, tuple[int, int]] = {}
        if not segments or not entries:
            return spans

        cursor = 0
        for source_id, seg in enumerate(segments, 1):
            match = self._find_word_time_span(seg.text, entries, cursor)
            if not match:
                while cursor < len(entries) and entries[cursor]["end_time"] <= seg.end_time:
                    cursor += 1
                continue
            start_index, end_index = match
            spans[source_id] = (start_index, end_index)
            cursor = end_index + 1

        logger.info(
            "Screen subtitle source word spans mapped: %s/%s",
            len(spans),
            len(segments),
        )
        return spans

    def _assign_item_word_spans(
        self, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        if not self._active_word_entries or not self._active_source_word_spans:
            return items

        assigned: List[ScreenSubtitleItem] = []
        cursor = 0
        assigned_count = 0
        fallback_count = 0

        for item in items:
            allowed_span = self._source_word_span_for_ids(item.source_ids)
            word_span = None
            if allowed_span and self._valid_item_word_span(item, allowed_span):
                word_span = (item.word_start, item.word_end)
            elif allowed_span:
                word_span = self._find_item_word_span_in_source(
                    item.original, allowed_span, cursor
                )

            if word_span:
                word_start, word_end = word_span
                cursor = max(cursor, word_end + 1)
                assigned_count += 1
            else:
                word_start = None
                word_end = None
                fallback_count += 1

            assigned.append(
                ScreenSubtitleItem(
                    source_ids=item.source_ids,
                    original=item.original,
                    translated=item.translated,
                    word_start=word_start,
                    word_end=word_end,
                    subtitle_id=item.subtitle_id,
                )
            )

        logger.info(
            "Screen subtitle item word spans assigned: assigned=%s fallback=%s",
            assigned_count,
            fallback_count,
        )
        return assigned

    def _text_from_valid_item_word_range(
        self,
        source_ids: List[int],
        word_start: Optional[int],
        word_end: Optional[int],
    ) -> str:
        if (
            not source_ids
            or word_start is None
            or word_end is None
            or not self._active_word_entries
            or not self._active_source_word_spans
        ):
            return ""
        allowed_span = self._source_word_span_for_ids(source_ids)
        if not allowed_span:
            return ""
        allowed_start, allowed_end = allowed_span
        if not (allowed_start <= word_start <= word_end <= allowed_end):
            return ""
        return self._text_from_word_span(word_start, word_end)

    def _source_word_span_for_ids(
        self, source_ids: List[int]
    ) -> Optional[tuple[int, int]]:
        spans = [
            self._active_source_word_spans[source_id]
            for source_id in source_ids
            if source_id in self._active_source_word_spans
        ]
        if not spans:
            return None
        return min(start for start, _ in spans), max(end for _, end in spans)

    def _valid_item_word_span(
        self, item: ScreenSubtitleItem, allowed_span: tuple[int, int]
    ) -> bool:
        if item.word_start is None or item.word_end is None:
            return False
        allowed_start, allowed_end = allowed_span
        if not (allowed_start <= item.word_start <= item.word_end <= allowed_end):
            return False
        item_tokens = self._word_tokens(item.original)
        if not item_tokens:
            return False
        span_tokens = [
            self._active_word_entries[index]["token"]
            for index in range(item.word_start, item.word_end + 1)
        ]
        return span_tokens == item_tokens

    def _find_item_word_span_in_source(
        self, text: str, allowed_span: tuple[int, int], cursor: int
    ) -> Optional[tuple[int, int]]:
        tokens = self._word_tokens(text)
        if not tokens:
            return None

        allowed_start, allowed_end = allowed_span
        search_start = max(allowed_start, min(cursor, allowed_end))
        max_extra_tokens = max(4, len(tokens) // 3)
        candidates = list(range(search_start, allowed_end + 1))
        if search_start > allowed_start:
            candidates.extend(range(allowed_start, search_start))

        best: Optional[tuple[int, int, int]] = None
        for start in candidates:
            if self._active_word_entries[start]["token"] != tokens[0]:
                continue
            pos = start
            matched: List[int] = []
            failed = False
            for token in tokens:
                limit = min(allowed_end + 1, start + len(tokens) + max_extra_tokens + 1)
                while pos < limit and self._active_word_entries[pos]["token"] != token:
                    pos += 1
                if pos >= limit:
                    failed = True
                    break
                matched.append(pos)
                pos += 1
            if failed or not matched:
                continue
            skipped = matched[-1] - matched[0] + 1 - len(tokens)
            score = skipped + abs(matched[0] - search_start)
            if best is None or score < best[0]:
                best = (score, matched[0], matched[-1])
                if score == 0:
                    break

        if best is None:
            return None
        return best[1], best[2]

    @classmethod
    def _find_word_time_span(
        cls, text: str, entries: List[Dict], cursor: int
    ) -> Optional[tuple[int, int]]:
        target_tokens = cls._word_tokens(text)
        if not target_tokens:
            return None

        best: Optional[tuple[int, int, int]] = None
        search_start = max(0, cursor - 3)
        max_start = min(len(entries), cursor + 80)
        max_extra_tokens = max(8, len(target_tokens) // 2)

        for start in range(search_start, max_start):
            if entries[start]["token"] != target_tokens[0]:
                continue
            pos = start
            matched_indices = []
            failed = False
            for token in target_tokens:
                limit = min(len(entries), start + len(target_tokens) + max_extra_tokens + 1)
                while pos < limit and entries[pos]["token"] != token:
                    pos += 1
                if pos >= limit:
                    failed = True
                    break
                matched_indices.append(pos)
                pos += 1
            if failed or not matched_indices:
                continue
            span_len = matched_indices[-1] - matched_indices[0] + 1
            skipped = span_len - len(target_tokens)
            if skipped > max_extra_tokens:
                continue
            score = skipped + abs(start - cursor)
            if best is None or score < best[0]:
                best = (score, matched_indices[0], matched_indices[-1])
                if score == 0:
                    break

        if best is None:
            return None
        return best[1], best[2]

    def _set_chinese_cache_contract(
        self,
        items: Sequence[ScreenSubtitleItem],
    ) -> None:
        """Bind every stable Chinese cache entry to the frozen English timeline."""
        frozen_items = [
            {
                "subtitle_id": str(item.subtitle_id or ""),
                "english": str(item.original or ""),
                "word_start": item.word_start,
                "word_end": item.word_end,
            }
            for item in items
        ]
        self._chinese_cache_contract = {
            "contract_version": STABLE_CHINESE_CACHE_CONTRACT_VERSION,
            "full_english_text_hash": stable_payload_hash(
                [entry["english"] for entry in frozen_items]
            ),
            "frozen_id_word_span_version": FROZEN_ID_WORD_SPAN_CACHE_VERSION,
            "frozen_id_word_span_hash": stable_payload_hash(
                [
                    {
                        "subtitle_id": entry["subtitle_id"],
                        "word_start": entry["word_start"],
                        "word_end": entry["word_end"],
                    }
                    for entry in frozen_items
                ]
            ),
            "semantic_full_translation_prompt_version": (
                SEMANTIC_FULL_TRANSLATION_PROMPT_VERSION
            ),
            "semantic_allocation_prompt_version": SEMANTIC_ALLOCATION_PROMPT_VERSION,
            "fixed_id_allocation_algorithm_version": (
                FIXED_ID_CHINESE_ALLOCATION_ALGORITHM_VERSION
            ),
        }

    @staticmethod
    def _semantic_chinese_prompt_version(cache_task: str) -> str:
        task = str(cache_task or "")
        if task == SEMANTIC_FULL_TRANSLATION_STYLE_RETRY_CACHE_TASK:
            return SEMANTIC_FULL_TRANSLATION_STYLE_RETRY_PROMPT_VERSION
        if task.startswith("screen_subtitle_semantic_full_translation"):
            return SEMANTIC_FULL_TRANSLATION_PROMPT_VERSION
        if task == SEMANTIC_FRAGMENT_ALLOCATION_RETRY_CACHE_TASK:
            return SEMANTIC_FRAGMENT_ALLOCATION_RETRY_PROMPT_VERSION
        if task == SEMANTIC_CHINESE_POLISH_CACHE_TASK:
            return SEMANTIC_CHINESE_POLISH_PROMPT_VERSION
        return SEMANTIC_ALLOCATION_PROMPT_VERSION

    def _semantic_chinese_cache_key(
        self,
        prompt: str,
        payload: Sequence[Dict],
        cache_task: str,
    ) -> str:
        contract = dict(getattr(self, "_chinese_cache_contract", {}) or {})
        if not contract:
            # Direct helper use outside the frozen stable pipeline must never
            # collide with a cache entry created from a verified timeline.
            contract = {
                "contract_version": STABLE_CHINESE_CACHE_CONTRACT_VERSION,
                "full_english_text_hash": stable_payload_hash(list(payload)),
                "frozen_id_word_span_version": "unbound",
                "frozen_id_word_span_hash": stable_payload_hash([]),
                "fixed_id_allocation_algorithm_version": (
                    FIXED_ID_CHINESE_ALLOCATION_ALGORITHM_VERSION
                ),
            }
        contract["cache_task"] = str(cache_task or "")
        contract["translation_prompt_version"] = self._semantic_chinese_prompt_version(
            cache_task
        )
        return self._cache_key(
            prompt,
            [
                {
                    "stable_chinese_cache_contract": contract,
                    "payload": list(payload),
                }
            ],
        )

    @staticmethod
    def _cache_key(prompt: str, payload: Sequence[Dict]) -> str:
        raw = json.dumps({"prompt": prompt, "payload": payload}, ensure_ascii=False)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _postprocess_items(self, items: List[ScreenSubtitleItem]) -> List[ScreenSubtitleItem]:
        result: List[ScreenSubtitleItem] = []
        for item in items:
            item = self._fix_obvious_asr_errors(item)
            result.extend(self._split_long_english_item(item))
        result = self._rebalance_prepositional_continuations(result)
        result = self._merge_required_prepositional_heads(result)
        result = self._merge_dangling_items(result)
        result = self._translate_semantic_subtitle_groups(result)
        result = self._translate_missing_item_translations(result)
        result = [self._align_item_translation_punctuation(item) for item in result]
        result = self._repair_leading_translation_punctuation_items(result)
        return result or items

    @staticmethod
    def _source_original_text(
        source_ids: List[int], by_id: Dict[int, ASRDataSeg]
    ) -> str:
        return " ".join(
            by_id[source_id].text.strip()
            for source_id in source_ids
            if source_id in by_id and by_id[source_id].text.strip()
        ).strip()

    @classmethod
    def _is_word_subsequence(cls, text: str, source_text: str) -> bool:
        words = cls._word_tokens(text)
        source_words = cls._word_tokens(source_text)
        if not words:
            return False
        source_index = 0
        for word in words:
            while source_index < len(source_words) and source_words[source_index] != word:
                source_index += 1
            if source_index >= len(source_words):
                return False
            source_index += 1
        return True

    @classmethod
    def _source_word_start(cls, text: str, source_text: str) -> int:
        words = cls._word_tokens(text)
        source_words = cls._word_tokens(source_text)
        if not words:
            return 10**9
        for start in range(len(source_words)):
            if source_words[start] != words[0]:
                continue
            source_index = start + 1
            matched = True
            for word in words[1:]:
                while source_index < len(source_words) and source_words[source_index] != word:
                    source_index += 1
                if source_index >= len(source_words):
                    matched = False
                    break
                source_index += 1
            if matched:
                return start
        return 10**9

    @classmethod
    def _restore_source_surface(cls, text: str, source_text: str) -> str:
        words = cls._word_tokens(text)
        source_matches = list(cls._word_token_matches(source_text))
        source_words = [
            token
            for match in source_matches
            for token in cls._word_tokens(match.group(0))
        ]
        if not words or not source_words:
            return cls._normalize_text(text)

        for start in range(len(source_words)):
            if source_words[start : start + len(words)] == words:
                start_pos = source_matches[start].start()
                end_pos = source_matches[start + len(words) - 1].end()
                while end_pos < len(source_text) and source_text[end_pos] in ".,!?;:":
                    end_pos += 1
                surface = source_text[start_pos:end_pos].strip()
                return cls._normalize_text(surface)
        return cls._normalize_text(text)

    @staticmethod
    def _word_token_matches(text: str):
        return re.finditer(
            r"[A-Za-z]+(?:[-'’][A-Za-z]+)?|\d+(?:[.,]\d+)?", text or ""
        )

    @staticmethod
    def _word_token_matches(text: str):
        return re.finditer(
            r"[A-Za-z]+(?:[-'’][A-Za-z]+)*(?:[.,!?;:]+)?|\d+(?:[.,]\d+)*(?:%?)(?:[.,!?;:]+)?",
            text or "",
        )

    def _split_long_english_item(self, item: ScreenSubtitleItem) -> List[ScreenSubtitleItem]:
        structural_parts = self._split_structural_phrases(item.original)
        if len(structural_parts) > 1:
            translated_parts = self._split_translated_text(
                item.translated, len(structural_parts)
            )
            if len(translated_parts) != len(structural_parts) or not all(translated_parts):
                translated_parts = self._translate_split_parts(structural_parts)
            return [
                ScreenSubtitleItem(
                    source_ids=item.source_ids,
                    original=part,
                    translated=(
                        translated_parts[index]
                        if index < len(translated_parts)
                        else ""
                    ),
                )
                for index, part in enumerate(structural_parts)
                if part.strip()
            ]

        parts = self._split_english_text(item.original, self.max_english_words)
        if len(parts) <= 1:
            return [item]

        translated_parts = self._split_translated_text(item.translated, len(parts))
        if len(translated_parts) != len(parts) or not all(translated_parts):
            translated_parts = self._translate_split_parts(parts)
        if len(translated_parts) != len(parts):
            translated_parts = self._split_translated_text(item.translated, len(parts))
        return [
            ScreenSubtitleItem(
                source_ids=item.source_ids,
                original=part,
                translated=translated_parts[index] if index < len(translated_parts) else "",
                subtitle_id=item.subtitle_id,
            )
            for index, part in enumerate(parts)
            if part.strip()
        ]

    @classmethod
    def _split_structural_phrases(cls, text: str) -> List[str]:
        text = cls._normalize_text(text)
        match = re.match(
            r"^(.+?\bright\?)\s+(From\s+\d{4}\s+to\s+\d{4},?)$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return [match.group(1).strip(), match.group(2).strip()]
        return [text]

    def _translate_split_parts(self, parts: List[str]) -> List[str]:
        if not parts:
            return []

        cache_key = self._cache_key(
            "split_part_translation",
            [{"original": part, "target_language": self.target_language} for part in parts],
        )
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=self.temperature,
            task="screen_subtitle_split_translation",
        )
        if cache_result:
            try:
                self._llm_cache_used = True
                data = json.loads(cache_result)
                if isinstance(data, list) and len(data) == len(parts):
                    return [str(item).strip() for item in data]
            except Exception:
                pass

        prompt = (
            "Translate each English subtitle line into concise Simplified Chinese. "
            "Use a polished magazine/journalistic video narration style. "
            "Keep exactly the same number of items and order. "
            "Return pure JSON array of strings only."
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(parts, ensure_ascii=False)},
                ],
                temperature=0.2,
                timeout=self.timeout,
            )
            data = json_repair.loads(response.choices[0].message.content)
            if isinstance(data, list) and len(data) == len(parts):
                result = [str(item).strip() for item in data]
                self.cache_manager.set_llm_result(
                    cache_key,
                    json.dumps(result, ensure_ascii=False),
                    self.model,
                    temperature=self.temperature,
                    task="screen_subtitle_split_translation",
                )
                return result
        except Exception as e:
            logger.warning("拆分字幕译文重译失败，回退到本地切分：%s", str(e))
        return []

    @classmethod
    def _strip_trailing_backchannel(cls, item: ScreenSubtitleItem) -> ScreenSubtitleItem:
        original = cls._normalize_text(item.original)
        translated = (item.translated or "").strip()
        original = re.sub(
            r"(\bright\?)\s+right\.\s+",
            r"\1 ",
            original,
            flags=re.IGNORECASE,
        )
        if re.search(r"\bright\?\s*$", original, flags=re.IGNORECASE):
            return ScreenSubtitleItem(
                item.source_ids,
                original,
                translated,
                item.word_start,
                item.word_end,
                item.subtitle_id,
            )

        stripped = re.sub(
            r"(?:[,;:]\s*)?\b(?:right|yeah|yes|yep|exactly|okay|ok|sure)\.?\s*$",
            "",
            original,
            flags=re.IGNORECASE,
        ).strip()
        if stripped and stripped != original:
            translated = re.sub(
                r"(?:[，,]\s*)?(?:对吧|对|是吧|是的|没错|嗯|好的|好吧)[。.!！?？…]*\s*$",
                "",
                translated,
            ).strip()
            if stripped[-1] not in ".!?":
                stripped += "."
            return ScreenSubtitleItem(
                item.source_ids,
                stripped,
                translated,
                item.word_start,
                item.word_end,
                item.subtitle_id,
            )
        return ScreenSubtitleItem(
            item.source_ids,
            original,
            translated,
            item.word_start,
            item.word_end,
            item.subtitle_id,
        )

    @classmethod
    def _strip_leading_backchannel(cls, item: ScreenSubtitleItem) -> ScreenSubtitleItem:
        original = cls._normalize_text(item.original)
        translated = (item.translated or "").strip()
        stripped = re.sub(
            r"^(?:yeah|right|yes|yep|exactly|okay|ok|sure)[,.\s]+(?=(?:and|but|so|because|today|we|it|this|that|the|there|in|on|for|to)\b)",
            "",
            original,
            flags=re.IGNORECASE,
        ).strip()
        if stripped and stripped != original:
            translated = re.sub(
                r"^(?:是的|对|对的|没错|嗯|好的|好吧)[，,。.\s]+",
                "",
                translated,
            ).strip()
            if stripped[0].islower():
                stripped = stripped[0].upper() + stripped[1:]
            return ScreenSubtitleItem(
                item.source_ids,
                stripped,
                translated,
                item.word_start,
                item.word_end,
                item.subtitle_id,
            )
        return ScreenSubtitleItem(
            item.source_ids,
            original,
            translated,
            item.word_start,
            item.word_end,
            item.subtitle_id,
        )

    @classmethod
    def _remove_embedded_backchannels(cls, item: ScreenSubtitleItem) -> ScreenSubtitleItem:
        original = cls._normalize_text(item.original)
        translated = (item.translated or "").strip()
        cleaned = re.sub(
            r"\s+\b(?:yeah|right|yes|yep|exactly|okay|ok|sure)\.\s+(?=[A-Z])",
            " ",
            original,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned != original:
            translated = re.sub(
                r"(?:是的|对|对的|没错|嗯|好的|好吧)[，,。.\s]*",
                "",
                translated,
            ).strip()
        return ScreenSubtitleItem(
            item.source_ids,
            cleaned,
            translated,
            item.word_start,
            item.word_end,
            item.subtitle_id,
        )

    @staticmethod
    def _fix_obvious_asr_errors(item: ScreenSubtitleItem) -> ScreenSubtitleItem:
        original = item.original
        original = re.sub(r"\bU\.\s*S\.", "U.S.", original)
        original = re.sub(r"\bU\.\s*K\.", "U.K.", original)
        original = re.sub(r"\bA\.\s*I\.", "AI", original)
        translated = item.translated or ""
        return ScreenSubtitleItem(
            item.source_ids,
            original,
            translated,
            item.word_start,
            item.word_end,
            item.subtitle_id,
        )

    def _merge_dangling_items(
        self, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        result: List[ScreenSubtitleItem] = []
        for item in items:
            merged_text = f"{result[-1].original} {item.original}" if result else item.original
            is_tail_dangling_word = self._is_tail_dangling_word(item.original)
            max_words_for_merge = (
                max(self.max_english_words, 16)
                if is_tail_dangling_word
                else self.max_english_words
            )
            if (
                result
                and self._word_count(item.original) <= 2
                and not self._looks_like_time_range(item.original)
                and self._word_count(merged_text) <= max_words_for_merge
                and self._can_merge_items(result[-1], item)
                and not (
                    getattr(result[-1], "subtitle_id", None)
                    and getattr(item, "subtitle_id", None)
                )
            ):
                previous = result[-1]
                result[-1] = ScreenSubtitleItem(
                    source_ids=sorted(set(previous.source_ids + item.source_ids)),
                    original=self._normalize_text(
                        f"{previous.original.rstrip()} {item.original.lstrip()}"
                    ),
                    translated=self._merge_translations(
                        previous.translated, item.translated
                    ),
                    subtitle_id=previous.subtitle_id or item.subtitle_id,
                )
            else:
                if (
                    result
                    and is_tail_dangling_word
                    and self._can_merge_items(result[-1], item)
                    and not (
                        getattr(result[-1], "subtitle_id", None)
                        and getattr(item, "subtitle_id", None)
                    )
                ):
                    rebalanced = self._rebalance_tail_dangling_merge(result[-1], item)
                    if rebalanced:
                        result[-1] = rebalanced[0]
                        result.extend(rebalanced[1:])
                        continue
                result.append(item)
        return result

    @staticmethod
    def _is_tail_dangling_word(text: str) -> bool:
        clean = re.sub(r"[.,!?;:\s]+$", "", text or "").lower()
        return clean in {
            "too",
            "though",
            "either",
            "also",
            "instead",
            "anyway",
        }

    def _rebalance_tail_dangling_merge(
        self, previous: ScreenSubtitleItem, dangling: ScreenSubtitleItem
    ) -> List[ScreenSubtitleItem]:
        merged_original = self._normalize_text(
            f"{previous.original.rstrip()} {dangling.original.lstrip()}"
        )
        split_match = re.search(
            r"\s+(?=(?:but|and|which|that|because|for|with)\b)",
            merged_original,
            flags=re.IGNORECASE,
        )
        if not split_match:
            return []

        candidates = [
            (match.start(), match.group(1).lower())
            for match in re.finditer(
                r"\s+(?=(but|because|which|that|and|for|with)\b)",
                merged_original,
                flags=re.IGNORECASE,
            )
        ]
        best_parts: Optional[tuple[str, str]] = None
        best_score: Optional[tuple[int, int]] = None
        marker_priority = {
            "but": 0,
            "because": 0,
            "which": 1,
            "that": 1,
            "and": 2,
            "for": 3,
            "with": 3,
        }
        for cut, marker in candidates:
            left = merged_original[:cut].strip()
            right = merged_original[cut:].strip()
            left_count = self._word_count(left)
            right_count = self._word_count(right)
            if not left or not right:
                continue
            if left_count > self.max_english_words or right_count > self.max_english_words:
                continue
            score = (marker_priority.get(marker, 4), abs(left_count - right_count))
            if best_score is None or score < best_score:
                best_score = score
                best_parts = (left, right)

        if not best_parts:
            return []

        parts = [best_parts[0], best_parts[1]]
        translations = self._translate_split_parts(parts)
        if len(translations) != 2:
            translations = self._split_translated_text(
                self._merge_translations(previous.translated, dangling.translated),
                2,
            )
        source_ids = sorted(set(previous.source_ids + dangling.source_ids))
        return [
            ScreenSubtitleItem(
                source_ids=previous.source_ids,
                original=parts[0],
                translated=translations[0] if len(translations) > 0 else "",
                subtitle_id=previous.subtitle_id,
            ),
            ScreenSubtitleItem(
                source_ids=source_ids,
                original=parts[1],
                translated=translations[1] if len(translations) > 1 else "",
                subtitle_id=dangling.subtitle_id,
            ),
        ]

    @staticmethod
    def _looks_like_time_range(text: str) -> bool:
        return bool(
            re.match(
                r"^(?:from\s+)?\d{4}\s+(?:to|through|-)\s+\d{4}[.,]?$",
                (text or "").strip(),
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _can_merge_items(left: ScreenSubtitleItem, right: ScreenSubtitleItem) -> bool:
        if not left.source_ids or not right.source_ids:
            return False
        return min(right.source_ids) - max(left.source_ids) <= 1

    @staticmethod
    def _merge_translations(left: str, right: str) -> str:
        left = (left or "").strip()
        right = (right or "").strip()
        if left and right:
            return f"{left}{right}"
        return left or right

    def _translate_semantic_subtitle_groups(
        self, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        groups = self._semantic_translation_groups(items)
        if not groups:
            return items

        full_translations = self._translate_semantic_group_full_translations(groups)
        self._last_semantic_full_translations = dict(full_translations)
        self._last_semantic_group_audit_contexts = self._semantic_group_audit_contexts(
            groups, full_translations
        )
        self._allocation_isolation_before = self._allocation_isolation_snapshot(
            stage="before_allocation",
            source_segments=list(getattr(self, "_active_source_segments_by_id", {}).values()),
            items=items,
            semantic_groups=groups,
            full_translations=full_translations,
        )
        allocated = self._allocate_semantic_group_translations(groups, full_translations)
        if allocated:
            allocated = self._polish_semantic_group_translations(
                groups, full_translations, allocated
            )
            return self._apply_semantic_group_translations(items, groups, allocated)

        logger.warning("语义组两阶段翻译失败，保留冻结英文并交由结构门禁阻止渲染")
        return items

    def _polish_semantic_group_translations(
        self,
        groups: Sequence[Dict],
        full_translations: Dict[int, str],
        allocations: Dict[int, Dict[str, str]],
    ) -> Dict[int, Dict[str, str]]:
        """Polish Chinese per fixed semantic group without touching English or timing."""
        if not self.enable_chinese_polish:
            return allocations
        if not hasattr(self, "_chinese_polish_log"):
            self._chinese_polish_log = []

        candidates: List[tuple[int, int, Dict, List[str]]] = []
        groups_by_id = {
            int(group.get("id") or 0): group
            for group in groups
            if str(group.get("id", "")).isdigit()
        }
        for group_id, group in groups_by_id.items():
            current = allocations.get(group_id, {})
            subtitle_parts = []
            for offset, item in enumerate(group.get("items") or [], 1):
                subtitle_id = self._item_subtitle_id(
                    item, int(group.get("start_index") or 0) + offset
                )
                timing = self._item_word_timing(item)
                subtitle_parts.append(
                    {
                        "subtitle_id": subtitle_id,
                        "english": item.original,
                        "duration_ms": max(0, timing[1] - timing[0]) if timing else None,
                        "max_zh_chars": self.max_cjk_chars,
                        **self._chinese_display_budget(
                            max(0, timing[1] - timing[0]) if timing else None
                        ),
                        "current_zh": self._normalize_text(current.get(subtitle_id, "")),
                    }
                )
            expected_ids = [part["subtitle_id"] for part in subtitle_parts]
            if set(current) != set(expected_ids):
                self._chinese_polish_log.append(
                    {
                        "semantic_group_id": f"G{group_id:04d}",
                        "decision": "skipped",
                        "reason": "current_allocation_id_mismatch",
                    }
                )
                continue
            entry = {
                "id": group_id,
                "polish_prompt_version": SEMANTIC_CHINESE_POLISH_PROMPT_VERSION,
                "full_english": " ".join(item.original for item in group["items"]),
                "full_translation": full_translations.get(group_id, ""),
                "subtitle_parts": subtitle_parts,
            }
            validation = self._validate_group_chinese_allocation(entry, current)
            strong_codes = {
                "group_allocation_information_omission",
                "adjacent_chinese_semantic_duplication",
                "entity_allocation_mismatch",
                "number_allocation_mismatch",
                "negation_allocation_mismatch",
                "cross_subtitle_predicate_break",
                "translation_group_cardinality_mismatch",
                "unnatural_chinese_fragment",
            }
            matched_codes = [
                code for code in validation.get("issue_codes") or [] if code in strong_codes
            ]
            matched_codes.extend(
                code
                for code in self._chinese_polish_risk_codes(entry, current)
                if code not in matched_codes
            )
            if not matched_codes:
                continue
            score = sum(
                3 if code != "unnatural_chinese_fragment" else 1
                for code in matched_codes
            )
            candidates.append((score, group_id, entry, matched_codes))

        # The optional polish pass is deliberately selective.  It targets only
        # groups with structural evidence of a bad allocation, then applies a
        # fixed cap so long-form jobs cannot turn into a third full translation.
        candidates.sort(key=lambda item: (-item[0], item[1]))
        payload: List[Dict] = []
        for _, group_id, entry, matched_codes in candidates[:MAX_SELECTIVE_CHINESE_POLISH_GROUPS]:
            payload.append(entry)
            self._chinese_polish_log.append(
                {
                    "semantic_group_id": f"G{group_id:04d}",
                    "decision": "selected",
                    "reason": "high_confidence_allocation_issue",
                    "issue_codes": matched_codes,
                }
            )
        for _, group_id, _, matched_codes in candidates[MAX_SELECTIVE_CHINESE_POLISH_GROUPS:]:
            self._chinese_polish_log.append(
                {
                    "semantic_group_id": f"G{group_id:04d}",
                    "decision": "skipped",
                    "reason": "selective_polish_limit",
                    "issue_codes": matched_codes,
                }
            )

        result = {group_id: dict(value) for group_id, value in allocations.items()}
        prompt = self._compose_prompt(SEMANTIC_CHINESE_POLISH_PROMPT)
        for payload_chunk in self._semantic_allocation_payload_chunks(payload):
            data = self._request_semantic_translation_allocation(
                prompt,
                payload_chunk,
                cache_task=SEMANTIC_CHINESE_POLISH_CACHE_TASK,
            )
            if data is None:
                self._chinese_polish_log.append(
                    {"decision": "batch_skipped", "reason": "request_failed"}
                )
                continue
            polished, complete, errors, _ = self._parse_allocation_chunk_data_isolated(
                payload_chunk, groups_by_id, data
            )
            if errors or not complete:
                self._chinese_polish_log.append(
                    {
                        "decision": "batch_skipped",
                        "reason": "response_structure_invalid",
                        "error_codes": sorted(
                            {str(error.get("code") or "invalid") for error in errors}
                        ),
                    }
                )
                continue
            for entry in payload_chunk:
                group_id = int(entry["id"])
                current = result.get(group_id, {})
                candidate = polished.get(group_id, {})
                validation = self._validate_group_chinese_allocation(entry, candidate)
                expected_ids = [part["subtitle_id"] for part in entry["subtitle_parts"]]
                current_validation = self._validate_group_chinese_allocation(
                    entry, current
                )
                candidate_decision = self._decide_id_bound_allocation_candidate(
                    original_allocation=current,
                    candidate_allocation=candidate,
                    group_context=entry,
                    original_validation=current_validation,
                    candidate_validation=validation,
                    candidate_source="polish",
                    require_high_confidence_fix=False,
                )
                comparison = candidate_decision["quality_comparison"]
                if not candidate_decision["accepted"]:
                    self._chinese_polish_log.append(
                        {
                            "semantic_group_id": f"G{group_id:04d}",
                            "decision": "rejected",
                            "reason": "validation_failed" if not validation["valid"] else "quality_regressed",
                            "issue_codes": list(validation.get("issue_codes") or []),
                            "quality_comparison": comparison,
                        }
                    )
                    continue
                if candidate != current:
                    result[group_id] = candidate
                    self._chinese_polish_log.append(
                        {
                            "semantic_group_id": f"G{group_id:04d}",
                            "decision": "applied",
                            "subtitle_ids": expected_ids,
                            "before": current,
                            "after": candidate,
                            "quality_comparison": comparison,
                        }
                    )
        return result

    def _chinese_polish_risk_codes(
        self,
        entry: Dict,
        allocation: Dict[str, str],
    ) -> List[str]:
        """Identify a small set of groups where fixed-ID Chinese needs review.

        This is deliberately a selection signal for the optional polish pass,
        not a generation failure or an automatic rewrite trigger.
        """
        parts = list(entry.get("subtitle_parts") or [])
        if len(parts) < 3:
            return []
        english = self._normalize_text(str(entry.get("full_english") or "")).lower()
        chinese_parts = [
            self._normalize_text(str((allocation or {}).get(part.get("subtitle_id"), "")))
            for part in parts
        ]
        if not all(chinese_parts):
            return []

        comma_count = english.count(",") + english.count(";")
        comparison_or_source_list = bool(
            re.search(r"\b(?:against|between|from|including|such as|compared?)\b", english)
        )
        continued_list_shape = sum(
            1 for text in chinese_parts[:-1] if text.rstrip().endswith(("，", "、", "：", "——"))
        ) >= 1
        if comma_count >= 2 and comparison_or_source_list and continued_list_shape:
            return ["complex_enumeration_or_comparison_allocation"]
        return []

    def _translate_semantic_group_full_translations(
        self, groups: Sequence[Dict]
    ) -> Dict[int, str]:
        payload = [
            {
                "id": group["id"],
                "full_english": " ".join(item.original for item in group["items"]),
                "current_translation": self._merge_group_translation(group["items"]),
            }
            for group in groups
        ]
        prompt = self._compose_prompt(SEMANTIC_FULL_TRANSLATION_PROMPT)
        result: Dict[int, str] = {}
        payload_chunks = self._semantic_allocation_payload_chunks(payload)
        cache_hits = 0
        self._emit_progress_event(
            "full_translation",
            completed=0,
            total=len(payload_chunks),
            cache_hits=0,
            retries=0,
        )
        for batch_index, payload_chunk in enumerate(payload_chunks, 1):
            data = self._request_semantic_full_translation_chunk(
                prompt,
                payload_chunk,
                cache_task=SEMANTIC_FULL_TRANSLATION_CACHE_TASK,
            )
            result.update(self._semantic_full_translations_from_response(data))
            latest = self._last_llm_raw_returns[-1] if self._last_llm_raw_returns else {}
            cache_hits += int(
                bool(
                    latest.get("task") == SEMANTIC_FULL_TRANSLATION_CACHE_TASK
                    and latest.get("cache_hit")
                )
            )
            self._emit_progress_event(
                "full_translation",
                completed=batch_index,
                total=len(payload_chunks),
                cache_hits=cache_hits,
                retries=0,
            )

        missing_ids = [int(entry["id"]) for entry in payload if int(entry["id"]) not in result]
        if missing_ids:
            logger.warning("语义组完整翻译缺失，按单组重试: %s", missing_ids)
        payload_by_id = {int(entry["id"]): entry for entry in payload}
        for group_id in missing_ids:
            retry_payload = [payload_by_id[group_id]]
            data = self._request_semantic_full_translation_chunk(
                prompt,
                retry_payload,
                cache_task=f"{SEMANTIC_FULL_TRANSLATION_CACHE_TASK}_retry",
            )
            result.update(self._semantic_full_translations_from_response(data))
            self._emit_progress_event(
                "full_translation",
                completed=len(payload_chunks),
                total=len(payload_chunks),
                cache_hits=cache_hits,
                retries=1,
                retry_group_id=group_id,
            )

        result = self._retry_full_translations_for_em_dash_style(
            payload_by_id=payload_by_id,
            full_translations=result,
        )

        final_missing_ids = [int(entry["id"]) for entry in payload if int(entry["id"]) not in result]
        groups_by_id = {
            int(group.get("id") or 0): group
            for group in groups
            if str(group.get("id", "")).isdigit()
        }
        for group_id in final_missing_ids:
            group = groups_by_id.get(group_id)
            expected_ids = self._group_expected_subtitle_ids(group) if group else []
            self._record_translation_structure_error(
                "translation_group_cardinality_mismatch",
                group_id=group_id,
                expected_ids=expected_ids,
                returned_ids=[],
                missing_ids=expected_ids,
                message="LLM omitted semantic group full_translation after retry.",
            )
        return result

    @staticmethod
    def _full_translation_em_dash_findings(translation: str) -> List[Dict]:
        """Report only em-dash style risks; lexical hyphens are intentionally ignored."""
        text = (translation or "").strip()
        dash_runs = re.findall(r"—+", text)
        if not dash_runs:
            return []

        findings: List[Dict] = []
        if text.startswith("—") or text.endswith("—"):
            findings.append(
                {
                    "code": "em_dash_at_translation_boundary",
                    "em_dash_runs": len(dash_runs),
                }
            )
        if len(dash_runs) > 1:
            findings.append(
                {
                    "code": "excessive_em_dash_usage",
                    "em_dash_runs": len(dash_runs),
                }
            )
        return findings

    @classmethod
    def _full_translation_em_dash_style_score(cls, translation: str) -> int:
        findings = cls._full_translation_em_dash_findings(translation)
        if not findings:
            return 0
        dash_runs = len(re.findall(r"—+", (translation or "").strip()))
        boundary_count = sum(
            1 for finding in findings if finding.get("code") == "em_dash_at_translation_boundary"
        )
        return dash_runs + boundary_count * 2

    def _full_translation_style_candidate_regressions(
        self,
        english: str,
        original_translation: str,
        candidate_translation: str,
    ) -> List[str]:
        candidate = self._normalize_text(candidate_translation)
        original = self._normalize_text(original_translation)
        if not candidate or not re.search(r"[\u4e00-\u9fff]", candidate):
            return ["candidate_not_chinese_translation"]

        regressions: List[str] = []
        for anchor in self._build_group_allocation_anchors(english):
            anchor_type = str(anchor.get("type") or "")
            value = str(anchor.get("value") or "")
            if not value:
                continue
            if self._allocation_anchor_present(value, anchor_type, original) and not self._allocation_anchor_present(
                value, anchor_type, candidate
            ):
                regressions.append(f"lost_{anchor_type}_anchor:{value}")
        return list(dict.fromkeys(regressions))

    def _retry_full_translations_for_em_dash_style(
        self,
        *,
        payload_by_id: Dict[int, Dict],
        full_translations: Dict[int, str],
    ) -> Dict[int, str]:
        """Retry only high-signal em-dash style violations without touching frozen inputs."""
        if not hasattr(self, "_last_full_translation_style_retry_log"):
            self._last_full_translation_style_retry_log = []

        result = dict(full_translations)
        retry_prompt = self._compose_prompt(SEMANTIC_FULL_TRANSLATION_STYLE_RETRY_PROMPT)
        for group_id in sorted(result):
            original_translation = result[group_id]
            original_findings = self._full_translation_em_dash_findings(original_translation)
            original_score = self._full_translation_em_dash_style_score(original_translation)
            if not original_findings:
                continue

            original_payload = payload_by_id.get(int(group_id))
            if not original_payload:
                continue
            retry_payload = dict(original_payload)
            retry_payload["current_translation"] = original_translation
            data = self._request_semantic_full_translation_chunk(
                retry_prompt,
                [retry_payload],
                cache_task=SEMANTIC_FULL_TRANSLATION_STYLE_RETRY_CACHE_TASK,
            )
            candidate_translation = self._semantic_full_translations_from_response(data).get(int(group_id), "")
            candidate_findings = self._full_translation_em_dash_findings(candidate_translation)
            candidate_score = self._full_translation_em_dash_style_score(candidate_translation)
            regressions = self._full_translation_style_candidate_regressions(
                str(original_payload.get("full_english") or ""),
                original_translation,
                candidate_translation,
            )
            rejection_reasons: List[str] = list(regressions)
            if not candidate_translation:
                rejection_reasons.append("style_retry_missing_translation")
            if candidate_score >= original_score:
                rejection_reasons.append("em_dash_style_not_improved")

            accepted = not rejection_reasons
            self._last_full_translation_style_retry_log.append(
                {
                    "semantic_group_id": f"G{int(group_id):04d}",
                    "cache_task": SEMANTIC_FULL_TRANSLATION_STYLE_RETRY_CACHE_TASK,
                    "original_translation": original_translation,
                    "candidate_translation": candidate_translation,
                    "original_style_findings": original_findings,
                    "candidate_style_findings": candidate_findings,
                    "original_style_score": original_score,
                    "candidate_style_score": candidate_score,
                    "accepted": accepted,
                    "decision": "accept_style_retry" if accepted else "keep_original",
                    "rejection_reasons": rejection_reasons,
                }
            )
            if accepted:
                result[int(group_id)] = candidate_translation
        return result

    def _request_semantic_full_translation_chunk(
        self,
        prompt: str,
        payload: Sequence[Dict],
        *,
        cache_task: str,
    ) -> Optional[object]:
        cache_key = self._semantic_chinese_cache_key(prompt, payload, cache_task)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=0.2,
            task=cache_task,
        )
        started = time.perf_counter()
        try:
            if cache_result:
                self._llm_cache_used = True
                self._record_llm_cache_stat(cache_task, True)
                data = json.loads(cache_result)
            else:
                self._record_llm_cache_stat(cache_task, False)
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.2,
                    timeout=self.timeout,
                )
                data = json_repair.loads(response.choices[0].message.content)
                self.cache_manager.set_llm_result(
                    cache_key,
                    json.dumps(data, ensure_ascii=False),
                    self.model,
                    temperature=0.2,
                    task=cache_task,
                )
            elapsed = time.perf_counter() - started
            self._last_llm_raw_returns.append(
                {
                    "task": cache_task,
                    "data": data,
                    "expected_group_ids": [entry.get("id") for entry in payload],
                    "cache_hit": bool(cache_result),
                    "elapsed_seconds": round(elapsed, 3),
                }
            )
            logger.info(
                "Semantic full translation batch completed: task=%s groups=%s cache_hit=%s elapsed=%.3fs",
                cache_task,
                len(payload),
                bool(cache_result),
                elapsed,
            )
            return data
        except Exception as e:
            logger.warning("语义组完整翻译失败: %s", str(e))
            return None

    def _semantic_full_translations_from_response(
        self,
        data: Optional[object],
    ) -> Dict[int, str]:
        if data is None:
            return {}
        groups_data = data.get("groups", []) if isinstance(data, dict) else data
        return self._semantic_full_translations_from_groups_data(
            groups_data if isinstance(groups_data, list) else []
        )

    @staticmethod
    def _semantic_full_translations_from_groups_data(
        groups_data: Sequence[Dict],
    ) -> Dict[int, str]:
        result: Dict[int, str] = {}
        for group in groups_data:
            if not isinstance(group, dict) or not str(group.get("id", "")).isdigit():
                continue
            translated = str(group.get("full_translation", "")).strip()
            if translated:
                result[int(group["id"])] = translated
        return result

    def _allocate_semantic_group_translations(
        self, groups: Sequence[Dict], full_translations: Dict[int, str]
    ) -> Dict[int, Dict[str, str]]:
        if not full_translations:
            return {}
        payload = []
        allocation_entries = []
        direct_allocations: Dict[int, Dict[str, str]] = {}
        for group in groups:
            full_translation = full_translations.get(group["id"], "")
            subtitle_parts = []
            for offset, item in enumerate(group["items"], 1):
                timing = self._item_word_timing(item)
                duration_ms = (
                    max(0, timing[1] - timing[0])
                    if timing
                    else None
                )
                subtitle_parts.append(
                    {
                        "subtitle_id": self._item_subtitle_id(
                            item,
                            int(group.get("start_index") or 0) + offset,
                        ),
                        "english": item.original,
                        "duration_ms": duration_ms,
                        "max_zh_chars": self.max_cjk_chars,
                        **self._chinese_display_budget(duration_ms),
                    }
                )
            entry = {
                "id": group["id"],
                "allocation_prompt_version": SEMANTIC_ALLOCATION_PROMPT_VERSION,
                "full_english": " ".join(item.original for item in group["items"]),
                "full_translation": full_translation,
                "subtitle_parts": subtitle_parts,
            }
            allocation_entries.append(entry)
            if not full_translation:
                expected_ids = [str(part["subtitle_id"]) for part in subtitle_parts]
                self._record_translation_structure_error(
                    "translation_group_cardinality_mismatch",
                    group_id=int(group["id"]),
                    expected_ids=expected_ids,
                    missing_ids=expected_ids,
                    message="Semantic full translation is missing for the fixed-ID group.",
                )
                self._record_allocation_quality_unresolved(
                    entry,
                    {},
                    {"issue_codes": ["translation_group_cardinality_mismatch"]},
                    "authoritative_full_translation_missing",
                )
                # A missing upstream translation blocks its own IDs during final
                # validation, but must not erase completed allocations for other
                # frozen groups.
                continue
            if len(subtitle_parts) != 1:
                payload.append(entry)
                continue

            # A one-cue group has no allocation boundary to decide.  The
            # approved group translation is the only lossless, ID-bound
            # result, so do not spend a second LLM request paraphrasing it.
            subtitle_id = str(subtitle_parts[0]["subtitle_id"])
            direct_allocation = {subtitle_id: full_translation}
            validation = self._validate_group_chinese_allocation(entry, direct_allocation)
            self._last_allocation_validation.append(validation)
            if not validation["valid"]:
                self._record_allocation_quality_unresolved(
                    entry,
                    direct_allocation,
                    validation,
                    "authoritative_single_cue_allocation_invalid",
                )
                # This group has no allocation boundary, but its failure must
                # never discard already valid fixed-ID allocations from other
                # groups. Final ID validation owns the render block for this
                # one unresolved cue.
                continue
            direct_allocations[int(group["id"])] = direct_allocation
            self._last_allocation_final.append(
                {
                    "semantic_group_id": f"G{int(group['id']):04d}",
                    "subtitle_ids": [subtitle_id],
                    "allocation": dict(direct_allocation),
                    "source": "authoritative_full_translation",
                }
            )

        self._last_allocation_inputs.extend(allocation_entries)
        result: Dict[int, Dict[str, str]] = dict(direct_allocations)
        if not payload:
            self._record_allocation_runtime_stat("batch_size", self.allocation_batch_size)
            self._record_allocation_runtime_stat("batch_count", 0)
            self._record_allocation_runtime_stat("pending_batch_count", 0)
            self._record_allocation_runtime_stat("cached_batch_count", 0)
            self._record_allocation_runtime_stat("actual_max_workers", 0)
            self._emit_progress_event(
                "allocation",
                completed=0,
                total=0,
                cache_hits=0,
                retries=0,
                authoritative_single_cue_groups=len(direct_allocations),
            )
            return result
        expected_groups_by_id = {
            int(group.get("id") or 0): group
            for group in groups
            if str(group.get("id", "")).isdigit()
        }
        prompt = self._compose_prompt(SEMANTIC_TRANSLATION_ALLOCATION_PROMPT)
        payload_chunks = self._semantic_allocation_payload_chunks(payload)
        if self.allocation_max_concurrency > 1 and len(payload_chunks) > 1:
            result.update(self._allocate_semantic_group_translations_concurrent(
                prompt,
                payload_chunks,
                expected_groups_by_id,
            ))
            return result
        self._record_allocation_runtime_stat("batch_size", self.allocation_batch_size)
        self._record_allocation_runtime_stat("batch_count", len(payload_chunks))
        self._record_allocation_runtime_stat("pending_batch_count", len(payload_chunks))
        self._record_allocation_runtime_stat("cached_batch_count", 0)
        self._record_allocation_runtime_stat("actual_max_workers", 1)
        logger.info(
            "Semantic allocation batches: total=%s pending=%s cached=0 configured_concurrency=%s actual_workers=1 batch_size=%s",
            len(payload_chunks),
            len(payload_chunks),
            self.allocation_max_concurrency,
            self.allocation_batch_size,
        )
        cache_hits = 0
        retries = 0
        self._emit_progress_event(
            "allocation",
            completed=0,
            total=len(payload_chunks),
            cache_hits=cache_hits,
            retries=retries,
            pending_batches=len(payload_chunks),
            configured_concurrency=self.allocation_max_concurrency,
            actual_workers=1,
        )
        for batch_id, payload_chunk in enumerate(payload_chunks, 1):
            chunk_result, complete, data = self._request_and_parse_allocation_chunk(
                prompt,
                payload_chunk,
                expected_groups_by_id,
            )
            latest = self._last_allocation_raw_returns[-1] if self._last_allocation_raw_returns else {}
            cache_hits += int(bool(latest.get("cache_hit")))
            if data is None:
                self._record_omitted_allocation_groups(
                    payload_chunk,
                    expected_groups_by_id,
                    {},
                )
                continue
            if not complete:
                retries += 1
                chunk_result, complete = self._retry_incomplete_allocation_chunk(
                    prompt,
                    payload_chunk,
                    expected_groups_by_id,
                )
            chunk_result = self._retry_quality_failed_group_allocations(
                prompt,
                payload_chunk,
                expected_groups_by_id,
                chunk_result,
            )
            result.update(chunk_result)
            if not complete:
                self._record_omitted_allocation_groups(
                    payload_chunk,
                    expected_groups_by_id,
                    chunk_result,
                )
            self._emit_progress_event(
                "allocation",
                completed=batch_id,
                total=len(payload_chunks),
                cache_hits=cache_hits,
                retries=retries,
                batch_id=batch_id,
                pending_batches=max(0, len(payload_chunks) - batch_id),
                configured_concurrency=self.allocation_max_concurrency,
                actual_workers=1,
            )
        return result

    def _allocate_semantic_group_translations_concurrent(
        self,
        prompt: str,
        payload_chunks: Sequence[Sequence[Dict]],
        expected_groups_by_id: Dict[int, Dict],
    ) -> Dict[int, Dict[str, str]]:
        results_by_batch: Dict[int, AllocationBatchResult] = {}
        pending: List[tuple[int, Sequence[Dict]]] = []

        for batch_id, payload_chunk in enumerate(payload_chunks, 1):
            cached = self._load_cached_allocation_batch(
                prompt,
                payload_chunk,
                expected_groups_by_id,
                batch_id=batch_id,
                cache_task=SEMANTIC_ALLOCATION_CACHE_TASK,
            )
            if cached is None:
                pending.append((batch_id, payload_chunk))
            else:
                results_by_batch[batch_id] = cached

        max_workers = max(1, min(self.allocation_max_concurrency, len(pending)))
        self._record_allocation_runtime_stat("batch_size", self.allocation_batch_size)
        self._record_allocation_runtime_stat("batch_count", len(payload_chunks))
        self._record_allocation_runtime_stat("pending_batch_count", len(pending))
        self._record_allocation_runtime_stat("cached_batch_count", len(results_by_batch))
        self._record_allocation_runtime_stat("actual_max_workers", max_workers if pending else 0)
        logger.info(
            "Semantic allocation batches: total=%s pending=%s cached=%s configured_concurrency=%s actual_workers=%s batch_size=%s",
            len(payload_chunks),
            len(pending),
            len(results_by_batch),
            self.allocation_max_concurrency,
            max_workers if pending else 0,
            self.allocation_batch_size,
        )
        self._emit_progress_event(
            "allocation",
            completed=len(results_by_batch),
            total=len(payload_chunks),
            cache_hits=len(results_by_batch),
            retries=0,
            pending_batches=len(pending),
            configured_concurrency=self.allocation_max_concurrency,
            actual_workers=max_workers if pending else 0,
        )
        if pending:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self._request_and_parse_allocation_chunk_uncached,
                        prompt,
                        payload_chunk,
                        expected_groups_by_id,
                        batch_id=batch_id,
                        cache_task=SEMANTIC_ALLOCATION_CACHE_TASK,
                    ): (batch_id, payload_chunk)
                    for batch_id, payload_chunk in pending
                }
                for future in as_completed(futures):
                    batch_id, payload_chunk = futures[future]
                    try:
                        batch_result = future.result()
                    except Exception as e:
                        batch_result = AllocationBatchResult(
                            batch_id=batch_id,
                            expected_ids=[int(entry.get("id") or 0) for entry in payload_chunk],
                            translations={},
                            complete=False,
                            data=None,
                            elapsed_seconds=0.0,
                            errors=[],
                            debug=[],
                            error_message=str(e),
                        )
                    if batch_result.data is not None:
                        self._store_allocation_batch_cache(
                            prompt,
                            payload_chunk,
                            batch_result.data,
                            cache_task=SEMANTIC_ALLOCATION_CACHE_TASK,
                        )
                    results_by_batch[batch_id] = batch_result
                    logger.info(
                        "Semantic allocation batch finished: batch=%s/%s groups=%s cache_hit=%s elapsed=%.3fs complete=%s error=%s",
                        batch_id,
                        len(payload_chunks),
                        len(payload_chunk),
                        batch_result.cache_hit,
                        batch_result.elapsed_seconds,
                        batch_result.complete,
                        bool(batch_result.error_message),
                    )
                    self._emit_progress_event(
                        "allocation",
                        completed=len(results_by_batch),
                        total=len(payload_chunks),
                        cache_hits=len(
                            [result for result in results_by_batch.values() if result.cache_hit]
                        ),
                        retries=0,
                        batch_id=batch_id,
                        batch_elapsed_seconds=round(batch_result.elapsed_seconds, 3),
                        batch_error=bool(batch_result.error_message),
                        pending_batches=max(0, len(payload_chunks) - len(results_by_batch)),
                        configured_concurrency=self.allocation_max_concurrency,
                        actual_workers=max_workers,
                    )

        merged: Dict[int, Dict[str, str]] = {}
        for batch_id, payload_chunk in enumerate(payload_chunks, 1):
            batch_result = results_by_batch.get(batch_id)
            if batch_result is None or batch_result.data is None:
                retry_result, retry_complete = self._retry_incomplete_allocation_chunk(
                    prompt,
                    payload_chunk,
                    expected_groups_by_id,
                )
                merged.update(retry_result)
                if not retry_complete:
                    self._record_omitted_allocation_groups(
                        payload_chunk,
                        expected_groups_by_id,
                        retry_result,
                    )
                continue

            self._last_llm_raw_returns.append(
                {
                    "task": SEMANTIC_ALLOCATION_CACHE_TASK,
                    "data": batch_result.data,
                    "expected_group_ids": [entry.get("id") for entry in payload_chunk],
                    "batch_id": batch_id,
                    "elapsed_seconds": round(batch_result.elapsed_seconds, 3),
                    "error_message": batch_result.error_message,
                    "cache_hit": batch_result.cache_hit,
                }
            )
            self._last_allocation_raw_returns.append(
                {
                    "task": SEMANTIC_ALLOCATION_CACHE_TASK,
                    "data": batch_result.data,
                    "expected_group_ids": [entry.get("id") for entry in payload_chunk],
                    "batch_id": batch_id,
                    "elapsed_seconds": round(batch_result.elapsed_seconds, 3),
                    "error_message": batch_result.error_message,
                    "cache_hit": batch_result.cache_hit,
                }
            )

            chunk_result = batch_result.translations
            complete = batch_result.complete
            if not complete:
                self._record_allocation_structure_attempt(
                    batch_result.errors,
                    stage="initial_batch",
                    expected_group_ids=batch_result.expected_ids,
                    batch_id=batch_id,
                )
                retry_result, retry_complete = self._retry_incomplete_allocation_chunk(
                    prompt,
                    payload_chunk,
                    expected_groups_by_id,
                )
                chunk_result = retry_result
                complete = retry_complete
            else:
                self._last_semantic_group_debug.extend(batch_result.debug)

            merged.update(chunk_result)
            if not complete:
                self._record_omitted_allocation_groups(
                    payload_chunk,
                    expected_groups_by_id,
                    chunk_result,
                )
            quality_retry = self._retry_quality_failed_group_allocations(
                prompt,
                payload_chunk,
                expected_groups_by_id,
                chunk_result,
            )
            merged.update(quality_retry)
        return merged

    def _request_and_parse_allocation_chunk(
        self,
        prompt: str,
        payload_chunk: Sequence[Dict],
        expected_groups_by_id: Dict[int, Dict],
        *,
        cache_task: str = SEMANTIC_ALLOCATION_CACHE_TASK,
    ) -> tuple[Dict[int, Dict[str, str]], bool, Optional[object]]:
        data = self._request_semantic_translation_allocation(
            prompt,
            payload_chunk,
            cache_task=cache_task,
        )
        if data is None:
            return {}, False, None
        self._last_llm_raw_returns.append(
            {
                "task": cache_task,
                "data": data,
                "expected_group_ids": [entry.get("id") for entry in payload_chunk],
            }
        )
        self._last_allocation_raw_returns.append(
            {
                "task": cache_task,
                "data": data,
                "expected_group_ids": [entry.get("id") for entry in payload_chunk],
            }
        )
        return self._parse_allocation_chunk_data(
            payload_chunk,
            expected_groups_by_id,
            data,
        ) + (data,)

    def _request_and_parse_allocation_chunk_uncached(
        self,
        prompt: str,
        payload_chunk: Sequence[Dict],
        expected_groups_by_id: Dict[int, Dict],
        *,
        batch_id: int,
        cache_task: str,
    ) -> AllocationBatchResult:
        started = time.perf_counter()
        expected_ids = [int(entry.get("id") or 0) for entry in payload_chunk]
        data, error_message = self._request_semantic_translation_allocation_api_only(
            prompt,
            payload_chunk,
            cache_task=cache_task,
        )
        elapsed = time.perf_counter() - started
        self._record_llm_cache_stat(cache_task, False)
        if data is None:
            return AllocationBatchResult(
                batch_id=batch_id,
                expected_ids=expected_ids,
                translations={},
                complete=False,
                data=None,
                elapsed_seconds=elapsed,
                errors=[],
                debug=[],
                error_message=error_message,
                cache_hit=False,
            )
        translations, complete, errors, debug = self._parse_allocation_chunk_data_isolated(
            payload_chunk,
            expected_groups_by_id,
            data,
        )
        return AllocationBatchResult(
            batch_id=batch_id,
            expected_ids=expected_ids,
            translations=translations,
            complete=complete,
            data=data,
            elapsed_seconds=elapsed,
            errors=errors,
            debug=debug,
            error_message=error_message,
            cache_hit=False,
        )

    def _load_cached_allocation_batch(
        self,
        prompt: str,
        payload_chunk: Sequence[Dict],
        expected_groups_by_id: Dict[int, Dict],
        *,
        batch_id: int,
        cache_task: str,
    ) -> Optional[AllocationBatchResult]:
        cache_key = self._semantic_chinese_cache_key(prompt, payload_chunk, cache_task)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=0.2,
            task=cache_task,
        )
        if not cache_result:
            return None
        self._llm_cache_used = True
        self._record_llm_cache_stat(cache_task, True)
        started = time.perf_counter()
        try:
            data = json.loads(cache_result)
        except Exception as e:
            logger.warning("Semantic allocation cache parse failed; requesting fresh batch: %s", str(e))
            return None
        translations, complete, errors, debug = self._parse_allocation_chunk_data_isolated(
            payload_chunk,
            expected_groups_by_id,
            data,
        )
        return AllocationBatchResult(
            batch_id=batch_id,
            expected_ids=[int(entry.get("id") or 0) for entry in payload_chunk],
            translations=translations,
            complete=complete,
            data=data,
            elapsed_seconds=time.perf_counter() - started,
            errors=errors,
            debug=debug,
            cache_hit=True,
        )

    def _store_allocation_batch_cache(
        self,
        prompt: str,
        payload_chunk: Sequence[Dict],
        data: object,
        *,
        cache_task: str,
    ) -> None:
        cache_key = self._semantic_chinese_cache_key(prompt, payload_chunk, cache_task)
        try:
            self.cache_manager.set_llm_result(
                cache_key,
                json.dumps(data, ensure_ascii=False),
                self.model,
                temperature=0.2,
                task=cache_task,
            )
        except Exception as e:
            logger.warning("Semantic allocation cache write failed: %s", str(e))

    def _parse_allocation_chunk_data(
        self,
        payload_chunk: Sequence[Dict],
        expected_groups_by_id: Dict[int, Dict],
        data: object,
    ) -> tuple[Dict[int, Dict[str, str]], bool]:
        result, complete, errors, debug = self._parse_allocation_chunk_data_isolated(
            payload_chunk,
            expected_groups_by_id,
            data,
        )
        if complete:
            self._last_semantic_group_debug.extend(debug)
        else:
            self._record_allocation_structure_attempt(
                errors,
                stage="initial_batch",
                expected_group_ids=[int(entry.get("id") or 0) for entry in payload_chunk],
            )
        return result, complete

    def _parse_allocation_chunk_data_isolated(
        self,
        payload_chunk: Sequence[Dict],
        expected_groups_by_id: Dict[int, Dict],
        data: object,
    ) -> tuple[Dict[int, Dict[str, str]], bool, List[Dict], List[Dict]]:
        result: Dict[int, Dict[str, str]] = {}
        errors: List[Dict] = []
        debug: List[Dict] = []
        groups_data = data.get("groups", []) if isinstance(data, dict) else data
        groups_data = self._normalize_allocation_groups_data(
            list(expected_groups_by_id.values()),
            groups_data,
            errors=errors,
        )
        expected_group_ids = [int(entry.get("id") or 0) for entry in payload_chunk]
        returned_group_ids = set()
        for group in groups_data:
            if not isinstance(group, dict) or not str(group.get("id", "")).isdigit():
                continue
            group_id = int(group["id"])
            if group_id not in expected_group_ids:
                self._append_translation_structure_error(
                    errors,
                    "translation_id_unknown",
                    message=f"Unknown semantic group id returned: {group_id}",
                )
                continue
            expected_group = expected_groups_by_id.get(group_id)
            if expected_group is None:
                continue
            returned_group_ids.add(group_id)
            result[group_id] = self._parse_id_bound_translations_into(
                expected_group,
                self._group_expected_subtitle_ids(expected_group),
                group.get("part_translations", []),
                errors,
                debug,
            )
        complete = not errors and set(expected_group_ids) == returned_group_ids
        return result, complete, errors, debug

    def _retry_incomplete_allocation_chunk(
        self,
        prompt: str,
        payload_chunk: Sequence[Dict],
        expected_groups_by_id: Dict[int, Dict],
    ) -> tuple[Dict[int, Dict[str, str]], bool]:
        result: Dict[int, Dict[str, str]] = {}
        complete = True
        for entry in payload_chunk:
            data = self._request_semantic_translation_allocation(
                prompt,
                [entry],
                cache_task=SEMANTIC_ALLOCATION_RETRY_CACHE_TASK,
            )
            if data is None:
                complete = False
                continue
            self._last_allocation_raw_returns.append(
                {
                    "task": SEMANTIC_ALLOCATION_RETRY_CACHE_TASK,
                    "data": data,
                    "expected_group_ids": [entry.get("id")],
                    "structure_retry": True,
                }
            )
            group_result, group_complete, errors, debug = self._parse_allocation_chunk_data_isolated(
                [entry],
                expected_groups_by_id,
                data,
            )
            result.update(group_result)
            if group_complete:
                self._last_semantic_group_debug.extend(debug)
            else:
                self._translation_structure_errors.extend(errors)
            complete = complete and group_complete
        return result, complete

    def _retry_quality_failed_group_allocations(
        self,
        prompt: str,
        payload_chunk: Sequence[Dict],
        expected_groups_by_id: Dict[int, Dict],
        chunk_result: Dict[int, Dict[str, str]],
    ) -> Dict[int, Dict[str, str]]:
        result = dict(chunk_result)
        for entry in payload_chunk:
            group_id = int(entry.get("id") or 0)
            expected_group = expected_groups_by_id.get(group_id)
            if expected_group is None:
                continue
            allocation = result.get(group_id, {})
            validation = self._validate_group_chinese_allocation(
                entry,
                allocation,
            )
            initial_decision = self._decide_id_bound_allocation_candidate(
                original_allocation=allocation,
                candidate_allocation=allocation,
                group_context=entry,
                original_validation=validation,
                candidate_validation=validation,
                candidate_source="initial",
                require_high_confidence_fix=False,
            )
            self._last_allocation_validation.append(validation)
            if initial_decision["accepted"]:
                self._last_allocation_final.append(
                    {
                        "semantic_group_id": f"G{group_id:04d}",
                        "subtitle_ids": self._group_expected_subtitle_ids(expected_group),
                        "allocation": dict(allocation),
                        "source": "initial",
                    }
                )
                continue

            retry_record = {
                "semantic_group_id": f"G{group_id:04d}",
                "reason_codes": list(validation.get("issue_codes") or []),
                "attempted": True,
                "success": False,
            }
            retry_prompt = prompt
            retry_cache_task = SEMANTIC_ALLOCATION_RETRY_CACHE_TASK
            if "unnatural_chinese_fragment" in set(validation.get("issue_codes") or []):
                retry_prompt = self._compose_prompt(SEMANTIC_FRAGMENT_ALLOCATION_RETRY_PROMPT)
                retry_cache_task = SEMANTIC_FRAGMENT_ALLOCATION_RETRY_CACHE_TASK
            self._emit_progress_event(
                "allocation_retry",
                completed=len(self._last_allocation_retry_log),
                total=None,
                cache_hits=0,
                retries=len(self._last_allocation_retry_log) + 1,
                semantic_group_id=f"G{group_id:04d}",
            )
            data = self._request_semantic_translation_allocation(
                retry_prompt,
                [entry],
                cache_task=retry_cache_task,
            )
            if data is None:
                self._last_allocation_retry_log.append(retry_record)
                self._record_allocation_quality_unresolved(entry, allocation, validation, "retry_request_failed")
                continue
            self._last_allocation_raw_returns.append(
                {
                    "task": retry_cache_task,
                    "data": data,
                    "expected_group_ids": [group_id],
                    "quality_retry": True,
                }
            )
            group_result, group_complete, errors, debug = self._parse_allocation_chunk_data_isolated(
                [entry],
                expected_groups_by_id,
                data,
            )
            if not group_complete:
                self._translation_structure_errors.extend(errors)
                self._last_allocation_retry_log.append(retry_record)
                self._record_allocation_quality_unresolved(entry, allocation, validation, "retry_structure_failed")
                continue
            retry_allocation = group_result.get(group_id, {})
            retry_validation = self._validate_group_chinese_allocation(
                entry,
                retry_allocation,
                retry_of=validation,
            )
            self._last_allocation_validation.append(retry_validation)
            retry_decision = self._decide_id_bound_allocation_candidate(
                original_allocation=allocation,
                candidate_allocation=retry_allocation,
                group_context=entry,
                original_validation=validation,
                candidate_validation=retry_validation,
                candidate_source="quality_retry",
            )
            retry_quality_check = retry_decision["quality_comparison"]
            retry_record["quality_comparison"] = retry_quality_check
            retry_record["original_allocation"] = dict(allocation or {})
            retry_record["retry_allocation"] = dict(retry_allocation or {})
            retry_record["original_validation"] = validation
            retry_record["retry_validation"] = retry_validation
            if retry_decision["accepted"]:
                result[group_id] = retry_allocation
                self._last_semantic_group_debug.extend(debug)
                retry_record["success"] = True
                self._last_allocation_final.append(
                    {
                        "semantic_group_id": f"G{group_id:04d}",
                        "subtitle_ids": self._group_expected_subtitle_ids(expected_group),
                        "allocation": dict(retry_allocation),
                        "source": "quality_retry",
                    }
                )
            elif retry_validation["valid"]:
                self._record_allocation_quality_unresolved(
                    entry,
                    allocation,
                    validation,
                    "retry_rejected_due_to_quality_regression",
                    extra={
                        "retry_allocation": dict(retry_allocation or {}),
                        "retry_validation": retry_validation,
                        "quality_comparison": retry_quality_check,
                    },
                )
            else:
                self._record_allocation_quality_unresolved(
                    entry,
                    retry_allocation or allocation,
                    retry_validation,
                    "retry_quality_failed",
                )
            self._last_allocation_retry_log.append(retry_record)
        return result

    def _record_allocation_quality_unresolved(
        self,
        entry: Dict,
        allocation: Dict[str, str],
        validation: Dict,
        reason: str,
        extra: Optional[Dict] = None,
    ) -> None:
        group_id = int(entry.get("id") or 0)
        record = {
            "semantic_group_id": f"G{group_id:04d}",
            "reason": reason,
            "issue_codes": list(validation.get("issue_codes") or []),
            "full_english": entry.get("full_english", ""),
            "full_translation": entry.get("full_translation", ""),
            "allocation": dict(allocation or {}),
        }
        if extra:
            record.update(extra)
        self._last_allocation_unresolved.append(record)

    def _is_retry_allocation_quality_upgrade(
        self,
        entry: Dict,
        original_allocation: Dict[str, str],
        retry_allocation: Dict[str, str],
        original_validation: Dict,
        retry_validation: Dict,
    ) -> Dict:
        return self._decide_id_bound_allocation_candidate(
            original_allocation=original_allocation,
            candidate_allocation=retry_allocation,
            group_context=entry,
            original_validation=original_validation,
            candidate_validation=retry_validation,
            candidate_source="quality_retry",
        )["quality_comparison"]

    def _decide_id_bound_allocation_candidate(
        self,
        *,
        original_allocation: Dict[str, str],
        candidate_allocation: Dict[str, str],
        group_context: Dict,
        original_validation: Optional[Dict] = None,
        candidate_validation: Optional[Dict] = None,
        candidate_source: str,
        require_high_confidence_fix: bool = True,
    ) -> Dict:
        """Return the sole writeback decision for a fixed-ID Chinese candidate."""
        original = dict(original_allocation or {})
        candidate = dict(candidate_allocation or {})
        original_validation = original_validation or self._validate_group_chinese_allocation(
            group_context,
            original,
        )
        candidate_validation = candidate_validation or self._validate_group_chinese_allocation(
            group_context,
            candidate,
        )
        comparison = self._compare_allocation_candidates(
            original_allocation=original,
            retry_allocation=candidate,
            group_context=group_context,
            original_validation=original_validation,
            retry_validation=candidate_validation,
            require_high_confidence_fix=require_high_confidence_fix,
        )
        accepted = bool(candidate_validation.get("valid")) and bool(comparison.get("accepted"))
        return {
            "candidate_source": candidate_source,
            "accepted": accepted,
            "decision": "accept_candidate" if accepted else "keep_original",
            "original_validation": original_validation,
            "candidate_validation": candidate_validation,
            "quality_comparison": comparison,
        }

    def _compare_allocation_candidates(
        self,
        *,
        original_allocation: Dict[str, str],
        retry_allocation: Dict[str, str],
        group_context: Dict,
        original_validation: Dict,
        retry_validation: Dict,
        require_high_confidence_fix: bool = True,
    ) -> Dict:
        """Decide whether a fixed-ID Chinese candidate may replace the current one.

        Allocation retries must prove a high-confidence repair.  A selective
        polish request is different: it is already preselected by a local risk
        signal, so it only needs to stay structurally valid and avoid any
        measured regression.  Both paths use the same comparison evidence.
        """
        expected_ids = [
            str(part.get("subtitle_id") or "").strip()
            for part in list(group_context.get("subtitle_parts") or [])
        ]
        regression_reasons = self._detect_retry_allocation_quality_regressions(
            group_context,
            original_allocation or {},
            retry_allocation or {},
            expected_ids,
        )
        return compare_fixed_id_allocation_candidates(
            original_validation=original_validation,
            candidate_validation=retry_validation,
            expected_subtitle_ids=expected_ids,
            regression_reasons=regression_reasons,
            require_high_confidence_fix=require_high_confidence_fix,
        )

    def _detect_retry_allocation_quality_regressions(
        self,
        entry: Dict,
        original_allocation: Dict[str, str],
        retry_allocation: Dict[str, str],
        expected_ids: Sequence[str],
    ) -> List[str]:
        reasons: List[str] = []
        original_texts = [
            self._normalize_text(str(original_allocation.get(subtitle_id, "")))
            for subtitle_id in expected_ids
        ]
        retry_texts = [
            self._normalize_text(str(retry_allocation.get(subtitle_id, "")))
            for subtitle_id in expected_ids
        ]
        if self._empty_allocation_slot_count(retry_texts) > self._empty_allocation_slot_count(original_texts):
            reasons.append("new_empty_allocation_slot")
        if len(self._detect_adjacent_chinese_duplication(expected_ids, retry_texts)) > len(
            self._detect_adjacent_chinese_duplication(expected_ids, original_texts)
        ):
            reasons.append("new_adjacent_chinese_semantic_duplication")
        if self._bad_allocation_fragment_count(retry_texts) > self._bad_allocation_fragment_count(original_texts):
            reasons.append("new_unnatural_chinese_fragment")
        original_merged = self._normalize_text("".join(original_texts))
        retry_merged = self._normalize_text("".join(retry_texts))
        full_translation = self._normalize_text(str(entry.get("full_translation") or ""))
        original_coverage = self._allocation_information_coverage(full_translation, original_merged)
        retry_coverage = self._allocation_information_coverage(full_translation, retry_merged)
        if retry_coverage + 0.08 < original_coverage:
            reasons.append("group_information_coverage_regressed")
        if self._adjacent_language_naturalness_score(retry_texts) + 2 < self._adjacent_language_naturalness_score(original_texts):
            reasons.append("adjacent_language_naturalness_regressed")
        return reasons

    @staticmethod
    def _empty_allocation_slot_count(texts: Sequence[str]) -> int:
        return sum(1 for text in texts if not (text or "").strip())

    def _bad_allocation_fragment_count(self, texts: Sequence[str]) -> int:
        total = len(texts)
        return sum(
            1
            for index, text in enumerate(texts)
            if text and self._is_bad_allocation_chinese_fragment(text, index, total)
        )

    def _allocation_information_coverage(self, full_translation: str, merged_allocation: str) -> float:
        full = self._normalize_chinese_for_compare(full_translation)
        merged = self._normalize_chinese_for_compare(merged_allocation)
        if not full:
            return 1.0
        if not merged:
            return 0.0
        bag_overlap = self._character_bag_overlap(full, merged)
        lcs_coverage = self._lcs_length(full, merged) / max(1, len(full))
        return max(bag_overlap, lcs_coverage)

    def _adjacent_language_naturalness_score(self, texts: Sequence[str]) -> int:
        score = 0
        normalized = [self._normalize_text(text) for text in texts]
        for index, text in enumerate(normalized):
            compact = re.sub(r"\s+", "", text or "")
            if not compact:
                score -= 4
                continue
            if len(compact) <= 2 and compact not in {"好的", "没错", "对", "是的", "真的"}:
                score -= 2
            if index + 1 < len(normalized):
                pair = self._normalize_chinese_for_compare(text + normalized[index + 1])
                if re.search(r"(.)\1{3,}", pair):
                    score -= 1
            if re.search(r"[，、：；]$", compact) and index == len(normalized) - 1:
                score -= 2
            if self._is_bad_allocation_chinese_fragment(text, index, len(normalized)):
                score -= 2
        return score

    def _validate_group_chinese_allocation(
        self,
        entry: Dict,
        allocation: Dict[str, str],
        *,
        retry_of: Optional[Dict] = None,
    ) -> Dict:
        group_id = int(entry.get("id") or 0)
        subtitle_parts = list(entry.get("subtitle_parts") or [])
        expected_ids = [str(part.get("subtitle_id") or "").strip() for part in subtitle_parts]
        issue_codes: List[str] = []
        issues: List[Dict] = []

        if set(allocation or {}) != set(expected_ids):
            issue_codes.append("translation_group_cardinality_mismatch")
        full_translation = self._normalize_text(str(entry.get("full_translation") or ""))
        if full_translation and not re.search(r"[\u4e00-\u9fff]", full_translation):
            issue_codes.append("full_translation_quality_issue")

        ordered_texts = [
            self._normalize_text(str((allocation or {}).get(subtitle_id, "")))
            for subtitle_id in expected_ids
        ]
        for offset, text in enumerate(ordered_texts):
            if not text:
                issue_codes.append("group_allocation_information_omission")
                issues.append({"subtitle_id": expected_ids[offset], "reason": "empty_chinese"})
                continue
            # A one-cue group is already the authoritative full translation;
            # it has no allocation boundary for this validator to repair.
            if len(expected_ids) > 1 and self._is_bad_allocation_chinese_fragment(
                text, offset, len(ordered_texts)
            ):
                issue_codes.append("unnatural_chinese_fragment")
                issues.append(
                    {
                        "code": "unnatural_chinese_fragment",
                        "subtitle_id": expected_ids[offset],
                        "text": text,
                        "reason": "local_chinese_fragment_failed_quality_check",
                    }
                )

        duplicate_pairs = self._detect_adjacent_chinese_duplication(expected_ids, ordered_texts)
        if duplicate_pairs:
            issue_codes.append("adjacent_chinese_semantic_duplication")
            issues.extend(duplicate_pairs)

        merged = self._normalize_text("".join(ordered_texts))
        omission = self._detect_group_information_omission(full_translation, merged)
        if omission:
            issue_codes.append("group_allocation_information_omission")
            issues.append(omission)

        anchor_issues = self._detect_cross_id_anchor_misplacement(entry, allocation or {})
        issue_codes.extend(issue["code"] for issue in anchor_issues)
        issues.extend(anchor_issues)

        predicate_breaks = self._detect_cross_subtitle_predicate_breaks(
            expected_ids,
            ordered_texts,
        )
        if predicate_breaks:
            issue_codes.append("cross_subtitle_predicate_break")
            issues.extend(predicate_breaks)

        issue_codes = list(dict.fromkeys(issue_codes))
        blocking_issue_codes = [
            code for code in issue_codes if code != "full_translation_quality_issue"
        ]
        return {
            "semantic_group_id": f"G{group_id:04d}",
            "allocation_prompt_version": SEMANTIC_ALLOCATION_PROMPT_VERSION,
            "valid": not blocking_issue_codes,
            "issue_codes": issue_codes,
            "issues": issues,
            "expected_subtitle_ids": expected_ids,
            "allocated_subtitle_ids": list((allocation or {}).keys()),
            "full_english": entry.get("full_english", ""),
            "full_translation": full_translation,
            "merged_allocation": merged,
            "retry_of": retry_of.get("semantic_group_id") if retry_of else "",
        }

    @staticmethod
    def _detect_cross_subtitle_predicate_breaks(
        subtitle_ids: Sequence[str],
        texts: Sequence[str],
    ) -> List[Dict]:
        """Detect a reporting clause whose delayed predicate was mapped as English order.

        This deliberately requires three adjacent signals: a reporting verb at
        the preceding boundary, a time/aspect-led relative clause ending in an
        agent noun, and a following predicate. It avoids treating ordinary
        Chinese line continuation as a defect.
        """
        reporting_verbs = r"(?:发现|表明|显示|指出|证明|说明|认为)$"
        time_or_aspect = r"^(?:目前|如今|现在|正在|已经|已|仍|将|会|也|都)"
        agent_nouns = r"(?:模型|系统|公司|企业|政府|机构|研究者|学者|人们|他们|它们|我们|读者|用户)$"
        following_predicate = r"^(?:已|正在|会|将|仍|又|也|突然|不|没|开始|继续|停止|变得|成为|导致|带来|使用|采用|放弃|出现)"
        issues: List[Dict] = []
        compact = [re.sub(r"\s+", "", text or "") for text in texts]
        for index in range(len(compact) - 2):
            left, middle, right = compact[index : index + 3]
            if not left or not middle or not right:
                continue
            if re.search(r"[。！？；：]$", left):
                continue
            if not re.search(reporting_verbs, left):
                continue
            if not re.search(time_or_aspect, middle):
                continue
            if not re.search(agent_nouns, middle):
                continue
            if not re.search(following_predicate, right):
                continue
            issues.append(
                {
                    "code": "cross_subtitle_predicate_break",
                    "subtitle_ids": list(subtitle_ids[index : index + 3]),
                    "reason": "reporting_clause_relative_subject_then_delayed_predicate",
                    "confidence": "high",
                }
            )
        return issues

    def _boundary_has_audited_issue_exception(
        self,
        previous: ASRDataSeg,
        current: ASRDataSeg,
        issue: str,
    ) -> bool:
        """Use a recorded parser-backed exception instead of text-only guessing."""
        previous_end = getattr(previous, "word_end", None)
        current_start = getattr(current, "word_start", None)
        if previous_end is None or current_start is None:
            return False
        for repair in getattr(self, "_pre_id_boundary_repairs", []) or []:
            if issue not in set(repair.get("allowed_hard_issues") or []):
                continue
            for cut in repair.get("new_boundary") or []:
                if (
                    isinstance(cut, (list, tuple))
                    and len(cut) == 2
                    and int(cut[0]) == int(previous_end)
                    and int(cut[1]) == int(current_start)
                ):
                    return True
        return False

    def _structural_english_overflow_issues(
        self,
        segments: Sequence[ASRDataSeg],
    ) -> List[Dict]:
        hard_limit = max(int(self.max_english_words or 0), HARD_ENGLISH_WORD_LIMIT)
        issues: List[Dict] = []
        for seg in segments:
            text = self._normalize_text(seg.text)
            word_count = self._word_count(text)
            if not self._is_allowed_structural_english_overflow(seg, text, word_count, hard_limit):
                continue
            issues.append(
                {
                    "subtitle_id": str(getattr(seg, "subtitle_id", "") or ""),
                    "start": self._format_ms(seg.start_time),
                    "end": self._format_ms(seg.end_time),
                    "word_count": word_count,
                    "hard_limit": hard_limit,
                    "text": text,
                    "reason": "no_legal_internal_cut_within_normal_limit",
                }
            )
        return issues

    def _is_allowed_structural_english_overflow(
        self,
        segment: ASRDataSeg,
        text: str,
        word_count: int,
        hard_limit: int,
    ) -> bool:
        """Allow an audited complete cue only when no legal <=16 split exists."""
        if word_count <= hard_limit:
            return False
        terminal_sentence = bool(re.search(r"[.!?][\"')\]]*\s*$", text or ""))
        protected_comma_clause = self._is_parser_confirmed_comma_subordinate_clause(text)
        word_start = getattr(segment, "word_start", None)
        word_end = getattr(segment, "word_end", None)
        if (
            not isinstance(word_start, int)
            or not isinstance(word_end, int)
            or word_end <= word_start
            or word_start < 0
            or word_end >= len(self._active_word_entries)
        ):
            return False
        item = ScreenSubtitleItem(
            source_ids=self._source_ids_for_word_range(word_start, word_end),
            original=text,
            translated="",
            word_start=word_start,
            word_end=word_end,
        )
        complete_comma_main_clause = (
            word_count <= hard_limit + 4
            and bool(re.search(r",[\"')\]]*\s*$", text or ""))
            and bool(self._visual_temporal_clause_shape(item).get("complete_main_clause"))
        )
        if not terminal_sentence and not protected_comma_clause and not complete_comma_main_clause:
            return False
        repaired, _ = self._safe_overlong_item_split(item)
        return not repaired

    def _is_parser_confirmed_comma_subordinate_clause(self, text: str) -> bool:
        """Allow a short parser-confirmed leading subordinate clause as overflow.

        This is intentionally narrower than treating every comma-ended display
        as complete. It applies only when the local parser finds a leading
        subordinating marker whose predicate is finite (including an auxiliary
        plus non-finite lexical verb). Without the parser, the normal hard word
        limit remains in force.
        """
        normalized = self._normalize_text(text)
        if not re.search(r",[\"')\]]*\s*$", normalized):
            return False
        nlp = self._load_syntax_nlp()
        if not nlp:
            return False
        doc = nlp(normalized)
        tokens = list(doc)
        if not tokens:
            return False

        def is_finite_predicate(token) -> bool:
            if token.pos_ in {"VERB", "AUX"} and token.tag_ not in {"VB", "VBG", "VBN"}:
                return True
            return bool(
                token.pos_ == "VERB"
                and token.tag_ in {"VB", "VBG", "VBN"}
                and any(
                    child.dep_ in {"aux", "auxpass"}
                    and child.tag_ in {"MD", "VBD", "VBP", "VBZ"}
                    for child in token.children
                )
            )

        for marker in tokens:
            if marker.dep_ != "mark" and marker.pos_ != "SCONJ":
                continue
            predicate = marker.head
            if predicate.i <= marker.i or not is_finite_predicate(predicate):
                continue
            leading_tokens = [
                token
                for token in tokens[: marker.i]
                if token.pos_ != "PUNCT"
            ]
            if any(is_finite_predicate(token) for token in leading_tokens):
                continue
            if all(token.pos_ in {"ADV", "CCONJ", "INTJ", "PART", "SCONJ"} for token in leading_tokens):
                return True
        return False

    @classmethod
    def _is_allowed_plus_discourse_overflow(
        cls, text: str, word_count: int, hard_limit: int
    ) -> bool:
        return is_allowed_discourse_overflow(text, word_count, hard_limit)

    def _detect_adjacent_chinese_duplication(
        self,
        subtitle_ids: Sequence[str],
        texts: Sequence[str],
    ) -> List[Dict]:
        issues: List[Dict] = []
        normalized = [self._normalize_chinese_for_compare(text) for text in texts]
        for index, (left, right) in enumerate(zip(normalized, normalized[1:])):
            if not left or not right:
                continue
            if left == right or (len(left) >= 8 and left in right) or (len(right) >= 8 and right in left):
                issues.append(
                    {
                        "subtitle_ids": [subtitle_ids[index], subtitle_ids[index + 1]],
                        "reason": "adjacent_duplicate_or_containment",
                    }
                )
                continue
            common = self._long_common_chinese_overlap(left, right)
            if common:
                issues.append(
                    {
                        "subtitle_ids": [subtitle_ids[index], subtitle_ids[index + 1]],
                        "reason": "adjacent_long_common_phrase",
                        "common_phrase": common,
                        "common_length": len(common),
                    }
                )
        return issues

    @staticmethod
    def _long_common_chinese_overlap(left: str, right: str) -> str:
        left = re.sub(r"\s+", "", left or "")
        right = re.sub(r"\s+", "", right or "")
        if len(left) < 12 or len(right) < 12:
            return ""
        match = SequenceMatcher(None, left, right).find_longest_match(
            0,
            len(left),
            0,
            len(right),
        )
        if match.size < 10:
            return ""
        common = left[match.a : match.a + match.size]
        if len(common) < max(10, int(min(len(left), len(right)) * 0.35)):
            return ""
        if re.fullmatch(r"(?:这个|那个|他们|我们|因为|所以|但是|而且|就是|一个|一种|问题|事情)+", common):
            return ""
        return common

    def _detect_group_information_omission(
        self,
        full_translation: str,
        merged_allocation: str,
    ) -> Dict:
        full = self._normalize_chinese_for_compare(full_translation)
        merged = self._normalize_chinese_for_compare(merged_allocation)
        if not full or not merged:
            return {}
        if len(full) < 10:
            return {} if full in merged else {"reason": "short_full_translation_not_preserved"}
        bag_overlap = self._character_bag_overlap(full, merged)
        if bag_overlap >= 0.82:
            return {}
        lcs = self._lcs_length(full, merged)
        coverage = lcs / max(1, len(full))
        if coverage < 0.50:
            return {
                "reason": "low_full_translation_coverage",
                "coverage": round(coverage, 3),
                "full_length": len(full),
                "merged_length": len(merged),
            }
        return {}

    def _is_bad_allocation_chinese_fragment(self, text: str, offset: int, total: int) -> bool:
        raw = re.sub(r"\s+", "", text or "")
        normalized = re.sub(r"\s+", "", text or "")
        normalized = re.sub(r"[，。！？；：、,.!?;:]+$", "", normalized)
        if not normalized:
            return True
        terminal_punctuation = bool(re.search(r"[。！？.!?]$", raw))
        terminal_dangling_endings = (
            "的",
            "以及",
            "因为",
            "如果",
            "对于",
            "在",
            "将",
            "把",
            "意味着",
        )
        # A sentence-final list item or noun phrase can begin with a connector
        # and still be complete. Punctuation only bypasses validation when the
        # final grammar is not itself a dangling modifier or connective.
        if terminal_punctuation and (
            not normalized.endswith(terminal_dangling_endings)
            or re.search(
                r"(?:不是|并非|是)[^，。！？；：]{0,20}(?:写|做|创|制|编|说|叫|算|为|用|称|给|由|被|有|在|来自|属于)[^，。！？；：]{0,12}的$",
                normalized,
            )
        ):
            return False
        if total <= 1:
            return self._is_bad_chinese_fragment(text)
        if len(normalized) <= 2 and normalized not in {"好的", "没错", "对", "是的", "真的"}:
            return True
        # Allocation is allowed to create natural subtitle half-sentences inside
        # one semantic group. Hard-failing these fragments creates noisy retries.
        if offset < total - 1 and normalized.endswith(
            ("意味着", "因为", "如果", "对于", "以及", "将", "把", "在", "的")
        ):
            return False
        if offset < total - 1 and normalized.startswith(
            ("因为", "如果", "对于", "在", "将", "把", "以及", "而", "但", "并")
        ):
            return False
        # Terminal punctuation does not make a bare modifier complete.  Check
        # the grammar after preserving permitted non-final continuations.
        return self._is_bad_chinese_fragment(text)

    def _detect_cross_id_anchor_misplacement(
        self,
        entry: Dict,
        allocation: Dict[str, str],
    ) -> List[Dict]:
        parts = list(entry.get("subtitle_parts") or [])
        issues: List[Dict] = []
        expected_by_anchor: Dict[str, tuple[str, str]] = {}
        english_by_id: Dict[str, str] = {}
        for part in parts:
            subtitle_id = str(part.get("subtitle_id") or "").strip()
            english = str(part.get("english") or "")
            english_by_id[subtitle_id] = english
            for anchor in self._build_group_allocation_anchors(english):
                expected_by_anchor.setdefault(anchor["value"], (subtitle_id, anchor["type"]))

        for value, (expected_id, anchor_type) in expected_by_anchor.items():
            present_ids = [
                subtitle_id
                for subtitle_id, zh in allocation.items()
                if self._allocation_anchor_present(value, anchor_type, zh)
            ]
            expected_english = english_by_id.get(expected_id, "")
            if not present_ids:
                if anchor_type in {"number", "negation"} or (
                    anchor_type == "entity"
                    and self._allocation_anchor_present(value, anchor_type, str(entry.get("full_translation") or ""))
                ):
                    full_translation_has_anchor = self._allocation_anchor_present(
                        value,
                        anchor_type,
                        str(entry.get("full_translation") or ""),
                    )
                    if anchor_type in {"number", "negation"} and not full_translation_has_anchor:
                        # Allocation may distribute a completed translation,
                        # but it must not invent a number or negation that is
                        # already absent from the authoritative group text.
                        issues.append(
                            {
                                "code": "full_translation_quality_issue",
                                "anchor": value,
                                "anchor_type": anchor_type,
                                "reason": "authoritative_full_translation_missing_anchor",
                                "expected_english": expected_english,
                                "full_translation": str(entry.get("full_translation") or ""),
                            }
                        )
                        continue
                    issues.append(
                        {
                            "code": f"{anchor_type}_allocation_mismatch",
                            "anchor": value,
                            "anchor_type": anchor_type,
                            "expected_subtitle_id": expected_id,
                            "actual_subtitle_ids": [],
                            "reason": "anchor_missing",
                            "failure_kind": "missing",
                            "expected_english": expected_english,
                            "expected_chinese": allocation.get(expected_id, ""),
                            "full_translation_has_anchor": full_translation_has_anchor,
                            "present_scan": self._allocation_anchor_presence_scan(
                                value,
                                anchor_type,
                                allocation,
                            ),
                        }
                    )
                continue
            if expected_id not in present_ids:
                if anchor_type == "number" and self._is_allowed_adjacent_number_allocation(
                    expected_id,
                    present_ids,
                    [str(part.get("subtitle_id") or "").strip() for part in parts],
                    allocation,
                ):
                    continue
                if anchor_type == "negation" and self._is_allowed_adjacent_negation_allocation(
                    expected_id,
                    present_ids,
                    [str(part.get("subtitle_id") or "").strip() for part in parts],
                    english_by_id,
                ):
                    continue
                if anchor_type == "entity" and not self._is_high_confidence_cross_id_semantic_leakage(
                    expected_id,
                    present_ids,
                    [str(part.get("subtitle_id") or "").strip() for part in parts],
                    allocation,
                ):
                    continue
                code = (
                    "cross_id_semantic_leakage"
                    if anchor_type == "entity"
                    else f"{anchor_type}_allocation_mismatch"
                )
                issues.append(
                    {
                        "code": code,
                        "anchor": value,
                        "anchor_type": anchor_type,
                        "expected_subtitle_id": expected_id,
                        "actual_subtitle_ids": present_ids,
                        "reason": "anchor_present_on_different_subtitle_id",
                        "failure_kind": "misplaced",
                        "expected_english": expected_english,
                        "expected_chinese": allocation.get(expected_id, ""),
                        "actual_chinese": {
                            subtitle_id: allocation.get(subtitle_id, "")
                            for subtitle_id in present_ids
                        },
                        "present_scan": self._allocation_anchor_presence_scan(
                            value,
                            anchor_type,
                            allocation,
                        ),
                    }
                )
        return issues

    def _allocation_anchor_presence_scan(
        self,
        value: str,
        anchor_type: str,
        allocation: Dict[str, str],
    ) -> List[Dict]:
        return [
            {
                "subtitle_id": subtitle_id,
                "present": self._allocation_anchor_present(value, anchor_type, zh),
                "text": zh,
            }
            for subtitle_id, zh in allocation.items()
        ]

    def _is_high_confidence_cross_id_semantic_leakage(
        self,
        expected_id: str,
        present_ids: Sequence[str],
        ordered_ids: Sequence[str],
        allocation: Dict[str, str],
    ) -> bool:
        expected_text = self._normalize_text(str(allocation.get(expected_id, "")))
        expected_norm = self._normalize_chinese_for_compare(expected_text)
        if not expected_norm:
            return True
        expected_index = list(ordered_ids).index(expected_id) if expected_id in ordered_ids else -1
        adjacent_ids = {
            ordered_ids[index]
            for index in (expected_index - 1, expected_index + 1)
            if 0 <= index < len(ordered_ids)
        }
        present_norms = [
            self._normalize_chinese_for_compare(str(allocation.get(subtitle_id, "")))
            for subtitle_id in present_ids
        ]
        if any(expected_norm and expected_norm == present_norm for present_norm in present_norms):
            return True
        if len(expected_norm) <= 3 and adjacent_ids.intersection(present_ids):
            return True
        if adjacent_ids.intersection(present_ids):
            return False
        return len(expected_norm) <= 6

    def _is_allowed_adjacent_number_allocation(
        self,
        expected_id: str,
        present_ids: Sequence[str],
        ordered_ids: Sequence[str],
        allocation: Dict[str, str],
    ) -> bool:
        if expected_id not in ordered_ids:
            return False
        expected_index = list(ordered_ids).index(expected_id)
        following_id = ordered_ids[expected_index + 1] if expected_index + 1 < len(ordered_ids) else ""
        if following_id not in set(present_ids):
            return False
        expected_text = self._normalize_text(str(allocation.get(expected_id, "")))
        expected_norm = self._normalize_chinese_for_compare(expected_text)
        if not expected_norm:
            return False
        present_norms = [
            self._normalize_chinese_for_compare(str(allocation.get(subtitle_id, "")))
            for subtitle_id in present_ids
        ]
        if any(expected_norm and expected_norm == present_norm for present_norm in present_norms):
            return False
        return not self._is_bad_allocation_chinese_fragment(
            expected_text,
            expected_index,
            len(ordered_ids),
        )

    @staticmethod
    def _is_allowed_adjacent_negation_allocation(
        expected_id: str,
        present_ids: Sequence[str],
        ordered_ids: Sequence[str],
        english_by_id: Dict[str, str],
    ) -> bool:
        if expected_id not in ordered_ids:
            return False
        expected_index = list(ordered_ids).index(expected_id)
        adjacent_ids = {
            ordered_ids[index]
            for index in (expected_index - 1, expected_index + 1)
            if 0 <= index < len(ordered_ids)
        }
        if not adjacent_ids.intersection(present_ids):
            return False
        english = (english_by_id.get(expected_id) or "").strip().lower()
        # English can carry the auxiliary negation before the local predicate is
        # completed; Chinese often places the negative marker with that predicate.
        return bool(re.search(r"\b(?:like|as|to|of|for|with|that|which|who|when|if)$", english))

    def _build_group_allocation_anchors(self, english: str) -> List[Dict]:
        anchors: List[Dict] = []
        for match in re.finditer(r"\b\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?%?|\b\d+(?:[.,]\d+)?%?", english or ""):
            raw = match.group(0)
            after = (english or "")[match.end(): match.end() + 16]
            value = raw.replace(",", "").replace(" ", "")
            scale_match = re.match(r"\s*(billion|million|thousand|hundred)\b", after, re.IGNORECASE)
            if scale_match:
                scale = {
                    "hundred": 100,
                    "thousand": 1000,
                    "million": 1000000,
                    "billion": 1000000000,
                }[scale_match.group(1).lower()]
                try:
                    value = str(int(round(float(value) * scale)))
                except ValueError:
                    pass
            anchors.append(
                {
                    "type": "number",
                    "value": value,
                    "raw": raw,
                    "percent": raw.endswith("%"),
                    "decade": bool(re.match(r"\s*s\b", after, re.IGNORECASE)),
                }
            )
        if re.search(r"\b(?:not|n't|never|no|without|cannot|can't|doesn't|don't|didn't)\b", english or "", re.IGNORECASE):
            anchors.append({"type": "negation", "value": "negation"})
        for match in re.finditer(r"\b[A-Z][A-Za-z0-9]*(?:[- ][A-Z][A-Za-z0-9]*){0,3}\b", english or ""):
            value = match.group(0).strip()
            if value.lower() in {"i", "ai", "the", "this", "that"}:
                continue
            anchors.append({"type": "entity", "value": value})
        return anchors

    @classmethod
    def _allocation_anchor_present(cls, value: str, anchor_type: str, chinese: str) -> bool:
        text = chinese or ""
        if anchor_type == "negation" and cls._allocation_negation_present(text):
            return True
        if anchor_type == "number":
            compact = re.sub(r"[,，\s]", "", text)
            value = (value or "").replace(",", "").replace(" ", "")
            if value in compact:
                return True
            return any(variant and variant in compact for variant in cls._chinese_number_anchor_variants(value))
        if anchor_type == "negation":
            return bool(re.search(r"[不没无非未别勿]|不能|不会|不是|没有", text))
        return value in text or cls._normalized_entity_anchor(value) in cls._normalized_entity_anchor(text)

    @staticmethod
    def _allocation_negation_present(text: str) -> bool:
        if not text:
            return False
        return bool(
            re.search(
                r"(?:不|没|无|非|未|别|勿|不能|不会|不是|没有|不再|不必|不用|无需|无法|并非|绝非|直到.+才|对吧|是吧|不是吗|对不对|难道)",
                text,
            )
        )

    @staticmethod
    def _normalized_entity_anchor(text: str) -> str:
        return re.sub(r"[^0-9A-Za-z]+", "", text or "").lower()

    @staticmethod
    def _chinese_number_anchor_variants(value: str) -> List[str]:
        compact = (value or "").strip()
        is_percent = compact.endswith("%")
        compact = compact[:-1] if is_percent else compact
        if not re.fullmatch(r"\d+(?:\.\d+)?", compact):
            return []
        if "." in compact:
            return []
        number = int(compact)
        digit_map = "零一二三四五六七八九"

        def small_to_zh(num: int) -> str:
            if num == 0:
                return "零"
            units = [(1000, "千"), (100, "百"), (10, "十"), (1, "")]
            out: List[str] = []
            zero_pending = False
            rest = num
            for unit, label in units:
                digit = rest // unit
                rest %= unit
                if digit:
                    if zero_pending:
                        out.append("零")
                        zero_pending = False
                    if not (unit == 10 and digit == 1 and not out):
                        out.append(digit_map[digit])
                    out.append(label)
                elif out and rest:
                    zero_pending = True
            return "".join(out)

        def int_to_zh(num: int) -> str:
            if num < 10000:
                return small_to_zh(num)
            if num >= 100000000:
                high, low = divmod(num, 100000000)
                result = int_to_zh(high) + "\u4ebf"
                if low:
                    result += ("\u96f6" if low < 10000000 else "") + int_to_zh(low)
                return result
            high, low = divmod(num, 10000)
            result = small_to_zh(high) + "万"
            if low:
                result += ("零" if low < 1000 else "") + small_to_zh(low)
            return result

        variants = {int_to_zh(number)}
        variants.update({item.replace("二百", "两百").replace("二千", "两千").replace("二万", "两万") for item in list(variants)})
        if number >= 100000000 and number % 100000000 == 0:
            variants.add(f"{number // 100000000}亿")
            variants.add(f"{number // 100000000}亿美元")
            variants.add(f"{number // 100000000}亿人民币")
        elif number >= 100000000 and number % 10000000 == 0:
            yi_value = number / 100000000
            variants.add(f"{yi_value:g}亿")
            variants.add(f"{yi_value:g}亿美元")
            variants.add(f"{yi_value:g}亿人民币")
        if 1000 <= number <= 2099:
            year_digits = "".join(digit_map[int(ch)] for ch in str(number))
            variants.update({year_digits, f"{year_digits}年", f"{number}年"})
            if number % 10 == 0:
                century = number // 100 + 1
                decade = (number % 100) // 10 * 10
                variants.update(
                    {
                        f"{century}世纪{decade}年代",
                        f"{small_to_zh(century)}世纪{small_to_zh(decade)}年代",
                    }
                )
                if decade == 0:
                    variants.update({f"{century}世纪初", f"{small_to_zh(century)}世纪初"})
            if number % 100 == 0:
                century = number // 100 + 1
                variants.update({f"{century}世纪", f"{small_to_zh(century)}世纪"})
        if number % 10000 == 0 and number >= 10000:
            variants.add(f"{number // 10000}万")
        if number % 1000 == 0 and number >= 1000:
            variants.add(f"{number // 1000}千")
        variants.update(ScreenSubtitleEditor._decimal_wan_number_variants(number))
        if is_percent:
            variants.update({f"百分之{item}" for item in list(variants)})
            if number == 100:
                variants.add("百分之百")
        elif 0 <= number <= 100:
            variants.add(f"百分之{int_to_zh(number)}")
            if number == 100:
                variants.add("百分之百")
        return sorted(variants, key=len, reverse=True)

    @staticmethod
    def _decimal_wan_number_variants(number: int) -> List[str]:
        if number < 10000 or number % 1000 != 0:
            return []
        wan_value = number / 10000
        if wan_value.is_integer():
            return []
        text = f"{wan_value:g}万"
        return [text, f"{text}美元"]

    @staticmethod
    def _character_bag_overlap(left: str, right: str) -> float:
        if not left:
            return 0.0
        counts: Dict[str, int] = {}
        for char in right:
            counts[char] = counts.get(char, 0) + 1
        matched = 0
        for char in left:
            available = counts.get(char, 0)
            if available:
                matched += 1
                counts[char] = available - 1
        return matched / max(1, len(left))

    @staticmethod
    def _lcs_length(left: str, right: str) -> int:
        if not left or not right:
            return 0
        previous = [0] * (len(right) + 1)
        for left_char in left:
            current = [0]
            for index, right_char in enumerate(right, 1):
                if left_char == right_char:
                    current.append(previous[index - 1] + 1)
                else:
                    current.append(max(previous[index], current[-1]))
            previous = current
        return previous[-1]

    def _record_omitted_allocation_groups(
        self,
        payload_chunk: Sequence[Dict],
        expected_groups_by_id: Dict[int, Dict],
        chunk_result: Dict[int, Dict[str, str]],
    ) -> None:
        for expected_group_id in [int(entry.get("id") or 0) for entry in payload_chunk]:
            expected_group = expected_groups_by_id.get(expected_group_id)
            if expected_group is None:
                continue
            expected_ids = self._group_expected_subtitle_ids(expected_group)
            mapped = chunk_result.get(expected_group_id, {})
            returned_ids = list(mapped.keys()) if isinstance(mapped, dict) else []
            missing_ids = [subtitle_id for subtitle_id in expected_ids if subtitle_id not in returned_ids]
            if not missing_ids:
                continue
            self._record_translation_structure_error(
                "translation_group_cardinality_mismatch",
                group_id=expected_group_id,
                expected_ids=expected_ids,
                returned_ids=returned_ids,
                missing_ids=missing_ids,
                message="LLM omitted semantic group allocation result after retry.",
            )

    def _semantic_allocation_payload_chunks(
        self, payload: Sequence[Dict]
    ) -> List[List[Dict]]:
        batch_size = min(24, max(1, int(self.allocation_batch_size or 16)))
        return [
            list(payload[index : index + batch_size])
            for index in range(0, len(payload), batch_size)
        ]

    def _request_semantic_translation_allocation(
        self,
        prompt: str,
        payload: Sequence[Dict],
        *,
        cache_task: str = SEMANTIC_ALLOCATION_CACHE_TASK,
    ) -> Optional[object]:
        cache_key = self._semantic_chinese_cache_key(prompt, payload, cache_task)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=0.2,
            task=cache_task,
        )
        started = time.perf_counter()
        try:
            if cache_result:
                self._llm_cache_used = True
                self._record_llm_cache_stat(cache_task, True)
                logger.info(
                    "Semantic allocation batch loaded from cache: task=%s groups=%s elapsed=%.3fs",
                    cache_task,
                    len(payload),
                    time.perf_counter() - started,
                )
                return json.loads(cache_result)
            self._record_llm_cache_stat(cache_task, False)
            data, _ = self._request_semantic_translation_allocation_api_only(
                prompt,
                payload,
                cache_task=cache_task,
            )
            if data is None:
                return None
            self.cache_manager.set_llm_result(
                cache_key,
                json.dumps(data, ensure_ascii=False),
                self.model,
                temperature=0.2,
                task=cache_task,
            )
            logger.info(
                "Semantic allocation batch completed: task=%s groups=%s cache_hit=False elapsed=%.3fs",
                cache_task,
                len(payload),
                time.perf_counter() - started,
            )
            return data
        except Exception as e:
            logger.warning("Semantic subtitle translation allocation failed: %s", str(e))
            return None

    def _request_semantic_translation_allocation_api_only(
        self,
        prompt: str,
        payload: Sequence[Dict],
        *,
        cache_task: str = SEMANTIC_ALLOCATION_CACHE_TASK,
        max_attempts: int = 3,
    ) -> tuple[Optional[object], str]:
        delay_seconds = 1.0
        last_error = ""
        for attempt in range(1, max(1, max_attempts) + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.2,
                    timeout=self.timeout,
                )
                return json_repair.loads(response.choices[0].message.content), ""
            except Exception as e:
                last_error = str(e)
                if attempt >= max_attempts or not self._is_retryable_allocation_error(e):
                    break
                logger.warning(
                    "Semantic allocation batch request failed; retrying attempt %s/%s task=%s error=%s",
                    attempt + 1,
                    max_attempts,
                    cache_task,
                    last_error,
                )
                time.sleep(delay_seconds)
                delay_seconds = min(delay_seconds * 2, 8.0)
        logger.warning("Semantic subtitle translation allocation failed: %s", last_error)
        return None, last_error

    @staticmethod
    def _is_retryable_allocation_error(error: Exception) -> bool:
        status_code = getattr(error, "status_code", None)
        if status_code == 429 or (isinstance(status_code, int) and 500 <= status_code < 600):
            return True
        name = type(error).__name__.lower()
        text = str(error).lower()
        return any(token in name or token in text for token in ("timeout", "timed out", "429", "rate limit", "500", "502", "503", "504"))

    def _normalize_allocation_groups_data(
        self,
        expected_groups: Sequence[Dict],
        groups_data: object,
        errors: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        target_errors = self._translation_structure_errors if errors is None else errors
        expected_ids_by_group: Dict[int, set] = {
            int(group.get("id") or 0): set(self._group_expected_subtitle_ids(group))
            for group in expected_groups
            if str(group.get("id", "")).isdigit()
        }
        group_records: Dict[int, Dict] = {}
        orphan_parts: List[Dict] = []

        def visit(node: object) -> None:
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if not isinstance(node, dict):
                return
            nested = node.get("groups")
            if isinstance(nested, list):
                visit(nested)
                return
            subtitle_id = str(node.get("subtitle_id") or "").strip()
            if subtitle_id:
                orphan_parts.append(node)
                return
            if not str(node.get("id", "")).isdigit():
                return
            group_id = int(node["id"])
            if group_id not in group_records:
                record = dict(node)
                parts = record.get("part_translations", [])
                record["part_translations"] = list(parts) if isinstance(parts, list) else []
                group_records[group_id] = record
                return
            record = group_records[group_id]
            existing_parts = record.setdefault("part_translations", [])
            if not isinstance(existing_parts, list):
                existing_parts = []
                record["part_translations"] = existing_parts
            new_parts = node.get("part_translations", [])
            if isinstance(new_parts, list):
                existing_parts.extend(new_parts)

        visit(groups_data)

        for part in orphan_parts:
            subtitle_id = str(part.get("subtitle_id") or "").strip()
            matching_group_ids = [
                group_id
                for group_id, expected_ids in expected_ids_by_group.items()
                if subtitle_id in expected_ids
            ]
            if len(matching_group_ids) != 1:
                self._append_translation_structure_error(
                    target_errors,
                    "translation_id_unknown",
                    expected_ids=[],
                    returned_ids=[subtitle_id],
                    unknown_ids=[subtitle_id],
                    message=f"Orphan translation subtitle_id cannot be mapped to one group: {subtitle_id}",
                )
                continue
            group_id = matching_group_ids[0]
            record = group_records.setdefault(
                group_id,
                {"id": group_id, "part_translations": []},
            )
            parts = record.setdefault("part_translations", [])
            if not isinstance(parts, list):
                parts = []
                record["part_translations"] = parts
            parts.append(part)

        return [group_records[group_id] for group_id in sorted(group_records)]

    def _apply_semantic_group_translations(
        self,
        items: List[ScreenSubtitleItem],
        groups: Sequence[Dict],
        translations_by_group: Dict[int, Dict[str, str]],
    ) -> List[ScreenSubtitleItem]:
        result: List[ScreenSubtitleItem] = []
        used_indexes = set()
        for group in groups:
            group_items = group["items"]
            translations = translations_by_group.get(group["id"], {})
            if not isinstance(translations, dict):
                translations = {}
            expected_ids = self._group_expected_subtitle_ids(group)
            for offset, item in enumerate(group_items):
                subtitle_id = expected_ids[offset]
                translated = str(translations.get(subtitle_id, "")).strip()
                translated = self._repair_atomic_response_polarity(
                    item.original,
                    translated or item.translated,
                )
                result.append(
                    ScreenSubtitleItem(
                        source_ids=item.source_ids,
                        original=item.original,
                        translated=translated,
                        word_start=item.word_start,
                        word_end=item.word_end,
                        subtitle_id=item.subtitle_id,
                    )
                )
                used_indexes.add(group["start_index"] + offset)

        if len(used_indexes) != len(items):
            for index, item in enumerate(items):
                if index not in used_indexes:
                    result.append(item)
            result.sort(key=lambda item: self._item_order_key(item, items))
        return result

    @classmethod
    def _repair_atomic_response_polarity(cls, english: str, chinese: str) -> str:
        """Prevent an ID-bound one-word ``No.`` from becoming an affirmative reply.

        This is deliberately narrower than a backchannel dictionary: it only
        corrects a direct semantic contradiction in an isolated response and
        leaves all longer conversational text to the semantic-group allocator.
        """
        english_key = re.sub(r"[^a-z]", "", (english or "").casefold())
        chinese_key = re.sub(r"[\s，,。.!！?？]", "", chinese or "")
        affirmative = {"对", "对的", "没错", "是", "是的", "当然"}
        if english_key == "no" and chinese_key in affirmative:
            return "不是。"
        return chinese

    def _translate_semantic_subtitle_groups_single_stage(
        self, items: List[ScreenSubtitleItem], groups: Sequence[Dict]
    ) -> List[ScreenSubtitleItem]:

        payload = [
            {
                "id": group["id"],
                "full_english": " ".join(item.original for item in group["items"]),
                "expected_subtitle_ids": self._group_expected_subtitle_ids(group),
                "subtitle_parts": [
                    {
                        "subtitle_id": self._item_subtitle_id(
                            item,
                            int(group.get("start_index") or 0) + offset,
                        ),
                        "english": item.original,
                    }
                    for offset, item in enumerate(group["items"], 1)
                ],
                "current_translations": [item.translated for item in group["items"]],
            }
            for group in groups
        ]
        prompt = self._compose_prompt(SEMANTIC_SUBTITLE_TRANSLATION_PROMPT)
        cache_key = self._semantic_chinese_cache_key(
            prompt,
            payload,
            "screen_subtitle_semantic_translation",
        )
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=0.2,
            task="screen_subtitle_semantic_translation",
        )
        try:
            if cache_result:
                self._llm_cache_used = True
                data = json.loads(cache_result)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": prompt,
                        },
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    temperature=0.2,
                    timeout=self.timeout,
                )
                data = json_repair.loads(response.choices[0].message.content)
                self.cache_manager.set_llm_result(
                    cache_key,
                    json.dumps(data, ensure_ascii=False),
                    self.model,
                    temperature=0.2,
                    task="screen_subtitle_semantic_translation",
                )
        except Exception as e:
            logger.warning("语义组翻译失败，保留现有译文: %s", str(e))
            return items

        groups_data = data.get("groups", []) if isinstance(data, dict) else data
        self._last_llm_raw_returns.append(
            {
                "task": "screen_subtitle_semantic_translation",
                "data": data,
            }
        )
        single_stage_full_translations = self._semantic_full_translations_from_groups_data(
            groups_data if isinstance(groups_data, list) else []
        )
        self._last_semantic_full_translations = dict(single_stage_full_translations)
        self._last_semantic_group_audit_contexts = self._semantic_group_audit_contexts(
            groups,
            single_stage_full_translations,
        )
        by_id = {
            int(group.get("id")): group
            for group in groups_data
            if isinstance(group, dict) and str(group.get("id", "")).isdigit()
        }
        result: List[ScreenSubtitleItem] = []
        used_indexes = set()
        for group in groups:
            translated_group = by_id.get(group["id"], {})
            group_items = group["items"]
            expected_ids = self._group_expected_subtitle_ids(group)
            translations = self._parse_id_bound_translations(
                group,
                expected_ids,
                translated_group.get("part_translations", []),
            )
            for offset, item in enumerate(group_items):
                subtitle_id = expected_ids[offset]
                translated = str(translations.get(subtitle_id, "")).strip()
                result.append(
                    ScreenSubtitleItem(
                        source_ids=item.source_ids,
                        original=item.original,
                        translated=translated or item.translated,
                        word_start=item.word_start,
                        word_end=item.word_end,
                        subtitle_id=item.subtitle_id,
                    )
                )
                used_indexes.add(group["start_index"] + offset)

        if len(used_indexes) != len(items):
            for index, item in enumerate(items):
                if index not in used_indexes:
                    result.append(item)
            result.sort(key=lambda item: self._item_order_key(item, items))
        return result

    def _semantic_translation_groups(
        self, items: List[ScreenSubtitleItem]
    ) -> List[Dict]:
        groups: List[Dict] = []
        current: List[ScreenSubtitleItem] = []
        current_start = 0
        current_words = 0
        max_group_words = max(self.max_english_words * 3, 36)

        for index, item in enumerate(items):
            text = self._normalize_text(item.original)
            if not text:
                if current:
                    self._append_semantic_group(groups, current_start, current)
                    current = []
                    current_words = 0
                continue

            item_words = self._word_count(text)
            can_append = (
                not current
                or (
                    self._can_merge_items(current[-1], item)
                    and current_words + item_words <= max_group_words
                )
            )
            if not can_append:
                self._append_semantic_group(groups, current_start, current)
                current = []
                current_words = 0

            if not current:
                current_start = index
            current.append(item)
            current_words += item_words

            if self._ends_semantic_group(text):
                self._append_semantic_group(groups, current_start, current)
                current = []
                current_words = 0

        if current:
            self._append_semantic_group(groups, current_start, current)
        return groups

    @staticmethod
    def _append_semantic_group(
        groups: List[Dict], start_index: int, items: List[ScreenSubtitleItem]
    ) -> None:
        if not items:
            return
        groups.append(
            {
                "id": len(groups) + 1,
                "start_index": start_index,
                "items": list(items),
            }
        )

    @staticmethod
    def _ends_semantic_group(text: str) -> bool:
        text = (text or "").strip()
        if re.search(r"[.!?]\s*$", text):
            return True
        if re.search(r"\b(?:right|okay|ok)\?\s*$", text, flags=re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _merge_group_translation(items: List[ScreenSubtitleItem]) -> str:
        return "".join((item.translated or "").strip() for item in items)

    @staticmethod
    def _item_order_key(
        item: ScreenSubtitleItem, original_items: List[ScreenSubtitleItem]
    ) -> int:
        for index, original in enumerate(original_items):
            if item is original:
                return index
            if (
                item.source_ids == original.source_ids
                and item.original == original.original
                and item.word_start == original.word_start
                and item.word_end == original.word_end
            ):
                return index
        return len(original_items)

    def _rebalance_prepositional_continuations(
        self, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        result: List[ScreenSubtitleItem] = []
        i = 0
        while i < len(items):
            current = items[i]
            if (
                result
                and self._can_merge_items(result[-1], current)
                and not (
                    getattr(result[-1], "subtitle_id", None)
                    and getattr(current, "subtitle_id", None)
                )
                and re.match(
                    r"^(?:for|of|in|on|at|to|from|with|about|around|according)\b",
                    current.original,
                    flags=re.IGNORECASE,
                )
            ):
                moved, remainder = self._take_leading_phrase(current.original)
                candidate = self._normalize_text(f"{result[-1].original} {moved}")
                if moved and self._word_count(candidate) <= self.max_english_words:
                    previous = result[-1]
                    result[-1] = ScreenSubtitleItem(
                        source_ids=sorted(set(previous.source_ids + current.source_ids)),
                        original=candidate,
                        translated="",
                        subtitle_id=previous.subtitle_id or current.subtitle_id,
                    )
                    if remainder:
                        result.append(
                            ScreenSubtitleItem(
                                source_ids=current.source_ids,
                                original=remainder,
                                translated="",
                                subtitle_id=current.subtitle_id,
                            )
                        )
                    i += 1
                    continue
            result.append(current)
            i += 1
        return self._merge_short_preposition_tails(result)

    @classmethod
    def _take_leading_phrase(cls, text: str) -> tuple[str, str]:
        text = cls._normalize_text(text)
        match = re.match(r"^(.+?(?:\.\.\.|[.!?]))\s+(.+)$", text)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return text, ""

    def _merge_short_preposition_tails(
        self, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        result: List[ScreenSubtitleItem] = []
        for item in items:
            if (
                result
                and self._can_merge_items(result[-1], item)
                and not (
                    getattr(result[-1], "subtitle_id", None)
                    and getattr(item, "subtitle_id", None)
                )
                and re.match(
                    r"^(?:for|of|in|on|at|to|from|with|about|around)\b",
                    item.original,
                    flags=re.IGNORECASE,
                )
                and self._word_count(f"{result[-1].original} {item.original}")
                <= self.max_english_words
            ):
                previous = result[-1]
                result[-1] = ScreenSubtitleItem(
                    source_ids=sorted(set(previous.source_ids + item.source_ids)),
                    original=self._normalize_text(
                        f"{previous.original} {item.original}"
                    ),
                    translated="",
                    subtitle_id=previous.subtitle_id or item.subtitle_id,
                )
            else:
                result.append(item)
        return result

    def _merge_required_prepositional_heads(
        self, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        result: List[ScreenSubtitleItem] = []
        i = 0
        while i < len(items):
            current = items[i]
            if (
                i + 1 < len(items)
                and self._needs_following_preposition(current.original)
                and not (
                    getattr(current, "subtitle_id", None)
                    and getattr(items[i + 1], "subtitle_id", None)
                )
                and re.match(r"^(?:for|of|in|on|at|to|from|with|about|around)\b", items[i + 1].original, flags=re.IGNORECASE)
            ):
                merged_original = self._normalize_text(
                    f"{current.original} {items[i + 1].original}"
                )
                split_parts = self._split_required_prepositional_head(
                    merged_original, self.max_english_words
                )
                for part in split_parts:
                    result.append(
                        ScreenSubtitleItem(
                            source_ids=sorted(set(current.source_ids + items[i + 1].source_ids)),
                            original=part,
                            translated="",
                            subtitle_id=current.subtitle_id or items[i + 1].subtitle_id,
                        )
                    )
                i += 2
                continue
            result.append(current)
            i += 1
        return result

    @staticmethod
    def _needs_following_preposition(text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:preference|translation|corners?|effect|legacy|ratio|number|figure|stack|source material)\.?$",
                (text or "").strip(),
                flags=re.IGNORECASE,
            )
        )

    @classmethod
    def _split_required_prepositional_head(
        cls, text: str, max_words: int
    ) -> List[str]:
        text = cls._normalize_text(text)
        text = re.sub(r"\.\s+(?=for\b)", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"^the\b", "The", text, flags=re.IGNORECASE)

        match = re.match(r"^(.+?\bsociety)\s+(led\s+to\s+.+)$", text, flags=re.IGNORECASE)
        if match:
            first = cls._normalize_text(match.group(1))
            second = cls._normalize_text(match.group(2))
            if cls._word_count(first) <= max_words and cls._word_count(second) <= max_words:
                return [first, second]

        return cls._split_english_text(text, max_words)

    def _translate_missing_item_translations(
        self, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        missing_indices = [
            index for index, item in enumerate(items) if not (item.translated or "").strip()
        ]
        if not missing_indices:
            return items

        originals = [items[index].original for index in missing_indices]
        translations = self._translate_split_parts(originals)
        if len(translations) != len(originals):
            return items

        result = list(items)
        for offset, index in enumerate(missing_indices):
            translated = translations[offset]
            item = result[index]
            result[index] = ScreenSubtitleItem(
                source_ids=item.source_ids,
                original=item.original,
                translated=translated,
                word_start=item.word_start,
                word_end=item.word_end,
                subtitle_id=item.subtitle_id,
            )
        return result

    def _translate_missing_segments(self, segments: List[ASRDataSeg]) -> List[ASRDataSeg]:
        missing_indices = [
            index
            for index, seg in enumerate(segments)
            if (seg.text or "").strip()
            and re.search(r"[A-Za-z]", seg.text)
            and not (seg.translated_text or "").strip()
        ]
        if not missing_indices:
            return segments

        originals = [segments[index].text for index in missing_indices]
        translations = self._translate_split_parts(originals)
        if len(translations) != len(originals):
            logger.warning(
                "最终上屏字幕缺译文补译失败，缺译文数量=%s",
                len(missing_indices),
            )
            return segments

        result = list(segments)
        for offset, index in enumerate(missing_indices):
            translated = translations[offset]
            seg = result[index]
            result[index] = self._copy_segment(
                seg,
                translated_text=translated,
            )
        logger.info("最终上屏字幕缺译文已补译: %s", len(missing_indices))
        return result

    @classmethod
    def _align_segment_translation_punctuation(
        cls, segments: List[ASRDataSeg]
    ) -> List[ASRDataSeg]:
        for seg in segments:
            seg.translated_text = cls._align_translation_punctuation(
                seg.text, seg.translated_text
            )
        cls._repair_leading_translation_punctuation_segments(segments)
        return segments

    @classmethod
    def _align_item_translation_punctuation(
        cls, item: ScreenSubtitleItem
    ) -> ScreenSubtitleItem:
        return ScreenSubtitleItem(
            source_ids=item.source_ids,
            original=item.original,
            translated=cls._align_translation_punctuation(
                item.original, item.translated
            ),
            word_start=item.word_start,
            word_end=item.word_end,
            subtitle_id=item.subtitle_id,
        )

    @classmethod
    def _repair_leading_translation_punctuation_items(
        cls, items: List[ScreenSubtitleItem]
    ) -> List[ScreenSubtitleItem]:
        if not items:
            return items
        repaired = list(items)
        for index in range(1, len(repaired)):
            previous = repaired[index - 1]
            current = repaired[index]
            previous_text, current_text = cls._move_leading_translation_punctuation(
                previous.translated, current.translated
            )
            if previous_text == previous.translated and current_text == current.translated:
                continue
            repaired[index - 1] = ScreenSubtitleItem(
                source_ids=previous.source_ids,
                original=previous.original,
                translated=previous_text,
                word_start=previous.word_start,
                word_end=previous.word_end,
                subtitle_id=previous.subtitle_id,
            )
            repaired[index] = ScreenSubtitleItem(
                source_ids=current.source_ids,
                original=current.original,
                translated=current_text,
                word_start=current.word_start,
                word_end=current.word_end,
                subtitle_id=current.subtitle_id,
            )
        return repaired

    @classmethod
    def _repair_leading_translation_punctuation_segments(
        cls, segments: List[ASRDataSeg]
    ) -> None:
        for index in range(1, len(segments)):
            previous = segments[index - 1]
            current = segments[index]
            previous_text, current_text = cls._move_leading_translation_punctuation(
                previous.translated_text, current.translated_text
            )
            previous.translated_text = previous_text
            current.translated_text = current_text

    @staticmethod
    def _move_leading_translation_punctuation(
        previous: str, current: str
    ) -> tuple[str, str]:
        previous = (previous or "").strip()
        current = (current or "").strip()
        if not previous or not current:
            return previous, current
        match = re.match(r"^([，,、。！？!?；;：:]+)(\s*)(.+)$", current)
        if not match:
            return previous, current
        leading = match.group(1)
        remainder = match.group(3).strip()
        if not remainder:
            return previous, current
        terminal = "。！？!?；;：:"
        if previous[-1] in terminal:
            return previous, remainder
        punctuation = "，" if any(char in leading for char in "，,、") else leading[-1]
        return f"{previous}{punctuation}", remainder

    @staticmethod
    def _align_translation_punctuation(original: str, translated: str) -> str:
        original = (original or "").strip()
        translated = (translated or "").strip()
        if not original or not translated:
            return translated

        final = original[-1]
        zh_terminal = "。！？；，、：…"
        if final in ".!?…":
            return translated
        if final == ",":
            return re.sub(r"[。！？；，、：…]+$", "，", translated)
        if final == ";":
            return re.sub(r"[。！？；，、：…]+$", "；", translated)
        if final == ":":
            return re.sub(r"[。！？；，、：…]+$", "：", translated)
        return re.sub(f"[{re.escape(zh_terminal)}]+$", "", translated).strip()

    @classmethod
    def _split_english_text(cls, text: str, max_words: int) -> List[str]:
        text = cls._normalize_text(text)
        if cls._word_count(text) <= max_words:
            return [text]

        clauses = cls._split_english_clauses(text)
        parts: List[str] = []
        current = ""
        for clause in clauses:
            candidate = f"{current} {clause}".strip() if current else clause
            if current and cls._word_count(candidate) > max_words:
                parts.extend(cls._split_by_words(current, max_words))
                current = clause
            else:
                current = candidate
        if current:
            parts.extend(cls._split_by_words(current, max_words))
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _split_english_clauses(text: str) -> List[str]:
        pieces = re.split(
            r"(?<=[,;:!?])\s+|(?=\b(?:because|but|so|which|who|that|when|where|while|although|though|and|or|for|with|without|in|on|at|by|from|to|about|around|according)\b)",
            text,
            flags=re.IGNORECASE,
        )
        return [piece.strip() for piece in pieces if piece.strip()]

    @classmethod
    def _split_by_words(cls, text: str, max_words: int) -> List[str]:
        if cls._word_count(text) <= max_words:
            return [text.strip()]
        tokens = re.findall(r"\S+", text)
        parts: List[str] = []
        current: List[str] = []
        current_words = 0
        for token in tokens:
            token_words = cls._word_count(token)
            if current and current_words + token_words > max_words:
                parts.append(" ".join(current).strip())
                current = [token]
                current_words = token_words
            else:
                current.append(token)
                current_words += token_words
        if current:
            parts.append(" ".join(current).strip())
        return parts

    @staticmethod
    def _split_translated_text(text: str, count: int) -> List[str]:
        text = (text or "").strip()
        if count <= 1 or not text:
            return [text]
        pieces = [piece.strip() for piece in re.split(r"(?<=[。！？；，,;])", text) if piece.strip()]
        if len(pieces) == count:
            return pieces
        if len(pieces) > count:
            result = pieces[: count - 1]
            result.append("".join(pieces[count - 1 :]))
            return result
        size = max(1, len(text) // count)
        result = []
        for index in range(count):
            start = index * size
            end = (index + 1) * size if index < count - 1 else len(text)
            result.append(text[start:end].strip())
        return result

    @staticmethod
    def _word_count(text: str) -> int:
        return word_count(text)

    @staticmethod
    def _word_tokens(text: str) -> List[str]:
        return word_tokens(text)

    @staticmethod
    def _clean_boundary_token(token: str) -> str:
        return re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", token or "").lower()

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text or "").strip()
        text = re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", text)
        return text

    @classmethod
    def _is_pure_backchannel(cls, original: str, translated: str) -> bool:
        return False
        original = (original or "").strip()
        translated = (translated or "").strip()
        clean_en = re.sub(r"[.!?。？！…\s]+$", "", original).lower()
        clean_zh = re.sub(r"[。.!！?？…\s]+$", "", translated)
        english_fillers = {
            "right",
            "yeah",
            "yes",
            "yep",
            "exactly",
            "definitely",
            "okay",
            "ok",
            "sure",
            "wow",
            "jeez",
            "ah",
            "oh",
            "mm",
            "hmm",
            "roughly",
            "no",
        }
        chinese_fillers = {
            "对",
            "对的",
            "没错",
            "是的",
            "当然",
            "好吧",
            "好的",
            "嗯",
            "啊",
            "哦",
            "哇",
            "天哪",
            "确实",
            "没问题",
        }
        if clean_en:
            return clean_en in english_fillers
        if clean_zh:
            return clean_zh in chinese_fillers
        return False

    @classmethod
    def _trim_backchannel_prefix(cls, original: str, translated: str) -> tuple[str, str]:
        return original, translated
