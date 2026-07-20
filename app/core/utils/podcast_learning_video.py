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

from app.config import BIN_PATH, RESOURCE_PATH
from app.core.entities import LLMServiceEnum
from app.core.utils.json_repair import loads as repair_json_loads


WIDTH = 1920
HEIGHT = 1080
FPS = 25
SX = WIDTH / 1879
SY = HEIGHT / 1056

TEMPLATE_DIR = RESOURCE_PATH / "podcast_template"
BACKGROUND = TEMPLATE_DIR / "background.png"
AVATAR_SOURCE = TEMPLATE_DIR / "hosts.png"
FONT_GANTARI = TEMPLATE_DIR / "Gantari-wght.ttf"
FONT_DIR = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"
FONT_DOUYIN = FONT_DIR / "douyinmeihaoti.otf"
FONT_YAHEI = Path("C:/Windows/Fonts/msyh.ttc")
FONT_SEGOE = Path("C:/Windows/Fonts/segoeui.ttf")
FFMPEG = BIN_PATH / "ffmpeg.exe"

TITLE_TEXT = "为什么人工智能会改变教育?"
TITLE_SAFE_LEFT_X0 = 410
TITLE_SAFE_RIGHT_X0 = 1470
TITLE_CENTER_Y0 = 234
TITLE_MAX_FONT_SIZE = 70
TITLE_MIN_FONT_SIZE = 40
BLUE = (0, 234, 255, 255)
MUTED = (153, 153, 153, 255)
WHITE = (245, 248, 255, 255)
SUBTITLE_EN = (220, 224, 232, 255)
SUBTITLE_ZH = (202, 206, 214, 255)
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
VOCAB_PROMPT_VERSION = 2

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


def text_w(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


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


def make_base() -> Image.Image:
    bg = fit_cover(Image.open(BACKGROUND).convert("RGB"), (WIDTH, HEIGHT))
    bg = bg.filter(ImageFilter.GaussianBlur(10))
    bg = ImageEnhance.Contrast(bg).enhance(0.84)
    img = bg.convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay, "RGBA")
    d.rectangle((0, 0, WIDTH, HEIGHT), fill=(0, 0, 0, 155))
    for y in range(HEIGHT):
        alpha = int(22 + 132 * (y / HEIGHT))
        d.line((0, y, WIDTH, y), fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, overlay)
    noise = Image.effect_noise((WIDTH, HEIGHT), 1.6).convert("L")
    noise = ImageChops.add(noise, Image.new("L", (WIDTH, HEIGHT), 128), scale=1.0, offset=-128)
    noise_rgba = Image.merge("RGBA", (noise, noise, noise, Image.new("L", (WIDTH, HEIGHT), 18)))
    return Image.alpha_composite(img, noise_rgba)


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
        meaning = str(item.get("meaning") or "").strip()[:28]
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
            "meaning": meaning,
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

    source_hash = subtitle_hash(cues)
    cache_path = Path(subtitle_path).with_suffix(".vocab_cards.json")
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("source_hash") == source_hash and cached.get("prompt_version") == VOCAB_PROMPT_VERSION:
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
- 每条字幕最多选1个词，不需要每条都选。
- 总数控制在18到32个之间；短字幕可更少。
- word必须是该字幕原文中真实出现的英文词或词形。
- phonetic给出英式或美式音标，必须带 / /，例如 /ˈreɡjələtɔːri/。
- meaning先给出原文语境下的中文意思，如有常见其他含义，用 / 补充。
- level使用 CET-4、CET-6、IELTS、TOEFL、GRE、专业词 之一。
- 只返回JSON数组，不要解释。

格式：
[
  {{"cue_index": 12, "word": "regulatory", "phonetic": "/ˈreɡjələtɔːri/", "level": "IELTS", "meaning": "adj. 监管的/调节的"}}
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
        cache_path.write_text(
            json.dumps(
                {"source_hash": source_hash, "prompt_version": VOCAB_PROMPT_VERSION, "model": model, "cards": cards},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
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
    phonetic_font = font(FONT_SEGOE if FONT_SEGOE.exists() else FONT_GANTARI, 27, 430)
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
        MUTED,
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
        zh_font = cjk_font(52)
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


def render_podcast_learning_video(
    media_path: str,
    subtitle_path: str,
    output_path: str,
    progress_callback=None,
) -> None:
    cues = parse_srt(subtitle_path)
    if not cues:
        raise RuntimeError("字幕文件没有可用内容")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    from app.common.config import cfg

    vocab_plan = load_or_generate_vocab_plan(
        subtitle_path,
        cues,
        cfg.podcast_template_ai_vocab.value,
        progress_callback=progress_callback,
    )
    duration = min(get_duration(media_path), max(cue.end for cue in cues) + 0.5)
    frames = int(math.ceil(duration * FPS))
    base = make_base()
    male, female = make_avatars()
    title_text = (cfg.podcast_template_title.value or TITLE_TEXT).strip() or TITLE_TEXT

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
        f"{WIDTH}x{HEIGHT}",
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
            cue_key = (cue.start, cue.end, cue.en, cue.zh, alpha, title_text) if cue else (None, title_text)
            if cue_key != last_cue_key:
                frame = draw_frame(
                    base,
                    male,
                    female,
                    cue,
                    vocab_plan,
                    alpha,
                    cfg.podcast_template_ai_vocab.value,
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
