import tempfile
import unittest
import json
from pathlib import Path

from app.core.article_context import (
    ARTICLE_ANALYSIS_META_KEY,
    ARTICLE_RAW_RESPONSE_KEY,
    analyze_article_text,
    apply_article_asr_corrections,
    build_article_glossary,
    enrich_article_context_with_evidence,
    save_article_artifacts,
)
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg


def _context():
    return {
        "people": [
            {"canonical_name": "Liang Wenfeng", "aliases": [], "category": "person"},
            {"canonical_name": "Zhang Junjie", "aliases": [], "category": "person"},
            {"canonical_name": "Jack Ma", "aliases": [], "category": "person"},
            {"canonical_name": "Yu Hao", "aliases": [], "category": "person"},
            {"canonical_name": "Zhong Shanshan", "aliases": [], "category": "person"},
        ],
        "brands": [
            {"canonical_name": "Pop Mart", "aliases": ["PopMart"], "category": "brand"},
            {"canonical_name": "Labubu", "aliases": [], "category": "product"},
            {"canonical_name": "Chagee", "aliases": ["Chagee's"], "category": "brand"},
            {"canonical_name": "DeepSeek", "aliases": ["Deep Seek"], "category": "brand"},
            {"canonical_name": "Meta", "aliases": [], "category": "company"},
        ],
        "organisations": [
            {
                "canonical_name": "Hurun Rich List",
                "aliases": ["Hurun List"],
                "category": "list",
            },
            {"canonical_name": "Hurun", "aliases": [], "category": "organisation"},
            {"canonical_name": "The Economist", "aliases": [], "category": "organisation"},
            {
                "canonical_name": "World Trade Organisation",
                "aliases": ["World Trade Organization"],
                "category": "organisation",
            },
            {"canonical_name": "Evergrande", "aliases": [], "category": "company"},
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

    def test_corrects_entity_shaped_names_without_special_case_audio_rules(self):
        raw = [
            ASRDataSeg("Zong Shan Shan built a water empire.", 100, 200),
            ASRDataSeg("Deep Seek startled the market.", 300, 500),
        ]

        corrected = self._correct(raw)
        self.assertEqual(
            [seg.text for seg in corrected.segments],
            [
                "Zhong Shanshan built a water empire.",
                "DeepSeek startled the market.",
            ],
        )

    def test_does_not_rewrite_common_words_or_numbers(self):
        raw = [
            ASRDataSeg("it doesn't just change where they sell,", 100, 200),
            ASRDataSeg("China's brand new generation stayed unchanged.", 300, 500),
            ASRDataSeg("33 year-old founders are not rewritten.", 600, 900),
            ASRDataSeg("Jack Ma of Alibaba stayed outside the glossary.", 1000, 1200),
        ]

        corrected = self._correct(raw)
        self.assertEqual([seg.text for seg in corrected.segments], [seg.text for seg in raw])

    def test_skips_self_replacements_and_technical_terms_for_asr_correction(self):
        context = {
            "technical_terms": [
                {"canonical_name": "AI", "aliases": [], "category": "technical_term"},
                {"canonical_name": "automation", "aliases": [], "category": "technical_term"},
            ],
            "brands": [
                {"canonical_name": "DeepSeek", "aliases": ["Deep Seek"], "category": "brand"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(
                    [
                        ASRDataSeg("AI and automation are already correct.", 100, 200),
                        ASRDataSeg("Deep Seek is a brand.", 300, 500),
                    ]
                ),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads((Path(tmp) / "correction_log.json").read_text(encoding="utf-8"))

        self.assertEqual(
            [seg.text for seg in corrected.segments],
            ["AI and automation are already correct.", "DeepSeek is a brand."],
        )
        self.assertEqual([item["corrected_text"] for item in logs], ["DeepSeek"])

    def test_rejects_fluent_common_phrases_that_sound_like_entities(self):
        raw = [
            ASRDataSeg("I mean, they are trading.", 100, 200),
            ASRDataSeg("No, he was not there.", 300, 500),
            ASRDataSeg("Seven are in video games.", 600, 900),
            ASRDataSeg("Four are in tea or coffee.", 1000, 1200),
            ASRDataSeg("Oh, yeah, that is right.", 1300, 1500),
            ASRDataSeg("But wait, I have to ask.", 1600, 1900),
            ASRDataSeg("They run their offices overseas.", 2000, 2300),
            ASRDataSeg("It might be the most interesting case.", 2400, 2700),
            ASRDataSeg("The economy is changing.", 2800, 3100),
            ASRDataSeg("It was gritty survival.", 3200, 3500),
            ASRDataSeg("Yet they are still expanding.", 3600, 3900),
            ASRDataSeg("But hey, you are right.", 4000, 4300),
        ]

        corrected = self._correct(raw)
        self.assertEqual([seg.text for seg in corrected.segments], [seg.text for seg in raw])

    def test_rejects_short_alias_expansion_to_longer_entity(self):
        raw = [
            ASRDataSeg("Seven Hurun video games.", 100, 200),
            ASRDataSeg("Four Hurun tea or coffee.", 300, 500),
            ASRDataSeg("They run their offices overseas.", 600, 900),
            ASRDataSeg("The founder of Dreame Consumer Electronics spoke.", 1000, 1200),
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

    def test_glossary_keeps_only_article_supported_aliases_for_matching(self):
        article = "Jack Ma founded Alibaba. Popmart became popular."
        context = {
            "people": [
                {
                    "canonical_name": "Jack Ma",
                    "aliases": ["Ma Yun"],
                    "category": "person",
                }
            ],
            "brands": [
                {
                    "canonical_name": "Pop Mart",
                    "aliases": ["Popmart", "POP MART Global"],
                    "category": "brand",
                }
            ],
        }

        enriched = enrich_article_context_with_evidence(context, article)
        glossary = build_article_glossary(enriched)

        jack = next(item for item in glossary if item["canonical_name"] == "Jack Ma")
        pop = next(item for item in glossary if item["canonical_name"] == "Pop Mart")
        self.assertEqual(jack["aliases"], [])
        self.assertEqual(pop["aliases"], ["Popmart"])
        self.assertTrue(pop["canonical_in_article"] is False)
        self.assertNotIn("asr_disabled_reason", pop)

    def test_save_article_artifacts_writes_raw_response_and_audit(self):
        article = "DeepSeek was founded by Liang Wenfeng."
        context = {
            ARTICLE_RAW_RESPONSE_KEY: '{"raw": true}',
            "people": [
                {
                    "canonical_name": "Liang Wenfeng",
                    "aliases": ["Li Yang"],
                    "category": "person",
                }
            ],
            "companies": [
                {
                    "canonical_name": "DeepSeek",
                    "aliases": ["Deep Seek"],
                    "category": "company",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_article_artifacts(Path(tmp), article, context)
            self.assertEqual(Path(paths["article_llm_raw_response"]).read_text(encoding="utf-8"), '{"raw": true}')
            audit = Path(paths["article_context_audit"]).read_text(encoding="utf-8")
            self.assertIn("unsupported_alias_count", audit)

    def test_cache_hit_marks_analysis_meta_without_calling_llm(self):
        class FakeCache:
            def __init__(self, payload):
                self.payload = payload

            def get_llm_result(self, *args, **kwargs):
                return self.payload

        cached_payload = {
            "title": "Cached title",
            "summary": "Cached summary",
            "people": [],
            "companies": [],
            "brands": [],
            "organisations": [],
            "places": [],
            "technical_terms": [],
            "numbers_and_dates": [],
        }

        context = analyze_article_text(
            "Cached summary text.",
            type("LLMConfig", (), {"base_url": "", "api_key": "", "model": "deepseek-v4-flash"})(),
            cache_manager=FakeCache(json.dumps(cached_payload, ensure_ascii=False)),
        )

        self.assertTrue(context[ARTICLE_ANALYSIS_META_KEY]["cache_used"])
        self.assertEqual(context["summary"], "Cached summary")


if __name__ == "__main__":
    unittest.main()
