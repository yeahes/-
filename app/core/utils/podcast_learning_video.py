# -*- coding: utf-8 -*-
import hashlib
import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.config import BIN_PATH, CACHE_PATH, RESOURCE_PATH
from app.core.entities import LLMServiceEnum
from app.core.utils.json_repair import loads as repair_json_loads


WIDTH = 1920
HEIGHT = 1080
FPS = 25
SX = WIDTH / 1879
SY = HEIGHT / 1056
ARTICLE_DESIGN_WIDTH = 1600
ARTICLE_DESIGN_HEIGHT = 900
ARTICLE_WIDTH = 1920
ARTICLE_HEIGHT = 1080
ARTICLE_SCALE_X = ARTICLE_WIDTH / ARTICLE_DESIGN_WIDTH
ARTICLE_SCALE_Y = ARTICLE_HEIGHT / ARTICLE_DESIGN_HEIGHT

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
VOCAB_CARD_CENTER_X0 = 940
VOCAB_CARD_TOP_Y0 = 430
VOCAB_CARD_WIDTH0 = 608
VOCAB_CARD_HEIGHT0 = 138
EN_SUBTITLE_CENTER_Y0 = 700
ZH_SUBTITLE_CENTER_Y0 = 912
SUBTITLE_FADE_SECONDS = 0.22
SUBTITLE_MIN_ALPHA = 175
VOCAB_PROMPT_VERSION = 3

BREAK_BEFORE_WORDS = {
    "about", "above", "across", "after", "against", "although", "among", "around",
    "as", "because", "before", "beneath", "beside", "between", "but", "by",
    "despite", "during", "except", "for", "from", "if", "in", "inside", "into",
    "like", "near", "of", "on", "onto", "or", "over", "since", "so", "than",
    "that", "through", "to", "unless", "until", "when", "where", "which", "while",
    "who", "whose", "with", "without", "yet",
}
AVOID_BREAK_AFTER_WORDS = {"a", "an", "the", "this", "that", "these", "those", "my", "your", "our", "their"}


@dataclass
class Cue:
    index: int
    start: float
    end: float
    en: str
    zh: str
    speaker: str


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


def acx(value: float) -> int:
    return round(value * ARTICLE_SCALE_X)


def acy(value: float) -> int:
    return round(value * ARTICLE_SCALE_Y)


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
    if FONT_HANCHAN_MEDIUM.exists():
        return font(FONT_HANCHAN_MEDIUM, size, weight)
    return font(FONT_DOUYIN if FONT_DOUYIN.exists() else FONT_YAHEI, size)


def article_mixed_font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    return font(FONT_YAHEI, acx(size), weight)


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


def normalize_vocab_plan(raw_items, cues: list[Cue]) -> dict[int, dict]:
    cue_by_index = {cue.index: cue for cue in cues}
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
        cue = cue_by_index.get(cue_index)
        word = str(item.get("word") or "").strip()
        phonetic = str(item.get("phonetic") or "").strip()[:36]
        level = str(item.get("level") or "").strip()[:20]
        pos = str(item.get("part_of_speech") or item.get("pos") or "").strip()[:12]
        meaning = str(item.get("meaning") or "").strip()[:40]
        definition = str(item.get("definition") or "").strip()[:120]
        tip = str(item.get("tip") or "").strip()[:120]
        if not cue or not word or not meaning:
            continue
        key_match = re.search(r"[A-Za-z]+(?:['-][A-Za-z]+)?", word)
        if not key_match:
            continue
        key = key_match.group(0).lower()
        if key in COMMON_WORDS or not re.search(rf"\b{re.escape(key)}\b", cue.en.lower()):
            continue
        plan[cue_index] = {
            "keys": [key],
            "key": key,
            "word": word[:24].capitalize(),
            "phonetic": phonetic,
            "level": level or "核心词",
            "pos": pos or "n.",
            "meaning": meaning,
            "definition": definition or "A useful word for understanding the sentence.",
            "tip": tip or "Notice how this word shapes the sentence meaning.",
        }
    return plan


def load_or_generate_vocab_plan(
    subtitle_path: str | Path,
    cues: list[Cue],
    enabled: bool,
    progress_callback=None,
) -> dict[int, dict]:
    if not enabled:
        return {}

    source_hash = vocab_source_hash(cues)
    legacy_source_hash = subtitle_hash(cues)
    cache_path = Path(subtitle_path).with_suffix(".vocab_cards.json")
    global_cache_dir = CACHE_PATH / "podcast_vocab_cards"
    global_cache_path = global_cache_dir / f"{source_hash}.json"
    for candidate in (cache_path, global_cache_path):
        if not candidate.exists():
            continue
        try:
            cached = json.loads(candidate.read_text(encoding="utf-8"))
            cached_hash = cached.get("source_hash")
            if cached_hash in {source_hash, legacy_source_hash} and cached.get("prompt_version") == VOCAB_PROMPT_VERSION:
                if progress_callback:
                    progress_callback(4, "智能单词卡命中缓存")
                return normalize_vocab_plan(cached.get("cards", []), cues)
        except Exception:
            pass

    base_url, api_key, model = current_llm_config()
    if not base_url or not api_key or not model:
        if progress_callback:
            progress_callback(4, "智能单词卡未配置，已跳过")
        return {}

    if progress_callback:
        progress_callback(1, "智能单词卡生成中")

    lines = "\n".join(f"{cue.index}. {cue.en}" for cue in cues if cue.en.strip())
    prompt = f"""
你是英语学习视频的词汇编辑。请根据下面按序号排列的英文字幕，挑选适合做单词卡的词。

要求：
- 只选择较难、信息量高、对理解句子有帮助的词。
- 避免过于常见的词、口头语、专有名词和重复出现太多的词。
- 按连续语义意群挑词；每个意群最多选1个词，不需要每条字幕都选。
- cue_index填这个词首次出现的字幕序号；该词会显示到下一个单词卡出现。
- 总数控制在18到32个之间；短字幕可更少。
- word必须是该字幕原文中真实出现的英文词或词形。
- phonetic给出英式或美式音标，必须带 / /，例如 /ˈreɡjələtɔːri/。
- meaning先给出原文语境下的中文意思，如有常见其他含义，用 / 补充。
- pos给出词性缩写，例如 n.、v.、adj.。
- definition给出一句适合英语学习者的英文解释，尽量短。
- tip给出一句学习提示，说明这个词在原句中的理解重点。
- level使用 CET-4、CET-6、IELTS、TOEFL、GRE、专业词 之一。
- 只返回JSON数组，不要解释。

格式：
[
  {{"cue_index": 12, "word": "regulatory", "phonetic": "/ˈreɡjələtɔːri/", "level": "IELTS", "pos": "adj.", "meaning": "监管的/调节的", "definition": "Related to rules or official control.", "tip": "It often describes systems controlled by laws or institutions."}}
]

英文字幕：
{lines}
""".strip()

    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=60)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        cards = extract_json_array(content)
        payload = {
            "source_hash": source_hash,
            "prompt_version": VOCAB_PROMPT_VERSION,
            "model": model,
            "cards": cards,
        }
        cache_text = json.dumps(payload, ensure_ascii=False, indent=2)
        for candidate in (cache_path, global_cache_path):
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text(cache_text, encoding="utf-8")
            except Exception:
                pass
        if progress_callback:
            progress_callback(4, "智能单词卡生成完成")
        return normalize_vocab_plan(cards, cues)
    except Exception:
        if progress_callback:
            progress_callback(4, "智能单词卡生成失败，已跳过")
        return {}


def wrap_en(draw, text: str, fnt, max_width: int) -> list[str]:
    words = text.split()
    if text_w(draw, text, fnt) <= max_width:
        return [text]
    best = None
    best_score = 10**9
    for split in range(1, len(words)):
        a, b = " ".join(words[:split]), " ".join(words[split:])
        aw, bw = text_w(draw, a, fnt), text_w(draw, b, fnt)
        if aw <= max_width and bw <= max_width:
            prev_word = re.sub(r"[^A-Za-z']", "", words[split - 1]).lower()
            next_word = re.sub(r"[^A-Za-z']", "", words[split]).lower()
            phrase_bonus = 0
            if re.search(r"[,;:]$", words[split - 1]):
                phrase_bonus -= 900
            if next_word in BREAK_BEFORE_WORDS:
                phrase_bonus -= 620
            if prev_word in AVOID_BREAK_AFTER_WORDS:
                phrase_bonus += 950
            if min(split, len(words) - split) <= 1:
                phrase_bonus += 700
            score = abs(aw - bw) + phrase_bonus
            if score < best_score:
                best = [a, b]
                best_score = score
    if best:
        return best
    lines, cur = [], []
    for word in words:
        cand = " ".join(cur + [word])
        if cur and text_w(draw, cand, fnt) > max_width:
            lines.append(" ".join(cur))
            cur = [word]
        else:
            cur.append(word)
    if cur:
        lines.append(" ".join(cur))
    return lines


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


def fit_en_font(draw, text: str, max_width: int) -> ImageFont.FreeTypeFont:
    for size in range(70, 35, -2):
        fnt = font(FONT_GANTARI, size, 600)
        lines = wrap_en(draw, text, fnt, max_width)
        if len(lines) <= 2 and all(text_w(draw, line, fnt) <= max_width for line in lines):
            return fnt
    return font(FONT_GANTARI, 34, 600)


def fit_title_font(draw, title: str, max_width: int) -> ImageFont.FreeTypeFont:
    for size in range(TITLE_MAX_FONT_SIZE, TITLE_MIN_FONT_SIZE - 1, -2):
        fnt = cjk_font(size)
        if text_w(draw, title, fnt) <= max_width:
            return fnt
    return cjk_font(TITLE_MIN_FONT_SIZE)


def draw_highlighted_line(img: Image.Image, draw, x: int, y: int, line: str, key: str | None, fnt, alpha: int = 255) -> None:
    white = with_alpha(SUBTITLE_EN, alpha)
    blue = with_alpha(BLUE, alpha)
    if not key or key.lower() not in line.lower():
        draw_subtitle_shadowed_text(img, draw, (x, y), line, fnt, white, anchor="mm", alpha=alpha)
        return
    lower = line.lower()
    start = lower.find(key.lower())
    end = start + len(key)
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
    level_font = font(FONT_GANTARI, 22, 650)
    meaning_font = cjk_font(28)
    word_x = x0 + scx(23)
    word_y = y0 + scy(10)
    draw_stroked_text(d, (word_x, word_y), word, word_font, BLUE, stroke_width=0)
    word_right = word_x + text_w(d, word, word_font)
    phonetic = str(item.get("phonetic") or "").strip()
    if phonetic:
        draw_stroked_text(d, (word_right + scx(16), y0 + scy(28)), phonetic, phonetic_font, MUTED, stroke_width=0)

    level = str(item["level"]).strip()
    level_text_w = text_w(d, level, level_font)
    tag_x0 = x0 + scx(24)
    tag_y0 = y0 + scy(85)
    tag_x1 = tag_x0 + level_text_w + scx(24)
    tag_y1 = tag_y0 + scy(31)
    d.rounded_rectangle((tag_x0, tag_y0, tag_x1, tag_y1), radius=scx(9), fill=(0, 124, 255, 225))
    draw_stroked_text(d, ((tag_x0 + tag_x1) // 2, (tag_y0 + tag_y1) // 2 - scy(1)), level, level_font, WHITE, anchor="mm", stroke_width=0)
    meaning = str(item["meaning"]).strip()
    meaning_x = tag_x1 + scx(16)
    meaning_y = y0 + scy(83)
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

    vocab = ((vocab_plan or {}).get(cue.index) or find_vocab(cue.en)) if show_vocab else None
    key = vocab["key"] if vocab else None
    en_width = scx(1459)
    en_font = fit_en_font(d, cue.en, en_width)
    en_lines = wrap_en(d, cue.en, en_font, en_width)
    line_gap = int(en_font.size * 1.06)
    en_start_y = scy(EN_SUBTITLE_CENTER_Y0) - (len(en_lines) - 1) * line_gap // 2
    for idx, line in enumerate(en_lines):
        draw_highlighted_line(img, d, WIDTH // 2, en_start_y + idx * line_gap, line, key, en_font, subtitle_alpha)

    if cue.zh:
        zh_font = cjk_font(50)
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

    if vocab and cue.end - cue.start > 1.0:
        draw_vocab_card(img, vocab)
    return img


def fit_article_en_font(draw, text: str, max_width: int) -> ImageFont.FreeTypeFont:
    max_width = acx(max_width)
    for size in range(58, 39, -2):
        fnt = article_en_font(size, 600)
        lines = wrap_en(draw, text, fnt, max_width)
        if len(lines) <= 2 and all(text_w(draw, line, fnt) <= max_width for line in lines):
            return fnt
    return article_en_font(40, 600)


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
    return lines or [""]


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


def normalize_article_date(date_text: str) -> str:
    date = (date_text or "").strip() or "Jul 23rd 2026"
    month_map = {
        "january": "Jan",
        "february": "Feb",
        "march": "Mar",
        "april": "Apr",
        "may": "May",
        "june": "Jun",
        "july": "Jul",
        "august": "Aug",
        "september": "Sep",
        "october": "Oct",
        "november": "Nov",
        "december": "Dec",
    }
    match = re.match(r"^([A-Za-z]+)(\b.*)$", date)
    if match:
        month = month_map.get(match.group(1).lower())
        if month:
            return month + match.group(2)
    return date


def decorate_article_cover(article_image: Image.Image, date_text: str) -> Image.Image:
    cover = article_image.convert("RGBA").copy()
    d = ImageDraw.Draw(cover, "RGBA")
    draw_economist_logo(cover, (0, 0))
    date = normalize_article_date(date_text)
    date_rect = article_rect(673, 0, 854, 44)
    d.rectangle(date_rect, fill=(234, 241, 255, 255))
    date_font = fit_article_font_to_width(
        d,
        date,
        166,
        24,
        16,
        lambda size: article_en_font(size, 500),
    )
    date_x = (date_rect[0] + date_rect[2]) // 2
    date_y = date_rect[1] + (date_rect[3] - text_h(d, date, date_font)) // 2 - acy(2)
    draw_stroked_text(d, (date_x, date_y), date, date_font, (47, 111, 237, 255), anchor="ma", stroke_width=0)
    return cover


def draw_article_vocab_card(img: Image.Image, item: dict | None, rect: tuple[int, int, int, int]) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    draw_article_panel(img, rect, acx(16), (255, 253, 248, 255))
    word = str(item.get("word") or "").strip().capitalize()
    phonetic = str(item.get("phonetic") or "").strip()
    pos = str(item.get("part_of_speech") or item.get("pos") or "").strip()
    meaning = str(item.get("meaning") or "").strip()
    definition = str(item.get("definition") or "").strip()
    tip = str(item.get("tip") or "").strip()

    word_font = fit_article_font_to_width(
        d,
        word,
        620,
        68,
        44,
        lambda size: article_en_font(size, 700),
    )
    phonetic_path = FONT_CAMBRIA if FONT_CAMBRIA.exists() else FONT_SEGOE
    phonetic_font = fit_article_font_to_width(
        d,
        phonetic,
        620,
        32,
        22,
        lambda size: font(phonetic_path if phonetic_path.exists() else FONT_GANTARI, size, 400),
    )
    meaning_font, meaning_lines = fit_article_wrapped_font(
        d,
        meaning,
        596,
        2,
        40,
        28,
        lambda size: article_cjk_font(size, 500),
        wrap_zh,
    )
    pos_font = fit_article_font_to_width(
        d,
        pos[:8],
        44,
        24,
        16,
        lambda size: article_en_font(size, 600),
    )
    def_font, definition_lines = fit_article_wrapped_font(
        d,
        definition,
        540,
        2,
        28,
        20,
        lambda size: article_en_font(size, 500),
        wrap_en,
    )
    tip_label_font = article_en_font(28, 700)
    tip_body_font, tip_lines = fit_article_wrapped_font(
        d,
        tip,
        524,
        2,
        24,
        18,
        lambda size: article_mixed_font(size, 400),
        wrap_article_mixed_text,
    )

    draw_stroked_text(d, (acx(940), acy(32)), word, word_font, (47, 111, 237, 255), stroke_width=0)
    draw_stroked_text(d, (acx(940), acy(126)), phonetic, phonetic_font, (122, 132, 147, 255), stroke_width=0)
    draw_dashed_line(d, (acx(940), acy(188)), (acx(1560), acy(188)), fill=(122, 132, 147, 150), width=1)

    for idx, line in enumerate(meaning_lines[:2]):
        draw_stroked_text(d, (acx(940), acy(212) + idx * int(meaning_font.size * 1.18)), line, meaning_font, (79, 91, 107, 255), stroke_width=0)

    d.rounded_rectangle(article_rect(940, 284, 1004, 320), radius=acx(4), fill=(234, 241, 255, 255))
    draw_stroked_text(d, (acx(972), acy(288)), pos[:8], pos_font, (47, 111, 237, 255), anchor="ma", stroke_width=0)
    for idx, line in enumerate(definition_lines[:2]):
        draw_stroked_text(d, (acx(1020), acy(292 + idx * 36)), line, def_font, (122, 132, 147, 255), stroke_width=0)

    d.rounded_rectangle(article_rect(940, 387, 1560, 506), radius=acx(8), fill=(234, 241, 255, 255))
    if ARTICLE_TIP_ICON.exists():
        try:
            icon = Image.open(ARTICLE_TIP_ICON).convert("RGBA").resize((acx(48), acy(48)), Image.Resampling.LANCZOS)
            img.alpha_composite(icon, (acx(956), acy(403)))
        except Exception:
            d.ellipse(article_rect(956, 403, 1004, 451), fill=(47, 111, 237, 255))
            bulb_font = article_en_font(28, 700)
            draw_stroked_text(d, (acx(980), acy(428)), "!", bulb_font, (255, 255, 255, 255), anchor="mm", stroke_width=0)
    else:
        d.ellipse(article_rect(956, 403, 1004, 451), fill=(47, 111, 237, 255))
        bulb_font = article_en_font(28, 700)
        draw_stroked_text(d, (acx(980), acy(428)), "!", bulb_font, (255, 255, 255, 255), anchor="mm", stroke_width=0)
    draw_stroked_text(d, (acx(1020), acy(403)), "TIP", tip_label_font, (47, 111, 237, 255), stroke_width=0)
    for idx, line in enumerate(tip_lines[:2]):
        draw_stroked_text(d, (acx(1020), acy(436) + idx * int(tip_body_font.size * 1.28)), line, tip_body_font, (122, 132, 147, 255), stroke_width=0)


def active_article_vocab(vocab_plan: dict[int, dict] | None, cue_index: int) -> dict | None:
    if not vocab_plan:
        return None
    eligible = [idx for idx in vocab_plan if idx <= cue_index]
    if not eligible:
        return None
    return vocab_plan.get(max(eligible))


def draw_article_frame(
    article_image: Image.Image,
    cue: Cue | None,
    vocab_plan: dict[int, dict] | None = None,
    subtitle_alpha: int = 255,
    show_vocab: bool = False,
    title_text: str = TITLE_TEXT,
    date_text: str = "Jul 23rd 2026",
) -> Image.Image:
    img = Image.new("RGBA", (ARTICLE_WIDTH, ARTICLE_HEIGHT), (247, 243, 234, 255))
    d = ImageDraw.Draw(img, "RGBA")

    draw_article_panel(img, article_rect(16, 16, 900, 530), acx(16), (255, 253, 248, 255))
    cover = decorate_article_cover(article_image, date_text)
    paste_rounded(img, cover, article_rect(31, 33, 885, 513), acx(8))

    vocab_rect = article_rect(916, 16, 1584, 530)
    vocab = active_article_vocab(vocab_plan, cue.index) if cue and show_vocab else None
    if cue and show_vocab and not vocab:
        vocab = find_vocab(cue.en)
    if vocab:
        draw_article_vocab_card(img, vocab, vocab_rect)
    else:
        draw_article_panel(img, vocab_rect, acx(16), (255, 253, 248, 255))

    draw_article_panel(img, article_rect(16, 546, 1584, 884), acx(16), (241, 236, 227, 255))

    if cue:
        key = vocab["key"] if vocab else None
        en_x = 68
        en_width = 1455
        en_font = fit_article_en_font(d, cue.en, en_width)
        en_lines = wrap_en(d, cue.en, en_font, acx(en_width))[:2]
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
        else:
            en_y, zh_y = 560, 736
        for idx, line in enumerate(en_lines):
            fill = with_alpha((42, 63, 93, 255), subtitle_alpha)
            if key and key.lower() in line.lower():
                draw_highlighted_article_line(d, acx(en_x + en_width // 2), acy(en_y) + idx * en_gap, line, key, en_font, fill, with_alpha(ARTICLE_BLUE, subtitle_alpha))
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
) -> None:
    lower = line.lower()
    start = lower.find(key.lower())
    if start < 0:
        draw_stroked_text(draw, (x, y), line, fnt, fill, stroke_width=0)
        return
    end = start + len(key)
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
            cue_key = (template_style, cue.start, cue.end, cue.en, cue.zh, alpha, title_text) if cue else (template_style, None, title_text)
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
