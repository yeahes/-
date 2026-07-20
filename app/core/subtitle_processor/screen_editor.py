import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from string import Template
from typing import Callable, Dict, List, Optional, Sequence

from openai import OpenAI

from app.config import CACHE_PATH
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.storage.cache_manager import CacheManager
from app.core.utils import json_repair
from app.core.utils.logger import setup_logger

logger = setup_logger("screen_subtitle_editor")

DISPLAY_LEAD_IN_MS = 80
DISPLAY_TAIL_PADDING_MS = 180
DISPLAY_MIN_GAP_MS = 40


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
- Merge tiny dangling fragments when they are awkward alone.
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
Pure backchannels should usually disappear from screen subtitles in both languages:
Right. / Yeah. / Exactly. / Definitely. / Okay. / Ah, okay. / Wow. / Jeez. / Sure.
Chinese equivalents such as "对。", "没错。", "是的。", "当然。", "好吧。", "哇。", "天哪。" should also disappear.

When a backchannel only pads the start of a meaningful sentence, usually remove only the backchannel and keep the content:
- "Yeah, and today we're..." -> "And today we're..." or "Today we're..."
- "Right, but the issue is..." -> "But the issue is..."

Keep or partially keep them only when:
- they are part of a real question or confirmation, e.g. "The bare branches, right?"
- they are attached to meaningful content and carry stance, correction, or turn-taking emphasis.
- they express an important turn, surprise, disagreement, or correction, e.g. "Wait, really?", "No, that's different."
- they are needed for section transitions or closing remarks.

# Very important
Do NOT create paragraph-like long subtitles.
Do NOT summarize.
Do NOT add new facts.
Do NOT remove meaningful content.
Do NOT change the order.
Do NOT remove punctuation or convert decimal numbers such as 22.5 into 22 5.
Do NOT rewrite English into a shorter new sentence just to meet the word limit. Split it instead.
You may remove meaningless backchannel words such as "Yeah," or "Right," when they only pad the start/end of a meaningful sentence.
Do not remove "you know", "like", "well", "I mean", "actually", "basically", or "honestly" just to make the sentence cleaner.

# Length style
- English length is the main visual constraint. Most English subtitles should be 6-12 words, with 13-14 acceptable when it preserves a natural phrase or spoken beat.
- Chinese length is secondary. Make Chinese natural and compact, but do not split only because the Chinese line is long.
- Soft upper limits: English ${max_english_words} words, Chinese ${max_cjk_chars} Chinese characters.
- Treat ${max_english_words} English words as the hard maximum. Do not exceed it. Still, do not cut mechanically at the number; first choose a natural semantic, prepositional, contrastive, or clause boundary.
- You may exceed the Chinese limit when the English line is already short and splitting would make timing or meaning worse.
- Keep short conversational beats only when they carry meaning. Merge useless fragments like "too.", "yuan.", "though." into nearby subtitles when natural.

# Cutting logic
Prefer audio/intonation-like boundaries implied by punctuation, discourse markers, and meaning.
If there is no obvious boundary but the English line is long, force a cut at a readable semantic boundary:
- after time/place phrases
- before/after because, but, so, which, when, where, and
- around appositives and examples
- after complete subject-verb-object units
Do not force a cut for Chinese length alone.
If an English item is longer than ${max_english_words} words, split it into multiple items using the exact original words.
Prefer natural cut points over mechanical word counts: meaning units, prepositional phrases, contrast markers, relative clauses, examples, and punctuation.
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
      "original": "source words in this word range",
      "translated": "edited Chinese subtitle"
    }
  ]
}

source_ids must list the original subtitle numbers used by this item.
If you split one original subtitle into multiple items, repeat the same source_id in multiple items.
If you merge adjacent subtitles, include all source ids.
Choose word_start/word_end as the inclusive source word range for this item.
The English original field must be copied from that exact source word range. Do not rewrite, shorten, polish, or paraphrase it.
Do not invent word indexes. The range must stay inside the provided source_ids.
"""


@dataclass
class ScreenSubtitleItem:
    source_ids: List[int]
    original: str
    translated: str
    word_start: Optional[int] = None
    word_end: Optional[int] = None


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
        enable_quality_check: bool = False,
        update_callback: Optional[Callable[[Dict], None]] = None,
    ):
        self.model = model
        self.target_language = target_language
        self.max_cjk_chars = max_cjk_chars
        self.max_english_words = max_english_words
        self.batch_num = batch_num
        self.thread_num = thread_num
        self.temperature = temperature
        self.timeout = timeout
        self.enable_quality_check = enable_quality_check
        self.update_callback = update_callback
        self.cache_manager = CacheManager(str(CACHE_PATH))
        self.client = self._init_client()
        self._active_word_entries: List[Dict] = []
        self._active_source_word_spans: Dict[int, tuple[int, int]] = {}

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
        edited_segments = self._align_segment_translation_punctuation(edited_segments)
        if word_time_asr_data and word_time_asr_data.is_word_timestamp():
            edited_segments = self._realign_segments_to_word_times(
                edited_segments, word_time_asr_data.segments
            )
            edited_segments = self._apply_display_timing_padding(edited_segments)
            return ASRData(edited_segments)

        edited_data = ASRData(edited_segments).optimize_timing()
        edited_data.segments = self._apply_display_timing_padding(edited_data.segments)
        return edited_data

    @staticmethod
    def _apply_display_timing_padding(
        segments: Sequence[ASRDataSeg],
        lead_in_ms: int = DISPLAY_LEAD_IN_MS,
        tail_padding_ms: int = DISPLAY_TAIL_PADDING_MS,
        min_gap_ms: int = DISPLAY_MIN_GAP_MS,
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
            if end_time <= start_time:
                end_time = start_time + 1
            if end_time > original_end:
                tail_count += 1

            adjusted.append(
                ASRDataSeg(
                    text=seg.text,
                    translated_text=seg.translated_text,
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

    def _segments_from_parts(self, seg: ASRDataSeg, parts: List[str]) -> List[ASRDataSeg]:
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

        prompt = Template(SCREEN_EDITOR_PROMPT).safe_substitute(
            target_language=self.target_language,
            max_cjk_chars=self.max_cjk_chars,
            max_english_words=self.max_english_words,
        )
        cache_key = self._cache_key(prompt, payload)
        cache_result = self.cache_manager.get_llm_result(
            cache_key,
            self.model,
            temperature=self.temperature,
            task="screen_subtitle_editor",
        )
        if cache_result:
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
                original = str(raw.get("original", "")).strip()
                translated = str(raw.get("translated", "")).strip()
                word_start = self._safe_int(raw.get("word_start"))
                word_end = self._safe_int(raw.get("word_end"))
                if not source_ids or not original:
                    continue
                original, translated = self._trim_backchannel_prefix(
                    self._normalize_text(original),
                    self._normalize_text(translated),
                )
                if self._is_pure_backchannel(original, translated):
                    continue
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

            result.append(
                ASRDataSeg(
                    text=original,
                    translated_text=item.translated,
                    start_time=start_time,
                    end_time=end_time,
                )
            )

        return result

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
                ASRDataSeg(
                    text=seg.text,
                    translated_text=seg.translated_text,
                    start_time=start_time,
                    end_time=end_time,
                )
            )

        logger.info(
            "Screen subtitle word-time realignment: aligned=%s fallback=%s",
            aligned_count,
            fallback_count,
        )
        return aligned

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
                )
            )

        logger.info(
            "Screen subtitle item word spans assigned: assigned=%s fallback=%s",
            assigned_count,
            fallback_count,
        )
        return assigned

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
            if self._is_pure_backchannel(item.original, item.translated):
                continue
            item = self._fix_obvious_asr_errors(item)
            item = self._remove_embedded_backchannels(item)
            item = self._strip_leading_backchannel(item)
            item = self._strip_trailing_backchannel(item)
            result.extend(self._split_long_english_item(item))
        result = self._rebalance_prepositional_continuations(result)
        result = self._merge_required_prepositional_heads(result)
        result = self._merge_dangling_items(result)
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

        translated_parts = self._translate_split_parts(parts)
        if len(translated_parts) != len(parts):
            translated_parts = self._split_translated_text(item.translated, len(parts))
        return [
            ScreenSubtitleItem(
                source_ids=item.source_ids,
                original=part,
                translated=translated_parts[index] if index < len(translated_parts) else "",
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
            return ScreenSubtitleItem(item.source_ids, original, translated)

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
            return ScreenSubtitleItem(item.source_ids, stripped, translated)
        return ScreenSubtitleItem(item.source_ids, original, translated)

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
            return ScreenSubtitleItem(item.source_ids, stripped, translated)
        return ScreenSubtitleItem(item.source_ids, original, translated)

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
        return ScreenSubtitleItem(item.source_ids, cleaned, translated)

    @staticmethod
    def _fix_obvious_asr_errors(item: ScreenSubtitleItem) -> ScreenSubtitleItem:
        original = item.original
        original = re.sub(r"\bU\.\s*S\.", "U.S.", original)
        original = re.sub(r"\bU\.\s*K\.", "U.K.", original)
        original = re.sub(r"\bA\.\s*I\.", "AI", original)
        translated = item.translated or ""
        return ScreenSubtitleItem(item.source_ids, original, translated)

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
                )
            else:
                if result and is_tail_dangling_word and self._can_merge_items(result[-1], item):
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
            ),
            ScreenSubtitleItem(
                source_ids=source_ids,
                original=parts[1],
                translated=translations[1] if len(translations) > 1 else "",
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
                    )
                    if remainder:
                        result.append(
                            ScreenSubtitleItem(
                                source_ids=current.source_ids,
                                original=remainder,
                                translated="",
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
        for index, translated in zip(missing_indices, translations):
            item = result[index]
            result[index] = ScreenSubtitleItem(
                source_ids=item.source_ids,
                original=item.original,
                translated=translated,
            )
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
        return len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)?|\d+(?:\.\d+)?", text or ""))

    @staticmethod
    def _word_tokens(text: str) -> List[str]:
        return re.findall(
            r"[A-Za-z]+(?:[-'][A-Za-z]+)?|\d+(?:\.\d+)?", (text or "").lower()
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text or "").strip()
        text = re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", text)
        return text

    @classmethod
    def _is_pure_backchannel(cls, original: str, translated: str) -> bool:
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
