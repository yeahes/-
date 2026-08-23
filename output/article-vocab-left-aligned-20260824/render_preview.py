from pathlib import Path
import sys

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.utils import podcast_learning_video as renderer


OUTPUT_DIR = Path(__file__).resolve().parent
SOURCE_PATH = ROOT / "work-dir" / "wound-down-preview-cover.png"


def article_cover() -> Image.Image:
    with Image.open(SOURCE_PATH) as source:
        source = source.convert("RGB").crop((122, 0, source.width, source.height))
        return renderer.fit_cover(source, (renderer.acx(854), renderer.acy(480)))


def cue() -> renderer.Cue:
    value = renderer.Cue(
        9901,
        0.0,
        8.0,
        "This frame audits the vocabulary card layout.",
        "这一帧用于检查单词卡的左对齐布局。",
        "male",
        subtitle_id="S9901",
    )
    value.word_timing = tuple(
        {
            "word_id": index,
            "surface": word,
            "start": float(index),
            "end": float(index) + 0.7,
        }
        for index, word in enumerate(value.en.split())
    )
    return value


def render_card(filename: str, item: dict) -> Path:
    frame = renderer.draw_article_frame(
        article_cover(),
        cue(),
        vocab_plan={9901: {**item, "display_start": 0.0}},
        show_vocab=True,
        display_time=0.0,
        title_text="单词卡左对齐预览",
    )
    path = OUTPUT_DIR / filename
    frame.convert("RGB").save(path, quality=95)
    return path


def make_contact_sheet(paths: list[Path]) -> Path:
    width, height = 960, 540
    sheet = Image.new("RGB", (width * 2, height), (234, 230, 222))
    for index, path in enumerate(paths):
        with Image.open(path) as image:
            thumb = image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (index * width, 0))
    output = OUTPUT_DIR / "left-aligned-contact-sheet.png"
    sheet.save(output, quality=95)
    return output


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        render_card(
            "01-common-left-aligned-card.png",
            {
                "key": "black-box algorithm",
                "word": "black-box algorithm",
                "meaning": "黑箱算法",
                "detail": "能给出结论，却无法说明 AI agent 的判断过程。",
                "card_type": "concept",
            },
        ),
        render_card(
            "02-long-left-aligned-card.png",
            {
                "key": "cross-border regulatory compliance framework",
                "word": "cross-border regulatory compliance framework",
                "meaning": "跨境监管合规制度框架与执行机制",
                "detail": "A concise explanation of how the framework works in practice.",
                "card_type": "concept",
            },
        ),
    ]
    for path in paths:
        print(path)
    print(make_contact_sheet(paths))


if __name__ == "__main__":
    main()
