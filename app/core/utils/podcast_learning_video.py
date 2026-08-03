# -*- coding: utf-8 -*-
import hashlib
import json
import logging
import math
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.config import BIN_PATH, CACHE_PATH, RESOURCE_PATH
from app.core.entities import LLMServiceEnum
from app.core.utils.json_repair import loads as repair_json_loads


logger = logging.getLogger(__name__)


WIDTH = 1920
HEIGHT = 1080
FPS = 25
VOCAB_REQUEST_TIMEOUT_SECONDS = 90
VOCAB_GENERATION_TIME_BUDGET_SECONDS = 240
VOCAB_REQUEST_MAX_GROUPS = 25
VOCAB_REQUEST_MAX_CHARS = 6000
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
VOCAB_CARDS_PER_MINUTE = 1.25
VOCAB_MIN_CARDS_PER_EPISODE = 3
VOCAB_MAX_CARDS_PER_EPISODE = 22
VOCAB_MAX_CONCEPT_CARDS_PER_EPISODE = 3
ARTICLE_SUBTITLE_EN_MIN_SIZE = 38
ARTICLE_AVOID_LINE_START_WORDS = frozenset(
    {"away", "back", "down", "in", "off", "on", "out", "over", "up"}
)
ARTICLE_MIXED_AVOID_LINE_START = frozenset(
    "来的是在于与和及或但而并把被将让使为对从向给由因比像就也都还又再已会能要"
)
ARTICLE_MIXED_PREFERRED_BREAK_AFTER = frozenset(
    "，。；：、来的于与和及或但而并把被将让使为对从向给由因比像"
)

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


@dataclass
class Cue:
    index: int
    start: float
    end: float
    en: str
    zh: str
    speaker: str


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
        if is_english(payload[0]):
            en = payload[0]
            zh = "".join(payload[1:])
        else:
            zh = payload[0]
            en = " ".join(payload[1:]) if len(payload) > 1 else payload[0]
        cues.append(Cue(len(cues) + 1, parse_ts(start_s), parse_ts(end_s), en, zh, speaker))
        if len(en.split()) >= 4 or en.endswith("?"):
            speaker = "female" if speaker == "male" else "male"
    return cues


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
        raise RuntimeError("无法读取音频/视频时长")
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


def schedule_vocab_card_plan(
    candidates: dict[int, dict],
    cues: list[Cue],
    *,
    max_cards: int = VOCAB_MAX_CARDS_PER_EPISODE,
) -> dict[int, dict]:
    """Start each card on its word's subtitle and keep it within that group."""
    cue_by_index = {cue.index: cue for cue in cues}
    groups = build_vocab_semantic_groups(cues)
    group_by_cue = {
        cue_index: group
        for group in groups
        for cue_index in group.cue_indices
    }
    scheduled: list[tuple[int, dict, VocabSemanticGroup]] = []
    selected_starts: list[float] = []
    selected_keys: set[str] = set()
    concept_cards = 0

    ranked_candidates = sorted(
        candidates.items(),
        key=lambda pair: (
            -vocab_card_priority(pair[1]),
            float(pair[1].get("group_start", math.inf)),
            pair[0],
        ),
    )
    for cue_index, item in ranked_candidates:
        cue = cue_by_index.get(cue_index)
        key = str(item.get("key") or "").strip().lower()
        group = group_by_cue.get(cue_index)
        if not cue or not key or not group:
            continue
        # Scores 1-2 are deliberately available to the model so it can signal
        # a marginal candidate, but such words are not strong enough to occupy
        # a visible learning-card slot.
        if vocab_card_priority(item) < 3:
            continue
        if key in selected_keys:
            continue
        if any(
            abs(cue.start - selected_start) < VOCAB_MIN_CARD_INTERVAL_SECONDS
            for selected_start in selected_starts
        ):
            continue
        scheduled_item = dict(item)
        if vocab_card_type(scheduled_item) == "concept":
            if concept_cards >= VOCAB_MAX_CONCEPT_CARDS_PER_EPISODE:
                scheduled_item["card_type"] = "standard"
                scheduled_item["detail"] = ""
            else:
                concept_cards += 1
        scheduled.append((cue_index, scheduled_item, group))
        selected_keys.add(key)
        selected_starts.append(cue.start)
        if len(scheduled) >= max(0, max_cards):
            break

    plan: dict[int, dict] = {}
    for cue_index, item, group in sorted(scheduled, key=lambda entry: entry[0]):
        trigger_cue = cue_by_index[cue_index]
        item["group_id"] = group.id
        item["group_cue_indices"] = list(group.cue_indices)
        # A card cannot foreshadow the word before its own subtitle appears.
        # It stays visible until the next card replaces it.
        item["display_start"] = trigger_cue.start
        item["display_id"] = f"{cue_index}:{item['key']}"
        plan[cue_index] = item

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
) -> dict[int, dict]:
    if not enabled:
        return {}

    groups = build_vocab_semantic_groups(cues)
    episode_card_target = vocabulary_card_target(cues)
    source_hash = vocab_source_hash(cues)
    cache_path = Path(subtitle_path).with_suffix(".vocab_cards.json")
    global_cache_dir = CACHE_PATH / "podcast_vocab_cards"
    global_cache_path = global_cache_dir / f"{source_hash}.json"
    base_url, api_key, model = current_llm_config()
    for candidate in (cache_path, global_cache_path):
        if not candidate.exists():
            continue
        try:
            cached = json.loads(candidate.read_text(encoding="utf-8"))
            if (
                cached.get("source_hash") == source_hash
                and cached.get("prompt_version") == VOCAB_PROMPT_VERSION
                and cached.get("model") == model
            ):
                cached_cards = cached.get("cards", [])
                plan = schedule_vocab_card_plan(
                    normalize_vocab_plan(cached_cards, cues, groups),
                    cues,
                    max_cards=episode_card_target,
                )
                if plan:
                    if progress_callback:
                        progress_callback(4, "智能单词卡命中缓存")
                    return apply_episode_vocab_ranks(
                        plan,
                        # Ranks are presentation-only. Recalculate them locally so
                        # older caches do not preserve a now-retired long-word bias.
                        fallback_episode_vocab_indices(plan),
                    )
                logger.warning(
                    "Vocabulary cache has no usable cards; regenerating instead of rendering an empty plan: %s",
                    candidate,
                )
        except Exception:
            pass

    if not base_url or not api_key or not model:
        if progress_callback:
            progress_callback(4, "智能单词卡未配置，已跳过")
        return {}

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
        cards = []
        failed_chunks: list[str] = []
        started_at = time.monotonic()
        request_groups = split_vocab_groups_for_requests(
            groups,
            max_groups=VOCAB_REQUEST_MAX_GROUPS,
            max_chars=VOCAB_REQUEST_MAX_CHARS,
        )
        cards_per_request = max(1, math.ceil(episode_card_target / max(1, len(request_groups))))
        for position, group_chunk in enumerate(request_groups, 1):
            if time.monotonic() - started_at >= VOCAB_GENERATION_TIME_BUDGET_SECONDS:
                failed_chunks.append(
                    f"{position}/{len(request_groups)}: generation time budget exhausted"
                )
                failed_chunks.extend(
                    f"{remaining}/{len(request_groups)}: generation time budget exhausted"
                    for remaining in range(position + 1, len(request_groups) + 1)
                )
                logger.warning(
                    "Vocabulary card generation stopped after %.1fs to keep video synthesis responsive.",
                    time.monotonic() - started_at,
                )
                break
            if progress_callback:
                progress_callback(
                    max(1, min(3, round(position * 3 / max(1, len(request_groups))))),
                    f"智能单词卡生成中（{position}/{len(request_groups)}）",
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
                        "Vocabulary card batch %s/%s failed on attempt %s: %s",
                        position,
                        len(request_groups),
                        attempt,
                        exc,
                    )
            if isinstance(chunk_cards, list):
                # The provider occasionally ignores a batch cardinality limit.
                # Enforce it locally using the requested editorial order/priority.
                cards.extend(
                    sorted(
                        (item for item in chunk_cards if isinstance(item, dict)),
                        key=vocab_card_priority,
                        reverse=True,
                    )[:cards_per_request]
                )
            else:
                failed_chunks.append(
                    f"{position}/{len(request_groups)}: {str(last_error or 'unknown error')[:120]}"
                )
        plan = schedule_vocab_card_plan(
            normalize_vocab_plan(cards, cues, groups),
            cues,
            max_cards=episode_card_target,
        )
        if plan:
            # Card ranking only affects the opening overview. A stable local
            # ranking avoids an extra LLM request without changing card content.
            overview_indices = fallback_episode_vocab_indices(plan)
            plan = apply_episode_vocab_ranks(plan, overview_indices)
        else:
            overview_indices = []
        if plan:
            payload = {
                "source_hash": source_hash,
                "prompt_version": VOCAB_PROMPT_VERSION,
                "model": model,
                "cards": cards,
                "episode_vocab_cue_indices": overview_indices,
            }
            cache_text = json.dumps(payload, ensure_ascii=False, indent=2)
            for candidate in (cache_path, global_cache_path):
                try:
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    candidate.write_text(cache_text, encoding="utf-8")
                except Exception:
                    pass
        else:
            logger.warning(
                "Vocabulary model returned no usable cards; empty result will not be cached. raw_cards=%s failed_batches=%s",
                len(cards),
                len(failed_chunks),
            )
        if progress_callback:
            if failed_chunks:
                progress_callback(
                    4,
                    f"智能单词卡部分生成完成（{len(failed_chunks)} 批失败，已跳过）",
                )
            elif not plan:
                progress_callback(4, "智能单词卡未选出合适单词，已跳过")
            else:
                progress_callback(4, "智能单词卡生成完成")
        return plan
    except Exception as exc:
        logger.exception("Vocabulary card generation failed: %s", exc)
        if progress_callback:
            progress_callback(4, f"智能单词卡生成失败，已跳过：{str(exc)[:100]}")
        return {}


def _has_short_caption_line(lines: list[str]) -> bool:
    """Reject a visual orphan such as a standalone ``And`` or ``of course``."""
    return len(lines) > 1 and any(len(line.split()) < 3 for line in lines)


def _caption_line_break_penalty(words: list[str], split: int) -> int:
    """Score a renderer-only line break without changing cue ownership."""
    previous = re.sub(r"[^A-Za-z']", "", words[split - 1]).lower()
    following = re.sub(r"[^A-Za-z']", "", words[split]).lower()
    penalty = 0
    if previous in LINE_BREAK_AVOID_AFTER_WORDS:
        penalty += CAPTION_HARD_BREAK_PENALTY
    if following in LINE_BREAK_AVOID_BEFORE_WORDS:
        penalty += CAPTION_HARD_BREAK_PENALTY
    if "-" in words[split - 1]:
        penalty += CAPTION_HARD_BREAK_PENALTY * 2
    if re.search(r"[,;:]$", words[split - 1]):
        penalty -= 1_200
    if re.search(r"[.!?]$", words[split - 1]):
        penalty -= 2_400
    return penalty


def _has_discouraged_caption_break(text: str, lines: list[str]) -> bool:
    if len(lines) != 2:
        return False
    words = text.split()
    first_line_words = len(lines[0].split())
    return (
        0 < first_line_words < len(words)
        and _caption_line_break_penalty(words, first_line_words) >= CAPTION_HARD_BREAK_PENALTY
    )


def wrap_en(draw, text: str, fnt, max_width: int) -> list[str]:
    """Choose a balanced two-line fit while retaining basic phrase units."""
    words = text.split()
    if text_w(draw, text, fnt) <= max_width:
        return [text]

    best = None
    best_score = 10**9
    for split in range(1, len(words)):
        # This is the one intentional improvement over the previous rule:
        # a subtitle line with one or two English words is not readable.
        if min(split, len(words) - split) < 3:
            continue
        a, b = " ".join(words[:split]), " ".join(words[split:])
        aw, bw = text_w(draw, a, fnt), text_w(draw, b, fnt)
        if aw <= max_width and bw <= max_width:
            score = abs(aw - bw) + _caption_line_break_penalty(words, split)
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


def wrap_en_preserving_highlight(draw, text: str, fnt, max_width: int, key: str | None) -> list[str]:
    """Avoid splitting the active vocabulary expression when a two-line fit permits it."""
    lines = wrap_en(draw, text, fnt, max_width)
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
    for split in range(3, len(words) - 2):
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
        break_penalty = _caption_line_break_penalty(words, split)
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

    if cue.zh:
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


def fit_article_en_font(draw, text: str, max_width: int) -> ImageFont.FreeTypeFont:
    max_width = acx(max_width)
    # Stable subtitle cues may be grammatically protected long sentences. Keep
    # a readable visual floor; callers display a third line when two are not
    # enough instead of silently omitting text.
    for size in range(58, ARTICLE_SUBTITLE_EN_MIN_SIZE - 1, -2):
        fnt = article_en_font(size, 600)
        lines = wrap_en(draw, text, fnt, max_width)
        if (
            len(lines) <= 2
            and all(text_w(draw, line, fnt) <= max_width for line in lines)
            and not _has_short_caption_line(lines)
            and not _has_discouraged_caption_break(text, lines)
        ):
            return fnt
    return article_en_font(ARTICLE_SUBTITLE_EN_MIN_SIZE, 600)


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
    previous = re.sub(r"[^A-Za-z']", "", words[split - 1])
    following = re.sub(r"[^A-Za-z']", "", words[split])
    previous_lower = previous.lower()
    following_lower = following.lower()
    penalty = _caption_line_break_penalty(words, split)
    if following_lower in ARTICLE_AVOID_LINE_START_WORDS:
        penalty += CAPTION_HARD_BREAK_PENALTY
    if previous.endswith("ly"):
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
            wrap_article_mixed_text,
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
        (lambda size: article_cjk_font(size, 700)) if has_cjk else (lambda size: article_en_font(size, 700)),
        wrap_article_mixed_text if has_cjk else wrap_en,
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
        key = vocab["key"] if vocab else None
        en_x = 68
        en_width = 1455
        en_font = fit_article_en_font(d, cue.en, en_width)
        en_lines = wrap_article_en_subtitle(d, cue.en, en_font, acx(en_width))
        if len(en_lines) == 2:
            en_lines = wrap_en_preserving_highlight(d, cue.en, en_font, acx(en_width), key)
        highlight_ranges = highlight_ranges_for_lines(en_lines, key)
        zh_font = article_cjk_font(46, 700)
        zh_width = 1455
        zh_lines = wrap_zh(d, cue.zh, zh_font, acx(zh_width))[:2] if cue.zh else []
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
        if zh_lines:
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
) -> None:
    cues = parse_srt(subtitle_path)
    if not cues:
        raise RuntimeError("字幕文件没有可用内容")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    vocab_plan = load_or_generate_vocab_plan(
        subtitle_path,
        cues,
        show_ai_vocab,
        progress_callback=progress_callback,
    )
    # The template is a video presentation of the source media, not a subtitle
    # clip. Keep the entire audio/video even when its final subtitle ends early.
    duration = get_duration(media_path)
    frames = int(math.ceil(duration * FPS))
    is_article_template = template_style == "文章单词"
    out_width = ARTICLE_WIDTH if is_article_template else WIDTH
    out_height = ARTICLE_HEIGHT if is_article_template else HEIGHT
    base = None if is_article_template else make_base(background_path)
    article_image = make_article_image(cover_path, (acx(854), acy(480))) if is_article_template else None
    male, female = (None, None) if is_article_template else make_avatars()
    title_text = (title_text or TITLE_TEXT).strip() or TITLE_TEXT
    date_text = (date_text or "Jul 23rd 2026").strip() or "Jul 23rd 2026"

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
        str(output_path),
    ]
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=False,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    last_index = 0
    last_cue_key = object()
    cached_frame_bytes = None
    try:
        for frame_index in range(frames):
            t = frame_index / FPS
            cue, last_index = active_cue(cues, t, last_index)
            alpha = fade_alpha(cue, t)
            vocab, vocab_state = vocab_card_display_state(vocab_plan, cue, t) if show_ai_vocab else (None, "hidden")
            vocab_display_id = (
                f"{vocab.get('display_id', '')}:{vocab_state}" if vocab else None
            )
            cue_key = (
                template_style,
                cue.start if cue else None,
                cue.end if cue else None,
                cue.en if cue else None,
                cue.zh if cue else None,
                alpha,
                title_text,
                vocab_display_id,
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
                    ).convert("RGB")
                cached_frame_bytes = frame.tobytes()
                last_cue_key = cue_key
            process.stdin.write(cached_frame_bytes)
            if progress_callback and (frame_index % 25 == 0 or frame_index == frames - 1):
                progress_callback(int(frame_index / max(frames - 1, 1) * 100), "英语学习模板渲染中")
        process.stdin.close()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError("模板视频合成失败")
    finally:
        if process.poll() is None:
            process.kill()
