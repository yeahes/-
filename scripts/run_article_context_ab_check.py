import json
from pathlib import Path

from app.core.article_context import apply_article_asr_corrections, save_article_artifacts
from app.core.bk_asr.asr_data import ASRData


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path.home() / "Desktop" / "\u4e2d\u56fd\u65b0\u5bcc\u8c6a\u6b63\u5728\u5f81\u670d\u4e16\u754c.srt"
OUT = ROOT / "work-dir" / "article_context_ab_test"


def _context():
    return {
        "title": "China new rich reference",
        "summary": "Reference glossary for proper-name ASR correction only.",
        "people": [
            {
                "canonical_name": "Liang Wenfeng",
                "chinese_name": "\u6881\u6587\u950b",
                "aliases": ["Liang Wen-Feng"],
                "category": "person",
            },
            {
                "canonical_name": "Zhang Junjie",
                "chinese_name": "\u5f20\u4fca\u6770",
                "aliases": [],
                "category": "person",
            },
        ],
        "companies": [
            {
                "canonical_name": "Dreame Technology",
                "chinese_name": "\u8ffd\u89c5\u79d1\u6280",
                "aliases": ["Dreame"],
                "category": "company",
            }
        ],
        "brands": [
            {
                "canonical_name": "Pop Mart",
                "chinese_name": "\u6ce1\u6ce1\u739b\u7279",
                "aliases": ["PopMart"],
                "category": "brand",
            },
            {
                "canonical_name": "Labubu",
                "chinese_name": "\u62c9\u5e03\u5e03",
                "aliases": ["La Bu Bu"],
                "category": "product",
            },
            {
                "canonical_name": "Shein",
                "chinese_name": "\u5e0c\u97f3",
                "aliases": ["SHEIN"],
                "category": "brand",
            },
            {
                "canonical_name": "Chagee",
                "chinese_name": "\u9738\u738b\u8336\u59ec",
                "aliases": ["Chagee's"],
                "category": "brand",
            },
        ],
        "organisations": [
            {
                "canonical_name": "Hurun Report",
                "chinese_name": "\u80e1\u6da6\u767e\u5bcc",
                "aliases": ["Hurun"],
                "category": "organisation",
            },
            {
                "canonical_name": "Hurun Rich List",
                "chinese_name": "\u80e1\u6da6\u767e\u5bcc\u699c",
                "aliases": ["Hurun List"],
                "category": "list",
            },
        ],
        "places": [],
        "technical_terms": [],
        "numbers_and_dates": [
            {
                "canonical_name": "33 founder",
                "chinese_name": "",
                "aliases": ["33 year old"],
                "category": "numbers_and_dates",
            }
        ],
    }


def _diff_segments(before, after):
    diffs = []
    for index, (left, right) in enumerate(zip(before, after), 1):
        if left.text == right.text:
            continue
        diffs.append(
            {
                "index": index,
                "time_unchanged": (
                    left.start_time == right.start_time
                    and left.end_time == right.end_time
                ),
                "start_time": left.start_time,
                "end_time": left.end_time,
                "before": left.text,
                "after": right.text,
            }
        )
    if len(before) != len(after):
        diffs.append(
            {
                "count_changed": True,
                "before_count": len(before),
                "after_count": len(after),
            }
        )
    return diffs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    context = _context()
    raw = ASRData.from_subtitle_file(str(SOURCE))
    save_article_artifacts(OUT, "offline reference glossary for AB test", context)
    raw.save(str(OUT / "asr_raw.json"))
    raw.save(str(OUT / "A_without_article_assist.srt"))

    corrected = apply_article_asr_corrections(raw, context, output_dir=OUT)
    corrected.save(str(OUT / "asr_corrected.json"))
    corrected.save(str(OUT / "B_with_article_assist.srt"))

    report = {
        "source": str(SOURCE),
        "raw_count": len(raw.segments),
        "corrected_count": len(corrected.segments),
        "diffs": _diff_segments(raw.segments, corrected.segments),
    }
    (OUT / "ab_diff_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(str(OUT))


if __name__ == "__main__":
    main()
