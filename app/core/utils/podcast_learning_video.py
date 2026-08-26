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

from app.core.llm_client import OpenAI
from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)

from app.config import BIN_PATH, CACHE_PATH, RESOURCE_PATH
from app.core.llm_service_config import resolve_llm_service_config
from app.core.subtitle_processor.stable_display_planner import (
    plan_word_page_span_frontier,
    plan_word_page_spans,
)
from app.core.subtitle_processor.text_metrics import HARD_ENGLISH_WORD_LIMIT
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
    find_stable_manifest_for_artifact,
    resolve_manifest_owned_path,
    validate_manifest_artifact,
)
from app.core.subtitle_processor.derived_media_timeline import (
    DerivedMediaTimelineError,
    map_source_time_ms,
    normalize_deleted_intervals,
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
PODCAST_OUTPUT_RESOLUTIONS = {
    "1080p": (1920, 1080),
    "1440p平台上传": (2560, 1440),
}
PODCAST_KEYFRAME_INTERVAL_SECONDS = 2
ARTICLE_SCALE_X = ARTICLE_WIDTH / ARTICLE_DESIGN_WIDTH
ARTICLE_SCALE_Y = ARTICLE_HEIGHT / ARTICLE_DESIGN_HEIGHT
ARTICLE_CARD_CONTAINER = (251, 246, 237, 255)  # #FBF6ED

TEMPLATE_DIR = RESOURCE_PATH / "podcast_template"
ARTICLE_TEMPLATE_DIR = TEMPLATE_DIR / "article_vocab"
TEMPLATE_FONT_DIR = TEMPLATE_DIR / "fonts"
ARTICLE_LOGO_DIR = ARTICLE_TEMPLATE_DIR / "logos"
BACKGROUND = TEMPLATE_DIR / "background.png"
AVATAR_SOURCE = TEMPLATE_DIR / "hosts.png"
FONT_GANTARI = TEMPLATE_FONT_DIR / "Gantari-wght.ttf"
FONT_READEX_MEDIUM = TEMPLATE_FONT_DIR / "ReadexPro-Medium.ttf"
FONT_READEX_SEMIBOLD = TEMPLATE_FONT_DIR / "ReadexPro-SemiBold.ttf"
FONT_READEX_BOLD = TEMPLATE_FONT_DIR / "ReadexPro-Bold.ttf"
FONT_READEX_REGULAR = TEMPLATE_FONT_DIR / "ReadexPro-Regular.ttf"
FONT_ROBOTO_SLAB_REGULAR = TEMPLATE_FONT_DIR / "RobotoSlab-Regular.ttf"
FONT_ROBOTO_SLAB_SEMIBOLD = TEMPLATE_FONT_DIR / "RobotoSlab-SemiBold.ttf"
FONT_SOURCE_SERIF_PRO_SEMIBOLD = TEMPLATE_FONT_DIR / "SourceSerifPro-Semibold.otf"
FONT_SOURCE_HAN_SERIF_CN_BOLD = TEMPLATE_FONT_DIR / "SourceHanSerifCN-Bold.otf"
FONT_SOURCE_HAN_SERIF_CN_SEMIBOLD = (
    TEMPLATE_FONT_DIR / "SourceHanSerifCN-SemiBold.otf"
)
FONT_ALIMAMA_SHUHEI_BOLD = TEMPLATE_FONT_DIR / "AlimamaShuHeiTi-Bold.ttf"
FONT_HANCHAN_BOLD = TEMPLATE_FONT_DIR / "ChillYunmoGothicBold.otf"
FONT_HANCHAN_HEAVY = TEMPLATE_FONT_DIR / "ChillYunmoGothicHeavy.otf"
FONT_HANCHAN_MEDIUM = TEMPLATE_FONT_DIR / "ChillYunmoGothicMedium.otf"
FONT_HANCHAN_REGULAR = TEMPLATE_FONT_DIR / "ChillYunmoGothicRegular.otf"
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
ARTICLE_SUBTITLE_ZH_COLOR = (85, 103, 128, 255)
ARTICLE_VOCAB_MEANING_COLOR = (42, 63, 93, 255)
ARTICLE_DATE_SCRIM_ENABLED = False
ARTICLE_DATE_SCRIM_COLOR = (27, 47, 74)  # #1B2F4A
ARTICLE_DATE_TEXT_COLOR = (251, 246, 237, 255)  # #FBF6ED
ARTICLE_DATE_SCRIM_MIN_ALPHA = 110
ARTICLE_DATE_SCRIM_MAX_ALPHA = 180
ARTICLE_DATE_MIN_CONTRAST = 4.5
ARTICLE_VOCAB_MEANING_FONT_WEIGHT = 600
ARTICLE_VOCAB_MEANING_MAX_RENDER_SIZE = 45
ARTICLE_VOCAB_MEANING_MIN_RENDER_SIZE = 29
ARTICLE_VOCAB_DETAIL_COLOR = ARTICLE_SUBTITLE_ZH_COLOR
ARTICLE_VOCAB_DETAIL_FONT_SIZE = 28
ARTICLE_VOCAB_DETAIL_MIN_FONT_SIZE = 22
ARTICLE_VOCAB_DETAIL_FONT_WEIGHT = 500
ARTICLE_VOCAB_DETAIL_EN_FONT_SCALE = 1.14
ARTICLE_VOCAB_DETAIL_MIN_TAIL_RATIO = 0.62
ARTICLE_VOCAB_PHRASE_MAX_FONT_SIZE = 58
ARTICLE_VOCAB_PHRASE_SINGLE_LINE_MIN_FONT_SIZE = 46
ARTICLE_VOCAB_PHRASE_MIN_FONT_SIZE = 32
ARTICLE_VOCAB_UNBROKEN_WORD_MIN_FONT_SIZE = 20
ARTICLE_VOCAB_PHRASE_LINE_BALANCE_RATIO = 0.55
# Keep every line inside the rounded card's safe edge without wasting width.
# These values are design-grid pixels. At 1920x1080 the accent gaps and the
# right content inset each resolve to an actual 45px safe margin.
ARTICLE_VOCAB_CONTENT_LEFT = 82.5
ARTICLE_VOCAB_CONTENT_RIGHT = 37.5
# Keep the accent aligned with the title card while leaving a deliberate
# breathing space before the first card line.
ARTICLE_VOCAB_ACCENT_LEFT = 37.5
ARTICLE_VOCAB_ACCENT_WIDTH = 7.5
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
VOCAB_PROMPT_VERSION = 17
VOCAB_GROUP_MAX_CUES = 6
VOCAB_GROUP_MAX_SECONDS = 18.0
VOCAB_GROUP_SILENCE_SECONDS = 0.7
VOCAB_MIN_CARD_INTERVAL_SECONDS = 15.0
VOCAB_CARDS_PER_MINUTE = 1.0
VOCAB_MIN_CARDS_PER_EPISODE = 3
VOCAB_MAX_CARDS_PER_EPISODE = 22
VOCAB_MAX_CONCEPT_CARDS_PER_EPISODE = 6
ARTICLE_SUBTITLE_EN_FONT_SIZE = 56
ARTICLE_SUBTITLE_ZH_FONT_SIZE = 50
# Percentage of the rendered font size applied between adjacent glyphs.
# This is intentionally scoped to the article template subtitle renderer;
# ordinary subtitles and vocabulary cards keep their existing spacing.
ARTICLE_SUBTITLE_ZH_LETTER_SPACING = 0.0
ARTICLE_SUBTITLE_EN_LINE_HEIGHT_MULTIPLIER = 1.22
# Every newly planned page keeps a 52px floor. The legacy 50px size is accepted
# only while validating or reopening an already-frozen artifact.
ARTICLE_SUBTITLE_EN_FALLBACK_SIZES = (56, 54, 52)
ARTICLE_SUBTITLE_EN_EMERGENCY_FALLBACK_SIZES: tuple[int, ...] = ()
ARTICLE_SUBTITLE_EN_LEGACY_FALLBACK_SIZES: tuple[int, ...] = (50,)
ARTICLE_SUBTITLE_EN_ALLOWED_SIZES = (
    *ARTICLE_SUBTITLE_EN_FALLBACK_SIZES,
    *ARTICLE_SUBTITLE_EN_LEGACY_FALLBACK_SIZES,
)
ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES = ARTICLE_SUBTITLE_EN_FALLBACK_SIZES
ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE = min(ARTICLE_SUBTITLE_EN_FALLBACK_SIZES)
ARTICLE_SUBTITLE_EN_MIN_SIZE = min(ARTICLE_SUBTITLE_EN_ALLOWED_SIZES)
ARTICLE_SUBTITLE_ZH_MIN_SIZE = ARTICLE_SUBTITLE_ZH_FONT_SIZE
ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH = 1100
ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH = 1260
ARTICLE_SUBTITLE_EN_WIDTH = 1455
# A cue may use the full safe panel width while retaining the preferred font.
# This is a layout profile, never a segmentation budget.
ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH = 1498
ARTICLE_SUBTITLE_ZH_WIDTH = 1455
ARTICLE_PAGE_MIN_DURATION_MS = 900
ARTICLE_PAGE_COMFORTABLE_MAX_DURATION_MS = 5200
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
ARTICLE_PAGE_SHORT_TERMINAL_REVIEW_MIN_WORDS = 5
ARTICLE_PAGE_SECONDARY_REVIEW_STRONG_PAUSE_MS = 500
ARTICLE_PAGE_PRESSURE_TRANSITION_FREE_DELTA = 0.22
ARTICLE_PAGE_PRESSURE_TRANSITION_PENALTY = 3_000
ARTICLE_PAGE_FONT_TRANSITION_PENALTY = 40
ARTICLE_PAGE_LINE_COUNT_TRANSITION_PENALTY = 30
ARTICLE_PAGE_INCOMPLETE_REVIEW_PENALTY = 800
ARTICLE_PAGE_CANDIDATE_FRONTIER_LIMIT = 4
ARTICLE_PAGE_TWO_LINE_BALANCE_FREE_RATIO = 0.82
ARTICLE_PAGE_TWO_LINE_BALANCE_PENALTY = 4_000
# Same-screen line wrapping may choose a wider profile than page planning, but
# it must not leave an extreme orphan line merely because a punctuation cut was
# encountered first.  This threshold is deliberately conservative: ordinary
# two-line pages remain at 56px, while a severe imbalance may use one complete
# line at a lower allowed size when that is the only cleaner layout.
ARTICLE_SAME_SCREEN_SEVERE_IMBALANCE_RATIO = 0.48
ARTICLE_SAME_SCREEN_BALANCE_FREE_RATIO = 0.72
ARTICLE_SAME_SCREEN_BALANCE_PENALTY = 30_000
ARTICLE_PAGE_50PX_LAST_RESORT_PENALTY = 1_200
ARTICLE_PAGE_ATOMIC_BOUNDARY_ISSUES = frozenset(
    {
        "determiner_numeric_noun_split",
        "modifier_head_split",
        "modifier_noun_head_split",
        "numeric_magnitude_split",
        "numeric_range_split",
        "numeric_unit_or_noun_split",
        "post_noun_participial_modifier_split",
        "subject_predicate_split",
        "subject_finite_verb_split",
        "verb_object_split",
        "to_infinitive_split",
    }
)
# A long frozen cue remains one subtitle ID and one timing envelope, but the
# article template may paginate it inside that envelope.  These are render
# budgets, not segmentation or translation limits.
# Keep 16 words as a soft renderer preference. The preferred 6-12 word target
# still guides the balanced split when possible.
# This is a preference, not a feasibility rule. Proportional-font pixel fit,
# grammar evidence, and page timing decide whether a page is renderable.
ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS = 16
ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS = 14
ARTICLE_VISUAL_PAGE_PREFERRED_WORDS = 12
ARTICLE_VISUAL_PAGE_REVIEW_WORDS = 15
ARTICLE_VISUAL_PAGE_SPLIT_PRIORITY_WORDS = 16
ARTICLE_VISUAL_PAGE_MIN_WORDS = 4
ARTICLE_VISUAL_PAGE_MAX_PAGES = 4
# A small number of renderable review fallbacks is acceptable at episode level.
# The fallback is tracked as degraded state; it is not a parent-level error.
ARTICLE_DISPLAY_DEGRADED_MAX_RATIO = 0.02
# Automatic planning stays conservative. An explicit editor action may use
# more pages because the user reviews every new boundary and translation.
ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES = 6
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
ARTICLE_VOCAB_PUNCTUATION_BREAKS = frozenset("，。；：、,.!?;:")
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
ARTICLE_PAGE_OPTIONAL_TEMPORAL_ADJUNCT_START_WORDS = frozenset(
    {"after", "before", "during"}
)
ARTICLE_PAGE_CONTINUATION_START_WORDS = frozenset(
    (LINE_BREAK_AVOID_BEFORE_WORDS - ARTICLE_PAGE_PHRASE_START_WORDS)
    | {"and", "but", "nor", "or", "so", "yet"}
)
MANUAL_DRAFT_PAGE_SCHEMA_VERSION = 1
# A display page may begin or end between ordinary clauses, but not inside a
# multiword work/person/place name.  This is deliberately inferred from the
# surface form rather than maintained as a sample-specific title list: title
# case, numeric tokens, and the small set of lower-case title connectors are
# enough to cover forms such as ``Escape from the 21 st Century`` while leaving
# coordinated titles (``Journey to the West and Escape ...``) separable.
ARTICLE_TITLE_CONNECTOR_WORDS = frozenset(
    {
        "a",
        "an",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "onto",
        "the",
        "to",
        "with",
    }
)
ARTICLE_TITLE_NUMERIC_SUFFIXES = frozenset({"s", "st", "nd", "rd", "th"})
ARTICLE_PAGE_OBJECT_DETERMINERS = frozenset(
    {"a", "an", "the", "this", "that", "these", "those", "my", "your", "our", "their", "its"}
)
ARTICLE_PAGE_NOMINAL_OBJECT_START_WORDS = frozenset(
    ARTICLE_PAGE_OBJECT_DETERMINERS
    | {"all", "any", "each", "either", "enough", "every", "few", "many", "more", "most", "much", "neither", "no", "several", "some"}
)
ARTICLE_PAGE_OF_QUANTIFIER_HEAD_WORDS = frozenset(
    {
        "all",
        "any",
        "each",
        "either",
        "every",
        "few",
        "half",
        "many",
        "most",
        "much",
        "neither",
        "no",
        "some",
    }
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
ARTICLE_PAGE_COMPLETE_SUBJECT_START_WORDS = frozenset(
    {"he", "i", "it", "she", "they", "we", "you"}
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
    # Optional presentation projection.  Each item maps one visible surface
    # back to an inclusive range in ``word_timing``.
    display_word_spans: tuple[dict, ...] = ()


def _article_timing_word_end(item: Mapping[str, object]) -> int:
    return int(item.get("word_end", item.get("word_id", -1)))


def _project_article_display_word_timing(
    raw_timing: Sequence[Mapping[str, object]],
    display_spans: Sequence[Mapping[str, object]],
) -> tuple[dict, ...]:
    """Project immutable raw words into atomic display spans."""
    timing = [dict(item) for item in raw_timing if isinstance(item, Mapping)]
    spans = [dict(item) for item in display_spans if isinstance(item, Mapping)]
    if not timing or not spans:
        return ()
    try:
        by_id = {int(item["word_id"]): item for item in timing}
        expected_start = int(timing[0]["word_id"])
        projected: list[dict] = []
        for span in spans:
            start = int(span["word_start"])
            end = int(span["word_end"])
            surface = re.sub(
                r"\s+",
                " ",
                str(span.get("surface") or ""),
            ).strip()
            if (
                start != expected_start
                or end < start
                or not surface
                or any(word_id not in by_id for word_id in range(start, end + 1))
            ):
                return ()
            projected.append(
                {
                    "word_id": start,
                    "word_end": end,
                    "surface": surface,
                    "start": float(by_id[start]["start"]),
                    "end": float(by_id[end]["end"]),
                }
            )
            expected_start = end + 1
        if expected_start != int(timing[-1]["word_id"]) + 1:
            return ()
    except (KeyError, TypeError, ValueError):
        return ()
    return tuple(projected)


def _article_local_spans_for_global_ranges(
    timing: Sequence[Mapping[str, object]],
    ranges: Sequence[tuple[int, int]],
) -> list[tuple[int, int]] | None:
    """Map raw ledger ranges to display-token indexes without splitting a span."""
    records = [dict(item) for item in timing if isinstance(item, Mapping)]
    try:
        by_start = {int(item["word_id"]): index for index, item in enumerate(records)}
        by_end = {
            _article_timing_word_end(item): index
            for index, item in enumerate(records)
        }
        local_spans: list[tuple[int, int]] = []
        for global_start, global_end in ranges:
            local_start = by_start[int(global_start)]
            local_end_index = by_end[int(global_end)]
            if local_end_index < local_start:
                return None
            previous_end = int(global_start) - 1
            for item in records[local_start : local_end_index + 1]:
                item_start = int(item["word_id"])
                item_end = _article_timing_word_end(item)
                if item_start != previous_end + 1 or item_end < item_start:
                    return None
                previous_end = item_end
            if previous_end != int(global_end):
                return None
            local_spans.append((local_start, local_end_index + 1))
    except (KeyError, TypeError, ValueError):
        return None
    return local_spans


def _article_boundary_words(cue: Cue) -> list[str]:
    """Return validated presentation surfaces without losing word provenance."""
    timing = list(cue.word_timing or ())
    spans = list(cue.display_word_spans or ())
    if timing and spans and len(timing) == len(spans):
        surfaces: list[str] = []
        expected_start = int(timing[0].get("word_id", -1))
        for item, span in zip(timing, spans):
            if not isinstance(item, Mapping) or not isinstance(span, Mapping):
                return str(cue.en or "").split()
            try:
                start, end = int(span["word_start"]), int(span["word_end"])
            except (KeyError, TypeError, ValueError):
                return str(cue.en or "").split()
            surface = re.sub(r"\s+", " ", str(span.get("surface") or "")).strip()
            if (
                not surface
                or start != expected_start
                or end < start
                or int(item.get("word_id", -1)) != start
                or _article_timing_word_end(item) != end
            ):
                return str(cue.en or "").split()
            surfaces.append(surface)
            expected_start = end + 1
        if (
            expected_start == _article_timing_word_end(timing[-1]) + 1
            and " ".join(surfaces) == " ".join(str(cue.en or "").split())
        ):
            return surfaces
    if timing:
        surfaces = [
            re.sub(r"\s+", " ", str(item.get("surface") or "")).strip()
            for item in timing
            if isinstance(item, Mapping)
        ]
        if (
            len(surfaces) == len(timing)
            and all(surfaces)
            and " ".join(" ".join(surfaces).split())
            == " ".join(str(cue.en or "").split())
        ):
            return surfaces
    return str(cue.en or "").split()


class RenderStructuralOverflowError(RuntimeError):
    """Block video synthesis when a fixed-font render page cannot be planned."""

    code = "render_structural_overflow"

    def __init__(
        self,
        errors: list[dict],
        *,
        partial_blueprint: Mapping[str, object] | None = None,
    ):
        self.errors = list(errors)
        self.partial_blueprint = (
            copy.deepcopy(dict(partial_blueprint))
            if isinstance(partial_blueprint, Mapping)
            else {}
        )
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


def article_date_font(size: int) -> ImageFont.FreeTypeFont:
    if FONT_ALIMAMA_SHUHEI_BOLD.exists():
        return font(FONT_ALIMAMA_SHUHEI_BOLD, acx(size), 700)
    return article_en_font(size, 700)


def article_subtitle_en_font(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    """Return the article subtitle face without changing card/title typography."""
    size = acx(size)
    if weight >= 600 and FONT_ROBOTO_SLAB_SEMIBOLD.exists():
        return font(FONT_ROBOTO_SLAB_SEMIBOLD, size, weight)
    if FONT_ROBOTO_SLAB_REGULAR.exists():
        return font(FONT_ROBOTO_SLAB_REGULAR, size, weight)
    return article_en_font(round(size / ARTICLE_SCALE_X), weight)


def article_vocab_phrase_font(size: int) -> ImageFont.FreeTypeFont:
    """Return the bundled Source Serif Pro SemiBold face for card expressions."""
    if FONT_SOURCE_SERIF_PRO_SEMIBOLD.exists():
        return font(FONT_SOURCE_SERIF_PRO_SEMIBOLD, acx(size), 600)
    return article_subtitle_en_font(size, 600)


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


def article_source_han_serif_cn_bold_font(size: int) -> ImageFont.FreeTypeFont:
    """Return the bundled Source Han Serif CN Bold face for opening titles."""
    if FONT_SOURCE_HAN_SERIF_CN_BOLD.exists():
        return font(FONT_SOURCE_HAN_SERIF_CN_BOLD, acx(size), 700)
    return article_cjk_font(size, 700)


def article_vocab_meaning_font(
    size: int,
    *,
    rendered: bool = False,
) -> ImageFont.FreeTypeFont:
    """Return the bundled 600-weight serif face for vocabulary meanings."""
    render_size = size if rendered else acx(size)
    if FONT_SOURCE_HAN_SERIF_CN_SEMIBOLD.exists():
        return font(
            FONT_SOURCE_HAN_SERIF_CN_SEMIBOLD,
            render_size,
            ARTICLE_VOCAB_MEANING_FONT_WEIGHT,
        )
    fallback_path = FONT_HANCHAN_BOLD if FONT_HANCHAN_BOLD.exists() else FONT_YAHEI
    return font(fallback_path, render_size, 700)


def article_vocab_detail_font(size: int) -> ImageFont.FreeTypeFont:
    """Return the medium-weight face used by vocabulary explanations."""
    return article_cjk_font(size, ARTICLE_VOCAB_DETAIL_FONT_WEIGHT)


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


def article_subtitle_zh_letter_spacing_px(
    fnt: ImageFont.FreeTypeFont,
) -> float:
    """Return article subtitle letter spacing in rendered pixels."""
    return float(fnt.size) * ARTICLE_SUBTITLE_ZH_LETTER_SPACING


def article_subtitle_zh_text_w(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
) -> int:
    """Measure article Chinese subtitles including negative glyph spacing."""
    width = text_w(draw, text, fnt)
    if len(text) <= 1:
        return width
    return max(
        0,
        round(width + article_subtitle_zh_letter_spacing_px(fnt) * (len(text) - 1)),
    )


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
        cue.display_word_spans = ()

    manifest_path = find_stable_manifest_for_artifact(subtitle_path)
    if manifest_path is None:
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stable_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            str((manifest.get("paths") or {}).get("original_top_srt") or ""),
            str((manifest.get("paths_sha256") or {}).get("original_top_srt") or ""),
        )
        if stable_path is None or Path(subtitle_path).resolve() != stable_path.resolve():
            return False
        if not validate_manifest_artifact(
            manifest,
            "original_top_srt",
            stable_path,
            manifest_path=manifest_path,
        ):
            return False
        timeline_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            str(manifest.get("final_cue_timeline_path") or ""),
            str(manifest.get("final_cue_timeline_sha256") or ""),
        )
        if timeline_path is None:
            return False
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        ledger_declared = str(manifest.get("word_ledger_path") or "")
        ledger_path = (
            resolve_manifest_owned_path(
                manifest_path,
                manifest,
                ledger_declared,
                str(manifest.get("word_ledger_sha256") or ""),
            )
            if ledger_declared
            else timeline_path.with_name("word-ledger.json")
        )
        if ledger_path is None or ledger_path.parent != timeline_path.parent:
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
        raw_surface_overrides = list(ledger.get("english_surface_overrides") or [])
        boundary_evidence: Mapping[str, object] | None = None
        boundary_path_value = str(
            manifest.get("display_boundary_evidence_path") or ""
        )
        if boundary_path_value:
            expected_boundary_sha256 = str(
                manifest.get("display_boundary_evidence_sha256") or ""
            )
            boundary_path = resolve_manifest_owned_path(
                manifest_path,
                manifest,
                boundary_path_value,
                expected_boundary_sha256,
            )
            if (
                boundary_path is None
                or not expected_boundary_sha256
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
        presentation = dict(timeline.get("presentation_timeline") or {})
        presentation_records = list(presentation.get("records") or [])
        presentation_by_id = {
            str(record.get("subtitle_id") or ""): dict(record)
            for record in presentation_records
            if isinstance(record, Mapping)
        }
        deleted_intervals = normalize_deleted_intervals(
            presentation.get("deleted_intervals") or []
        )
        words = list(ledger.get("words") or [])
    except (
        DerivedMediaTimelineError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        logger.warning("Article renderer could not load frozen word timing: %s", exc)
        return False

    visible_records = [
        record
        for record in records
        if isinstance(record, Mapping) and not record.get("display_suppressed")
    ]
    if len(visible_records) != len(cues) or not words:
        return False
    if presentation and (
        str((presentation.get("validation") or {}).get("status") or "") != "PASS"
        or set(presentation_by_id)
        != {
            str(record.get("subtitle_id") or "")
            for record in records
            if isinstance(record, Mapping)
        }
    ):
        return False
    overrides_by_start: dict[int, dict] = {}
    previous_override_end = -1
    for raw_override in raw_surface_overrides:
        if not isinstance(raw_override, Mapping):
            return False
        try:
            start, end = int(raw_override["word_start"]), int(raw_override["word_end"])
        except (KeyError, TypeError, ValueError):
            return False
        expected = [str(value) for value in raw_override.get("expected_surfaces") or []]
        surface = re.sub(r"\s+", " ", str(raw_override.get("display_surface") or "")).strip()
        if (
            start <= previous_override_end or end <= start or start < 0 or end >= len(words)
            or len(expected) != end - start + 1 or not surface
            or expected != [str(words[word_id].get("surface") or "") for word_id in range(start, end + 1)]
        ):
            return False
        overrides_by_start[start] = dict(raw_override)
        previous_override_end = end

    attached: list[tuple[Cue, str, tuple[dict, ...], tuple[dict, ...], dict[str, dict] | None]] = []
    seen_subtitle_ids: set[str] = set()
    previous_word_end = -1
    visible_cue_index = 0
    for record in records:
        if not isinstance(record, Mapping):
            return False
        display_suppressed = bool(record.get("display_suppressed"))
        cue = None if display_suppressed else cues[visible_cue_index]
        try:
            subtitle_id = str(record["subtitle_id"])
            word_start = int(record["word_start"])
            word_end = int(record["word_end"])
            presentation_record = presentation_by_id.get(subtitle_id)
            timeline_deleted = bool(
                presentation_record
                and presentation_record.get("timeline_deleted")
            )
            if presentation_record and not timeline_deleted:
                record_start = int(presentation_record["output_start_ms"]) / 1000.0
                record_end = int(presentation_record["output_end_ms"]) / 1000.0
            else:
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
            or (
                cue is not None
                and (
                    abs(record_start - cue.start) > 0.005
                    or abs(record_end - cue.end) > 0.005
                )
            )
        ):
            return False
        timed_words: list[dict] = []
        for word_id, word in enumerate(
            words[word_start : word_end + 1],
            start=word_start,
        ):
            try:
                source_start_ms = int(word["start_ms"])
                source_end_ms = int(word["end_ms"])
                timed_words.append(
                    {
                        "word_id": word_id,
                        "surface": str(word["surface"]),
                        "start": (
                            source_start_ms
                            if timeline_deleted or not presentation
                            else map_source_time_ms(
                                source_start_ms,
                                deleted_intervals,
                            )
                        )
                        / 1000.0,
                        "end": (
                            source_end_ms
                            if timeline_deleted or not presentation
                            else map_source_time_ms(
                                source_end_ms,
                                deleted_intervals,
                            )
                        )
                        / 1000.0,
                    }
                )
            except (
                DerivedMediaTimelineError,
                KeyError,
                TypeError,
                ValueError,
            ):
                return False
        display_spans: list[dict] = []
        cursor = word_start
        while cursor <= word_end:
            override = overrides_by_start.get(cursor)
            if override is not None:
                override_end = int(override["word_end"])
                if override_end > word_end or str(override.get("parent_subtitle_id") or "") != subtitle_id:
                    return False
                display_spans.append({"word_start": cursor, "word_end": override_end, "surface": str(override["display_surface"])})
                cursor = override_end + 1
            else:
                display_spans.append({"word_start": cursor, "word_end": cursor, "surface": str(words[cursor].get("surface") or "")})
                cursor += 1
        displayed_text = (
            str(record.get("original") or "")
            if cue is None
            else cue.en
        )
        if " ".join(str(displayed_text or "").split()) != " ".join(span["surface"] for span in display_spans):
            return False
        if (
            not timed_words
            or float(timed_words[0]["start"]) < record_start - 0.005
            or float(timed_words[-1]["end"]) > record_end + 0.005
        ):
            return False
        projected_timing = _project_article_display_word_timing(
            timed_words,
            display_spans,
        )
        if not projected_timing:
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
        if cue is not None:
            attached.append(
                (
                    cue,
                    subtitle_id,
                    projected_timing,
                    tuple(display_spans),
                    cue_boundary_evidence,
                )
            )
            visible_cue_index += 1

    if previous_word_end != len(words) - 1 or visible_cue_index != len(cues):
        return False

    for cue, subtitle_id, timed_words, display_spans, cue_boundary_evidence in attached:
        cue.subtitle_id = subtitle_id
        cue.word_timing = timed_words
        cue.display_word_spans = display_spans
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
    llm_runtime = resolve_llm_service_config()
    return llm_runtime.base_url, llm_runtime.api_key, llm_runtime.model


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


def _reset_vocab_diagnostics(raw_items, diagnostics: dict | None) -> None:
    if diagnostics is None:
        return
    diagnostics.clear()
    diagnostics.update(
        {
            "raw_items": len(raw_items) if isinstance(raw_items, list) else 0,
            "accepted_items": 0,
            "rejected": {},
        }
    )


def _record_vocab_diagnostic(diagnostics: dict | None, reason: str) -> None:
    if diagnostics is None:
        return
    rejected = diagnostics.setdefault("rejected", {})
    rejected[reason] = int(rejected.get(reason, 0)) + 1


def _annotate_vocab_schedule_diagnostics(
    diagnostics: dict | None,
    plan: dict[int, dict],
) -> None:
    if diagnostics is None:
        return
    diagnostics["scheduled_items"] = len(plan)
    diagnostics["scheduled_detail_items"] = sum(
        bool(str(item.get("detail") or "").strip())
        for item in plan.values()
    )
    diagnostics["scheduled_concept_items"] = sum(
        vocab_card_type(item) == "concept"
        for item in plan.values()
    )


def normalize_vocab_plan(
    raw_items,
    cues: list[Cue],
    groups: list[VocabSemanticGroup] | None = None,
    diagnostics: dict | None = None,
) -> dict[int, dict]:
    _reset_vocab_diagnostics(raw_items, diagnostics)
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
        _record_vocab_diagnostic(diagnostics, "invalid_payload")
        return plan
    for item in raw_items:
        if not isinstance(item, dict):
            _record_vocab_diagnostic(diagnostics, "item_not_object")
            continue
        try:
            cue_index = int(item.get("cue_index"))
        except Exception:
            _record_vocab_diagnostic(diagnostics, "invalid_cue_index")
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
        if not group or not cue:
            _record_vocab_diagnostic(diagnostics, "missing_group_or_cue")
            continue
        if cue_index not in group.cue_indices:
            _record_vocab_diagnostic(diagnostics, "cue_not_in_group")
            continue
        if not meaning:
            _record_vocab_diagnostic(diagnostics, "missing_meaning")
            continue
        phrase = find_vocab_source_phrase(cue.en, phrase_candidate)
        if not phrase:
            _record_vocab_diagnostic(diagnostics, "phrase_not_found")
            continue
        phrase_terms = re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)?", phrase.lower())
        if not phrase_terms:
            _record_vocab_diagnostic(diagnostics, "no_english_terms")
            continue
        if len(phrase_terms) > 8:
            _record_vocab_diagnostic(diagnostics, "too_many_terms")
            continue
        if len(phrase) > 56:
            _record_vocab_diagnostic(diagnostics, "phrase_too_long")
            continue
        if all(term in COMMON_WORDS for term in phrase_terms):
            _record_vocab_diagnostic(diagnostics, "all_common_words")
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
        if diagnostics is not None:
            diagnostics["accepted_items"] = int(diagnostics.get("accepted_items", 0)) + 1
    if diagnostics is not None:
        diagnostics["normalized_items"] = len(plan)
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
        if not cue or not key or not group or vocab_card_priority(item) < 3:
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
        relative = (
            0.0
            if episode_duration <= 0
            else max(0.0, min(1.0, (display_start - episode_start) / episode_duration))
        )
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

    # First take one strong candidate from each timeline stratum so early
    # high-priority candidates cannot consume the whole episode budget.
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

    # Empty strata may be filled by the best remaining candidate, but the
    # minimum interval and exact-expression de-duplication still apply.
    while len(scheduled) < card_limit:
        remaining = [
            entry
            for entry in eligible
            if entry[0] not in selected_cue_indices
            and entry[4] not in selected_keys
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
                -min(
                    (abs(display_starts[value[0]] - start) for start in selected_starts),
                    default=0.0,
                ),
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
- 不选择普通填充口头语、基础词、专有名词、数字、缩略词或只靠上下文才成立的词；但有明确语境义的口语短语和习语可以入选。
- 排除本集主题本身的专业术语，以及能从词根直接猜出大意的透明复合词。比如 tariff gap、connector economies、economies of scale、coping mechanism，除非它们在本集承担了不可替代且非字面意义的论点。
- 优先选择中文字幕难以承载的口语、习语、比喻、反语和低频动词短语，例如 rule of thumb、a far cry from、shell out、barely a blip、draw the line。
- phrase 必须是 cue_index 对应英文字幕中的连续原文，逐字保留原句写法；优先固定搭配、短语或完整概念，最多 8 个英文词。不要为了词典化而改写原文。
- cue_index 必须是 phrase 实际出现的字幕序号，phrase 不能跨字幕行。
- 不要为了凑数量选词。单词卡会从对应字幕出现时开始展示，并保持完整卡片直到下一张替换它。
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
        normalization_diagnostics: dict = {}
        plan = schedule_vocab_card_plan(
            normalize_vocab_plan(
                cards,
                cues,
                groups,
                diagnostics=normalization_diagnostics,
            ),
            cues,
            max_cards=episode_card_target,
            align_to_article_pages=align_to_article_pages,
        )
        _annotate_vocab_schedule_diagnostics(normalization_diagnostics, plan)
        progress_payload["normalization_diagnostics"] = normalization_diagnostics
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
        progress_payload["generation_diagnostics"] = {
            "request_batches": len(request_groups),
            "completed_batches": len(completed_ids),
            "failed_batches": len(failed_chunks),
        }
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
    if _looks_like_numeric_rate_boundary(words, split):
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


def _looks_like_numeric_rate_boundary(words: list[str], split: int) -> bool:
    """Keep an evidenced amount together with ``a/per + period``."""
    if split <= 0 or split >= len(words):
        return False

    def normalized(index: int) -> str:
        return re.sub(r"[^A-Za-z0-9'.]", "", words[index]).lower()

    def is_quantity(token: str) -> bool:
        return bool(
            re.fullmatch(r"\d+(?:[.,]\d+)?", token)
            or token in ENGLISH_NUMERIC_MAGNITUDE_WORDS
        )

    previous = normalized(split - 1)
    following = normalized(split)
    nearby_left = [normalized(index) for index in range(max(0, split - 5), split)]
    has_nearby_quantity = any(is_quantity(token) for token in nearby_left)
    return bool(
        (
            has_nearby_quantity
            and following in ENGLISH_RATE_DETERMINERS
            and split + 1 < len(words)
            and normalized(split + 1) in ENGLISH_RATE_PERIOD_WORDS
        )
        or (
            has_nearby_quantity
            and previous in ENGLISH_RATE_DETERMINERS
            and following in ENGLISH_RATE_PERIOD_WORDS
        )
    )


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
    penalty = _caption_line_break_penalty(words, split)
    if 0 < split < len(words) and "-" in words[split - 1]:
        # Both renderer lines remain visible, and the break is outside the
        # complete whitespace token. Keep the generic wrapper unchanged while
        # removing only its article-template false positive.
        penalty -= CAPTION_HARD_BREAK_PENALTY * 2
    return penalty


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


def _article_same_screen_line_balance_penalty(
    first_width: int,
    second_width: int,
) -> int:
    """Penalize visibly uneven lines without overriding lexical hard stops."""
    widest = max(int(first_width), int(second_width), 1)
    ratio = min(int(first_width), int(second_width)) / widest
    deficit = max(0.0, ARTICLE_SAME_SCREEN_BALANCE_FREE_RATIO - ratio)
    penalty = int(round(deficit * deficit * ARTICLE_SAME_SCREEN_BALANCE_PENALTY))
    # A slight bottom-heavy preference matches established timed-text layout
    # guidance while leaving genuinely balanced candidates effectively tied.
    if first_width > second_width:
        penalty += int(round((first_width - second_width) * 0.12))
    return penalty


def _article_line_balance_ratio(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font_size: int,
) -> float:
    if len(lines) != 2:
        return 1.0
    font = article_subtitle_en_font(int(font_size), 600)
    widths = [text_w(draw, str(line), font) for line in lines]
    widest = max(widths, default=0)
    return min(widths) / widest if widest else 1.0


def _article_layout_has_severe_imbalance(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font_size: int,
) -> bool:
    return (
        len(lines) == 2
        and _article_line_balance_ratio(draw, lines, font_size)
        < ARTICLE_SAME_SCREEN_SEVERE_IMBALANCE_RATIO
    )


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
            | ARTICLE_PAGE_COMPLETE_SUBJECT_START_WORDS
        )
        and _caption_has_terminal_completion(remaining)
    )


def _caption_complete_clausal_subject_before_copula(
    words: list[str],
    split: int,
) -> bool:
    """Recognize a complete clausal subject before a copular predicate."""
    if split <= 0 or split >= len(words):
        return False
    left = [
        re.sub(r"[^A-Za-z']", "", word).lower()
        for word in words[:split]
    ]
    while left and left[0] in {"and", "but", "exactly", "so", "well"}:
        left.pop(0)
    clausal_markers = {
        "that", "what", "whether", "which", "who", "whom", "whose",
    }
    subject_pronouns = ARTICLE_PAGE_COMPLETE_SUBJECT_START_WORDS | {
        "me", "him", "her", "them", "us",
    }
    return bool(
        len(left) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and (
            left[0] in ARTICLE_PAGE_COMPLETE_WH_CLAUSE_START_WORDS
            or any(word in clausal_markers for word in left[1:])
        )
        and left[-1]
        and left[-1] not in LINE_BREAK_AVOID_AFTER_WORDS
        and left[-1] not in subject_pronouns
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


def _article_complete_prepositional_continuation_shape(
    words: list[str],
    split: int,
    issue_codes: set[str],
) -> bool:
    """Recognize a terminal, visible preposition-object continuation."""
    if not 0 <= split < len(words):
        return False
    following = re.sub(r"[^A-Za-z']", "", words[split]).casefold()
    remaining = words[split:]
    object_start = (
        re.sub(r"[^A-Za-z']", "", remaining[1]).casefold()
        if len(remaining) > 1
        else ""
    )
    existing_continuation_issues = {
        "dependency_phrase_entrance_split",
        "object_attached_modifier_split",
        "predicate_attached_continuation_split",
        "unsupported_tight_page_transition",
    }
    noun_attached_continuation_issues = {
        "atomic_of_complement_split",
        "dependency_phrase_entrance_split",
        "unsupported_tight_page_transition",
    }
    simple_for_continuation_issues = {
        "dependency_phrase_entrance_split",
        "unsupported_tight_page_transition",
    }
    quantifier_head_of_phrase = bool(
        following == "of"
        and (
            (
                split >= 1
                and re.sub(
                    r"[^A-Za-z']", "", words[split - 1]
                ).casefold()
                in ARTICLE_PAGE_OF_QUANTIFIER_HEAD_WORDS
            )
            or (
                split >= 2
                and re.sub(
                    r"[^A-Za-z']", "", words[split - 2]
                ).casefold()
                in ARTICLE_PAGE_OF_QUANTIFIER_HEAD_WORDS
            )
        )
    )
    issue_shape_is_supported = bool(
        issue_codes
        and (
            (
                following in {"by", "from", "in", "into"}
                and issue_codes <= existing_continuation_issues
            )
            or (
                following == "for"
                and issue_codes <= simple_for_continuation_issues
            )
            or (
                issue_codes <= noun_attached_continuation_issues
                and object_start in ARTICLE_PAGE_NOMINAL_OBJECT_START_WORDS
                and not quantifier_head_of_phrase
            )
        )
    )
    return bool(
        following in ARTICLE_PAGE_PHRASE_START_WORDS
        and len(remaining) >= ARTICLE_PAGE_SHORT_TERMINAL_REVIEW_MIN_WORDS
        and _caption_has_terminal_completion(remaining)
        and issue_shape_is_supported
    )


def _article_complete_object_continuation_shape(
    words: list[str],
    split: int,
    issue_codes: set[str],
) -> bool:
    """Recognize a complete determiner-led direct-object continuation."""
    if not 0 <= split < len(words):
        return False
    following = re.sub(r"[^A-Za-z']", "", words[split]).casefold()
    remaining = words[split:]
    previous = (
        re.sub(r"[^A-Za-z']", "", words[split - 1]).casefold()
        if split > 0
        else ""
    )
    object_issues = {
        "short_verb_complement_split",
        "short_verb_object_split",
        "verb_complement_split",
    }
    return bool(
        (
            split == 0
            or split >= ARTICLE_VISUAL_PAGE_MIN_WORDS + 1
        )
        and len(remaining) >= ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
        and following in ARTICLE_PAGE_NOMINAL_OBJECT_START_WORDS
        and "short_verb_object_split" in issue_codes
        and issue_codes <= object_issues
        and not previous.endswith(("ed", "ing"))
        and _caption_has_terminal_completion(remaining)
    )


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
    line_balance_penalty: Callable[[int, int], int] | None = None,
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
            if line_balance_penalty is not None:
                score += int(line_balance_penalty(aw, bw))
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
    line_balance_penalty: Callable[[int, int], int] | None = None,
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
        line_balance_penalty=line_balance_penalty,
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
        if line_balance_penalty is not None:
            break_penalty += int(line_balance_penalty(before_width, after_width))
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
    return article_subtitle_en_font(int(font_size), 600)


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
            # Legacy best-effort callers still need a page projection, but the
            # fallback must not create a page that starts with punctuation or
            # splits a glued ASCII token.  If no such projection exists, fail
            # closed instead of manufacturing a visibly malformed page.
            fallback_candidates = [
                value
                for value in nearby
                if 0 < value < len(compact)
                and compact[value] not in punctuation
                and not (
                    compact[value - 1].isascii()
                    and compact[value].isascii()
                    and (
                        compact[value - 1].isalnum()
                        or compact[value].isalnum()
                    )
                )
            ]
            if not fallback_candidates:
                return None
            candidates = fallback_candidates
        # A punctuation boundary is a stronger page-local semantic signal
        # than being a few characters closer to the proportional target. Keep
        # the choice deterministic: punctuation wins within the same safe
        # window, then distance and the existing rightmost tie-break apply.
        punctuation_candidates = [
            value for value in candidates if compact[value - 1] in punctuation
        ]
        if punctuation_candidates:
            candidates = punctuation_candidates
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
    fnt = article_subtitle_en_font(int(font_size), 600)
    score_intrinsic = intrinsic_penalty
    if score_intrinsic is None and relax_same_screen_syntax:
        score_intrinsic = _article_intrinsic_line_break_penalty
    # Keep ordinary lines within a comfortable reading measure. The wider
    # profiles remain controlled fallbacks when a natural two-line wrap is not
    # available; they are not the first-choice one-line target.
    if text_w(draw, text, fnt) <= acx(ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH):
        return [text]
    minimum_word_candidates = (
        (3, 2)
        if (
            len(text.split()) <= ARTICLE_STATIC_TWO_WORD_LINE_MAX_WORDS
            or font_size == ARTICLE_SUBTITLE_EN_MIN_SIZE
        )
        else (3,)
    )
    width_profiles = (
        ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH,
        ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
        ARTICLE_SUBTITLE_EN_WIDTH,
        ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
    )
    max_line_candidates = (
        (2, 3)
        if font_size == ARTICLE_SUBTITLE_EN_MIN_SIZE
        else (2,)
    )
    for max_lines in max_line_candidates:
        for minimum_line_words in minimum_word_candidates:
            candidates: list[tuple[tuple[int, int, int], list[str]]] = []
            for width in width_profiles:
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
                    line_balance_penalty=_article_same_screen_line_balance_penalty,
                )
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
                            # A line break keeps both lines visible at once;
                            # frozen page-boundary syntax must only rank the
                            # candidate, not make an otherwise fitting page
                            # structurally unrenderable. Cross-page planning
                            # still applies the same penalty as a hard gate.
                            boundary_penalty=(
                                None
                                if relax_same_screen_syntax
                                else boundary_penalty
                            ),
                            intrinsic_penalty=score_intrinsic,
                        )
                    )
                ):
                    continue
                line_count = len(lines)
                if line_count == 1:
                    layout_tier = 1
                    layout_score = text_w(draw, lines[0], fnt)
                elif line_count == 2:
                    ratio = _article_line_balance_ratio(draw, lines, font_size)
                    layout_tier = (
                        2
                        if ratio < ARTICLE_SAME_SCREEN_SEVERE_IMBALANCE_RATIO
                        else 0
                    )
                    split = len(lines[0].split())
                    words = text.split()
                    layout_score = abs(
                        text_w(draw, lines[0], fnt)
                        - text_w(draw, lines[1], fnt)
                    )
                    if score_intrinsic is not None:
                        layout_score += int(score_intrinsic(words, split))
                    if boundary_penalty is not None:
                        layout_score += int(boundary_penalty(split))
                    layout_score += int(
                        _article_same_screen_line_balance_penalty(
                            text_w(draw, lines[0], fnt),
                            text_w(draw, lines[1], fnt),
                        )
                    )
                else:
                    layout_tier = 3
                    layout_score = sum(
                        text_w(draw, line, fnt) for line in lines
                    )
                candidates.append(
                    ((layout_tier, layout_score, width), list(lines))
                )
            if candidates:
                # Two-word lines are a last-resort wrapping candidate. New
                # automatic pages never use a third line or 50px; legacy
                # artifacts are validated through the explicit compatibility
                # path instead of being regenerated here.
                return min(candidates, key=lambda item: item[0])[1]
    return []


def _article_english_layout_width(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font_size: int,
) -> int:
    fnt = article_subtitle_en_font(font_size, 600)
    measured = max((text_w(draw, line, fnt) for line in lines), default=0)
    for width in (
        ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
        ARTICLE_SUBTITLE_EN_WIDTH,
        ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
    ):
        if measured <= acx(width):
            return width
    return ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH


def _article_wrap_zh_by_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap article Chinese subtitles using the same spacing as rendering."""
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and article_subtitle_zh_text_w(draw, candidate, fnt) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def wrap_article_zh(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap article Chinese text with punctuation-aware negative letter spacing."""
    text = text.strip()
    if not text:
        return []
    if article_subtitle_zh_text_w(draw, text, fnt) <= max_width:
        return [text]

    comma_positions = [m.end() for m in re.finditer(r"[，,]", text)]
    if comma_positions:
        midpoint = len(text) / 2
        split_at = min(comma_positions, key=lambda pos: abs(pos - midpoint))
        left = text[:split_at].strip()
        right = text[split_at:].strip()
        if len(left) >= 6 and len(right) >= 6:
            lines: list[str] = []
            for part in (left, right):
                if article_subtitle_zh_text_w(draw, part, fnt) <= max_width:
                    lines.append(part)
                else:
                    lines.extend(
                        _article_wrap_zh_by_width(draw, part, fnt, max_width)
                    )
            return lines

    return _article_wrap_zh_by_width(draw, text, fnt, max_width)


def draw_article_zh_line(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    y: int,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    fill,
) -> None:
    """Draw one centered article Chinese line with per-glyph letter spacing."""
    if not text:
        return
    advances = [draw.textlength(char, font=fnt) for char in text]
    spacing = article_subtitle_zh_letter_spacing_px(fnt)
    total_advance = sum(advances) + spacing * max(0, len(text) - 1)
    cursor = float(center_x) - total_advance / 2
    for char, advance in zip(text, advances):
        draw.text((round(cursor), y), char, font=fnt, fill=fill, anchor="la")
        cursor += advance + spacing


def _article_fixed_chinese_lines(draw: ImageDraw.ImageDraw, text: str) -> list[str]:
    if not text:
        return []
    fnt = article_cjk_font(ARTICLE_SUBTITLE_ZH_FONT_SIZE, 700)
    lines = wrap_article_zh(draw, text, fnt, acx(ARTICLE_SUBTITLE_ZH_WIDTH))
    if len(lines) > 2 or any(
        article_subtitle_zh_text_w(draw, line, fnt)
        > acx(ARTICLE_SUBTITLE_ZH_WIDTH)
        for line in lines
    ):
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
    english_font = article_subtitle_en_font(font_size, 600)
    english_pixels = text_w(draw, " ".join(words), english_font)
    english_capacity = max(1, 2 * acx(ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH))
    english_pixel_pages = max(1, math.ceil(english_pixels / english_capacity))
    if len(words) <= ARTICLE_VISUAL_PAGE_REVIEW_WORDS:
        english_word_pages = 1
    else:
        english_word_pages = max(
            2,
            math.ceil(len(words) / ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS),
        )

    chinese_pages = 1
    if chinese:
        chinese_font = article_cjk_font(ARTICLE_SUBTITLE_ZH_FONT_SIZE, 700)
        chinese_pixels = article_subtitle_zh_text_w(draw, chinese, chinese_font)
        chinese_capacity = max(1, 2 * acx(ARTICLE_SUBTITLE_ZH_WIDTH))
        chinese_pages = max(1, math.ceil(chinese_pixels / chinese_capacity))

    measured_load_pages = max(
        english_pixel_pages,
        english_word_pages,
        chinese_pages,
    )
    duration_pages = 1
    if (
        measured_load_pages > 1
        and cue_duration_ms is not None
        and cue_duration_ms > 0
    ):
        duration_pages = max(
            1,
            math.ceil(cue_duration_ms / ARTICLE_PAGE_COMFORTABLE_MAX_DURATION_MS),
        )
    return min(
        ARTICLE_VISUAL_PAGE_MAX_PAGES,
        max(
            measured_load_pages,
            duration_pages,
        ),
    )


def _article_title_entity_spans(words: Sequence[str]) -> tuple[tuple[int, int], ...]:
    """Infer multiword title/name spans from stable surface tokens.

    The display planner receives frozen words, not a model-generated title
    list.  A conservative surface heuristic is therefore preferable to a
    growing allowlist: a span must contain at least two title-case/numeric
    components and a lower-case title connector, a numeric token, or adjacent
    title-case components.  ``and``/``or`` deliberately terminate a span so
    two coordinated works can still be separated between titles.
    """
    if not words:
        return ()

    def surface(index: int) -> str:
        return str(words[index] or "").strip("\"'`([{<")

    def token(index: int) -> str:
        return re.sub(r"[^A-Za-z0-9']", "", surface(index))

    def lower(index: int) -> str:
        return token(index).lower()

    def is_title_or_numeric(index: int) -> bool:
        value = token(index)
        return bool(
            value
            and (
                re.fullmatch(r"[A-Z][A-Za-z0-9']*", value)
                or re.fullmatch(r"\d+(?:\.\d+)?", value)
            )
        )

    def ends_sentence(index: int) -> bool:
        raw = surface(index)
        if not re.search(r"[.!?][\"')\]]*$", raw):
            return False
        if "?" in raw or "!" in raw:
            return True
        abbreviation = raw.rstrip("\"')]")
        return not bool(
            re.fullmatch(r"(?:[A-Z]\.){1,4}", abbreviation)
            or token(index).lower()
            in {"dr", "jr", "mr", "mrs", "ms", "prof", "sr", "st", "vs"}
        )

    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(words):
        if not is_title_or_numeric(index):
            index += 1
            continue
        if lower(index) in ARTICLE_PAGE_COMPLETE_CONTINUATION_START_WORDS:
            index += 1
            continue
        start = index
        components = 1
        has_connector = False
        has_numeric = bool(re.fullmatch(r"\d+(?:\.\d+)?", token(index)))
        cursor = index + 1
        while cursor < len(words):
            if ends_sentence(cursor - 1):
                break
            current = lower(cursor)
            if (
                current in ARTICLE_TITLE_NUMERIC_SUFFIXES
                and re.fullmatch(r"\d+(?:\.\d+)?", token(cursor - 1))
            ):
                components += 1
                has_numeric = True
                cursor += 1
                continue
            if is_title_or_numeric(cursor):
                components += 1
                has_numeric = has_numeric or bool(
                    re.fullmatch(r"\d+(?:\.\d+)?", token(cursor))
                )
                cursor += 1
                continue
            if current in ARTICLE_TITLE_CONNECTOR_WORDS:
                lookahead = cursor + 1
                while (
                    lookahead < len(words)
                    and lower(lookahead) in ARTICLE_TITLE_CONNECTOR_WORDS
                ):
                    lookahead += 1
                if lookahead < len(words) and is_title_or_numeric(lookahead):
                    has_connector = True
                    cursor = lookahead
                    continue
            break
        starts_with_numeric = bool(
            re.fullmatch(r"\d+(?:\.\d+)?", token(start))
        )
        if cursor > start + 1 and (
            has_connector
            or (not starts_with_numeric and (has_numeric or components >= 3))
        ):
            spans.append((start, cursor))
            index = cursor
        else:
            index += 1
    return tuple(spans)


def _article_boundary_inside_title_entity(
    words: Sequence[str],
    split: int,
) -> bool:
    """Return whether a page cut falls inside an inferred title/name span."""
    return any(start < split < end for start, end in _article_title_entity_spans(words))


def _article_boundary_between_title_entities(
    words: Sequence[str],
    split: int,
) -> bool:
    """Return whether a cut would strand the join between two coordinated titles."""
    spans = _article_title_entity_spans(words)
    for left_start, left_end in spans:
        if left_end != split or split >= len(words):
            continue
        connector = re.sub(r"[^A-Za-z]", "", str(words[split] or "")).lower()
        if connector not in {"and", "or"}:
            continue
        if any(
            right_start == split + 1 and right_end - right_start >= 3
            for right_start, right_end in spans
        ):
            return True
    return False


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
    words = _article_boundary_words(cue)
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
    if _article_boundary_inside_title_entity(words, split):
        hard_issues.add("protected_work_title_split")
    if _article_boundary_between_title_entities(words, split):
        hard_issues.add("protected_work_title_join_split")

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
    title_entity_end = any(
        end == split and end - start >= 3
        for start, end in _article_title_entity_spans(words)
    )
    title_entity_join = _article_boundary_between_title_entities(words, split)
    complete_title_restart = bool(
        title_entity_end
        and not title_entity_join
        and min(split, len(words) - split) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and following not in (
            LINE_BREAK_AVOID_BEFORE_WORDS
            | ARTICLE_PAGE_PHRASE_START_WORDS
        )
        and not _caption_boundary_has_stranded_dependency(words, split)
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
    complete_content_clause_start = bool(
        following == "that"
        and complete_page_clause_start
        and min(split, len(words) - split) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and issue_codes
        and issue_codes <= {"object_content_clause_split"}
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
            "clause_complement_entrance_split",
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
    open_parent_coordinated_restart = bool(
        punctuation_boundary
        and following in {"and", "but", "nor", "or", "so", "yet"}
        and split + 1 < len(words)
        and re.sub(r"[^A-Za-z']", "", words[split + 1]).lower()
        in ARTICLE_PAGE_COMPLETE_SUBJECT_START_WORDS
        and min(split, len(words) - split) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and not _caption_has_terminal_completion(words)
        and bool(re.search(r"[,;:][\"')\]]*$", str(words[-1]).strip()))
        and issue_codes
        and issue_codes <= {"coordinated_constituent_split"}
    )
    punctuated_coordinated_gerund_restart = bool(
        following.endswith("ing")
        and punctuation_boundary
        and min(split, len(words) - split) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and _caption_has_terminal_completion(words[split:])
        and pause_ms is not None
        and int(pause_ms) >= ARTICLE_PAGE_BALANCED_CLAUSE_REVIEW_MS
        and issue_codes == {"coordinated_constituent_split"}
    )
    open_parent_coordinated_gerund_restart = bool(
        following in {"and", "but"}
        and split + 1 < len(words)
        and re.sub(r"[^A-Za-z']", "", words[split + 1]).lower().endswith("ing")
        and len(words) - split >= ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
        and pause_ms is not None
        and int(pause_ms) >= ARTICLE_PAGE_BALANCED_CLAUSE_REVIEW_MS
        and bool(re.search(r"[,;:][\"')\]]*$", str(words[-1]).strip()))
        and issue_codes
        and issue_codes <= {"coordinated_constituent_split"}
    )
    complete_prepositional_continuation = (
        _article_complete_prepositional_continuation_shape(
            words,
            split,
            issue_codes,
        )
        or bool(
            following in {"by", "from", "into"}
            and len(words) - split >= ARTICLE_VISUAL_PAGE_MIN_WORDS
            and split + 1 < len(words)
            and re.sub(r"[^A-Za-z']", "", words[split + 1])
            .lower()
            .endswith("ing")
            and issue_codes
            <= {
                "dependency_phrase_entrance_split",
                "object_attached_modifier_split",
                "predicate_attached_continuation_split",
                "unsupported_tight_page_transition",
            }
        )
    )
    complete_object_continuation = _article_complete_object_continuation_shape(
        words,
        split,
        issue_codes,
    )
    balanced_predicate_restart = bool(
        min(split, len(words) - split) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        and _caption_has_terminal_completion(words[split:])
        and pause_ms is not None
        and int(pause_ms) >= ARTICLE_PAGE_BALANCED_CLAUSE_REVIEW_MS
        and atomic
        and atomic
        <= {
            "embedded_wh_clause_split",
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
        relaxation_reason = "complete_wh_clause_start"
    elif complete_content_clause_start:
        classification = "review"
        confidence = "medium"
        relaxation_reason = "complete_content_clause_start"
    elif strong_pause_reviews_clause_boundary:
        classification = "review"
        confidence = "high"
        relaxation_reason = "strong_pause_clause_restart"
    elif (
        complete_clause_restart
        or coordinated_phrase_restart
        or open_parent_coordinated_restart
        or punctuated_coordinated_gerund_restart
        or open_parent_coordinated_gerund_restart
        or complete_prepositional_continuation
        or complete_object_continuation
        or balanced_predicate_restart
    ):
        classification = "review"
        confidence = "medium"
        relaxation_reason = (
            "balanced_predicate_restart"
            if balanced_predicate_restart
            else (
                "punctuated_coordinated_gerund_restart"
                if punctuated_coordinated_gerund_restart
                else (
                    "open_parent_coordinated_restart"
                    if open_parent_coordinated_restart
                    else (
                        "open_parent_coordinated_gerund_restart"
                        if open_parent_coordinated_gerund_restart
                        else (
                            "complete_prepositional_continuation"
                            if complete_prepositional_continuation
                            else (
                                "complete_object_continuation"
                                if complete_object_continuation
                                else "complete_clause_restart"
                            )
                        )
                    )
                )
            )
        )
    elif complete_title_restart:
        classification = "review"
        confidence = "medium"
        relaxation_reason = "complete_title_restart"
    elif atomic:
        classification = "hard"
        confidence = "high"
        relaxation_reason = ""
    elif hard_issues or soft_issues:
        classification = "review"
        confidence = "medium"
        relaxation_reason = (
            "reviewable_hard_issue" if hard_issues else "soft_issue"
        )
    else:
        classification = "allow"
        confidence = "low"
        relaxation_reason = ""
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
        "raw_hard_issue_codes": sorted(hard_issues),
        "raw_atomic_issue_codes": sorted(atomic),
        "relaxed_raw_hard": bool(
            classification == "review"
            and atomic
            and not complete_wh_clause_start
            and not complete_content_clause_start
            and not punctuation_boundary
        ),
        "relaxation_reason": relaxation_reason,
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
        "complete_content_clause_start": complete_content_clause_start,
        "complete_title_restart": complete_title_restart,
        "balanced_predicate_restart": balanced_predicate_restart,
        "punctuated_coordinated_gerund_restart": (
            punctuated_coordinated_gerund_restart
        ),
        "open_parent_coordinated_restart": open_parent_coordinated_restart,
        "open_parent_coordinated_gerund_restart": (
            open_parent_coordinated_gerund_restart
        ),
        "complete_prepositional_continuation": (
            complete_prepositional_continuation
        ),
        "complete_object_continuation": complete_object_continuation,
        "tight_complete_phrase_start": tight_complete_phrase_start,
    }


def _article_line_boundary_penalty(cue: Cue, split: int) -> int:
    """Project frozen syntax evidence onto a renderer-only line break."""
    decision = _article_display_boundary_decision(cue, split)
    issue_codes = set(decision.get("issue_codes") or [])
    if issue_codes == {"unsupported_tight_page_transition"}:
        # A tight pause matters when the text disappears and the next display
        # page replaces it. Both renderer lines remain visible at once, so a
        # page-turn-only timing warning must not distort the line wrap.
        return 0
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
        "clause_introducer_split",
        "dependency_phrase_entrance_split",
        "object_attached_modifier_split",
        "short_verb_complement_split",
        "stranded_leading_complement_split",
        "verb_complement_split",
        "verb_preposition_complement_split",
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
    previous = re.sub(r"[^A-Za-z']", "", words[split - 1]).lower()
    forced_subject_predicate = bool(
        following in {"am", "are", "is", "was", "were"}
        and _caption_complete_clausal_subject_before_copula(words, split)
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
        reviewable.update(
            {
                "high_confidence_modifier_head_split",
                "protected_syntax_cut",
                "relative_clause_subject_verb_split",
            }
        )
    complete_phrase = _caption_phrase_start_is_complete(words, split)
    complete_continuation = _caption_complete_continuation_clause(words[split:])
    predicate_phrase_issues = {
        "predicate_attached_continuation_split",
        "predicate_complement_chain_split",
        "verb_adverb_preposition_split",
    }
    complete_predicate_phrase = bool(
        complete_phrase
        and issue_codes & predicate_phrase_issues
        and issue_codes
        <= reviewable | predicate_phrase_issues
    )
    if (
        forced_subject_predicate
        or (
            issue_codes
            and (
                issue_codes <= reviewable
                or complete_predicate_phrase
            )
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
            "relaxed_raw_hard": bool(
                decision.get("raw_atomic_issue_codes")
            ),
            "relaxation_reason": (
                "forced_subject_predicate"
                if forced_subject_predicate
                else "forced_complete_continuation"
            ),
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
            "forced_complete_to_phrase": bool(
                likely_infinitive_start
                and previous not in ARTICLE_PAGE_TO_INFINITIVE_HEADS
                and not forced_subject_predicate
            ),
            "forced_complete_predicate_phrase": bool(
                complete_predicate_phrase and not forced_subject_predicate
            ),
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


def _article_manual_override_break_rank(
    cue: Cue,
    words: list[str],
    split: int,
    target_words: float,
    word_timing: tuple[dict, ...],
) -> tuple[int, float]:
    """Rank every timed-word boundary for an explicit human override."""
    regular = _article_page_break_rank(
        cue,
        words,
        split,
        target_words,
        word_timing,
        allow_review_boundary=True,
    )
    if regular is not None:
        return regular

    decision = _article_display_boundary_decision(cue, split)
    score = abs(split - target_words) * 240
    # ``allow_hard_boundary`` is an explicit editor action: the caller has
    # already accepted that no grammar-safe automatic cut exists.  Preserve
    # punctuation/pause preferences, but do not let the automatic hard-break
    # penalty (often 12,000+) force the suggestion to the final ``N-1 + 1``
    # split.  A bounded presentation cost keeps natural punctuation ahead of
    # arbitrary cuts while allowing the requested page counts to balance.
    score += min(max(0, _article_visual_break_penalty(words, split)), 900)
    if len(word_timing) == len(words):
        pause_ms = max(
            0,
            round(
                (
                    word_timing[split]["start"]
                    - word_timing[split - 1]["end"]
                )
                * 1000
            ),
        )
        score -= min(pause_ms, ARTICLE_PAGE_PAUSE_PREFERENCE_MS) * 4
    issue_codes = set(decision.get("issue_codes") or [])
    atomic_count = len(issue_codes & ARTICLE_PAGE_ATOMIC_BOUNDARY_ISSUES)
    return 7 + min(atomic_count, 2), float(score)


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
        if (
            decision.get("forced_display_continuation")
            and issue_codes
            & {"short_verb_complement_split", "verb_complement_split"}
        ):
            # A forced page may separate a complete predicate from its subject
            # before it splits a verb from the complement that completes it.
            risk = max(risk, 6)
    if float(cost) >= DISPLAY_PAGE_HIGH_RISK_COST:
        risk = max(risk, 1)
    if (
        decision.get("forced_complete_to_phrase")
        and not issue_codes
        & {"short_verb_complement_split", "verb_complement_split"}
    ):
        # A complete ``to ...`` phrase is still reviewable, but it is a
        # substantially safer page restart only when the left page has not
        # stranded the governing verb from that complement.
        risk = min(risk, 2)
    elif decision.get("complete_prepositional_continuation"):
        risk = min(risk, 2)
    elif decision.get("complete_object_continuation"):
        risk = min(risk, 2)
    elif decision.get("forced_complete_predicate_phrase"):
        risk = min(risk, 2)
    elif decision.get("forced_display_continuation"):
        risk = max(risk, 4)
    if decision.get("forced_subject_predicate"):
        risk = max(risk, 5)
    return risk


ARTICLE_BOUNDARY_ISSUE_LABELS_ZH = {
    "subject_finite_verb_split": "主语和谓语被拆开",
    "subject_predicate_split": "主语和谓语被拆开",
    "relative_clause_subject_verb_split": "从句主语和谓语被拆开",
    "preposition_object_split": "介词和宾语被拆开",
    "verb_preposition_complement_split": "动词及其介词补语被拆开",
    "particle_or_preposition_complement_split": "短语动词或介词补语被拆开",
    "clause_introducer_split": "从句连接处不完整",
    "object_content_clause_split": "宾语从句被拆开",
    "coordinated_constituent_split": "并列结构被拆开",
    "modifier_head_split": "修饰语和中心词被拆开",
    "determiner_head_phrase_split": "限定词和名词被拆开",
    "dependency_phrase_entrance_split": "依存短语入口被拆开",
    "short_verb_complement_split": "动词和补语被拆开",
    "verb_complement_split": "动词和补语被拆开",
    "atomic_of_complement_split": "of 固定补语被拆开",
    "protected_work_title_split": "多词作品名或专名被拆开",
    "protected_work_title_join_split": "并列作品名连接处被拆开",
    "protected_syntax_cut": "命中受保护的语法结构",
    "forced_complete_continuation_page_split": "没有完全安全的切点，使用了受控兜底",
    "forced_subject_predicate_page_split": "没有完全安全的切点，在主谓附近使用了受控兜底",
    "unsupported_tight_page_transition": "停顿较短，翻页衔接偏紧",
}


def article_display_boundary_explanation(
    boundary: Mapping | None,
    *,
    left_english: str = "",
    right_english: str = "",
) -> dict:
    """Turn machine boundary evidence into a stable editor-facing hint."""
    evidence = dict(boundary or {})
    classification = str(evidence.get("classification") or "allow")
    rule_codes = [str(code) for code in evidence.get("issue_codes") or [] if str(code)]
    labels = list(
        dict.fromkeys(
            ARTICLE_BOUNDARY_ISSUE_LABELS_ZH.get(code, f"需复核：{code}")
            for code in rule_codes
        )
    )
    forced = bool(
        evidence.get("forced_display_continuation")
        or evidence.get("forced_subject_predicate")
    )
    if forced and not any("受控兜底" in label for label in labels):
        labels.append("没有完全安全的切点，使用了受控兜底")
    if classification == "allow" and not labels:
        summary = "自然意群切点"
    elif labels:
        summary = "；".join(labels)
    else:
        summary = "这个切点需要人工确认"
    return {
        "classification": classification,
        "confidence": str(evidence.get("confidence") or "low"),
        "rule_codes": rule_codes,
        "summary_zh": summary,
        "requires_confirmation": classification == "review" or forced,
        "applicable": classification != "hard",
        "pause_ms": evidence.get("pause_ms"),
        "left_english": str(left_english or ""),
        "right_english": str(right_english or ""),
        "forced_fallback": forced,
    }


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
    complete_preposition_gerund_page = bool(
        (boundary_decision or {}).get("forced_complete_predicate_phrase")
        and following in {"by", "from", "into"}
        and split + 1 < len(words)
        and re.sub(r"[^A-Za-z']", "", words[split + 1]).lower().endswith("ing")
        and _caption_has_terminal_completion(words[split:])
    )
    pause_ms = (boundary_decision or {}).get("pause_ms")
    strong_pause_evidence = bool(
        (boundary_decision or {}).get("strong_pause_evidence")
    )
    supported_relative_start = bool(
        following in {"that", "which", "who", "whom", "whose", "where", "when"}
        and "dependency_phrase_entrance_split" in issue_codes
        and (
            punctuation_boundary
            or (
                pause_ms is not None
                and int(pause_ms) >= ARTICLE_PAGE_BALANCED_CLAUSE_REVIEW_MS
            )
        )
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
        and (
            issue_codes
            & {
                "object_attached_modifier_split",
                "verb_preposition_complement_split",
            }
            or (boundary_decision or {}).get("classification") == "hard"
        )
        and not complete_preposition_gerund_page
    ):
        # Parser-backed tight complements remain atomic even when the relaxed
        # continuation planner is evaluating an otherwise complete phrase.
        return True
    if (boundary_decision or {}).get("complete_title_restart"):
        # A complete named/work span is an explicit visual unit.  Once it has
        # ended, allow the following independent phrase to start a page even
        # when the parser reports a broader subject/predicate warning at the
        # same word boundary.
        return False
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
    if (boundary_decision or {}).get("forced_complete_predicate_phrase"):
        # The right page owns a complete visible phrase (for example,
        # ``from eating ...``). It remains reviewable but is not a stranded
        # non-finite fragment.
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


def _article_boundary_has_incomplete_predicate(
    decision: Mapping[str, object],
    *,
    words: Sequence[str] | None = None,
    split: int | None = None,
) -> bool:
    """Keep explicit manual review from bisecting a predicate unit.

    Manual pagination may relax layout and timing constraints, but it must not
    turn a parser-backed predicate/object boundary into a displayable page
    split. Completion flags are emitted by the normal boundary classifier when
    the right page is a complete visible continuation.
    """
    issue_codes = {str(code or "") for code in decision.get("issue_codes") or []}
    predicate_issues = {
        "clause_introducer_split",
        "dependency_phrase_entrance_split",
        "object_attached_modifier_split",
        "post_noun_participial_modifier_split",
        "preposition_object_split",
        "subject_finite_verb_split",
        "subject_predicate_split",
        "short_verb_complement_split",
        "short_verb_object_split",
        "verb_complement_split",
        "verb_preposition_complement_split",
        "predicate_attached_continuation_split",
        "predicate_complement_chain_split",
        "verb_adverb_preposition_split",
    }
    if not issue_codes & predicate_issues:
        if (
            "protected_syntax_cut" not in issue_codes
            or words is None
            or split is None
        ):
            return False
        left_surface = str(words[split - 1] or "").strip()
        right_surface = str(words[split] or "").strip()
        adjacent_capitalized_name = bool(
            split > 1
            and re.match(r"^[A-Z][A-Za-z'’-]*[,.!?;:]?$", left_surface)
            and re.match(r"^[A-Z][A-Za-z'’-]*[,.!?;:]?$", right_surface)
        )
        return bool(
            _article_boundary_inside_title_entity(words, split)
            or _article_boundary_between_title_entities(words, split)
            or adjacent_capitalized_name
        )
    completion_flags = {
        "balanced_predicate_restart",
        "complete_object_continuation",
        "complete_prepositional_continuation",
        "complete_title_restart",
        "forced_complete_predicate_phrase",
        "forced_subject_predicate",
    }
    return not any(bool(decision.get(flag)) for flag in completion_flags)


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

    fnt = article_subtitle_en_font(font_size, 600)
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
    allow_manual_override: bool = False,
    prefer_punctuation_for_manual_review: bool = False,
    span_layout: Callable[[int, int, int, bool], Sequence[str]] | None = None,
    span_balance: Callable[[int, int, int, int], float] | None = None,
    max_candidates: int = 1,
) -> list[tuple[int, int]] | list[list[tuple[int, int]]] | None:
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
                    boundary_decision.get("classification") == "allow"
                    and boundary_decision.get("complete_page_clause_start")
                )
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
            else _article_same_screen_english_lines(
                draw,
                cue,
                words,
                start,
                end,
                font_size,
                enforce_word_limit=paginated,
            )
        )
        if allow_manual_override:
            return bool(page_words and lines)
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

    planner_kwargs = {
        "cue_start": float(cue.start),
        "cue_end": float(cue.end),
        "word_timing": word_timing,
        "min_page_duration": (
            0.0
            if allow_manual_override
            else ARTICLE_PAGE_MIN_DURATION_MS / 1000.0
        ),
        "span_is_readable": span_is_readable,
        "break_score": lambda end, target: (
            (
                _article_manual_review_break_rank
                if prefer_punctuation_for_manual_review
                else _article_manual_override_break_rank
            )(
                cue,
                words,
                end,
                target,
                word_timing,
            )
            if allow_manual_override
            else _article_page_break_rank(
                cue,
                words,
                end,
                target,
                word_timing,
                allow_forced_continuation=allow_forced_continuation,
                allow_review_boundary=allow_review_boundary,
            )
        ),
        "span_score": (
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
        "diagnostics": diagnostics,
    }
    if int(max_candidates or 1) > 1:
        return plan_word_page_span_frontier(
            len(words),
            page_count,
            **planner_kwargs,
            max_candidates=max_candidates,
        )
    return plan_word_page_spans(
        len(words),
        page_count,
        **planner_kwargs,
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
    if len(words) != len(_article_boundary_words(cue)):
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


def _article_same_screen_english_lines(
    draw: ImageDraw.ImageDraw,
    cue: Cue,
    words: Sequence[str],
    start: int,
    end: int,
    font_size: int,
    *,
    enforce_word_limit: bool = True,
) -> list[str]:
    """Resolve one visible page through the sole same-screen wrap contract."""
    return _article_fixed_english_lines(
        draw,
        " ".join(words[start:end]),
        font_size=int(font_size),
        enforce_word_limit=enforce_word_limit,
        boundary_penalty=lambda split, base=start: (
            # Page-boundary evidence still ranks a line break, but a hard
            # cross-page prohibition is not a hard same-screen prohibition.
            # Keep the penalty finite so the pixel-fitting wrap can choose a
            # natural line rather than forcing a smaller font or overflow.
            min(
                _article_line_boundary_penalty(cue, base + split),
                DISPLAY_PAGE_HIGH_CONFIDENCE_REVIEW_PENALTY,
            )
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


def _article_final_page_layout(
    draw: ImageDraw.ImageDraw,
    cue: Cue,
    words: Sequence[str],
    start: int,
    end: int,
    *,
    allow_legacy_fallback: bool = False,
) -> tuple[int, list[str]] | None:
    """Keep the preferred font whenever the page fits within two lines."""
    return _article_choose_page_layout_by_font(
        draw,
        lambda font_size: _article_same_screen_english_lines(
            draw,
            cue,
            words,
            start,
            end,
            font_size,
        ),
        font_sizes=(
            ARTICLE_SUBTITLE_EN_ALLOWED_SIZES
            if allow_legacy_fallback
            else ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES
        ),
    )


def _article_planning_final_page_layout(
    draw: ImageDraw.ImageDraw,
    cue: Cue,
    words: Sequence[str],
    start: int,
    end: int,
) -> tuple[int, list[str]] | None:
    """Use the same same-screen layout contract as the frozen renderer."""
    return _article_final_page_layout(
        draw,
        cue,
        words,
        start,
        end,
    )


def _article_choose_page_layout_by_font(
    draw: ImageDraw.ImageDraw,
    layout_for_font: Callable[[int], list[str]],
    *,
    font_sizes: Sequence[int] = ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES,
) -> tuple[int, list[str]] | None:
    """Keep 56px unless it is severely imbalanced and a smaller size is one line."""
    first: tuple[int, list[str]] | None = None
    for font_size in font_sizes:
        lines = layout_for_font(int(font_size))
        if not lines:
            continue
        candidate = (int(font_size), list(lines))
        if first is None:
            first = candidate
            if font_size != ARTICLE_SUBTITLE_EN_FONT_SIZE:
                return first
            if not _article_layout_has_severe_imbalance(draw, lines, font_size):
                return first
            # A severe 56px two-line imbalance is allowed to seek a complete
            # one-line layout at the next permitted size. A merely moderate
            # imbalance keeps the larger, more legible font.
            continue
        if first[0] == ARTICLE_SUBTITLE_EN_FONT_SIZE and len(lines) == 1:
            return candidate
    return first


def _article_candidate_fallback_tier(
    candidate: Mapping[str, object],
) -> int:
    """Order page candidates as strict, explicit review, then forced."""
    if candidate.get("review_boundary_candidate"):
        return 1
    if candidate.get("forced_continuation"):
        return 2
    return 0


def _finalize_article_same_screen_layout(
    cue: Cue,
    draw: ImageDraw.ImageDraw,
    plan: Mapping[str, object],
) -> dict:
    """Reflow frozen pages without changing their IDs, spans, or timing."""
    finalized = dict(plan)
    words = _article_boundary_words(cue)
    pages = [dict(page) for page in plan.get("pages") or []]
    page_fonts: list[int] = []
    for page in pages:
        start = int(page["word_start"])
        end = int(page["word_end"]) + 1
        previous_font_size = int(
            page.get("english_font_size") or ARTICLE_SUBTITLE_EN_FONT_SIZE
        )
        layout = _article_final_page_layout(
            draw,
            cue,
            words,
            start,
            end,
            allow_legacy_fallback=(
                previous_font_size in ARTICLE_SUBTITLE_EN_LEGACY_FALLBACK_SIZES
            ),
        )
        if layout is None:
            return finalized
        font_size, lines = layout
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
    words = _article_boundary_words(cue)
    timing = list(cue.word_timing or ())
    raw_pages = list(frozen_plan.get("pages") or [])
    try:
        first_word_id = int(timing[0]["word_id"])
        last_word_id = _article_timing_word_end(timing[-1])
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
        local_spans = _article_local_spans_for_global_ranges(
            timing,
            [(global_start, global_end)],
        )
        if local_spans is None:
            raise RenderStructuralOverflowError(
                [
                    {
                        "cue_index": cue.index,
                        "reason": "frozen_page_reflow_splits_display_span",
                    }
                ]
            )
        local_start, local_end_exclusive = local_spans[0]
        local_end = local_end_exclusive - 1
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
    max_page_count: int = ARTICLE_VISUAL_PAGE_MAX_PAGES,
) -> dict:
    """Freeze the English word pages before any Chinese page text is selected."""
    words = _article_boundary_words(cue)
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
                _article_same_screen_english_lines(
                    draw,
                    cue,
                    words,
                    start,
                    end,
                    font_size,
                    enforce_word_limit=paginated,
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
    automatic_floor_static_lines = list(
        span_layout(
            0,
            len(words),
            ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE,
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
    if (
        not base_static_lines
        and (
            len(words) >= ARTICLE_VISUAL_PAGE_REVIEW_WORDS
            or not automatic_floor_static_lines
        )
    ):
        # Long-pixel cues should try a natural 56px multi-page projection
        # before accepting a smaller one-page fallback.
        base_preferred_page_count = max(2, base_preferred_page_count)
    base_duration_ms = max(
        0,
        round((float(cue.end) - float(cue.start)) * 1000),
    )
    enumerate_high_pressure_alternatives = bool(
        not base_static_lines
        or len(words) > ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS
        or base_duration_ms > ARTICLE_PAGE_COMFORTABLE_MAX_DURATION_MS
    )

    def candidate_from_spans(
        spans: list[tuple[int, int]],
        page_count: int,
        forced_continuation: bool,
        review_boundary_candidate: bool = False,
        emergency_font_candidate: bool = False,
        manual_override_candidate: bool = False,
    ) -> tuple[dict | None, str]:
        if (
            page_count == 1
            and str(cue.zh or "").strip()
            and not _article_fixed_chinese_lines(draw, str(cue.zh))
        ):
            return None, "chinese_does_not_fit_fixed_font"
        # Candidate scoring must use the exact typography that the frozen
        # blueprint will publish. Planning feasibility was already checked by
        # ``_partition_article_english_pages``; using the later reflow result
        # here prevents a nominal 56/52px candidate from becoming 50px only
        # after whole-episode selection.
        page_layouts = [
            _article_final_page_layout(
                draw,
                cue,
                words,
                start,
                end,
                allow_legacy_fallback=emergency_font_candidate,
            )
            for start, end in spans
        ]
        if any(layout is None for layout in page_layouts):
            return None, "english_does_not_fit_fixed_font"
        page_font_sizes = [int(layout[0]) for layout in page_layouts if layout]
        english_layouts = [list(layout[1]) for layout in page_layouts if layout]
        selected_parent_font = min(page_font_sizes)
        boundaries, timing_reason = _schedule_article_page_boundaries(cue, spans)
        if boundaries is None:
            return None, timing_reason
        boundary_decisions = [
            (
                _article_forced_continuation_decision(cue, words, start)
                if forced_continuation
                else _article_display_boundary_decision(cue, start)
            )
            for start, _ in spans[1:]
        ]
        boundary_costs = []
        for start, _ in spans[1:]:
            cost = _article_page_break_score(
                cue,
                words,
                start,
                len(words) / page_count,
                cue.word_timing,
                allow_forced_continuation=forced_continuation,
                allow_review_boundary=review_boundary_candidate,
            )
            if cost is None and manual_override_candidate:
                # This path is only a review seed.  Keep the hard decision and
                # its issue codes in the page artifact, but use the existing
                # explicit-editor rank so a human can inspect the page map.
                cost = int(
                    _article_manual_override_break_rank(
                        cue,
                        words,
                        start,
                        len(words) / page_count,
                        cue.word_timing,
                    )[1]
                )
            boundary_costs.append(cost)
        if any(cost is None for cost in boundary_costs):
            return None, "hard_page_boundary"
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
        relaxed_raw_hard_count = sum(
            bool(decision.get("relaxed_raw_hard"))
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
            _article_page_span_balance_cost(
                draw,
                words,
                start,
                end,
                cue.word_timing,
                page_font_sizes[index],
                page_count,
            )
            for index, (start, end) in enumerate(spans)
        )
        pages = []
        line_balance_ratios = []
        line_balance_cost = 0.0
        for index, (start, end) in enumerate(spans):
            layout_lines = english_layouts[index]
            layout_font_size = page_font_sizes[index]
            layout_font = article_subtitle_en_font(layout_font_size, 600)
            measured_line_widths = [
                text_w(draw, line, layout_font) for line in layout_lines
            ]
            max_line_width = max(measured_line_widths, default=0)
            line_balance_ratio = 1.0
            if len(measured_line_widths) == 2 and max_line_width:
                line_balance_ratio = min(measured_line_widths) / max_line_width
                imbalance = max(
                    0.0,
                    ARTICLE_PAGE_TWO_LINE_BALANCE_FREE_RATIO - line_balance_ratio,
                )
                line_balance_cost += (
                    imbalance
                    * imbalance
                    * ARTICLE_PAGE_TWO_LINE_BALANCE_PENALTY
                )
            line_balance_ratios.append(round(line_balance_ratio, 6))
            pages.append(
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
                        _article_timing_word_end(cue.word_timing[end - 1])
                        if len(cue.word_timing) == len(words)
                        and cue.word_timing[end - 1].get("word_id") is not None
                        else None
                    ),
                    "start": boundaries[index],
                    "end": boundaries[index + 1],
                    "en_lines": layout_lines,
                    "english_font_size": layout_font_size,
                    "rendered_line_width": max_line_width,
                    "line_balance_ratio": round(line_balance_ratio, 6),
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
                        layout_lines,
                        layout_font_size,
                    ),
                    "line_wrap_review": bool(
                        _has_discouraged_caption_break(
                            " ".join(words[start:end]),
                            layout_lines,
                            boundary_penalty=lambda split, base=start: (
                                _article_line_boundary_penalty(cue, base + split)
                            ),
                        )
                    ),
                }
            )
        warnings = []
        last_word = (
            re.sub(r"[^A-Za-z']", "", words[-1]).lower() if words else ""
        )
        static_dangling_tail = bool(
            page_count == 1
            and last_word in LINE_BREAK_AVOID_AFTER_WORDS
            and not _caption_has_terminal_completion(words)
        )
        if (
            (page_count < base_preferred_page_count or static_dangling_tail)
            and not (
                page_count == 1 and _caption_has_terminal_completion(words)
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
            + line_balance_cost
            + soft_word_overflow * 300
            + font_reduction * DISPLAY_PAGE_FONT_STEP_PENALTY
            + (
                ARTICLE_PAGE_50PX_LAST_RESORT_PENALTY
                if selected_parent_font == ARTICLE_SUBTITLE_EN_MIN_SIZE
                else 0
            )
            + abs(page_count - base_preferred_page_count)
            * DISPLAY_PAGE_COUNT_DEVIATION_PENALTY
            + max(0, page_count - 1) * DISPLAY_PAGE_TRANSITION_PENALTY
        )
        return (
            {
                "plan": plan,
                "page_count": page_count,
                "font_reduction": font_reduction,
                "forced_continuation": forced_continuation,
                "review_boundary_candidate": review_boundary_candidate,
                "manual_override_candidate": manual_override_candidate,
                "emergency_font_candidate": emergency_font_candidate,
                "risk_score": risk_score,
                "high_risk_count": high_risk_count,
                "medium_risk_count": medium_risk_count,
                "low_risk_count": low_risk_count,
                "supported_restart_count": supported_restart_count,
                "relaxed_raw_hard_count": relaxed_raw_hard_count,
                "severe_risk_count": sum(
                    risk >= 3 for risk in boundary_risks
                ),
                "tight_complete_phrase_count": tight_complete_phrase_count,
                "review_count": review_count,
                "incomplete_review_count": sum(
                    decision.get("classification") == "review"
                    and not _article_secondary_review_boundary_is_complete(page)
                    for decision, page in zip(boundary_decisions, pages[1:])
                ),
                "quality_cost": round(quality_cost),
                "page_pressures": tuple(
                    _article_display_page_pressure(page) for page in pages
                ),
                "line_balance_ratios": tuple(line_balance_ratios),
                "line_wrap_review_count": sum(
                    bool(page.get("line_wrap_review")) for page in pages
                ),
            },
            "",
        )

    def collect_candidates(
        font_sizes: Sequence[int],
        *,
        emergency_font_candidate: bool,
    ) -> None:
        manual_fallback_candidates: list[dict] = []
        bounded_max_page_count = min(max(1, int(max_page_count)), len(words))
        for font_size in font_sizes:
            for page_count in range(1, bounded_max_page_count + 1):
                attempt_diagnostics: set[str] = set()
                strict_partitions = _partition_article_english_pages(
                    draw,
                    cue,
                    words,
                    page_count,
                    cue.word_timing,
                    font_size,
                    diagnostics=attempt_diagnostics,
                    span_layout=span_layout,
                    span_balance=span_balance,
                    max_candidates=ARTICLE_PAGE_CANDIDATE_FRONTIER_LIMIT,
                )
                partition_modes = []
                if strict_partitions:
                    partition_modes.append((strict_partitions, False, False, False))
                if page_count > 1 and (
                    not strict_partitions or enumerate_high_pressure_alternatives
                ):
                    forced_partitions = _partition_article_english_pages(
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
                        max_candidates=ARTICLE_PAGE_CANDIDATE_FRONTIER_LIMIT,
                    )
                    if forced_partitions:
                        partition_modes.append((forced_partitions, True, False, False))
                    review_partitions = _partition_article_english_pages(
                        draw,
                        cue,
                        words,
                        page_count,
                        cue.word_timing,
                        font_size,
                        diagnostics=attempt_diagnostics,
                        allow_review_boundary=True,
                        span_layout=span_layout,
                        span_balance=span_balance,
                        max_candidates=ARTICLE_PAGE_CANDIDATE_FRONTIER_LIMIT,
                    )
                    if review_partitions:
                        partition_modes.append((review_partitions, False, True, False))
                if (
                    not partition_modes
                    and _return_candidates
                    and page_count > 1
                    and not candidates
                ):
                    manual_partitions = _partition_article_english_pages(
                        draw,
                        cue,
                        words,
                        page_count,
                        cue.word_timing,
                        font_size,
                        diagnostics=attempt_diagnostics,
                        allow_manual_override=True,
                        prefer_punctuation_for_manual_review=True,
                        span_layout=span_layout,
                        span_balance=span_balance,
                        max_candidates=ARTICLE_PAGE_CANDIDATE_FRONTIER_LIMIT,
                    )
                    if manual_partitions:
                        partition_modes.append((manual_partitions, False, False, True))
                if not partition_modes:
                    failure_reasons.update(
                        attempt_diagnostics
                        or {"no_complete_legal_page_partition"}
                    )
                    continue
                for (
                    partitions,
                    forced_continuation,
                    review_boundary_candidate,
                    manual_override_candidate,
                ) in (
                    partition_modes
                ):
                    for spans in partitions:
                        candidate, failure_reason = candidate_from_spans(
                            spans,
                            page_count,
                            forced_continuation,
                            review_boundary_candidate,
                            emergency_font_candidate,
                            manual_override_candidate,
                        )
                        if candidate is None:
                            failure_reasons.add(failure_reason)
                            continue
                        if manual_override_candidate:
                            manual_fallback_candidates.append(candidate)
                        else:
                            candidates.append(candidate)

        return manual_fallback_candidates

    manual_fallback_candidates = collect_candidates(
        ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES,
        emergency_font_candidate=False,
    )
    all_candidates = list(candidates)
    complete_normal_font_candidates = [
        candidate
        for candidate in candidates
        if not int(candidate.get("incomplete_review_count") or 0)
        and int(candidate.get("relaxed_raw_hard_count") or 0) <= 1
    ]
    fallback_review_candidate = None
    if (
        (candidates and not complete_normal_font_candidates)
        or (not candidates and not automatic_floor_static_lines)
    ):
        failure_reasons.add("no_complete_normal_font_page_partition")
        if _return_candidates and candidates:
            # Keep the best displayable review candidate available to the
            # partial checkpoint.  It is never a formal success: the caller
            # records the same structural error and keeps publication blocked.
            fallback_pool = [
                candidate
                for candidate in candidates
                if int(candidate.get("incomplete_review_count") or 0) == 0
            ]
            if fallback_pool:
                fallback_review_candidate = min(
                    fallback_pool,
                key=lambda candidate: (
                    int(candidate.get("incomplete_review_count") or 0),
                    _article_candidate_fallback_tier(candidate),
                    int(candidate.get("relaxed_raw_hard_count") or 0),
                    int(candidate.get("severe_risk_count") or 0),
                    int(candidate.get("high_risk_count") or 0),
                    int(candidate.get("medium_risk_count") or 0),
                    float(candidate.get("quality_cost") or 0.0),
                    tuple(
                        int(page.get("word_end") or 0)
                        for page in candidate.get("plan", {}).get("pages") or []
                    ),
                )
                )
                fallback_review_candidate = dict(fallback_review_candidate)
                fallback_review_candidate["fallback_review_candidate"] = True
    candidates = complete_normal_font_candidates

    if fallback_review_candidate is not None:
        return {
            "status": "candidate_bundle",
            "candidates": [fallback_review_candidate],
            "shadow_candidates": all_candidates,
            "preferred_page_count": base_preferred_page_count,
            "candidate_mode": "review_fallback",
            "fallback_review": True,
            "fallback_errors": [
                {
                    "cue_index": cue.index,
                    "reason": "no_complete_normal_font_page_partition",
                }
            ],
        }

    if candidates:
        deduplicated: dict[tuple, dict] = {}
        for candidate in candidates:
            pages = candidate.get("plan", {}).get("pages") or []
            signature = tuple(
                (
                    int(page.get("word_start") or 0),
                    int(page.get("word_end") or 0),
                    int(page.get("english_font_size") or 0),
                    tuple(page.get("en_lines") or []),
                )
                for page in pages
            )
            existing = deduplicated.get(signature)
            rank = (
                int(candidate.get("relaxed_raw_hard_count") or 0),
                _article_candidate_fallback_tier(candidate),
                int(candidate.get("severe_risk_count") or 0),
                int(candidate.get("high_risk_count") or 0),
                int(candidate.get("medium_risk_count") or 0),
                float(candidate.get("quality_cost") or 0.0),
            )
            if existing is None:
                deduplicated[signature] = candidate
                continue
            existing_rank = (
                int(existing.get("relaxed_raw_hard_count") or 0),
                _article_candidate_fallback_tier(existing),
                int(existing.get("severe_risk_count") or 0),
                int(existing.get("high_risk_count") or 0),
                int(existing.get("medium_risk_count") or 0),
                float(existing.get("quality_cost") or 0.0),
            )
            if rank < existing_rank:
                deduplicated[signature] = candidate
        bounded_candidates = []
        candidate_groups = sorted(
            {
                (
                    int(candidate.get("page_count") or 0),
                    _article_candidate_fallback_tier(candidate),
                )
                for candidate in deduplicated.values()
            }
        )
        for page_count, fallback_tier in candidate_groups:
            same_count = [
                candidate
                for candidate in deduplicated.values()
                if int(candidate.get("page_count") or 0) == page_count
                and _article_candidate_fallback_tier(candidate) == fallback_tier
            ]
            same_count.sort(
                key=lambda candidate: (
                    int(candidate.get("relaxed_raw_hard_count") or 0),
                    _article_candidate_fallback_tier(candidate),
                    int(candidate.get("severe_risk_count") or 0),
                    int(candidate.get("high_risk_count") or 0),
                    int(candidate.get("medium_risk_count") or 0),
                    float(candidate.get("quality_cost") or 0.0),
                    tuple(
                        int(page.get("word_end") or 0)
                        for page in candidate.get("plan", {}).get("pages") or []
                    ),
                )
            )
            bounded_candidates.extend(
                same_count[:ARTICLE_PAGE_CANDIDATE_FRONTIER_LIMIT]
            )
        candidates = bounded_candidates
    if candidates:
        minimum_relaxed_raw_hard_count = min(
            int(candidate.get("relaxed_raw_hard_count") or 0)
            for candidate in candidates
        )
        eligible_candidates = [
            candidate
            for candidate in candidates
            if int(candidate.get("relaxed_raw_hard_count") or 0)
            == minimum_relaxed_raw_hard_count
        ]
        safe_baseline_page_count = min(
            (
                int(candidate.get("page_count") or 0)
                for candidate in eligible_candidates
                if int(candidate.get("page_count") or 0) > 0
            ),
            default=0,
        )
        safe_baseline_candidates = [
            candidate
            for candidate in eligible_candidates
            if int(candidate.get("page_count") or 0) == safe_baseline_page_count
        ]
        safe_plan_requires_three_lines = bool(
            minimum_relaxed_raw_hard_count == 0
            and safe_baseline_candidates
            and all(
                any(
                    len(list(page.get("en_lines") or [])) > 2
                    for page in candidate.get("plan", {}).get("pages") or []
                )
                for candidate in safe_baseline_candidates
            )
        )
        if safe_plan_requires_three_lines:
            # A verified complete continuation may replace the emergency
            # three-line layout, but it cannot compete with any safe one- or
            # two-line plan. Ordinary pause-relaxed hard boundaries stay out.
            eligible_candidates.extend(
                candidate
                for candidate in candidates
                if int(candidate.get("relaxed_raw_hard_count") or 0) > 0
                and bool(candidate.get("forced_continuation"))
                and all(
                    len(list(page.get("en_lines") or [])) <= 2
                    for page in candidate.get("plan", {}).get("pages") or []
                )
            )
        complete_phrase_fallbacks = [
            candidate
            for candidate in candidates
            if int(candidate.get("relaxed_raw_hard_count") or 0)
            > minimum_relaxed_raw_hard_count
            and (
                bool(candidate.get("forced_continuation"))
                or any(
                    bool(
                        (page.get("boundary_before") or {}).get(
                            "complete_title_restart"
                        )
                        or (page.get("boundary_before") or {}).get(
                            "complete_prepositional_continuation"
                        )
                    )
                    for page in candidate.get("plan", {}).get("pages", [])[1:]
                )
            )
            and not int(candidate.get("incomplete_review_count") or 0)
            and all(
                str((page.get("boundary_before") or {}).get("classification") or "allow")
                == "allow"
                or bool(
                    (page.get("boundary_before") or {}).get(
                        "forced_complete_to_phrase"
                    )
                    or (page.get("boundary_before") or {}).get(
                        "forced_complete_predicate_phrase"
                    )
                    or (page.get("boundary_before") or {}).get(
                        "complete_title_restart"
                    )
                    or (page.get("boundary_before") or {}).get(
                        "complete_prepositional_continuation"
                    )
                )
                for page in candidate.get("plan", {}).get("pages", [])[1:]
            )
        ]
        eligible_signatures = {id(candidate) for candidate in eligible_candidates}
        eligible_candidates.extend(
            candidate
            for candidate in complete_phrase_fallbacks
            if id(candidate) not in eligible_signatures
        )
        # Page count is a reading-load decision. Break rewards and penalties
        # are deliberately absent here; they select a boundary only after the
        # number of pages is fixed.
        strict_candidates = [
            candidate
            for candidate in eligible_candidates
            if _article_candidate_fallback_tier(candidate) == 0
        ]
        candidate_mode = (
            "relaxed_raw_hard"
            if minimum_relaxed_raw_hard_count
            else "strict"
            if strict_candidates
            else (
                "review_boundary"
                if any(
                    candidate.get("review_boundary_candidate")
                    for candidate in eligible_candidates
                )
                else "forced_continuation"
            )
        )
        selection_pool = strict_candidates or eligible_candidates
        # Diagnostic callers may compare production selection with the wider
        # bounded frontier.  These candidates have already passed word-cover,
        # timing, layout, and minimum raw-hard-risk filtering; exposing them
        # does not grant them production authority.
        shadow_candidates = list(eligible_candidates)
        secondary_review_candidates = _article_high_pressure_review_candidates(
            eligible_candidates,
            total_word_count=len(words),
        )
        if secondary_review_candidates:
            selection_pool = secondary_review_candidates

        def selected_page_count_for(
            candidate_pool: Sequence[Mapping[str, object]],
        ) -> tuple[dict[int, list[Mapping[str, object]]], int]:
            by_page_count = {
                page_count: [
                    candidate
                    for candidate in candidate_pool
                    if int(candidate.get("page_count") or 0) == page_count
                ]
                for page_count in sorted(
                    {
                        int(candidate.get("page_count") or 0)
                        for candidate in candidate_pool
                    }
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
            preferred_candidates = by_page_count.get(
                base_preferred_page_count,
                [],
            )
            static_candidates = by_page_count.get(1, [])
            best_static_font_reduction = min(
                (
                    int(candidate.get("font_reduction") or 0)
                    for candidate in static_candidates
                ),
                default=None,
            )
            preferred_is_low_confidence_or_supported_only = bool(
                preferred_candidates
                and all(
                    int(candidate.get("review_count") or 0)
                    == int(candidate.get("low_risk_count") or 0)
                    + int(candidate.get("supported_restart_count") or 0)
                    for candidate in preferred_candidates
                )
            )
            preferred_requires_structural_fallback = bool(
                preferred_candidates
                and all(
                    any(
                        (
                            len(str(page.get("en") or "").split())
                            < ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
                            and (
                                _article_candidate_fallback_tier(candidate) > 0
                                or int(candidate.get("review_count") or 0) > 0
                            )
                        )
                        or bool(
                            _article_nonoverridable_atomic_page_boundary_issues(
                                page.get("boundary_before") or {}
                            )
                        )
                        for page in candidate.get("plan", {}).get("pages") or []
                    )
                    or (
                        int(candidate.get("incomplete_review_count") or 0) > 0
                        and best_static_font_reduction is not None
                        and best_static_font_reduction
                        <= ARTICLE_PAGE_LOW_CONFIDENCE_FONT_REDUCTION_LIMIT
                    )
                    for candidate in preferred_candidates
                )
            )
            if (
                not secondary_review_candidates
                and base_preferred_page_count > 1
                and preferred_candidates
                and static_candidates
                and (
                    preferred_requires_structural_fallback
                    or all(
                        int(candidate.get("severe_risk_count") or 0)
                        or int(candidate.get("tight_complete_phrase_count") or 0)
                        for candidate in preferred_candidates
                    )
                    and (
                        not preferred_is_low_confidence_or_supported_only
                        or best_static_font_reduction
                        <= ARTICLE_PAGE_LOW_CONFIDENCE_FONT_REDUCTION_LIMIT
                    )
                )
            ):
                # Avoid structurally uncertain page turns. A low-confidence
                # turn may not be used to manufacture a new below-floor page;
                # if 56/54/52px cannot produce a complete plan, the parent is
                # handed to the manual editable-seed path.
                selected_page_count = 1
            return by_page_count, selected_page_count

        if _return_candidates:
            if not secondary_review_candidates:
                safe_preferred_font_candidates = [
                    candidate
                    for candidate in selection_pool
                    if candidate["plan"]["font_size"]["english"]
                    == ARTICLE_SUBTITLE_EN_FONT_SIZE
                    and _article_candidate_fallback_tier(candidate) == 0
                    and not candidate["severe_risk_count"]
                    and not candidate["medium_risk_count"]
                ]
                if safe_preferred_font_candidates:
                    selection_pool = safe_preferred_font_candidates
            by_page_count, selected_page_count = selected_page_count_for(
                selection_pool
            )
            selection_pool = list(by_page_count[selected_page_count])
            return {
                "status": "candidate_bundle",
                "candidates": selection_pool,
                "shadow_candidates": shadow_candidates,
                "preferred_page_count": base_preferred_page_count,
                "candidate_mode": candidate_mode,
            }
        by_page_count, selected_page_count = selected_page_count_for(
            selection_pool
        )

        selected = min(
            by_page_count[selected_page_count],
            key=lambda candidate: (
                candidate["risk_score"],
                candidate["high_risk_count"],
                candidate["medium_risk_count"],
                candidate["low_risk_count"],
                -int(candidate.get("supported_restart_count") or 0),
                int(candidate.get("line_wrap_review_count") or 0),
                candidate["font_reduction"],
                candidate["quality_cost"],
            ),
        )
        selected = _select_article_dominant_readability_candidate(
            cue,
            selected,
            shadow_candidates,
        )
        selected = _promote_article_material_readability_candidate(
            selected,
            shadow_candidates,
        )
        selected["plan"]["page_count_decision"] = {
            "preferred": base_preferred_page_count,
            "selected": int(selected.get("page_count") or selected_page_count),
            "candidate_mode": (
                candidate_mode
            ),
            "basis": (
                "material_readability_non_regression"
                if selected.get("material_readability_promoted")
                else (
                    "dominant_cross_page_count_candidate"
                    if selected.get("dominant_readability_promoted")
                    else "pixel_word_chinese_duration_load"
                )
            ),
        }
        return _finalize_article_same_screen_layout(
            cue,
            draw,
            selected["plan"],
        )
    reason_priority = (
        "missing_or_mismatched_word_ledger",
        "no_complete_normal_font_page_partition",
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
    width_load = float(
        page.get("rendered_line_width") or page.get("en_width") or 0.0
    ) / max(
        float(acx(ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH)),
        1.0,
    )
    spoken_load = (word_count / duration) / 3.2
    return round(max(word_load, width_load, spoken_load), 6)


def _article_high_pressure_review_candidates(
    candidates: Sequence[Mapping[str, object]],
    *,
    total_word_count: int,
) -> list[dict]:
    """Promote complete normal-font expansions over a dense baseline."""
    available_page_counts = [
        int(candidate.get("page_count") or 0)
        for candidate in candidates
        if int(candidate.get("page_count") or 0) > 0
    ]
    if not available_page_counts:
        return []
    baseline_page_count = min(available_page_counts)
    baseline_candidates = [
        candidate
        for candidate in candidates
        if int(candidate.get("page_count") or 0) == baseline_page_count
    ]
    if not baseline_candidates:
        return []
    baseline_is_high_pressure = any(
        any(
            len(str(page.get("en") or "").split())
            > ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS
            or int(
                page.get("english_font_size")
                or candidate.get("plan", {}).get("font_size", {}).get(
                    "english"
                )
                or 0
            )
            < ARTICLE_SUBTITLE_EN_FONT_SIZE
            or (
                float(page.get("end") or 0.0)
                - float(page.get("start") or 0.0)
            )
            * 1000
            > ARTICLE_PAGE_COMFORTABLE_MAX_DURATION_MS
            for page in candidate.get("plan", {}).get("pages") or []
        )
        for candidate in baseline_candidates
    )
    if not baseline_is_high_pressure:
        return []

    baseline_font_floor = max(
        (
            min(
                (
                    int(
                        page.get("english_font_size")
                        or candidate.get("plan", {}).get("font_size", {}).get(
                            "english"
                        )
                        or 0
                    )
                    for page in candidate.get("plan", {}).get("pages") or []
                ),
                default=0,
            )
            for candidate in baseline_candidates
        ),
        default=0,
    )
    baseline_uses_three_lines = any(
        any(
            len(list(page.get("en_lines") or [])) > 2
            for page in candidate.get("plan", {}).get("pages") or []
        )
        for candidate in baseline_candidates
    )

    promoted: list[dict] = []
    for candidate in candidates:
        plan = candidate.get("plan") or {}
        pages = list(plan.get("pages") or [])
        candidate_font_floor = min(
            (
                int(
                    page.get("english_font_size")
                    or plan.get("font_size", {}).get("english")
                    or 0
                )
                for page in pages
            ),
            default=0,
        )
        restores_preferred_font = bool(
            candidate_font_floor == ARTICLE_SUBTITLE_EN_FONT_SIZE
            and (
                baseline_font_floor < ARTICLE_SUBTITLE_EN_FONT_SIZE
                or total_word_count > ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS
            )
        )
        restores_automatic_floor = bool(
            baseline_font_floor < ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE
            and candidate_font_floor >= ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE
        )
        removes_three_line_fallback = bool(
            baseline_uses_three_lines
            and pages
            and all(len(list(page.get("en_lines") or [])) <= 2 for page in pages)
            and candidate_font_floor >= baseline_font_floor
        )
        if (
            int(candidate.get("page_count") or 0) <= baseline_page_count
            or not (
                restores_preferred_font
                or restores_automatic_floor
                or removes_three_line_fallback
            )
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
        if (
            not baseline_uses_three_lines
            and any(
                _article_secondary_boundary_needs_three_line_escape(page)
                for page in pages[1:]
            )
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
    preferred_font_promoted = [
        candidate
        for candidate in promoted
        if int(
            candidate.get("plan", {}).get("font_size", {}).get("english") or 0
        )
        == ARTICLE_SUBTITLE_EN_FONT_SIZE
    ]
    return preferred_font_promoted or promoted


def _article_nonoverridable_atomic_page_boundary_issues(
    decision: Mapping[str, object],
) -> set[str]:
    """Return lexical issues that acoustic restart evidence cannot relax.

    A display transition must never bisect a written numeric phrase such as
    ``1.4 billion``. Unlike a clause restart, no pause can make either visible
    half independently meaningful.
    """
    issue_codes = {
        str(issue or "") for issue in decision.get("issue_codes") or []
    }
    atomic_issues = issue_codes & ARTICLE_PAGE_ATOMIC_BOUNDARY_ISSUES
    if (
        decision.get("balanced_predicate_restart")
        and int(decision.get("pause_ms") or 0)
        >= ARTICLE_PAGE_BALANCED_CLAUSE_REVIEW_MS
    ):
        atomic_issues -= {
            "subject_predicate_split",
            "subject_finite_verb_split",
        }
    if decision.get("complete_prepositional_continuation"):
        atomic_issues -= {
            "atomic_of_complement_split",
            "dependency_phrase_entrance_split",
            "object_attached_modifier_split",
            "predicate_attached_continuation_split",
        }
    if decision.get("complete_object_continuation"):
        atomic_issues -= {
            "short_verb_complement_split",
            "short_verb_object_split",
            "verb_complement_split",
        }
    if decision.get("forced_complete_predicate_phrase"):
        atomic_issues -= {
            "predicate_attached_continuation_split",
            "predicate_complement_chain_split",
            "verb_adverb_preposition_split",
        }
    return atomic_issues


def _article_secondary_review_boundary_is_complete(
    right_page: Mapping[str, object],
) -> bool:
    decision = right_page.get("boundary_before") or {}
    classification = str(decision.get("classification") or "")
    if classification == "reject":
        return False
    issue_codes = {
        str(issue or "") for issue in decision.get("issue_codes") or []
    }
    words = str(right_page.get("en") or "").split()
    if not words:
        return False
    first_word = re.sub(r"[^A-Za-z]+", "", words[0]).casefold()
    complete_from_gerund = _article_complete_from_gerund_restart(right_page)
    complete_from_nominal = _article_complete_from_nominal_restart(right_page)
    complete_to_infinitive = _article_complete_to_infinitive_restart(right_page)
    complete_participial_restart = _article_complete_participial_restart(
        right_page
    )
    complete_temporal_range_restart = _article_complete_temporal_range_restart(
        right_page
    )
    complete_prepositional_continuation = bool(
        decision.get("complete_prepositional_continuation")
        and _article_complete_prepositional_continuation_shape(
            words,
            0,
            issue_codes,
        )
    )
    complete_object_continuation = bool(
        decision.get("complete_object_continuation")
        and _article_complete_object_continuation_shape(
            words,
            0,
            issue_codes,
        )
    )
    complete_temporal_adjunct = bool(
        first_word in ARTICLE_PAGE_OPTIONAL_TEMPORAL_ADJUNCT_START_WORDS
        and issue_codes
        and issue_codes
        <= {
            "dependency_phrase_entrance_split",
            "forced_complete_continuation_page_split",
            "object_attached_modifier_split",
            "predicate_attached_continuation_split",
        }
        and len(words) >= ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
        and _caption_has_terminal_completion(words)
    )
    complete_forced_predicate = bool(
        decision.get("forced_subject_predicate")
        and len(words) >= ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
        and _caption_has_terminal_completion(words)
    )
    atomic_issues = _article_nonoverridable_atomic_page_boundary_issues(
        decision
    )
    if complete_forced_predicate:
        atomic_issues -= {
            "subject_finite_verb_split",
            "subject_predicate_split",
        }
    if complete_participial_restart:
        atomic_issues.discard("post_noun_participial_modifier_split")
    if complete_temporal_adjunct:
        atomic_issues -= {
            "dependency_phrase_entrance_split",
            "object_attached_modifier_split",
            "predicate_attached_continuation_split",
        }
    if decision.get("complete_title_restart"):
        atomic_issues -= {
            "subject_finite_verb_split",
            "subject_predicate_split",
        }
    if atomic_issues:
        return False
    if issue_codes & {
        "clause_introducer_split",
        "object_attached_modifier_split",
        "post_noun_participial_modifier_split",
        "verb_preposition_complement_split",
    } and not (
        complete_from_gerund
        or complete_from_nominal
        or complete_to_infinitive
        or complete_participial_restart
        or complete_temporal_adjunct
        or complete_prepositional_continuation
    ):
        return False
    # Strictly allowed boundaries have already passed the page-level syntax
    # contract.  Only review boundaries need additional restart evidence.
    if classification == "allow":
        return True
    return bool(
        decision.get("strong_pause_evidence")
        and int(decision.get("pause_ms") or 0)
        >= ARTICLE_PAGE_SECONDARY_REVIEW_STRONG_PAUSE_MS
        or decision.get("complete_page_clause_start")
        or decision.get("balanced_predicate_restart")
        or decision.get("punctuated_coordinated_gerund_restart")
        or decision.get("open_parent_coordinated_restart")
        or decision.get("open_parent_coordinated_gerund_restart")
        or complete_prepositional_continuation
        or complete_object_continuation
        or complete_from_gerund
        or complete_from_nominal
        or complete_to_infinitive
        or decision.get("forced_complete_to_phrase")
        or decision.get("forced_complete_predicate_phrase")
        or complete_forced_predicate
        or complete_participial_restart
        or complete_temporal_adjunct
        or complete_temporal_range_restart
        or decision.get("complete_title_restart")
        or first_word in {"that", "who", "which"}
    )


def _article_complete_from_gerund_restart(
    right_page: Mapping[str, object],
) -> bool:
    """Recognize a complete preposition-plus-gerund continuation page."""
    decision = right_page.get("boundary_before") or {}
    words = str(right_page.get("en") or "").split()
    if len(words) < 2:
        return False
    first_word = re.sub(r"[^A-Za-z]+", "", words[0]).casefold()
    second_word = re.sub(r"[^A-Za-z]+", "", words[1]).casefold()
    return bool(
        decision.get("tight_complete_phrase_start")
        and first_word in {"by", "from", "into"}
        and second_word.endswith("ing")
    )


def _article_complete_from_nominal_restart(
    right_page: Mapping[str, object],
) -> bool:
    """Keep a complete visible ``from/into + noun phrase`` page eligible."""
    decision = right_page.get("boundary_before") or {}
    words = str(right_page.get("en") or "").split()
    if len(words) < ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS:
        return False
    first_word = re.sub(r"[^A-Za-z]+", "", words[0]).casefold()
    second_word = re.sub(r"[^A-Za-z]+", "", words[1]).casefold()
    return bool(
        decision.get("tight_complete_phrase_start")
        and first_word in {"from", "into"}
        and not second_word.endswith("ing")
        and _caption_has_terminal_completion(words)
    )


def _article_complete_to_infinitive_restart(
    right_page: Mapping[str, object],
) -> bool:
    """Allow a full visual ``to + verb`` page, not an attached noun phrase."""
    decision = right_page.get("boundary_before") or {}
    issue_codes = set(decision.get("issue_codes") or [])
    words = str(right_page.get("en") or "").split()
    if len(words) < ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS:
        return False
    first_word = re.sub(r"[^A-Za-z]+", "", words[0]).casefold()
    second_word = re.sub(r"[^A-Za-z']+", "", words[1]).casefold()
    return bool(
        decision.get("tight_complete_phrase_start")
        and issue_codes == {"unsupported_tight_page_transition"}
        and first_word == "to"
        and second_word
        and second_word not in ARTICLE_PAGE_OBJECT_DETERMINERS
        and not second_word.endswith("'s")
        and _caption_has_terminal_completion(words)
    )


def _article_complete_participial_restart(
    right_page: Mapping[str, object],
) -> bool:
    """Allow a complete visible ``growing ...`` continuation for review."""
    decision = right_page.get("boundary_before") or {}
    issue_codes = {
        str(issue or "") for issue in decision.get("issue_codes") or []
    }
    words = str(right_page.get("en") or "").split()
    compatible_participial_issues = (
        {"post_noun_participial_modifier_split"},
        {
            "dependency_phrase_entrance_split",
            "post_noun_participial_modifier_split",
        },
        {"unsupported_tight_page_transition"},
    )
    if (
        len(words) < ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
        or issue_codes not in compatible_participial_issues
    ):
        return False
    first_word = re.sub(r"[^A-Za-z]+", "", words[0]).casefold()
    last_word = re.sub(r"[^A-Za-z]+", "", words[-1]).casefold()
    return bool(
        first_word.endswith(("ed", "ing"))
        and (
            _caption_has_terminal_completion(words)
            or (last_word.endswith("s") and not last_word.endswith("ss"))
        )
    )


def _article_complete_temporal_range_restart(
    right_page: Mapping[str, object],
) -> bool:
    """Recognize a complete ``this year to ...`` range continuation."""
    decision = right_page.get("boundary_before") or {}
    if set(decision.get("issue_codes") or []) != {
        "unsupported_tight_page_transition"
    }:
        return False
    words = str(right_page.get("en") or "").split()
    normalized = [
        re.sub(r"[^A-Za-z0-9.]+", "", word).casefold()
        for word in words
    ]
    if (
        len(normalized) < ARTICLE_VISUAL_PAGE_MIN_WORDS
        or not _caption_has_terminal_completion(words)
        or normalized[0] not in {"last", "next", "this"}
        or normalized[1]
        not in {"day", "decade", "month", "quarter", "week", "year"}
        or "to" not in normalized[2:]
    ):
        return False
    to_index = normalized.index("to", 2)
    return any(
        re.match(r"^\d", word or "") for word in normalized[to_index + 1 :]
    )


def _article_secondary_boundary_needs_three_line_escape(
    right_page: Mapping[str, object],
) -> bool:
    """Keep unsupported tight phrase restarts as a three-line last resort."""
    decision = right_page.get("boundary_before") or {}
    if (
        str(decision.get("classification") or "") == "allow"
        or not decision.get("tight_complete_phrase_start")
        or _article_complete_from_gerund_restart(right_page)
        or _article_complete_to_infinitive_restart(right_page)
        or decision.get("forced_complete_predicate_phrase")
    ):
        return False
    words = str(right_page.get("en") or "").split()
    if not words:
        return True
    first_word = re.sub(r"[^A-Za-z]+", "", words[0]).casefold()
    return not bool(
        decision.get("complete_page_clause_start")
        or (
            decision.get("strong_pause_evidence")
            and int(decision.get("pause_ms") or 0)
            >= ARTICLE_PAGE_SECONDARY_REVIEW_STRONG_PAUSE_MS
        )
        or first_word in {"that", "who", "which"}
    )


def _article_dense_page_pair_cost(left: float, right: float) -> float:
    shared_overload = max(0.0, min(float(left), float(right)) - 0.95)
    return shared_overload * shared_overload * 6_000


def _article_candidate_page_signature(
    candidate: Mapping[str, object],
    page_index: int,
) -> tuple[float, int, int]:
    """Return renderer-only pressure, font, and line count for one page."""
    plan = candidate.get("plan") or {}
    pages = list(plan.get("pages") or [])
    if not pages or not -len(pages) <= page_index < len(pages):
        return 0.0, 0, 0
    normalized_index = page_index % len(pages)
    page = pages[normalized_index]
    pressures = tuple(float(value) for value in candidate.get("page_pressures") or ())
    pressure = (
        pressures[normalized_index]
        if normalized_index < len(pressures)
        else _article_display_page_pressure(page)
    )
    font_size = int(
        page.get("english_font_size")
        or plan.get("font_size", {}).get("english")
        or 0
    )
    lines = [
        str(line).strip()
        for line in (
            page.get("en_lines")
            or page.get("english_lines")
            or []
        )
        if str(line).strip()
    ]
    return pressure, font_size, len(lines)


def _article_visual_page_transition_cost(
    left_candidate: Mapping[str, object],
    left_page_index: int,
    right_candidate: Mapping[str, object],
    right_page_index: int,
    *,
    include_typography: bool = True,
) -> float:
    """Downrank abrupt layout changes only after both pages are already valid."""
    left_pressure, left_font, left_lines = _article_candidate_page_signature(
        left_candidate,
        left_page_index,
    )
    right_pressure, right_font, right_lines = _article_candidate_page_signature(
        right_candidate,
        right_page_index,
    )
    pressure_delta = max(
        0.0,
        abs(left_pressure - right_pressure)
        - ARTICLE_PAGE_PRESSURE_TRANSITION_FREE_DELTA,
    )
    cost = _article_dense_page_pair_cost(left_pressure, right_pressure)
    cost += (
        pressure_delta
        * pressure_delta
        * ARTICLE_PAGE_PRESSURE_TRANSITION_PENALTY
    )
    if include_typography and left_font and right_font:
        cost += (
            abs(left_font - right_font)
            * ARTICLE_PAGE_FONT_TRANSITION_PENALTY
        )
    if include_typography and left_lines and right_lines:
        cost += (
            abs(left_lines - right_lines)
            * ARTICLE_PAGE_LINE_COUNT_TRANSITION_PENALTY
        )
    return cost


def _article_candidate_sequence_cost(candidate: Mapping[str, object]) -> float:
    pressures = tuple(float(value) for value in candidate.get("page_pressures") or ())
    overload_cost = sum(max(0.0, value - 1.0) ** 2 * 3_000 for value in pressures)
    incomplete_review_cost = (
        int(candidate.get("incomplete_review_count") or 0)
        * ARTICLE_PAGE_INCOMPLETE_REVIEW_PENALTY
    )
    internal_transition_cost = sum(
        _article_visual_page_transition_cost(
            candidate,
            index,
            candidate,
            index + 1,
            include_typography=False,
        )
        for index in range(max(0, len(pressures) - 1))
    )
    return (
        float(candidate.get("quality_cost") or 0.0)
        + overload_cost
        + incomplete_review_cost
        + internal_transition_cost
    )


def _article_candidate_readability_metrics(
    candidate: Mapping[str, object],
) -> dict[str, float | int]:
    """Summarize objective display load for cross-page-count comparison."""
    pages = list((candidate.get("plan") or {}).get("pages") or [])
    word_counts = [len(str(page.get("en") or "").split()) for page in pages]
    font_sizes = [
        int(
            page.get("english_font_size")
            or candidate.get("plan", {}).get("font_size", {}).get("english")
            or 0
        )
        for page in pages
    ]
    pressures = [_article_display_page_pressure(page) for page in pages]
    return {
        "page_count": len(pages),
        "min_font": min(font_sizes, default=0),
        "max_words": max(word_counts, default=0),
        "min_words": min(word_counts, default=0),
        "max_pressure": max(pressures, default=0.0),
        "low_font_pages": sum(
            font_size < ARTICLE_SUBTITLE_EN_FONT_SIZE
            for font_size in font_sizes
        ),
        "over_16_pages": sum(
            word_count > ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS
            for word_count in word_counts
        ),
        "three_line_pages": sum(
            len(list(page.get("en_lines") or [])) > 2 for page in pages
        ),
        "line_wrap_review_count": int(
            candidate.get("line_wrap_review_count") or 0
        ),
        "supported_restart_count": int(
            candidate.get("supported_restart_count") or 0
        ),
        "risk_score": int(candidate.get("risk_score") or 0),
        "review_count": int(candidate.get("review_count") or 0),
        "incomplete_review_count": int(
            candidate.get("incomplete_review_count") or 0
        ),
        "severe_risk_count": int(candidate.get("severe_risk_count") or 0),
        "relaxed_raw_hard_count": int(
            candidate.get("relaxed_raw_hard_count") or 0
        ),
    }


def _article_added_reviews_are_complete_phrases(
    cue: Cue,
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
) -> bool:
    """Allow one new review edge only for a complete visible phrase."""
    baseline_metrics = _article_candidate_readability_metrics(baseline)
    candidate_metrics = _article_candidate_readability_metrics(candidate)
    baseline_reviews = int(baseline_metrics["review_count"])
    candidate_reviews = int(candidate_metrics["review_count"])
    if candidate_reviews > baseline_reviews + 1:
        return False
    words = _article_boundary_words(cue)
    reviewable_phrase_issues = {
        "dependency_phrase_entrance_split",
        "object_attached_modifier_split",
        "unsupported_tight_page_transition",
    }
    for page in list((candidate.get("plan") or {}).get("pages") or [])[1:]:
        decision = page.get("boundary_before") or {}
        if str(decision.get("classification") or "") != "review":
            continue
        if decision.get("relaxed_raw_hard") and not decision.get(
            "complete_prepositional_continuation"
        ):
            return False
        issue_codes = {
            str(value) for value in decision.get("issue_codes") or []
        }
        split = int(page.get("word_start") or 0)
        first_word = (
            re.sub(r"[^A-Za-z']", "", words[split]).casefold()
            if 0 <= split < len(words)
            else ""
        )
        attached_modifier_is_optional_temporal_adjunct = bool(
            "object_attached_modifier_split" in issue_codes
            and first_word in ARTICLE_PAGE_OPTIONAL_TEMPORAL_ADJUNCT_START_WORDS
        )
        if (
            "object_attached_modifier_split" in issue_codes
            and not attached_modifier_is_optional_temporal_adjunct
            and not decision.get("complete_prepositional_continuation")
        ):
            return False
        if decision.get("complete_prepositional_continuation"):
            issue_codes -= {
                "dependency_phrase_entrance_split",
                "object_attached_modifier_split",
                "predicate_attached_continuation_split",
            }
        complete_prepositional = bool(
            decision.get("complete_prepositional_continuation")
        )
        if complete_prepositional:
            if issue_codes or not _article_page_can_start_with_complete_phrase(
                words, split
            ):
                return False
        elif (
            not issue_codes
            or not issue_codes <= reviewable_phrase_issues
            or not _article_page_can_start_with_complete_phrase(words, split)
        ):
            return False
    return True


def _article_candidate_relaxes_only_complete_prepositional_continuations(
    candidate: Mapping[str, object],
) -> bool:
    relaxed = [
        page.get("boundary_before") or {}
        for page in list((candidate.get("plan") or {}).get("pages") or [])[1:]
        if (page.get("boundary_before") or {}).get("relaxed_raw_hard")
    ]
    return bool(relaxed) and all(
        decision.get("complete_prepositional_continuation")
        and not _article_nonoverridable_atomic_page_boundary_issues(decision)
        for decision in relaxed
    )


_ARTICLE_MATERIAL_FINITE_AUXILIARIES = frozenset(
    {
        "am",
        "are",
        "be",
        "been",
        "being",
        "can",
        "could",
        "did",
        "do",
        "does",
        "had",
        "has",
        "have",
        "is",
        "may",
        "might",
        "must",
        "shall",
        "should",
        "was",
        "were",
        "will",
        "would",
    }
)


def _article_material_boundary_has_support(
    decision: Mapping[str, object],
    page: Mapping[str, object],
) -> bool:
    """Reject REVIEW edges that only look complete without a finite clause."""
    if str(decision.get("classification") or "allow") != "review":
        return True
    if decision.get("complete_prepositional_continuation"):
        words = [
            "".join(
                character
                for character in token.casefold()
                if character.isalpha()
            )
            for token in str(page.get("en") or "").split()
        ]
        if any(
            word in _ARTICLE_MATERIAL_FINITE_AUXILIARIES
            for word in words[1:]
        ):
            return False
    return any(
        bool(decision.get(key))
        for key in (
            "strong_pause_evidence",
            "complete_page_clause_start",
            "complete_content_clause_start",
            "complete_title_restart",
            "balanced_predicate_restart",
            "complete_prepositional_continuation",
            "complete_object_continuation",
            "forced_complete_predicate_phrase",
            "forced_complete_to_phrase",
        )
    )


def _article_material_candidate_metrics(
    candidate: Mapping[str, object],
) -> dict[str, float | int]:
    """Measure only display defects that justify changing a valid projection."""
    pages = list((candidate.get("plan") or {}).get("pages") or [])
    word_counts = [len(str(page.get("en") or "").split()) for page in pages]
    font_sizes = [
        int(
            page.get("english_font_size")
            or ARTICLE_SUBTITLE_EN_FONT_SIZE
        )
        for page in pages
    ]
    stored_pressures = tuple(
        float(value) for value in candidate.get("page_pressures") or ()
    )
    if len(stored_pressures) == len(pages):
        pressures = list(stored_pressures)
    else:
        pressures = [_article_display_page_pressure(page) for page in pages]
    review_pages = [
        page
        for page in pages[1:]
        if str((page.get("boundary_before") or {}).get("classification") or "allow")
        == "review"
    ]
    return {
        "page_count": len(pages),
        "under_five_pages": sum(value < 5 for value in word_counts),
        "short_page_deficit": sum(
            max(0, ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS - value)
            for value in word_counts
        ),
        "over_16_word_excess": sum(
            max(0, value - ARTICLE_VISUAL_PAGE_SOFT_MAX_WORDS)
            for value in word_counts
        ),
        "font_deficit": sum(
            max(0, ARTICLE_SUBTITLE_EN_FONT_SIZE - value)
            for value in font_sizes
        ),
        "three_line_pages": sum(
            len(list(page.get("en_lines") or [])) > 2 for page in pages
        ),
        "review_boundaries": len(review_pages),
        "unsupported_review_boundaries": sum(
            not _article_material_boundary_has_support(
                page.get("boundary_before") or {},
                page,
            )
            for page in review_pages
        ),
        "severe_risk_count": int(candidate.get("severe_risk_count") or 0),
        "incomplete_review_count": int(
            candidate.get("incomplete_review_count") or 0
        ),
        "risk_score": int(candidate.get("risk_score") or 0),
        "max_pressure": max(pressures, default=0.0),
        "word_count_imbalance": (
            max(word_counts, default=0) - min(word_counts, default=0)
        ),
    }


def _article_material_improvement_reason(
    baseline: Mapping[str, float | int],
    candidate: Mapping[str, float | int],
) -> str | None:
    short_relief = int(candidate["short_page_deficit"]) < int(
        baseline["short_page_deficit"]
    )
    over_16_relief = int(candidate["over_16_word_excess"]) < int(
        baseline["over_16_word_excess"]
    )
    font_relief = int(candidate["font_deficit"]) < int(
        baseline["font_deficit"]
    )
    pressure_relief = (
        float(baseline["max_pressure"]) - float(candidate["max_pressure"])
        >= ARTICLE_PAGE_PRESSURE_TRANSITION_FREE_DELTA
    )
    if short_relief and over_16_relief:
        return "short_page_and_over_16_relief"
    if short_relief:
        return "short_page_relief"
    if over_16_relief:
        return "over_16_relief"
    if font_relief:
        return "font_floor_relief"
    if pressure_relief:
        return "maximum_pressure_relief"
    return None


def _select_article_material_readability_candidate(
    baseline: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], str]:
    """Choose a materially better fixed-parent projection with no regression."""
    baseline_metrics = _article_material_candidate_metrics(baseline)
    eligible: list[
        tuple[tuple[float | int, ...], Mapping[str, object], str]
    ] = []
    for candidate in candidates:
        if candidate is baseline:
            continue
        metrics = _article_material_candidate_metrics(candidate)
        if (
            int(metrics["unsupported_review_boundaries"]) > 0
            or int(metrics["under_five_pages"])
            > int(baseline_metrics["under_five_pages"])
            or int(metrics["short_page_deficit"])
            > int(baseline_metrics["short_page_deficit"])
            or int(metrics["over_16_word_excess"])
            > int(baseline_metrics["over_16_word_excess"])
            or int(metrics["font_deficit"])
            > int(baseline_metrics["font_deficit"])
            or int(metrics["three_line_pages"])
            > int(baseline_metrics["three_line_pages"])
            or int(metrics["review_boundaries"])
            > int(baseline_metrics["review_boundaries"])
            or int(metrics["severe_risk_count"])
            > int(baseline_metrics["severe_risk_count"])
            or int(metrics["incomplete_review_count"])
            > int(baseline_metrics["incomplete_review_count"])
            or int(metrics["risk_score"]) > int(baseline_metrics["risk_score"])
            or float(metrics["max_pressure"])
            > float(baseline_metrics["max_pressure"])
            or int(metrics["word_count_imbalance"])
            > int(baseline_metrics["word_count_imbalance"])
            or int(metrics["page_count"])
            > int(baseline_metrics["page_count"]) + 1
        ):
            continue
        reason = _article_material_improvement_reason(
            baseline_metrics,
            metrics,
        )
        if reason is None:
            continue
        rank = (
            int(metrics["under_five_pages"]),
            int(metrics["short_page_deficit"]),
            int(metrics["over_16_word_excess"]),
            int(metrics["font_deficit"]),
            int(metrics["unsupported_review_boundaries"]),
            int(metrics["severe_risk_count"]),
            int(metrics["incomplete_review_count"]),
            float(metrics["max_pressure"]),
            int(metrics["word_count_imbalance"]),
            int(metrics["risk_score"]),
            int(metrics["page_count"]),
            float(candidate.get("quality_cost") or 0.0),
        )
        eligible.append((rank, candidate, reason))
    if not eligible:
        return baseline, "baseline_retained"
    _rank, selected, reason = min(eligible, key=lambda item: item[0])
    return selected, reason


def _article_mark_material_readability_candidate(
    candidate: Mapping[str, object],
    reason: str,
) -> dict:
    promoted = dict(candidate)
    plan = dict(promoted.get("plan") or {})
    plan["readability_selection"] = {
        "basis": "material_readability_non_regression",
        "reason": reason,
    }
    promoted["plan"] = plan
    promoted["material_readability_promoted"] = reason
    return promoted


def _promote_article_material_readability_candidate(
    baseline: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    selected, reason = _select_article_material_readability_candidate(
        baseline,
        candidates,
    )
    if selected is baseline:
        return baseline
    return _article_mark_material_readability_candidate(selected, reason)


def _article_mark_dominant_readability_candidate(
    candidate: Mapping[str, object],
    reason: str,
) -> dict:
    promoted = dict(candidate)
    plan = dict(promoted.get("plan") or {})
    plan["readability_selection"] = {
        "basis": "dominant_cross_page_count_candidate",
        "reason": reason,
    }
    promoted["plan"] = plan
    promoted["dominant_readability_promoted"] = reason
    return promoted


def _select_article_dominant_readability_candidate(
    cue: Cue,
    baseline: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """Promote a validated candidate only when readability objectively improves.

    Stable English and timing have already been frozen.  This selector may
    only choose another validated renderer projection: it cannot create a new
    boundary, relax an atomic issue, or change any word ownership.
    """
    baseline_metrics = _article_candidate_readability_metrics(baseline)
    words = _article_boundary_words(cue)
    eligible: list[tuple[str, Mapping[str, object], dict[str, float | int]]] = []
    for candidate in candidates:
        metrics = _article_candidate_readability_metrics(candidate)
        pages = list((candidate.get("plan") or {}).get("pages") or [])
        same_page_line_wrap_relief = bool(
            int(metrics["page_count"]) == int(baseline_metrics["page_count"])
            and int(metrics["line_wrap_review_count"]) == 0
            and int(baseline_metrics["line_wrap_review_count"]) > 0
            and int(metrics["supported_restart_count"])
            >= int(baseline_metrics["supported_restart_count"])
            and int(metrics["min_words"]) >= ARTICLE_VISUAL_PAGE_MIN_WORDS
        )
        line_wrap_relief_boundaries_complete = bool(
            same_page_line_wrap_relief
            and all(
                _article_secondary_review_boundary_is_complete(page)
                for page in pages[1:]
            )
        )
        if (
            int(metrics["severe_risk_count"])
            or (
                int(metrics["relaxed_raw_hard_count"])
                and not _article_candidate_relaxes_only_complete_prepositional_continuations(
                    candidate
                )
                and not line_wrap_relief_boundaries_complete
            )
            or int(metrics["three_line_pages"])
            > int(baseline_metrics["three_line_pages"])
            or (
                int(metrics["min_words"])
                < ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
                and not same_page_line_wrap_relief
            )
            or not _article_added_reviews_are_complete_phrases(
                cue,
                baseline,
                candidate,
            )
            and not line_wrap_relief_boundaries_complete
            or any(
                str(
                    (page.get("boundary_before") or {}).get("classification")
                    or ""
                )
                == "reject"
                or bool(
                    _article_nonoverridable_atomic_page_boundary_issues(
                        page.get("boundary_before") or {}
                    )
                )
                or _looks_like_numeric_rate_boundary(
                    words,
                    int(page.get("word_start") or 0),
                )
                for page in pages[1:]
            )
        ):
            continue
        page_delta = int(metrics["page_count"]) - int(
            baseline_metrics["page_count"]
        )
        risk_not_worse = int(metrics["risk_score"]) <= int(
            baseline_metrics["risk_score"]
        )
        if page_delta < 0:
            removes_short_tail = bool(
                int(baseline_metrics["min_words"])
                <= ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
                and int(metrics["page_count"]) == 1
                and int(metrics["max_words"])
                <= ARTICLE_VISUAL_PAGE_REVIEW_WORDS
            )
            if (
                risk_not_worse
                and int(metrics["min_font"]) >= ARTICLE_SUBTITLE_EN_FONT_SIZE
                and int(metrics["max_words"])
                <= ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS
                and (
                    removes_short_tail
                    or float(metrics["max_pressure"])
                    <= float(baseline_metrics["max_pressure"])
                    + ARTICLE_PAGE_PRESSURE_TRANSITION_FREE_DELTA
                )
            ):
                eligible.append(("fewer_comfortable_pages", candidate, metrics))
            continue
        if page_delta > 0:
            baseline_needs_relief = bool(
                int(baseline_metrics["low_font_pages"])
                or int(baseline_metrics["over_16_pages"])
                or int(baseline_metrics["three_line_pages"])
            )
            if (
                baseline_needs_relief
                and int(metrics["min_font"]) >= ARTICLE_SUBTITLE_EN_FONT_SIZE
                and int(metrics["max_words"])
                <= ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS
                and int(metrics["min_words"])
                >= ARTICLE_PAGE_SECONDARY_REVIEW_MIN_WORDS
                and float(metrics["max_pressure"])
                < float(baseline_metrics["max_pressure"])
            ):
                eligible.append(("objective_pressure_relief", candidate, metrics))
            continue
        removes_line_wrap_review = same_page_line_wrap_relief
        if (
            removes_line_wrap_review
            and risk_not_worse
            and int(metrics["min_font"]) >= int(baseline_metrics["min_font"])
            and int(metrics["max_words"])
            <= ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS
            and float(metrics["max_pressure"])
            <= float(baseline_metrics["max_pressure"])
            + ARTICLE_PAGE_PRESSURE_TRANSITION_FREE_DELTA
        ):
            eligible.append(("same_page_count_line_wrap_relief", candidate, metrics))
            continue
        dominates = bool(
            risk_not_worse
            and int(metrics["incomplete_review_count"])
            <= int(baseline_metrics["incomplete_review_count"])
            and int(metrics["low_font_pages"])
            <= int(baseline_metrics["low_font_pages"])
            and int(metrics["over_16_pages"])
            <= int(baseline_metrics["over_16_pages"])
            and int(metrics["max_words"]) <= int(baseline_metrics["max_words"])
            and float(metrics["max_pressure"])
            <= float(baseline_metrics["max_pressure"])
            and (
                int(metrics["low_font_pages"])
                < int(baseline_metrics["low_font_pages"])
                or int(metrics["over_16_pages"])
                < int(baseline_metrics["over_16_pages"])
                or int(metrics["max_words"]) < int(baseline_metrics["max_words"])
                or float(metrics["max_pressure"])
                < float(baseline_metrics["max_pressure"])
            )
        )
        if dominates:
            eligible.append(("same_page_count_dominance", candidate, metrics))

    fewer_pages = [item for item in eligible if item[0] == "fewer_comfortable_pages"]
    if fewer_pages:
        reason, selected, _ = min(
            fewer_pages,
            key=lambda item: (
                int(item[2]["page_count"]),
                float(item[2]["max_pressure"]),
                float(item[1].get("quality_cost") or 0.0),
            ),
        )
        return _article_mark_dominant_readability_candidate(selected, reason)
    pressure_relief = [item for item in eligible if item[0] == "objective_pressure_relief"]
    if pressure_relief:
        reason, selected, _ = min(
            pressure_relief,
            key=lambda item: (
                int(item[2]["low_font_pages"]),
                int(item[2]["over_16_pages"]),
                float(item[2]["max_pressure"]),
                int(item[2]["risk_score"]),
                int(item[2]["page_count"]),
            ),
        )
        return _article_mark_dominant_readability_candidate(selected, reason)
    same_page_count = [
        item
        for item in eligible
        if item[0]
        in {"same_page_count_line_wrap_relief", "same_page_count_dominance"}
    ]
    if same_page_count:
        reason, selected, _ = min(
            same_page_count,
            key=lambda item: (
                int(item[2]["line_wrap_review_count"]),
                int(item[2]["low_font_pages"]),
                int(item[2]["over_16_pages"]),
                float(item[2]["max_pressure"]),
                int(item[2]["risk_score"]),
            ),
        )
        return _article_mark_dominant_readability_candidate(selected, reason)
    return baseline


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

    states: list[
        tuple[tuple[int, int, int, int, float], list[Mapping[str, object]]]
    ] = []
    for candidate in groups[0]:
        states.append(
            (
                (
                    int(bool(candidate.get("forced_continuation"))),
                    int(bool(candidate.get("review_boundary_candidate"))),
                    int(candidate.get("severe_risk_count") or 0),
                    int(candidate.get("line_wrap_review_count") or 0),
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
                int(bool(candidate.get("review_boundary_candidate"))),
                int(candidate.get("severe_risk_count") or 0),
                int(candidate.get("line_wrap_review_count") or 0),
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
                    transition_cost = _article_visual_page_transition_cost(
                        previous,
                        -1,
                        candidate,
                        0,
                    )
                rank = (
                    previous_rank[0] + local_rank[0],
                    previous_rank[1] + local_rank[1],
                    previous_rank[2] + local_rank[2],
                    previous_rank[3] + local_rank[3],
                    previous_rank[4] + local_rank[4] + transition_cost,
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
            "material_readability_non_regression"
            if candidate.get("material_readability_promoted")
            else (
                "dominant_cross_page_count_candidate"
                if candidate.get("dominant_readability_promoted")
                else (
                    "high_pressure_secondary_review"
                    if candidate.get("secondary_review_promoted")
                    else "semantic_pixel_duration_sequence_pressure"
                )
            )
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
        "english_legacy_readable_sizes": list(
            ARTICLE_SUBTITLE_EN_LEGACY_FALLBACK_SIZES
        ),
        "english_normal_min_size": ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE,
        "english_min_size": ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE,
        "chinese_font_size": ARTICLE_SUBTITLE_ZH_FONT_SIZE,
        "chinese_letter_spacing": ARTICLE_SUBTITLE_ZH_LETTER_SPACING,
        "english_preferred_line_width": ARTICLE_SUBTITLE_EN_PREFERRED_LINE_WIDTH,
        "english_comfortable_width": ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH,
        "english_width": ARTICLE_SUBTITLE_EN_WIDTH,
        "english_wide_safe_width": ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
        "chinese_width": ARTICLE_SUBTITLE_ZH_WIDTH,
        "comfortable_page_words": ARTICLE_VISUAL_PAGE_COUNT_TARGET_WORDS,
        "review_page_words": ARTICLE_VISUAL_PAGE_REVIEW_WORDS,
        "split_priority_page_words": ARTICLE_VISUAL_PAGE_SPLIT_PRIORITY_WORDS,
        "max_lines": 2,
        "minimum_page_duration_ms": ARTICLE_PAGE_MIN_DURATION_MS,
    }


def _article_editable_page_seed_plan(
    cue: Cue,
    errors: Sequence[Mapping[str, object]],
) -> dict | None:
    """Retain immutable parent authority when no renderable plan exists."""
    words = _article_boundary_words(cue)
    timing = list(cue.word_timing or ())
    if (
        not cue.subtitle_id
        or not words
        or len(words) != len(timing)
    ):
        return None
    try:
        word_start = int(timing[0]["word_id"])
        word_end = _article_timing_word_end(timing[-1])
    except (KeyError, TypeError, ValueError):
        return None
    reasons = [
        str(error.get("reason") or "render_structural_overflow")
        for error in errors
        if str(error.get("cue_index") or "") == str(cue.index)
    ]
    # This is an explicit non-renderable recovery checkpoint, not a normal
    # page layout. Keep the English visible for editor review even when no
    # legal two-line layout exists; an empty line array makes the checkpoint
    # look like missing content and violates the display-page artifact shape.
    preview_lines = [" ".join(words)]
    return {
        "parent_subtitle_id": str(cue.subtitle_id),
        "english": str(cue.en or ""),
        "chinese": str(cue.zh or ""),
        "word_start": word_start,
        "word_end": word_end,
        "english_font_size": ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE,
        "font_fallback": {"used": False},
        "editable_seed": True,
        "renderable": False,
        "failure_reasons": sorted(set(reasons)),
        "pages": [
            {
                "display_page_id": display_page_id(str(cue.subtitle_id), 1),
                "word_start": word_start,
                "word_end": word_end,
                "english": " ".join(words),
                "start_ms": round(float(cue.start) * 1000),
                "end_ms": round(float(cue.end) * 1000),
                "english_lines": preview_lines,
                "english_font_size": ARTICLE_SUBTITLE_EN_NORMAL_MIN_SIZE,
                "english_width": ARTICLE_SUBTITLE_EN_WIDE_SAFE_WIDTH,
                "boundary_before": {},
            }
        ],
    }


def _article_manual_degraded_render_plan(
    cue: Cue,
    errors: Sequence[Mapping[str, object]],
) -> dict | None:
    """Build a renderable, review-only plan after automatic planning fails."""
    words = _article_boundary_words(cue)
    if not cue.subtitle_id or len(words) != len(cue.word_timing):
        return None
    max_page_count = min(ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES, len(words))
    reasons = sorted(
        {
            str(error.get("reason") or "render_structural_overflow")
            for error in errors
        }
    ) or ["render_structural_overflow"]
    for requested_page_count in range(2, max_page_count + 1):
        try:
            ranges = propose_article_manual_page_word_ranges(
                cue,
                requested_page_count,
                allow_review_boundary=True,
                allow_hard_boundary=True,
            )
            local_spans = _article_local_spans_for_global_ranges(
                list(cue.word_timing),
                ranges,
            )
            minimum_page_words = max(
                ARTICLE_VISUAL_PAGE_MIN_WORDS,
                math.floor(len(words) / requested_page_count * 0.55),
            )
            if local_spans is None or any(
                end - start < minimum_page_words
                for start, end in local_spans
            ):
                continue
            if any(
                _article_boundary_has_incomplete_predicate(
                    _article_display_boundary_decision(cue, local_start),
                    words=words,
                    split=local_start,
                )
                for local_start, _local_end in local_spans[1:]
            ):
                continue
            seed = {
                "pages": [
                    {
                        "display_page_id": display_page_id(
                            str(cue.subtitle_id),
                            index + 1,
                        )
                    }
                    for index in range(len(ranges))
                ]
            }
            rebuilt = rebuild_article_frozen_page_plan_from_word_ranges(
                cue,
                seed,
                ranges,
                {},
                allow_page_count_change=True,
                allow_incomplete_page_translations=True,
                allow_manual_review=True,
            )
        except RenderStructuralOverflowError:
            continue
        rebuilt.update(
            {
                "review_only": True,
                "renderable": True,
                "degraded": True,
                "degraded_reasons": reasons,
                "review_reasons": ["automatic_page_plan_unavailable"],
                "page_count_decision": {
                    "preferred": requested_page_count,
                    "selected": len(rebuilt.get("pages") or []),
                    "basis": "manual_degraded_fallback",
                },
            }
        )
        return rebuilt
    return None


def build_article_display_page_blueprint(cues: Sequence[Cue]) -> dict:
    """Return only multi-page parents after final word timing is frozen."""
    draw = ImageDraw.Draw(Image.new("RGB", (ARTICLE_WIDTH, ARTICLE_HEIGHT)))
    errors: list[dict] = []
    degraded_parents: list[dict] = []
    degraded_render_plans: list[tuple[Cue, dict]] = []
    bundle_entries: list[tuple[Cue, dict]] = []
    for cue in cues:
        bundle = _build_article_english_page_plan(
            cue,
            draw,
            _return_candidates=True,
        )
        if bundle.get("status") != "candidate_bundle":
            bundle_errors = list(bundle.get("errors") or [])
            degraded_plan = _article_manual_degraded_render_plan(cue, bundle_errors)
            if degraded_plan is None:
                errors.extend(bundle_errors)
                continue
            degraded_parents.append(
                {
                    "cue_index": cue.index,
                    "parent_subtitle_id": str(cue.subtitle_id or ""),
                    "reasons": sorted(
                        {
                            str(error.get("reason") or "render_structural_overflow")
                            for error in bundle_errors
                        }
                    )
                    or ["render_structural_overflow"],
                }
            )
            degraded_render_plans.append((cue, degraded_plan))
            continue
        if bundle.get("fallback_review"):
            fallback_errors = list(bundle.get("fallback_errors") or [])
            degraded_parents.append(
                {
                    "cue_index": cue.index,
                    "parent_subtitle_id": str(cue.subtitle_id or ""),
                    "reasons": sorted(
                        {
                            str(error.get("reason") or "render_structural_overflow")
                            for error in fallback_errors
                        }
                    )
                    or ["render_structural_overflow"],
                }
            )
        bundle_entries.append((cue, bundle))
    selected_candidates = _select_article_page_plan_sequence(
        [bundle["candidates"] for _cue, bundle in bundle_entries]
    )
    if len(selected_candidates) != len(bundle_entries):
        errors.append(
            {"cue_index": "all", "reason": "display_page_sequence_unavailable"}
        )
        selected_candidates = []
    selected_candidates = [
        _select_article_dominant_readability_candidate(
            cue,
            selected,
            bundle.get("shadow_candidates") or (),
        )
        for (cue, bundle), selected in zip(bundle_entries, selected_candidates)
    ]
    selected_candidates = [
        _promote_article_material_readability_candidate(
            selected,
            bundle.get("shadow_candidates") or (),
        )
        for (_cue, bundle), selected in zip(bundle_entries, selected_candidates)
    ]

    parents: list[dict] = []
    render_plans: list[dict] = []
    for (cue, bundle), selected in zip(bundle_entries, selected_candidates):
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
                "page_count_decision": dict(
                    plan.get("page_count_decision") or {}
                ),
                "readability_selection": dict(
                    plan.get("readability_selection") or {}
                ),
                "pages": frozen_pages,
            }
        )
        if bundle.get("fallback_review"):
            render_plans[-1].update(
                {
                    "review_only": True,
                    "renderable": True,
                    "degraded": True,
                    "degraded_reasons": [
                        str(error.get("reason") or "render_structural_overflow")
                        for error in bundle.get("fallback_errors") or []
                    ]
                    or ["render_structural_overflow"],
                    "review_reasons": [
                        "no_complete_normal_font_page_partition"
                    ],
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
    for cue, degraded_plan in degraded_render_plans:
        render_plans.append(degraded_plan)
        pages = list(degraded_plan.get("pages") or [])
        if len(pages) > 1:
            parents.append(
                {
                    "parent_subtitle_id": cue.subtitle_id,
                    "english": cue.en,
                    "chinese": cue.zh,
                    "word_start": int(pages[0]["word_start"]),
                    "word_end": int(pages[-1]["word_end"]),
                    "pages": pages,
                }
            )
    cue_order = {
        str(cue.subtitle_id or ""): index
        for index, cue in enumerate(cues)
    }
    render_plans.sort(
        key=lambda plan: cue_order.get(str(plan.get("parent_subtitle_id") or ""), len(cues))
    )
    parents.sort(
        key=lambda parent: cue_order.get(
            str(parent.get("parent_subtitle_id") or ""),
            len(cues),
        )
    )
    degraded_page_count = len(degraded_parents)
    total_parent_count = len(cues)
    degraded_parent_ratio = (
        degraded_page_count / total_parent_count if total_parent_count else 0.0
    )
    degraded_threshold = max(
        1,
        math.floor(total_parent_count * ARTICLE_DISPLAY_DEGRADED_MAX_RATIO),
    )
    if degraded_page_count > degraded_threshold:
        errors.append(
            {
                "cue_index": "all",
                "reason": "degraded_page_count_exceeded",
                "degraded_page_count": degraded_page_count,
                "total_parent_count": total_parent_count,
                "degraded_parent_ratio": degraded_parent_ratio,
                "degraded_page_threshold": degraded_threshold,
            }
        )
    if errors:
        plans_by_parent = {
            str(plan.get("parent_subtitle_id") or ""): plan
            for plan in render_plans
            if str(plan.get("parent_subtitle_id") or "")
        }
        for cue in cues:
            parent_id = str(cue.subtitle_id or "")
            if parent_id in plans_by_parent:
                continue
            seed = _article_editable_page_seed_plan(cue, errors)
            if seed is not None:
                plans_by_parent[parent_id] = seed
        partial_blueprint = {
            "schema_version": DISPLAY_PAGE_SCHEMA_VERSION,
            "status": "ERROR",
            "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
            "layout_profile": article_display_page_layout_profile(),
            "degraded_page_count": degraded_page_count,
            "total_parent_count": total_parent_count,
            "degraded_parent_ratio": degraded_parent_ratio,
            "degraded_page_threshold": degraded_threshold,
            "degraded_parents": degraded_parents,
            "parents": [],
            "render_plans": [
                plans_by_parent[parent_id]
                for parent_id in [str(cue.subtitle_id or "") for cue in cues]
                if parent_id in plans_by_parent
            ],
            "errors": [dict(error) for error in errors],
        }
        raise RenderStructuralOverflowError(
            errors,
            partial_blueprint=partial_blueprint,
        )
    return {
        "status": "PASS",
        "planner_version": DISPLAY_PAGE_PLANNER_VERSION,
        "layout_profile": article_display_page_layout_profile(),
        "parents": parents,
        "render_plans": render_plans,
        "degraded_page_count": degraded_page_count,
        "total_parent_count": total_parent_count,
        "degraded_parent_ratio": degraded_parent_ratio,
        "degraded_page_threshold": degraded_threshold,
        "degraded_parents": degraded_parents,
    }


def build_article_display_page_candidate_workspace(
    cue: Cue,
    *,
    min_page_count: int = 2,
    max_page_count: int = ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES,
) -> dict:
    """Return bounded read-only page candidates for editor inspection.

    The production blueprint remains the only writer of ``article_page_plan``.
    This helper creates no IDs, translations, timing overrides, or file output.
    """
    lower = max(2, int(min_page_count or 2))
    upper = min(
        ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES,
        max(
            lower,
            int(max_page_count or ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES),
        ),
    )
    draw = ImageDraw.Draw(Image.new("RGB", (ARTICLE_WIDTH, ARTICLE_HEIGHT)))
    bundle = _build_article_english_page_plan(
        cue,
        draw,
        _return_candidates=True,
        max_page_count=upper,
    )
    if bundle.get("status") != "candidate_bundle":
        return {
            "status": "unavailable",
            "parent_subtitle_id": str(cue.subtitle_id or ""),
            "reason": "candidate_bundle_unavailable",
            "errors": list(bundle.get("errors") or []),
            "candidates": [],
        }
    selected = [
        candidate
        for candidate in bundle.get("candidates") or []
        if lower <= int(candidate.get("page_count") or 0) <= upper
    ]
    if not selected:
        # The production bundle may intentionally expose only the selected
        # page count. For a manual workspace, fall back to the read-only
        # shadow frontier so a 15-word review cue can still be inspected as
        # a two-page proposal without changing production authority.
        selected = [
            candidate
            for candidate in bundle.get("shadow_candidates") or []
            if lower <= int(candidate.get("page_count") or 0) <= upper
        ]
    selected.sort(
        key=lambda candidate: (
            int(candidate.get("page_count") or 0),
            float(candidate.get("quality_cost") or 0),
        )
    )
    return {
        "status": "candidate_workspace",
        "parent_subtitle_id": str(cue.subtitle_id or ""),
        "english": str(cue.en or ""),
        "chinese": str(cue.zh or ""),
        "preferred_page_count": int(bundle.get("preferred_page_count") or 1),
        "candidate_mode": str(bundle.get("candidate_mode") or "strict"),
        "candidates": [copy.deepcopy(candidate) for candidate in selected[: max(1, upper - lower + 1)]],
    }


def propose_article_manual_page_word_ranges(
    cue: Cue,
    page_count: int,
    *,
    allow_review_boundary: bool = False,
    allow_hard_boundary: bool = False,
) -> list[tuple[int, int]]:
    """Plan an explicit page count with the normal syntax/timing scorer."""
    requested = int(page_count)
    words = _article_boundary_words(cue)
    timing = list(cue.word_timing or ())
    if (
        requested < 2
        or requested > ARTICLE_MANUAL_VISUAL_PAGE_MAX_PAGES
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
        for font_size in ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES:
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
                (
                    int(timing[start]["word_id"]),
                    _article_timing_word_end(timing[end - 1]),
                )
                for start, end in spans
            ]

    if allow_review_boundary:
        for font_size in ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES:
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
                (
                    int(timing[start]["word_id"]),
                    _article_timing_word_end(timing[end - 1]),
                )
                for start, end in spans
            ]

    if allow_hard_boundary:
        for font_size in ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES:
            diagnostics: set[str] = set()
            spans = _partition_article_english_pages(
                draw,
                cue,
                words,
                requested,
                cue.word_timing,
                font_size,
                diagnostics=diagnostics,
                allow_manual_override=True,
            )
            attempted_reasons.update(diagnostics)
            if spans is None:
                continue
            schedule, schedule_error = _schedule_article_page_boundaries(
                cue,
                spans,
                minimum_page_duration_ms=0,
            )
            if schedule is None:
                attempted_reasons.add(schedule_error)
                continue
            return [
                (
                    int(timing[start]["word_id"]),
                    _article_timing_word_end(timing[end - 1]),
                )
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
    words = _article_boundary_words(cue)
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
        last_word_id = _article_timing_word_end(timing[-1])
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

    local_spans = _article_local_spans_for_global_ranges(timing, ranges)
    if local_spans is None:
        raise RenderStructuralOverflowError(
            [
                {
                    "cue_index": cue.index,
                    "reason": "manual_page_boundary_splits_display_span",
                }
            ]
        )
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
                        "word_start": int(timing[local_start]["word_id"]),
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
        _article_final_page_layout(
            draw,
            cue,
            words,
            local_start,
            local_end,
            allow_legacy_fallback=False,
        )
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
        (local_start, local_end),
        raw_page,
        lines,
        page_font_size,
    ) in enumerate(
        zip(
            ranges,
            local_spans,
            page_templates,
            selected_lines,
            selected_page_fonts,
        )
    ):
        page_id = str(raw_page.get("display_page_id") or "")
        if page_id != display_page_id(str(cue.subtitle_id or ""), page_index + 1):
            raise RenderStructuralOverflowError(
                [{"cue_index": cue.index, "reason": "manual_page_id_mismatch"}]
            )
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
    words = _article_boundary_words(cue)
    timing = list(cue.word_timing or ())
    if not words or len(words) != len(timing):
        return None
    try:
        first_word_id = int(timing[0]["word_id"])
        last_word_id = _article_timing_word_end(timing[-1])
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
        local_spans = _article_local_spans_for_global_ranges(
            timing,
            [(global_start, global_end)],
        )
        if local_spans is None:
            return None
        local_start, local_end_exclusive = local_spans[0]
        local_end = local_end_exclusive - 1
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
        # Line breaks are renderer-owned.  A frozen page produced before a
        # typography-only change may still carry the previous face's lines;
        # keep its immutable word span and timing, but publish the lines
        # measured with the current subtitle font.
        frozen_lines = list(expected_lines)
        expected_width = _article_english_layout_width(
            draw,
            expected_lines,
            page_font_size,
        )
        boundary_before = dict(raw_page.get("boundary_before") or {})
        if (
            not expected_lines
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
                "en_width": expected_width,
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
    *,
    failure_items: list[dict[str, str]] | None = None,
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
        source_parent_chinese = re.sub(
            r"\s+", "", str(parent.get("source_parent_chinese") or "")
        )
        if source_parent_chinese != re.sub(r"\s+", "", str(cue.zh or "")):
            return False
        aggregate = re.sub(r"\s+", "", str(parent.get("aggregate_chinese") or ""))
        if not aggregate:
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
            if failure_items is not None:
                failure_items.append(
                    {
                        "subtitle_id": parent_id,
                        "reason": "display_page_artifact_blueprint_mismatch",
                    }
                )
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
    manifest_path = find_stable_manifest_for_artifact(subtitle_path)
    if manifest_path is None:
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(manifest.get("display_page_translation_status") or "") != "PASS":
            return False
        expected_sha256 = str(manifest.get("display_page_translation_sha256") or "")
        artifact_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            str(manifest.get("display_page_translation_path") or ""),
            expected_sha256,
        )
        if artifact_path is None:
            return False
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
    if len(cue.word_timing) != len(_article_boundary_words(cue)):
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
        words = _article_boundary_words(cue)
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
            for font_size in ARTICLE_SUBTITLE_EN_AUTOMATIC_SIZES:
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
                            "global_word_end": _article_timing_word_end(
                                cue.word_timing[end - 1]
                            ),
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
    manifest_path = find_stable_manifest_for_artifact(subtitle_path)
    if manifest_path is None:
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        expected_sha256 = str(manifest.get("manual_draft_page_plan_sha256") or "")
        override = manifest.get("manual_final_override") or {}
        if not isinstance(override, Mapping):
            return False
        override_sha256 = str(override.get("manual_draft_page_plan_sha256") or "")
        artifact_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            str(manifest.get("manual_draft_page_plan_path") or ""),
            expected_sha256,
        )
        override_path = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            str(override.get("manual_draft_page_plan_path") or ""),
            override_sha256,
        )
        artifact_dir = resolve_manifest_owned_path(
            manifest_path,
            manifest,
            str(override.get("artifact_dir") or ""),
            expect_directory=True,
        )
        if (
            artifact_path is None
            or override_path is None
            or artifact_dir is None
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


def article_subtitle_origins(en_count: int, zh_count: int) -> tuple[int, int]:
    """Return stable design-space origins for the rendered subtitle block."""
    if en_count == 1 and zh_count <= 1:
        return 604, 766
    if en_count == 2 and zh_count <= 1:
        return 570, 772
    if en_count == 1 and zh_count == 2:
        return 586, 736
    if en_count == 3:
        return (552, 774) if zh_count <= 1 else (552, 746)
    return 560, 736


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


ARTICLE_VOCAB_MEANING_LINE_BALANCE_RATIO = 2 / 3
ARTICLE_VOCAB_MEANING_EDGE_PARTICLES = frozenset(
    "的与和及或但而并把被将让使为对从向给由因比像"
)


class ArticleVocabularyMeaningOverflowError(RuntimeError):
    """Raised when a vocabulary meaning cannot fit without losing text."""


class ArticleVocabularyPhraseOverflowError(RuntimeError):
    """Raised when an English card phrase cannot fit without tiny text."""


def wrap_article_vocab_phrase(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap an English card phrase at whitespace into at most two lines."""
    phrase = " ".join(str(text).split())
    if not phrase or text_w(draw, phrase, fnt) <= max_width:
        return [phrase]

    words = phrase.split()
    candidates: list[tuple[tuple[int, int, int], list[str]]] = []
    for split in range(1, len(words)):
        before = " ".join(words[:split])
        after = " ".join(words[split:])
        before_width = text_w(draw, before, fnt)
        after_width = text_w(draw, after, fnt)
        if before_width > max_width or after_width > max_width:
            continue
        break_penalty = _article_intrinsic_line_break_penalty(words, split)
        candidates.append(
            (
                (
                    0 if break_penalty < CAPTION_HARD_BREAK_PENALTY else 1,
                    abs(after_width - before_width),
                    0 if after_width >= before_width else 1,
                ),
                [before, after],
            )
        )
    return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else []


def fit_article_vocab_phrase_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int = 540,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Keep phrases readable by wrapping before shrinking below normal size."""
    phrase = " ".join(str(text).split())
    rendered_max_width = acx(max_width)
    factory = article_vocab_phrase_font
    if not phrase:
        return factory(ARTICLE_VOCAB_PHRASE_MAX_FONT_SIZE), [""]

    words = phrase.split()
    if len(words) == 1:
        for size in range(
            ARTICLE_VOCAB_PHRASE_MAX_FONT_SIZE,
            ARTICLE_VOCAB_UNBROKEN_WORD_MIN_FONT_SIZE - 1,
            -2,
        ):
            fnt = factory(size)
            if text_w(draw, phrase, fnt) <= rendered_max_width:
                return fnt, [phrase]
        raise ArticleVocabularyPhraseOverflowError(
            "文章单词卡英文单词超出可用宽度，请缩短词条"
        )

    for size in range(
        ARTICLE_VOCAB_PHRASE_MAX_FONT_SIZE,
        ARTICLE_VOCAB_PHRASE_SINGLE_LINE_MIN_FONT_SIZE - 1,
        -2,
    ):
        fnt = factory(size)
        if text_w(draw, phrase, fnt) <= rendered_max_width:
            return fnt, [phrase]

    fallback: tuple[ImageFont.FreeTypeFont, list[str]] | None = None
    for size in range(
        ARTICLE_VOCAB_PHRASE_MAX_FONT_SIZE,
        ARTICLE_VOCAB_PHRASE_MIN_FONT_SIZE - 1,
        -2,
    ):
        fnt = factory(size)
        lines = wrap_article_vocab_phrase(draw, phrase, fnt, rendered_max_width)
        if len(lines) != 2:
            continue
        widths = [text_w(draw, line, fnt) for line in lines]
        if fallback is None:
            fallback = (fnt, lines)
        longest = max(widths)
        if longest and min(widths) / longest >= ARTICLE_VOCAB_PHRASE_LINE_BALANCE_RATIO:
            return fnt, lines
    if fallback is not None:
        return fallback
    raise ArticleVocabularyPhraseOverflowError(
        "文章单词卡英文短语无法在两行内清晰显示，请缩短词条"
    )


def wrap_article_vocab_meaning(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap a vocabulary meaning at safe lexical boundaries into two lines."""
    meaning = str(text).strip()
    if not meaning or text_w(draw, meaning, fnt) <= max_width:
        return [meaning]

    candidates: list[tuple[tuple[int, int, int], list[str]]] = []
    for offset in _article_title_break_offsets(meaning):
        if offset in {0, len(meaning)}:
            continue
        before = meaning[:offset].strip()
        after = meaning[offset:].strip()
        if not before or not after:
            continue
        if (
            before[-1] in ARTICLE_VOCAB_MEANING_EDGE_PARTICLES
            or after[0] in ARTICLE_VOCAB_MEANING_EDGE_PARTICLES
        ):
            continue
        before_width = text_w(draw, before, fnt)
        after_width = text_w(draw, after, fnt)
        if before_width > max_width or after_width > max_width:
            continue

        shorter = min(before_width, after_width)
        longer = max(before_width, after_width)
        balanced = bool(
            longer
            and shorter / longer >= ARTICLE_VOCAB_MEANING_LINE_BALANCE_RATIO
        )
        score = (
            # The second line should carry a little more visual weight. Keep
            # this ahead of semantic preference so a lead-in cannot consume
            # most of the first line and strand a short tail below it.
            0 if after_width >= before_width else 1,
            0 if balanced else 1,
            abs(after_width - before_width),
        )
        candidates.append((score, [before, after]))

    return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else []


def fit_article_vocab_meaning_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int = 500,
    max_size: int = ARTICLE_VOCAB_MEANING_MAX_RENDER_SIZE,
    min_size: int = ARTICLE_VOCAB_MEANING_MIN_RENDER_SIZE,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Fit a complete meaning using rendered-pixel font sizes."""
    rendered_max_width = acx(max_width)
    for size in range(max_size, min_size - 1, -2):
        fnt = article_vocab_meaning_font(size, rendered=True)
        lines = wrap_article_vocab_meaning(
            draw,
            text,
            fnt,
            rendered_max_width,
        )
        if lines and len(lines) <= 2 and all(
            text_w(draw, line, fnt) <= rendered_max_width for line in lines
        ):
            return fnt, lines
    raise ArticleVocabularyMeaningOverflowError(
        "文章单词卡中文释义无法在两行内完整显示，请缩短释义"
    )


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


def article_vocab_detail_mixed_tokens(text: str) -> list[str]:
    """Tokenize a Chinese explanation without breaking English expressions."""
    return re.findall(
        r"[A-Za-z0-9]+(?:['/-][A-Za-z0-9]+)*|\s+|.",
        str(text).strip(),
    )


def article_vocab_display_phrase(text: str) -> str:
    """Capitalize only the first Latin letter in a vocabulary expression."""
    phrase = " ".join(str(text or "").split())
    return re.sub(
        r"[A-Za-z]",
        lambda match: match.group(0).upper(),
        phrase,
        count=1,
    )


def article_vocab_detail_is_english_only(text: str) -> bool:
    """Return whether a detail contains Latin text but no CJK text."""
    value = str(text or "").strip()
    return bool(re.search(r"[A-Za-z]", value)) and not bool(
        re.search(r"[\u4e00-\u9fff]", value)
    )


def article_vocab_detail_mixed_font(
    token: str,
    size: int,
    *,
    english_only: bool = False,
) -> ImageFont.FreeTypeFont:
    """Use Roboto Slab for Latin text and the existing Medium face for CJK."""
    if re.search(r"[A-Za-z0-9]", token):
        english_size = max(1, round(size * ARTICLE_VOCAB_DETAIL_EN_FONT_SCALE))
        if not english_only:
            english_size = size
        return article_subtitle_en_font(english_size, 400)
    return article_vocab_detail_font(size)


def article_vocab_detail_mixed_width(
    draw: ImageDraw.ImageDraw,
    tokens: Sequence[str],
    size: int,
    *,
    english_only: bool = False,
) -> int:
    return sum(
        text_w(
            draw,
            token,
            article_vocab_detail_mixed_font(
                token,
                size,
                english_only=english_only,
            ),
        )
        for token in tokens
    )


def _wrap_article_vocab_detail_tokens_by_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    size: int,
    max_width: int,
    *,
    english_only: bool,
) -> list[list[str]]:
    lines: list[list[str]] = []
    current: list[str] = []
    for token in article_vocab_detail_mixed_tokens(text):
        candidate = [*current, token]
        if (
            current
            and token not in "，。！？；：、,.!?;:)]}】》〉」』"
            and article_vocab_detail_mixed_width(
                draw,
                candidate,
                size,
                english_only=english_only,
            ) > max_width
        ):
            lines.append(current)
            current = [token.lstrip()]
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [[]]


def wrap_article_vocab_detail_mixed_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    size: int,
    max_width: int,
    *,
    prefer_semantic_break: bool,
) -> list[list[str]]:
    """Wrap mixed-script explanations using the fonts used for final drawing."""
    paragraph = str(text).strip()
    english_only = article_vocab_detail_is_english_only(paragraph)
    full_tokens = article_vocab_detail_mixed_tokens(paragraph)
    if not paragraph or article_vocab_detail_mixed_width(
        draw,
        full_tokens,
        size,
        english_only=english_only,
    ) <= max_width:
        return [full_tokens]

    safe_offsets = _article_title_break_offsets(paragraph)
    semantic_offsets = (
        _article_concept_semantic_break_offsets(paragraph, safe_offsets)
        if prefer_semantic_break
        else set()
    )
    total_cjk = len(re.findall(r"[\u4e00-\u9fff]", paragraph))
    candidates: list[tuple[tuple[int, int, int, int], list[list[str]]]] = []
    punctuation_candidates: list[tuple[tuple[int, int, int, int], list[list[str]]]] = []
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
        before_tokens = article_vocab_detail_mixed_tokens(before)
        after_tokens = article_vocab_detail_mixed_tokens(after)
        before_width = article_vocab_detail_mixed_width(
            draw,
            before_tokens,
            size,
            english_only=english_only,
        )
        after_width = article_vocab_detail_mixed_width(
            draw,
            after_tokens,
            size,
            english_only=english_only,
        )
        if before_width > max_width or after_width > max_width:
            continue
        before_cjk = len(re.findall(r"[\u4e00-\u9fff]", before))
        after_cjk = len(re.findall(r"[\u4e00-\u9fff]", after))
        # Do not create a one- or two-character tail when the explanation is
        # predominantly Chinese. Keep at least a quarter of the CJK content on
        # each line, with a four-character floor for short notes.
        if total_cjk >= 8 and min(before_cjk, after_cjk) < max(4, math.ceil(total_cjk * 0.25)):
            continue
        widest = max(before_width, after_width, 1)
        tail_ratio = min(before_width, after_width) / widest
        short_tail_penalty = int(tail_ratio < ARTICLE_VOCAB_DETAIL_MIN_TAIL_RATIO)
        punctuation_penalty = int(before[-1:] not in ARTICLE_MIXED_PREFERRED_BREAK_AFTER)
        candidate = (
            (
                # Body explanations fill the first line toward the right
                # safe edge, but never strand a very short second line.
                short_tail_penalty,
                -before_width,
                punctuation_penalty,
                0 if offset in semantic_offsets else 1,
                abs(after_width - before_width),
            ),
            [before_tokens, after_tokens],
        )
        candidates.append(candidate)
        if before[-1:] in ARTICLE_VOCAB_PUNCTUATION_BREAKS:
            punctuation_candidates.append(candidate)
    # A comma is the author's explicit semantic boundary. Once the complete
    # explanation is too wide, prefer a legal comma/semicolon boundary over a
    # closer-looking lexical cut. If no punctuation boundary can fit at this
    # font size, retain the existing safe-boundary fallback.
    selected_candidates = punctuation_candidates or candidates
    if selected_candidates:
        return min(selected_candidates, key=lambda candidate: candidate[0])[1]
    return _wrap_article_vocab_detail_tokens_by_width(
        draw,
        paragraph,
        size,
        max_width,
        english_only=english_only,
    )


def fit_article_vocab_detail_mixed_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_lines: int,
    max_size: int,
    min_size: int,
    prefer_semantic_break: bool,
) -> tuple[int, list[list[str]]]:
    rendered_max_width = acx(max_width)
    english_only = article_vocab_detail_is_english_only(text)
    for size in range(max_size, min_size - 1, -2):
        lines = wrap_article_vocab_detail_mixed_text(
            draw,
            text,
            size,
            rendered_max_width,
            prefer_semantic_break=prefer_semantic_break,
        )
        if len(lines) <= max_lines and all(
            article_vocab_detail_mixed_width(
                draw,
                line,
                size,
                english_only=english_only,
            )
            <= rendered_max_width
            for line in lines
        ):
            return size, lines
    return min_size, wrap_article_vocab_detail_mixed_text(
        draw,
        text,
        min_size,
        rendered_max_width,
        prefer_semantic_break=prefer_semantic_break,
    )[:max_lines]


def _coalesce_article_vocab_detail_tokens(tokens: Sequence[str]) -> list[str]:
    runs: list[str] = []
    run_is_latin: bool | None = None
    for token in tokens:
        token_is_latin = bool(re.search(r"[A-Za-z0-9]", token))
        if runs and token_is_latin == run_is_latin:
            runs[-1] += token
        else:
            runs.append(token)
            run_is_latin = token_is_latin
    return runs


def draw_article_vocab_detail_mixed_line(
    draw: ImageDraw.ImageDraw,
    left_x: int,
    y: int,
    tokens: Sequence[str],
    size: int,
    fill: tuple[int, int, int, int],
    *,
    english_only: bool = False,
) -> None:
    runs = _coalesce_article_vocab_detail_tokens(tokens)
    if not runs:
        return
    fonts = [
        article_vocab_detail_mixed_font(
            run,
            size,
            english_only=english_only,
        )
        for run in runs
    ]
    widths = [text_w(draw, run, fnt) for run, fnt in zip(runs, fonts)]
    cursor = left_x
    baseline = y + max(
        (text_h(draw, run, fnt) for run, fnt in zip(runs, fonts)),
        default=0,
    )
    for run, fnt, width in zip(runs, fonts, widths):
        draw_stroked_text(
            draw,
            (cursor, baseline),
            run,
            fnt,
            fill,
            anchor="ls",
            stroke_width=0,
        )
        cursor += width


def article_vocab_detail_mixed_line_bounds(
    draw: ImageDraw.ImageDraw,
    y: int,
    tokens: Sequence[str],
    size: int,
    *,
    english_only: bool = False,
) -> tuple[int, int]:
    """Return the visible vertical bounds used by a mixed-script detail line."""
    runs = _coalesce_article_vocab_detail_tokens(tokens)
    if not runs:
        return y, y
    fonts = [
        article_vocab_detail_mixed_font(
            run,
            size,
            english_only=english_only,
        )
        for run in runs
    ]
    baseline = y + max(
        (text_h(draw, run, fnt) for run, fnt in zip(runs, fonts)),
        default=0,
    )
    boxes = [
        draw.textbbox((0, baseline), run, font=fnt, anchor="ls")
        for run, fnt in zip(runs, fonts)
    ]
    return min(box[1] for box in boxes), max(box[3] for box in boxes)


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
        return article_subtitle_en_font(size, 400)
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


def load_article_logo(logo_path: str) -> Image.Image | None:
    """Load one optional brand asset into the article template's safe area."""
    normalized_path = str(logo_path or "").strip()
    if not normalized_path:
        return None

    path = Path(normalized_path).expanduser()
    if not path.is_file():
        raise RuntimeError(f"品牌 Logo 文件不存在：{path}")
    try:
        with Image.open(path) as source:
            logo = source.convert("RGBA")
    except Exception as exc:
        raise RuntimeError(f"无法读取品牌 Logo：{path}（{exc}）") from exc
    if logo.width <= 0 or logo.height <= 0:
        raise RuntimeError(f"品牌 Logo 尺寸无效：{path}")
    return ImageOps.contain(
        logo,
        (acx(100), acy(50)),
        Image.Resampling.LANCZOS,
    )


def draw_article_logo(
    img: Image.Image,
    logo: Image.Image | None,
    position: tuple[int, int] = (0, 0),
) -> None:
    if logo is None:
        return
    safe_width, safe_height = acx(100), acy(50)
    x = position[0] + max(0, (safe_width - logo.width) // 2)
    y = position[1] + max(0, (safe_height - logo.height) // 2)
    img.alpha_composite(logo, (x, y))


def _article_date_ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _article_date_relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels = []
    for value in rgb:
        channel = value / 255.0
        channels.append(
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _article_date_contrast_ratio(
    background: tuple[int, int, int],
    scrim_alpha: int,
) -> float:
    blended = tuple(
        round(
            (scrim * scrim_alpha + source * (255 - scrim_alpha))
            / 255
        )
        for source, scrim in zip(background, ARTICLE_DATE_SCRIM_COLOR)
    )
    text_luminance = _article_date_relative_luminance(
        ARTICLE_DATE_TEXT_COLOR[:3]
    )
    background_luminance = _article_date_relative_luminance(blended)
    lighter = max(text_luminance, background_luminance)
    darker = min(text_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def article_date_scrim_alpha(
    cover: Image.Image,
    sample_box: tuple[int, int, int, int] | None = None,
) -> int:
    if sample_box is None:
        sample_width = min(cover.width, acx(360))
        sample_height = min(cover.height, acy(50))
        sample_box = (
            cover.width - sample_width,
            0,
            cover.width,
            sample_height,
        )
    x0, y0, x1, y1 = sample_box
    bounded_box = (
        max(0, min(cover.width, x0)),
        max(0, min(cover.height, y0)),
        max(0, min(cover.width, x1)),
        max(0, min(cover.height, y1)),
    )
    crop = cover.crop(bounded_box).convert("RGBA")
    if crop.width <= 0 or crop.height <= 0:
        return ARTICLE_DATE_SCRIM_MAX_ALPHA
    backdrop = Image.new("RGBA", crop.size, ARTICLE_CARD_CONTAINER)
    backdrop.alpha_composite(crop)
    pixels = backdrop.convert("RGB").getdata()
    for alpha in range(
        ARTICLE_DATE_SCRIM_MIN_ALPHA,
        ARTICLE_DATE_SCRIM_MAX_ALPHA + 1,
    ):
        if all(
            _article_date_contrast_ratio(pixel, alpha)
            >= ARTICLE_DATE_MIN_CONTRAST
            for pixel in pixels
        ):
            return alpha
    return ARTICLE_DATE_SCRIM_MAX_ALPHA


def article_date_gradient_mask(
    width: int,
    height: int,
    max_alpha: int,
    fade_width: int,
) -> Image.Image:
    solid_height = min(height, acy(36))
    horizontal = Image.new("L", (width, 1), 0)
    horizontal.putdata(
        [
            round(
                max_alpha
                * _article_date_ease(x / max(1, fade_width - 1))
            )
            for x in range(width)
        ]
    )
    horizontal = horizontal.resize((width, height), Image.Resampling.NEAREST)

    vertical = Image.new("L", (1, height), 0)
    vertical.putdata(
        [
            255
            if y <= solid_height
            else round(
                255
                * _article_date_ease(
                    (height - 1 - y)
                    / max(1, height - 1 - solid_height)
                )
            )
            for y in range(height)
        ]
    )
    vertical = vertical.resize((width, height), Image.Resampling.NEAREST)
    return ImageChops.multiply(horizontal, vertical)


def decorate_article_cover(
    article_image: Image.Image,
    date_text: str,
    logo: Image.Image | None = None,
) -> Image.Image:
    cover = article_image.convert("RGBA").copy()
    draw_article_logo(cover, logo, (0, 0))
    date = re.sub(r"\s+", " ", str(date_text or "")).strip()
    if not date:
        return cover

    draw = ImageDraw.Draw(cover, "RGBA")
    date_font = fit_article_font_to_width(
        draw,
        date,
        330,
        22,
        12,
        article_date_font,
    )
    max_text_width = acx(330)
    if text_w(draw, date, date_font) > max_text_width:
        suffix = "..."
        while date and text_w(draw, date + suffix, date_font) > max_text_width:
            date = date[:-1].rstrip()
        date = (date + suffix) if date else suffix

    right_padding = acx(14)
    text_xy = (cover.width - right_padding, acy(25))
    if ARTICLE_DATE_SCRIM_ENABLED:
        fade_padding = acx(74)
        text_width = text_w(draw, date, date_font)
        gradient_width = min(
            cover.width,
            text_width + right_padding + fade_padding,
        )
        gradient_height = min(cover.height, acy(72))
        text_box = draw.textbbox(
            text_xy,
            date,
            font=date_font,
            anchor="rm",
        )
        scrim = Image.new(
            "RGBA",
            (gradient_width, gradient_height),
            (*ARTICLE_DATE_SCRIM_COLOR, 0),
        )
        scrim.putalpha(article_date_gradient_mask(
            gradient_width,
            gradient_height,
            article_date_scrim_alpha(cover, text_box),
            fade_padding,
        ))
        cover.alpha_composite(scrim, (cover.width - gradient_width, 0))

    shadow = Image.new("RGBA", cover.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow, "RGBA").text(
        (text_xy[0], text_xy[1] + acy(1)),
        date,
        font=date_font,
        fill=(0, 0, 0, 150),
        anchor="rm",
    )
    cover.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(acx(2))))
    ImageDraw.Draw(cover, "RGBA").text(
        text_xy,
        date,
        font=date_font,
        fill=ARTICLE_DATE_TEXT_COLOR,
        anchor="rm",
    )
    return cover


def _draw_article_vocab_card_legacy(img: Image.Image, item: dict | None, rect: tuple[int, int, int, int]) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    word = article_vocab_display_phrase(item.get("word") or "")
    phonetic = str(item.get("phonetic") or "").strip()
    pos = str(item.get("pos") or "词性").strip()
    meaning = str(item.get("meaning") or "").strip()
    definition = str(item.get("definition") or "").strip()
    tip_zh = str(item.get("tip_zh") or "结合当前意群理解这个词的作用。").strip()

    content_left = 940
    content_right = 1560
    word_font = fit_article_font_to_width(
        d, word, 340, 68, 44, article_vocab_phrase_font
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
        article_vocab_meaning_font,
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
        draw_stroked_text(d, (meaning_x, meaning_start_y + idx * meaning_gap), line, meaning_font, ARTICLE_VOCAB_MEANING_COLOR, anchor="lm", stroke_width=0)

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
            ARTICLE_VOCAB_DETAIL_COLOR,
        )


def draw_article_vocab_card(img: Image.Image, item: dict | None, rect: tuple[int, int, int, int]) -> None:
    """Render one calm expression card; concepts alone receive a third line."""
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = rect
    content_left_x = x0 + acx(ARTICLE_VOCAB_CONTENT_LEFT)
    content_width = max(
        1,
        round((x1 - x0) / ARTICLE_SCALE_X)
        - ARTICLE_VOCAB_CONTENT_LEFT
        - ARTICLE_VOCAB_CONTENT_RIGHT,
    )
    phrase = article_vocab_display_phrase(item.get("word") or "")
    meaning = str(item.get("meaning") or "").strip()
    detail = str(item.get("detail") or "").strip()
    detail_english_only = article_vocab_detail_is_english_only(detail)
    is_concept = vocab_card_type(item) == "concept" and bool(detail)

    phrase_font, phrase_lines = fit_article_vocab_phrase_font(
        d,
        phrase,
        max_width=content_width,
    )
    meaning_font, meaning_lines = fit_article_vocab_meaning_font(
        d,
        meaning,
        max_width=content_width,
    )
    detail_lines: list[list[str]] = []
    detail_size = 0
    detail_font = None
    if is_concept:
        detail_size, detail_lines = fit_article_vocab_detail_mixed_font(
            d,
            detail,
            max_width=content_width,
            max_lines=2,
            max_size=ARTICLE_VOCAB_DETAIL_FONT_SIZE,
            min_size=ARTICLE_VOCAB_DETAIL_MIN_FONT_SIZE,
            prefer_semantic_break=True,
        )
        detail_font = article_vocab_detail_font(detail_size)
    elif detail:
        detail_size, detail_lines = fit_article_vocab_detail_mixed_font(
            d,
            detail,
            max_width=content_width,
            max_lines=1,
            max_size=24,
            min_size=18,
            prefer_semantic_break=False,
        )
        detail_font = article_vocab_detail_font(detail_size)

    phrase_gap = int(phrase_font.size * 1.18)
    meaning_gap = int(meaning_font.size * 1.28)
    mixed_detail_line_size = 0
    if detail_font:
        mixed_detail_line_size = max(
            (
                article_vocab_detail_mixed_font(
                    token,
                    detail_size,
                    english_only=detail_english_only,
                ).size
                for line_tokens in detail_lines
                for token in line_tokens
            ),
            default=detail_font.size,
        )
    detail_gap = int(mixed_detail_line_size * 1.3) if detail_font else 0
    group_gap = acy(24)
    block_height = len(phrase_lines) * phrase_gap + group_gap + len(meaning_lines) * meaning_gap
    if detail_lines:
        block_height += group_gap + len(detail_lines) * detail_gap
    block_top = (y0 + y1 - block_height) // 2
    block_bottom = block_top + block_height
    # Match the opening title card's anchored blue rule to visible glyphs,
    # rather than the vertical gaps between phrase, meaning, and detail.
    visible_bounds: list[tuple[int, int]] = []
    measure_cursor_y = block_top
    for line in phrase_lines:
        box = d.textbbox(
            (content_left_x, measure_cursor_y),
            line,
            font=phrase_font,
            anchor="la",
        )
        visible_bounds.append((box[1], box[3]))
        measure_cursor_y += phrase_gap
    measure_cursor_y += group_gap
    for line in meaning_lines:
        box = d.textbbox(
            (content_left_x, measure_cursor_y),
            line,
            font=meaning_font,
            anchor="la",
        )
        visible_bounds.append((box[1], box[3]))
        measure_cursor_y += meaning_gap
    if detail_lines and detail_font:
        measure_cursor_y += group_gap
        for line_tokens in detail_lines:
            visible_bounds.append(
                article_vocab_detail_mixed_line_bounds(
                    d,
                    measure_cursor_y,
                    line_tokens,
                    detail_size,
                    english_only=detail_english_only,
                )
            )
            measure_cursor_y += detail_gap
    visible_top = min((bounds[0] for bounds in visible_bounds), default=block_top)
    visible_bottom = max((bounds[1] for bounds in visible_bounds), default=block_bottom)
    d.rectangle(
        (
            x0 + acx(ARTICLE_VOCAB_ACCENT_LEFT),
            visible_top,
            x0 + acx(ARTICLE_VOCAB_ACCENT_LEFT + ARTICLE_VOCAB_ACCENT_WIDTH),
            visible_bottom,
        ),
        fill=ARTICLE_BLUE,
    )
    cursor_y = block_top

    for line in phrase_lines:
        draw_stroked_text(
            d,
            (content_left_x, cursor_y),
            line,
            phrase_font,
            ARTICLE_BLUE,
            anchor="la",
            stroke_width=0,
        )
        cursor_y += phrase_gap
    cursor_y += group_gap
    for line in meaning_lines:
        draw_stroked_text(
            d,
            (content_left_x, cursor_y),
            line,
            meaning_font,
            ARTICLE_VOCAB_MEANING_COLOR,
            anchor="la",
            stroke_width=0,
        )
        cursor_y += meaning_gap
    if detail_lines and detail_font:
        cursor_y += group_gap
        for line_tokens in detail_lines:
            draw_article_vocab_detail_mixed_line(
                d,
                content_left_x,
                cursor_y,
                line_tokens,
                detail_size,
                ARTICLE_VOCAB_DETAIL_COLOR,
                english_only=detail_english_only,
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
    word = article_vocab_display_phrase(item.get("word") or "")
    pos = str(item.get("pos") or "").strip()
    meaning = str(item.get("meaning") or "").strip()
    word_font = fit_article_font_to_width(
        d,
        word,
        190,
        32,
        22,
        article_vocab_phrase_font,
    )
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
        article_vocab_meaning_font,
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
    draw_stroked_text(d, (divider_x + acx(16), center_y), meaning, meaning_font, ARTICLE_VOCAB_MEANING_COLOR, anchor="lm", stroke_width=0)


def draw_article_vocab_review_bar(
    img: Image.Image,
    item: dict,
    rect: tuple[int, int, int, int],
) -> None:
    """Keep the card container but leave only the expression and its gloss."""
    draw_article_panel(img, rect, acx(16), ARTICLE_CARD_CONTAINER)
    d = ImageDraw.Draw(img, "RGBA")
    phrase = article_vocab_display_phrase(item.get("word") or "")
    meaning = str(item.get("meaning") or "").strip()
    phrase_font = fit_article_font_to_width(
        d,
        phrase,
        500,
        34,
        16,
        article_vocab_phrase_font,
    )
    phrase_lines = [phrase]
    meaning_font = fit_article_font_to_width(
        d,
        meaning,
        440,
        26,
        18,
        article_vocab_meaning_font,
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
        ARTICLE_VOCAB_MEANING_COLOR,
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
        ARTICLE_VOCAB_DETAIL_COLOR,
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
        article_source_han_serif_cn_bold_font
        if has_cjk
        else (lambda size: article_en_font(size, 700)),
        wrap_article_title_text,
    )
    line_gap = int(title_font.size * 1.25)
    block_height = max(line_gap, len(title_lines) * line_gap)
    x0, y0, x1, y1 = rect
    title_x = x0 + acx(ARTICLE_VOCAB_CONTENT_LEFT)
    first_y = (y0 + y1 - block_height) // 2
    title_bounds = [
        d.textbbox((title_x, first_y + index * line_gap), line, font=title_font)
        for index, line in enumerate(title_lines)
    ]
    accent_y0 = min(bounds[1] for bounds in title_bounds)
    accent_y1 = max(bounds[3] for bounds in title_bounds)
    d.rectangle(
        (
            x0 + acx(ARTICLE_VOCAB_ACCENT_LEFT),
            accent_y0,
            x0 + acx(ARTICLE_VOCAB_ACCENT_LEFT + ARTICLE_VOCAB_ACCENT_WIDTH),
            accent_y1,
        ),
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
        max(
            meanings,
            key=lambda value: text_w(
                d,
                value,
                article_vocab_meaning_font(54),
            ),
            default="",
        ),
        330,
        46,
        30,
        article_vocab_meaning_font,
    )
    # Use the widest gloss to place a single left-aligned Chinese column. This
    # keeps all rows aligned while letting the longest item reach the right edge.
    meaning_right = 1030
    widest_meaning = max((text_w(d, meaning, meaning_font) for meaning in meanings), default=0)
    meaning_x = meaning_right - widest_meaning
    word_x = 116
    word_to_meaning_gap = 32
    for index, item in enumerate(upcoming):
        word = article_vocab_display_phrase(item.get("word") or "")
        meaning = meanings[index]
        # This is deliberately based on rendered pixel width rather than the
        # generic design-width helper: the overview card is drawn at a native
        # intermediate size before its final resize.
        word_available_width = max(1, meaning_x - word_x - word_to_meaning_gap)
        word_font = article_vocab_phrase_font(20)
        for size in range(68, 19, -2):
            candidate_font = article_vocab_phrase_font(size)
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
        draw_stroked_text(d, (meaning_x, meaning_y), meaning, meaning_font, ARTICLE_VOCAB_MEANING_COLOR, stroke_width=0)

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
    logo: Image.Image | None = None,
) -> Image.Image:
    img = Image.new("RGBA", (ARTICLE_WIDTH, ARTICLE_HEIGHT), (247, 243, 234, 255))
    d = ImageDraw.Draw(img, "RGBA")

    draw_article_panel(img, article_rect(16, 16, 900, 530), acx(16), ARTICLE_CARD_CONTAINER)
    cover = decorate_article_cover(article_image, date_text, logo)
    paste_rounded(img, cover, article_rect(31, 33, 885, 513), acx(8))

    vocab_rect = article_rect(916, 16, 1584, 530)
    vocab, vocab_state = vocab_card_display_state(vocab_plan, cue, display_time) if show_vocab else (None, "hidden")
    if vocab_state == "full" and vocab:
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
        zh_lines = wrap_article_zh(d, visual_zh, zh_font, acx(zh_width)) if visual_zh else []
        en_gap = int(en_font.size * ARTICLE_SUBTITLE_EN_LINE_HEIGHT_MULTIPLIER)
        zh_gap = 58
        en_count = max(1, len(en_lines))
        zh_count = max(0, len(zh_lines))
        en_y, zh_y = article_subtitle_origins(en_count, zh_count)
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
            zh_fill = with_alpha(ARTICLE_SUBTITLE_ZH_COLOR, subtitle_alpha)
            for idx, line in enumerate(zh_lines):
                draw_article_zh_line(
                    d,
                    ARTICLE_WIDTH // 2,
                    acy(zh_y) + idx * acy(zh_gap),
                    line,
                    zh_font,
                    zh_fill,
                )
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


def build_podcast_ffmpeg_command(
    media_path: str | Path,
    staged_output: str | Path,
    *,
    source_width: int,
    source_height: int,
    output_resolution: str,
) -> list[str]:
    """Build the deterministic upload-master encoding command."""
    target_width, target_height = PODCAST_OUTPUT_RESOLUTIONS.get(
        output_resolution,
        PODCAST_OUTPUT_RESOLUTIONS["1080p"],
    )
    keyframe_interval = FPS * PODCAST_KEYFRAME_INTERVAL_SECONDS
    command = [
        str(FFMPEG),
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{source_width}x{source_height}",
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
    ]
    if (target_width, target_height) != (source_width, source_height):
        command.extend(
            [
                "-vf",
                f"scale={target_width}:{target_height}:flags=lanczos",
            ]
        )
    command.extend(
        [
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "slow",
            "-crf",
            "15",
            "-bf",
            "2",
            "-g",
            str(keyframe_interval),
            "-keyint_min",
            str(keyframe_interval),
            "-sc_threshold",
            "0",
            "-flags",
            "+cgop",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-shortest",
            str(staged_output),
        ]
    )
    return command


def render_podcast_learning_video(
    media_path: str,
    subtitle_path: str,
    output_path: str,
    template_style: str = "暗色播客",
    output_resolution: str = "1080p",
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
    logo_path: str = "",
) -> None:
    cues = parse_srt(subtitle_path)
    if not cues:
        raise RuntimeError("字幕文件没有可用内容")
    is_article_template = template_style == "文章单词"
    article_logo = load_article_logo(logo_path) if is_article_template else None
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
    title_text = (title_text or TITLE_TEXT).strip() or TITLE_TEXT
    date_text = re.sub(r"\s+", " ", str(date_text or "")).strip()
    article_image = make_article_image(cover_path, (acx(854), acy(480))) if is_article_template else None
    if article_image is not None:
        article_image = decorate_article_cover(
            article_image,
            date_text,
            article_logo,
        )
        date_text = ""
        article_logo = None
    male, female = (None, None) if is_article_template else make_avatars()

    with staged_media_output(output_path) as staged_output:
        cmd = build_podcast_ffmpeg_command(
            media_path,
            staged_output,
            source_width=out_width,
            source_height=out_height,
            output_resolution=output_resolution,
        )
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
                                article_logo,
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
