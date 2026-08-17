import tempfile
import unittest
import json
from pathlib import Path

from app.core.article_context import (
    ARTICLE_ANALYSIS_META_KEY,
    ARTICLE_ANALYSIS_PROMPT_POLICY_VERSION,
    ARTICLE_RAW_RESPONSE_KEY,
    analyze_article_text,
    article_analysis_cache_key,
    article_analysis_prompt_hash,
    article_text_hash,
    apply_article_asr_corrections,
    build_article_asr_review_artifact,
    build_article_glossary,
    empty_article_context,
    enrich_article_context_with_evidence,
    save_article_artifacts,
    _dedupe_adjacent_canonical_entity_overlap,
    _find_article_evidence,
    _resolve_overlapping_article_correction_candidates,
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
            {"canonical_name": "Taylor Swift", "aliases": ["Ms Swift"], "category": "person"},
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
            {"canonical_name": "New York Fed", "aliases": [], "category": "organisation"},
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

    def _correct_with_context(self, segments, context):
        with tempfile.TemporaryDirectory() as tmp:
            return apply_article_asr_corrections(
                ASRData(segments),
                context,
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

    def test_exact_article_entity_is_not_rewritten_as_another_article_entity(self):
        context = enrich_article_context_with_evidence(
            {
                "places": [
                    {"canonical_name": "Red Sea", "aliases": [], "category": "region"},
                    {"canonical_name": "Russia", "aliases": [], "category": "country"},
                ]
            },
            "Shipping through the Red Sea changed while Russia adjusted exports.",
        )
        raw = [
            ASRDataSeg("Red", 100, 250),
            ASRDataSeg("Sea", 250, 500),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw), context, output_dir=Path(tmp)
            )
            rejected = json.loads(
                (Path(tmp) / "correction_rejected.json").read_text(encoding="utf-8")
            )

        self.assertEqual([segment.text for segment in corrected.segments], ["Red", "Sea"])
        collision = next(
            item
            for item in rejected
            if item.get("original_text") == "Red Sea"
            and item.get("candidate_text") == "Russia"
        )
        self.assertEqual(collision["reason"], "source_is_exact_other_article_entity")

    def test_capitalized_multiword_entity_is_not_collapsed_by_phonetics(self):
        context = enrich_article_context_with_evidence(
            {
                "places": [
                    {"canonical_name": "Russia", "aliases": [], "category": "country"}
                ]
            },
            "Russia adjusted its exports.",
        )
        raw = [
            ASRDataSeg("Red", 100, 250),
            ASRDataSeg("Sea", 250, 500),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw), context, output_dir=Path(tmp)
            )
            rejected = json.loads(
                (Path(tmp) / "correction_rejected.json").read_text(encoding="utf-8")
            )

        self.assertEqual([segment.text for segment in corrected.segments], ["Red", "Sea"])
        collision = next(
            item
            for item in rejected
            if item.get("original_text") == "Red Sea"
            and item.get("candidate_text") == "Russia"
        )
        self.assertEqual(
            collision["reason"],
            "multiword_entity_cannot_collapse_to_unrelated_entity",
        )

    def test_lowercase_word_is_not_expanded_into_multiword_article_entity(self):
        context = enrich_article_context_with_evidence(
            {
                "places": [
                    {"canonical_name": "New York", "aliases": [], "category": "city"}
                ]
            },
            "The company later opened pubs in New York.",
        )
        raw = [ASRDataSeg("network", 100, 400)]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw), context, output_dir=Path(tmp)
            )
            rejected = json.loads(
                (Path(tmp) / "correction_rejected.json").read_text(encoding="utf-8")
            )

        self.assertEqual([segment.text for segment in corrected.segments], ["network"])
        candidate = next(
            item
            for item in rejected
            if item.get("original_text") == "network"
            and item.get("candidate_text") == "New York"
        )
        self.assertEqual(
            candidate["reason"],
            "lowercase_single_token_cannot_expand_to_multiword_entity",
        )

    def test_capitalized_compound_can_still_expand_to_multiword_entity(self):
        context = enrich_article_context_with_evidence(
            {
                "companies": [
                    {
                        "canonical_name": "Mixue Bingcheng",
                        "aliases": [],
                        "category": "company",
                    }
                ]
            },
            "Mixue Bingcheng operates a large franchise network.",
        )
        raw = [ASRDataSeg("MixueBingcheng", 100, 500)]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            ["Mixue Bingcheng"],
        )

    def test_uncertain_proper_name_candidate_remains_review_only(self):
        context = enrich_article_context_with_evidence(
            {
                "companies": [
                    {
                        "canonical_name": "Fulujia",
                        "aliases": ["Lucky Deer"],
                        "category": "company",
                    }
                ]
            },
            "Fulujia, whose name means Lucky Deer, operates thousands of pubs.",
        )
        raw = [ASRDataSeg("Felugia", 100, 500)]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw), context, output_dir=Path(tmp)
            )
            rejected = json.loads(
                (Path(tmp) / "correction_rejected.json").read_text(encoding="utf-8")
            )

        self.assertEqual([segment.text for segment in corrected.segments], ["Felugia"])
        candidate = next(
            item
            for item in rejected
            if item.get("original_text") == "Felugia"
            and item.get("candidate_text") == "Fulujia"
        )
        self.assertEqual(candidate["result"], "review_only")
        self.assertEqual(candidate["reason"], "below_high_confidence_threshold")

    def test_article_review_artifact_maps_only_best_uncertain_candidate_to_frozen_id(self):
        final = ASRDataSeg("They opened a Felugia pub.", 1000, 2200)
        final.subtitle_id = "S0002"
        base = {
            "candidate_id": "candidate-company",
            "original_text": "Felugia",
            "candidate_text": "Fulujia",
            "original_token_count": 1,
            "candidate_token_count": 1,
            "final_confidence": 0.8167,
            "start_time": 1400,
            "end_time": 1700,
            "source_key": "companies",
            "category": "company",
            "entity_gate_passed": True,
            "applied": False,
            "result": "review_only",
            "reason": "below_high_confidence_threshold",
        }
        expanded = {
            **base,
            "candidate_id": "candidate-brand",
            "candidate_text": "Fulujia beer",
            "candidate_token_count": 2,
        }
        noisy = {
            **base,
            "candidate_id": "candidate-noisy",
            "original_text": "fully",
            "candidate_text": "Fulujia",
            "entity_gate_passed": False,
        }

        artifact = build_article_asr_review_artifact(
            [expanded, noisy, base],
            [final],
            word_ledger_hash="ledger-hash",
            source_file_hash="source-hash",
        )

        self.assertEqual(artifact["word_ledger_hash"], "ledger-hash")
        self.assertEqual(artifact["source_file_hash"], "source-hash")
        self.assertEqual(artifact["item_count"], 1)
        self.assertEqual(artifact["items"][0]["candidate_id"], "candidate-company")
        self.assertEqual(artifact["items"][0]["subtitle_ids"], ["S0002"])
        self.assertEqual(artifact["items"][0]["suggested_text"], "Fulujia")

    def test_does_not_collapse_function_words_into_a_distant_article_entity(self):
        article = (
            "The character was known literally only as Stifler's Mom. "
            "Later, platforms such as OnlyFans changed distribution."
        )
        context = enrich_article_context_with_evidence(
            {
                "platforms": [
                    {
                        "canonical_name": "OnlyFans",
                        "aliases": [],
                        "category": "adult content platform",
                    }
                ]
            },
            article,
        )
        words = [
            "known",
            "literally",
            "only",
            "as",
            "Stifler's",
            "Mom.",
            "Later,",
            "OnlyFans",
            "changed",
            "distribution.",
        ]
        raw = [
            ASRDataSeg(word, index * 100, (index + 1) * 100)
            for index, word in enumerate(words)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads(
                (Path(tmp) / "correction_log.json").read_text(encoding="utf-8")
            )

        self.assertEqual(
            [segment.text.strip() for segment in corrected.segments],
            words,
        )
        rejected = [
            item
            for item in logs
            if item.get("original_text") == "only as"
            and item.get("candidate_text") == "OnlyFans"
        ]
        self.assertTrue(rejected)
        self.assertTrue(all(not item.get("applied") for item in rejected))
        self.assertTrue(
            all(
                item.get("reason") == "candidate_would_merge_function_words"
                for item in rejected
            )
        )

    def test_corrects_near_threshold_person_name_when_last_name_matches_article_entity(self):
        raw = [
            ASRDataSeg(
                "Kaler Swift's marriage was a massive cultural event.",
                100,
                200,
            )
        ]

        corrected = self._correct(raw)

        self.assertEqual(
            corrected.segments[0].text,
            "Taylor Swift's marriage was a massive cultural event.",
        )

    def test_person_description_context_corrects_low_similarity_titled_name(self):
        context = enrich_article_context_with_evidence(
            {
                "people": [
                    {
                        "canonical_name": "Ms Hao",
                        "aliases": [],
                        "category": "person",
                    }
                ]
            },
            (
                "Ms Hao, a 25-year-old Chinese woman, was working for a startup "
                "in America when she decided to return home."
            ),
        )
        words = (
            "Like the case of Ms. Howe. Yes, exactly. Ms. Howe is a 25 year-old "
            "Chinese woman working for a startup in America."
        ).split()
        raw = [
            ASRDataSeg(word, index * 200, index * 200 + 160)
            for index, word in enumerate(words)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads(
                (Path(tmp) / "correction_log.json").read_text(encoding="utf-8")
            )

        corrected_text = " ".join(segment.text for segment in corrected.segments)
        self.assertEqual(corrected_text.count("Ms Hao"), 2)
        applied = [
            item
            for item in logs
            if item.get("applied") and item.get("canonical_name") == "Ms Hao"
        ]
        self.assertEqual(len(applied), 2)
        self.assertTrue(all(item.get("context_match") for item in applied))

    def test_similar_titled_name_without_matching_description_is_not_rewritten(self):
        context = enrich_article_context_with_evidence(
            {
                "people": [
                    {
                        "canonical_name": "Ms Hao",
                        "aliases": [],
                        "category": "person",
                    }
                ]
            },
            "Ms Hao discussed cross-border education policy in Beijing.",
        )
        words = "Ms. Howe presented unrelated laboratory findings yesterday.".split()
        raw = [
            ASRDataSeg(word, index * 200, index * 200 + 160)
            for index, word in enumerate(words)
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            [segment.text for segment in raw],
        )

    def test_exact_haigui_surface_is_preserved(self):
        context = enrich_article_context_with_evidence(
            {
                "technical_terms": [
                    {
                        "canonical_name": "haigui",
                        "aliases": ["sea turtles"],
                        "category": "term",
                    }
                ]
            },
            "Returning graduates are known as haigui or sea turtles.",
        )
        raw = [ASRDataSeg("haigui", 100, 420)]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual([segment.text for segment in corrected.segments], ["haigui"])

    def test_article_defined_single_token_term_repairs_framed_multiword_asr_surface(self):
        context = enrich_article_context_with_evidence(
            {
                "technical_terms": [
                    {
                        "canonical_name": "fudaoke",
                        "aliases": ["remedial class"],
                        "category": "Chinese term",
                    }
                ]
            },
            (
                "To many young people, counselling is like a fudaoke, "
                "just a remedial class for emotional well-being."
            ),
        )
        words = (
            "Many young people now refer to therapy as a food of oak. "
            "They later describe a remedial class for emotional well-being."
        ).split()
        raw = [
            ASRDataSeg(word, index * 200, index * 200 + 160)
            for index, word in enumerate(words)
        ]

        corrected = self._correct_with_context(raw, context)

        text = " ".join(segment.text for segment in corrected.segments)
        self.assertIn("therapy as a fudaoke.", text)
        self.assertIn("a remedial class", text)

    def test_article_defined_term_does_not_rewrite_unframed_ordinary_phrase(self):
        context = enrich_article_context_with_evidence(
            {
                "technical_terms": [
                    {
                        "canonical_name": "fudaoke",
                        "aliases": ["remedial class"],
                        "category": "Chinese term",
                    }
                ]
            },
            "Counselling is like a fudaoke, just a remedial class.",
        )
        words = "They placed the food of oak beside the table.".split()
        raw = [
            ASRDataSeg(word, index * 200, index * 200 + 160)
            for index, word in enumerate(words)
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            [segment.text for segment in raw],
        )

    def test_extended_term_path_does_not_collapse_general_technical_words_or_correct_surface(self):
        context = enrich_article_context_with_evidence(
            {
                "technical_terms": [
                    {
                        "canonical_name": "counselling",
                        "aliases": ["therapy"],
                        "category": "therapy term",
                    },
                    {
                        "canonical_name": "fudaoke",
                        "aliases": ["remedial class"],
                        "category": "Chinese term",
                    },
                ]
            },
            "Counselling is therapy. A fudaoke is a remedial class.",
        )
        words = "They entered a counselling room and described it as a fudaoke.".split()
        raw = [
            ASRDataSeg(word, index * 200, index * 200 + 160)
            for index, word in enumerate(words)
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            [segment.text for segment in raw],
        )

    def test_extended_term_context_must_be_adjacent_and_cannot_consume_trailing_function_word(self):
        context = enrich_article_context_with_evidence(
            {
                "technical_terms": [
                    {
                        "canonical_name": "fudaoke",
                        "aliases": ["remedial class"],
                        "category": "Chinese term",
                    }
                ]
            },
            "Counselling is like a fudaoke, just a remedial class.",
        )
        raw_cases = (
            "As usual, they placed a food oak beside the table.",
            "They frame the food oak as a bad habit.",
        )
        for sentence in raw_cases:
            words = sentence.split()
            raw = [
                ASRDataSeg(word, index * 200, index * 200 + 160)
                for index, word in enumerate(words)
            ]

            corrected = self._correct_with_context(raw, context)

            self.assertEqual(
                [segment.text for segment in corrected.segments],
                [segment.text for segment in raw],
            )

    def test_article_alias_title_and_description_repair_adjacent_titled_person(self):
        context = enrich_article_context_with_evidence(
            {
                "people": [
                    {
                        "canonical_name": "Yuan Chengmei",
                        "aliases": ["Dr Yuan"],
                        "category": "psychiatrist",
                    }
                ]
            },
            (
                "Yuan Chengmei of SMHC points to better identification of "
                "milder cases of mental distress. Dr Yuan discusses demand."
            ),
        )
        words = (
            "But Dr. Yuan Qingmai from SMHC points out that they identify "
            "milder cases of mental distress."
        ).split()
        raw = [
            ASRDataSeg(word, index * 200, index * 200 + 160)
            for index, word in enumerate(words)
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertIn(
            "Dr. Yuan Chengmei from SMHC",
            " ".join(segment.text for segment in corrected.segments),
        )

    def test_adjacent_title_without_article_description_overlap_remains_review_only(self):
        context = enrich_article_context_with_evidence(
            {
                "people": [
                    {
                        "canonical_name": "Yuan Chengmei",
                        "aliases": ["Dr Yuan"],
                        "category": "psychiatrist",
                    }
                ]
            },
            "Yuan Chengmei of SMHC identifies milder cases of mental distress. Dr Yuan spoke.",
        )
        words = "Dr. Yuan Qingmai presented unrelated laboratory findings yesterday.".split()
        raw = [
            ASRDataSeg(word, index * 200, index * 200 + 160)
            for index, word in enumerate(words)
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            [segment.text for segment in raw],
        )

    def test_adjacent_title_with_scattered_topic_words_but_no_shared_description_remains_review_only(self):
        context = enrich_article_context_with_evidence(
            {
                "people": [
                    {
                        "canonical_name": "Yuan Chengmei",
                        "aliases": ["Dr Yuan"],
                        "category": "psychiatrist",
                    }
                ]
            },
            (
                "Yuan Chengmei of SMHC points to better identification of "
                "milder cases of mental distress. Dr Yuan discusses demand."
            ),
        )
        words = (
            "Dr. Yuan Qingmai from SMHC identifies unrelated cases of "
            "mental distress."
        ).split()
        raw = [
            ASRDataSeg(word, index * 200, index * 200 + 160)
            for index, word in enumerate(words)
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            [segment.text for segment in raw],
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

    def test_does_not_conflate_places_with_demonyms_or_consume_trailing_words(self):
        context = {
            "places": [
                {"canonical_name": "America", "aliases": [], "category": "place"},
                {"canonical_name": "China", "aliases": [], "category": "place"},
            ],
            "organisations": [
                {"canonical_name": "Census Bureau", "aliases": [], "category": "organisation"},
                {
                    "canonical_name": "American Enterprise Institute",
                    "aliases": [],
                    "category": "organisation",
                },
            ],
        }
        raw = [
            ASRDataSeg("Americans", 100, 200),
            ASRDataSeg("have", 200, 300),
            ASRDataSeg("applied.", 300, 400),
            ASRDataSeg("Chinese", 500, 600),
            ASRDataSeg("founders", 600, 700),
            ASRDataSeg("are", 700, 800),
            ASRDataSeg("growing.", 800, 900),
            ASRDataSeg("Census", 1000, 1100),
            ASRDataSeg("Bureau,", 1100, 1200),
            ASRDataSeg("there", 1200, 1300),
            ASRDataSeg("are", 1300, 1400),
            ASRDataSeg("signs.", 1400, 1500),
            ASRDataSeg("American", 1600, 1700),
            ASRDataSeg("Enterprise", 1700, 1800),
            ASRDataSeg("Institute", 1800, 1900),
            ASRDataSeg("details", 1900, 2000),
            ASRDataSeg("findings.", 2000, 2100),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads((Path(tmp) / "correction_log.json").read_text(encoding="utf-8"))

        self.assertEqual(
            " ".join(seg.text for seg in corrected.segments),
            " ".join(seg.text for seg in raw),
        )
        american_logs = [item for item in logs if item.get("original_text") == "Americans"]
        self.assertTrue(american_logs)
        self.assertTrue(all(item["reason"] == "place_demonym_not_entity" for item in american_logs))
        self.assertTrue(
            any(
                item.get("original_text") == "Census Bureau, there"
                and item["reason"] == "candidate_would_delete_non_entity_token"
                for item in logs
            )
        )
        self.assertTrue(
            any(
                item.get("original_text") == "American Enterprise Institute details"
                and item["reason"] == "candidate_would_delete_non_entity_token"
                for item in logs
            )
        )

    def test_multi_token_entity_candidate_cannot_consume_acronym_fragment(self):
        context = {
            "places": [
                {"canonical_name": "Japan", "aliases": [], "category": "place"},
            ],
        }
        raw = [
            ASRDataSeg("U", 100, 180),
            ASRDataSeg(".S.,", 180, 360),
            ASRDataSeg("Japan,", 420, 560),
            ASRDataSeg("and", 600, 700),
            ASRDataSeg("South", 700, 820),
            ASRDataSeg("Korea", 820, 940),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads((Path(tmp) / "correction_log.json").read_text(encoding="utf-8"))

        self.assertEqual([seg.text for seg in corrected.segments], [seg.text for seg in raw])
        rejected = [item for item in logs if item.get("original_text") == ".S., Japan,"]
        self.assertTrue(rejected)
        self.assertTrue(all(not item.get("applied") for item in rejected))
        self.assertTrue(
            all(item.get("reason") == "candidate_would_delete_non_entity_token" for item in rejected)
        )

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

    def test_corrects_article_defined_domain_term_from_phonetic_asr_forms(self):
        context = enrich_article_context_with_evidence(
            {
                "technical_terms": [
                    {
                        "canonical_name": "haigui",
                        "aliases": ["sea turtles"],
                        "category": "term",
                    }
                ]
            },
            (
                "Last year the proportion of returnees, who are known as "
                "haigui or sea turtles, reached an all-time high."
            ),
        )
        raw = [
            ASRDataSeg("Higee", 100, 320),
            ASRDataSeg("students", 320, 620),
            ASRDataSeg("and", 620, 760),
            ASRDataSeg("Higgies", 760, 1040),
            ASRDataSeg("returned.", 1040, 1360),
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            ["haigui", "students", "and", "haigui", "returned."],
        )
        self.assertEqual(
            [(segment.start_time, segment.end_time) for segment in corrected.segments],
            [(segment.start_time, segment.end_time) for segment in raw],
        )

    def test_preserves_words_adjacent_to_an_already_complete_entity(self):
        context = {
            "people": [
                {
                    "canonical_name": "Donald Trump",
                    "aliases": [],
                    "category": "person",
                }
            ],
            "organisations": [
                {
                    "canonical_name": "Peking University",
                    "aliases": [],
                    "category": "organisation",
                }
            ],
        }
        raw = [
            ASRDataSeg("Like,", 100, 180),
            ASRDataSeg("Peking", 180, 280),
            ASRDataSeg("University", 280, 420),
            ASRDataSeg("President", 500, 640),
            ASRDataSeg("Donald", 640, 760),
            ASRDataSeg("Trump", 760, 900),
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            [segment.text for segment in raw],
        )
        self.assertEqual(
            [(segment.start_time, segment.end_time) for segment in corrected.segments],
            [(segment.start_time, segment.end_time) for segment in raw],
        )

    def test_plain_article_technical_word_is_not_a_phonetic_rewrite_authority(self):
        context = enrich_article_context_with_evidence(
            {
                "technical_terms": [
                    {
                        "canonical_name": "automation",
                        "aliases": [],
                        "category": "technical_term",
                    }
                ]
            },
            "Automation can reduce repetitive work.",
        )
        raw = [ASRDataSeg("Automotion", 100, 620)]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual([segment.text for segment in corrected.segments], ["Automotion"])

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

    def test_short_alias_collision_with_related_canonical_is_review_only(self):
        article = (
            "Northbridge Reserve College opened a research centre. "
            "Northbridge Reserve Council Directorate published a separate report."
        )
        context = enrich_article_context_with_evidence(
            {
                "organisations": [
                    {
                        "canonical_name": "Northbridge Reserve College",
                        "aliases": [],
                        "category": "organisation",
                    },
                    {
                        "canonical_name": "Northbridge Reserve Council Directorate",
                        "aliases": ["Northbridge Reserve"],
                        "category": "organisation",
                    },
                ]
            },
            article,
        )
        raw = [
            ASRDataSeg("Northbridge", 0, 100),
            ASRDataSeg("Reserve", 100, 200),
            ASRDataSeg("College", 200, 300),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads((Path(tmp) / "correction_log.json").read_text(encoding="utf-8"))

        self.assertEqual(" ".join(seg.text for seg in corrected.segments), "Northbridge Reserve College")
        collision = next(
            item
            for item in logs
            if item.get("reason") == "ambiguous_alias_canonical_collision"
        )
        self.assertFalse(collision["applied"])
        self.assertEqual(collision["result"], "review_only")
        self.assertEqual(collision["matched_variant"], "Northbridge Reserve")
        self.assertEqual(collision["canonical_name"], "Northbridge Reserve Council Directorate")
        self.assertEqual(
            collision["alias_canonical_collision"]["conflicting_canonicals"][0]["canonical_name"],
            "Northbridge Reserve College",
        )
        self.assertEqual(collision["start_word_index"], 0)
        self.assertEqual(collision["end_word_index"], 3)

    def test_exact_canonical_correction_survives_related_alias_collision_guard(self):
        article = (
            "Northbridge Reserve College opened a research centre. "
            "Northbridge Reserve Council Directorate published a separate report."
        )
        context = enrich_article_context_with_evidence(
            {
                "organisations": [
                    {
                        "canonical_name": "Northbridge Reserve College",
                        "aliases": [],
                        "category": "organisation",
                    },
                    {
                        "canonical_name": "Northbridge Reserve Council Directorate",
                        "aliases": ["Northbridge Reserve"],
                        "category": "organisation",
                    },
                ]
            },
            article,
        )
        raw = [
            ASRDataSeg("Northbridge", 0, 100),
            ASRDataSeg("Reserve", 100, 200),
            ASRDataSeg("Collage", 200, 300),
        ]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual(" ".join(seg.text for seg in corrected.segments), "Northbridge Reserve College")

    def test_unrelated_high_confidence_entity_correction_remains_automatic(self):
        article = "Harborview Dynamics released a new report."
        context = enrich_article_context_with_evidence(
            {
                "companies": [
                    {
                        "canonical_name": "Harborview Dynamics",
                        "aliases": [],
                        "category": "company",
                    }
                ]
            },
            article,
        )
        raw = [
            ASRDataSeg("Harbourview", 0, 100),
            ASRDataSeg("Dynamics", 100, 200),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads((Path(tmp) / "correction_log.json").read_text(encoding="utf-8"))

        self.assertEqual(" ".join(seg.text for seg in corrected.segments), "Harborview Dynamics")
        self.assertTrue(
            any(
                item.get("applied")
                and item.get("canonical_name") == "Harborview Dynamics"
                for item in logs
            )
        )

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

    def test_empty_context_contains_article_entity_categories(self):
        context = empty_article_context()

        self.assertIn("books_and_works", context)
        self.assertIn("awards", context)
        self.assertIn("media_outlets", context)
        self.assertIn("platforms", context)

    def test_article_evidence_matches_curly_and_mojibake_apostrophes(self):
        self.assertIsNotNone(_find_article_evidence("People's Daily praised him.", "People's Daily"))
        self.assertIsNotNone(_find_article_evidence("People’s Daily praised him.", "People's Daily"))
        self.assertIsNotNone(_find_article_evidence("People鈥檚 Daily praised him.", "People's Daily"))

    def test_article_entities_correct_people_works_awards_media_and_platforms_without_degrading_plausible_names(self):
        article = (
            "Hu Anyan and Fan Yusu were discussed by Lizzi Lee. "
            "The Lu Xun Literary Prize recognized migrant worker writing. "
            "Adrift in the South became a memoir. "
            "People’s Daily, Douyin, and Douban all appeared in the article."
        )
        context = enrich_article_context_with_evidence(
            {
                "people": [
                    {"canonical_name": "Hu Anyan", "aliases": [], "category": "writer"},
                    {"canonical_name": "Fan Yusu", "aliases": [], "category": "writer"},
                    {"canonical_name": "Lizzi Lee", "aliases": [], "category": "analyst"},
                ],
                "books_and_works": [
                    {"canonical_name": "Adrift in the South", "aliases": [], "category": "memoir"},
                ],
                "awards": [
                    {"canonical_name": "Lu Xun Literary Prize", "aliases": [], "category": "literary award"},
                ],
                "media_outlets": [
                    {"canonical_name": "People's Daily", "aliases": [], "category": "media outlet"},
                ],
                "platforms": [
                    {"canonical_name": "Douyin", "aliases": [], "category": "social media platform"},
                    {"canonical_name": "Douban", "aliases": [], "category": "social media platform"},
                ],
            },
            article,
        )
        raw = [
            ASRDataSeg("Hu Anyin released a book.", 100, 200),
            ASRDataSeg("Fan Yuzu described factory life.", 300, 500),
            ASRDataSeg("Lizzie Li analyzed the trend.", 600, 800),
            ASRDataSeg("The Lusun Literary Prize matters.", 900, 1100),
            ASRDataSeg("A Drift in the South was cited.", 1200, 1400),
            ASRDataSeg("People's Daily and Duyin covered it.", 1500, 1700),
            ASRDataSeg("On Duben, readers responded.", 1800, 2000),
            ASRDataSeg("on", 2100, 2200),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads((Path(tmp) / "correction_log.json").read_text(encoding="utf-8"))

        self.assertEqual(
            [seg.text for seg in corrected.segments],
            [
                "Hu Anyin released a book.",
                "Fan Yuzu described factory life.",
                "Lizzie Li analyzed the trend.",
                "The Lu Xun Literary Prize matters.",
                "Adrift in the South was cited.",
                "People's Daily and Douyin covered it.",
                "On Douban, readers responded.",
                "on",
            ],
        )
        reasons = {item["original_text"]: item["reason"] for item in logs if not item.get("applied")}
        self.assertEqual(reasons["Hu Anyin"], "capitalized_name_ambiguous")
        self.assertEqual(reasons["Fan Yuzu"], "capitalized_name_ambiguous")
        lizzie_reasons = {
            item["reason"]
            for item in logs
            if not item.get("applied") and str(item.get("original_text", "")).startswith("Lizzie")
        }
        self.assertTrue(
            lizzie_reasons
            & {
                "capitalized_name_ambiguous",
                "token_count_expansion_without_canonical_support",
            }
        )

    def test_article_work_context_corrects_split_title_but_not_unrelated_phrase(self):
        article = (
            'The animated film "Niulai" unexpectedly went viral. '
            'Hashtags such as "Niulai box office surges 1000 times" and '
            '"How did Niulai pass censorship" became trending topics.'
        )
        context = enrich_article_context_with_evidence(
            {
                "books_and_works": [
                    {
                        "canonical_name": "Niulai",
                        "aliases": [],
                        "category": "film",
                    }
                ]
            },
            article,
        )
        raw = [
            ASRDataSeg("Hashtags", 0, 100),
            ASRDataSeg("like,", 100, 200),
            ASRDataSeg("new", 200, 300),
            ASRDataSeg("lie", 300, 400),
            ASRDataSeg("box", 400, 500),
            ASRDataSeg("office", 500, 600),
            ASRDataSeg("surges.", 600, 700),
            ASRDataSeg("Separately,", 800, 900),
            ASRDataSeg("a", 900, 1000),
            ASRDataSeg("new", 1000, 1100),
            ASRDataSeg("lie", 1100, 1200),
            ASRDataSeg("spread", 1200, 1300),
            ASRDataSeg("yesterday.", 1300, 1400),
            ASRDataSeg("How", 1500, 1600),
            ASRDataSeg("did", 1600, 1700),
            ASRDataSeg("new", 1700, 1800),
            ASRDataSeg("lie", 1800, 1900),
            ASRDataSeg("past", 1900, 2000),
            ASRDataSeg("censorship?", 2000, 2100),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads(
                (Path(tmp) / "correction_log.json").read_text(encoding="utf-8")
            )

        corrected_text = " ".join(segment.text for segment in corrected.segments)
        self.assertIn("Niulai box office surges.", corrected_text)
        self.assertIn("a new lie spread yesterday.", corrected_text)
        self.assertIn("How did Niulai past censorship?", corrected_text)
        applied = [
            item
            for item in logs
            if item.get("applied") and item.get("candidate_text") == "Niulai"
        ]
        self.assertEqual(len(applied), 2)
        self.assertTrue(all(item.get("book_title_context_match") for item in applied))
        self.assertEqual(
            [(segment.start_time, segment.end_time) for segment in corrected.segments if segment.text == "Niulai"],
            [(200, 400), (1700, 1900)],
        )

    def test_scope_rejected_high_signal_title_candidate_reaches_review_artifact(self):
        frozen = ASRDataSeg("Yulai appears.", 100, 500)
        frozen.subtitle_id = "S0001"
        artifact = build_article_asr_review_artifact(
            [
                {
                    "candidate_id": "candidate-yulai",
                    "applied": False,
                    "result": "review_only",
                    "reason": "ordinary_text_not_article_proper_noun_scope",
                    "entity_gate_passed": True,
                    "final_confidence": 0.84,
                    "start_time": 100,
                    "end_time": 300,
                    "original_text": "Yulai",
                    "candidate_text": "Niulai",
                    "candidate_token_count": 1,
                    "original_token_count": 1,
                    "source_key": "books_and_works",
                    "category": "film",
                    "evidence": {"evidence_sentence": 'The film "Niulai" opened.'},
                }
            ],
            [frozen],
            word_ledger_hash="ledger-hash",
            source_file_hash="source-hash",
        )

        self.assertEqual(artifact["item_count"], 1)
        self.assertEqual(artifact["items"][0]["subtitle_ids"], ["S0001"])
        self.assertEqual(artifact["items"][0]["suggested_text"], "Niulai")

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
            ARTICLE_ANALYSIS_META_KEY: {
                "article_text_hash": article_text_hash("Cached summary text."),
                "prompt_hash": article_analysis_prompt_hash(),
                "analysis_prompt_hash": article_analysis_prompt_hash(),
                "analysis_prompt_policy_version": ARTICLE_ANALYSIS_PROMPT_POLICY_VERSION,
                "analysis_cache_key": article_analysis_cache_key("Cached summary text."),
            },
        }

        context = analyze_article_text(
            "Cached summary text.",
            type("LLMConfig", (), {"base_url": "", "api_key": "", "model": "deepseek-v4-flash"})(),
            cache_manager=FakeCache(json.dumps(cached_payload, ensure_ascii=False)),
        )

        self.assertTrue(context[ARTICLE_ANALYSIS_META_KEY]["cache_used"])
        self.assertEqual(context["summary"], "Cached summary")
        self.assertEqual(
            context[ARTICLE_ANALYSIS_META_KEY]["article_text_hash"],
            article_text_hash("Cached summary text."),
        )
        self.assertEqual(
            context[ARTICLE_ANALYSIS_META_KEY]["analysis_prompt_hash"],
            article_analysis_prompt_hash(),
        )
        self.assertEqual(
            context[ARTICLE_ANALYSIS_META_KEY]["analysis_prompt_policy_version"],
            ARTICLE_ANALYSIS_PROMPT_POLICY_VERSION,
        )

    def test_article_analysis_cache_key_includes_prompt_policy_identity(self):
        article = "The same article text."

        current = article_analysis_cache_key(article)
        changed_policy = article_analysis_cache_key(
            article,
            prompt_policy_version="article-context-analysis-test-version",
        )
        changed_prompt = article_analysis_cache_key(
            article,
            prompt="A materially different analysis prompt.",
        )

        self.assertNotEqual(current, changed_policy)
        self.assertNotEqual(current, changed_prompt)

    def test_overlapping_candidates_keep_highest_score_for_same_range(self):
        low = _candidate(
            "candidate-1",
            10,
            12,
            "New York",
            "New York Times",
            0.86,
        )
        high = _candidate(
            "candidate-2",
            10,
            12,
            "New York",
            "New York Fed",
            0.93,
        )

        selected, rejected = _resolve_overlapping_article_correction_candidates([low, high])

        self.assertEqual([item["candidate_id"] for item in selected], ["candidate-2"])
        self.assertEqual(rejected[0]["reason"], "overlapping_candidate")
        self.assertEqual(rejected[0]["kept_candidate_id"], "candidate-2")
        self.assertEqual(rejected[0]["rejected_candidate_id"], "candidate-1")

    def test_contained_and_crossing_candidates_apply_only_one_deterministically(self):
        long = _candidate("candidate-1", 20, 23, "Sam Bankman", "Sam Bankman-Fried", 0.91)
        short = _candidate("candidate-2", 21, 23, "Bankman Fried", "Sam Bankman-Fried", 0.9)
        crossing = _candidate("candidate-3", 22, 24, "Fried said", "Sam Bankman-Fried", 0.89)

        selected, rejected = _resolve_overlapping_article_correction_candidates(
            [crossing, short, long]
        )
        selected_again, rejected_again = _resolve_overlapping_article_correction_candidates(
            [long, crossing, short]
        )

        self.assertEqual([item["candidate_id"] for item in selected], ["candidate-1"])
        self.assertEqual([item["candidate_id"] for item in selected_again], ["candidate-1"])
        self.assertEqual({item["rejected_candidate_id"] for item in rejected}, {"candidate-2", "candidate-3"})
        self.assertEqual(
            {item["rejected_candidate_id"] for item in rejected_again},
            {"candidate-2", "candidate-3"},
        )

    def test_adjacent_canonical_prefix_and_suffix_overlap_is_deduped(self):
        segments = [
            _word("First", 0, 100, 0, 1),
            _word("Bill", 100, 200, 1, 2),
            _corrected_word("Bill Gurley,", 200, 300, 2, 3, "Bill Gurley"),
            _word("survey", 400, 500, 3, 4),
            _word("by", 500, 600, 4, 5),
            _word("the", 600, 700, 5, 6),
            _corrected_word("New York Fed", 700, 900, 6, 8, "New York Fed"),
            _word("Fed", 900, 1000, 8, 9),
            _word("found", 1000, 1100, 9, 10),
        ]

        corrected, logs = _dedupe_adjacent_canonical_entity_overlap(segments)
        texts = [seg.text for seg in corrected]

        self.assertIn("Bill Gurley,", texts)
        self.assertIn("New York Fed", texts)
        self.assertNotIn("Bill", texts)
        self.assertNotIn("Fed", texts)
        self.assertEqual(
            " ".join(texts),
            "First Bill Gurley, survey by the New York Fed found",
        )
        bill = next(seg for seg in corrected if seg.text == "Bill Gurley,")
        fed = next(seg for seg in corrected if seg.text == "New York Fed")
        self.assertEqual((bill.start_time, bill.end_time), (100, 300))
        self.assertEqual((fed.start_time, fed.end_time), (700, 1000))
        self.assertEqual(len(logs), 2)

    def test_adjacent_canonical_overlap_examples_without_hardcoded_names(self):
        context = {
            "people": [
                {"canonical_name": "Sam Bankman-Fried", "aliases": [], "category": "person"},
                {"canonical_name": "Maya Angelou", "aliases": [], "category": "person"},
                {"canonical_name": "Benjamin Todd", "aliases": [], "category": "person"},
            ]
        }
        raw = [
            ASRDataSeg("Sam", 0, 100),
            ASRDataSeg("Bankman-Fried.", 100, 200),
            ASRDataSeg("Maya", 300, 400),
            ASRDataSeg("Angelou", 400, 500),
            ASRDataSeg("Benjamin", 600, 700),
            ASRDataSeg("Todd.", 700, 800),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads((Path(tmp) / "correction_log.json").read_text(encoding="utf-8"))

        texts = [seg.text for seg in corrected.segments]
        self.assertEqual(texts, ["Sam Bankman-Fried.", "Maya Angelou", "Benjamin Todd."])
        self.assertTrue(
            any(item["reason"] == "adjacent_canonical_entity_overlap_deduped" for item in logs)
        )

    def test_dedupe_does_not_delete_general_adjacent_repeated_words(self):
        raw = [
            ASRDataSeg("very", 0, 100),
            ASRDataSeg("very", 100, 200),
            ASRDataSeg("important", 200, 300),
            ASRDataSeg("had", 400, 500),
            ASRDataSeg("had", 500, 600),
            ASRDataSeg("no", 600, 700),
            ASRDataSeg("effect", 700, 800),
        ]

        corrected = self._correct(raw)

        self.assertEqual([seg.text for seg in corrected.segments], [seg.text for seg in raw])
        self.assertEqual(
            [(seg.start_time, seg.end_time) for seg in corrected.segments],
            [(seg.start_time, seg.end_time) for seg in raw],
        )

    def test_exact_supported_alias_surface_is_not_canonicalized(self):
        context = enrich_article_context_with_evidence(
            {
                "places": [
                    {
                        "canonical_name": "United States",
                        "aliases": ["America"],
                        "category": "country",
                    }
                ]
            },
            "The United States is also known as America.",
        )
        alias_details = context["places"][0]["alias_details"]
        self.assertTrue(
            any(
                detail.get("alias") == "America" and detail.get("in_article")
                for detail in alias_details
            )
        )
        raw = [ASRDataSeg("America.", 100, 620)]

        corrected = self._correct_with_context(raw, context)

        self.assertEqual([segment.text for segment in corrected.segments], ["America."])
        self.assertEqual(
            [(segment.start_time, segment.end_time) for segment in corrected.segments],
            [(100, 620)],
        )

    def test_article_alias_cannot_replace_standalone_yes_discourse_marker(self):
        context = {
            "places": [
                {
                    "canonical_name": "United States",
                    "aliases": ["US"],
                    "category": "country",
                }
            ]
        }
        raw = [
            ASRDataSeg("Yes,", 100, 420),
            ASRDataSeg("exactly.", 420, 800),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            corrected = apply_article_asr_corrections(
                ASRData(raw),
                context,
                output_dir=Path(tmp),
            )
            logs = json.loads(
                (Path(tmp) / "correction_log.json").read_text(encoding="utf-8")
            )

        self.assertEqual(
            [segment.text for segment in corrected.segments],
            ["Yes,", "exactly."],
        )
        yes_candidates = [
            item for item in logs if item.get("original_text") == "Yes,"
        ]
        self.assertTrue(yes_candidates)
        self.assertTrue(all(not item.get("applied") for item in yes_candidates))
        self.assertTrue(
            all(
                item.get("reason") == "contains_function_word_or_discourse_marker"
                for item in yes_candidates
            )
        )

    def test_rejected_file_records_overlapping_candidate(self):
        context = {"organisations": [{"canonical_name": "New York Fed", "aliases": [], "category": "organisation"}]}
        raw = [
            ASRDataSeg("by", 0, 100),
            ASRDataSeg("the", 100, 200),
            ASRDataSeg("New", 200, 300),
            ASRDataSeg("York", 300, 400),
            ASRDataSeg("Fed", 400, 500),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            apply_article_asr_corrections(ASRData(raw), context, output_dir=Path(tmp))
            rejected = json.loads((Path(tmp) / "correction_rejected.json").read_text(encoding="utf-8"))
            log = json.loads((Path(tmp) / "correction_log.json").read_text(encoding="utf-8"))

        overlap_items = [item for item in rejected if item.get("reason") == "overlapping_candidate"]
        self.assertTrue(overlap_items)
        applied = [item for item in log if item.get("applied") and item.get("reason") == "high_confidence_article_glossary_match"]
        self.assertTrue(all("start_word_index" in item and "end_word_index" in item for item in applied))


def _candidate(
    candidate_id,
    start,
    end,
    original,
    canonical,
    score,
):
    return {
        "candidate_id": candidate_id,
        "start_word_index": start,
        "end_word_index": end,
        "original_words": original.split(),
        "original_text": original,
        "corrected_text": canonical,
        "candidate_text": canonical,
        "canonical_name": canonical,
        "final_confidence": score,
        "confidence": score,
        "article_entity_present": True,
        "evidence": {"evidence_sentence": canonical},
    }


def _word(text, start_time, end_time, start_index, end_index):
    segment = ASRDataSeg(text, start_time, end_time)
    segment._article_word_range = (start_index, end_index)
    return segment


def _corrected_word(text, start_time, end_time, start_index, end_index, canonical):
    segment = _word(text, start_time, end_time, start_index, end_index)
    segment._article_correction = {
        "candidate_id": f"test-{start_index}-{end_index}",
        "canonical_name": canonical,
        "candidate_text": canonical,
        "confidence": 0.99,
        "final_confidence": 0.99,
        "category": "person",
        "source_key": "people",
        "source_glossary": {"canonical_name": canonical, "category": "person"},
    }
    return segment


if __name__ == "__main__":
    unittest.main()
