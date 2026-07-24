import hashlib
import json
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
from typing import Callable, Dict, List, Optional, Sequence

from openai import OpenAI

from app.config import CACHE_PATH
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.storage.cache_manager import CacheManager
from app.core.subtitle_processor.text_metrics import word_count, word_tokens
from app.core.utils import json_repair
from app.core.utils.logger import setup_logger

logger = setup_logger("screen_subtitle_editor")

DISPLAY_LEAD_IN_MS = 80
DISPLAY_TAIL_PADDING_MS = 180
DISPLAY_MIN_GAP_MS = 40
DISPLAY_MIN_DURATION_MS = 900
DISPLAY_SHORT_MERGE_MS = 700
DISPLAY_SHORT_MERGE_GAP_MS = 500
DISPLAY_SHORT_BRIDGE_GAP_MS = 2200
COVERAGE_GAP_REPORT_MS = 1500
ABNORMAL_TIMING_GAP_MS = 1800
ABNORMAL_TIMING_CLUSTER_GAP_MS = 900
READ_MS_PER_EN_WORD = 260
CHINESE_CPS_WARNING = 9.0
CHINESE_CPS_ERROR = 11.0
ENGLISH_WPS_WARNING = 5.0
ADJACENT_ZH_DUPLICATE_SIMILARITY = 0.88
SUBTITLE_DURATION_INVALID_MS = 150
SUBTITLE_DURATION_ERROR_MS = 250
SUBTITLE_DURATION_WARNING_MS = 500
SCREEN_SUBTITLE_PROMPT_VERSION = "global-subtitle-id-v2"
SEMANTIC_ALLOCATION_PROMPT_VERSION = "semantic-allocation-v2"
SEMANTIC_ALLOCATION_CACHE_TASK = "screen_subtitle_semantic_translation_allocation_v2"
SEMANTIC_ALLOCATION_RETRY_CACHE_TASK = "screen_subtitle_semantic_translation_allocation_retry_v2"


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
- English length is the main visual constraint. Most English subtitles should be 6-12 words, with 13-14 acceptable when it preserves a natural phrase or spoken beat.
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
- Keep facts, numbers, names, negation, contrast, conditions, modality, and speaker stance.
- Avoid stiff translationese and overly literal English sentence shape.
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

Version: semantic-allocation-v2

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

Return pure JSON only:
{
  "groups": [
    {
      "id": 1,
      "allocation_prompt_version": "semantic-allocation-v2",
      "part_translations": [
        {"subtitle_id": "S0001", "zh": "中文字幕1"},
        {"subtitle_id": "S0002", "zh": "中文字幕2"}
      ]
    }
  ]
}
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
        allocation_max_concurrency: int = 1,
    ):
        self.model = model
        self.target_language = target_language
        self.max_cjk_chars = max_cjk_chars
        self.max_english_words = max_english_words
        self.batch_num = batch_num
        self.thread_num = thread_num
        self.temperature = temperature
        self.timeout = timeout
        self.enable_stable_mode = enable_stable_mode
        self.enable_quality_check = enable_quality_check
        self.coverage_report_path = coverage_report_path
        self.article_context_prompt = (article_context_prompt or "").strip()
        self.update_callback = update_callback
        self.allocation_max_concurrency = max(1, int(allocation_max_concurrency or 1))
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
        self._llm_cache_used: bool = False
        self._boundary_snapshots: List[Dict] = []
        self._boundary_snapshot_changes: List[Dict] = []
        self._boundary_snapshot_item_sets: Dict[str, List[ScreenSubtitleItem]] = {}
        self._pre_id_boundary_repairs: List[Dict] = []
        self.last_validation_summary: Optional[Dict] = None

    def _compose_prompt(self, base_prompt: str) -> str:
        if not self.article_context_prompt:
            return base_prompt
        return f"{base_prompt}\n\n{self.article_context_prompt}"

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

        if word_time_asr_data and word_time_asr_data.is_word_timestamp():
            self._active_word_entries = self._word_time_entries(word_time_asr_data.segments)
            self._active_source_word_spans = self._map_source_segments_to_word_entries(
                asr_data.segments, self._active_word_entries
            )
            if self.enable_stable_mode and self._active_source_word_spans:
                return self._edit_stable_word_timed(asr_data)
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
        if self.enable_quality_check:
            edited_segments = self._quality_check_candidate_segments(edited_segments)
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
        self._last_semantic_full_translations = {}
        self._last_semantic_group_audit_contexts = {}
        self._last_semantic_group_id_by_subtitle_id = {}
        self._discourse_marker_orphans = []
        self._boundary_snapshots = []
        self._boundary_snapshot_changes = []
        self._boundary_snapshot_item_sets = {}
        self._pre_id_boundary_repairs = []
        self._active_source_segments_by_id = {
            index: seg for index, seg in enumerate(asr_data.segments, 1)
        }
        self._llm_cache_used = False
        items = self._stable_cut_items(asr_data.segments)
        self._capture_boundary_snapshot(
            "_stable_cut_items",
            items,
            changed_by="_stable_cut_items",
            previous_items=None,
        )
        items = self._merge_standalone_discourse_markers(items)
        self._capture_boundary_snapshot(
            "_merge_standalone_discourse_markers",
            items,
            changed_by="_merge_standalone_discourse_markers",
            previous_items=self._boundary_snapshot_items("_stable_cut_items"),
        )
        items = self._merge_short_display_segments(items)
        self._capture_boundary_snapshot(
            "_merge_short_display_segments",
            items,
            changed_by="_merge_short_display_segments",
            previous_items=self._boundary_snapshot_items("_merge_standalone_discourse_markers"),
        )
        items = self._rebalance_edge_discourse_markers(items)
        self._capture_boundary_snapshot(
            "_rebalance_edge_discourse_markers",
            items,
            changed_by="_rebalance_edge_discourse_markers",
            previous_items=self._boundary_snapshot_items("_merge_short_display_segments"),
        )
        items = self._validate_and_repair_final_pre_id_boundaries(items)
        items = self._assign_global_subtitle_ids(items)
        semantic_groups = self._semantic_translation_groups(items)
        items = self._translate_semantic_subtitle_groups(items)
        self._validate_final_item_translation_ids(items)
        items = self._validate_stable_items(items)
        segments = self._items_to_segments(
            items, list(enumerate(asr_data.segments, 1))
        )
        segments = self._translate_missing_segments(segments)
        segments = self._align_segment_translation_punctuation(segments)
        segments = self._repair_blocking_subtitle_issues(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=items,
        )
        segments = self._repair_abnormal_timing_gaps(segments)
        segments = self._apply_display_timing_padding(segments)
        segments = self._order_segments_by_frozen_subtitle_ids(segments)
        self._validate_final_segment_translation_ids(segments)
        self._write_stable_pipeline_artifacts(
            source_segments=asr_data.segments,
            semantic_groups=semantic_groups,
            subtitle_items=items,
            final_segments=segments,
        )
        self._report_subtitle_coverage_gaps(asr_data.segments, segments)
        return ASRData(segments)

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
        if normalized in {"i mean", "you know", "i guess", "well i mean"}:
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

    def _attach_marker_to_next_item(
        self,
        marker: ScreenSubtitleItem,
        next_item: ScreenSubtitleItem,
    ) -> tuple[Optional[ScreenSubtitleItem], Optional[ScreenSubtitleItem]]:
        combined = self._merge_subtitle_items(marker, next_item)
        if self._word_count(combined.original) <= self.max_english_words:
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
                repair_reason="hard_syntax_boundary_repaired",
                candidates_considered=candidates,
            )
            result[start:end] = new_items
            index = max(0, start - 1)
        result = self._validate_final_display_fragments(result)
        return result

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
                repair_reason="hard_fragment_repaired",
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
        for item in items:
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

        hard = list(dict.fromkeys(issues))
        result["hard_fragment_issues"] = hard
        result["fragment_type"] = hard[0] if hard else ""
        result["is_valid"] = not hard
        result["has_independent_meaning"] = bool(result["has_finite_predicate"] and word_count >= 4)
        return result

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
        attempts = [
            (boundary_index, boundary_index + 2),
            (max(0, boundary_index - 1), boundary_index + 1),
            (max(0, boundary_index - 1), boundary_index + 2),
            (boundary_index, min(len(items), boundary_index + 3)),
        ]
        seen = set()
        for start, end in attempts:
            if end - start < 2 or (start, end) in seen:
                continue
            seen.add((start, end))
            window = list(items[start:end])
            if not self._can_repair_pre_id_window(window):
                continue
            direct = self._direct_merge_weak_fragment_window(window, evaluation)
            if direct:
                return start, end, direct, [
                    {
                        "cuts": [],
                        "word_counts": [self._word_count(item.original) for item in direct],
                        "hard_issues": [],
                        "hard_fragment_issues": [],
                        "boundary_scores": [],
                    }
                ]
            repaired, candidates = self._repartition_pre_id_window(window)
            if not repaired:
                continue
            return start, end, repaired, candidates
        return None

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
        }
        if len(items) != 2:
            return []
        if not any(issue in weak_codes for issue in (evaluation.get("hard_issues") or [])):
            return []
        merged = self._merge_subtitle_items(items[0], items[1])
        if self._word_count(merged.original) > self.max_english_words:
            return []
        if self._internal_sentence_transition_word_index(merged) is not None:
            return []
        if self._weak_fragment_issues(merged, None, None):
            return []
        return [merged]

    def _can_repair_pre_id_window(self, items: Sequence[ScreenSubtitleItem]) -> bool:
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
            if pause is not None and pause >= 450:
                return False
        return True

    def _repartition_pre_id_window(
        self,
        items: Sequence[ScreenSubtitleItem],
    ) -> tuple[List[ScreenSubtitleItem], List[Dict]]:
        span_start = items[0].word_start
        span_end = items[-1].word_end
        if span_start is None or span_end is None or span_end <= span_start:
            return [], []
        target_count = len(items)
        candidates_considered: List[Dict] = []
        best: Optional[tuple[float, float, float, List[ScreenSubtitleItem]]] = None
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
            boundary_scores: List[float] = []
            for boundary_index, (left, right) in enumerate(zip(candidate_items, candidate_items[1:])):
                evaluation = self._evaluate_item_pair_for_final_boundary(
                    left,
                    right,
                    candidate_items[boundary_index - 1] if boundary_index > 0 else None,
                )
                hard_issues.extend(evaluation["hard_issues"])
                hard_fragment_issues.extend(evaluation.get("hard_fragment_issues", []))
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
                "boundary_scores": boundary_scores,
            }
            candidates_considered.append(candidate_record)
            if hard_issues:
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
                balance,
                sum(boundary_scores),
                sum(abs(count - self.max_english_words * 0.72) for count in word_counts),
            )
            if best is None or score < best[:3]:
                best = (score[0], score[1], score[2], candidate_items)
        return (best[3], candidates_considered) if best else ([], candidates_considered)

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
        hard_after = [
            self._evaluate_item_pair_for_final_boundary(
                left,
                right,
                (new_items or [])[index - 1] if index > 0 else None,
            ).get("hard_issues", [])
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
                "soft_issues": list(evaluation.get("soft_issues") or []),
                "hard_fragment_issues": list(evaluation.get("hard_fragment_issues") or []),
                "soft_fragment_issues": list(evaluation.get("soft_fragment_issues") or []),
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
                "unresolved_hard_issue": new_items is None,
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
        return copied

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
        return {
            "translation_model": self.model,
            "code_commit": self._current_git_commit(),
            "cache_used": self._llm_cache_used,
            "prompt_version": SCREEN_SUBTITLE_PROMPT_VERSION,
        }

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
        target = target_words or min(self.max_english_words, 14)
        emergency = max(target, min(16, max(self.max_english_words, target)))
        start, end = span
        if end < start:
            return []
        count = end - start + 1
        if count <= emergency:
            return [(start, end)]

        dp: List[tuple[float, Optional[int]]] = [(float("inf"), None)] * (count + 1)
        dp[0] = (0.0, None)
        for right in range(1, count + 1):
            max_len = min(emergency, right)
            for length in range(1, max_len + 1):
                left = right - length
                prev_score, _ = dp[left]
                if prev_score == float("inf"):
                    continue
                abs_left = start + left
                abs_right = start + right - 1
                score = (
                    prev_score
                    + self._segment_length_score(length, target, emergency)
                    + self._segment_boundary_score(abs_left, abs_right, start, end)
                )
                if left > 0:
                    boundary = self._evaluate_stable_cut_boundary(
                        abs_left - 1,
                        abs_left,
                        source_start=start,
                        source_end=end,
                    )
                    if not boundary["legal"]:
                        score += 100_000
                    score += float(boundary["boundary_score"])
                if score < dp[right][0]:
                    dp[right] = (score, left)

        ranges: List[tuple[int, int]] = []
        cursor = count
        while cursor > 0:
            prev = dp[cursor][1]
            if prev is None:
                break
            ranges.append((start + prev, start + cursor - 1))
            cursor = prev
        if cursor != 0 or not ranges:
            return self._stable_greedy_ranges(start, end, target, emergency)
        ranges.reverse()
        return self._merge_tiny_stable_ranges(ranges, target, emergency)

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
        if pause_ms is not None and pause_ms >= 450:
            return []
        entries = self._active_word_entries
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        issues: List[str] = []
        prepositions = {
            "into", "of", "for", "with", "without", "in", "on", "at", "by",
            "from", "to", "about", "around", "through", "over", "under",
            "between", "among", "against", "within", "across",
        }
        if left_token in prepositions and right_token:
            issues.append("preposition_object_split")
        context_start = max(0, left - 4)
        context_end = min(len(entries) - 1, right + 4)
        context = [
            self._clean_boundary_token(entries[index].get("token") or "")
            for index in range(context_start, context_end + 1)
        ]
        boundary_offset = left - context_start
        if self._boundary_inside_determiner_numeric_noun(context, boundary_offset):
            issues.append("determiner_numeric_noun_split")
        if self._boundary_inside_quantifier_phrase(context, boundary_offset):
            issues.append("quantifier_phrase_split")
        if self._is_numeric_unit_or_noun_split(left, right):
            issues.append("numeric_unit_or_noun_split")
        if self._is_auxiliary_predicate_split(left_token, right_token):
            issues.append("auxiliary_predicate_split")
        if self._is_subject_finite_verb_boundary(left_token, right_token):
            issues.append("subject_finite_verb_split")
        if self._is_short_verb_object_split(left_token, right_token):
            issues.append("short_verb_object_split")
        if self._is_verb_complement_split(left_token, right_token):
            issues.append("verb_complement_split")
        if self._is_compound_noun_split(left_token, right_token):
            issues.append("compound_noun_split")
        if self._is_modifier_noun_head_split(left_token, right_token):
            issues.append("modifier_noun_head_split")
        if self._is_determiner_head_phrase_split(left_token, right_token):
            issues.append("determiner_head_phrase_split")
        if self._is_particle_or_preposition_complement_split(left_token, right_token):
            issues.append("particle_or_preposition_complement_split")
        if self._is_negation_or_emphasis_boundary(left_token, right_token):
            issues.append("negation_or_emphasis_fragment")
        if self._is_adverb_adjective_boundary(left_token, right_token, pause_ms):
            issues.append("adverb_adjective_split")
        if self._is_transition_attached_to_previous_sentence(left, right, pause_ms):
            issues.append("transition_attached_to_previous_sentence")
        for issue in (getattr(self, "_syntax_hard_cut_issues", {}) or {}).get((left, right), []):
            if issue not in issues:
                issues.append(issue)
        return issues

    def _soft_stable_cut_issues(self, left: int, right: int) -> List[str]:
        entries = self._active_word_entries
        left_token = self._clean_boundary_token(entries[left].get("token") or "")
        right_token = self._clean_boundary_token(entries[right].get("token") or "")
        issues: List[str] = []
        if left_token in {"you", "than"} and right_token:
            issues.append("comparative_clause_split")
        return issues

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
        if "-" in left:
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
            "majority",
        }
        common_adjectives = {
            "complete", "existing", "grueling", "high-tech", "intensive",
            "massive", "outward", "own", "private", "publicly", "recurring",
            "relentless", "sprawling", "state", "structural", "sustainable",
            "today's", "vast", "corporate",
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
            right = min(cursor + emergency - 1, end)
            if right < end:
                best = right
                best_score = float("inf")
                for candidate in range(max(cursor, cursor + 5), right + 1):
                    boundary = self._evaluate_stable_cut_boundary(
                        candidate,
                        candidate + 1,
                        source_start=cursor,
                        source_end=end,
                    )
                    score = 100_000 if not boundary["legal"] else 0.0
                    score += float(boundary["boundary_score"])
                    score += abs((candidate - cursor) - target)
                    if score < best_score:
                        best_score = score
                        best = candidate
                right = best
            ranges.append((cursor, right))
            cursor = right + 1
        return ranges

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
            self._protect_subject_verb_boundaries(doc, doc_to_word)
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
            if min(subtree_indices) != head_index + 1:
                continue
            if len(subtree_indices) > 3:
                continue
            timing_gap = self._word_pause_ms(head_index, min(subtree_indices))
            if timing_gap is not None and timing_gap > 180:
                continue
            issue = "short_verb_object_split" if token.dep_ in {"obj", "dobj"} else "verb_complement_split"
            self._record_syntax_hard_issue_for_indices([head_index] + subtree_indices, issue)
            self._record_syntax_hard_issue_for_indices([head_index] + subtree_indices, "short_verb_complement_split")

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
        for token in doc:
            normalized = self._clean_boundary_token(token.text)
            if not normalized:
                continue
            while cursor <= span_end:
                entry_token = self._clean_boundary_token(
                    self._active_word_entries[cursor].get("token") or ""
                )
                if entry_token == normalized:
                    mapping[token.i] = cursor
                    cursor += 1
                    break
                if normalized in entry_token or entry_token in normalized:
                    mapping[token.i] = cursor
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
            )
            lines = [
                "字幕体检报告",
                "状态：发现需要人工检查的问题" if has_failures else "状态：通过，未发现明显问题",
                f"验证等级：{validation_summary['status']}",
                f"ERROR 数量：{len(validation_summary['errors'])}",
                f"WARNING 数量：{len(validation_summary['warnings'])}",
                f"INFO 数量：{len(validation_summary['info'])}",
                f"覆盖缺口数量：{len(gaps)}",
                f"缺中文字幕数量：{len(translation_gaps)}",
                f"英文超长数量：{len(health['overlong_english'])}",
                f"疑似坏切点数量：{len(health['bad_cuts'])}",
                f"疑似翻译腔数量：{len(health['translationese'])}",
                f"阅读速度严重问题数量：{len(health['reading_speed_errors'])}",
                f"阅读速度警告数量：{len(health['reading_speed_warnings'])}",
                f"字幕时长严重问题数量：{len(health['duration_errors'])}",
                f"字幕时长警告数量：{len(health['duration_warnings'])}",
                f"相邻中文疑似重复数量：{len(health['duplicate_chinese'])}",
                f"ASR 可疑文本数量：{len(health['asr_suspicious'])}",
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
            logger.info("上屏字幕覆盖报告已保存 / Coverage report saved: %s", report_path)
        except Exception as e:
            logger.warning("上屏字幕覆盖报告保存失败 / Coverage report save failed: %s", str(e))

    def has_blocking_validation_errors(self) -> bool:
        return bool(self._translation_structure_errors)

    def blocking_validation_message(self) -> str:
        errors = self._translation_structure_errors or []
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

        if health["syntax_boundary_audit"]:
            warnings.append(
                {
                    "code": "syntax_boundary_audit",
                    "message": f"存在 {len(health['syntax_boundary_audit'])} 处英文句法边界疑似坏切点。",
                    "items": health["syntax_boundary_audit"],
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

        return {
            "status": "ERROR" if errors else ("WARNING" if warnings else "PASS"),
            "errors": errors,
            "warnings": warnings,
            "info": info,
        }

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
            artifact_dir = self._artifact_dir(report_path)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "validation-report.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
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
            artifact_dir = self._artifact_dir(report_path)
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
                "enable_quality_check": self.enable_quality_check,
                "source_segment_count": len(source_segments),
                "word_count": len(self._active_word_entries),
                "subtitle_count": len(final_segments),
                "frozen_subtitle_ids": list(self._frozen_subtitle_ids),
                "translation_structure_error_count": len(self._translation_structure_errors),
                "artifact_schema_version": 1,
            }
            self._write_json_artifact(artifact_dir / "run-manifest.json", manifest)
            self._write_json_artifact(
                artifact_dir / "transcript.json",
                [self._segment_to_dict(index, seg) for index, seg in enumerate(source_segments, 1)],
            )
            self._write_json_artifact(
                artifact_dir / "word-ledger.json",
                self._word_ledger_payload(source_segments),
            )
            self._write_json_artifact(
                artifact_dir / "semantic-groups.json",
                self._semantic_groups_payload(semantic_groups),
            )
            self._write_json_artifact(
                artifact_dir / "subtitle-spans.json",
                [self._item_to_span_dict(index, item) for index, item in enumerate(subtitle_items, 1)],
            )
            self._write_json_artifact(
                artifact_dir / "stable-boundary-snapshots.json",
                self._boundary_snapshot_payload(),
            )
            self._write_json_artifact(
                artifact_dir / "translations.json",
                [self._segment_to_dict(index, seg) for index, seg in enumerate(final_segments, 1)],
            )
            self._write_json_artifact(
                artifact_dir / "llm-raw-returns.json",
                self._last_llm_raw_returns,
            )
            self._write_json_artifact(
                artifact_dir / "allocation-inputs.json",
                self._last_allocation_inputs,
            )
            self._write_json_artifact(
                artifact_dir / "allocation-raw-returns.json",
                self._last_allocation_raw_returns,
            )
            self._write_json_artifact(
                artifact_dir / "allocation-validation.json",
                self._last_allocation_validation,
            )
            self._write_json_artifact(
                artifact_dir / "allocation-retry-log.json",
                self._last_allocation_retry_log,
            )
            self._write_json_artifact(
                artifact_dir / "allocation-final.json",
                self._last_allocation_final,
            )
            self._write_json_artifact(
                artifact_dir / "allocation-unresolved.json",
                self._last_allocation_unresolved,
            )
            self._write_json_artifact(
                artifact_dir / "semantic-group-debug.json",
                self._last_semantic_group_debug,
            )
            self._write_json_artifact(
                artifact_dir / "translation-structure-errors.json",
                self._translation_structure_errors,
            )
            logger.info("稳定模式中间产物已保存 / Stable artifacts saved: %s", artifact_dir)
        except Exception as e:
            logger.warning("稳定模式中间产物保存失败 / Stable artifacts save failed: %s", str(e))

    @staticmethod
    def _artifact_dir(report_path: Path) -> Path:
        stem = report_path.stem
        if stem.endswith("-coverage-report"):
            stem = stem[: -len("-coverage-report")]
        return report_path.with_name(f"{stem}-artifacts")

    @staticmethod
    def _write_json_artifact(path: Path, payload) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
        for seg in segments:
            text = self._normalize_text(seg.text)
            word_count = self._word_count(text)
            if word_count <= self.max_english_words:
                continue
            issues.append(
                {
                    "start": self._format_ms(seg.start_time),
                    "end": self._format_ms(seg.end_time),
                    "word_count": word_count,
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
        issues: List[Dict] = []
        for index, (previous, current) in enumerate(zip(segments, segments[1:]), 1):
            previous_text = self._normalize_text(previous.text)
            current_text = self._normalize_text(current.text)
            if not previous_text or not current_text:
                continue
            reasons = self._syntax_boundary_reasons(previous_text, current_text)
            if not reasons:
                continue
            previous_last = self._clean_boundary_token(previous_text.split()[-1])
            current_first = self._clean_boundary_token(current_text.split()[0])
            legacy_reasons = self._bad_cut_reasons(previous_last, current_first)
            confidence_score = min(0.95, 0.65 + 0.12 * len(reasons))
            issues.append(
                {
                    "index": index + 1,
                    "left_subtitle_id": f"S{index:04d}",
                    "right_subtitle_id": f"S{index + 1:04d}",
                    "start": self._format_ms(previous.start_time),
                    "end": self._format_ms(current.end_time),
                    "reason": "; ".join(reasons),
                    "rule_codes": reasons,
                    "confidence": "high" if confidence_score >= 0.75 else "medium",
                    "confidence_score": round(confidence_score, 2),
                    "evidence": (
                        f"left_last={previous_last}; right_first={current_first}; "
                        f"left_tokens={self._word_tokens(previous_text)[-4:]}; "
                        f"right_tokens={self._word_tokens(current_text)[:4]}"
                    ),
                    "duplicates_legacy_bad_cut": bool(legacy_reasons),
                    "legacy_rule_codes": legacy_reasons,
                    "previous": previous_text,
                    "current": current_text,
                    "previous_english": previous_text,
                    "current_english": current_text,
                    "boundary": f"{previous_text} | {current_text}",
                }
            )
        return issues

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
            "took", "create", "creates", "created",
        }
        adjectives = {
            "absolute", "extreme", "uncomfortable", "rapid", "massive", "structural",
            "financial", "corporate", "public", "private", "local", "global",
            "new", "old", "major", "regional", "economic", "entire", "empty",
            "really",
        }
        common_nouns = {
            "air", "look", "edge", "atmosphere", "world", "question", "solution",
            "solutions", "building", "government", "market", "markets", "policy",
            "data", "source", "sources",
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
        if mapping_valid and self._is_incomplete_chinese_group(chinese):
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
        if mapping_valid:
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
            is_error = is_invalid or is_too_short_for_load
            is_warning = (
                not is_error
                and (
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
                else (SUBTITLE_DURATION_ERROR_MS if is_error else SUBTITLE_DURATION_WARNING_MS)
            )
            issues.append(
                {
                    "code": "subtitle_duration_invalid" if is_error else "subtitle_duration_too_short",
                    "level": "ERROR" if is_error else "WARNING",
                    "index": index,
                    "start": self._format_ms(seg.start_time),
                    "end": self._format_ms(seg.end_time),
                    "duration_ms": duration_ms,
                    "threshold_ms": threshold,
                    "reason": f"字幕显示时间 {duration_ms}ms，低于 {threshold}ms 阈值",
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
            "\u6ca1\u9519",
            "\u5bf9",
            "\u662f\u7684",
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
        repaired = self._repair_overlong_english_segments_local(segments)
        repaired = self._compress_fast_chinese_segments(
            repaired,
            semantic_groups=semantic_groups,
            subtitle_items=subtitle_items,
        )
        return repaired

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
            "Avoid title-like fragments and dangling clauses such as 而若..., 如果..., 因为..., 对于..., 在..., 把..., 将..., 意味着..., 的..., 以及...\n"
            "Keep facts, numbers, names, negation, contrast, causality, modality, and core conclusions.\n"
            "Return pure JSON:\n"
            "{\"items\":[{\"index\":0,\"chinese\":\"压缩后的中文\"}]}"
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
        for item in data.get("items", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict) or not str(item.get("index", "")).isdigit():
                continue
            index = int(item["index"])
            if index < 0 or index >= len(segments):
                self._record_translation_structure_error(
                    "translation_id_unknown",
                    message=f"Compression returned unknown segment index: {index}",
                )
                continue
            text = str(item.get("chinese", "")).strip()
            if text:
                by_id[self._segment_subtitle_id(segments[index], index + 1)] = text

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
                "Return only existing indices from sense_group.parts. Keep every returned line natural and readable.\n"
                "The concatenated group Chinese must preserve the core meaning and form a complete Chinese sentence.\n"
                "Return pure JSON: {\"groups\":[{\"target_index\":0,\"segments\":[{\"index\":0,\"zh\":\"中文\"}]}]}"
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
                "Return pure JSON: {\"groups\":[{\"target_index\":0,\"segments\":[{\"index\":0,\"zh\":\"中文\"}]}]}"
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
            before_valid = self._validate_group_chinese_allocation(before_entry, before_allocation)["valid"]
            after_validation = self._validate_group_chinese_allocation(entry, after_allocation)
            self._last_allocation_validation.append(
                {
                    **after_validation,
                    "postprocess_stage": "compression_or_reallocation",
                }
            )
            if before_valid and not after_validation["valid"]:
                for index in range(start, end):
                    result[index] = before_segments[index]
                self._last_allocation_unresolved.append(
                    {
                        "semantic_group_id": f"G{int(group.get('id') or 0):04d}",
                        "reason": "postprocess_allocation_quality_regression_restored",
                        "issue_codes": after_validation["issue_codes"],
                    }
                )
        return result

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
        cache_key = self._cache_key(prompt, payload)
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
        for group in groups:
            if not isinstance(group, dict) or not str(group.get("target_index", "")).isdigit():
                continue
            target_index = int(group["target_index"])
            if target_index < 0 or target_index >= len(segments):
                continue
            target_id = self._segment_subtitle_id(segments[target_index], target_index + 1)
            allocation: Dict[str, str] = {}
            for item in group.get("segments", []):
                if not isinstance(item, dict) or not str(item.get("index", "")).isdigit():
                    continue
                index = int(item["index"])
                if index < 0 or index >= len(segments):
                    continue
                text = str(item.get("zh", item.get("chinese", ""))).strip()
                if text:
                    allocation[self._segment_subtitle_id(segments[index], index + 1)] = text
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
            "index": index,
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
                "target_index": index,
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
            "target_index": index,
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
        if self._is_incomplete_chinese_group(merged):
            return False
        if self._has_core_semantic_loss(merged, full_translation, full_english):
            return False
        return True

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
        if normalized.startswith(bad_prefixes):
            return True
        if normalized.endswith(bad_suffixes):
            return True
        if "联系更宏观层面" in normalized and not normalized.startswith("再从"):
            return True
        if "空置" in normalized and "政府" in normalized and not re.search(r"[\u60f3\u601d\u8003\u770b]", normalized):
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

        semantic_markers = [
            ("ponder", ("\u60f3", "\u601d\u8003", "\u7422\u78e8")),
            ("think", ("\u60f3", "\u601d\u8003")),
            ("question", ("\u95ee\u9898", "\u7591\u95ee", "\u8d28\u7591")),
            ("not ", ("\u4e0d", "\u6ca1", "\u65e0")),
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
        if duration_ms < 1200 or zh_chars < 12:
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

    @staticmethod
    def _cache_key(prompt: str, payload: List[Dict]) -> str:
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
                max(self.max_english_words, 14)
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
        allocated = self._allocate_semantic_group_translations(groups, full_translations)
        if allocated:
            return self._apply_semantic_group_translations(items, groups, allocated)

        logger.warning("语义组两阶段翻译失败，回退旧的一阶段语义组翻译")
        return self._translate_semantic_subtitle_groups_single_stage(items, groups)

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
        cache_key = self._cache_key(prompt, payload)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=0.2,
            task="screen_subtitle_semantic_full_translation",
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
                    task="screen_subtitle_semantic_full_translation",
                )
        except Exception as e:
            logger.warning("语义组完整翻译失败: %s", str(e))
            return {}

        groups_data = data.get("groups", []) if isinstance(data, dict) else data
        result: Dict[int, str] = {}
        for group in groups_data:
            if not isinstance(group, dict) or not str(group.get("id", "")).isdigit():
                continue
            translated = str(group.get("full_translation", "")).strip()
            if translated:
                result[int(group["id"])] = translated
        return result

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
        for group in groups:
            full_translation = full_translations.get(group["id"], "")
            if not full_translation:
                return {}
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
                    }
                )
            payload.append(
                {
                    "id": group["id"],
                    "allocation_prompt_version": SEMANTIC_ALLOCATION_PROMPT_VERSION,
                    "full_english": " ".join(item.original for item in group["items"]),
                    "full_translation": full_translation,
                    "subtitle_parts": subtitle_parts,
                }
            )

        self._last_allocation_inputs.extend(payload)
        result: Dict[int, Dict[str, str]] = {}
        expected_groups_by_id = {
            int(group.get("id") or 0): group
            for group in groups
            if str(group.get("id", "")).isdigit()
        }
        prompt = self._compose_prompt(SEMANTIC_TRANSLATION_ALLOCATION_PROMPT)
        payload_chunks = self._semantic_allocation_payload_chunks(payload)
        if self.allocation_max_concurrency > 1 and len(payload_chunks) > 1:
            return self._allocate_semantic_group_translations_concurrent(
                prompt,
                payload_chunks,
                expected_groups_by_id,
            )
        for payload_chunk in payload_chunks:
            chunk_result, complete, data = self._request_and_parse_allocation_chunk(
                prompt,
                payload_chunk,
                expected_groups_by_id,
            )
            if data is None:
                return {}
            if not complete:
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
                }
            )

            chunk_result = batch_result.translations
            complete = batch_result.complete
            if not complete:
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
        cache_key = self._cache_key(prompt, payload_chunk)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=0.2,
            task=cache_task,
        )
        if not cache_result:
            return None
        self._llm_cache_used = True
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
        )

    def _store_allocation_batch_cache(
        self,
        prompt: str,
        payload_chunk: Sequence[Dict],
        data: object,
        *,
        cache_task: str,
    ) -> None:
        cache_key = self._cache_key(prompt, payload_chunk)
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
            self._last_allocation_validation.append(validation)
            if validation["valid"]:
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
            data = self._request_semantic_translation_allocation(
                prompt,
                [entry],
                cache_task=SEMANTIC_ALLOCATION_RETRY_CACHE_TASK,
            )
            if data is None:
                self._last_allocation_retry_log.append(retry_record)
                self._record_allocation_quality_unresolved(entry, allocation, validation, "retry_request_failed")
                continue
            self._last_allocation_raw_returns.append(
                {
                    "task": SEMANTIC_ALLOCATION_RETRY_CACHE_TASK,
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
            if retry_validation["valid"]:
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
    ) -> None:
        group_id = int(entry.get("id") or 0)
        self._last_allocation_unresolved.append(
            {
                "semantic_group_id": f"G{group_id:04d}",
                "reason": reason,
                "issue_codes": list(validation.get("issue_codes") or []),
                "full_english": entry.get("full_english", ""),
                "full_translation": entry.get("full_translation", ""),
                "allocation": dict(allocation or {}),
            }
        )

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
            if self._is_bad_chinese_fragment(text):
                issue_codes.append("unnatural_chinese_fragment")
                issues.append({"subtitle_id": expected_ids[offset], "text": text})

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
        return issues

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
        lcs = self._lcs_length(full, merged)
        coverage = lcs / max(1, len(full))
        if coverage < 0.62:
            return {
                "reason": "low_full_translation_coverage",
                "coverage": round(coverage, 3),
                "full_length": len(full),
                "merged_length": len(merged),
            }
        return {}

    def _detect_cross_id_anchor_misplacement(
        self,
        entry: Dict,
        allocation: Dict[str, str],
    ) -> List[Dict]:
        parts = list(entry.get("subtitle_parts") or [])
        issues: List[Dict] = []
        expected_by_anchor: Dict[str, tuple[str, str]] = {}
        for part in parts:
            subtitle_id = str(part.get("subtitle_id") or "").strip()
            english = str(part.get("english") or "")
            for anchor in self._build_group_allocation_anchors(english):
                expected_by_anchor.setdefault(anchor["value"], (subtitle_id, anchor["type"]))

        for value, (expected_id, anchor_type) in expected_by_anchor.items():
            present_ids = [
                subtitle_id
                for subtitle_id, zh in allocation.items()
                if self._allocation_anchor_present(value, anchor_type, zh)
            ]
            if not present_ids:
                if anchor_type in {"number", "negation"} or (
                    anchor_type == "entity"
                    and self._allocation_anchor_present(value, anchor_type, str(entry.get("full_translation") or ""))
                ):
                    issues.append(
                        {
                            "code": f"{anchor_type}_allocation_mismatch",
                            "anchor": value,
                            "expected_subtitle_id": expected_id,
                            "actual_subtitle_ids": [],
                            "reason": "anchor_missing",
                        }
                    )
                continue
            if expected_id not in present_ids:
                code = (
                    "cross_id_semantic_leakage"
                    if anchor_type == "entity"
                    else f"{anchor_type}_allocation_mismatch"
                )
                issues.append(
                    {
                        "code": code,
                        "anchor": value,
                        "expected_subtitle_id": expected_id,
                        "actual_subtitle_ids": present_ids,
                    }
                )
        return issues

    def _build_group_allocation_anchors(self, english: str) -> List[Dict]:
        anchors: List[Dict] = []
        for match in re.finditer(r"\b\d+(?:[.,]\d+)?\b", english or ""):
            anchors.append({"type": "number", "value": match.group(0).replace(",", "")})
        if re.search(r"\b(?:not|n't|never|no|without|cannot|can't|doesn't|don't|didn't)\b", english or "", re.IGNORECASE):
            anchors.append({"type": "negation", "value": "negation"})
        for match in re.finditer(r"\b[A-Z][A-Za-z0-9]*(?:[- ][A-Z][A-Za-z0-9]*){0,3}\b", english or ""):
            value = match.group(0).strip()
            if value.lower() in {"i", "ai", "the", "this", "that"}:
                continue
            anchors.append({"type": "entity", "value": value})
        return anchors

    @staticmethod
    def _allocation_anchor_present(value: str, anchor_type: str, chinese: str) -> bool:
        text = chinese or ""
        if anchor_type == "number":
            compact = re.sub(r"[,，\s]", "", text)
            return value in compact
        if anchor_type == "negation":
            return bool(re.search(r"[不没无非未别勿]|不能|不会|不是|没有", text))
        return value in text

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
        batch_size = min(24, max(1, int(self.batch_num or 24)))
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
        cache_key = self._cache_key(prompt, payload)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=0.2,
            task=cache_task,
        )
        try:
            if cache_result:
                self._llm_cache_used = True
                return json.loads(cache_result)
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
        cache_key = self._cache_key(prompt, payload)
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
            if not text or not re.search(r"[A-Za-z]", text):
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
