import tempfile
import unittest
from pathlib import Path

from app.core.article_context import apply_article_asr_corrections
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg


def _context():
    return {
        "people": [
            {"canonical_name": "Liang Wenfeng", "aliases": [], "category": "person"},
            {"canonical_name": "Zhang Junjie", "aliases": [], "category": "person"},
        ],
        "brands": [
            {"canonical_name": "Pop Mart", "aliases": ["PopMart"], "category": "brand"},
            {"canonical_name": "Labubu", "aliases": [], "category": "product"},
            {"canonical_name": "Chagee", "aliases": ["Chagee's"], "category": "brand"},
        ],
        "organisations": [
            {
                "canonical_name": "Hurun Rich List",
                "aliases": ["Hurun List"],
                "category": "list",
            }
        ],
        "numbers_and_dates": [
            {"canonical_name": "33 founder", "aliases": ["33 year old"], "category": "numbers_and_dates"}
        ],
    }


class ArticleContextASRCorrectionTests(unittest.TestCase):
    def _correct(self, segments):
        with tempfile.TemporaryDirectory() as tmp:
            return apply_article_asr_corrections(
                ASRData(segments),
                _context(),
                output_dir=Path(tmp),
            )

    def test_corrects_only_article_glossary_proper_names(self):
        raw = [
            ASRDataSeg("Right, Li Yang Wenfing.", 100, 200),
            ASRDataSeg("Hero Unriched List and Popmart were mentioned.", 300, 500),
            ASRDataSeg("LeBooBoo dolls and Chagi's Zhang Jinji.", 600, 900),
        ]

        corrected = self._correct(raw)
        texts = [seg.text for seg in corrected.segments]

        self.assertEqual(texts[0], "Right, Liang Wenfeng.")
        self.assertEqual(texts[1], "Hurun Rich List and Pop Mart were mentioned.")
        self.assertEqual(texts[2], "Labubu dolls and Chagee's Zhang Junjie.")

    def test_does_not_rewrite_common_words_or_numbers(self):
        raw = [
            ASRDataSeg("it doesn't just change where they sell,", 100, 200),
            ASRDataSeg("China's brand new generation stayed unchanged.", 300, 500),
            ASRDataSeg("33 year-old founders are not rewritten.", 600, 900),
            ASRDataSeg("Jack Ma of Alibaba stayed outside the glossary.", 1000, 1200),
        ]

        corrected = self._correct(raw)
        self.assertEqual([seg.text for seg in corrected.segments], [seg.text for seg in raw])

    def test_preserves_count_and_timestamps(self):
        raw = [
            ASRDataSeg("Even Popmart made money.", 100, 200),
            ASRDataSeg("Yeah, he makes LeBooBoo dolls.", 300, 500),
        ]

        corrected = self._correct(raw)

        self.assertEqual(len(corrected.segments), len(raw))
        self.assertEqual(
            [(seg.start_time, seg.end_time) for seg in corrected.segments],
            [(seg.start_time, seg.end_time) for seg in raw],
        )


if __name__ == "__main__":
    unittest.main()
