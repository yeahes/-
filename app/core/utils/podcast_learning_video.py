# -*- coding: utf-8 -*-
import copy
import hashlib
import json
import logging
import math
import os
import re
import subprocess
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from openai import OpenAI
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.config import BIN_PATH, CACHE_PATH, RESOURCE_PATH
from app.core.entities import LLMServiceEnum
from app.core.subtitle_processor.stable_display_planner import plan_word_page_spans
from app.core.subtitle_processor.chinese_token_boundaries import (
    chinese_token_boundaries,
)
from app.core.subtitle_processor.stable_display_page_contract import (
    DISPLAY_PAGE_PLANNER_VERSION,
    DISPLAY_PAGE_SCHEMA_VERSION,
    display_page_id,
)
from app.core.subtitle_processor.stable_artifacts import (
    file_sha256,
    validate_manifest_artifact,
)
from app.core.utils.json_repair import loads as repair_json_loads
from app.core.utils.video_utils import (
    MediaSynthesisCancelled,
    staged_media_output,
    terminate_media_process,
)


logger = logging.getLogger(__name__)


WIDTH = 1920
HEIGHT = 1080
FPS = 25
VOCAB_REQUEST_TIMEOUT_SECONDS = 90
VOCAB_REQUEST_MAX_GROUPS = 25
VOCAB_REQUEST_MAX_CHARS = 6000
VOCAB_CACHE_SCHEMA_VERSION = 2
SX = WIDTH / 1879
SY = HEIGHT / 1056
ARTICLE_DESIGN_WIDTH = 1600
ARTICLE_DESIGN_HEIGHT = 900
ARTICLE_WIDTH = 1920
ARTICLE_HEIGHT = 1080
ARTICLE_SCALE_X = ARTICLE_WIDTH / ARTICLE_DESIGN_WIDTH
ARTICLE_SCALE_Y = ARTICLE_HEIGHT / ARTICLE_DESIGN_HEIGHT
ARTICLE_CARD_CONTAINER = (251, 246, 237, 255)  # #FBF6ED

TEMPLATE_DIR = RESOURCE_PATH / "podcast_template"
ARTICLE_TEMPLATE_DIR = TEMPLATE_DIR / "article_vocab"
BACKGROUND = TEMPLATE_DIR / "background.png"
AVATAR_SOURCE = TEMPLATE_DIR / "hosts.png"
FONT_GANTARI = TEMPLATE_DIR / "Gantari-wght.ttf"
FONT_READEX_MEDIUM = (
    ARTICLE_TEMPLATE_DIR / "ReadexPro-Medium.ttf"
    if (ARTICLE_TEMPLATE_DIR / "ReadexPro-Medium.ttf").exists()
    else TEMPLATE_DIR / "ReadexPro-SemiBold.ttf"
)
FONT_READEX_SEMIBOLD = (
    ARTICLE_TEMPLATE_DIR / "ReadexPro-SemiBold.ttf"
    if (ARTICLE_TEMPLATE_DIR / "ReadexPro-SemiBold.ttf").exists()
    else TEMPLATE_DIR / "ReadexPro-SemiBold.ttf"
)
FONT_READEX_BOLD = (
    ARTICLE_TEMPLATE_DIR / "ReadexPro-Bold.ttf"
    if (ARTICLE_TEMPLATE_DIR / "ReadexPro-Bold.ttf").exists()
    else TEMPLATE_DIR / "ReadexPro-SemiBold.ttf"
)
FONT_READEX_REGULAR = (
    ARTICLE_TEMPLATE_DIR / "ReadexPro-Regular.ttf"
    if (ARTICLE_TEMPLATE_DIR / "ReadexPro-Regular.ttf").exists()
    else TEMPLATE_DIR / "ReadexPro-SemiBold.ttf"
)
FONT_HANCHAN_BOLD = (
    ARTICLE_TEMPLATE_DIR / "ChillYunmoGothicBold.otf"
    if (ARTICLE_TEMPLATE_DIR / "ChillYunmoGothicBold.otf").exists()
    else TEMPLATE_DIR / "ChillYunmoGothicBold.otf"
)
FONT_HANCHAN_HEAVY = (
    ARTICLE_TEMPLATE_DIR / "ChillYunmoGothicHeavy.otf"
    if (ARTICLE_TEMPLATE_DIR / "ChillYunmoGothicHeavy.otf").exists()
    else FONT_HANCHAN_BOLD
)
FONT_HANCHAN_MEDIUM = (
    ARTICLE_TEMPLATE_DIR / "ChillYunmoGothicMedium.otf"
    if (ARTICLE_TEMPLATE_DIR / "ChillYunmoGothicMedium.otf").exists()
    else TEMPLATE_DIR / "ChillYunmoGothicMedium.otf"
)
FONT_HANCHAN_REGULAR = (
    ARTICLE_TEMPLATE_DIR / "ChillYunmoGothicRegular.otf"
    if (ARTICLE_TEMPLATE_DIR / "ChillYunmoGothicRegular.otf").exists()
    else TEMPLATE_DIR / "ChillYunmoGothicRegular.otf"
)
ARTICLE_LOGO = (
    ARTICLE_TEMPLATE_DIR / "economist_logo.png"
    if (ARTICLE_TEMPLATE_DIR / "economist_logo.png").exists()
    else TEMPLATE_DIR / "economist_logo.png"
)
ARTICLE_TIP_ICON = ARTICLE_TEMPLATE_DIR / "Vector.png"
FONT_DIR = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"
FONT_DOUYIN = FONT_DIR / "douyinmeihaoti.otf"
FONT_YAHEI = Path("C:/Windows/Fonts/msyh.ttc")
FONT_SEGOE = Path("C:/Windows/Fonts/segoeui.ttf")
FONT_CAMBRIA = Path("C:/Windows/Fonts/cambria.ttc")
FFMPEG = BIN_PATH / "ffmpeg.exe"

TITLE_TEXT = "为什么人工智能会改变教育?"
TITLE_SAFE_LEFT_X0 = 410
TITLE_SAFE_RIGHT_X0 = 1470
TITLE_CENTER_Y0 = 234
TITLE_MAX_FONT_SIZE = 70
TITLE_MIN_FONT_SIZE = 40
BLUE = (0, 234, 255, 255)
ARTICLE_BLUE = (47, 111, 237, 255)
MUTED = (153, 153, 153, 255)
WHITE = (245, 248, 255, 255)
TITLE_FILL = (255, 255, 255, 179)
SUBTITLE_EN = (220, 224, 232, 255)
SUBTITLE_ZH = (186, 191, 200, 255)
SUBTITLE_EN_SHADOW = (0, 0, 0, 52)
SUBTITLE_EN_SHADOW_BLUR = 5
HIGHLIGHT_TRAILING_PUNCTUATION = frozenset(
    ".,;:!?…，。；：！？、)]}〉》」』】）\"'”’"
)
VOCAB_CARD_CENTER_X0 = 940
VOCAB_CARD_TOP_Y0 = 430
VOCAB_CARD_WIDTH0 = 608
VOCAB_CARD_HEIGHT0 = 138
EN_SUBTITLE_CENTER_Y0 = 700
ZH_SUBTITLE_CENTER_Y0 = 912
SUBTITLE_FADE_SECONDS = 0.22
SUBTITLE_MIN_ALPHA = 175
VOCAB_PROMPT_VERSION = 16
VOCAB_GROUP_MAX_CUES = 6
VOCAB_GROUP_MAX_SECONDS = 18.0
VOCAB_GROUP_SILENCE_SECONDS = 0.7
VOCAB_MIN_CARD_INTERVAL_SECONDS = 15.0
VOCAB_OPENING_CARD_TRANSITION_SECONDS = 0.25
VOCAB_CARDS_PER_MINUTE = 1.0
VOCAB_MIN_CARDS_PER_EPISODE = 3
VOCAB_MAX_CARDS_PER_EPISODE = 22
VOCAB_MAX_CONCEPT_CARDS_PER_EPISODE = 3
ARTICLE_SUBTITLE_EN_FONT_SIZE = 56
ARTICLE_SUBTITLE_ZH_FONT_SIZE = 46
ARTICLE_SUBTITLE_EN_FALLBACK_SIZES = (56, 54, 52, 50)
ARTICLE_SUBTITLE_EN_EMERGENCY_FALLBACK_SIZES: tuple[int, ...] = ()
ARTICLE_SUBTITLE_EN_ALLOWED_SIZES = (
    *ARTICLE_SUBTITLE_EN_FALLBACK_SIZES,
    *ARTICLE_SUBTITLE_EN_EMERGENCY_FALLBACK_SIZES,
)
ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE = min(ARTICLE_SUBTITLE_EN_FALLBACK_SIZES)
ARTICLE_SUBTITLE_EN_MIN_SIZE = min(ARTICLE_SUBTITLE_EN_ALLOWED_SIZES)
ARTICLE_SUBTITLE_ZH_MIN_SIZE = ARTICLE_SUBTITLE_ZH_FONT_SIZE
ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH = 1260
ARTICLE_SUBTITLE_EN_WIDTH = 1455
# A cue may use the full safe panel width while retaining the preferred font.
# This is a layout profile, never a segmentation budget.
ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH = 1498
ARTICLE_SUBTITLE_ZH_WIDTH = 1455
ARTICLE_PAGE_MIN_DURATION_MS = 900
ARTICLE_PAGE_COMFORTABLE_MAX_DURATION_MS = 6500
ARTICLE_PAGE_LEAD_IN_MS = 70
ARTICLE_PAGE_TAIL_HOLD_MS = 120
ARTICLE_PAGE_PAUSE_PREFERENCE_MS = 220
ARTICLE_PAGE_UNSUPPORTED_TRANSITION_MIN_PAUSE_MS = 260
ARTICLE_PAGE_NONFINITE_COMPLEMENT_MAX_PAUSE_MS = 200
ARTICLE_PAGE_STRONG_PAUSE_REVIEW_MS = 600
ARTICLE_PAGE_PUNCTUATED_PREDICATE_REVIEW_MS = 320
ARTICLE_PAGE_BALANCED_CLAUSE_REVIEW_MS = 180
ARTICLE_PAGE_LOW_CONFIDENCE_FONT_REDUCTION_LIMIT = 4
ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS = 6
ARTICLE_PAGE_SECONDARY_REVIEW_STRONG_PAUSE_MS = 500
# A long frozen cue remains one subtitle ID and one timing envelope, but the
# article template may paginate it inside that envelope.  These are render
# budgets, not segmentation or translation limits.
# Keep 16 words as a soft renderer preference. The preferred 6-12 word target
# still guides the balanced split when possible.
# This is a preference, not a feasibility rule. Proportional-font pixel fit,
# grammar evidence, and page timing decide whether a page is renderable.
ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS = 16
ARTICLE_VISUAL_PAGE_PREFERRED_WORDS = 12
ARTICLE_VISUAL_PAGE_MIN_WORDS = 4
ARTICLE_VISUAL_PAGE_MAX_PAGES = 4
ARTICLE_STATIC_TWO_WORD_LINE_MAX_WORDS = ARTICLE_VISUAL_PAGE_MIN_WORDS * 2
ARTICLE_AVOID_LINE_START_WORDS = frozenset(
    {"away", "back", "down", "in", "off", "on", "out", "over", "up"}
)
ARTICLE_MIXED_AVOID_LINE_START = frozenset(
    "来的是在于与和及或但而并把被将让使为对从向给由因比像就也都还又再已会能要"
)
ARTICLE_MIXED_PREFERRED_BREAK_AFTER = frozenset(
    "，。；：、来的于与和及或但而并把被将让使为对从向给由因比像"
)
ARTICLE_CONCEPT_LEAD_IN_SUBJECTS = ("本句", "这句", "文中", "这里")
ARTICLE_CONCEPT_LEAD_IN_PREDICATES = (
    "说明",
    "表明",
    "表示",
    "意味着",
    "强调",
    "形容",
    "比喻",
    "描述",
    "解释",
)
ARTICLE_CONCEPT_LEAD_IN_MIN_CJK = 6
ARTICLE_CONCEPT_LEAD_IN_MAX_CJK = 12

LINE_BREAK_AVOID_BEFORE_WORDS = {
    "about", "above", "across", "after", "against", "although", "among", "around",
    "as", "because", "before", "beneath", "beside", "between", "but", "by",
    "despite", "during", "except", "for", "from", "if", "in", "inside", "into",
    "like", "near", "of", "on", "onto", "or", "over", "since", "so", "than",
    "that", "through", "to", "unless", "until", "when", "where", "which", "while",
    "who", "whose", "with", "without", "yet",
}
LINE_BREAK_AVOID_AFTER_WORDS = {
    "a", "an", "the", "this", "that", "these", "those", "my", "your", "our", "their",
    "about", "above", "across", "after", "against", "among", "around", "as", "at",
    "before", "behind", "below", "beneath", "beside", "between", "beyond", "by", "despite",
    "during", "except", "for", "from", "in", "inside", "into", "like", "near", "of", "on",
    "onto", "over", "since", "than", "through", "to", "under", "until", "with", "without",
    "am", "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "have",
    "has", "had", "can", "could", "will", "would", "shall", "should", "may", "might", "must",
}
CAPTION_HARD_BREAK_PENALTY = 12_000
ARTICLE_LINE_SOFT_MODIFIER_PENALTY = 1_600
ARTICLE_LINE_FONT_PIXEL_PENALTY = 2_500
# A complete phrase that starts on the next line/page is readable, but it is
# still slightly less desirable than a neutral boundary.  Keep this below the
# hard threshold so callers can distinguish a review-worthy preference from a
# genuinely stranded dependency.
CAPTION_COMPLETE_PHRASE_START_PENALTY = 600
# These are high-confidence lexical dependencies: the word on the left needs
# the function word on the right to complete the same phrase.  They are
# general grammar relations, not sample-specific exceptions.
CAPTION_DEPENDENT_BOUNDARY_PAIRS = frozenset(
    {
        ("according", "to"),
        ("based", "on"),
        ("because", "of"),
        ("completely", "out"),
        ("different", "from"),
        ("depending", "on"),
        ("due", "to"),
        ("far", "more"),
        ("instead", "of"),
        ("kind", "of"),
        ("lack", "of"),
        ("less", "than"),
        ("more", "than"),
        ("one", "of"),
        ("part", "of"),
        ("prior", "to"),
        ("rather", "than"),
        ("related", "to"),
        ("sort", "of"),
        ("such", "as"),
    }
)

# These are presentation-only guards.  A paginated page may begin with a
# complete prepositional or infinitive phrase, but a page must not begin with
# a bare clause introducer or connector that needs the preceding page.
ARTICLE_PAGE_PHRASE_START_WORDS = frozenset(
    {
        "about", "above", "across", "after", "against", "among", "around", "as",
        "at", "before", "behind", "below", "beneath", "beside", "between", "beyond",
        "by", "despite", "during", "except", "for", "from", "in", "inside", "into",
        "like", "near", "of", "on", "onto", "over", "since", "than", "through",
        "to", "under", "until", "with", "without",
    }
)
ARTICLE_PAGE_CONTINUATION_START_WORDS = frozenset(
    (LINE_BREAK_AVOID_BEFORE_WORDS - ARTICLE_PAGE_PHRASE_START_WORDS)
    | {"and", "but", "nor", "or", "so", "yet"}
)
MANUAL_DRAFT_PAGE_SCHEMA_VERSION = 1
ARTICLE_PAGE_OBJECT_DETERMINERS = frozenset(
    {"a", "an", "the", "this", "that", "these", "those", "my", "your", "our", "their", "its"}
)
ARTICLE_PAGE_TO_INFINITIVE_HEADS = frozenset(
    {
        "ability", "attempt", "chance", "decision", "effort", "goal", "need",
        "opportunity", "option", "permission", "plan", "power", "reason", "way",
    }
)
ARTICLE_PAGE_COMPLETE_CONTINUATION_START_WORDS = frozenset(
    {
        "although", "and", "because", "but", "if", "nor", "or", "so",
        "that", "unless", "when", "where", "which", "while", "who", "yet",
    }
)
ARTICLE_PAGE_COMPLETE_WH_CLAUSE_START_WORDS = frozenset(
    {
        "how",
        "what",
        "when",
        "where",
        "whether",
        "which",
        "who",
        "whom",
        "whose",
        "why",
    }
)
ENGLISH_VISUAL_MODIFIER_SUFFIXES = (
    "able", "al", "ant", "ary", "ed", "ent", "ful", "ic", "ical", "ible",
    "ish", "ive", "less", "ory", "ous",
)
ENGLISH_VISUAL_NOMINAL_SUFFIXES = ("ment",)
ENGLISH_VISUAL_MODIFIER_WORDS = frozenset(
    {
        "another", "bigger", "first", "former", "higher", "last", "larger",
        "least", "less", "lower", "more", "most", "new", "next", "old",
        "other", "previous", "same", "smaller",
    }
)
ENGLISH_NUMERIC_MAGNITUDE_WORDS = frozenset(
    {"hundred", "thousand", "million", "billion", "trillion"}
)
ENGLISH_RATE_DETERMINERS = frozenset({"a", "an", "each", "per"})
ENGLISH_RATE_PERIOD_WORDS = frozenset(
    {
        "day", "days", "hour", "hours", "minute", "minutes", "month",
        "months", "quarter", "quarters", "second", "seconds", "week",
        "weeks", "year", "years",
    }
)

# Formal cue boundaries and renderer-only page boundaries share evidence, but
# not every cue-level warning is an absolute page prohibition. Coordinators
# and complete dependency phrases remain reviewable; atomic lexical or
# predicate attachments stay hard.
DISPLAY_PAGE_REVIEWABLE_BOUNDARY_ISSUES = frozenset(
    {
        "clause_introducer_split",
        "coordinated_constituent_split",
        "dependency_phrase_entrance_split",
        "fronted_wh_clause_split",
        "modifier_head_split",
        "object_attached_modifier_split",
        "post_noun_participial_modifier_split",
        "verb_preposition_complement_split",
        "zero_relative_clause_split",
    }
)
DISPLAY_PAGE_ATOMIC_SOFT_ISSUES = frozenset(
    {
        "comparative_clause_split",
        "compound_noun_split",
        "modifier_noun_head_split",
        "phrasal_verb_particle_split",
        "short_verb_object_split",
        "verb_complement_split",
    }
)
DISPLAY_PAGE_STRONG_PAUSE_REVIEWABLE_HARD_ISSUES = frozenset(
    {
        "relative_clause_subject_verb_split",
        "subject_finite_verb_split",
        "subject_predicate_split",
    }
)
# A page transition hides the previous text, while a line wrap keeps both
# halves visible together. Only genuinely atomic language units remain hard at
# a same-screen line boundary; broader clause and predicate warnings are
# quality signals used to rank otherwise valid layouts.
ARTICLE_LINE_ATOMIC_BOUNDARY_ISSUES = frozenset(
    {
        "abbreviation_name_split",
        "auxiliary_predicate_split",
        "be_complement_split",
        "candidate_protected_named_phrase_split",
        "compound_noun_split",
        "compound_preposition_split",
        "determiner_head_phrase_split",
        "determiner_noun_split",
        "determiner_numeric_noun_split",
        "high_confidence_modifier_head_split",
        "hyphenated_measure_noun_split",
        "initialism_continuation_split",
        "modifier_head_split",
        "modifier_noun_head_split",
        "numeric_magnitude_split",
        "numeric_range_split",
        "numeric_unit_or_noun_split",
        "particle_or_preposition_complement_split",
        "phrasal_verb_particle_split",
        "phrasal_verb_split",
        "possessive_head_split",
        "predicate_complement_chain_split",
        "preposition_object_split",
        "protected_named_phrase_split",
        "protected_phrasal_boundary_split",
        "quantifier_phrase_split",
        "separable_verb_particle_chain_split",
        "to_infinitive_split",
        "verb_adverb_preposition_split",
        "verb_particle_preposition_chain_split",
        "verb_particle_split",
        "verb_preposition_complement_split",
        "verb_preposition_split",
    }
)
DISPLAY_PAGE_REVIEW_PENALTY = 2_800
DISPLAY_PAGE_LOW_CONFIDENCE_REVIEW_PENALTY = 800
DISPLAY_PAGE_HIGH_CONFIDENCE_REVIEW_PENALTY = 7_200
DISPLAY_PAGE_FORCED_CONTINUATION_REVIEW_PENALTY = 12_000
DISPLAY_PAGE_HIGH_RISK_COST = 6_000
DISPLAY_PAGE_FONT_STEP_PENALTY = 650
DISPLAY_PAGE_COUNT_DEVIATION_PENALTY = 600
DISPLAY_PAGE_TRANSITION_PENALTY = 150

# A Chinese visual page may switch before a new grammatical phrase, but it
# must not switch inside an unspaced lexical unit.  This is intentionally a
# conservative boundary vocabulary rather than a translation or segmentation
# authority: punctuation remains strongest, and ambiguous text is rejected by
# the strict page planner instead of being cut by character count.
CHINESE_VISUAL_SAFE_PREFIXES = frozenset(
    {
        "因为", "所以", "但是", "然而", "而且", "并且", "不过", "否则", "因此",
        "如果", "虽然", "即使", "以及", "还有", "同时", "并非", "尽管", "除非",
        "其中", "于是", "比如", "例如", "包括", "随着", "那么", "这样",
        "这种", "这些", "这个", "那个", "那些", "这里", "那里", "尤其", "而是",
    }
)


@dataclass
class Cue:
    index: int
    start: float
    end: float
    en: str
    zh: str
    speaker: str
    subtitle_id: str = ""
    word_timing: tuple[dict, ...] = ()
    article_page_plan: dict | None = None
    display_page_translations: dict[str, str] | None = None
    display_boundary_evidence: dict[str, dict] | None = None


class RenderStructuralOverflowError(RuntimeError):
    """Block video synthesis when a fixed-font render page cannot be planned."""

    code = "render_structural_overflow"

    def __init__(self, errors: list[dict]):
        self.errors = list(errors)
        details = "; ".join(
            f"cue={error.get('cue_index')} reason={error.get('reason')}"
            for error in self.errors
        )
        super().__init__(f"{self.code}: {details}")


class VocabularyPlanIncompleteError(RuntimeError):
    """Block synthesis until every current vocabulary batch is complete."""

    code = "vocabulary_plan_incomplete"

    def __init__(
        self,
        completed_chunks: int,
        total_chunks: int,
        failures: Sequence[str] = (),
    ) -> None:
        self.completed_chunks = completed_chunks
        self.total_chunks = total_chunks
        self.failures = tuple(failures)
        super().__init__(
            "智能单词卡生成未完成"
            f"（{completed_chunks}/{total_chunks} 批）；已保存进度，请重试合成"
        )


@dataclass(frozen=True)
class VocabSemanticGroup:
    """A display-only group built from frozen subtitle cues.

    This deliberately has no authority over subtitle text or timing.  It only
    tells the vocabulary selector which subtitle cues form one learning unit.
    """

    id: str
    cue_indices: tuple[int, ...]
    start: float
    end: float
    english: str


VOCAB = [
    {"keys": ["companionship"], "word": "Companionship", "level": "GRE", "meaning": "n. 陪伴关系/亲密关系"},
    {"keys": ["regulatory"], "word": "Regulatory", "level": "IELTS", "meaning": "adj. 监管的/调节的"},
    {"keys": ["regulation", "regulations"], "word": "Regulation", "level": "CET-6", "meaning": "n. 监管规定/规则"},
    {"keys": ["crackdown"], "word": "Crackdown", "level": "TOEFL", "meaning": "n. 严厉整治/打击"},
    {"keys": ["personas", "persona"], "word": "Persona", "level": "IELTS", "meaning": "n. 人设/角色形象"},
    {"keys": ["attachment"], "word": "Attachment", "level": "CET-6", "meaning": "n. 依恋/附件"},
    {"keys": ["mimic"], "word": "Mimic", "level": "CET-6", "meaning": "v. 模仿/模拟"},
    {"keys": ["deceased"], "word": "Deceased", "level": "TOEFL", "meaning": "adj. 已故的"},
    {"keys": ["compliance", "comply"], "word": "Compliance", "level": "TOEFL", "meaning": "n. 合规/遵从"},
    {"keys": ["insecurities", "insecurity"], "word": "Insecurity", "level": "CET-6", "meaning": "n. 不安全感/缺乏信心"},
    {"keys": ["paralyzed", "paralyze"], "word": "Paralyze", "level": "TOEFL", "meaning": "v. 使瘫痪/使停摆"},
    {"keys": ["fictional"], "word": "Fictional", "level": "CET-6", "meaning": "adj. 虚构的"},
    {"keys": ["algorithm", "algorithms"], "word": "Algorithm", "level": "CET-6", "meaning": "n. 算法"},
    {"keys": ["identity"], "word": "Identity", "level": "CET-4", "meaning": "n. 身份/特征"},
    {"keys": ["emotional"], "word": "Emotional", "level": "CET-4", "meaning": "adj. 情感的/情绪化的"},
]

COMMON_WORDS = {
    "about", "after", "again", "because", "before", "between", "could", "every",
    "first", "people", "really", "right", "should", "their", "there", "these",
    "thing", "those", "through", "where", "which", "would", "platform", "basically",
    "someone", "single", "sounds", "exactly", "yeah",
}


def scx(value: float) -> int:
    return round(value * SX)


def scy(value: float) -> int:
    return round(value * SY)


def _scaled_article_pixel(value: float, scale: float) -> int:
    """Keep every article-template geometry value on an integer pixel grid."""
    return int(round(value * scale))


def acx(value: float) -> int:
    return _scaled_article_pixel(value, ARTICLE_SCALE_X)


def acy(value: float) -> int:
    return _scaled_article_pixel(value, ARTICLE_SCALE_Y)


def article_rect(*values: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = values
    return acx(x0), acy(y0), acx(x1), acy(y1)


def font(path: Path, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    if not path.exists():
        path = FONT_YAHEI
    fnt = ImageFont.truetype(str(path), size)
    if weight is not None and hasattr(fnt, "set_variation_by_axes"):
        try:
            fnt.set_variation_by_axes([weight])
        except Exception:
            pass
    return fnt


def cjk_font(size: int) -> ImageFont.FreeTypeFont:
    return font(FONT_DOUYIN if FONT_DOUYIN.exists() else FONT_YAHEI, size)


def article_en_font(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    size = acx(size)
    if weight >= 700 and FONT_READEX_BOLD.exists():
        return font(FONT_READEX_BOLD, size, weight)
    if weight >= 600 and FONT_READEX_SEMIBOLD.exists():
        return font(FONT_READEX_SEMIBOLD, size, weight)
    if weight >= 500 and FONT_READEX_MEDIUM.exists():
        return font(FONT_READEX_MEDIUM, size, weight)
    if FONT_READEX_REGULAR.exists():
        return font(FONT_READEX_REGULAR, size, weight)
    return font(FONT_GANTARI, size, weight)


def article_cjk_font(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    size = acx(size)
    if weight >= 800 and FONT_HANCHAN_HEAVY.exists():
        return font(FONT_HANCHAN_HEAVY, size, weight)
    if weight >= 700 and FONT_HANCHAN_BOLD.exists():
        return font(FONT_HANCHAN_BOLD, size, weight)
    if weight >= 500 and FONT_HANCHAN_MEDIUM.exists():
        return font(FONT_HANCHAN_MEDIUM, size, weight)
    if FONT_HANCHAN_REGULAR.exists():
        return font(FONT_HANCHAN_REGULAR, size, weight)
    return font(FONT_DOUYIN if FONT_DOUYIN.exists() else FONT_YAHEI, size)


def article_mixed_font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    return font(FONT_YAHEI, acx(size), weight)


def article_tip_font(size: int) -> ImageFont.FreeTypeFont:
    return font(FONT_HANCHAN_MEDIUM, acx(size))


def text_w(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def text_h(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[3] - box[1]


def parse_ts(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def is_english(text: str) -> bool:
    letters = len(re.findall(r"[A-Za-z]", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk:
        return False
    return letters > cjk


def _split_bilingual_srt_payload(payload: list[str]) -> tuple[str, str]:
    first = payload[0]
    remaining = payload[1:]
    joined_remaining = "".join(remaining)
    if is_english(first):
        return first, joined_remaining
    if re.search(r"[\u4e00-\u9fff]", first):
        return " ".join(remaining) if remaining else first, first
    if any(is_english(line) for line in remaining):
        return " ".join(remaining), first

    first_has_ascii_terminal = bool(re.search(r"[.!?;:]", first))
    first_has_cjk_terminal = bool(re.search(r"[。！？；：]", first))
    remaining_has_ascii_terminal = bool(
        re.search(r"[.!?;:]", joined_remaining)
    )
    remaining_has_cjk_terminal = bool(
        re.search(r"[。！？；：]", joined_remaining)
    )
    if first_has_ascii_terminal and remaining_has_cjk_terminal:
        return first, joined_remaining
    if first_has_cjk_terminal and remaining_has_ascii_terminal:
        return " ".join(remaining), first
    return (" ".join(remaining) if remaining else first), first


def parse_srt(path: str | Path) -> list[Cue]:
    text = Path(path).read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: list[Cue] = []
    speaker = "male"
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_s, end_s = [part.strip() for part in lines[1].split("-->")]
        payload = lines[2:]
        en, zh = _split_bilingual_srt_payload(payload)
        cues.append(Cue(len(cues) + 1, parse_ts(start_s), parse_ts(end_s), en, zh, speaker))
        if len(en.split()) >= 4 or en.endswith("?"):
            speaker = "female" if speaker == "male" else "male"
    return cues


def attach_article_word_timing(cues: list[Cue], subtitle_path: str | Path) -> bool:
    """Attach only verified frozen-ledger timings for renderer page planning.

    The SRT remains the display source.  The adjacent stable manifest supplies
    timing evidence only after its final cue records agree with that SRT.
    """
    for cue in cues:
        cue.subtitle_id = ""
        cue.word_timing = ()
        cue.article_page_plan = None
        cue.display_page_translations = None
        cue.display_boundary_evidence = None

    manifest_path = Path(subtitle_path).parent / "stable-final-manifest.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stable_path = Path(
            str((manifest.get("paths") or {}).get("original_top_srt") or "")
        )
        if Path(subtitle_path).resolve() != stable_path.resolve():
            return False
        if not validate_manifest_artifact(
            manifest,
            "original_top_srt",
            stable_path,
        ):
            return False
        timeline_path = Path(str(manifest.get("final_cue_timeline_path") or ""))
        if not timeline_path.is_file():
            return False
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        ledger_path = timeline_path.with_name("word-ledger.json")
        manifest_ledger_path = str(manifest.get("word_ledger_path") or "")
        if manifest_ledger_path and Path(manifest_ledger_path).resolve() != ledger_path.resolve():
            return False
        expected_timeline_sha256 = str(
            manifest.get("final_cue_timeline_sha256") or ""
        )
        expected_ledger_sha256 = str(manifest.get("word_ledger_sha256") or "")
        if expected_timeline_sha256 and file_sha256(timeline_path) != expected_timeline_sha256:
            return False
        if expected_ledger_sha256 and file_sha256(ledger_path) != expected_ledger_sha256:
            return False
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        boundary_evidence: Mapping[str, object] | None = None
        boundary_path_value = str(
            manifest.get("display_boundary_evidence_path") or ""
        )
        if boundary_path_value:
            boundary_path = Path(boundary_path_value)
            if not boundary_path.is_absolute():
                boundary_path = manifest_path.parent / boundary_path
            expected_boundary_sha256 = str(
                manifest.get("display_boundary_evidence_sha256") or ""
            )
            if (
                not boundary_path.is_file()
                or not expected_boundary_sha256
                or file_sha256(boundary_path) != expected_boundary_sha256
            ):
                return False
            boundary_artifact = json.loads(
                boundary_path.read_text(encoding="utf-8")
            )
            raw_boundaries = boundary_artifact.get("boundaries")
            if not isinstance(raw_boundaries, Mapping):
                return False
            boundary_evidence = raw_boundaries
        records = list(timeline.get("records") or [])
        words = list(ledger.get("words") or [])
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Article renderer could not load frozen word timing: %s", exc)
        return False

    if len(records) != len(cues) or not words:
        return False
    attached: list[tuple[Cue, str, tuple[dict, ...], dict[str, dict] | None]] = []
    seen_subtitle_ids: set[str] = set()
    previous_word_end = -1
    for cue, record in zip(cues, records):
        try:
            subtitle_id = str(record["subtitle_id"])
            word_start = int(record["word_start"])
            word_end = int(record["word_end"])
            record_start = int(record["start_ms"]) / 1000.0
            record_end = int(record["end_ms"]) / 1000.0
        except (KeyError, TypeError, ValueError):
            return False
        if (
            not re.fullmatch(r"S\d{4,}", subtitle_id)
            or subtitle_id in seen_subtitle_ids
            or word_start != previous_word_end + 1
            or word_end < word_start
            or word_end >= len(words)
            or abs(record_start - cue.start) > 0.005
            or abs(record_end - cue.end) > 0.005
        ):
            return False
        timed_words: list[dict] = []
        for word_id, word in enumerate(
            words[word_start : word_end + 1],
            start=word_start,
        ):
            try:
                timed_words.append(
                    {
                        "word_id": word_id,
                        "surface": str(word["surface"]),
                        "start": int(word["start_ms"]) / 1000.0,
                        "end": int(word["end_ms"]) / 1000.0,
                    }
                )
            except (KeyError, TypeError, ValueError):
                return False
        cue_tokens = [
            re.sub(r"[^a-z0-9']", "", token.lower())
            for token in cue.en.split()
        ]
        ledger_tokens = [
            re.sub(r"[^a-z0-9']", "", word["surface"].lower())
            for word in timed_words
        ]
        if not cue_tokens or cue_tokens != ledger_tokens:
            return False
        if (
            not timed_words
            or float(timed_words[0]["start"]) < cue.start - 0.005
            or float(timed_words[-1]["end"]) > cue.end + 0.005
        ):
            return False
        cue_boundary_evidence: dict[str, dict] | None = None
        if boundary_evidence is not None:
            cue_boundary_evidence = {}
            for boundary_word_id in range(word_start + 1, word_end + 1):
                raw_boundary = boundary_evidence.get(str(boundary_word_id))
                if not isinstance(raw_boundary, Mapping):
                    return False
                cue_boundary_evidence[str(boundary_word_id)] = dict(raw_boundary)
        seen_subtitle_ids.add(subtitle_id)
        previous_word_end = word_end
        attached.append(
            (cue, subtitle_id, tuple(timed_words), cue_boundary_evidence)
        )

    if previous_word_end != len(words) - 1:
        return False

    for cue, subtitle_id, timed_words, cue_boundary_evidence in attached:
        cue.subtitle_id = subtitle_id
        cue.word_timing = timed_words
        cue.display_boundary_evidence = cue_boundary_evidence
    return True


def get_duration(media_path: str | Path) -> float:
    result = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-i", str(media_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        detail = result.stderr.strip()[-2000:]
        suffix = f"：{detail}" if detail else ""
        raise RuntimeError(f"无法读取音频/视频时长{suffix}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def fit_cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    iw, ih = img.size
    sw, sh = size
    scale = max(sw / iw, sh / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    return img.crop(((nw - sw) // 2, (nh - sh) // 2, (nw + sw) // 2, (nh + sh) // 2))


def fit_contain(img: Image.Image, size: tuple[int, int], fill=(232, 237, 243)) -> Image.Image:
    iw, ih = img.size
    sw, sh = size
    scale = min(sw / iw, sh / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (sw, sh), fill)
    canvas.paste(resized, ((sw - nw) // 2, (sh - nh) // 2))
    return canvas


def make_base(background_path: str | Path | None = None) -> Image.Image:
    bg_path = Path(background_path) if background_path else BACKGROUND
    if not bg_path.exists():
        bg_path = BACKGROUND
    bg = fit_cover(Image.open(bg_path).convert("RGB"), (WIDTH, HEIGHT))
    bg = bg.filter(ImageFilter.GaussianBlur(10))
    bg = ImageEnhance.Contrast(bg).enhance(0.84)
    img = bg.convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay, "RGBA")
    d.rectangle((0, 0, WIDTH, HEIGHT), fill=(6, 21, 38, 175))
    for y in range(HEIGHT):
        alpha = int(22 + 132 * (y / HEIGHT))
        d.line((0, y, WIDTH, y), fill=(6, 21, 38, alpha))
    img = Image.alpha_composite(img, overlay)
    noise = Image.effect_noise((WIDTH, HEIGHT), 1.6).convert("L")
    noise = ImageChops.add(noise, Image.new("L", (WIDTH, HEIGHT), 128), scale=1.0, offset=-128)
    noise_rgba = Image.merge("RGBA", (noise, noise, noise, Image.new("L", (WIDTH, HEIGHT), 18)))
    return Image.alpha_composite(img, noise_rgba)


def make_article_image(background_path: str | Path | None, size: tuple[int, int]) -> Image.Image:
    bg_path = Path(background_path) if background_path else None
    if bg_path and bg_path.exists():
        try:
            return fit_cover(Image.open(bg_path).convert("RGB"), size)
        except Exception:
            pass
    placeholder = Image.new("RGB", size, (220, 234, 246))
    d = ImageDraw.Draw(placeholder, "RGBA")
    w, h = size
    d.rectangle((0, int(h * 0.64), w, h), fill=(200, 216, 232, 255))
    d.ellipse((int(w * 0.68), int(h * 0.18), int(w * 0.83), int(h * 0.42)), fill=(255, 255, 255, 210))
    fnt = font(FONT_GANTARI, max(24, int(w * 0.035)), 650)
    d.text((int(w * 0.07), int(h * 0.40)), "Article image area", font=fnt, fill=(16, 35, 61, 255))
    return placeholder


def crop_circle(src: Image.Image, box: tuple[int, int, int, int], size: int) -> Image.Image:
    crop = src.crop(box).resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(crop, (0, 0), mask)
    return out


def make_avatars() -> tuple[Image.Image, Image.Image]:
    src = Image.open(AVATAR_SOURCE).convert("RGBA")
    return (
        crop_circle(src, (218, 208, 690, 704), scx(165)),
        crop_circle(src, (968, 204, 1464, 704), scx(176)),
    )


def draw_avatar(img: Image.Image, avatar: Image.Image, x: int, y: int) -> None:
    img.alpha_composite(avatar, (x, y))
    d = ImageDraw.Draw(img, "RGBA")
    w, h = avatar.size
    d.ellipse((x, y, x + w - 1, y + h - 1), outline=(245, 248, 255, 235), width=2)


def draw_stroked_text(
    draw: ImageDraw.ImageDraw,
    xy,
    text: str,
    fnt,
    fill,
    anchor=None,
    stroke_width: int = 2,
    stroke_fill=(0, 0, 0, 210),
) -> None:
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)


def draw_subtitle_shadowed_text(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    xy,
    text: str,
    fnt,
    fill,
    anchor=None,
    alpha: int = 255,
) -> None:
    shadow_alpha = round(SUBTITLE_EN_SHADOW[3] * max(0, min(255, alpha)) / 255)
    x, y = xy
    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer, "RGBA")
    shadow_draw.text(
        (x + scx(1), y + scy(4)),
        text,
        font=fnt,
        fill=(0, 0, 0, shadow_alpha),
        anchor=anchor,
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(SUBTITLE_EN_SHADOW_BLUR))
    img.alpha_composite(shadow_layer)
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)


def with_alpha(color: tuple[int, int, int, int], alpha: int) -> tuple[int, int, int, int]:
    alpha = max(0, min(255, alpha))
    return (color[0], color[1], color[2], round(color[3] * alpha / 255))


def fade_alpha(cue: Cue | None, t: float) -> int:
    if not cue:
        return 0
    fade = min(SUBTITLE_FADE_SECONDS, max((cue.end - cue.start) / 3, 0.05))
    fade_in = min(1.0, max(0.0, (t - cue.start) / fade))
    eased = fade_in
    eased = eased * eased * (3 - 2 * eased)
    return round(SUBTITLE_MIN_ALPHA + (255 - SUBTITLE_MIN_ALPHA) * eased)


def rounded_blur_card(img: Image.Image, rect: tuple[int, int, int, int], radius: int, tint=(0, 0, 0, 28)) -> None:
    x0, y0, x1, y1 = rect
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow, "RGBA").rounded_rectangle(
        (x0, y0 + scy(5), x1, y1 + scy(5)),
        radius=radius,
        fill=(0, 0, 0, 72),
    )
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(scx(10))))
    crop = img.crop(rect).filter(ImageFilter.GaussianBlur(15))
    crop = Image.alpha_composite(crop, Image.new("RGBA", crop.size, tint))
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, crop.size[0] - 1, crop.size[1] - 1), radius=radius, fill=255)
    img.paste(crop, (x0, y0), mask)
    ImageDraw.Draw(img, "RGBA").rounded_rectangle(rect, radius=radius, outline=(255, 255, 255, 135), width=1)


def find_vocab(en: str) -> dict | None:
    lower = en.lower()
    for item in VOCAB:
        for key in item["keys"]:
            if re.search(rf"\b{re.escape(key)}\b", lower):
                return {**item, "key": key}
    return None


def subtitle_hash(cues: list[Cue]) -> str:
    raw = "\n".join(f"{cue.index}\t{cue.en}\t{cue.zh}" for cue in cues)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def vocab_source_hash(cues: list[Cue]) -> str:
    raw = "\n".join(f"{cue.index}\t{cue.en}" for cue in cues)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_vocab_semantic_groups(cues: list[Cue]) -> list[VocabSemanticGroup]:
    """Build conservative local learning groups without changing subtitles.

    A terminal punctuation mark is the primary boundary.  A real pause and a
    bounded group length keep incomplete ASR punctuation from producing one
    oversized request to the vocabulary model.
    """
    groups: list[VocabSemanticGroup] = []
    pending: list[Cue] = []

    def flush() -> None:
        if not pending:
            return
        position = len(groups) + 1
        groups.append(
            VocabSemanticGroup(
                id=f"VG{position:04d}",
                cue_indices=tuple(cue.index for cue in pending),
                start=pending[0].start,
                end=pending[-1].end,
                english=" ".join(cue.en.strip() for cue in pending if cue.en.strip()),
            )
        )
        pending.clear()

    for cue in cues:
        if pending:
            previous = pending[-1]
            has_pause = cue.start - previous.end >= VOCAB_GROUP_SILENCE_SECONDS
            too_long = (
                len(pending) >= VOCAB_GROUP_MAX_CUES
                or cue.end - pending[0].start >= VOCAB_GROUP_MAX_SECONDS
            )
            if has_pause or too_long:
                flush()
        pending.append(cue)
        if re.search(r"[.!?][\"')\]]*$", cue.en.strip()):
            flush()
    flush()
    return groups


def current_llm_config() -> tuple[str, str, str]:
    from app.common.config import cfg

    service = cfg.llm_service.value
    if service == LLMServiceEnum.OPENAI:
        return cfg.openai_api_base.value, cfg.openai_api_key.value, cfg.openai_model.value
    if service == LLMServiceEnum.SILICON_CLOUD:
        return cfg.silicon_cloud_api_base.value, cfg.silicon_cloud_api_key.value, cfg.silicon_cloud_model.value
    if service == LLMServiceEnum.DEEPSEEK:
        return cfg.deepseek_api_base.value, cfg.deepseek_api_key.value, cfg.deepseek_model.value
    if service == LLMServiceEnum.OLLAMA:
        return cfg.ollama_api_base.value, cfg.ollama_api_key.value, cfg.ollama_model.value
    if service == LLMServiceEnum.LM_STUDIO:
        return cfg.lm_studio_api_base.value, cfg.lm_studio_api_key.value, cfg.lm_studio_model.value
    if service == LLMServiceEnum.GEMINI:
        return cfg.gemini_api_base.value, cfg.gemini_api_key.value, cfg.gemini_model.value
    if service == LLMServiceEnum.CHATGLM:
        return cfg.chatglm_api_base.value, cfg.chatglm_api_key.value, cfg.chatglm_model.value
    if service == LLMServiceEnum.PUBLIC:
        return cfg.public_api_base.value, cfg.public_api_key.value, cfg.public_model.value
    return "", "", ""


def extract_json_array(text: str):
    match = re.search(r"\[[\s\S]*\]", text or "")
    if not match:
        raise ValueError("LLM did not return a JSON array")
    return repair_json_loads(match.group(0))


def vocab_card_priority(item: dict) -> int:
    """Normalize the model's editorial priority to a small stable range."""
    try:
        return max(1, min(5, int(item.get("priority", 3))))
    except (TypeError, ValueError):
        return 3


def vocab_card_type(item: dict) -> str:
    """Only explicit concept terms receive the expanded learning-card layout."""
    return "concept" if str(item.get("card_type") or "").strip().lower() == "concept" else "standard"


def find_vocab_source_phrase(cue_text: str, candidate: object) -> str:
    """Return the source subtitle surface form for a model-selected expression."""
    phrase = re.sub(r"\s+", " ", str(candidate or "").strip())
    if not phrase:
        return ""
    pattern = re.escape(phrase).replace(r"\ ", r"\s+")
    if phrase[0].isalnum():
        pattern = r"(?<![A-Za-z0-9'-])" + pattern
    if phrase[-1].isalnum():
        pattern += r"(?![A-Za-z0-9'-])"
    match = re.search(pattern, cue_text, flags=re.IGNORECASE)
    return match.group(0) if match else ""


def compact_vocab_meaning(value: object) -> str:
    """Keep the card's primary gloss short; detailed context belongs in IN CONTEXT."""
    meaning = str(value or "").strip()
    meaning = re.sub(r"^(?:n|v|adj|adv|prep|conj)\.?\s*", "", meaning, flags=re.IGNORECASE)
    # Parenthetical material is useful context, but turns the main card into a
    # paragraph. The detailed card still has definition and Tip for that work.
    meaning = re.sub(r"[（(][^（）()]*[）)]", "", meaning).strip()
    meaning = re.sub(r"\s+", " ", meaning).strip(" ：:；;，,、/ ")
    if not meaning:
        return ""

    # Two compact senses are enough for a learning card. Prefer semantic breaks
    # to a raw character cutoff so the rendered phrase remains readable.
    senses = [
        part.strip()
        for part in re.split(r"[；;/／]", meaning)
        if part.strip()
    ]
    compact = "；".join(senses[:2]) if senses else meaning
    if len(compact) <= 18:
        return compact
    return senses[0] if senses and len(senses[0]) <= 18 else compact[:18].rstrip("，、； ")


def normalize_vocab_plan(
    raw_items,
    cues: list[Cue],
    groups: list[VocabSemanticGroup] | None = None,
) -> dict[int, dict]:
    cue_by_index = {cue.index: cue for cue in cues}
    groups = groups or build_vocab_semantic_groups(cues)
    group_by_id = {group.id: group for group in groups}
    group_by_cue = {
        cue_index: group
        for group in groups
        for cue_index in group.cue_indices
    }
    plan: dict[int, dict] = {}
    if not isinstance(raw_items, list):
        return plan
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            cue_index = int(item.get("cue_index"))
        except Exception:
            continue
        group_id = str(item.get("group_id") or "").strip()
        group = group_by_id.get(group_id) if group_id else group_by_cue.get(cue_index)
        cue = cue_by_index.get(cue_index)
        phrase_candidate = item.get("phrase") or item.get("word")
        meaning = compact_vocab_meaning(item.get("meaning"))
        card_type = vocab_card_type(item)
        detail = str(
            item.get("detail")
            or item.get("concept_note")
            or item.get("collocation")
            or ""
        ).strip()[:72]
        if not group or not cue or cue_index not in group.cue_indices or not meaning:
            continue
        phrase = find_vocab_source_phrase(cue.en, phrase_candidate)
        phrase_terms = re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)?", phrase.lower())
        if not phrase_terms or len(phrase_terms) > 8 or len(phrase) > 56:
            continue
        if all(term in COMMON_WORDS for term in phrase_terms):
            continue
        key = phrase.lower()
        plan[cue.index] = {
            "keys": [key],
            "key": key,
            "group_id": group.id,
            "group_cue_indices": list(group.cue_indices),
            "group_start": group.start,
            "group_end": group.end,
            "group_english": group.english,
            "word": phrase,
            "priority": vocab_card_priority(item),
            "card_type": card_type,
            "meaning": meaning,
            "detail": detail if card_type == "concept" or detail else "",
        }
    return plan


def fallback_episode_vocab_indices(plan: dict[int, dict], limit: int = 3) -> list[int]:
    """Choose a balanced, stable opening vocabulary set without another LLM call."""
    level_score = {
        "专业词": 6,
        "GRE": 5,
        "TOEFL": 4,
        "IELTS": 3,
        "CET-6": 2,
        "CET-4": 1,
    }
    def candidate_score(pair: tuple[int, dict]) -> tuple[float, float, float]:
        _, item = pair
        word_length = len(str(item.get("word") or ""))
        # Longer is not inherently more useful for a learner. Penalize only
        # overlong display words while retaining genuinely advanced concepts.
        length_penalty = max(0, word_length - 13) * 0.65
        return (
            level_score.get(str(item.get("level") or ""), 0) - length_penalty,
            -abs(word_length - 10),
            -float(item.get("display_start", math.inf)),
        )

    ranked = sorted(plan.items(), key=candidate_score, reverse=True)
    selected: list[int] = []
    used_pos: set[str] = set()
    used_levels: set[str] = set()
    advanced_count = 0

    for cue_index, item in ranked:
        level = str(item.get("level") or "")
        pos = str(item.get("pos") or "").split(".", 1)[0].lower()
        is_advanced = level in {"专业词", "GRE", "TOEFL"}
        # The opening should explain the episode, not become three unusually
        # long test words. One advanced term is enough for a three-word index.
        if is_advanced and advanced_count >= 1:
            continue
        if pos and pos in used_pos and len(selected) < limit - 1:
            continue
        if level and level in used_levels and len(selected) < limit - 1:
            continue
        selected.append(cue_index)
        used_pos.add(pos)
        used_levels.add(level)
        advanced_count += int(is_advanced)
        if len(selected) == limit:
            return selected

    for cue_index, _ in ranked:
        if cue_index not in selected:
            selected.append(cue_index)
        if len(selected) == limit:
            break
    return selected


def apply_episode_vocab_ranks(plan: dict[int, dict], cue_indices: list[int]) -> dict[int, dict]:
    valid = []
    seen: set[int] = set()
    for cue_index in cue_indices:
        if cue_index in plan and cue_index not in seen:
            valid.append(cue_index)
            seen.add(cue_index)
        if len(valid) == 3:
            break
    if len(valid) < 3:
        valid.extend(
            cue_index
            for cue_index in fallback_episode_vocab_indices(plan)
            if cue_index not in seen
        )
    for rank, cue_index in enumerate(valid[:3], 1):
        plan[cue_index]["episode_rank"] = rank
    return plan


def select_episode_vocab_indices(
    plan: dict[int, dict],
    client: OpenAI,
    model: str,
) -> list[int]:
    """Ask one small editorial pass to choose the three words for the opener."""
    candidates = [
        {
            "cue_index": cue_index,
            "word": item.get("word"),
            "level": item.get("level"),
            "meaning": item.get("meaning"),
            "context": str(item.get("group_english") or "")[:260],
        }
        for cue_index, item in sorted(plan.items())
    ]
    prompt = f"""
你是英语学习视频的总编辑。请从候选词中为“本期重点词汇”选择最能概括全片主题、论点或关键机制的 3 个词。

要求：
- 必须只使用候选 cue_index；返回 3 个不同的 cue_index，按重要性从高到低排序。
- 优先核心概念、抽象机制和专业词；不要仅因它在前几分钟出现就优先。
- 避免同词根或近义词重复；尽量覆盖不同论点。
- 只返回 JSON 数组，例如 [{{"cue_index": 12}}, {{"cue_index": 47}}, {{"cue_index": 95}}]。

候选词：
{json.dumps(candidates, ensure_ascii=False)}
""".strip()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    raw = extract_json_array(response.choices[0].message.content or "")
    selected = []
    for item in raw if isinstance(raw, list) else []:
        try:
            cue_index = int(item.get("cue_index"))
        except Exception:
            continue
        if cue_index in plan and cue_index not in selected:
            selected.append(cue_index)
        if len(selected) == 3:
            break
    return selected if len(selected) == 3 else fallback_episode_vocab_indices(plan)


def episode_vocab_overview_items(vocab_plan: dict[int, dict], limit: int = 3) -> list[dict]:
    ranked = [
        item
        for item in vocab_plan.values()
        if isinstance(item.get("episode_rank"), int) and item["episode_rank"] > 0
    ]
    if ranked:
        return sorted(ranked, key=lambda item: item["episode_rank"])[:limit]
    return sorted(
        vocab_plan.values(),
        key=lambda item: (float(item.get("display_start", math.inf)), str(item.get("key") or "")),
    )[:limit]


def article_vocab_phrase_display_start(cue: Cue, key: str) -> float | None:
    """Return the start of the one final article page that shows the phrase."""
    plan = cue.article_page_plan
    if not plan or plan.get("status") != "ok":
        return None
    matches = [
        page
        for page in list(plan.get("pages") or [])
        if find_vocab_source_phrase(str(page.get("en") or ""), key)
    ]
    if len(matches) != 1:
        return None
    try:
        display_start = float(matches[0]["start"])
    except (KeyError, TypeError, ValueError):
        return None
    if display_start < float(cue.start) or display_start >= float(cue.end):
        return None
    return display_start


def schedule_vocab_card_plan(
    candidates: dict[int, dict],
    cues: list[Cue],
    *,
    max_cards: int = VOCAB_MAX_CARDS_PER_EPISODE,
    align_to_article_pages: bool = False,
) -> dict[int, dict]:
    """Select strong cards across the episode and start them on their own cue."""
    cue_by_index = {cue.index: cue for cue in cues}
    groups = build_vocab_semantic_groups(cues)
    group_by_cue = {
        cue_index: group
        for group in groups
        for cue_index in group.cue_indices
    }
    display_starts: dict[int, float] = {}
    eligible: list[tuple[int, dict, Cue, VocabSemanticGroup, str]] = []
    for cue_index, item in candidates.items():
        cue = cue_by_index.get(cue_index)
        key = str(item.get("key") or "").strip().lower()
        group = group_by_cue.get(cue_index)
        if not cue or not key or not group:
            continue
        # Scores 1-2 let the model report a marginal candidate without making
        # it eligible merely to fill a time bucket.
        if vocab_card_priority(item) < 3:
            continue
        display_start = float(cue.start)
        if align_to_article_pages:
            display_start = article_vocab_phrase_display_start(cue, key)
            if display_start is None:
                continue
        display_starts[cue_index] = display_start
        eligible.append((cue_index, item, cue, group, key))

    card_limit = min(max(0, max_cards), len(eligible))
    if card_limit <= 0:
        return {}

    episode_start = min(cue.start for cue in cues)
    episode_end = max(cue.end for cue in cues)
    episode_duration = max(0.0, episode_end - episode_start)
    bucket_count = card_limit if episode_duration > 0 else 1
    buckets: list[list[tuple[int, dict, Cue, VocabSemanticGroup, str]]] = [
        [] for _ in range(bucket_count)
    ]
    for entry in eligible:
        display_start = display_starts[entry[0]]
        if episode_duration <= 0:
            bucket_index = 0
        else:
            relative = max(0.0, min(1.0, (display_start - episode_start) / episode_duration))
            bucket_index = min(bucket_count - 1, int(relative * bucket_count))
        buckets[bucket_index].append(entry)

    scheduled: list[tuple[int, dict, Cue, VocabSemanticGroup, str]] = []
    selected_starts: list[float] = []
    selected_keys: set[str] = set()
    selected_cue_indices: set[int] = set()

    def try_schedule(entry: tuple[int, dict, Cue, VocabSemanticGroup, str]) -> bool:
        cue_index, _, _, _, key = entry
        display_start = display_starts[cue_index]
        if cue_index in selected_cue_indices or key in selected_keys:
            return False
        if any(
            abs(display_start - selected_start) < VOCAB_MIN_CARD_INTERVAL_SECONDS
            for selected_start in selected_starts
        ):
            return False
        scheduled.append(entry)
        selected_cue_indices.add(cue_index)
        selected_keys.add(key)
        selected_starts.append(display_start)
        return True

    # One strong candidate per timeline stratum prevents an opening cluster
    # from consuming the entire episode budget. Empty strata stay empty rather
    # than admitting a low-value word merely to meet the target count.
    for bucket in buckets:
        for entry in sorted(
            bucket,
            key=lambda value: (
                -vocab_card_priority(value[1]),
                display_starts[value[0]],
                value[0],
            ),
        ):
            if try_schedule(entry):
                break

    # If some strata had no candidate, fill the remaining budget with the best
    # valid expressions while preferring distance from cards already selected.
    while len(scheduled) < card_limit:
        remaining = [
            entry
            for entry in eligible
            if entry[0] not in selected_cue_indices and entry[4] not in selected_keys
            and all(
                abs(display_starts[entry[0]] - selected_start)
                >= VOCAB_MIN_CARD_INTERVAL_SECONDS
                for selected_start in selected_starts
            )
        ]
        if not remaining:
            break
        entry = min(
            remaining,
            key=lambda value: (
                -vocab_card_priority(value[1]),
                -min(abs(display_starts[value[0]] - start) for start in selected_starts),
                display_starts[value[0]],
                value[0],
            ),
        )
        try_schedule(entry)

    detailed_concepts = {
        entry[0]
        for entry in sorted(
            (entry for entry in scheduled if vocab_card_type(entry[1]) == "concept"),
            key=lambda value: (
                -vocab_card_priority(value[1]),
                float(value[1].get("group_start", math.inf)),
                value[0],
            ),
        )[:VOCAB_MAX_CONCEPT_CARDS_PER_EPISODE]
    }

    plan: dict[int, dict] = {}
    for cue_index, item, _, group, _ in sorted(
        scheduled,
        key=lambda entry: (display_starts[entry[0]], entry[0]),
    ):
        scheduled_item = dict(item)
        if vocab_card_type(scheduled_item) == "concept" and cue_index not in detailed_concepts:
            scheduled_item["card_type"] = "standard"
            scheduled_item["detail"] = ""
        scheduled_item["group_id"] = group.id
        scheduled_item["group_cue_indices"] = list(group.cue_indices)
        # A card cannot foreshadow the word before its own subtitle appears.
        # It stays visible until the next card replaces it.
        scheduled_item["display_start"] = display_starts[cue_index]
        scheduled_item["display_id"] = f"{cue_index}:{scheduled_item['key']}"
        plan[cue_index] = scheduled_item

    return plan


def vocabulary_card_target(cues: list[Cue]) -> int:
    """Return a calm, duration-aware target for expression-based vocabulary cards."""
    if not cues:
        return 0
    duration = max(cue.end for cue in cues) - min(cue.start for cue in cues)
    return max(
        VOCAB_MIN_CARDS_PER_EPISODE,
        min(VOCAB_MAX_CARDS_PER_EPISODE, round(duration / 60.0 * VOCAB_CARDS_PER_MINUTE)),
    )


def vocab_card_display_state(
    vocab_plan: dict[int, dict] | None,
    cue: Cue | None,
    display_time: float | None = None,
) -> tuple[dict | None, str]:
    """Return the active card and its visual state for a given render time."""
    if not vocab_plan:
        return None, "hidden"

    timestamp = display_time if display_time is not None else (cue.start if cue else None)
    if timestamp is None:
        return None, "hidden"

    previous = [
        item for item in vocab_plan.values()
        if float(item.get("display_start", math.inf)) <= timestamp
    ]
    if not previous:
        return None, "hidden"
    item = max(previous, key=lambda value: float(value.get("display_start", -math.inf)))
    return item, "full"


def active_vocab_card(
    vocab_plan: dict[int, dict] | None,
    cue: Cue | None,
    display_time: float | None = None,
) -> dict | None:
    """Compatibility helper for callers that only need the current card."""
    return vocab_card_display_state(vocab_plan, cue, display_time)[0]


def opening_card_transition_progress(
    vocab_plan: dict[int, dict] | None,
    vocab: dict | None,
    vocab_state: str,
    display_time: float | None,
) -> float | None:
    """Return the title-to-first-card crossfade progress, if it is active."""
    if not vocab_plan or not vocab or vocab_state != "full" or display_time is None:
        return None
    first_start = min(float(item.get("display_start", math.inf)) for item in vocab_plan.values())
    current_start = float(vocab.get("display_start", math.inf))
    if current_start != first_start:
        return None
    elapsed = display_time - first_start
    if elapsed < 0 or elapsed >= VOCAB_OPENING_CARD_TRANSITION_SECONDS:
        return None
    return max(0.0, min(1.0, elapsed / VOCAB_OPENING_CARD_TRANSITION_SECONDS))


def split_vocab_groups_for_requests(
    groups: list[VocabSemanticGroup],
    max_groups: int = 40,
    max_chars: int = 16000,
) -> list[list[VocabSemanticGroup]]:
    """Keep vocabulary requests bounded while preserving complete groups."""
    chunks: list[list[VocabSemanticGroup]] = []
    current: list[VocabSemanticGroup] = []
    current_chars = 0
    for group in groups:
        group_chars = len(group.english) + 80
        if current and (len(current) >= max_groups or current_chars + group_chars > max_chars):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(group)
        current_chars += group_chars
    if current:
        chunks.append(current)
    return chunks


def order_vocab_request_chunks(
    chunks: list[list[VocabSemanticGroup]],
) -> list[list[VocabSemanticGroup]]:
    """Interleave the timeline so a partial run is not front-loaded."""
    if len(chunks) < 3:
        return list(chunks)

    indices = [0, len(chunks) - 1]
    intervals = deque([(0, len(chunks) - 1)])
    while intervals:
        left, right = intervals.popleft()
        middle = (left + right) // 2
        if middle not in indices:
            indices.append(middle)
        if middle - left > 1:
            intervals.append((left, middle))
        if right - middle > 1:
            intervals.append((middle, right))
    return [chunks[index] for index in indices]


def vocab_request_chunk_id(groups: list[VocabSemanticGroup]) -> str:
    """Return a stable content ID for one vocabulary request batch."""
    payload = [
        {
            "group_id": group.id,
            "cue_indices": list(group.cue_indices),
            "english": group.english,
        }
        for group in groups
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"VC{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def vocab_progress_cache_path(cache_path: str | Path) -> Path:
    """Keep resumable state beside, but separate from, the display cache."""
    path = Path(cache_path)
    return path.with_name(
        f"{path.stem}.v{VOCAB_CACHE_SCHEMA_VERSION}.progress{path.suffix}"
    )


def atomic_write_vocab_cache(path: str | Path, payload: Mapping[str, object]) -> bool:
    """Atomically replace a cache file without damaging its previous value."""
    target = Path(path)
    temporary_path: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.replace(target)
        return True
    except Exception as exc:
        logger.warning("Unable to atomically write vocabulary cache %s: %s", target, exc)
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def _read_vocab_progress_cache(
    path: Path,
    *,
    source_hash: str,
    model: str,
    chunk_order: list[str],
    chunks_by_id: Mapping[str, list[VocabSemanticGroup]],
) -> dict | None:
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(cached, Mapping) or (
        cached.get("cache_schema_version") != VOCAB_CACHE_SCHEMA_VERSION
        or cached.get("source_hash") != source_hash
        or cached.get("prompt_version") != VOCAB_PROMPT_VERSION
        or cached.get("model") != model
        or cached.get("chunk_order") != chunk_order
    ):
        return None

    completed_raw = cached.get("completed_chunk_ids")
    cached_chunks = cached.get("chunks")
    if not isinstance(completed_raw, list) or not isinstance(cached_chunks, Mapping):
        return None
    completed = [str(chunk_id) for chunk_id in completed_raw]
    if len(completed) != len(set(completed)) or any(
        chunk_id not in chunks_by_id for chunk_id in completed
    ):
        return None

    normalized_chunks: dict[str, dict] = {}
    for chunk_id in completed:
        entry = cached_chunks.get(chunk_id)
        groups = chunks_by_id[chunk_id]
        expected_group_ids = [group.id for group in groups]
        if not isinstance(entry, Mapping) or entry.get("group_ids") != expected_group_ids:
            return None
        cards = entry.get("cards")
        if not isinstance(cards, list) or any(not isinstance(card, dict) for card in cards):
            return None
        if any(str(card.get("group_id") or "") not in expected_group_ids for card in cards):
            return None
        normalized_chunks[chunk_id] = {
            "group_ids": expected_group_ids,
            "cards": [dict(card) for card in cards],
        }

    is_complete = set(completed) == set(chunk_order)
    if not isinstance(cached.get("complete"), bool) or cached.get("complete") != is_complete:
        return None
    return {
        "cache_schema_version": VOCAB_CACHE_SCHEMA_VERSION,
        "source_hash": source_hash,
        "prompt_version": VOCAB_PROMPT_VERSION,
        "model": model,
        "complete": is_complete,
        "chunk_order": list(chunk_order),
        "completed_chunk_ids": completed,
        "chunks": normalized_chunks,
    }


def _vocab_cards_from_progress(payload: Mapping[str, object]) -> list[dict]:
    cards: list[dict] = []
    chunks = payload.get("chunks")
    if not isinstance(chunks, Mapping):
        return cards
    for chunk_id in payload.get("chunk_order") or []:
        entry = chunks.get(str(chunk_id))
        if isinstance(entry, Mapping):
            cards.extend(
                dict(card)
                for card in entry.get("cards") or []
                if isinstance(card, dict)
            )
    return cards


def build_vocab_selection_prompt(groups: list[VocabSemanticGroup], max_cards: int) -> str:
    serialized_groups = [
        {
            "group_id": group.id,
            "cue_indices": list(group.cue_indices),
            "english": group.english,
        }
        for group in groups
    ]
    return f"""
你是英语学习视频的词汇编辑。下面每一项都是一个已冻结的英文语义组。

要求：
- 每个语义组最多选择 1 个表达；本批最多返回 {max_cards} 个表达。没有真正值得学习的表达时可以不返回该组。
- 只有该批确实没有任何合格学习词时才返回空数组；只要有符合条件的实词，至少返回 1 个。
- 词必须承担当前论点、机制、关键判断，或具有不能直接从字面猜出的语境义。仅仅“词长、考试难度高”不是入选理由。
- 避免普通副词、基础动作、一般文学名词和标点名称；除非它正是当前讨论对象或不懂它会误解结论。
- priority 用 1-5 表示学习必要性：5=理解意群核心结论不可缺少，4=关键机制或非透明语境义，3=明显有学习价值，1-2=通常不应入选。按 priority 从高到低返回。
- 不选择口头语、基础词、专有名词、数字、缩略词或只靠上下文才成立的词。
- phrase 必须是 cue_index 对应英文字幕中的连续原文，逐字保留原句写法；优先固定搭配、短语或完整概念，最多 8 个英文词。不要为了词典化而改写原文。
- cue_index 必须是 phrase 实际出现的字幕序号，phrase 不能跨字幕行。
- 不要为了凑数量选词。单词卡会从对应字幕出现时开始展示，先显示完整讲解卡，随后缩为复习条。
- meaning 只写当前语境的主释义：2-14 个汉字，最多两个核心义项（用；分隔）；禁止词性前缀、括号解释、例句或完整句。
- card_type 只能是 standard 或 concept。standard 是默认；只有字面翻译无法理解的文化、技术、经济或抽象概念才用 concept。
- detail：standard 可留空，只有存在明显迁移价值时才写一条简短英文搭配；concept 必须写一条不超过 28 个汉字的中文解释，说明它在当前语境中的实际概念。detail 不得重复 meaning。
- 不要生成音标、词性、考试标签、英文词典释义、IN CONTEXT 标签、词源或长语法说明。
- 只返回 JSON 数组，不要解释；每个对象必须包含 group_id、cue_index、phrase、priority、card_type、meaning、detail。

语义组：
{json.dumps(serialized_groups, ensure_ascii=False)}
""".strip()


def load_or_generate_vocab_plan(
    subtitle_path: str | Path,
    cues: list[Cue],
    enabled: bool,
    progress_callback=None,
    *,
    align_to_article_pages: bool = False,
) -> dict[int, dict]:
    if not enabled:
        return {}

    groups = build_vocab_semantic_groups(cues)
    if not groups:
        return {}
    episode_card_target = vocabulary_card_target(cues)
    source_hash = vocab_source_hash(cues)
    cache_path = Path(subtitle_path).with_suffix(".vocab_cards.json")
    global_cache_dir = CACHE_PATH / "podcast_vocab_cards"
    global_cache_path = global_cache_dir / f"{source_hash}.json"
    formal_cache_paths = (cache_path, global_cache_path)
    progress_cache_paths = tuple(
        vocab_progress_cache_path(candidate) for candidate in formal_cache_paths
    )
    base_url, api_key, model = current_llm_config()

    request_groups = order_vocab_request_chunks(
        split_vocab_groups_for_requests(
            groups,
            max_groups=VOCAB_REQUEST_MAX_GROUPS,
            max_chars=VOCAB_REQUEST_MAX_CHARS,
        )
    )
    chunk_order = [vocab_request_chunk_id(chunk) for chunk in request_groups]
    chunks_by_id = dict(zip(chunk_order, request_groups))
    progress_payload = {
        "cache_schema_version": VOCAB_CACHE_SCHEMA_VERSION,
        "source_hash": source_hash,
        "prompt_version": VOCAB_PROMPT_VERSION,
        "model": model,
        "complete": False,
        "chunk_order": chunk_order,
        "completed_chunk_ids": [],
        "chunks": {},
    }

    def make_plan(cards: list[dict]) -> dict[int, dict]:
        plan = schedule_vocab_card_plan(
            normalize_vocab_plan(cards, cues, groups),
            cues,
            max_cards=episode_card_target,
            align_to_article_pages=align_to_article_pages,
        )
        if not plan:
            return {}
        return apply_episode_vocab_ranks(
            plan,
            fallback_episode_vocab_indices(plan),
        )

    for candidate in (*formal_cache_paths, *progress_cache_paths):
        if not candidate.exists():
            continue
        cached_progress = _read_vocab_progress_cache(
            candidate,
            source_hash=source_hash,
            model=model,
            chunk_order=chunk_order,
            chunks_by_id=chunks_by_id,
        )
        if cached_progress is not None:
            completed = progress_payload["completed_chunk_ids"]
            progress_chunks = progress_payload["chunks"]
            for chunk_id in cached_progress["completed_chunk_ids"]:
                if chunk_id not in completed:
                    completed.append(chunk_id)
                    progress_chunks[chunk_id] = cached_progress["chunks"][chunk_id]

    completed_ids = progress_payload["completed_chunk_ids"]

    def persist_progress() -> None:
        for candidate in progress_cache_paths:
            atomic_write_vocab_cache(candidate, progress_payload)

    def incomplete_error(failures: Sequence[str]) -> VocabularyPlanIncompleteError:
        return VocabularyPlanIncompleteError(
            len(completed_ids),
            len(chunk_order),
            failures,
        )

    progress_payload["complete"] = set(completed_ids) == set(chunk_order)
    if progress_payload["complete"]:
        cards = _vocab_cards_from_progress(progress_payload)
        plan = make_plan(cards)
        for candidate in formal_cache_paths:
            atomic_write_vocab_cache(candidate, progress_payload)
        if progress_callback:
            progress_callback(4, "智能单词卡命中完整缓存")
        return plan

    if not base_url or not api_key or not model:
        persist_progress()
        if progress_callback:
            progress_callback(
                4,
                f"智能单词卡未完成（{len(completed_ids)}/{len(chunk_order)} 批）：模型未配置",
            )
        raise incomplete_error(("vocabulary model is not configured",))

    if progress_callback:
        progress_callback(1, "智能单词卡生成中")

    try:
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=VOCAB_REQUEST_TIMEOUT_SECONDS,
            # The loop below owns the one explicit retry. SDK retries turn a
            # 90-second request into several minutes without producing a card.
            max_retries=0,
        )
        failed_chunks: list[str] = []
        cards_per_request = max(1, math.ceil(episode_card_target / max(1, len(request_groups))))
        pending_chunks = [
            (chunk_id, chunks_by_id[chunk_id])
            for chunk_id in chunk_order
            if chunk_id not in completed_ids
        ]
        for chunk_id, group_chunk in pending_chunks:
            completed_count = len(completed_ids)
            if progress_callback:
                progress_callback(
                    max(1, min(3, round((completed_count + 1) * 3 / max(1, len(request_groups))))),
                    f"智能单词卡生成中（已完成 {completed_count}/{len(request_groups)} 批）",
                )
            prompt = build_vocab_selection_prompt(group_chunk, cards_per_request)
            chunk_cards = None
            last_error: Exception | None = None
            for attempt in range(1, 3):
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "Return valid JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.1,
                    )
                    chunk_cards = extract_json_array(
                        response.choices[0].message.content or ""
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Vocabulary card batch %s (%s/%s) failed on attempt %s: %s",
                        chunk_id,
                        completed_count + 1,
                        len(request_groups),
                        attempt,
                        exc,
                    )
            if isinstance(chunk_cards, list):
                # The provider occasionally ignores a batch cardinality limit.
                # Enforce it locally using the requested editorial order/priority.
                group_ids = [group.id for group in group_chunk]
                bounded_cards = sorted(
                    (
                        item
                        for item in chunk_cards
                        if isinstance(item, dict)
                        and str(item.get("group_id") or "") in group_ids
                    ),
                    key=vocab_card_priority,
                    reverse=True,
                )[:cards_per_request]
                progress_payload["chunks"][chunk_id] = {
                    "group_ids": group_ids,
                    "cards": bounded_cards,
                }
                completed_ids.append(chunk_id)
                progress_payload["complete"] = set(completed_ids) == set(chunk_order)
                persist_progress()
            else:
                failed_chunks.append(
                    f"{chunk_id}: {str(last_error or 'unknown error')[:120]}"
                )
        progress_payload["complete"] = set(completed_ids) == set(chunk_order)
        cards = _vocab_cards_from_progress(progress_payload)
        plan = make_plan(cards)
        if progress_payload["complete"]:
            for candidate in formal_cache_paths:
                atomic_write_vocab_cache(candidate, progress_payload)
        if not plan:
            logger.warning(
                "Vocabulary model returned no usable cards. raw_cards=%s failed_batches=%s complete=%s",
                len(cards),
                len(failed_chunks),
                progress_payload["complete"],
            )
        if progress_callback:
            if failed_chunks:
                progress_callback(
                    4,
                    "智能单词卡生成未完成"
                    f"（{len(completed_ids)}/{len(chunk_order)} 批），已保存进度",
                )
            elif not plan:
                progress_callback(4, "智能单词卡未选出合适单词，已跳过")
            else:
                progress_callback(4, "智能单词卡生成完成")
        if progress_payload["complete"]:
            return plan
        persist_progress()
        raise incomplete_error(failed_chunks)
    except VocabularyPlanIncompleteError:
        raise
    except Exception as exc:
        logger.exception("Vocabulary card generation failed: %s", exc)
        persist_progress()
        if progress_callback:
            progress_callback(
                4,
                "智能单词卡生成未完成"
                f"（{len(completed_ids)}/{len(chunk_order)} 批），已保存进度",
            )
        raise incomplete_error((f"generation failed: {str(exc)[:120]}",)) from exc


def _has_short_caption_line(lines: list[str]) -> bool:
    """Reject a visual orphan such as a standalone ``And`` or ``of course``."""
    return len(lines) > 1 and any(len(line.split()) < 3 for line in lines)


def _looks_like_english_modifier_boundary(previous: str, following: str) -> bool:
    """Recognize a deterministic modifier-to-head visual break.

    This deliberately uses morphology only.  The renderer has no parser or
    authority to alter frozen subtitles, so an uncertain case remains on the
    same visual page rather than risking a visible lexical split.
    """
    previous = re.sub(r"[^A-Za-z']", "", previous).lower()
    following = re.sub(r"[^A-Za-z']", "", following).lower()
    return (
        len(previous) >= 3
        and following.isalpha()
        and following not in LINE_BREAK_AVOID_BEFORE_WORDS
        and following not in ARTICLE_PAGE_OBJECT_DETERMINERS
        and following not in {"and", "but", "nor", "or", "so", "yet"}
        and not previous.endswith(ENGLISH_VISUAL_NOMINAL_SUFFIXES)
        and (
            previous in ENGLISH_VISUAL_MODIFIER_WORDS
            or previous.endswith(ENGLISH_VISUAL_MODIFIER_SUFFIXES)
        )
    )


def _looks_like_numeric_phrase_boundary(words: list[str], split: int) -> bool:
    """Keep a numeric value, its magnitude, and its following head together."""
    if split <= 0 or split >= len(words):
        return False

    def normalized(index: int) -> str:
        return re.sub(r"[^A-Za-z0-9'.]", "", words[index]).lower()

    def is_numeric_value(token: str) -> bool:
        return bool(
            re.fullmatch(r"\d+(?:[.,]\d+)?", token)
            or token
            in {
                "zero", "one", "two", "three", "four", "five", "six",
                "seven", "eight", "nine", "ten", "eleven", "twelve",
                "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
                "eighteen", "nineteen", "twenty", "thirty", "forty",
                "fifty", "sixty", "seventy", "eighty", "ninety",
            }
        )

    previous = normalized(split - 1)
    following = normalized(split)
    nearby_left = [normalized(index) for index in range(max(0, split - 5), split)]
    has_nearby_quantity = any(
        is_numeric_value(token) or token in ENGLISH_NUMERIC_MAGNITUDE_WORDS
        for token in nearby_left
    )
    if (
        has_nearby_quantity
        and following in ENGLISH_RATE_DETERMINERS
        and split + 1 < len(words)
        and normalized(split + 1) in ENGLISH_RATE_PERIOD_WORDS
    ):
        return True
    if (
        has_nearby_quantity
        and previous in ENGLISH_RATE_DETERMINERS
        and following in ENGLISH_RATE_PERIOD_WORDS
    ):
        return True
    if is_numeric_value(previous) and is_numeric_value(following):
        return True
    if is_numeric_value(previous) and following in ENGLISH_NUMERIC_MAGNITUDE_WORDS:
        return True
    if (
        previous in ENGLISH_NUMERIC_MAGNITUDE_WORDS
        and split >= 2
        and (
            is_numeric_value(normalized(split - 2))
            or normalized(split - 2) in ENGLISH_NUMERIC_MAGNITUDE_WORDS
        )
        and following.isalpha()
    ):
        return True
    if (
        split >= 3
        and previous.isalpha()
        and following.isalpha()
        and following not in LINE_BREAK_AVOID_BEFORE_WORDS
        and normalized(split - 2) in ENGLISH_NUMERIC_MAGNITUDE_WORDS
        and (
            is_numeric_value(normalized(split - 3))
            or normalized(split - 3) in ENGLISH_NUMERIC_MAGNITUDE_WORDS
        )
    ):
        return True
    return False


def _caption_line_break_penalty(words: list[str], split: int) -> int:
    """Score a renderer-only line break without changing cue ownership."""
    previous_surface = str(words[split - 1]).strip()
    previous = re.sub(r"[^A-Za-z']", "", words[split - 1]).lower()
    following = re.sub(r"[^A-Za-z']", "", words[split]).lower()
    punctuation_boundary = bool(
        re.search(r"[,;:.!?][\"')\]]*$", previous_surface)
    )
    penalty = 0
    if previous in LINE_BREAK_AVOID_AFTER_WORDS:
        penalty += CAPTION_HARD_BREAK_PENALTY
    if _caption_boundary_has_stranded_dependency(words, split):
        penalty += CAPTION_HARD_BREAK_PENALTY
    elif following in LINE_BREAK_AVOID_BEFORE_WORDS:
        if (
            _caption_phrase_start_is_complete(words, split)
            or _caption_complete_continuation_clause(words[split:])
        ):
            penalty += CAPTION_COMPLETE_PHRASE_START_PENALTY
        else:
            penalty += CAPTION_HARD_BREAK_PENALTY
    if (
        not punctuation_boundary
        and _looks_like_english_modifier_boundary(words[split - 1], words[split])
    ):
        penalty += CAPTION_HARD_BREAK_PENALTY
    if not punctuation_boundary and _looks_like_numeric_phrase_boundary(words, split):
        penalty += CAPTION_HARD_BREAK_PENALTY
    if "-" in words[split - 1]:
        penalty += CAPTION_HARD_BREAK_PENALTY * 2
    if re.search(r"[,;:]$", words[split - 1]):
        penalty -= 1_200
    if re.search(r"[.!?]$", words[split - 1]):
        penalty -= 2_400
    return penalty


def _article_intrinsic_line_break_penalty(words: list[str], split: int) -> int:
    """Keep lexical morphology hard when no frozen syntax evidence exists."""
    return _caption_line_break_penalty(words, split)


def _article_same_screen_intrinsic_line_break_penalty(
    cue: Cue,
    words: list[str],
    split: int,
    global_split: int,
) -> int:
    """Soften a morphology false positive only at a proven predicate start."""
    penalty = _article_intrinsic_line_break_penalty(words, split)
    if not _looks_like_english_modifier_boundary(
        words[split - 1],
        words[split],
    ):
        return penalty
    decision = _article_display_boundary_decision(cue, global_split)
    issue_codes = set(decision.get("issue_codes") or [])
    predicate_issues = {
        "relative_clause_subject_verb_split",
        "subject_finite_verb_split",
        "subject_predicate_split",
    }
    if (
        issue_codes & predicate_issues
        and not issue_codes & ARTICLE_LINE_ATOMIC_BOUNDARY_ISSUES
    ):
        return (
            penalty
            - CAPTION_HARD_BREAK_PENALTY
            + ARTICLE_LINE_SOFT_MODIFIER_PENALTY
        )
    return penalty


def _caption_boundary_has_stranded_dependency(words: list[str], split: int) -> bool:
    """Return whether a split leaves a known lexical dependency behind."""
    if split <= 0 or split >= len(words):
        return False
    previous = re.sub(r"[^A-Za-z']", "", words[split - 1]).lower()
    following = re.sub(r"[^A-Za-z']", "", words[split]).lower()
    return (previous, following) in CAPTION_DEPENDENT_BOUNDARY_PAIRS


def _caption_has_terminal_completion(words: list[str]) -> bool:
    if not words:
        return False
    return bool(re.search(r"[.!?][\"')\]]*$", str(words[-1]).strip()))


def _caption_complete_continuation_clause(words: list[str]) -> bool:
    """Treat a full visible continuation clause as reviewable, not invalid."""
    if len(words) < ARTICLE_VISUAL_PAGE_MIN_WORDS:
        return False
    first = re.sub(r"[^A-Za-z']", "", words[0]).lower()
    return bool(
        first in ARTICLE_PAGE_COMPLETE_CONTINUATION_START_WORDS
        and _caption_has_terminal_completion(words)
    )


def _caption_complete_page_clause_start(words: list[str], split: int) -> bool:
    """Return whether a page starts with a complete visible clause."""
    if split <= 0 or split >= len(words):
        return False
    remaining = words[split:]
    if len(remaining) < ARTICLE_VISUAL_PAGE_MIN_WORDS:
        return False
    first = re.sub(r"[^A-Za-z']", "", remaining[0]).lower()
    return bool(
        first
        in (
            ARTICLE_PAGE_COMPLETE_CONTINUATION_START_WORDS
            | ARTICLE_PAGE_COMPLETE_WH_CLAUSE_START_WORDS
        )
        and _caption_has_terminal_completion(remaining)
    )


def _caption_phrase_start_is_complete(words: list[str], split: int) -> bool:
    """Allow a complete prepositional/infinitive phrase to start a line."""
    if split <= 0 or split >= len(words):
        return False
    first = re.sub(r"[^A-Za-z']", "", words[split]).lower()
    if first not in ARTICLE_PAGE_PHRASE_START_WORDS:
        return False
    if _caption_boundary_has_stranded_dependency(words, split):
        return False
    remaining = [re.sub(r"[^A-Za-z']", "", word).lower() for word in words[split:]]
    if len(remaining) < 2:
        return False
    # An article may introduce the phrase's complete object (``in a large
    # market``). Only a terminal function word leaves the visible phrase
    # incomplete (``from the`` / ``to a``).
    return remaining[-1] not in LINE_BREAK_AVOID_AFTER_WORDS


def _has_discouraged_caption_break(
    text: str,
    lines: list[str],
    *,
    boundary_penalty: Callable[[int], int] | None = None,
    intrinsic_penalty: Callable[[list[str], int], int] | None = None,
) -> bool:
    if len(lines) < 2:
        return False
    words = text.split()
    split = 0
    score_break = intrinsic_penalty or _caption_line_break_penalty
    for line in lines[:-1]:
        split += len(line.split())
        if not 0 < split < len(words):
            continue
        penalty = score_break(words, split)
        if boundary_penalty is not None:
            penalty += int(boundary_penalty(split))
        if penalty >= CAPTION_HARD_BREAK_PENALTY:
            return True
    return False


def wrap_en(
    draw,
    text: str,
    fnt,
    max_width: int,
    *,
    minimum_line_words: int = 3,
    boundary_penalty: Callable[[int], int] | None = None,
    intrinsic_penalty: Callable[[list[str], int], int] | None = None,
) -> list[str]:
    """Choose a balanced two-line fit while retaining basic phrase units."""
    words = text.split()
    if text_w(draw, text, fnt) <= max_width:
        return [text]

    best = None
    best_score = 10**9
    for split in range(1, len(words)):
        if min(split, len(words) - split) < minimum_line_words:
            continue
        a, b = " ".join(words[:split]), " ".join(words[split:])
        aw, bw = text_w(draw, a, fnt), text_w(draw, b, fnt)
        if aw <= max_width and bw <= max_width:
            score_break = intrinsic_penalty or _caption_line_break_penalty
            score = abs(aw - bw) + score_break(words, split)
            if boundary_penalty is not None:
                score += int(boundary_penalty(split))
            if score < best_score:
                best = [a, b]
                best_score = score

    if best:
        return best

    lines, current = [], []
    for word in words:
        candidate = " ".join(current + [word])
        if current and text_w(draw, candidate, fnt) > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def highlight_ranges_for_lines(lines: list[str], key: str | None) -> list[tuple[int, int] | None]:
    """Return per-line character spans for the first matching vocabulary phrase."""
    ranges: list[tuple[int, int] | None] = [None] * len(lines)
    if not key or not lines:
        return ranges
    joined = " ".join(lines)
    start = joined.lower().find(key.lower())
    if start < 0:
        return ranges
    end = extend_highlight_to_trailing_punctuation(joined, start + len(key))
    offset = 0
    for index, line in enumerate(lines):
        line_end = offset + len(line)
        overlap_start = max(start, offset)
        overlap_end = min(end, line_end)
        if overlap_start < overlap_end:
            ranges[index] = (overlap_start - offset, overlap_end - offset)
        offset = line_end + 1
    return ranges


def wrap_en_preserving_highlight(
    draw,
    text: str,
    fnt,
    max_width: int,
    key: str | None,
    *,
    minimum_line_words: int = 3,
    boundary_penalty: Callable[[int], int] | None = None,
    intrinsic_penalty: Callable[[list[str], int], int] | None = None,
) -> list[str]:
    """Avoid splitting the active vocabulary expression when a two-line fit permits it."""
    lines = wrap_en(
        draw,
        text,
        fnt,
        max_width,
        minimum_line_words=minimum_line_words,
        boundary_penalty=boundary_penalty,
        intrinsic_penalty=intrinsic_penalty,
    )
    if not key or len(lines) != 2 or any(key.lower() in line.lower() for line in lines):
        return lines

    words = text.split()
    phrase_words = [re.sub(r"[^A-Za-z0-9']", "", word).lower() for word in key.split()]
    caption_words = [re.sub(r"[^A-Za-z0-9']", "", word).lower() for word in words]
    phrase_words = [word for word in phrase_words if word]
    if not phrase_words:
        return lines

    phrase_start = next(
        (
            index
            for index in range(len(caption_words) - len(phrase_words) + 1)
            if caption_words[index:index + len(phrase_words)] == phrase_words
        ),
        None,
    )
    if phrase_start is None:
        return lines
    phrase_end = phrase_start + len(phrase_words)

    best: list[str] | None = None
    best_score: int | None = None
    for split in range(minimum_line_words, len(words) - minimum_line_words + 1):
        if phrase_start < split < phrase_end:
            continue
        before = " ".join(words[:split])
        after = " ".join(words[split:])
        before_width = text_w(draw, before, fnt)
        after_width = text_w(draw, after, fnt)
        if before_width > max_width or after_width > max_width:
            continue
        # Keep the expression at a line edge when possible, then retain the
        # previous wrapper's preference for visually balanced line lengths.
        edge_distance = min(abs(split - phrase_start), abs(split - phrase_end))
        score_break = intrinsic_penalty or _caption_line_break_penalty
        break_penalty = score_break(words, split)
        if boundary_penalty is not None:
            break_penalty += int(boundary_penalty(split))
        if break_penalty >= CAPTION_HARD_BREAK_PENALTY:
            continue
        score = (
            edge_distance * 1600
            + abs(before_width - after_width)
            + break_penalty
        )
        if best_score is None or score < best_score:
            best = [before, after]
            best_score = score
    return best or lines


def wrap_zh_by_width(draw, text: str, fnt, max_width: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        cand = cur + ch
        if cur and text_w(draw, cand, fnt) > max_width:
            lines.append(cur)
            cur = ch
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def wrap_zh(draw, text: str, fnt, max_width: int) -> list[str]:
    text = text.strip()
    if text_w(draw, text, fnt) <= max_width:
        return [text]

    comma_positions = [m.end() for m in re.finditer(r"[，,]", text)]
    if comma_positions:
        midpoint = len(text) / 2
        split_at = min(comma_positions, key=lambda pos: abs(pos - midpoint))
        left = text[:split_at].strip()
        right = text[split_at:].strip()
        if len(left) >= 6 and len(right) >= 6:
            lines = []
            for part in (left, right):
                if text_w(draw, part, fnt) <= max_width:
                    lines.append(part)
                else:
                    lines.extend(wrap_zh_by_width(draw, part, fnt, max_width))
            return lines

    return wrap_zh_by_width(draw, text, fnt, max_width)


def fit_standard_zh_font(draw, text: str, max_width: int) -> ImageFont.FreeTypeFont:
    """Keep ordinary subtitles large, but avoid a needless second Chinese line."""
    for size in (48, 46):
        fnt = cjk_font(size)
        if text_w(draw, text, fnt) <= max_width:
            return fnt
    return cjk_font(46)


def fit_en_font(draw, text: str, max_width: int) -> ImageFont.FreeTypeFont:
    for size in range(70, 35, -2):
        fnt = font(FONT_GANTARI, size, 600)
        lines = wrap_en(draw, text, fnt, max_width)
        if (
            len(lines) <= 2
            and all(text_w(draw, line, fnt) <= max_width for line in lines)
            and not _has_short_caption_line(lines)
            and not _has_discouraged_caption_break(text, lines)
        ):
            return fnt
    return font(FONT_GANTARI, 34, 600)


def fit_title_font(draw, title: str, max_width: int) -> ImageFont.FreeTypeFont:
    for size in range(TITLE_MAX_FONT_SIZE, TITLE_MIN_FONT_SIZE - 1, -2):
        fnt = cjk_font(size)
        if text_w(draw, title, fnt) <= max_width:
            return fnt
    return cjk_font(TITLE_MIN_FONT_SIZE)


def extend_highlight_to_trailing_punctuation(line: str, end: int) -> int:
    """Keep punctuation immediately attached to a matched expression highlighted."""
    while end < len(line) and line[end] in HIGHLIGHT_TRAILING_PUNCTUATION:
        end += 1
    return end


def draw_highlighted_line(
    img: Image.Image,
    draw,
    x: int,
    y: int,
    line: str,
    key: str | None,
    fnt,
    alpha: int = 255,
    match_range: tuple[int, int] | None = None,
) -> None:
    white = with_alpha(SUBTITLE_EN, alpha)
    blue = with_alpha(BLUE, alpha)
    if match_range is None:
        if not key or key.lower() not in line.lower():
            draw_subtitle_shadowed_text(img, draw, (x, y), line, fnt, white, anchor="mm", alpha=alpha)
            return
        start = line.lower().find(key.lower())
        end = extend_highlight_to_trailing_punctuation(line, start + len(key))
    else:
        start, end = match_range
    if start < 0 or end > len(line) or start >= end:
        draw_subtitle_shadowed_text(img, draw, (x, y), line, fnt, white, anchor="mm", alpha=alpha)
        return
    parts = [line[:start], line[start:end], line[end:]]
    widths = [text_w(draw, part, fnt) for part in parts]
    cursor = x - sum(widths) // 2
    for i, part in enumerate(parts):
        if part:
            draw_subtitle_shadowed_text(
                img,
                draw,
                (cursor, y),
                part,
                fnt,
                blue if i == 1 else white,
                anchor="lm",
                alpha=alpha,
            )
            cursor += widths[i]


def draw_vocab_card(img: Image.Image, item: dict) -> None:
    card_width = scx(VOCAB_CARD_WIDTH0)
    card_height = scy(VOCAB_CARD_HEIGHT0)
    x0 = scx(VOCAB_CARD_CENTER_X0) - card_width // 2
    y0 = scy(VOCAB_CARD_TOP_Y0)
    rect = (x0, y0, x0 + card_width, y0 + card_height)
    rounded_blur_card(img, rect, radius=scx(12), tint=(0, 0, 0, 26))
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, _, _ = rect
    word = str(item["word"]).strip().capitalize()
    word_font = font(FONT_GANTARI, 52, 650)
    phonetic_path = FONT_CAMBRIA if FONT_CAMBRIA.exists() else FONT_SEGOE
    phonetic_font = font(phonetic_path if phonetic_path.exists() else FONT_GANTARI, 27, 430)
    pos_font = font(FONT_GANTARI, 20, 650)
    meaning_font = cjk_font(28)
    word_x = x0 + scx(23)
    word_y = y0 + scy(10)
    draw_stroked_text(d, (word_x, word_y), word, word_font, BLUE, stroke_width=0)
    word_right = word_x + text_w(d, word, word_font)
    phonetic = str(item.get("phonetic") or "").strip()
    if phonetic:
        draw_stroked_text(d, (word_right + scx(16), y0 + scy(28)), phonetic, phonetic_font, MUTED, stroke_width=0)

    pos = str(item.get("pos") or "词性").strip()
    if re.search(r"[\u4e00-\u9fff]", pos):
        pos_font = cjk_font(18)
    pos_text_w = text_w(d, pos, pos_font)
    tag_x0 = x0 + scx(24)
    tag_y0 = y0 + scy(87)
    tag_x1 = tag_x0 + max(scx(38), min(scx(68), pos_text_w + scx(14)))
    tag_y1 = tag_y0 + scy(27)
    d.rounded_rectangle((tag_x0, tag_y0, tag_x1, tag_y1), radius=scx(7), fill=(0, 124, 255, 225))
    draw_stroked_text(d, ((tag_x0 + tag_x1) // 2, (tag_y0 + tag_y1) // 2 - scy(1)), pos, pos_font, WHITE, anchor="mm", stroke_width=0)
    meaning = str(item["meaning"]).strip()
    meaning_x = tag_x1 + scx(16)
    meaning_y = y0 + scy(86)
    meaning_max_w = rect[2] - meaning_x - scx(24)
    while text_w(d, meaning, meaning_font) > meaning_max_w and meaning_font.size > 22:
        meaning_font = cjk_font(meaning_font.size - 1)
    if text_w(d, meaning, meaning_font) <= meaning_max_w:
        draw_stroked_text(d, (meaning_x, meaning_y), meaning, meaning_font, MUTED, stroke_width=0)
    else:
        lines = wrap_zh(d, meaning, meaning_font, meaning_max_w)
        if len(lines) > 2:
            lines = lines[:2]
            lines[-1] = lines[-1].rstrip("，。；、 ") + "..."
        gap = int(meaning_font.size * 1.12)
        first_y = meaning_y - gap // 2 if len(lines) == 2 else meaning_y
        for idx, line in enumerate(lines):
            draw_stroked_text(d, (meaning_x, first_y + idx * gap), line, meaning_font, MUTED, stroke_width=0)


def draw_vocab_review_bar(img: Image.Image, item: dict) -> None:
    """Render a compact reminder after the detailed card has been read."""
    bar_width = scx(440)
    bar_height = scy(54)
    x0 = scx(VOCAB_CARD_CENTER_X0) - bar_width // 2
    y0 = scy(VOCAB_CARD_TOP_Y0 + 28)
    rect = (x0, y0, x0 + bar_width, y0 + bar_height)
    rounded_blur_card(img, rect, radius=scx(12), tint=(0, 0, 0, 22))
    d = ImageDraw.Draw(img, "RGBA")
    word = str(item.get("word") or "").strip().capitalize()
    meaning = str(item.get("meaning") or "").strip()
    word_font = font(FONT_GANTARI, 29, 650)
    meaning_font = cjk_font(22)
    word_x = x0 + scx(20)
    word_y = y0 + bar_height // 2
    draw_stroked_text(d, (word_x, word_y), word, word_font, BLUE, anchor="lm", stroke_width=0)
    divider_x = word_x + text_w(d, word, word_font) + scx(14)
    d.line((divider_x, y0 + scy(12), divider_x, y0 + bar_height - scy(12)), fill=(155, 174, 208, 180), width=1)
    meaning_x = divider_x + scx(14)
    available = rect[2] - meaning_x - scx(18)
    while text_w(d, meaning, meaning_font) > available and meaning_font.size > 17:
        meaning_font = cjk_font(meaning_font.size - 1)
    draw_stroked_text(d, (meaning_x, word_y), meaning, meaning_font, MUTED, anchor="lm", stroke_width=0)


def active_cue(cues: list[Cue], t: float, last_index: int) -> tuple[Cue | None, int]:
    i = last_index
    while i + 1 < len(cues) and cues[i].end < t:
        i += 1
    if i < len(cues) and cues[i].start <= t <= cues[i].end:
        return cues[i], i
    return None, i


def draw_frame(
    base: Image.Image,
    male: Image.Image,
    female: Image.Image,
    cue: Cue | None,
    vocab_plan: dict[int, dict] | None = None,
    subtitle_alpha: int = 255,
    show_vocab: bool = False,
    title_text: str = TITLE_TEXT,
    display_time: float | None = None,
    english_only: bool = False,
) -> Image.Image:
    img = base.copy()
    d = ImageDraw.Draw(img, "RGBA")
    title = (title_text or TITLE_TEXT).strip() or TITLE_TEXT
    title_left = scx(TITLE_SAFE_LEFT_X0)
    title_right = scx(TITLE_SAFE_RIGHT_X0)
    title_font = fit_title_font(d, title, title_right - title_left)
    draw_stroked_text(
        d,
        ((title_left + title_right) // 2, scy(TITLE_CENTER_Y0)),
        title,
        title_font,
        TITLE_FILL,
        anchor="mm",
        stroke_width=0,
    )
    draw_avatar(img, male, scx(160), scy(143))
    draw_avatar(img, female, scx(1543), scy(143))
    if not cue:
        return img

    vocab, vocab_state = vocab_card_display_state(vocab_plan, cue, display_time) if show_vocab else (None, "hidden")
    key = vocab["key"] if vocab else None
    en_width = scx(1459)
    en_font = fit_en_font(d, cue.en, en_width)
    en_lines = wrap_en_preserving_highlight(d, cue.en, en_font, en_width, key)
    highlight_ranges = highlight_ranges_for_lines(en_lines, key)
    line_gap = int(en_font.size * 1.06)
    en_start_y = scy(EN_SUBTITLE_CENTER_Y0) - (len(en_lines) - 1) * line_gap // 2
    for idx, line in enumerate(en_lines):
        draw_highlighted_line(
            img,
            d,
            WIDTH // 2,
            en_start_y + idx * line_gap,
            line,
            key,
            en_font,
            subtitle_alpha,
            highlight_ranges[idx],
        )

    if cue.zh and not english_only:
        zh_font = fit_standard_zh_font(d, cue.zh, en_width)
        zh_lines = wrap_zh(d, cue.zh, zh_font, en_width)
        zh_gap = 66
        zh_start_y = scy(ZH_SUBTITLE_CENTER_Y0) - (len(zh_lines) - 1) * zh_gap // 2
        zh_fill = with_alpha(SUBTITLE_ZH, subtitle_alpha)
        zh_stroke = (0, 0, 0, round(165 * subtitle_alpha / 255))
        for idx, line in enumerate(zh_lines):
            draw_stroked_text(
                d,
                (WIDTH // 2, zh_start_y + idx * zh_gap),
                line,
                zh_font,
                zh_fill,
                anchor="mm",
                stroke_width=2,
                stroke_fill=zh_stroke,
            )

    if vocab_state == "full" and vocab:
        draw_vocab_card(img, vocab)
    return img


def fit_article_en_font(
    draw,
    text: str,
    max_width: int,
    font_size: int = ARTICLE_SUBTITLE_EN_FONT_SIZE,
) -> ImageFont.FreeTypeFont:
    """Return the explicit font chosen by the frozen page plan."""
    return article_en_font(int(font_size), 600)


def article_visual_page_count(cue: Cue | None) -> int:
    """Return the conservative fallback page count for an unplanned cue."""
    if cue is None:
        return 1
    english_words = len(str(cue.en or "").split())
    return max(1, math.ceil(english_words / ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS))


def article_visual_page_index(cue: Cue | None, display_time: float | None) -> int:
    """Map an absolute render time to a page without changing cue timing."""
    plan = cue.article_page_plan if cue is not None else None
    if plan and plan.get("status") == "ok":
        pages = list(plan.get("pages") or [])
        if display_time is None or len(pages) <= 1:
            return 0
        for index, page in enumerate(pages):
            if float(display_time) < float(page["end"]) or index == len(pages) - 1:
                return index
        return len(pages) - 1
    page_count = article_visual_page_count(cue)
    if cue is None or page_count <= 1 or display_time is None:
        return 0
    duration = max(float(cue.end) - float(cue.start), 0.001)
    progress = min(0.999999, max(0.0, (float(display_time) - float(cue.start)) / duration))
    return min(page_count - 1, int(progress * page_count))


def _article_visual_break_score(words: list[str], split: int, target: int) -> int:
    """Prefer phrase-safe punctuation while staying near a balanced page."""
    score = abs(split - target) * 100
    score += _article_visual_break_penalty(words, split)
    previous = words[split - 1].rstrip() if split else ""
    if previous.endswith((",", ";", ":", ".", "?", "!")):
        score -= 1_500
    return score


def split_article_visual_pages(text: str, page_count: int) -> list[str]:
    """Split frozen English text into readable render pages, preserving words."""
    words = str(text or "").split()
    page_count = max(1, min(int(page_count or 1), len(words) or 1))
    if page_count == 1:
        return [" ".join(words)] if words else []
    boundaries = [0]
    for page in range(1, page_count):
        target = round(len(words) * page / page_count)
        min_split = boundaries[-1] + 1
        max_split = min(
            len(words) - (page_count - page),
            boundaries[-1] + ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS,
        )
        candidates = range(max(min_split, target - 5), min(max_split, target + 5) + 1)
        split = min(candidates, key=lambda value: _article_visual_break_score(words, value, target))
        boundaries.append(split)
    boundaries.append(len(words))
    return [" ".join(words[start:end]) for start, end in zip(boundaries, boundaries[1:])]


def split_chinese_visual_pages(
    text: str,
    page_count: int,
    page_word_counts: Sequence[int] | None = None,
) -> list[str]:
    """Split Chinese near safe phrase boundaries with English proportions.

    Render pages are derived from frozen English word spans.  Using those
    spans as the Chinese target prevents a later English-heavy page from
    receiving an unrelated, equal-sized Chinese fragment merely because both
    pages happen to contain the same number of characters.  The public helper
    retains a best-effort fallback for legacy callers; the production planner
    uses ``_strict_split_chinese_visual_pages`` and fails closed when no safe
    boundary exists.
    """
    return _strict_split_chinese_visual_pages(
        text,
        page_count,
        page_word_counts,
        strict=False,
    ) or []


def _chinese_visual_token_boundaries(text: str) -> dict[int, tuple[int, int]] | None:
    """Return deterministic token-boundary context from the vendored jieba model."""
    return chinese_token_boundaries(text)


def _strict_split_chinese_visual_pages(
    text: str,
    page_count: int,
    page_word_counts: Sequence[int] | None = None,
    *,
    strict: bool = True,
) -> list[str] | None:
    """Split Chinese without cutting a Han-word or glued token.

    Chinese subtitles do not carry spaces, so a renderer cannot infer every
    lexical word with certainty from characters alone.  A strict plan accepts
    only punctuation or a conservative phrase-start boundary.  If none is
    available near the English-proportional target, it returns ``None`` so the
    caller can keep one page or block the render rather than create a visibly
    broken word such as ``大 | 陆``.
    """
    compact = re.sub(r"\s+", "", str(text or ""))
    page_count = max(1, min(int(page_count or 1), len(compact) or 1))
    if page_count == 1:
        return [compact] if compact else []
    weights = list(page_word_counts or [])
    if len(weights) != page_count or any(int(weight) <= 0 for weight in weights):
        weights = [1] * page_count
    total_weight = sum(int(weight) for weight in weights)
    boundaries = [0]
    punctuation = set("，。；：！？、")
    token_boundaries = _chinese_visual_token_boundaries(compact)
    for page in range(1, page_count):
        target = round(len(compact) * sum(int(weight) for weight in weights[:page]) / total_weight)
        minimum = boundaries[-1] + 1
        maximum = len(compact) - (page_count - page)
        nearby = range(
            max(minimum, target - 8),
            min(maximum, target + 8) + 1,
        )

        def is_safe(value: int) -> bool:
            if value <= 0 or value >= len(compact):
                return False
            previous = compact[value - 1]
            following = compact[value]
            # A renderer page must never start with closing punctuation that
            # belongs to the phrase on the prior page.  Prefer the boundary
            # after that punctuation or keep the cue on a single page.
            if following in punctuation:
                return False
            if previous in punctuation:
                return True
            # Never split an ASCII/number token that was kept contiguous by
            # the translation stage (URLs, model names, percentages, etc.).
            if previous.isascii() and following.isascii() and (
                previous.isalnum() or following.isalnum()
            ):
                return False
            if not ("\u4e00" <= previous <= "\u9fff" and "\u4e00" <= following <= "\u9fff"):
                return True
            if isinstance(token_boundaries, dict):
                token_context = token_boundaries.get(value)
            elif isinstance(token_boundaries, set):
                # Preserve the read-only test/legacy contract where callers
                # provide only the set of known token-end offsets.
                token_context = (2, 2) if value in token_boundaries else None
            else:
                token_context = None
            # A tokenizer can still analyse a compound as ``轻 | 量化``.  A
            # Han/Han page break is trustworthy only between two multi-character
            # tokens; single-character edges require independent punctuation or
            # an explicit discourse-prefix boundary below.
            if token_context is not None and min(token_context) >= 2:
                return True
            prefix = compact[value:min(len(compact), value + 2)]
            if prefix in CHINESE_VISUAL_SAFE_PREFIXES:
                return True
            # Do not allow an ambiguous Han/Han boundary in strict mode.
            return not strict

        candidates = [value for value in nearby if is_safe(value)]
        if not candidates:
            if strict:
                return None
            candidates = [target]
        boundaries.append(
            min(
                candidates,
                key=lambda value: (
                    abs(value - target),
                    0 if compact[value - 1] in punctuation else 1,
                    -value,
                ),
            )
        )
    boundaries.append(len(compact))
    return [compact[start:end] for start, end in zip(boundaries, boundaries[1:])]


def article_visual_page_text(cue: Cue | None, display_time: float | None) -> tuple[str, str]:
    """Return the page text for a cue while retaining its frozen source text."""
    if cue is None:
        return "", ""
    page = _article_visual_page(cue, display_time)
    if page is not None:
        return str(page["en"]), str(page["zh"])
    page_count = article_visual_page_count(cue)
    page_index = article_visual_page_index(cue, display_time)
    english_pages = split_article_visual_pages(cue.en, page_count)
    chinese_pages = _strict_split_chinese_visual_pages(cue.zh, page_count, strict=True)
    if chinese_pages is None:
        # Unplanned article rendering is blocked by the normal preflight.  If
        # a legacy caller still reaches this fallback, keep the complete text
        # together rather than reproducing a character-level split.
        chinese_pages = [re.sub(r"\s+", "", str(cue.zh or ""))]
    return (
        english_pages[min(page_index, len(english_pages) - 1)] if english_pages else "",
        chinese_pages[min(page_index, len(chinese_pages) - 1)] if chinese_pages else "",
    )


def _article_visual_page(cue: Cue | None, display_time: float | None) -> dict | None:
    """Return the active planned page, including its fixed-font line layout."""
    if cue is None:
        return None
    plan = cue.article_page_plan
    if plan and plan.get("status") == "ok":
        pages = list(plan.get("pages") or [])
        if pages:
            return pages[article_visual_page_index(cue, display_time)]
    return None


def _article_fixed_english_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    key: str | None = None,
    *,
    font_size: int = ARTICLE_SUBTITLE_EN_FONT_SIZE,
    enforce_word_limit: bool = True,
    boundary_penalty: Callable[[int], int] | None = None,
    relax_same_screen_syntax: bool = False,
    intrinsic_penalty: Callable[[list[str], int], int] | None = None,
) -> list[str]:
    # Kept as a compatibility argument for callers/tests from the earlier
    # fixed-word contract. Word count now affects ranking only; it cannot
    # reject a page that fits the measured two-line region.
    _ = enforce_word_limit
    fnt = article_en_font(int(font_size), 600)
    score_intrinsic = intrinsic_penalty
    if score_intrinsic is None and relax_same_screen_syntax:
        score_intrinsic = _article_intrinsic_line_break_penalty
    # Keep ordinary lines within a comfortable reading measure. The wider
    # profiles remain controlled fallbacks when a natural two-line wrap is not
    # available; they are not the first-choice one-line target.
    if text_w(draw, text, fnt) <= acx(ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH):
        return [text]
    minimum_word_candidates = (
        (3, 2)
        if (
            len(text.split()) <= ARTICLE_STATIC_TWO_WORD_LINE_MAX_WORDS
            or font_size == ARTICLE_SUBTITLE_EN_MIN_SIZE
        )
        else (3,)
    )
    for minimum_line_words in minimum_word_candidates:
        for width in (
            ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
            ARTICLE_SUBTITLE_EN_WIDTH,
            ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
        ):
            max_width = acx(width)
            lines = wrap_en_preserving_highlight(
                draw,
                text,
                fnt,
                max_width,
                key,
                minimum_line_words=minimum_line_words,
                boundary_penalty=boundary_penalty,
                intrinsic_penalty=score_intrinsic,
            )
            max_lines = 3 if font_size == ARTICLE_SUBTITLE_EN_MIN_SIZE else 2
            if (
                not lines
                or len(lines) > max_lines
                or any(text_w(draw, line, fnt) > max_width for line in lines)
                or (
                    len(lines) > 1
                    and any(
                        len(line.split()) < minimum_line_words
                        for line in lines
                    )
                )
                or (
                    font_size != ARTICLE_SUBTITLE_EN_MIN_SIZE
                    and _has_discouraged_caption_break(
                        text,
                        lines,
                        boundary_penalty=boundary_penalty,
                        intrinsic_penalty=score_intrinsic,
                    )
                )
            ):
                continue
            # Two-word lines are an article-template fallback only. They avoid
            # silent font shrinking when no legal three-word layout fits; a
            # one-word orphan and every hard lexical break remain forbidden.
            return lines
    return []


def _article_english_layout_width(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font_size: int,
) -> int:
    fnt = article_en_font(font_size, 600)
    measured = max((text_w(draw, line, fnt) for line in lines), default=0)
    for width in (
        ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
        ARTICLE_SUBTITLE_EN_WIDTH,
        ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
    ):
        if measured <= acx(width):
            return width
    return ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH


def _article_fixed_chinese_lines(draw: ImageDraw.ImageDraw, text: str) -> list[str]:
    if not text:
        return []
    fnt = article_cjk_font(ARTICLE_SUBTITLE_ZH_FONT_SIZE, 700)
    lines = wrap_zh(draw, text, fnt, acx(ARTICLE_SUBTITLE_ZH_WIDTH))
    if len(lines) > 2 or any(text_w(draw, line, fnt) > acx(ARTICLE_SUBTITLE_ZH_WIDTH) for line in lines):
        return []
    return lines


def _article_preferred_readability_page_count(
    draw: ImageDraw.ImageDraw,
    words: list[str],
    chinese: str,
    *,
    font_size: int = ARTICLE_SUBTITLE_EN_FONT_SIZE,
    cue_duration_ms: int | None = None,
) -> int:
    """Choose page count from display load, before evaluating break quality."""
    if not words:
        return 1
    english_font = article_en_font(font_size, 600)
    english_pixels = text_w(draw, " ".join(words), english_font)
    english_capacity = max(1, 2 * acx(ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH))
    english_pixel_pages = max(1, math.ceil(english_pixels / english_capacity))
    english_word_pages = max(
        1,
        math.ceil(len(words) / ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS),
    )

    chinese_pages = 1
    if chinese:
        chinese_font = article_cjk_font(ARTICLE_SUBTITLE_ZH_FONT_SIZE, 700)
        chinese_pixels = text_w(draw, chinese, chinese_font)
        chinese_capacity = max(1, 2 * acx(ARTICLE_SUBTITLE_ZH_WIDTH))
        chinese_pages = max(1, math.ceil(chinese_pixels / chinese_capacity))

    duration_pages = 1
    if cue_duration_ms is not None and cue_duration_ms > 0:
        duration_pages = max(
            1,
            math.ceil(cue_duration_ms / ARTICLE_PAGE_COMFORTABLE_MAX_DURATION_MS),
        )
    return min(
        ARTICLE_VISUAL_PAGE_MAX_PAGES,
        max(
            english_pixel_pages,
            english_word_pages,
            chinese_pages,
            duration_pages,
        ),
    )


def _article_display_boundary_decision(cue: Cue, split: int) -> dict:
    evidence = dict(cue.display_boundary_evidence or {})
    if split <= 0 or split >= len(cue.word_timing):
        return {
            "classification": "allow",
            "issue_codes": [],
            "confidence": "low",
        }
    right_word_id = cue.word_timing[split].get("word_id")
    item = dict(evidence.get(str(right_word_id)) or {})
    hard_issues = {
        str(code) for code in item.get("hard_issues") or [] if str(code)
    }
    soft_issues = {
        str(code) for code in item.get("soft_issues") or [] if str(code)
    }
    words = str(cue.en or "").split()
    previous_surface = words[split - 1] if split <= len(words) else ""
    previous = re.sub(r"[^A-Za-z']", "", previous_surface).lower()
    following = (
        re.sub(r"[^A-Za-z']", "", words[split]).lower()
        if split < len(words)
        else ""
    )
    punctuation_boundary = bool(
        re.search(r"[,;:.!?][\"')\]]*$", previous_surface)
    )
    if not punctuation_boundary and following == "of":
        hard_issues.add("atomic_of_complement_split")
    if (
        not punctuation_boundary
        and previous in {"and", "but", "nor", "or", "so", "yet"}
    ):
        hard_issues.add("dangling_coordinator_page_split")

    pause_ms = item.get("pause_ms")
    if pause_ms is None and len(cue.word_timing) == len(words):
        pause_ms = max(
            0,
            round(
                (
                    float(cue.word_timing[split]["start"])
                    - float(cue.word_timing[split - 1]["end"])
                )
                * 1000
            ),
        )
    issue_codes = set(hard_issues | soft_issues)
    atomic = (hard_issues - DISPLAY_PAGE_REVIEWABLE_BOUNDARY_ISSUES) | (
        soft_issues & DISPLAY_PAGE_ATOMIC_SOFT_ISSUES
    )
    complete_page_clause_start = _caption_complete_page_clause_start(
        words,
        split,
    )
    complete_wh_clause_start = bool(
        following in ARTICLE_PAGE_COMPLETE_WH_CLAUSE_START_WORDS
        and complete_page_clause_start
        and issue_codes
        and issue_codes
        <= {
            "clause_introducer_split",
            "short_verb_complement_split",
            "verb_complement_split",
        }
    )
    complete_clause_restart = bool(
        complete_page_clause_start
        and following in ARTICLE_PAGE_COMPLETE_CONTINUATION_START_WORDS
        and min(split, len(words) - split) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and pause_ms is not None
        and int(pause_ms) >= ARTICLE_PAGE_BALANCED_CLAUSE_REVIEW_MS
        and issue_codes
        and issue_codes
        <= {
            "clause_introducer_split",
            "coordinated_constituent_split",
            "object_content_clause_split",
            "protected_syntax_cut",
            "short_verb_complement_split",
            "verb_complement_split",
        }
    )
    coordinated_phrase_restart = bool(
        following in {"and", "but", "nor", "or", "so", "yet"}
        and _caption_complete_continuation_clause(words[split:])
        and min(split, len(words) - split) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and pause_ms is not None
        and int(pause_ms) >= ARTICLE_PAGE_STRONG_PAUSE_REVIEW_MS
        and issue_codes
        and issue_codes <= {"coordinated_constituent_split"}
    )
    balanced_predicate_restart = bool(
        min(split, len(words) - split) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and _caption_has_terminal_completion(words[split:])
        and pause_ms is not None
        and int(pause_ms) >= ARTICLE_PAGE_BALANCED_CLAUSE_REVIEW_MS
        and atomic
        and atomic
        <= {
            "relative_clause_subject_verb_split",
            "subject_finite_verb_split",
            "subject_predicate_split",
        }
    )
    strong_pause_restarts_ing_clause = bool(
        atomic
        and atomic <= {"determiner_head_phrase_split"}
        and "clause_introducer_split" in issue_codes
        and previous == "that"
        and following.endswith("ing")
    )
    punctuated_predicate_restart = bool(
        atomic
        and atomic <= DISPLAY_PAGE_STRONG_PAUSE_REVIEWABLE_HARD_ISSUES
        and punctuation_boundary
        and pause_ms is not None
        and int(pause_ms) >= ARTICLE_PAGE_PUNCTUATED_PREDICATE_REVIEW_MS
    )
    strong_pause_reviews_clause_boundary = bool(
        atomic
        and (
            atomic <= DISPLAY_PAGE_STRONG_PAUSE_REVIEWABLE_HARD_ISSUES
            or strong_pause_restarts_ing_clause
        )
        and pause_ms is not None
        and (
            int(pause_ms) >= ARTICLE_PAGE_STRONG_PAUSE_REVIEW_MS
            or punctuated_predicate_restart
        )
    )
    if complete_wh_clause_start:
        classification = "review"
        confidence = "medium"
    elif strong_pause_reviews_clause_boundary:
        classification = "review"
        confidence = "high"
    elif (
        complete_clause_restart
        or coordinated_phrase_restart
        or balanced_predicate_restart
    ):
        classification = "review"
        confidence = "medium"
    elif atomic:
        classification = "hard"
        confidence = "high"
    elif hard_issues or soft_issues:
        classification = "review"
        confidence = "medium"
    else:
        classification = "allow"
        confidence = "low"
    complete_phrase_start = _article_page_can_start_with_complete_phrase(
        words,
        split,
    )
    if (
        classification == "review"
        and complete_phrase_start
        and following in {"by", "into", "to"}
        and issue_codes
        and issue_codes <= {"dependency_phrase_entrance_split"}
    ):
        confidence = "low"
    if (
        classification == "allow"
        and not punctuation_boundary
        and (
            pause_ms is None
            or int(pause_ms) < ARTICLE_PAGE_UNSUPPORTED_TRANSITION_MIN_PAUSE_MS
        )
    ):
        classification = "review"
        confidence = "medium" if complete_phrase_start else "low"
        issue_codes.add("unsupported_tight_page_transition")
    tight_complete_phrase_start = bool(
        complete_phrase_start
        and not punctuation_boundary
        and (
            pause_ms is None
            or int(pause_ms) < ARTICLE_PAGE_UNSUPPORTED_TRANSITION_MIN_PAUSE_MS
        )
    )
    return {
        "classification": classification,
        "issue_codes": sorted(issue_codes),
        "confidence": confidence,
        "pause_ms": pause_ms,
        "boundary_score": item.get("boundary_score"),
        "protected_syntax": bool(item.get("protected_syntax")),
        "strong_pause_evidence": bool(
            strong_pause_reviews_clause_boundary
            or complete_clause_restart
            or coordinated_phrase_restart
            or balanced_predicate_restart
        ),
        "complete_page_clause_start": complete_page_clause_start,
        "balanced_predicate_restart": balanced_predicate_restart,
        "tight_complete_phrase_start": tight_complete_phrase_start,
    }


def _article_line_boundary_penalty(cue: Cue, split: int) -> int:
    """Project frozen syntax evidence onto a renderer-only line break."""
    decision = _article_display_boundary_decision(cue, split)
    issue_codes = set(decision.get("issue_codes") or [])
    if issue_codes & ARTICLE_LINE_ATOMIC_BOUNDARY_ISSUES:
        return CAPTION_HARD_BREAK_PENALTY
    if decision.get("classification") == "hard":
        # Both lines remain visible simultaneously, so cue/page-level syntax
        # prohibitions should steer a wrap without making the cue unrenderable.
        return DISPLAY_PAGE_HIGH_CONFIDENCE_REVIEW_PENALTY
    if decision.get("classification") != "review":
        return 0
    return {
        "high": DISPLAY_PAGE_HIGH_CONFIDENCE_REVIEW_PENALTY,
        "medium": DISPLAY_PAGE_REVIEW_PENALTY,
        "low": DISPLAY_PAGE_LOW_CONFIDENCE_REVIEW_PENALTY,
    }.get(str(decision.get("confidence") or "low"), 0)


def _article_page_planning_line_boundary_penalty(cue: Cue, split: int) -> int:
    """Retain v18 line feasibility while page spans are being selected."""
    decision = _article_display_boundary_decision(cue, split)
    issue_codes = set(decision.get("issue_codes") or [])
    if "verb_preposition_complement_split" in issue_codes:
        return CAPTION_HARD_BREAK_PENALTY
    if decision.get("classification") == "hard":
        return DISPLAY_PAGE_HIGH_CONFIDENCE_REVIEW_PENALTY
    if decision.get("classification") != "review":
        return 0
    return {
        "high": DISPLAY_PAGE_HIGH_CONFIDENCE_REVIEW_PENALTY,
        "medium": DISPLAY_PAGE_REVIEW_PENALTY,
        "low": DISPLAY_PAGE_LOW_CONFIDENCE_REVIEW_PENALTY,
    }.get(str(decision.get("confidence") or "low"), 0)


def _article_forced_continuation_decision(
    cue: Cue,
    words: list[str],
    split: int,
) -> dict:
    """Downgrade only a complete continuation phrase after strict planning fails.

    These are page transitions inside one frozen cue, not new subtitle
    boundaries.  Atomic lexical units remain hard; only a whole visible
    prepositional/infinitive phrase or continuation clause can enter the
    reviewable fallback tier.
    """
    decision = _article_display_boundary_decision(cue, split)
    if decision.get("classification") != "hard":
        return decision
    issue_codes = set(decision.get("issue_codes") or [])
    reviewable = {
        "atomic_of_complement_split",
        "clause_introducer_split",
        "dependency_phrase_entrance_split",
        "short_verb_complement_split",
        "stranded_leading_complement_split",
        "verb_complement_split",
    }
    following = re.sub(r"[^A-Za-z']", "", words[split]).lower()
    next_word = (
        re.sub(r"[^A-Za-z']", "", words[split + 1]).lower()
        if split + 1 < len(words)
        else ""
    )
    likely_infinitive_start = bool(
        following == "to"
        and next_word
        and next_word not in ARTICLE_PAGE_OBJECT_DETERMINERS
        and next_word not in LINE_BREAK_AVOID_BEFORE_WORDS
    )
    forced_subject_predicate = bool(
        following
        in {
            "am", "are", "can", "could", "had", "has", "have", "is",
            "may", "might", "must", "should", "was", "were", "will", "would",
        }
        and split >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and len(words) - split >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and issue_codes
        <= {
            "dependency_phrase_entrance_split",
            "modifier_head_split",
            "protected_syntax_cut",
            "subject_finite_verb_split",
        }
    )
    if likely_infinitive_start:
        reviewable.add("protected_syntax_cut")
    complete_phrase = _caption_phrase_start_is_complete(words, split)
    complete_continuation = _caption_complete_continuation_clause(words[split:])
    if (
        forced_subject_predicate
        or (
            issue_codes
            and issue_codes <= reviewable
            and (complete_phrase or complete_continuation or likely_infinitive_start)
            and (
                not _caption_boundary_has_stranded_dependency(words, split)
                or likely_infinitive_start
                or (
                    following in {"of", "for", "from"}
                    and re.sub(r"[^A-Za-z']", "", words[split - 1]).lower()
                    not in {
                        "amount", "half", "kind", "none", "number", "one",
                        "part", "sort",
                    }
                )
            )
        )
    ):
        return {
            **decision,
            "classification": "review",
            "confidence": "high",
            "issue_codes": sorted(
                issue_codes
                | {
                    (
                        "forced_subject_predicate_page_split"
                        if forced_subject_predicate
                        else "forced_complete_continuation_page_split"
                    )
                }
            ),
            "forced_display_continuation": True,
            "forced_subject_predicate": forced_subject_predicate,
        }
    return decision


def _article_page_break_score(
    cue: Cue,
    words: list[str],
    split: int,
    target_words: float,
    word_timing: tuple[dict, ...],
    *,
    allow_forced_continuation: bool = False,
    allow_review_boundary: bool = False,
    boundary_decision: Mapping | None = None,
) -> int | None:
    score = abs(split - target_words) * 240
    if split >= len(words):
        return int(score)
    if boundary_decision is None:
        boundary_decision = (
            _article_forced_continuation_decision(cue, words, split)
            if allow_forced_continuation
            else _article_display_boundary_decision(cue, split)
        )
    if boundary_decision.get("classification") == "hard":
        return None
    manual_review_boundary = bool(
        allow_review_boundary
        and boundary_decision.get("classification") == "review"
    )
    if not manual_review_boundary and _article_page_has_tight_nonfinite_complement(
        words,
        split,
        word_timing,
        boundary_decision,
    ):
        return None
    if not manual_review_boundary and _article_page_break_is_forbidden(
        words,
        split,
        boundary_decision=boundary_decision,
    ):
        return None
    break_penalty = _article_visual_break_penalty(words, split)
    previous_surface = str(words[split - 1]).strip()
    previous = re.sub(r"[^A-Za-z']", "", previous_surface).lower()
    if (
        previous in LINE_BREAK_AVOID_AFTER_WORDS
        and re.search(r"[,;:][\"')\]]*$", previous_surface)
        and _caption_complete_page_clause_start(words, split)
    ):
        # Punctuation closes the preceding phrase here; the lexical function-
        # word penalty must not override a complete following clause.
        break_penalty -= CAPTION_HARD_BREAK_PENALTY
    if _article_page_can_start_with_complete_phrase(words, split):
        # A page transition differs from a line wrap: the phrase begins on a
        # fresh page and remains intact there. Remove only the penalties that
        # belong to that phrase start; independent hard penalties still block.
        break_penalty -= CAPTION_COMPLETE_PHRASE_START_PENALTY
        following = re.sub(r"[^A-Za-z']", "", words[split]).lower()
        if following in ARTICLE_AVOID_LINE_START_WORDS:
            break_penalty -= CAPTION_HARD_BREAK_PENALTY
    score += break_penalty
    if boundary_decision.get("classification") == "review":
        confidence = str(boundary_decision.get("confidence") or "medium")
        if (
            boundary_decision.get("strong_pause_evidence")
            and not boundary_decision.get("forced_display_continuation")
        ):
            confidence = "medium"
        score += {
            "low": DISPLAY_PAGE_LOW_CONFIDENCE_REVIEW_PENALTY,
            "high": DISPLAY_PAGE_HIGH_CONFIDENCE_REVIEW_PENALTY,
        }.get(confidence, DISPLAY_PAGE_REVIEW_PENALTY)
    if boundary_decision.get("forced_display_continuation"):
        score += DISPLAY_PAGE_FORCED_CONTINUATION_REVIEW_PENALTY
    if len(word_timing) == len(words):
        pause_ms = max(
            0,
            round((word_timing[split]["start"] - word_timing[split - 1]["end"]) * 1000),
        )
        score -= min(pause_ms, ARTICLE_PAGE_PAUSE_PREFERENCE_MS) * 4
    return int(score)


def _article_page_break_rank(
    cue: Cue,
    words: list[str],
    split: int,
    target_words: float,
    word_timing: tuple[dict, ...],
    *,
    allow_forced_continuation: bool = False,
    allow_review_boundary: bool = False,
) -> tuple[int, float] | None:
    decision = (
        _article_forced_continuation_decision(cue, words, split)
        if allow_forced_continuation
        else _article_display_boundary_decision(cue, split)
    )
    cost = _article_page_break_score(
        cue,
        words,
        split,
        target_words,
        word_timing,
        allow_forced_continuation=allow_forced_continuation,
        allow_review_boundary=allow_review_boundary,
        boundary_decision=decision,
    )
    if cost is None:
        return None
    risk = _article_page_boundary_risk(decision, cost)
    return risk, float(cost)


def _article_page_boundary_risk(decision: Mapping, cost: int | float) -> int:
    """Keep review confidence visible to the partitioning dynamic program."""
    risk = 0
    if decision.get("classification") == "review":
        risk = {
            "low": 1,
            "medium": 2,
            "high": 3,
        }.get(str(decision.get("confidence") or "medium"), 2)
        if (
            decision.get("strong_pause_evidence")
            and not decision.get("forced_display_continuation")
        ):
            # A verified acoustic restart makes a clause-level review more
            # usable, even though the audit remains high-confidence evidence.
            risk = min(risk, 2)
        issue_codes = set(decision.get("issue_codes") or [])
        if "verb_preposition_complement_split" in issue_codes:
            risk = max(risk, 4)
        if "atomic_of_complement_split" in issue_codes:
            risk = max(risk, 5)
    if float(cost) >= DISPLAY_PAGE_HIGH_RISK_COST:
        risk = max(risk, 1)
    if decision.get("forced_display_continuation"):
        risk = max(risk, 4)
    if decision.get("forced_subject_predicate"):
        risk = max(risk, 5)
    return risk


def _article_page_break_is_forbidden(
    words: list[str],
    split: int,
    *,
    boundary_decision: Mapping | None = None,
) -> bool:
    """Return hard presentation constraints separately from preference cost."""
    if split <= 0 or split >= len(words):
        return False
    previous_surface = str(words[split - 1]).strip()
    previous = re.sub(r"[^A-Za-z']", "", previous_surface).lower()
    following = re.sub(r"[^A-Za-z']", "", words[split]).lower()
    punctuation_boundary = bool(
        re.search(r"[,;:.!?][\"')\]]*$", previous_surface)
    )
    complete_phrase = _caption_phrase_start_is_complete(words, split)
    complete_continuation = _caption_complete_continuation_clause(words[split:])
    complete_page_clause_start = _caption_complete_page_clause_start(words, split)
    punctuated_complete_clause_start = bool(
        punctuation_boundary and complete_page_clause_start
    )
    issue_codes = set((boundary_decision or {}).get("issue_codes") or [])
    pause_ms = (boundary_decision or {}).get("pause_ms")
    strong_pause_evidence = bool(
        (boundary_decision or {}).get("strong_pause_evidence")
    )
    supported_relative_start = bool(
        following in {"that", "which", "who", "whom", "whose", "where", "when"}
        and "dependency_phrase_entrance_split" in issue_codes
    )
    if (
        "fronted_wh_clause_split" in issue_codes
        and not punctuated_complete_clause_start
    ):
        return True
    if (
        not punctuation_boundary
        and following == "to"
        and previous in ARTICLE_PAGE_TO_INFINITIVE_HEADS
    ):
        return True
    if (
        not punctuation_boundary
        and following.endswith(("ing", "ed"))
        and pause_ms is not None
        and int(pause_ms) <= ARTICLE_PAGE_NONFINITE_COMPLEMENT_MAX_PAUSE_MS
        and issue_codes
        & {
            "dependency_phrase_entrance_split",
            "object_attached_modifier_split",
            "post_noun_participial_modifier_split",
        }
    ):
        return True
    if (
        not punctuation_boundary
        and following in ARTICLE_PAGE_PHRASE_START_WORDS
        and pause_ms is not None
        and int(pause_ms) <= ARTICLE_PAGE_NONFINITE_COMPLEMENT_MAX_PAUSE_MS
        and issue_codes
        & {
            "dependency_phrase_entrance_split",
            "object_attached_modifier_split",
            "verb_preposition_complement_split",
        }
    ):
        # Parser-backed tight complements remain atomic even when the relaxed
        # continuation planner is evaluating an otherwise complete phrase.
        return True
    if (boundary_decision or {}).get("forced_display_continuation"):
        return False
    if (
        previous in LINE_BREAK_AVOID_AFTER_WORDS
        and not strong_pause_evidence
        and not punctuated_complete_clause_start
        and not (boundary_decision or {}).get("forced_display_continuation")
    ):
        return True
    if (
        _caption_boundary_has_stranded_dependency(words, split)
        and not (boundary_decision or {}).get("forced_display_continuation")
    ):
        return True
    if (
        following in LINE_BREAK_AVOID_BEFORE_WORDS
        and not complete_phrase
        and not complete_continuation
        and not supported_relative_start
        and not (boundary_decision or {}).get("forced_display_continuation")
    ):
        return True
    if (
        not punctuation_boundary
        and _looks_like_english_modifier_boundary(words[split - 1], words[split])
    ):
        return True
    if not punctuation_boundary and _looks_like_numeric_phrase_boundary(words, split):
        return True
    if "-" in previous_surface and not punctuation_boundary:
        return True
    if following in ARTICLE_AVOID_LINE_START_WORDS and not complete_phrase:
        return True
    return False


def _article_page_has_tight_nonfinite_complement(
    words: list[str],
    split: int,
    word_timing: tuple[dict, ...],
    boundary_decision: Mapping | None = None,
) -> bool:
    """Reject only parser-supported, tightly spoken non-finite attachments."""
    if split <= 0 or split >= len(words) or len(word_timing) != len(words):
        return False
    previous = re.sub(r"[^A-Za-z']", "", words[split - 1]).lower()
    following = re.sub(r"[^A-Za-z']", "", words[split]).lower()
    issue_codes = set((boundary_decision or {}).get("issue_codes") or [])
    nonfinite_evidence = issue_codes & {
        "object_attached_modifier_split",
        "post_noun_participial_modifier_split",
        "verb_complement_split",
        "verb_preposition_complement_split",
    }
    if (
        not previous.endswith(("ing", "ed"))
        or not nonfinite_evidence
        or following
        not in (ARTICLE_PAGE_PHRASE_START_WORDS | ARTICLE_PAGE_OBJECT_DETERMINERS)
    ):
        return False
    pause_ms = max(
        0,
        round((word_timing[split]["start"] - word_timing[split - 1]["end"]) * 1000),
    )
    return pause_ms <= ARTICLE_PAGE_NONFINITE_COMPLEMENT_MAX_PAUSE_MS


def _article_page_can_start_with_complete_phrase(words: list[str], split: int) -> bool:
    """Allow a full prepositional or infinitive phrase to start a new page."""
    return _caption_phrase_start_is_complete(words, split)


def _article_page_span_is_readable(
    words: list[str],
    *,
    is_first_page: bool,
    paginated: bool,
    allow_attached_continuation: bool = False,
    allow_dangling_end: bool = False,
) -> bool:
    """Reject a timed page that is visibly too short or syntactically dangling."""
    if not paginated:
        return True
    if len(words) < ARTICLE_VISUAL_PAGE_MIN_WORDS:
        return False
    first = re.sub(r"[^A-Za-z']", "", words[0]).lower()
    last = re.sub(r"[^A-Za-z']", "", words[-1]).lower()
    terminal_completion = _caption_has_terminal_completion(words)
    phrase_boundary = bool(
        re.search(r"[,;:][\"')\]]*$", str(words[-1]).strip())
    )
    if (
        not is_first_page
        and first in ARTICLE_PAGE_CONTINUATION_START_WORDS
        and not _caption_complete_continuation_clause(words)
        and not allow_attached_continuation
    ):
        return False
    return bool(
        last not in LINE_BREAK_AVOID_AFTER_WORDS
        or terminal_completion
        or phrase_boundary
        or allow_dangling_end
    )


def _article_page_span_balance_cost(
    draw: ImageDraw.ImageDraw,
    words: list[str],
    start: int,
    end: int,
    word_timing: tuple[dict, ...],
    font_size: int,
    page_count: int,
) -> float:
    """Score page load by words, rendered pixels, and spoken duration."""
    if page_count <= 1:
        return 0.0
    span_word_count = end - start
    target_words = len(words) / page_count
    word_delta = (span_word_count - target_words) / max(target_words, 1.0)

    fnt = article_en_font(font_size, 600)
    total_pixels = text_w(draw, " ".join(words), fnt)
    span_pixels = text_w(draw, " ".join(words[start:end]), fnt)
    target_pixels = total_pixels / page_count
    pixel_delta = (span_pixels - target_pixels) / max(target_pixels, 1.0)

    score = word_delta * word_delta * 1_600
    score += pixel_delta * pixel_delta * 1_400
    if len(word_timing) == len(words):
        total_duration = max(
            float(word_timing[-1]["end"]) - float(word_timing[0]["start"]),
            0.001,
        )
        span_duration = max(
            float(word_timing[end - 1]["end"])
            - float(word_timing[start]["start"]),
            0.001,
        )
        target_duration = total_duration / page_count
        duration_delta = (span_duration - target_duration) / max(
            target_duration,
            0.001,
        )
        score += duration_delta * duration_delta * 900
    if span_word_count < max(
        ARTICLE_VISUAL_PAGE_MIN_WORDS,
        math.floor(target_words * 0.55),
    ):
        score += 4_000
    return score


def _partition_article_english_pages(
    draw: ImageDraw.ImageDraw,
    cue: Cue,
    words: list[str],
    page_count: int,
    word_timing: tuple[dict, ...],
    font_size: int,
    diagnostics: set[str] | None = None,
    *,
    allow_forced_continuation: bool = False,
    allow_review_boundary: bool = False,
    span_layout: Callable[[int, int, int, bool], Sequence[str]] | None = None,
    span_balance: Callable[[int, int, int, int], float] | None = None,
) -> list[tuple[int, int]] | None:
    """Find fixed-font page spans without creating a hard phrase split."""
    def span_is_readable(
        start: int,
        end: int,
        is_first_page: bool,
        paginated: bool,
    ) -> bool:
        page_words = words[start:end]
        boundary_decision = (
            (
                _article_forced_continuation_decision(cue, words, start)
                if allow_forced_continuation
                else _article_display_boundary_decision(cue, start)
            )
            if start > 0
            else {}
        )
        first = (
            re.sub(r"[^A-Za-z']", "", page_words[0]).lower()
            if page_words
            else ""
        )
        allow_attached_continuation = bool(
            start > 0
            and (
                (
                    first
                    in {"that", "which", "who", "whom", "whose", "where", "when"}
                    and "dependency_phrase_entrance_split"
                    in set(boundary_decision.get("issue_codes") or [])
                    and re.search(r"[,;:.!?][\"')\]]*$", page_words[-1])
                )
                or (
                    first in {"and", "but", "nor", "or", "so", "yet"}
                    and len(page_words) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
                )
                or bool(boundary_decision.get("forced_display_continuation"))
                or bool(
                    allow_review_boundary
                    and boundary_decision.get("classification") == "review"
                )
            )
        )
        outgoing_decision = (
            _article_forced_continuation_decision(cue, words, end)
            if allow_forced_continuation and end < len(words)
            else {}
        )
        lines = (
            list(span_layout(start, end, font_size, paginated))
            if span_layout is not None
            else _article_fixed_english_lines(
                draw,
                " ".join(page_words),
                font_size=font_size,
                enforce_word_limit=paginated,
                boundary_penalty=lambda local_split: _article_page_planning_line_boundary_penalty(
                    cue,
                    start + local_split,
                ),
            )
        )
        return bool(
            _article_page_span_is_readable(
                page_words,
                is_first_page=is_first_page,
                paginated=paginated,
                allow_attached_continuation=allow_attached_continuation,
                allow_dangling_end=bool(
                    outgoing_decision.get("forced_display_continuation")
                ),
            )
            and lines
        )

    return plan_word_page_spans(
        len(words),
        page_count,
        cue_start=float(cue.start),
        cue_end=float(cue.end),
        word_timing=word_timing,
        min_page_duration=ARTICLE_PAGE_MIN_DURATION_MS / 1000.0,
        span_is_readable=span_is_readable,
        break_score=lambda end, target: _article_page_break_rank(
            cue,
            words,
            end,
            target,
            word_timing,
            allow_forced_continuation=allow_forced_continuation,
            allow_review_boundary=allow_review_boundary,
        ),
        span_score=(
            (lambda start, end: span_balance(
                start,
                end,
                font_size,
                page_count,
            ))
            if span_balance is not None
            else (
                lambda start, end: _article_page_span_balance_cost(
                    draw,
                    words,
                    start,
                    end,
                    word_timing,
                    font_size,
                    page_count,
                )
            )
        ),
        diagnostics=diagnostics,
    )


def _schedule_article_page_boundaries(
    cue: Cue,
    spans: list[tuple[int, int]],
    *,
    minimum_page_duration_ms: int | None = None,
) -> tuple[list[float] | None, str]:
    if len(spans) <= 1:
        return [float(cue.start), float(cue.end)], ""
    words = cue.word_timing
    if len(words) != len(str(cue.en or "").split()):
        return None, "missing_or_mismatched_word_ledger"
    configured_minimum = (
        ARTICLE_PAGE_MIN_DURATION_MS
        if minimum_page_duration_ms is None
        else max(int(minimum_page_duration_ms), 0)
    )
    min_duration = configured_minimum / 1000.0
    if float(cue.end) - float(cue.start) + 1e-6 < len(spans) * min_duration:
        return None, "cue_duration_below_page_minimum"

    boundaries = [float(cue.start)]
    for index, (_, end) in enumerate(spans[:-1]):
        previous_word = words[end - 1]
        next_word = words[spans[index + 1][0]]
        previous_end = float(previous_word["end"])
        next_start = float(next_word["start"])
        remaining_pages = len(spans) - index - 1
        lower = max(previous_end, boundaries[-1] + min_duration)
        upper = min(next_start, float(cue.end) - remaining_pages * min_duration)
        if lower > upper + 1e-6:
            return None, "no_word_boundary_with_minimum_page_duration"
        comfortable_lower = max(lower, previous_end + ARTICLE_PAGE_TAIL_HOLD_MS / 1000.0)
        comfortable_upper = min(upper, next_start - ARTICLE_PAGE_LEAD_IN_MS / 1000.0)
        if comfortable_lower <= comfortable_upper:
            boundary = (comfortable_lower + comfortable_upper) / 2.0
        else:
            boundary = (lower + upper) / 2.0
        boundaries.append(boundary)
    boundaries.append(float(cue.end))
    return boundaries, ""


def _article_final_page_layout(
    draw: ImageDraw.ImageDraw,
    cue: Cue,
    words: Sequence[str],
    start: int,
    end: int,
) -> tuple[int, list[str]] | None:
    """Choose font and line wrap together for one frozen page span."""
    text = " ".join(words[start:end])
    candidates: list[tuple[int, int, list[str]]] = []
    for font_size in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES:
        lines = _article_fixed_english_lines(
            draw,
            text,
            font_size=font_size,
            boundary_penalty=lambda split, base=start: (
                _article_line_boundary_penalty(cue, base + split)
            ),
            relax_same_screen_syntax=True,
            intrinsic_penalty=lambda page_words, split, base=start: (
                _article_same_screen_intrinsic_line_break_penalty(
                    cue,
                    page_words,
                    split,
                    base + split,
                )
            ),
        )
        if lines:
            score = _article_same_screen_layout_score(
                cue,
                words,
                start,
                end,
                int(font_size),
                lines,
            )
            candidates.append((score, int(font_size), list(lines)))
    if not candidates:
        return None
    normal_candidates = [
        candidate
        for candidate in candidates
        if candidate[1] > ARTICLE_SUBTITLE_EN_MIN_SIZE
    ]
    if normal_candidates:
        candidates = normal_candidates
    _, font_size, lines = min(
        candidates,
        key=lambda candidate: (candidate[0], -candidate[1]),
    )
    return font_size, lines


def _article_same_screen_layout_score(
    cue: Cue,
    words: Sequence[str],
    start: int,
    end: int,
    font_size: int,
    lines: Sequence[str],
) -> int:
    """Compare renderer-only layouts without changing their frozen page span."""
    page_words = list(words[start:end])
    split = 0
    break_penalty = 0
    for line in lines[:-1]:
        split += len(str(line).split())
        break_penalty += _article_same_screen_intrinsic_line_break_penalty(
            cue,
            page_words,
            split,
            start + split,
        )
        break_penalty += _article_line_boundary_penalty(
            cue,
            start + split,
        )
    return (
        break_penalty
        + (ARTICLE_SUBTITLE_EN_FONT_SIZE - int(font_size))
        * ARTICLE_LINE_FONT_PIXEL_PENALTY
    )


def _article_planning_final_page_layout(
    draw: ImageDraw.ImageDraw,
    cue: Cue,
    words: Sequence[str],
    start: int,
    end: int,
) -> tuple[int, list[str]] | None:
    """Use the v18 feasibility contract while selecting page boundaries."""
    text = " ".join(words[start:end])
    for font_size in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES:
        lines = _article_fixed_english_lines(
            draw,
            text,
            font_size=font_size,
            boundary_penalty=lambda split, base=start: (
                _article_page_planning_line_boundary_penalty(cue, base + split)
            ),
        )
        if lines:
            return int(font_size), list(lines)
    return None


def _finalize_article_same_screen_layout(
    cue: Cue,
    draw: ImageDraw.ImageDraw,
    plan: Mapping[str, object],
) -> dict:
    """Reflow frozen pages without changing their IDs, spans, or timing."""
    finalized = dict(plan)
    words = str(cue.en or "").split()
    pages = [dict(page) for page in plan.get("pages") or []]
    page_fonts: list[int] = []
    for page in pages:
        start = int(page["word_start"])
        end = int(page["word_end"]) + 1
        layout = _article_final_page_layout(draw, cue, words, start, end)
        if layout is None:
            return finalized
        font_size, lines = layout
        previous_font_size = int(
            page.get("english_font_size") or ARTICLE_SUBTITLE_EN_FONT_SIZE
        )
        previous_lines = [
            " ".join(str(line or "").split())
            for line in page.get("en_lines") or []
            if str(line or "").strip()
        ]
        previous_valid_lines = _article_fixed_english_lines(
            draw,
            " ".join(words[start:end]),
            font_size=previous_font_size,
            boundary_penalty=lambda split, base=start: (
                _article_line_boundary_penalty(cue, base + split)
            ),
            relax_same_screen_syntax=True,
            intrinsic_penalty=lambda page_words, split, base=start: (
                _article_same_screen_intrinsic_line_break_penalty(
                    cue,
                    page_words,
                    split,
                    base + split,
                )
            ),
        )
        if (
            font_size < previous_font_size
            and previous_font_size in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES
            and " ".join(previous_lines).split() == words[start:end]
            and previous_lines == previous_valid_lines
            and _article_same_screen_layout_score(
                cue,
                words,
                start,
                end,
                font_size,
                lines,
            )
            >= _article_same_screen_layout_score(
                cue,
                words,
                start,
                end,
                previous_font_size,
                previous_lines,
            )
        ):
            font_size = previous_font_size
            lines = previous_lines
        page["en_lines"] = list(lines)
        page["english_font_size"] = int(font_size)
        page["en_width"] = _article_english_layout_width(
            draw,
            lines,
            font_size,
        )
        page["line_wrap_review"] = bool(
            _has_discouraged_caption_break(
                str(page.get("en") or ""),
                lines,
                boundary_penalty=lambda split, base=start: (
                    _article_line_boundary_penalty(cue, base + split)
                ),
                intrinsic_penalty=lambda page_words, split, base=start: (
                    _article_same_screen_intrinsic_line_break_penalty(
                        cue,
                        page_words,
                        split,
                        base + split,
                    )
                ),
            )
        )
        page_fonts.append(int(font_size))
    if not pages or not page_fonts:
        return finalized
    selected_font = min(page_fonts)
    finalized["pages"] = pages
    finalized["font_size"] = {
        **dict(plan.get("font_size") or {}),
        "english": selected_font,
    }
    finalized["font_fallback"] = (
        {"used": False}
        if selected_font == ARTICLE_SUBTITLE_EN_FONT_SIZE
        else {
            "used": True,
            "from": ARTICLE_SUBTITLE_EN_FONT_SIZE,
            "to": selected_font,
            "reason": (
                "no_safe_normal_font_layout"
                if selected_font < ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE
                else "no_safe_higher_font_layout"
            ),
        }
    )
    return finalized


def reflow_article_frozen_page_plan_same_screen(
    cue: Cue,
    frozen_plan: Mapping[str, object],
) -> dict:
    """Upgrade only the typography inside already frozen display pages."""
    words = str(cue.en or "").split()
    timing = list(cue.word_timing or ())
    raw_pages = list(frozen_plan.get("pages") or [])
    try:
        first_word_id = int(timing[0]["word_id"])
        last_word_id = int(timing[-1]["word_id"])
        plan_word_start = int(frozen_plan["word_start"])
        plan_word_end = int(frozen_plan["word_end"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "frozen_page_reflow_invalid"}]
        ) from exc
    if (
        not words
        or len(words) != len(timing)
        or not raw_pages
        or plan_word_start != first_word_id
        or plan_word_end != last_word_id
    ):
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "frozen_page_reflow_invalid"}]
        )

    local_pages: list[dict] = []
    expected_start = first_word_id
    for raw_page in raw_pages:
        if not isinstance(raw_page, Mapping):
            raise RenderStructuralOverflowError(
                [{"cue_index": cue.index, "reason": "frozen_page_reflow_invalid"}]
            )
        try:
            global_start = int(raw_page["word_start"])
            global_end = int(raw_page["word_end"])
            previous_font = int(raw_page["english_font_size"])
            previous_width = int(raw_page["english_width"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RenderStructuralOverflowError(
                [{"cue_index": cue.index, "reason": "frozen_page_reflow_invalid"}]
            ) from exc
        local_start = global_start - first_word_id
        local_end = global_end - first_word_id
        page_english = " ".join(words[local_start : local_end + 1])
        if (
            global_start != expected_start
            or local_start < 0
            or local_end < local_start
            or local_end >= len(words)
            or page_english
            != " ".join(str(raw_page.get("english") or "").split())
        ):
            raise RenderStructuralOverflowError(
                [{"cue_index": cue.index, "reason": "frozen_page_reflow_invalid"}]
            )
        local_pages.append(
            {
                "word_start": local_start,
                "word_end": local_end,
                "en": page_english,
                "en_lines": list(raw_page.get("english_lines") or []),
                "english_font_size": previous_font,
                "en_width": previous_width,
            }
        )
        expected_start = global_end + 1
    if expected_start - 1 != last_word_id:
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "frozen_page_reflow_invalid"}]
        )

    local_plan = {
        "font_size": {
            "english": int(
                frozen_plan.get("english_font_size")
                or min(page["english_font_size"] for page in local_pages)
            ),
            "chinese": ARTICLE_SUBTITLE_ZH_FONT_SIZE,
        },
        "font_fallback": dict(frozen_plan.get("font_fallback") or {"used": False}),
        "pages": local_pages,
    }
    finalized = _finalize_article_same_screen_layout(cue, ImageDraw.Draw(
        Image.new("RGB", (ARTICLE_WIDTH, ARTICLE_HEIGHT))
    ), local_plan)
    finalized_pages = list(finalized.get("pages") or [])
    if len(finalized_pages) != len(raw_pages):
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "frozen_page_reflow_invalid"}]
        )

    upgraded = copy.deepcopy(dict(frozen_plan))
    upgraded_pages = list(upgraded.get("pages") or [])
    for upgraded_page, finalized_page in zip(upgraded_pages, finalized_pages):
        upgraded_page["english_lines"] = list(finalized_page["en_lines"])
        upgraded_page["english_font_size"] = int(
            finalized_page["english_font_size"]
        )
        upgraded_page["english_width"] = int(finalized_page["en_width"])
    upgraded["pages"] = upgraded_pages
    upgraded["english_font_size"] = int(finalized["font_size"]["english"])
    upgraded["font_fallback"] = dict(finalized.get("font_fallback") or {})
    return upgraded


def _build_article_english_page_plan(
    cue: Cue,
    draw: ImageDraw.ImageDraw,
    *,
    _return_candidates: bool = False,
) -> dict:
    """Freeze the English word pages before any Chinese page text is selected."""
    words = str(cue.en or "").split()
    if not words:
        return {
            "status": "render_structural_overflow",
            "errors": [{"cue_index": cue.index, "reason": "empty_english_cue"}],
        }
    failure_reasons: set[str] = set()
    candidates: list[dict] = []
    layout_cache: dict[tuple[int, int, int, bool], tuple[str, ...]] = {}
    balance_cache: dict[tuple[int, int, int, int], float] = {}

    def span_layout(
        start: int,
        end: int,
        font_size: int,
        paginated: bool,
    ) -> tuple[str, ...]:
        key = (start, end, font_size, paginated)
        if key not in layout_cache:
            layout_cache[key] = tuple(
                _article_fixed_english_lines(
                    draw,
                    " ".join(words[start:end]),
                    font_size=font_size,
                    enforce_word_limit=paginated,
                    boundary_penalty=lambda local_split, base=start: (
                        _article_page_planning_line_boundary_penalty(
                            cue,
                            base + local_split,
                        )
                    ),
                )
            )
        return layout_cache[key]

    def span_balance(
        start: int,
        end: int,
        font_size: int,
        page_count: int,
    ) -> float:
        key = (start, end, font_size, page_count)
        if key not in balance_cache:
            balance_cache[key] = _article_page_span_balance_cost(
                draw,
                words,
                start,
                end,
                cue.word_timing,
                font_size,
                page_count,
            )
        return balance_cache[key]

    base_static_lines = list(
        span_layout(
            0,
            len(words),
            ARTICLE_SUBTITLE_EN_FONT_SIZE,
            False,
        )
    )
    base_preferred_page_count = _article_preferred_readability_page_count(
        draw,
        words,
        str(cue.zh or ""),
        font_size=ARTICLE_SUBTITLE_EN_FONT_SIZE,
        cue_duration_ms=max(0, round((float(cue.end) - float(cue.start)) * 1000)),
    )
    if not base_static_lines and len(words) > ARTICLE_VISUAL_PAGE_PREFERRED_WORDS:
        base_preferred_page_count = max(2, base_preferred_page_count)

    for font_size in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES:
        max_page_count = min(ARTICLE_VISUAL_PAGE_MAX_PAGES, len(words))
        for page_count in range(1, max_page_count + 1):
            attempt_diagnostics: set[str] = set()
            spans = _partition_article_english_pages(
                draw,
                cue,
                words,
                page_count,
                cue.word_timing,
                font_size,
                diagnostics=attempt_diagnostics,
                span_layout=span_layout,
                span_balance=span_balance,
            )
            forced_continuation = False
            if spans is None and page_count > 1:
                spans = _partition_article_english_pages(
                    draw,
                    cue,
                    words,
                    page_count,
                    cue.word_timing,
                    font_size,
                    diagnostics=attempt_diagnostics,
                    allow_forced_continuation=True,
                    span_layout=span_layout,
                    span_balance=span_balance,
                )
                forced_continuation = spans is not None
            if spans is None:
                failure_reasons.update(
                    attempt_diagnostics or {"no_complete_legal_page_partition"}
                )
                continue
            page_layouts = [
                _article_planning_final_page_layout(draw, cue, words, start, end)
                for start, end in spans
            ]
            if any(layout is None for layout in page_layouts):
                failure_reasons.add("english_does_not_fit_fixed_font")
                continue
            page_font_sizes = [int(layout[0]) for layout in page_layouts if layout]
            english_layouts = [list(layout[1]) for layout in page_layouts if layout]
            selected_parent_font = min(page_font_sizes)
            boundaries, timing_reason = _schedule_article_page_boundaries(cue, spans)
            if boundaries is None:
                failure_reasons.add(timing_reason)
                continue
            boundary_decisions = [
                (
                    _article_forced_continuation_decision(cue, words, start)
                    if forced_continuation
                    else _article_display_boundary_decision(cue, start)
                )
                for start, _ in spans[1:]
            ]
            boundary_costs = [
                _article_page_break_score(
                    cue,
                    words,
                    start,
                    len(words) / page_count,
                    cue.word_timing,
                    allow_forced_continuation=forced_continuation,
                )
                for start, _ in spans[1:]
            ]
            if any(cost is None for cost in boundary_costs):
                failure_reasons.add("hard_page_boundary")
                continue
            boundary_risks = [
                _article_page_boundary_risk(decision, int(cost or 0))
                for decision, cost in zip(boundary_decisions, boundary_costs)
            ]
            review_count = sum(
                decision.get("classification") == "review"
                for decision in boundary_decisions
            )
            high_risk_count = sum(risk > 0 for risk in boundary_risks)
            medium_risk_count = sum(
                decision.get("classification") == "review"
                and decision.get("confidence") == "medium"
                for decision in boundary_decisions
            )
            low_risk_count = sum(
                decision.get("classification") == "review"
                and decision.get("confidence") == "low"
                for decision in boundary_decisions
            )
            supported_restart_count = sum(
                decision.get("classification") == "review"
                and decision.get("strong_pause_evidence")
                for decision in boundary_decisions
            )
            tight_complete_phrase_count = sum(
                bool(decision.get("tight_complete_phrase_start"))
                for decision in boundary_decisions
            )
            risk_score = sum(boundary_risks)
            soft_word_overflow = sum(
                max(0, end - start - ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS)
                for start, end in spans
            )
            page_balance_cost = sum(
                span_balance(start, end, font_size, page_count)
                for start, end in spans
            )
            pages = [
                {
                    "index": index,
                    "display_page_id": (
                        display_page_id(cue.subtitle_id, index + 1)
                        if cue.subtitle_id
                        else ""
                    ),
                    "parent_subtitle_id": str(cue.subtitle_id or ""),
                    "en": " ".join(words[start:end]),
                    "word_start": start,
                    "word_end": end - 1,
                    "global_word_start": (
                        int(cue.word_timing[start].get("word_id"))
                        if len(cue.word_timing) == len(words)
                        and cue.word_timing[start].get("word_id") is not None
                        else None
                    ),
                    "global_word_end": (
                        int(cue.word_timing[end - 1].get("word_id"))
                        if len(cue.word_timing) == len(words)
                        and cue.word_timing[end - 1].get("word_id") is not None
                        else None
                    ),
                    "start": boundaries[index],
                    "end": boundaries[index + 1],
                    "en_lines": english_layouts[index],
                    "english_font_size": page_font_sizes[index],
                    "boundary_before": (
                        boundary_decisions[index - 1]
                        if index > 0
                        else {
                            "classification": "allow",
                            "issue_codes": [],
                            "confidence": "low",
                        }
                    ),
                    "en_width": _article_english_layout_width(
                        draw,
                        english_layouts[index],
                        page_font_sizes[index],
                    ),
                    "line_wrap_review": bool(
                        _has_discouraged_caption_break(
                            " ".join(words[start:end]),
                            english_layouts[index],
                            boundary_penalty=lambda split, base=start: (
                                _article_line_boundary_penalty(cue, base + split)
                            ),
                        )
                    ),
                }
                for index, (start, end) in enumerate(spans)
            ]
            warnings = []
            last_word = (
                re.sub(r"[^A-Za-z']", "", words[-1]).lower()
                if words
                else ""
            )
            static_dangling_tail = bool(
                page_count == 1
                and last_word in LINE_BREAK_AVOID_AFTER_WORDS
                and not _caption_has_terminal_completion(words)
            )
            if (
                (
                    page_count < base_preferred_page_count
                    or static_dangling_tail
                )
                and not (
                    page_count == 1
                    and _caption_has_terminal_completion(words)
                )
            ):
                warnings.append(
                    {
                        "reason": "preferred_readability_page_unscheduled",
                        "requested_page_count": max(
                            base_preferred_page_count,
                            2 if static_dangling_tail else 1,
                        ),
                    }
                )
            if review_count:
                warnings.append(
                    {
                        "reason": "review_boundary_fallback",
                        "boundary_count": review_count,
                        "high_risk_count": high_risk_count,
                        "risk_score": risk_score,
                    }
                )
            if forced_continuation:
                warnings.append(
                    {
                        "reason": "forced_complete_continuation_page_split",
                        "boundary_count": sum(
                            bool(decision.get("forced_display_continuation"))
                            for decision in boundary_decisions
                        ),
                        "requires_review": True,
                    }
                )
            if soft_word_overflow:
                warnings.append(
                    {
                        "reason": "visual_word_budget_exceeded",
                        "soft_limit": ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS,
                        "overflow_words": soft_word_overflow,
                    }
                )
            if selected_parent_font < ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE:
                warnings.append(
                    {
                        "reason": "emergency_font_fallback",
                        "normal_minimum": ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE,
                        "selected": selected_parent_font,
                        "requires_review": True,
                    }
                )
            page_word_counts = [end - start for start, end in spans]
            if (
                len(page_word_counts) > 1
                and max(page_word_counts) / max(min(page_word_counts), 1) >= 1.8
            ):
                warnings.append(
                    {
                        "reason": "display_page_load_imbalance",
                        "page_word_counts": page_word_counts,
                        "balance_cost": round(page_balance_cost),
                    }
                )
            plan = {
                "status": "ok",
                "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
                "font_size": {
                    "english": selected_parent_font,
                    "chinese": ARTICLE_SUBTITLE_ZH_FONT_SIZE,
                },
                "font_fallback": (
                    {
                        "used": True,
                        "from": ARTICLE_SUBTITLE_EN_FONT_SIZE,
                        "to": selected_parent_font,
                        "reason": (
                            "no_safe_normal_font_layout"
                            if selected_parent_font < ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE
                            else "no_safe_higher_font_layout"
                        ),
                    }
                    if selected_parent_font != ARTICLE_SUBTITLE_EN_FONT_SIZE
                    else {"used": False}
                ),
                "pages": pages,
                "readability_warnings": warnings,
            }
            font_reduction = ARTICLE_SUBTITLE_EN_FONT_SIZE - selected_parent_font
            quality_cost = (
                sum(int(cost or 0) for cost in boundary_costs)
                + page_balance_cost
                + soft_word_overflow * 300
                + font_reduction * DISPLAY_PAGE_FONT_STEP_PENALTY
                + abs(page_count - base_preferred_page_count)
                * DISPLAY_PAGE_COUNT_DEVIATION_PENALTY
                + max(0, page_count - 1) * DISPLAY_PAGE_TRANSITION_PENALTY
            )
            candidates.append(
                {
                    "plan": plan,
                    "page_count": page_count,
                    "font_reduction": font_reduction,
                    "forced_continuation": forced_continuation,
                    "risk_score": risk_score,
                    "high_risk_count": high_risk_count,
                    "medium_risk_count": medium_risk_count,
                    "low_risk_count": low_risk_count,
                    "supported_restart_count": supported_restart_count,
                    "severe_risk_count": sum(
                        risk >= 3 for risk in boundary_risks
                    ),
                    "tight_complete_phrase_count": tight_complete_phrase_count,
                    "review_count": review_count,
                    "quality_cost": round(quality_cost),
                    "page_pressures": tuple(
                        _article_display_page_pressure(page) for page in pages
                    ),
                }
            )
    if candidates:
        normal_font_candidates = [
            candidate
            for candidate in candidates
            if candidate["plan"]["font_size"]["english"]
            >= ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE
        ]
        if normal_font_candidates:
            candidates = normal_font_candidates
        # Page count is a reading-load decision. Break rewards and penalties
        # are deliberately absent here; they select a boundary only after the
        # number of pages is fixed.
        strict_candidates = [
            candidate
            for candidate in candidates
            if not candidate["forced_continuation"]
        ]
        selection_pool = strict_candidates or candidates
        secondary_review_candidates = _article_high_pressure_review_candidates(
            selection_pool,
            total_word_count=len(words),
        )
        if secondary_review_candidates:
            selection_pool = secondary_review_candidates
        if _return_candidates:
            if not secondary_review_candidates:
                safe_preferred_font_candidates = [
                    candidate
                    for candidate in selection_pool
                    if candidate["plan"]["font_size"]["english"]
                    == ARTICLE_SUBTITLE_EN_FONT_SIZE
                    and not candidate["forced_continuation"]
                    and not candidate["severe_risk_count"]
                    and not candidate["medium_risk_count"]
                ]
                if safe_preferred_font_candidates:
                    selection_pool = safe_preferred_font_candidates
            by_page_count = {
                page_count: [
                    candidate
                    for candidate in selection_pool
                    if candidate["page_count"] == page_count
                ]
                for page_count in sorted(
                    {candidate["page_count"] for candidate in selection_pool}
                )
            }
            preferred_candidates = by_page_count.get(
                base_preferred_page_count,
                [],
            )
            static_candidates = by_page_count.get(1, [])
            best_static_font_reduction = min(
                (
                    candidate["font_reduction"]
                    for candidate in static_candidates
                ),
                default=None,
            )
            preferred_is_low_confidence_or_supported_only = bool(
                preferred_candidates
                and all(
                    candidate["review_count"]
                    == candidate["low_risk_count"]
                    + candidate["supported_restart_count"]
                    for candidate in preferred_candidates
                )
            )
            if (
                not secondary_review_candidates
                and base_preferred_page_count > 1
                and preferred_candidates
                and static_candidates
                and all(
                    candidate["severe_risk_count"]
                    or candidate["tight_complete_phrase_count"]
                    for candidate in preferred_candidates
                )
                and (
                    not preferred_is_low_confidence_or_supported_only
                    or best_static_font_reduction
                    <= ARTICLE_PAGE_LOW_CONFIDENCE_FONT_REDUCTION_LIMIT
                )
            ):
                selection_pool = static_candidates
            return {
                "status": "candidate_bundle",
                "candidates": selection_pool,
                "preferred_page_count": base_preferred_page_count,
                "candidate_mode": (
                    "strict" if strict_candidates else "forced_continuation"
                ),
            }
        by_page_count = {
            page_count: [
                candidate
                for candidate in selection_pool
                if candidate["page_count"] == page_count
            ]
            for page_count in sorted(
                {candidate["page_count"] for candidate in selection_pool}
            )
        }
        available_page_counts = sorted(by_page_count)
        selected_page_count = min(
            available_page_counts,
            key=lambda page_count: (
                abs(page_count - base_preferred_page_count),
                page_count < base_preferred_page_count,
                page_count,
            ),
        )
        preferred_candidates = by_page_count.get(base_preferred_page_count, [])
        best_static_font_reduction = min(
            (
                candidate["font_reduction"]
                for candidate in by_page_count.get(1, [])
            ),
            default=None,
        )
        preferred_is_low_confidence_or_supported_only = bool(
            preferred_candidates
            and all(
                candidate["review_count"]
                == candidate["low_risk_count"]
                + candidate["supported_restart_count"]
                for candidate in preferred_candidates
            )
        )
        if (
            not secondary_review_candidates
            and base_preferred_page_count > 1
            and preferred_candidates
            and 1 in by_page_count
            and all(
                candidate["severe_risk_count"]
                or candidate["tight_complete_phrase_count"]
                for candidate in preferred_candidates
            )
            and (
                not preferred_is_low_confidence_or_supported_only
                or best_static_font_reduction
                <= ARTICLE_PAGE_LOW_CONFIDENCE_FONT_REDUCTION_LIMIT
            )
        ):
            # Avoid structurally uncertain page turns. A low-confidence turn
            # may still beat the deepest 50px fallback, but not the normal
            # 54/52px fallback range; medium/high risk never wins on font size.
            selected_page_count = 1

        selected = min(
            by_page_count[selected_page_count],
            key=lambda candidate: (
                candidate["risk_score"],
                candidate["high_risk_count"],
                candidate["medium_risk_count"],
                candidate["low_risk_count"],
                candidate["font_reduction"],
                candidate["quality_cost"],
            ),
        )
        selected["plan"]["page_count_decision"] = {
            "preferred": base_preferred_page_count,
            "selected": selected_page_count,
            "candidate_mode": (
                "strict" if strict_candidates else "forced_continuation"
            ),
            "basis": "pixel_word_chinese_duration_load",
        }
        return _finalize_article_same_screen_layout(
            cue,
            draw,
            selected["plan"],
        )
    reason_priority = (
        "missing_or_mismatched_word_ledger",
        "no_word_boundary_with_minimum_page_duration",
        "cue_duration_below_page_minimum",
        "hard_page_boundary",
        "fixed_font_span_unreadable",
        "no_complete_legal_page_partition",
        "no_fixed_font_page_partition",
    )
    primary_reason = next(
        (reason for reason in reason_priority if reason in failure_reasons),
        "no_fixed_font_page_partition",
    )
    return {
        "status": "render_structural_overflow",
        "errors": [
            {
                "cue_index": cue.index,
                "reason": primary_reason,
                "attempted_reasons": sorted(failure_reasons),
            }
        ],
    }


def _article_display_page_pressure(page: Mapping[str, object]) -> float:
    """Measure page density without turning a word target into a hard limit."""
    english = " ".join(str(page.get("en") or "").split())
    word_count = len(english.split())
    duration = max(
        float(page.get("end") or 0.0) - float(page.get("start") or 0.0),
        0.001,
    )
    word_load = word_count / max(ARTICLE_VISUAL_PAGE_PREFERRED_WORDS, 1)
    width_load = float(page.get("en_width") or 0.0) / max(
        float(acx(ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH)),
        1.0,
    )
    spoken_load = (word_count / duration) / 3.2
    return round(max(word_load, width_load, spoken_load), 6)


def _article_high_pressure_review_candidates(
    candidates: Sequence[Mapping[str, object]],
    *,
    total_word_count: int,
) -> list[dict]:
    """Promote only complete, readable review cuts over a dense static page."""
    static_candidates = [
        candidate
        for candidate in candidates
        if int(candidate.get("page_count") or 0) == 1
    ]
    if not static_candidates:
        return []
    static_is_high_pressure = any(
        total_word_count > ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS
        or int(candidate.get("plan", {}).get("font_size", {}).get("english") or 0)
        <= 52
        for candidate in static_candidates
    )
    if not static_is_high_pressure:
        return []

    promoted: list[dict] = []
    for candidate in candidates:
        plan = candidate.get("plan") or {}
        pages = list(plan.get("pages") or [])
        if (
            int(candidate.get("page_count") or 0) <= 1
            or int(plan.get("font_size", {}).get("english") or 0)
            != ARTICLE_SUBTITLE_EN_FONT_SIZE
            or candidate.get("forced_continuation")
            or int(candidate.get("severe_risk_count") or 0)
            or not pages
        ):
            continue
        if any(
            len(str(page.get("en") or "").split())
            < ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
            or (
                float(page.get("end") or 0.0)
                - float(page.get("start") or 0.0)
            )
            * 1000
            < ARTICLE_PAGE_MIN_DURATION_MS
            for page in pages
        ):
            continue
        if not all(
            _article_secondary_review_boundary_is_complete(page)
            for page in pages[1:]
        ):
            continue

        promoted_candidate = dict(candidate)
        promoted_plan = dict(plan)
        warnings = list(promoted_plan.get("readability_warnings") or [])
        warnings.append(
            {
                "reason": "high_pressure_secondary_page_review",
                "review_required": True,
            }
        )
        promoted_plan["readability_warnings"] = warnings
        promoted_candidate["plan"] = promoted_plan
        promoted_candidate["secondary_review_promoted"] = True
        promoted.append(promoted_candidate)
    return promoted


def _article_secondary_review_boundary_is_complete(
    right_page: Mapping[str, object],
) -> bool:
    decision = right_page.get("boundary_before") or {}
    if str(decision.get("classification") or "") == "reject":
        return False
    issue_codes = {
        str(issue or "") for issue in decision.get("issue_codes") or []
    }
    if issue_codes & {
        "modifier_head_split",
        "modifier_noun_head_split",
        "post_noun_participial_modifier_split",
        "subject_predicate_split",
        "subject_finite_verb_split",
        "verb_object_split",
        "to_infinitive_split",
    }:
        return False
    words = str(right_page.get("en") or "").split()
    if not words:
        return False
    first_word = re.sub(r"[^A-Za-z]+", "", words[0]).casefold()
    return bool(
        decision.get("strong_pause_evidence")
        and int(decision.get("pause_ms") or 0)
        >= ARTICLE_PAGE_SECONDARY_REVIEW_STRONG_PAUSE_MS
        or decision.get("complete_page_clause_start")
        or first_word in {"that", "who", "which"}
    )


def _article_dense_page_pair_cost(left: float, right: float) -> float:
    shared_overload = max(0.0, min(float(left), float(right)) - 0.95)
    return shared_overload * shared_overload * 6_000


def _article_candidate_sequence_cost(candidate: Mapping[str, object]) -> float:
    pressures = tuple(float(value) for value in candidate.get("page_pressures") or ())
    overload_cost = sum(max(0.0, value - 1.0) ** 2 * 3_000 for value in pressures)
    consecutive_cost = sum(
        _article_dense_page_pair_cost(left, right)
        for left, right in zip(pressures, pressures[1:])
    )
    return float(candidate.get("quality_cost") or 0.0) + overload_cost + consecutive_cost


def _select_article_page_plan_sequence(
    candidate_groups: Sequence[Sequence[Mapping[str, object]]],
) -> list[Mapping[str, object]]:
    """Choose cue-local page plans while accounting for adjacent page pressure.

    The state space is bounded by the existing per-cue candidates.  The
    dynamic program never moves words across frozen subtitle IDs; it only
    chooses among already valid renderer projections.
    """
    groups = [list(group) for group in candidate_groups]
    if not groups or any(not group for group in groups):
        return []

    states: list[tuple[tuple[int, int, float], list[Mapping[str, object]]]] = []
    for candidate in groups[0]:
        states.append(
            (
                (
                    int(bool(candidate.get("forced_continuation"))),
                    int(candidate.get("severe_risk_count") or 0),
                    _article_candidate_sequence_cost(candidate),
                ),
                [candidate],
            )
        )

    for group in groups[1:]:
        next_states = []
        for candidate in group:
            local_rank = (
                int(bool(candidate.get("forced_continuation"))),
                int(candidate.get("severe_risk_count") or 0),
                _article_candidate_sequence_cost(candidate),
            )
            current_pressures = tuple(
                float(value) for value in candidate.get("page_pressures") or ()
            )
            best = None
            for previous_rank, previous_path in states:
                previous = previous_path[-1]
                previous_pressures = tuple(
                    float(value) for value in previous.get("page_pressures") or ()
                )
                transition_cost = 0.0
                if previous_pressures and current_pressures:
                    transition_cost = _article_dense_page_pair_cost(
                        previous_pressures[-1],
                        current_pressures[0],
                    )
                rank = (
                    previous_rank[0] + local_rank[0],
                    previous_rank[1] + local_rank[1],
                    previous_rank[2] + local_rank[2] + transition_cost,
                )
                proposed = (rank, [*previous_path, candidate])
                if best is None or proposed[0] < best[0]:
                    best = proposed
            if best is not None:
                next_states.append(best)
        states = next_states
        if not states:
            return []
    return min(states, key=lambda state: state[0])[1]


def _finalize_article_sequence_candidate(
    candidate: Mapping[str, object],
    bundle: Mapping[str, object],
) -> dict:
    plan = dict(candidate.get("plan") or {})
    plan["page_count_decision"] = {
        "preferred": int(bundle.get("preferred_page_count") or 1),
        "selected": int(candidate.get("page_count") or 1),
        "candidate_mode": str(bundle.get("candidate_mode") or "strict"),
        "basis": (
            "high_pressure_secondary_review"
            if candidate.get("secondary_review_promoted")
            else "semantic_pixel_duration_sequence_pressure"
        ),
    }
    return plan


def build_article_visual_page_plan(
    cue: Cue,
    draw: ImageDraw.ImageDraw,
) -> dict:
    """Plan fixed-font pages from frozen English plus validated page Chinese."""
    # A validated display-page artifact owns the renderer projection. Replanning
    # a single cue here can choose different spans from the sequence planner and
    # invalidate otherwise correct page translations.
    frozen_plan = cue.article_page_plan
    if (
        isinstance(frozen_plan, Mapping)
        and frozen_plan.get("status") == "ok"
        and str(frozen_plan.get("source") or "").startswith("frozen_")
    ):
        return dict(frozen_plan)

    plan = _build_article_english_page_plan(cue, draw)
    if plan.get("status") != "ok":
        return plan
    pages = [dict(page) for page in plan.get("pages") or []]
    chinese = re.sub(r"\s+", "", str(cue.zh or ""))
    if len(pages) <= 1:
        chinese_pages = [chinese]
    else:
        expected_page_ids = [str(page.get("display_page_id") or "") for page in pages]
        translations = dict(cue.display_page_translations or {})
        chinese_pages = [
            re.sub(r"\s+", "", str(translations.get(page_id) or ""))
            for page_id in expected_page_ids
        ]
        if (
            not cue.subtitle_id
            or not all(expected_page_ids)
            or set(translations) != set(expected_page_ids)
            or not all(chinese_pages)
            or "".join(chinese_pages) != chinese
        ):
            return {
                "status": "render_structural_overflow",
                "errors": [
                    {
                        "cue_index": cue.index,
                        "reason": "missing_or_invalid_display_page_translations",
                    }
                ],
            }
    if any(not _article_fixed_chinese_lines(draw, page) for page in chinese_pages if page):
        return {
            "status": "render_structural_overflow",
            "errors": [
                {
                    "cue_index": cue.index,
                    "reason": "chinese_does_not_fit_fixed_font",
                }
            ],
        }
    for page, chinese_page in zip(pages, chinese_pages):
        page["zh"] = chinese_page
    plan["pages"] = pages
    return plan


def article_display_page_layout_profile() -> dict:
    return {
        "template": "article_words",
        "width": ARTICLE_WIDTH,
        "height": ARTICLE_HEIGHT,
        "english_font_size": ARTICLE_SUBTITLE_EN_FONT_SIZE,
        "english_font_fallback_sizes": list(ARTICLE_SUBTITLE_EN_FALLBACK_SIZES),
        "english_emergency_fallback_sizes": list(
            ARTICLE_SUBTITLE_EN_EMERGENCY_FALLBACK_SIZES
        ),
        "english_normal_min_size": ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE,
        "english_min_size": ARTICLE_SUBTITLE_EN_MIN_SIZE,
        "chinese_font_size": ARTICLE_SUBTITLE_ZH_FONT_SIZE,
        "english_comfortable_width": ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
        "english_width": ARTICLE_SUBTITLE_EN_WIDTH,
        "english_wide_safe_width": ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
        "chinese_width": ARTICLE_SUBTITLE_ZH_WIDTH,
        "max_lines": 2,
        "minimum_page_duration_ms": ARTICLE_PAGE_MIN_DURATION_MS,
    }


def build_article_display_page_blueprint(cues: Sequence[Cue]) -> dict:
    """Return only multi-page parents after final word timing is frozen."""
    draw = ImageDraw.Draw(Image.new("RGB", (ARTICLE_WIDTH, ARTICLE_HEIGHT)))
    errors: list[dict] = []
    bundles: list[dict] = []
    for cue in cues:
        bundle = _build_article_english_page_plan(
            cue,
            draw,
            _return_candidates=True,
        )
        if bundle.get("status") != "candidate_bundle":
            errors.extend(bundle.get("errors") or [])
            continue
        bundles.append(bundle)
    if errors:
        raise RenderStructuralOverflowError(errors)
    selected_candidates = _select_article_page_plan_sequence(
        [bundle["candidates"] for bundle in bundles]
    )
    if len(selected_candidates) != len(cues):
        raise RenderStructuralOverflowError(
            [{"cue_index": "all", "reason": "display_page_sequence_unavailable"}]
        )

    parents: list[dict] = []
    render_plans: list[dict] = []
    for cue, bundle, selected in zip(cues, bundles, selected_candidates):
        plan = _finalize_article_sequence_candidate(selected, bundle)
        plan = _finalize_article_same_screen_layout(cue, draw, plan)
        pages = list(plan.get("pages") or [])
        if (
            not cue.subtitle_id
            or not pages
            or pages[0].get("global_word_start") is None
            or pages[-1].get("global_word_end") is None
        ):
            errors.append(
                {
                    "cue_index": cue.index,
                    "reason": "missing_or_mismatched_word_ledger",
                }
            )
            continue
        frozen_pages = [
            {
                "display_page_id": page["display_page_id"],
                "word_start": int(page["global_word_start"]),
                "word_end": int(page["global_word_end"]),
                "english": page["en"],
                "start_ms": round(float(page["start"]) * 1000),
                "end_ms": round(float(page["end"]) * 1000),
                "english_lines": list(page.get("en_lines") or []),
                "english_font_size": int(page["english_font_size"]),
                "english_width": int(page["en_width"]),
                "boundary_before": dict(page.get("boundary_before") or {}),
            }
            for page in pages
        ]
        render_plans.append(
            {
                "parent_subtitle_id": cue.subtitle_id,
                "english": cue.en,
                "chinese": cue.zh,
                "word_start": int(pages[0]["global_word_start"]),
                "word_end": int(pages[-1]["global_word_end"]),
                "english_font_size": int(plan["font_size"]["english"]),
                "font_fallback": dict(plan.get("font_fallback") or {"used": False}),
                "pages": frozen_pages,
            }
        )
        if len(pages) <= 1:
            continue
        parents.append(
            {
                "parent_subtitle_id": cue.subtitle_id,
                "english": cue.en,
                "chinese": cue.zh,
                "word_start": int(pages[0]["global_word_start"]),
                "word_end": int(pages[-1]["global_word_end"]),
                "pages": frozen_pages,
            }
        )
    if errors:
        raise RenderStructuralOverflowError(errors)
    return {
        "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
        "layout_profile": article_display_page_layout_profile(),
        "parents": parents,
        "render_plans": render_plans,
    }


def propose_article_manual_page_word_ranges(
    cue: Cue,
    page_count: int,
    *,
    allow_review_boundary: bool = False,
) -> list[tuple[int, int]]:
    """Plan an explicit page count with the normal syntax/timing scorer."""
    requested = int(page_count)
    words = str(cue.en or "").split()
    timing = list(cue.word_timing or ())
    if (
        requested < 2
        or requested > ARTICLE_VISUAL_PAGE_MAX_PAGES
        or requested > len(words)
        or len(words) != len(timing)
    ):
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "manual_page_count_invalid"}]
        )
    try:
        first_word_id = int(timing[0]["word_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "missing_or_mismatched_word_ledger"}]
        ) from exc

    draw = ImageDraw.Draw(Image.new("RGB", (ARTICLE_WIDTH, ARTICLE_HEIGHT)))
    attempted_reasons: set[str] = set()
    for allow_forced_continuation in (False, True):
        for font_size in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES:
            diagnostics: set[str] = set()
            spans = _partition_article_english_pages(
                draw,
                cue,
                words,
                requested,
                cue.word_timing,
                font_size,
                diagnostics=diagnostics,
                allow_forced_continuation=allow_forced_continuation,
            )
            attempted_reasons.update(diagnostics)
            if spans is None:
                continue
            schedule, schedule_error = _schedule_article_page_boundaries(cue, spans)
            if schedule is None:
                attempted_reasons.add(schedule_error)
                continue
            return [
                (first_word_id + start, first_word_id + end - 1)
                for start, end in spans
            ]

    if allow_review_boundary:
        for font_size in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES:
            diagnostics: set[str] = set()
            spans = _partition_article_english_pages(
                draw,
                cue,
                words,
                requested,
                cue.word_timing,
                font_size,
                diagnostics=diagnostics,
                allow_review_boundary=True,
            )
            attempted_reasons.update(diagnostics)
            if spans is None:
                continue
            schedule, schedule_error = _schedule_article_page_boundaries(cue, spans)
            if schedule is None:
                attempted_reasons.add(schedule_error)
                continue
            return [
                (first_word_id + start, first_word_id + end - 1)
                for start, end in spans
            ]

    raise RenderStructuralOverflowError(
        [
            {
                "cue_index": cue.index,
                "reason": "manual_page_count_has_no_safe_partition",
                "requested_page_count": requested,
                "attempted_reasons": sorted(
                    reason for reason in attempted_reasons if reason
                ),
            }
        ]
    )


def rebuild_article_frozen_page_plan_from_word_ranges(
    cue: Cue,
    frozen_plan: Mapping[str, object],
    page_word_ranges: Sequence[tuple[int, int]],
    page_translations: Mapping[str, str],
    *,
    allow_page_count_change: bool = False,
    allow_incomplete_page_translations: bool = False,
    allow_manual_review: bool = False,
) -> dict:
    """Rebuild one frozen render plan after an explicit manual page-boundary move.

    The parent cue remains immutable. Only the continuous word ranges owned by
    its existing display-page IDs may change. Layout, timing, minimum duration,
    and hard-boundary checks are recomputed from the authoritative word ledger.
    """
    words = str(cue.en or "").split()
    timing = list(cue.word_timing or ())
    raw_pages = list(frozen_plan.get("pages") or [])
    if (
        not words
        or len(words) != len(timing)
        or not raw_pages
        or (
            len(page_word_ranges) != len(raw_pages)
            and not allow_page_count_change
        )
    ):
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "manual_page_boundary_invalid"}]
        )

    try:
        first_word_id = int(timing[0]["word_id"])
        last_word_id = int(timing[-1]["word_id"])
        ranges = [(int(start), int(end)) for start, end in page_word_ranges]
    except (KeyError, TypeError, ValueError) as exc:
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "manual_page_boundary_invalid"}]
        ) from exc

    expected_start = first_word_id
    for start, end in ranges:
        if start != expected_start or end < start or end > last_word_id:
            raise RenderStructuralOverflowError(
                [{"cue_index": cue.index, "reason": "manual_page_boundary_not_contiguous"}]
            )
        expected_start = end + 1
    if expected_start - 1 != last_word_id:
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "manual_page_boundary_not_contiguous"}]
        )

    local_spans = [
        (start - first_word_id, end - first_word_id + 1)
        for start, end in ranges
    ]
    schedule, schedule_error = _schedule_article_page_boundaries(
        cue,
        local_spans,
        minimum_page_duration_ms=(0 if allow_manual_review else None),
    )
    if schedule is None:
        raise RenderStructuralOverflowError(
            [
                {
                    "cue_index": cue.index,
                    "reason": schedule_error or "manual_page_timing_invalid",
                }
            ]
        )

    boundary_decisions: list[dict] = [{}]
    for local_start, _local_end in local_spans[1:]:
        decision = dict(_article_display_boundary_decision(cue, local_start) or {})
        if (
            str(decision.get("classification") or "") == "hard"
            and not allow_manual_review
        ):
            raise RenderStructuralOverflowError(
                [
                    {
                        "cue_index": cue.index,
                        "reason": "manual_page_boundary_is_hard",
                        "word_start": first_word_id + local_start,
                        "issue_codes": list(decision.get("issue_codes") or []),
                    }
                ]
            )
        if str(decision.get("classification") or "") == "hard":
            decision["classification"] = "review"
            decision["confidence"] = "high"
            decision["manual_original_classification"] = "hard"
        decision["manual_override"] = True
        boundary_decisions.append(decision)

    if allow_manual_review:
        short_page_indices = [
            page_index
            for page_index in range(len(local_spans))
            if (
                float(schedule[page_index + 1]) - float(schedule[page_index])
            )
            * 1000.0
            + 1e-6
            < ARTICLE_PAGE_MIN_DURATION_MS
        ]
        for page_index in short_page_indices:
            decision_index = min(max(page_index, 1), len(boundary_decisions) - 1)
            decision = boundary_decisions[decision_index]
            issue_codes = set(decision.get("issue_codes") or [])
            issue_codes.add("manual_short_page_review")
            decision["issue_codes"] = sorted(issue_codes)
            decision["classification"] = "review"
            decision["manual_override"] = True
            decision["page_duration_ms"] = round(
                (
                    float(schedule[page_index + 1])
                    - float(schedule[page_index])
                )
                * 1000
            )

    draw = ImageDraw.Draw(Image.new("RGB", (ARTICLE_WIDTH, ARTICLE_HEIGHT)))
    selected_layouts = [
        _article_final_page_layout(draw, cue, words, local_start, local_end)
        for local_start, local_end in local_spans
    ]
    if any(layout is None for layout in selected_layouts):
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "manual_page_layout_overflow"}]
        )
    selected_page_fonts = [
        int(layout[0]) for layout in selected_layouts if layout
    ]
    selected_lines = [list(layout[1]) for layout in selected_layouts if layout]
    selected_font = min(selected_page_fonts)

    page_templates = (
        raw_pages
        if len(raw_pages) == len(ranges)
        else [
            {"display_page_id": display_page_id(str(cue.subtitle_id or ""), index + 1)}
            for index in range(len(ranges))
        ]
    )
    frozen_pages = []
    for page_index, (
        (global_start, global_end),
        raw_page,
        lines,
        page_font_size,
    ) in enumerate(
        zip(ranges, page_templates, selected_lines, selected_page_fonts)
    ):
        page_id = str(raw_page.get("display_page_id") or "")
        if page_id != display_page_id(str(cue.subtitle_id or ""), page_index + 1):
            raise RenderStructuralOverflowError(
                [{"cue_index": cue.index, "reason": "manual_page_id_mismatch"}]
            )
        local_start = global_start - first_word_id
        local_end = global_end - first_word_id + 1
        frozen_pages.append(
            {
                "display_page_id": page_id,
                "word_start": global_start,
                "word_end": global_end,
                "english": " ".join(words[local_start:local_end]),
                "start_ms": round(float(schedule[page_index]) * 1000),
                "end_ms": round(float(schedule[page_index + 1]) * 1000),
                "english_lines": list(lines),
                "english_font_size": page_font_size,
                "english_width": _article_english_layout_width(
                    draw,
                    lines,
                    page_font_size,
                ),
                "boundary_before": boundary_decisions[page_index],
            }
        )

    rebuilt = {
        "parent_subtitle_id": str(cue.subtitle_id or ""),
        "english": str(cue.en or ""),
        "chinese": str(cue.zh or ""),
        "word_start": first_word_id,
        "word_end": last_word_id,
        "english_font_size": selected_font,
        "font_fallback": (
            {"used": False}
            if selected_font == ARTICLE_SUBTITLE_EN_FONT_SIZE
            else {
                "used": True,
                "from": ARTICLE_SUBTITLE_EN_FONT_SIZE,
                "to": selected_font,
                "reason": "manual_page_boundary_layout",
            }
        ),
        "pages": frozen_pages,
    }
    if (
        not allow_incomplete_page_translations
        and _article_plan_from_frozen_artifact(
            cue,
            rebuilt,
            page_translations,
            draw,
        ) is None
    ):
        raise RenderStructuralOverflowError(
            [{"cue_index": cue.index, "reason": "manual_page_boundary_invalid"}]
        )
    return rebuilt


def _article_plan_from_frozen_artifact(
    cue: Cue,
    frozen: Mapping[str, object],
    page_translations: Mapping[str, str],
    draw: ImageDraw.ImageDraw,
) -> dict | None:
    words = str(cue.en or "").split()
    timing = list(cue.word_timing or ())
    if not words or len(words) != len(timing):
        return None
    try:
        first_word_id = int(timing[0]["word_id"])
        last_word_id = int(timing[-1]["word_id"])
        font_size = int(frozen["english_font_size"])
        frozen_word_start = int(frozen["word_start"])
        frozen_word_end = int(frozen["word_end"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        str(frozen.get("parent_subtitle_id") or "") != str(cue.subtitle_id or "")
        or " ".join(str(frozen.get("english") or "").split()) != " ".join(words)
        or frozen_word_start != first_word_id
        or frozen_word_end != last_word_id
        or font_size not in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES
    ):
        return None
    font_fallback = dict(frozen.get("font_fallback") or {})
    if font_size == ARTICLE_SUBTITLE_EN_FONT_SIZE:
        if bool(font_fallback.get("used")):
            return None
    elif (
        not bool(font_fallback.get("used"))
        or int(font_fallback.get("from") or 0) != ARTICLE_SUBTITLE_EN_FONT_SIZE
        or int(font_fallback.get("to") or 0) != font_size
    ):
        return None

    raw_pages = list(frozen.get("pages") or [])
    if not raw_pages:
        return None
    pages: list[dict] = []
    expected_global_start = first_word_id
    previous_end_ms: int | None = None
    for page_index, raw_page in enumerate(raw_pages):
        if not isinstance(raw_page, Mapping):
            return None
        try:
            global_start = int(raw_page["word_start"])
            global_end = int(raw_page["word_end"])
            start_ms = int(raw_page["start_ms"])
            end_ms = int(raw_page["end_ms"])
            page_font_size = int(raw_page["english_font_size"])
            english_width = int(raw_page["english_width"])
        except (KeyError, TypeError, ValueError):
            return None
        local_start = global_start - first_word_id
        local_end = global_end - first_word_id
        if (
            global_start != expected_global_start
            or local_start < 0
            or local_end < local_start
            or local_end >= len(words)
            or page_font_size not in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES
            or english_width
            not in {
                ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
                ARTICLE_SUBTITLE_EN_WIDTH,
                ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
            }
            or (previous_end_ms is not None and start_ms != previous_end_ms)
        ):
            return None
        page_english = " ".join(words[local_start : local_end + 1])
        if page_english != " ".join(str(raw_page.get("english") or "").split()):
            return None
        expected_lines = _article_fixed_english_lines(
            draw,
            page_english,
            font_size=page_font_size,
            boundary_penalty=lambda split, base=local_start: (
                _article_line_boundary_penalty(cue, base + split)
            ),
            relax_same_screen_syntax=True,
            intrinsic_penalty=lambda page_words, split, base=local_start: (
                _article_same_screen_intrinsic_line_break_penalty(
                    cue,
                    page_words,
                    split,
                    base + split,
                )
            ),
        )
        frozen_lines = [
            " ".join(str(line or "").split())
            for line in raw_page.get("english_lines") or []
        ]
        expected_width = _article_english_layout_width(
            draw,
            expected_lines,
            page_font_size,
        )
        boundary_before = dict(raw_page.get("boundary_before") or {})
        if (
            not expected_lines
            or frozen_lines != expected_lines
            or english_width != expected_width
            or (page_index > 0 and boundary_before.get("classification") == "hard")
        ):
            return None
        if page_index == 0:
            if abs(start_ms / 1000.0 - float(cue.start)) > 0.005:
                return None
        else:
            previous_word_end = float(timing[local_start - 1]["end"])
            next_word_start = float(timing[local_start]["start"])
            if not previous_word_end - 0.005 <= start_ms / 1000.0 <= next_word_start + 0.005:
                return None
        if page_index == len(raw_pages) - 1 and abs(
            end_ms / 1000.0 - float(cue.end)
        ) > 0.005:
            return None
        page_id = str(raw_page.get("display_page_id") or "")
        if page_id != display_page_id(str(cue.subtitle_id or ""), page_index + 1):
            return None
        chinese = (
            re.sub(r"\s+", "", str(page_translations.get(page_id) or ""))
            if len(raw_pages) > 1
            else re.sub(r"\s+", "", str(cue.zh or ""))
        )
        if not chinese or not _article_fixed_chinese_lines(draw, chinese):
            return None
        pages.append(
            {
                "index": page_index,
                "display_page_id": page_id,
                "parent_subtitle_id": str(cue.subtitle_id or ""),
                "en": page_english,
                "zh": chinese,
                "word_start": local_start,
                "word_end": local_end,
                "global_word_start": global_start,
                "global_word_end": global_end,
                "start": start_ms / 1000.0,
                "end": end_ms / 1000.0,
                "en_lines": frozen_lines,
                "english_font_size": page_font_size,
                "en_width": english_width,
                "boundary_before": boundary_before,
                "line_wrap_review": bool(
                    _has_discouraged_caption_break(
                        page_english,
                        frozen_lines,
                        boundary_penalty=lambda split, base=local_start: (
                            _article_line_boundary_penalty(cue, base + split)
                        ),
                    )
                ),
            }
        )
        expected_global_start = global_end + 1
        previous_end_ms = end_ms
    if expected_global_start - 1 != last_word_id:
        return None
    if min(int(page["english_font_size"]) for page in pages) != font_size:
        return None
    if "".join(page["zh"] for page in pages) != re.sub(r"\s+", "", str(cue.zh or "")):
        return None
    return {
        "status": "ok",
        "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
        "font_size": {
            "english": font_size,
            "chinese": ARTICLE_SUBTITLE_ZH_FONT_SIZE,
        },
        "font_fallback": font_fallback,
        "pages": pages,
        "readability_warnings": [],
        "source": "frozen_display_page_artifact",
    }


def apply_article_display_page_translation_artifact(
    cues: Sequence[Cue],
    artifact: Mapping[str, object],
) -> bool:
    """Validate and attach the frozen page plans selected after final timing."""
    for cue in cues:
        cue.display_page_translations = None
        cue.article_page_plan = None
    if (
        int(artifact.get("schema_version") or 0) != DISPLAY_PAGE_SCHEMA_VERSION
        or str(artifact.get("status") or "") != "PASS"
        or str(artifact.get("planner_version") or "") != DISPLAY_PAGE_PLANNER_VERSION
        or dict(artifact.get("layout_profile") or {}) != article_display_page_layout_profile()
    ):
        return False
    frozen_plans = list(artifact.get("render_plans") or [])
    expected_ids = {str(cue.subtitle_id or "") for cue in cues}
    frozen_ids = [
        str(plan.get("parent_subtitle_id") or "")
        for plan in frozen_plans
        if isinstance(plan, Mapping)
    ]
    if len(frozen_ids) != len(set(frozen_ids)) or set(frozen_ids) != expected_ids:
        return False
    returned_parents = list(artifact.get("parents") or [])
    returned_ids = [
        str(parent.get("parent_subtitle_id") or "")
        for parent in returned_parents
        if isinstance(parent, Mapping)
    ]
    if len(returned_ids) != len(set(returned_ids)):
        return False
    cues_by_id = {str(cue.subtitle_id): cue for cue in cues if cue.subtitle_id}
    translations_by_parent: dict[str, dict[str, str]] = {}
    for parent in returned_parents:
        if not isinstance(parent, Mapping):
            return False
        parent_id = str(parent.get("parent_subtitle_id") or "")
        cue = cues_by_id.get(parent_id)
        if cue is None:
            return False
        aggregate = re.sub(r"\s+", "", str(parent.get("aggregate_chinese") or ""))
        if aggregate != re.sub(r"\s+", "", str(cue.zh or "")):
            return False
        returned_pages = list(parent.get("pages") or [])
        if len(returned_pages) < 2:
            return False
        translations: dict[str, str] = {}
        for returned_page in returned_pages:
            if not isinstance(returned_page, Mapping):
                return False
            page_id = str(returned_page.get("display_page_id") or "")
            chinese = re.sub(r"\s+", "", str(returned_page.get("zh") or ""))
            if (
                not page_id
                or not chinese
                or page_id in translations
            ):
                return False
            translations[page_id] = chinese
        if "".join(translations.values()) != aggregate:
            return False
        translations_by_parent[parent_id] = translations
    multipage_plan_ids = {
        str(plan.get("parent_subtitle_id") or "")
        for plan in frozen_plans
        if isinstance(plan, Mapping) and len(list(plan.get("pages") or [])) > 1
    }
    if set(returned_ids) != multipage_plan_ids:
        return False
    draw = ImageDraw.Draw(Image.new("RGB", (ARTICLE_WIDTH, ARTICLE_HEIGHT)))
    frozen_by_id = {
        str(plan.get("parent_subtitle_id") or ""): plan
        for plan in frozen_plans
        if isinstance(plan, Mapping)
    }
    pending_plans: list[tuple[Cue, dict, dict[str, str]]] = []
    for cue in cues:
        parent_id = str(cue.subtitle_id or "")
        translations = translations_by_parent.get(parent_id, {})
        plan = _article_plan_from_frozen_artifact(
            cue,
            frozen_by_id[parent_id],
            translations,
            draw,
        )
        if plan is None:
            return False
        pending_plans.append((cue, plan, translations))
    for cue, plan, translations in pending_plans:
        cue.article_page_plan = plan
        cue.display_page_translations = translations or None
    return True


def load_article_display_page_translation_artifact(
    cues: Sequence[Cue],
    subtitle_path: str | Path,
) -> bool:
    manifest_path = Path(subtitle_path).parent / "stable-final-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(manifest.get("display_page_translation_status") or "") != "PASS":
            return False
        artifact_path = Path(str(manifest.get("display_page_translation_path") or ""))
        if not artifact_path.is_file():
            return False
        expected_sha256 = str(manifest.get("display_page_translation_sha256") or "")
        expected_contract_hash = str(
            manifest.get("display_page_translation_contract_hash") or ""
        )
        if not expected_sha256 or not expected_contract_hash:
            return False
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != expected_sha256:
            return False
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        if str(artifact.get("contract_hash") or "") != expected_contract_hash:
            return False
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Article renderer could not load display page translations: %s", exc)
        return False
    return apply_article_display_page_translation_artifact(cues, artifact)


def _manual_draft_page_boundaries(
    cue: Cue,
    spans: Sequence[tuple[int, int]],
) -> list[float] | None:
    if len(cue.word_timing) != len(str(cue.en or "").split()):
        return None
    boundaries = [float(cue.start)]
    for start, _ in spans[1:]:
        if start <= 0 or start >= len(cue.word_timing):
            return None
        left_end = float(cue.word_timing[start - 1]["end"])
        right_start = float(cue.word_timing[start]["start"])
        boundary = (left_end + right_start) / 2.0
        if boundary <= boundaries[-1] or boundary >= float(cue.end):
            return None
        boundaries.append(boundary)
    boundaries.append(float(cue.end))
    if any(right - left < 0.25 for left, right in zip(boundaries, boundaries[1:])):
        return None
    return boundaries


def build_article_manual_draft_page_plan(
    cue: Cue,
    draw: ImageDraw.ImageDraw,
) -> dict:
    """Build an explicit best-effort page plan without weakening final export."""
    normal = _build_article_english_page_plan(cue, draw)
    if normal.get("status") == "ok":
        english_plan = normal
    else:
        words = str(cue.en or "").split()
        english_plan = {}
        preferred = max(1, min(ARTICLE_VISUAL_PAGE_MAX_PAGES, article_visual_page_count(cue)))
        page_counts = list(range(preferred, ARTICLE_VISUAL_PAGE_MAX_PAGES + 1))
        page_counts.extend(range(1, preferred))
        for page_count in page_counts:
            english_pages = split_article_visual_pages(cue.en, page_count)
            if len(english_pages) != page_count:
                continue
            word_counts = [len(page.split()) for page in english_pages]
            boundaries = [0]
            for count in word_counts:
                boundaries.append(boundaries[-1] + count)
            if boundaries[-1] != len(words):
                continue
            spans = list(zip(boundaries, boundaries[1:]))
            timed_boundaries = _manual_draft_page_boundaries(cue, spans)
            if timed_boundaries is None:
                continue
            for font_size in ARTICLE_SUBTITLE_EN_ALLOWED_SIZES:
                layouts = [
                    _article_fixed_english_lines(
                        draw,
                        page,
                        font_size=font_size,
                        enforce_word_limit=False,
                        boundary_penalty=lambda split, base=start: (
                            _article_line_boundary_penalty(cue, base + split)
                        ),
                        relax_same_screen_syntax=True,
                        intrinsic_penalty=lambda page_words, split, base=start: (
                            _article_same_screen_intrinsic_line_break_penalty(
                                cue,
                                page_words,
                                split,
                                base + split,
                            )
                        ),
                    )
                    for page in english_pages
                ]
                if any(not lines for lines in layouts):
                    continue
                pages = []
                for index, ((start, end), page, lines) in enumerate(
                    zip(spans, english_pages, layouts)
                ):
                    pages.append(
                        {
                            "index": index,
                            "display_page_id": display_page_id(cue.subtitle_id, index + 1),
                            "parent_subtitle_id": str(cue.subtitle_id or ""),
                            "en": page,
                            "word_start": start,
                            "word_end": end - 1,
                            "global_word_start": int(cue.word_timing[start]["word_id"]),
                            "global_word_end": int(cue.word_timing[end - 1]["word_id"]),
                            "start": timed_boundaries[index],
                            "end": timed_boundaries[index + 1],
                            "en_lines": list(lines),
                            "english_font_size": font_size,
                            "boundary_before": {
                                "classification": "review" if index else "allow",
                                "confidence": "high" if index else "low",
                                "issue_codes": (
                                    ["manual_draft_relaxed_boundary"] if index else []
                                ),
                            },
                            "en_width": _article_english_layout_width(
                                draw,
                                lines,
                                font_size,
                            ),
                            "line_wrap_review": False,
                        }
                    )
                english_plan = {
                    "status": "ok",
                    "planner_version": f"{DISPLAY_PAGE_PLANNER_VERSION}-manual-draft",
                    "font_size": {
                        "english": font_size,
                        "chinese": ARTICLE_SUBTITLE_ZH_FONT_SIZE,
                    },
                    "font_fallback": {
                        "used": font_size != ARTICLE_SUBTITLE_EN_FONT_SIZE,
                        "from": ARTICLE_SUBTITLE_EN_FONT_SIZE,
                        "to": font_size,
                        "reason": "manual_draft_relaxed_partition",
                    },
                    "pages": pages,
                    "readability_warnings": [
                        {
                            "reason": "manual_draft_relaxed_partition",
                            "requires_review": True,
                        }
                    ],
                }
                break
            if english_plan:
                break
        if not english_plan:
            return normal

    pages = [dict(page) for page in english_plan.get("pages") or []]
    chinese = re.sub(r"\s+", "", str(cue.zh or ""))
    page_word_counts = [int(page["word_end"]) - int(page["word_start"]) + 1 for page in pages]
    chinese_pages = _strict_split_chinese_visual_pages(
        chinese,
        len(pages),
        page_word_counts,
        strict=True,
    )
    if chinese_pages is None or len(chinese_pages) != len(pages):
        return {
            "status": "render_structural_overflow",
            "errors": [
                {
                    "cue_index": cue.index,
                    "reason": "manual_draft_chinese_no_safe_boundary",
                }
            ],
        }
    if any(not _article_fixed_chinese_lines(draw, page) for page in chinese_pages if page):
        return {
            "status": "render_structural_overflow",
            "errors": [
                {
                    "cue_index": cue.index,
                    "reason": "manual_draft_chinese_does_not_fit_fixed_font",
                }
            ],
        }
    for page, chinese_page in zip(pages, chinese_pages):
        page["zh"] = chinese_page
    english_plan["pages"] = pages
    english_plan["manual_draft_mode"] = True
    return english_plan


def _freeze_article_page_plan(cue: Cue, plan: Mapping[str, object]) -> dict:
    pages = list(plan.get("pages") or [])
    if not pages:
        return {}
    frozen_pages = []
    for index, page in enumerate(pages):
        if not isinstance(page, Mapping):
            return {}
        try:
            frozen_pages.append(
                {
                    "display_page_id": str(page["display_page_id"]),
                    "page_index": index + 1,
                    "word_start": int(page["global_word_start"]),
                    "word_end": int(page["global_word_end"]),
                    "english": str(page["en"]),
                    "chinese": str(page.get("zh") or page.get("chinese") or ""),
                    "start_ms": round(float(page["start"]) * 1000),
                    "end_ms": round(float(page["end"]) * 1000),
                    "english_lines": list(page.get("en_lines") or []),
                    "english_font_size": int(page["english_font_size"]),
                    "english_width": int(page["en_width"]),
                    "boundary_before": dict(page.get("boundary_before") or {}),
                }
            )
        except (KeyError, TypeError, ValueError):
            return {}
    return {
        "parent_subtitle_id": str(cue.subtitle_id or ""),
        "english": str(cue.en or ""),
        "chinese": str(cue.zh or ""),
        "word_start": int(frozen_pages[0]["word_start"]),
        "word_end": int(frozen_pages[-1]["word_end"]),
        "english_font_size": int(plan["font_size"]["english"]),
        "font_fallback": dict(plan.get("font_fallback") or {"used": False}),
        "manual_draft_mode": True,
        "pages": frozen_pages,
    }


def build_article_manual_draft_page_artifact(
    cues: Sequence[Cue],
    frozen_render_plans: Sequence[Mapping[str, object]] | None = None,
    semantic_page_translations: Mapping[str, Mapping[str, object]] | None = None,
) -> dict:
    """Persist a draft map without inventing page-level Chinese boundaries."""
    frozen_by_id: dict[str, Mapping[str, object]] = {}
    for plan in frozen_render_plans or ():
        if not isinstance(plan, Mapping):
            continue
        parent_id = str(plan.get("parent_subtitle_id") or "")
        if not parent_id or parent_id in frozen_by_id:
            raise RenderStructuralOverflowError(
                [{"cue_index": parent_id or "all", "reason": "invalid_frozen_draft_page_plan"}]
            )
        frozen_by_id[parent_id] = plan

    draw = ImageDraw.Draw(Image.new("RGBA", (ARTICLE_WIDTH, ARTICLE_HEIGHT)))
    render_plans: list[dict] = []
    errors: list[dict] = []
    for cue in cues:
        parent_id = str(cue.subtitle_id or "")
        frozen = dict(frozen_by_id.get(parent_id) or {})
        if not frozen:
            planned = build_article_manual_draft_page_plan(cue, draw)
            if planned.get("status") != "ok":
                errors.extend(planned.get("errors") or [])
                continue
            frozen = _freeze_article_page_plan(cue, planned)
        raw_pages = [dict(page) for page in frozen.get("pages") or []]
        if not raw_pages:
            errors.append({"cue_index": cue.index, "reason": "missing_frozen_draft_page_plan"})
            continue
        chinese_pages: list[str] = []
        if len(raw_pages) == 1:
            chinese_pages = [re.sub(r"\s+", "", str(cue.zh or ""))]
        else:
            for page in raw_pages:
                page_id = str(page.get("display_page_id") or "")
                semantic = dict((semantic_page_translations or {}).get(page_id) or {})
                try:
                    identity_matches = bool(
                        page_id
                        and str(semantic.get("parent_subtitle_id") or "") == parent_id
                        and int(semantic.get("word_start", -1)) == int(page["word_start"])
                        and int(semantic.get("word_end", -1)) == int(page["word_end"])
                        and " ".join(str(semantic.get("english") or "").split())
                        == " ".join(str(page.get("english") or "").split())
                    )
                except (KeyError, TypeError, ValueError):
                    identity_matches = False
                chinese = re.sub(r"\s+", "", str(semantic.get("chinese") or ""))
                if not identity_matches or not chinese:
                    chinese_pages = []
                    break
                chinese_pages.append(chinese)
        if (
            len(chinese_pages) != len(raw_pages)
            or "".join(chinese_pages)
            != re.sub(r"\s+", "", str(cue.zh or ""))
        ):
            errors.append(
                {
                    "cue_index": cue.index,
                    "reason": "manual_draft_page_translation_required",
                }
            )
            continue
        if any(
            not chinese or not _article_fixed_chinese_lines(draw, chinese)
            for chinese in chinese_pages
        ):
            errors.append({"cue_index": cue.index, "reason": "manual_draft_chinese_does_not_fit_fixed_font"})
            continue
        translations: dict[str, str] = {}
        for page_index, (page, chinese) in enumerate(zip(raw_pages, chinese_pages), 1):
            page_id = str(page.get("display_page_id") or "")
            page["page_index"] = page_index
            page["chinese"] = chinese
            translations[page_id] = chinese
        frozen["pages"] = raw_pages
        frozen["manual_draft_mode"] = True
        if _article_plan_from_frozen_artifact(cue, frozen, translations, draw) is None:
            errors.append({"cue_index": cue.index, "reason": "invalid_frozen_draft_page_plan"})
            continue
        render_plans.append(frozen)
    if errors:
        raise RenderStructuralOverflowError(errors)
    return {
        "schema_version": MANUAL_DRAFT_PAGE_SCHEMA_VERSION,
        "status": "REVIEW",
        "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
        "layout_profile": article_display_page_layout_profile(),
        "render_plans": render_plans,
    }


def apply_article_manual_draft_page_artifact(
    cues: Sequence[Cue],
    artifact: Mapping[str, object],
) -> bool:
    """Validate and attach the exact page map persisted by the editor save."""
    for cue in cues:
        cue.display_page_translations = None
        cue.article_page_plan = None
    if (
        int(artifact.get("schema_version") or 0) != MANUAL_DRAFT_PAGE_SCHEMA_VERSION
        or str(artifact.get("status") or "") != "REVIEW"
        or str(artifact.get("planner_version") or "") != DISPLAY_PAGE_PLANNER_VERSION
        or dict(artifact.get("layout_profile") or {}) != article_display_page_layout_profile()
    ):
        return False
    frozen_plans = list(artifact.get("render_plans") or [])
    frozen_by_id: dict[str, Mapping[str, object]] = {}
    for plan in frozen_plans:
        if not isinstance(plan, Mapping):
            return False
        parent_id = str(plan.get("parent_subtitle_id") or "")
        if not parent_id or parent_id in frozen_by_id:
            return False
        frozen_by_id[parent_id] = plan
    expected_ids = {str(cue.subtitle_id or "") for cue in cues}
    if not all(expected_ids) or set(frozen_by_id) != expected_ids:
        return False

    draw = ImageDraw.Draw(Image.new("RGB", (ARTICLE_WIDTH, ARTICLE_HEIGHT)))
    pending: list[tuple[Cue, dict, dict[str, str]]] = []
    for cue in cues:
        frozen = frozen_by_id[str(cue.subtitle_id or "")]
        raw_pages = list(frozen.get("pages") or [])
        translations: dict[str, str] = {}
        for page in raw_pages:
            if not isinstance(page, Mapping):
                return False
            page_id = str(page.get("display_page_id") or "")
            chinese = re.sub(r"\s+", "", str(page.get("chinese") or ""))
            if not page_id or not chinese or page_id in translations:
                return False
            translations[page_id] = chinese
        plan = _article_plan_from_frozen_artifact(cue, frozen, translations, draw)
        if plan is None:
            return False
        plan["manual_draft_mode"] = True
        plan["source"] = "frozen_manual_draft_page_artifact"
        pending.append((cue, plan, translations))
    for cue, plan, translations in pending:
        cue.article_page_plan = plan
        cue.display_page_translations = translations
    return True


def load_article_manual_draft_page_artifact(
    cues: Sequence[Cue],
    subtitle_path: str | Path,
) -> bool:
    manifest_path = Path(subtitle_path).parent / "stable-final-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        artifact_path = Path(str(manifest.get("manual_draft_page_plan_path") or ""))
        expected_sha256 = str(manifest.get("manual_draft_page_plan_sha256") or "")
        override = manifest.get("manual_final_override") or {}
        if not isinstance(override, Mapping):
            return False
        override_path = Path(str(override.get("manual_draft_page_plan_path") or ""))
        override_sha256 = str(override.get("manual_draft_page_plan_sha256") or "")
        artifact_dir = Path(str(override.get("artifact_dir") or ""))
        if (
            not artifact_path.is_file()
            or not expected_sha256
            or artifact_path.resolve().parent != artifact_dir.resolve()
            or artifact_path.resolve() != override_path.resolve()
            or expected_sha256 != override_sha256
            or file_sha256(artifact_path) != expected_sha256
        ):
            return False
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return apply_article_manual_draft_page_artifact(cues, artifact)


def prepare_article_visual_page_plans(
    cues: list[Cue],
    subtitle_path: str | Path,
    *,
    allow_manual_draft: bool = False,
) -> None:
    """Prepare every article-template page plan before starting ffmpeg."""
    if not attach_article_word_timing(cues, subtitle_path):
        raise RenderStructuralOverflowError(
            [
                {
                    "cue_index": "all",
                    "reason": "missing_or_mismatched_word_ledger",
                }
            ]
        )
    if not load_article_display_page_translation_artifact(cues, subtitle_path):
        if allow_manual_draft:
            if load_article_manual_draft_page_artifact(cues, subtitle_path):
                return
            raise RenderStructuralOverflowError(
                [
                    {
                        "cue_index": "all",
                        "reason": "missing_or_invalid_manual_draft_page_artifact",
                    }
                ]
            )
        raise RenderStructuralOverflowError(
            [
                {
                    "cue_index": "all",
                    "reason": "missing_or_invalid_display_page_translation_artifact",
                }
            ]
        )
    errors: list[dict] = []
    for cue in cues:
        if not cue.article_page_plan or cue.article_page_plan.get("status") != "ok":
            errors.append(
                {
                    "cue_index": cue.index,
                    "reason": "missing_frozen_display_page_plan",
                }
            )
    if errors:
        raise RenderStructuralOverflowError(errors)


def fit_article_zh_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_lines: int = 2,
) -> ImageFont.FreeTypeFont:
    """Article subtitle typography is fixed; page planning owns overflow."""
    return article_cjk_font(ARTICLE_SUBTITLE_ZH_FONT_SIZE, 700)


def wrap_article_en_subtitle(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap a subtitle visually without changing its frozen cue boundary."""
    lines = wrap_en(draw, text, fnt, max_width)
    if len(lines) <= 2:
        return lines

    words = text.split()
    best_lines: list[str] | None = None
    best_score: int | None = None
    for first_break in range(3, len(words) - 5):
        for second_break in range(first_break + 3, len(words) - 2):
            candidate = [
                " ".join(words[:first_break]),
                " ".join(words[first_break:second_break]),
                " ".join(words[second_break:]),
            ]
            widths = [text_w(draw, line, fnt) for line in candidate]
            if any(width > max_width for width in widths):
                continue
            average_width = sum(widths) / len(widths)
            score = int(sum(abs(width - average_width) for width in widths))
            score += _article_visual_break_penalty(words, first_break)
            score += _article_visual_break_penalty(words, second_break)
            if best_score is None or score < best_score:
                best_lines = candidate
                best_score = score
    return best_lines or lines


def _article_visual_break_penalty(words: list[str], split: int) -> int:
    previous_surface = str(words[split - 1]).strip()
    previous = re.sub(r"[^A-Za-z']", "", previous_surface)
    following = re.sub(r"[^A-Za-z']", "", words[split])
    previous_lower = previous.lower()
    following_lower = following.lower()
    punctuation_boundary = bool(
        re.search(r"[,;:.!?][\"')\]]*$", previous_surface)
    )
    penalty = _caption_line_break_penalty(words, split)
    if following_lower in ARTICLE_AVOID_LINE_START_WORDS:
        penalty += CAPTION_HARD_BREAK_PENALTY
    if previous.endswith("ly") and not punctuation_boundary:
        penalty += 1_200
    if previous[:1].isupper() and following[:1].isupper():
        penalty += 1_600
    return penalty


def fit_article_font_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_size: int,
    min_size: int,
    factory,
) -> ImageFont.FreeTypeFont:
    max_width = acx(max_width)
    for size in range(max_size, min_size - 1, -2):
        fnt = factory(size)
        if text_w(draw, text, fnt) <= max_width:
            return fnt
    return factory(min_size)


def fit_article_wrapped_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_lines: int,
    max_size: int,
    min_size: int,
    factory,
    wrapper,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    max_width = acx(max_width)
    for size in range(max_size, min_size - 1, -2):
        fnt = factory(size)
        lines = wrapper(draw, text, fnt, max_width)
        if len(lines) <= max_lines and all(text_w(draw, line, fnt) <= max_width for line in lines):
            return fnt, lines
    fnt = factory(min_size)
    return fnt, wrapper(draw, text, fnt, max_width)[:max_lines]


def wrap_article_mixed_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*|\s+|.", text.strip())
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = current + token
        if token in "，。！？；：、" and current:
            current = candidate
            continue
        if current and text_w(draw, candidate, fnt) > max_width:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current = candidate
    if current.strip():
        lines.append(current.rstrip())
    return rebalance_article_mixed_lines(draw, lines, fnt, max_width) or [""]


def _article_title_break_offsets(text: str) -> list[int]:
    """Return lexical and punctuation break opportunities for one title line."""
    offsets = {0, len(text)}
    token_boundaries = chinese_token_boundaries(text)
    if isinstance(token_boundaries, dict):
        offsets.update(int(offset) for offset in token_boundaries)
    for match in re.finditer(r"\s+|[，。！？；：、,.!?;:]+", text):
        offsets.add(match.end())

    closing = frozenset("，。！？；：、,.!?;:)]}】》〉」』")
    opening = frozenset("([{【《〈「『")
    safe = []
    for offset in sorted(offsets):
        if offset in {0, len(text)}:
            safe.append(offset)
            continue
        before = text[:offset].rstrip()
        after = text[offset:].lstrip()
        if not before or not after:
            continue
        if after[0] in closing or before[-1] in opening:
            continue
        if before[-1].isascii() and after[0].isascii() and (
            before[-1].isalnum() or after[0].isalnum()
        ):
            continue
        safe.append(offset)
    return safe


def _wrap_article_title_paragraph(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap one title paragraph at lexical boundaries and balance its lines."""
    paragraph = text.strip()
    if not paragraph or text_w(draw, paragraph, fnt) <= max_width:
        return [paragraph]

    offsets = _article_title_break_offsets(paragraph)
    if len(offsets) <= 2:
        return wrap_article_mixed_text(draw, paragraph, fnt, max_width)

    segments: dict[tuple[int, int], tuple[str, int]] = {}
    for start_index, start in enumerate(offsets[:-1]):
        for end in offsets[start_index + 1 :]:
            line = paragraph[start:end].strip()
            if not line:
                continue
            width = text_w(draw, line, fnt)
            if width <= max_width:
                segments[(start, end)] = (line, width)

    reachable = {0}
    line_count = 0
    while reachable and len(paragraph) not in reachable:
        line_count += 1
        reachable = {
            end
            for start in reachable
            for end in offsets
            if end > start and (start, end) in segments
        }
    if len(paragraph) not in reachable or line_count <= 0:
        return wrap_article_mixed_text(draw, paragraph, fnt, max_width)

    total_width = sum(
        text_w(draw, paragraph[start:end].strip(), fnt)
        for start, end in zip(offsets, offsets[1:])
    )
    target_width = total_width / line_count
    states: dict[int, tuple[float, list[str]]] = {0: (0.0, [])}
    for _ in range(line_count):
        next_states: dict[int, tuple[float, list[str]]] = {}
        for start, (cost, lines) in states.items():
            for end in offsets:
                segment = segments.get((start, end))
                if segment is None:
                    continue
                line, width = segment
                candidate = (cost + (width - target_width) ** 2, [*lines, line])
                previous = next_states.get(end)
                if previous is None or candidate[0] < previous[0]:
                    next_states[end] = candidate
        states = next_states
    selected = states.get(len(paragraph))
    return selected[1] if selected is not None else wrap_article_mixed_text(
        draw, paragraph, fnt, max_width
    )


def wrap_article_title_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap a title without splitting lexical words; explicit newlines are fixed."""
    paragraphs = [part.strip() for part in re.split(r"\r?\n", str(text).strip())]
    lines: list[str] = []
    for paragraph in paragraphs:
        if paragraph:
            lines.extend(_wrap_article_title_paragraph(draw, paragraph, fnt, max_width))
    return lines or [""]


def _article_concept_semantic_break_offsets(
    text: str,
    safe_offsets: Sequence[int],
) -> set[int]:
    """Find the boundary between a short explanatory lead-in and its content."""
    if not text.startswith(ARTICLE_CONCEPT_LEAD_IN_SUBJECTS):
        return set()

    safe = set(safe_offsets)
    offsets: set[int] = set()
    for predicate in ARTICLE_CONCEPT_LEAD_IN_PREDICATES:
        search_from = 0
        while True:
            start = text.find(predicate, search_from)
            if start < 0:
                break
            end = start + len(predicate)
            before_cjk = len(re.findall(r"[\u4e00-\u9fff]", text[:end]))
            after_cjk = len(re.findall(r"[\u4e00-\u9fff]", text[end:]))
            if (
                end in safe
                and ARTICLE_CONCEPT_LEAD_IN_MIN_CJK
                <= before_cjk
                <= ARTICLE_CONCEPT_LEAD_IN_MAX_CJK
                and after_cjk >= 4
            ):
                offsets.add(end)
            search_from = end
    return offsets


def wrap_article_concept_detail(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap a concept note into at most two lexical, meaning-led lines."""
    paragraph = str(text).strip()
    if not paragraph or text_w(draw, paragraph, fnt) <= max_width:
        return [paragraph]

    safe_offsets = _article_title_break_offsets(paragraph)
    semantic_offsets = _article_concept_semantic_break_offsets(
        paragraph,
        safe_offsets,
    )
    candidates: list[tuple[tuple[int, int, int], list[str]]] = []
    for offset in safe_offsets:
        if offset in {0, len(paragraph)}:
            continue
        before = paragraph[:offset].rstrip()
        after = paragraph[offset:].lstrip()
        if (
            not before
            or not after
            or after[0] in ARTICLE_MIXED_AVOID_LINE_START
            or after[0] in "，。！？；：、,.!?;:)]}】》〉」』"
        ):
            continue
        before_width = text_w(draw, before, fnt)
        after_width = text_w(draw, after, fnt)
        if before_width > max_width or after_width > max_width:
            continue
        before_cjk = len(re.findall(r"[\u4e00-\u9fff]", before))
        after_cjk = len(re.findall(r"[\u4e00-\u9fff]", after))
        if min(before_cjk, after_cjk) < 4:
            continue

        score = (
            0 if offset in semantic_offsets else 1,
            0 if after_width >= before_width else 1,
            abs(after_width - before_width),
        )
        candidates.append((score, [before, after]))

    if candidates:
        return min(candidates, key=lambda candidate: candidate[0])[1]
    return wrap_article_mixed_text(draw, paragraph, fnt, max_width)[:2]


def rebalance_article_mixed_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Avoid a one- or two-character Chinese tail line in contextual notes."""
    if len(lines) != 2:
        return lines
    cjk_counts = [len(re.findall(r"[\u4e00-\u9fff]", line)) for line in lines]
    if min(cjk_counts) > 3:
        return lines

    text = "".join(lines)
    tokens = re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*|\s+|.", text)
    total_cjk = sum(cjk_counts)
    best_lines: list[str] | None = None
    best_score: int | None = None
    for split in range(1, len(tokens)):
        before = "".join(tokens[:split]).rstrip()
        after = "".join(tokens[split:]).lstrip()
        if not before or not after or after[0] in "，。！？；：、":
            continue
        before_width = text_w(draw, before, fnt)
        after_width = text_w(draw, after, fnt)
        if before_width > max_width or after_width > max_width:
            continue
        before_cjk = len(re.findall(r"[\u4e00-\u9fff]", before))
        after_cjk = len(re.findall(r"[\u4e00-\u9fff]", after))
        if total_cjk >= 8 and min(before_cjk, after_cjk) < 4:
            continue

        score = abs(before_width - after_width)
        if before[-1] in ARTICLE_MIXED_PREFERRED_BREAK_AFTER:
            score -= 260
        if after[0] in ARTICLE_MIXED_AVOID_LINE_START:
            score += 900
        if best_score is None or score < best_score:
            best_lines = [before, after]
            best_score = score
    return best_lines or lines


def article_tip_mixed_tokens(text: str) -> list[str]:
    """Keep English words and affixes intact inside a Chinese learning tip."""
    return re.findall(r"-[A-Za-z][A-Za-z-]*|[A-Za-z0-9]+(?:['/-][A-Za-z0-9]+)*|\s+|.", text.strip())


def article_tip_mixed_font(token: str, size: int) -> ImageFont.FreeTypeFont:
    if re.search(r"[A-Za-z0-9]", token):
        return article_en_font(size, 400)
    return article_cjk_font(size, 400)


def article_tip_mixed_width(draw: ImageDraw.ImageDraw, tokens: list[str], size: int) -> int:
    return sum(text_w(draw, token, article_tip_mixed_font(token, size)) for token in tokens)


def wrap_article_tip_mixed_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    size: int,
    max_width: int,
) -> list[list[str]]:
    tokens = article_tip_mixed_tokens(text)
    lines: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        candidate = [*current, token]
        if current and article_tip_mixed_width(draw, candidate, size) > max_width:
            lines.append(current)
            current = [token.lstrip()]
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [[]]


def fit_article_tip_mixed_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_lines: int = 2,
) -> tuple[int, list[list[str]]]:
    width_px = acx(max_width)
    for size in range(22, 15, -2):
        lines = wrap_article_tip_mixed_text(draw, text, size, width_px)
        if len(lines) <= max_lines:
            return size, lines
    return 16, wrap_article_tip_mixed_text(draw, text, 16, width_px)[:max_lines]


def draw_article_tip_mixed_line(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    tokens: list[str],
    size: int,
    fill: tuple[int, int, int, int],
) -> None:
    if not tokens:
        return
    fonts = [article_tip_mixed_font(token, size) for token in tokens]
    baseline = y + max((text_h(draw, token, fnt) for token, fnt in zip(tokens, fonts)), default=0)
    cursor = x
    for token, fnt in zip(tokens, fonts):
        draw_stroked_text(draw, (cursor, baseline), token, fnt, fill, anchor="ls", stroke_width=0)
        cursor += text_w(draw, token, fnt)


def draw_article_panel(
    img: Image.Image,
    rect: tuple[int, int, int, int],
    radius: int,
    fill_color: tuple[int, int, int, int],
    stroke_color=(230, 222, 208, 255),
) -> None:
    x0, y0, x1, y1 = rect
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.rounded_rectangle((x0, y0 + acy(4), x1, y1 + acy(4)), radius=radius, fill=(0, 0, 0, 13))
    shadow = shadow.filter(ImageFilter.GaussianBlur(acx(16)))
    img.alpha_composite(shadow)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(rect, radius=radius, fill=fill_color, outline=stroke_color, width=1)


def draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: tuple[int, int, int, int],
    width: int = 1,
    dash: int = 9,
    gap: int = 8,
) -> None:
    x0, y0 = start
    x1, y1 = end
    width = acx(width)
    dash = acx(dash)
    gap = acx(gap)
    if y0 != y1:
        draw.line((x0, y0, x1, y1), fill=fill, width=width)
        return
    x = x0
    while x < x1:
        draw.line((x, y0, min(x + dash, x1), y1), fill=fill, width=width)
        x += dash + gap


def paste_rounded(img: Image.Image, src: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    x0, y0, x1, y1 = box
    src = src.convert("RGBA").resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    mask = Image.new("L", src.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, src.size[0] - 1, src.size[1] - 1), radius=radius, fill=255)
    img.paste(src, (x0, y0), mask)


def draw_economist_logo(img: Image.Image, position: tuple[int, int] = (31, 33)) -> None:
    x, y = position
    if ARTICLE_LOGO.exists():
        try:
            logo = Image.open(ARTICLE_LOGO).convert("RGBA").resize((acx(100), acy(50)), Image.Resampling.LANCZOS)
            img.alpha_composite(logo, (x, y))
            return
        except Exception:
            pass
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((x, y, x + acx(100), y + acy(50)), fill=(229, 0, 0, 255))
    logo_font = article_mixed_font(18)
    draw_stroked_text(d, (x + acx(50), y + acy(25)), "The\nEconomist", logo_font, (255, 255, 255, 255), anchor="mm", stroke_width=0)


def decorate_article_cover(article_image: Image.Image, _date_text: str) -> Image.Image:
    cover = article_image.convert("RGBA").copy()
    draw_economist_logo(cover, (0, 0))
    return cover


def _draw_article_vocab_card_legacy(img: Image.Image, item: dict | None, rect: tuple[int, int, int, int]) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    word = str(item.get("word") or "").strip().capitalize()
    phonetic = str(item.get("phonetic") or "").strip()
    pos = str(item.get("pos") or "词性").strip()
    meaning = str(item.get("meaning") or "").strip()
    definition = str(item.get("definition") or "").strip()
    tip_zh = str(item.get("tip_zh") or "结合当前意群理解这个词的作用。").strip()

    content_left = 940
    content_right = 1560
    word_font = fit_article_font_to_width(
        d, word, 340, 68, 44, lambda size: article_en_font(size, 700)
    )
    word_x = acx(content_left)
    phonetic_path = FONT_CAMBRIA if FONT_CAMBRIA.exists() else FONT_SEGOE
    word_right = word_x + text_w(d, word, word_font)
    inline_phonetic_width_px = acx(content_right) - word_right - acx(20)
    inline_phonetic = inline_phonetic_width_px >= acx(150)
    phonetic_x = word_right + acx(20) if inline_phonetic else acx(content_left)
    phonetic_width = (
        max(150, round(inline_phonetic_width_px / ARTICLE_SCALE_X) - 16)
        if inline_phonetic
        else 620
    )
    phonetic_font = fit_article_font_to_width(
        d,
        phonetic,
        phonetic_width,
        32,
        22,
        lambda size: font(phonetic_path if phonetic_path.exists() else FONT_GANTARI, size, 400),
    )
    meaning_font, meaning_lines = fit_article_wrapped_font(
        d,
        meaning,
        520,
        2,
        34,
        26,
        lambda size: article_cjk_font(size, 400),
        wrap_zh,
    )
    pos_font_factory = (
        (lambda size: article_cjk_font(size, 600))
        if re.search(r"[\u4e00-\u9fff]", pos)
        else (lambda size: article_en_font(size, 600))
    )
    pos_font = fit_article_font_to_width(
        d,
        pos[:10],
        62,
        18,
        13,
        pos_font_factory,
    )
    def_font, definition_lines = fit_article_wrapped_font(
        d,
        definition,
        620,
        2,
        26,
        20,
        lambda size: article_en_font(size, 400),
        wrap_en,
    )
    tip_label_font = article_en_font(24, 700)
    tip_zh_size, tip_zh_lines = fit_article_tip_mixed_lines(
        d,
        tip_zh,
        524,
    )
    word_row_offset = round(10 / ARTICLE_SCALE_Y)

    if inline_phonetic:
        draw_stroked_text(d, (word_x, acy(86 + word_row_offset)), word, word_font, (47, 111, 237, 255), anchor="ls", stroke_width=0)
        draw_stroked_text(d, (phonetic_x, acy(86 + word_row_offset)), phonetic, phonetic_font, (122, 132, 147, 255), anchor="ls", stroke_width=0)
        divider_y = 138
        metadata_top = 156
        definition_y = 222
        tip_top = 360
    else:
        draw_stroked_text(d, (word_x, acy(28 + word_row_offset)), word, word_font, (47, 111, 237, 255), stroke_width=0)
        draw_stroked_text(d, (acx(content_left), acy(104 + word_row_offset)), phonetic, phonetic_font, (122, 132, 147, 255), stroke_width=0)
        divider_y = 160
        metadata_top = 178
        definition_y = 244
        tip_top = 366
    draw_dashed_line(d, (acx(content_left), acy(divider_y)), (acx(content_right), acy(divider_y)), fill=(122, 132, 147, 150), width=1)

    pos_width = max(
        acx(44),
        min(acx(72), text_w(d, pos[:10], pos_font) + acx(18)),
    )
    pos_rect = (
        acx(content_left),
        acy(metadata_top),
        acx(content_left) + pos_width,
        acy(metadata_top + 32),
    )
    d.rounded_rectangle(pos_rect, radius=acx(4), fill=(234, 241, 255, 255))
    draw_stroked_text(
        d,
        ((pos_rect[0] + pos_rect[2]) // 2, (pos_rect[1] + pos_rect[3]) // 2),
        pos[:10],
        pos_font,
        (47, 111, 237, 255),
        anchor="mm",
        stroke_width=0,
    )
    meaning_gap = int(meaning_font.size * 1.18)
    meaning_center_y = (pos_rect[1] + pos_rect[3]) // 2
    meaning_start_y = meaning_center_y - (len(meaning_lines[:2]) - 1) * meaning_gap // 2
    meaning_x = pos_rect[2] + acx(14)
    for idx, line in enumerate(meaning_lines[:2]):
        draw_stroked_text(d, (meaning_x, meaning_start_y + idx * meaning_gap), line, meaning_font, (79, 91, 107, 255), anchor="lm", stroke_width=0)

    for idx, line in enumerate(definition_lines[:2]):
        draw_stroked_text(d, (acx(content_left), acy(definition_y + idx * 32)), line, def_font, (122, 132, 147, 255), stroke_width=0)

    # Align this card's baseline with the cover's inner bottom edge.
    tip_rect = article_rect(content_left, tip_top, content_right, 513)
    d.rounded_rectangle(tip_rect, radius=acx(8), fill=(234, 241, 255, 255))
    icon_y = tip_top + 18
    tip_label_y = tip_top + 18
    tip_zh_y = tip_top + 70
    if ARTICLE_TIP_ICON.exists():
        try:
            icon = Image.open(ARTICLE_TIP_ICON).convert("RGBA").resize((acx(48), acy(48)), Image.Resampling.LANCZOS)
            img.alpha_composite(icon, (acx(956), acy(icon_y)))
        except Exception:
            d.ellipse(article_rect(956, icon_y, 1004, icon_y + 48), fill=(47, 111, 237, 255))
            bulb_font = article_en_font(28, 700)
            draw_stroked_text(d, (acx(980), acy(icon_y + 25)), "!", bulb_font, (255, 255, 255, 255), anchor="mm", stroke_width=0)
    else:
        d.ellipse(article_rect(956, icon_y, 1004, icon_y + 48), fill=(47, 111, 237, 255))
        bulb_font = article_en_font(28, 700)
        draw_stroked_text(d, (acx(980), acy(icon_y + 25)), "!", bulb_font, (255, 255, 255, 255), anchor="mm", stroke_width=0)
    draw_stroked_text(d, (acx(1020), acy(tip_label_y)), "IN CONTEXT", tip_label_font, (47, 111, 237, 255), stroke_width=0)
    for index, line in enumerate(tip_zh_lines):
        draw_article_tip_mixed_line(
            d,
            acx(1020),
            acy(tip_zh_y + index * 25),
            line,
            tip_zh_size,
            (79, 91, 107, 255),
        )


def draw_article_vocab_card(img: Image.Image, item: dict | None, rect: tuple[int, int, int, int]) -> None:
    """Render one calm expression card; concepts alone receive a third line."""
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    d = ImageDraw.Draw(img, "RGBA")
    phrase = str(item.get("word") or "").strip()
    meaning = str(item.get("meaning") or "").strip()
    detail = str(item.get("detail") or "").strip()
    is_concept = vocab_card_type(item) == "concept" and bool(detail)

    phrase_font = fit_article_font_to_width(
        d,
        phrase,
        540,
        58,
        20,
        lambda size: article_en_font(size, 700),
    )
    phrase_lines = [phrase]
    meaning_font, meaning_lines = fit_article_wrapped_font(
        d,
        meaning,
        500,
        2,
        34,
        24,
        lambda size: article_cjk_font(size, 400),
        wrap_article_mixed_text,
    )
    detail_lines: list[str] = []
    detail_font = None
    if is_concept:
        detail_font, detail_lines = fit_article_wrapped_font(
            d,
            detail,
            500,
            2,
            26,
            20,
            lambda size: article_cjk_font(size, 400),
            wrap_article_concept_detail,
        )
    elif detail:
        detail_font, detail_lines = fit_article_wrapped_font(
            d,
            detail,
            500,
            1,
            24,
            18,
            lambda size: article_en_font(size, 500),
            wrap_en,
        )

    phrase_gap = int(phrase_font.size * 1.18)
    meaning_gap = int(meaning_font.size * 1.28)
    detail_gap = int(detail_font.size * 1.3) if detail_font else 0
    group_gap = acy(24)
    block_height = len(phrase_lines) * phrase_gap + group_gap + len(meaning_lines) * meaning_gap
    if detail_lines:
        block_height += group_gap + len(detail_lines) * detail_gap
    x0, y0, x1, y1 = rect
    cursor_y = (y0 + y1 - block_height) // 2
    center_x = (x0 + x1) // 2

    for line in phrase_lines:
        draw_stroked_text(
            d,
            (center_x, cursor_y),
            line,
            phrase_font,
            ARTICLE_BLUE,
            anchor="ma",
            stroke_width=0,
        )
        cursor_y += phrase_gap
    cursor_y += group_gap
    for line in meaning_lines:
        draw_stroked_text(
            d,
            (center_x, cursor_y),
            line,
            meaning_font,
            (79, 91, 107, 255),
            anchor="ma",
            stroke_width=0,
        )
        cursor_y += meaning_gap
    if detail_lines and detail_font:
        cursor_y += group_gap
        for line in detail_lines:
            draw_stroked_text(
                d,
                (center_x, cursor_y),
                line,
                detail_font,
                (122, 132, 147, 255),
                anchor="ma",
                stroke_width=0,
            )
            cursor_y += detail_gap


def _draw_article_vocab_review_bar_legacy(
    img: Image.Image,
    item: dict,
    rect: tuple[int, int, int, int],
) -> None:
    """Keep the article card container while reducing it to a review line."""
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, _ = rect
    word = str(item.get("word") or "").strip().capitalize()
    pos = str(item.get("pos") or "").strip()
    meaning = str(item.get("meaning") or "").strip()
    word_font = fit_article_font_to_width(d, word, 190, 32, 22, lambda size: article_en_font(size, 700))
    pos_font = article_en_font(16, 600)
    word_width = text_w(d, word, word_font)
    pos_width = text_w(d, pos, pos_font) if pos else 0
    max_meaning_width = max(
        140,
        round((acx(500) - word_width - pos_width - acx(72)) / ARTICLE_SCALE_X),
    )
    meaning_font = fit_article_font_to_width(
        d,
        meaning,
        max_meaning_width,
        24,
        17,
        lambda size: article_cjk_font(size, 400),
    )
    meaning_width = text_w(d, meaning, meaning_font)
    content_width = word_width + pos_width + meaning_width + acx(72)
    content_x = (x0 + x1 - content_width) // 2
    center_y = y0 + acy(265)
    accent_x = content_x
    d.ellipse((accent_x, center_y - acx(6), accent_x + acx(12), center_y + acx(6)), fill=ARTICLE_BLUE)
    word_x = accent_x + acx(24)
    draw_stroked_text(d, (word_x, center_y), word, word_font, ARTICLE_BLUE, anchor="lm", stroke_width=0)
    pos_x = word_x + word_width + acx(10)
    if pos:
        draw_stroked_text(d, (pos_x, center_y), pos, pos_font, (122, 132, 147, 255), anchor="lm", stroke_width=0)
    divider_x = pos_x + pos_width + acx(16)
    d.line((divider_x, center_y - acy(18), divider_x, center_y + acy(18)), fill=(202, 215, 237, 255), width=1)
    draw_stroked_text(d, (divider_x + acx(16), center_y), meaning, meaning_font, (79, 91, 107, 255), anchor="lm", stroke_width=0)


def draw_article_vocab_review_bar(
    img: Image.Image,
    item: dict,
    rect: tuple[int, int, int, int],
) -> None:
    """Keep the card container but leave only the expression and its gloss."""
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    d = ImageDraw.Draw(img, "RGBA")
    phrase = str(item.get("word") or "").strip()
    meaning = str(item.get("meaning") or "").strip()
    phrase_font = fit_article_font_to_width(
        d,
        phrase,
        500,
        34,
        16,
        lambda size: article_en_font(size, 700),
    )
    phrase_lines = [phrase]
    meaning_font = fit_article_font_to_width(
        d,
        meaning,
        440,
        26,
        18,
        lambda size: article_cjk_font(size, 400),
    )
    phrase_gap = int(phrase_font.size * 1.15)
    total_height = len(phrase_lines) * phrase_gap + acy(26) + meaning_font.size
    x0, y0, x1, y1 = rect
    cursor_y = (y0 + y1 - total_height) // 2
    center_x = (x0 + x1) // 2
    for line in phrase_lines:
        draw_stroked_text(
            d,
            (center_x, cursor_y),
            line,
            phrase_font,
            ARTICLE_BLUE,
            anchor="ma",
            stroke_width=0,
        )
        cursor_y += phrase_gap
    cursor_y += acy(26)
    draw_stroked_text(
        d,
        (center_x, cursor_y),
        meaning,
        meaning_font,
        (79, 91, 107, 255),
        anchor="ma",
        stroke_width=0,
    )


def draw_article_vocab_placeholder(img: Image.Image, rect: tuple[int, int, int, int]) -> None:
    """Render a deliberate opening state before the first study word arrives."""
    d = ImageDraw.Draw(img, "RGBA")
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    content_left = 940
    content_right = 1560
    title_font = article_en_font(60, 700)
    body_font = article_cjk_font(30, 400)
    tip_label_font = article_en_font(28, 700)
    tip_body_font = article_tip_font(24)

    draw_stroked_text(
        d,
        (acx(content_left), acy(58)),
        "Vocabulary",
        title_font,
        ARTICLE_BLUE,
        stroke_width=0,
    )
    draw_dashed_line(
        d,
        (acx(content_left), acy(138)),
        (acx(content_right), acy(138)),
        fill=(122, 132, 147, 150),
        width=1,
    )
    draw_stroked_text(
        d,
        (acx(content_left), acy(202)),
        "重点词会随当前意群出现",
        body_font,
        (79, 91, 107, 255),
        stroke_width=0,
    )

    tip_rect = article_rect(content_left, 326, content_right, 506)
    d.rounded_rectangle(tip_rect, radius=acx(8), fill=(234, 241, 255, 255))
    if ARTICLE_TIP_ICON.exists():
        try:
            icon = Image.open(ARTICLE_TIP_ICON).convert("RGBA").resize((acx(48), acy(48)), Image.Resampling.LANCZOS)
            img.alpha_composite(icon, (acx(956), acy(345)))
        except Exception:
            d.ellipse(article_rect(956, 345, 1004, 393), fill=ARTICLE_BLUE)
    else:
        d.ellipse(article_rect(956, 345, 1004, 393), fill=ARTICLE_BLUE)
    draw_stroked_text(d, (acx(1020), acy(345)), "IN CONTEXT", tip_label_font, ARTICLE_BLUE, stroke_width=0)
    draw_stroked_text(
        d,
        (acx(1020), acy(390)),
        "词卡会补充它在当前语境中的具体意思。",
        tip_body_font,
        (122, 132, 147, 255),
        stroke_width=0,
    )


def draw_article_opening_topic_panel(
    img: Image.Image,
    rect: tuple[int, int, int, int],
    title_text: str,
) -> None:
    """Fill the opening card area with the episode topic, not a word preview."""
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    d = ImageDraw.Draw(img, "RGBA")
    title = str(title_text or "").strip() or TITLE_TEXT
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", title))
    title_font, title_lines = fit_article_wrapped_font(
        d,
        title,
        500,
        3,
        52,
        24,
        (lambda size: article_cjk_font(size, 800)) if has_cjk else (lambda size: article_en_font(size, 700)),
        wrap_article_title_text,
    )
    line_gap = int(title_font.size * 1.25)
    block_height = max(line_gap, len(title_lines) * line_gap)
    x0, y0, x1, y1 = rect
    title_x = x0 + acx(92)
    first_y = (y0 + y1 - block_height) // 2
    title_bounds = [
        d.textbbox((title_x, first_y + index * line_gap), line, font=title_font)
        for index, line in enumerate(title_lines)
    ]
    accent_y0 = min(bounds[1] for bounds in title_bounds)
    accent_y1 = max(bounds[3] for bounds in title_bounds)
    d.rounded_rectangle(
        (x0 + acx(48), accent_y0, x0 + acx(56), accent_y1),
        radius=acx(4),
        fill=ARTICLE_BLUE,
    )
    for index, line in enumerate(title_lines):
        draw_stroked_text(
            d,
            (title_x, first_y + index * line_gap),
            line,
            title_font,
            (42, 63, 93, 255),
            stroke_width=0,
        )


def draw_article_vocab_overview(
    img: Image.Image,
    vocab_plan: dict[int, dict],
    rect: tuple[int, int, int, int],
) -> None:
    """Render the Figma overview card on its native 1080 x 900 coordinate grid."""
    design_width, design_height = 1080, 900
    # Keep the outside of the rounded card transparent.  An opaque rectangular
    # backing here would cover the panel's corners after the final resize.
    card = Image.new("RGBA", (design_width, design_height), (0, 0, 0, 0))
    d = ImageDraw.Draw(card, "RGBA")
    d.rounded_rectangle(
        (0, 0, design_width - 1, design_height - 1),
        radius=28,
        fill=ARTICLE_CARD_CONTAINER,
        outline=(222, 215, 202, 255),
        width=1,
    )
    title_font = article_en_font(82, 700)
    title_x = 50
    draw_stroked_text(d, (title_x, 48), "Key Vocabulary", title_font, ARTICLE_BLUE, stroke_width=0)
    for dash_x in range(title_x, 1030, 24):
        d.line((dash_x, 184, min(dash_x + 12, 1030), 184), fill=(122, 132, 147, 150), width=2)

    upcoming = episode_vocab_overview_items(vocab_plan)
    row_y = (320, 480, 640)
    def overview_gloss(item: dict) -> str:
        """Keep the opener as an index: one contextual Chinese gloss per word."""
        raw = str(item.get("meaning") or "").strip()
        # Detailed cards retain every sense and explanatory parenthetical.
        # The opener only needs the core gloss; otherwise one verbose entry
        # pulls the whole two-column grid too far toward the English column.
        raw = re.sub(r"[（(][^（）()]*[）)]", "", raw).strip()
        primary = re.split(r"[／/；;，,、]", raw, maxsplit=1)[0].strip()
        return primary or raw

    meanings = [overview_gloss(item) for item in upcoming]
    # The overview is a compact index, not three independently responsive
    # cards.  Give all translations one shared type scale for a calmer grid.
    meaning_font = fit_article_font_to_width(
        d,
        max(meanings, key=lambda value: text_w(d, value, article_cjk_font(54, 400)), default=""),
        330,
        46,
        30,
        lambda size: article_cjk_font(size, 400),
    )
    # Use the widest gloss to place a single left-aligned Chinese column. This
    # keeps all rows aligned while letting the longest item reach the right edge.
    meaning_right = 1030
    widest_meaning = max((text_w(d, meaning, meaning_font) for meaning in meanings), default=0)
    meaning_x = meaning_right - widest_meaning
    word_x = 116
    word_to_meaning_gap = 32
    for index, item in enumerate(upcoming):
        word = str(item.get("word") or "").strip().capitalize()
        meaning = meanings[index]
        # This is deliberately based on rendered pixel width rather than the
        # generic design-width helper: the overview card is drawn at a native
        # intermediate size before its final resize.
        word_available_width = max(1, meaning_x - word_x - word_to_meaning_gap)
        word_font = article_en_font(20, 700)
        for size in range(68, 19, -2):
            candidate_font = article_en_font(size, 700)
            if text_w(d, word, candidate_font) <= word_available_width:
                word_font = candidate_font
                break
        center_y = row_y[index]
        d.ellipse((58, center_y - 16, 90, center_y + 16), fill=ARTICLE_BLUE)
        d.ellipse((69, center_y - 5, 79, center_y + 5), fill=(255, 253, 248, 255))
        # Center the visible glyph bounds, not the font box. The English and
        # Chinese fonts have different ascender/descent metrics.
        word_box = d.textbbox((0, 0), word, font=word_font)
        meaning_box = d.textbbox((0, 0), meaning, font=meaning_font)
        word_y = center_y - ((word_box[1] + word_box[3]) // 2)
        meaning_y = center_y - ((meaning_box[1] + meaning_box[3]) // 2)
        draw_stroked_text(d, (word_x, word_y), word, word_font, (42, 63, 93, 255), stroke_width=0)
        draw_stroked_text(d, (meaning_x, meaning_y), meaning, meaning_font, (79, 91, 107, 255), stroke_width=0)

    for index in range(6):
        dot_x = 126 + index * 46
        d.ellipse((dot_x - 9, 796 - 9, dot_x + 9, 796 + 9), fill=(196, 211, 235, 255))

    x0, y0, x1, y1 = rect
    rendered = card.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    img.alpha_composite(rendered, (x0, y0))


def draw_article_frame(
    article_image: Image.Image,
    cue: Cue | None,
    vocab_plan: dict[int, dict] | None = None,
    subtitle_alpha: int = 255,
    show_vocab: bool = False,
    title_text: str = TITLE_TEXT,
    date_text: str = "Jul 23rd 2026",
    display_time: float | None = None,
    english_only: bool = False,
) -> Image.Image:
    img = Image.new("RGBA", (ARTICLE_WIDTH, ARTICLE_HEIGHT), (247, 243, 234, 255))
    d = ImageDraw.Draw(img, "RGBA")

    draw_article_panel(img, article_rect(16, 16, 900, 530), acx(16), ARTICLE_CARD_CONTAINER)
    cover = decorate_article_cover(article_image, date_text)
    paste_rounded(img, cover, article_rect(31, 33, 885, 513), acx(8))

    vocab_rect = article_rect(916, 16, 1584, 530)
    vocab, vocab_state = vocab_card_display_state(vocab_plan, cue, display_time) if show_vocab else (None, "hidden")
    transition_progress = opening_card_transition_progress(
        vocab_plan,
        vocab,
        vocab_state,
        display_time,
    )
    if transition_progress is not None:
        topic_frame = img.copy()
        empty_frame = img.copy()
        card_frame = img.copy()
        draw_article_opening_topic_panel(topic_frame, vocab_rect, title_text)
        draw_article_panel(empty_frame, vocab_rect, acx(16), ARTICLE_CARD_CONTAINER)
        draw_article_vocab_card(card_frame, vocab, vocab_rect)
        if transition_progress < 0.45:
            img = Image.blend(topic_frame, empty_frame, transition_progress / 0.45)
        else:
            img = Image.blend(empty_frame, card_frame, (transition_progress - 0.45) / 0.55)
        d = ImageDraw.Draw(img, "RGBA")
    elif vocab_state == "full" and vocab:
        draw_article_vocab_card(img, vocab, vocab_rect)
    else:
        draw_article_opening_topic_panel(img, vocab_rect, title_text)

    draw_article_panel(img, article_rect(16, 546, 1584, 884), acx(16), (241, 236, 227, 255))

    if cue:
        if cue.article_page_plan is None:
            cue.article_page_plan = build_article_visual_page_plan(cue, d)
        if cue.article_page_plan.get("status") != "ok":
            raise RenderStructuralOverflowError(cue.article_page_plan.get("errors") or [])
        key = vocab["key"] if vocab else None
        page = _article_visual_page(cue, display_time)
        visual_en, visual_zh = article_visual_page_text(cue, display_time)
        en_width = int(page.get("en_width", ARTICLE_SUBTITLE_EN_WIDTH)) if page else ARTICLE_SUBTITLE_EN_WIDTH
        en_x = (1600 - en_width) // 2
        en_font = fit_article_en_font(
            d,
            visual_en,
            en_width,
            font_size=int(
                page.get("english_font_size", ARTICLE_SUBTITLE_EN_FONT_SIZE)
                if page
                else ARTICLE_SUBTITLE_EN_FONT_SIZE
            ),
        )
        en_lines = list(page.get("en_lines") or []) if page else []
        if not en_lines:
            en_lines = wrap_article_en_subtitle(d, visual_en, en_font, acx(en_width))
            if len(en_lines) == 2:
                en_lines = wrap_en_preserving_highlight(d, visual_en, en_font, acx(en_width), key)
        highlight_ranges = highlight_ranges_for_lines(en_lines, key)
        zh_width = ARTICLE_SUBTITLE_ZH_WIDTH
        zh_font = fit_article_zh_font(d, visual_zh, acx(zh_width)) if visual_zh else None
        zh_lines = wrap_zh(d, visual_zh, zh_font, acx(zh_width)) if visual_zh else []
        en_gap = int(en_font.size * 1.16)
        zh_gap = 58
        en_count = max(1, len(en_lines))
        zh_count = max(0, len(zh_lines))
        if en_count == 1 and zh_count <= 1:
            en_y, zh_y = 604, 766
        elif en_count == 2 and zh_count <= 1:
            en_y, zh_y = 570, 772
        elif en_count == 1 and zh_count == 2:
            en_y, zh_y = 586, 736
        elif en_count == 3:
            en_y, zh_y = 552, 746
        else:
            en_y, zh_y = 560, 736
        for idx, line in enumerate(en_lines):
            fill = with_alpha((42, 63, 93, 255), subtitle_alpha)
            if highlight_ranges[idx]:
                draw_highlighted_article_line(
                    d,
                    acx(en_x + en_width // 2),
                    acy(en_y) + idx * en_gap,
                    line,
                    key,
                    en_font,
                    fill,
                    with_alpha(ARTICLE_BLUE, subtitle_alpha),
                    highlight_ranges[idx],
                )
            else:
                line_x = acx(en_x) + (acx(en_width) - text_w(d, line, en_font)) // 2
                draw_stroked_text(d, (line_x, acy(en_y) + idx * en_gap), line, en_font, fill, stroke_width=0)
        if zh_lines and not english_only:
            zh_fill = with_alpha((65, 81, 104, 255), subtitle_alpha)
            for idx, line in enumerate(zh_lines):
                draw_stroked_text(d, (ARTICLE_WIDTH // 2, acy(zh_y) + idx * acy(zh_gap)), line, zh_font, zh_fill, anchor="ma", stroke_width=0)
    return img


def draw_highlighted_article_line(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    line: str,
    key: str,
    fnt,
    fill,
    highlight_fill,
    match_range: tuple[int, int] | None = None,
) -> None:
    if match_range is None:
        start = line.lower().find(key.lower())
        end = extend_highlight_to_trailing_punctuation(line, start + len(key)) if start >= 0 else start
    else:
        start, end = match_range
    if start < 0 or end > len(line) or start >= end:
        draw_stroked_text(draw, (x, y), line, fnt, fill, stroke_width=0)
        return
    widths = [text_w(draw, part, fnt) for part in (line[:start], line[start:end], line[end:])]
    cursor = x - sum(widths) // 2
    for idx, part in enumerate((line[:start], line[start:end], line[end:])):
        if part:
            draw_stroked_text(draw, (cursor, y), part, fnt, highlight_fill if idx == 1 else fill, stroke_width=0)
            cursor += text_w(draw, part, fnt)


def render_podcast_learning_video(
    media_path: str,
    subtitle_path: str,
    output_path: str,
    template_style: str = "暗色播客",
    show_ai_vocab: bool = False,
    title_text: str = "",
    background_path: str = "",
    cover_path: str = "",
    date_text: str = "",
    progress_callback=None,
    cancel_check: Callable[[], bool] | None = None,
    process_callback: Callable[[object | None], None] | None = None,
    allow_manual_draft: bool = False,
    english_only: bool = False,
) -> None:
    cues = parse_srt(subtitle_path)
    if not cues:
        raise RuntimeError("字幕文件没有可用内容")
    is_article_template = template_style == "文章单词"
    if is_article_template:
        # Reject any unreadable fixed-font page before a vocabulary request or
        # ffmpeg process can create a partial output.
        prepare_article_visual_page_plans(
            cues,
            subtitle_path,
            allow_manual_draft=allow_manual_draft,
        )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    vocab_plan = load_or_generate_vocab_plan(
        subtitle_path,
        cues,
        show_ai_vocab,
        progress_callback=progress_callback,
        align_to_article_pages=is_article_template,
    )
    # The template is a video presentation of the source media, not a subtitle
    # clip. Keep the entire audio/video even when its final subtitle ends early.
    duration = get_duration(media_path)
    frames = int(math.ceil(duration * FPS))
    out_width = ARTICLE_WIDTH if is_article_template else WIDTH
    out_height = ARTICLE_HEIGHT if is_article_template else HEIGHT
    base = None if is_article_template else make_base(background_path)
    article_image = make_article_image(cover_path, (acx(854), acy(480))) if is_article_template else None
    male, female = (None, None) if is_article_template else make_avatars()
    title_text = (title_text or TITLE_TEXT).strip() or TITLE_TEXT
    date_text = (date_text or "Jul 23rd 2026").strip() or "Jul 23rd 2026"

    with staged_media_output(output_path) as staged_output:
        cmd = [
            str(FFMPEG),
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{out_width}x{out_height}",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-i",
            str(media_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "slow",
            "-crf",
            "15",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(staged_output),
        ]
        process = None
        last_index = 0
        last_cue_key = object()
        cached_frame_bytes = None

        with tempfile.TemporaryFile(mode="w+b") as stderr_file:
            def ffmpeg_stderr_detail() -> str:
                stderr_file.flush()
                stderr_file.seek(0)
                return stderr_file.read().decode(
                    "utf-8", errors="replace"
                ).strip()

            try:
                if cancel_check and cancel_check():
                    raise MediaSynthesisCancelled("视频合成已取消")
                try:
                    process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=stderr_file,
                        text=False,
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW
                            if hasattr(subprocess, "CREATE_NO_WINDOW")
                            else 0
                        ),
                    )
                except Exception as exc:
                    raise RuntimeError(f"无法启动 FFmpeg：{exc}") from exc

                if process_callback:
                    process_callback(process)
                for frame_index in range(frames):
                    if cancel_check and cancel_check():
                        raise MediaSynthesisCancelled("视频合成已取消")
                    t = frame_index / FPS
                    cue, last_index = active_cue(cues, t, last_index)
                    alpha = fade_alpha(cue, t)
                    vocab, vocab_state = (
                        vocab_card_display_state(vocab_plan, cue, t)
                        if show_ai_vocab
                        else (None, "hidden")
                    )
                    vocab_display_id = (
                        f"{vocab.get('display_id', '')}:{vocab_state}"
                        if vocab
                        else None
                    )
                    cue_key = (
                        template_style,
                        cue.start if cue else None,
                        cue.end if cue else None,
                        cue.en if cue else None,
                        cue.zh if cue else None,
                        alpha,
                        title_text,
                        article_visual_page_index(cue, t)
                        if is_article_template
                        else 0,
                        vocab_display_id,
                        english_only,
                    )
                    if cue_key != last_cue_key:
                        if is_article_template:
                            frame = draw_article_frame(
                                article_image,
                                cue,
                                vocab_plan,
                                alpha,
                                show_ai_vocab,
                                title_text,
                                date_text,
                                t,
                                english_only,
                            ).convert("RGB")
                        else:
                            frame = draw_frame(
                                base,
                                male,
                                female,
                                cue,
                                vocab_plan,
                                alpha,
                                show_ai_vocab,
                                title_text,
                                t,
                                english_only,
                            ).convert("RGB")
                        cached_frame_bytes = frame.tobytes()
                        last_cue_key = cue_key
                    try:
                        process.stdin.write(cached_frame_bytes)
                    except (BrokenPipeError, OSError) as exc:
                        if cancel_check and cancel_check():
                            raise MediaSynthesisCancelled("视频合成已取消") from exc
                        terminate_media_process(process)
                        detail = ffmpeg_stderr_detail()
                        suffix = f"：{detail[-4000:]}" if detail else ""
                        raise RuntimeError(
                            f"模板视频写入 FFmpeg 失败{suffix}"
                        ) from exc
                    if progress_callback and (
                        frame_index % 25 == 0 or frame_index == frames - 1
                    ):
                        progress_callback(
                            int(frame_index / max(frames - 1, 1) * 100),
                            "英语学习模板渲染中",
                        )
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError) as exc:
                    if cancel_check and cancel_check():
                        raise MediaSynthesisCancelled("视频合成已取消") from exc
                    terminate_media_process(process)
                    detail = ffmpeg_stderr_detail()
                    suffix = f"：{detail[-4000:]}" if detail else ""
                    raise RuntimeError(
                        f"模板视频结束 FFmpeg 输入失败{suffix}"
                    ) from exc
                return_code = process.wait()
                if cancel_check and cancel_check():
                    raise MediaSynthesisCancelled("视频合成已取消")
                if return_code != 0:
                    detail = ffmpeg_stderr_detail()
                    suffix = f"：{detail[-4000:]}" if detail else ""
                    raise RuntimeError(
                        f"模板视频合成失败，FFmpeg 退出码 {return_code}{suffix}"
                    )
            finally:
                terminate_media_process(process)
                if process_callback:
                    process_callback(None)
