import tempfile
import unittest
from pathlib import Path

from app.core.article_context import (
    ARTICLE_ANALYSIS_META_KEY,
    apply_article_asr_corrections,
    article_text_hash,
    build_translation_context_prompt,
)
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.entities import SubtitleConfig, SubtitleTask
from app.core.output_paths import media_result_dir
from app.core.task_factory import TaskFactory
from app.thread.subtitle_thread import SubtitleThread


class TaskContextContractTests(unittest.TestCase):
    def test_media_result_dir_is_stable_for_source_and_owned_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "episode.m4a"
            expected = Path(temp_dir) / "episode-处理结果"

            self.assertEqual(media_result_dir(source), expected)
            self.assertEqual(
                media_result_dir(expected / "人工终稿字幕包" / "episode-尾部裁剪.m4a"),
                expected,
            )
            self.assertEqual(
                media_result_dir(
                    source,
                    output_anchor=Path(temp_dir) / "reports" / "anchor.m4a",
                ),
                Path(temp_dir) / "reports" / "episode-处理结果",
            )

    def test_synthesis_outputs_share_the_media_result_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "episode.m4a"
            formal = TaskFactory.create_synthesis_task(
                str(source),
                "stable-final-manifest.json",
            )
            draft = TaskFactory.create_synthesis_task(
                str(source),
                "stable-final-manifest.json",
                manual_draft_mode=True,
            )

            expected = media_result_dir(source)
            self.assertEqual(Path(formal.output_path).parent, expected)
            self.assertEqual(Path(draft.output_path).parent, expected)

    def test_transcribe_task_owns_source_audio_and_article_state(self):
        context = {
            "summary": "Current article",
            ARTICLE_ANALYSIS_META_KEY: {"prompt_hash": article_text_hash("Article")},
        }

        task = TaskFactory.create_transcribe_task(
            "input.m4a",
            need_next_task=True,
            source_audio_path="original.m4a",
            article_reference_text="Article",
            article_context_data=context,
            use_article_reference_assist=True,
            use_article_translation_terms=True,
        )

        self.assertEqual(task.source_audio_path, "original.m4a")
        self.assertEqual(task.article_reference_text, "Article")
        self.assertIs(task.article_context_data, context)
        self.assertTrue(task.use_article_reference_assist)
        self.assertTrue(task.use_article_translation_terms)

    def test_subtitle_stage_discards_context_for_different_article(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            context = {
                "summary": "Analysis for A",
                ARTICLE_ANALYSIS_META_KEY: {
                    "prompt_hash": article_text_hash("Article A")
                },
            }
            thread = SubtitleThread.__new__(SubtitleThread)
            thread.task = SubtitleTask(
                output_path=str(Path(temp_dir) / "output.srt"),
                article_reference_text="Article B",
                article_context_data=context,
                use_article_translation_terms=True,
            )

            resolved = thread._resolve_article_context(
                SubtitleConfig(),
                Path(temp_dir),
            )

            self.assertEqual(resolved["summary"], "")

    def test_subtitle_stage_keeps_context_for_same_article(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            context = {
                "summary": "Analysis for A",
                ARTICLE_ANALYSIS_META_KEY: {
                    "prompt_hash": article_text_hash("Article A")
                },
            }
            thread = SubtitleThread.__new__(SubtitleThread)
            thread.task = SubtitleTask(
                output_path=str(Path(temp_dir) / "output.srt"),
                article_reference_text="Article A",
                article_context_data=context,
                use_article_translation_terms=True,
            )

            resolved = thread._resolve_article_context(
                SubtitleConfig(),
                Path(temp_dir),
            )

            self.assertEqual(resolved["summary"], "Analysis for A")

    def test_subtitle_stage_enriches_cached_entities_before_asr_and_translation(self):
        article = (
            "Liang Wenfeng discussed returnees known as haigui or sea turtles, "
            "and many haigui graduates later return to China."
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            context = {
                "people": [
                    {
                        "canonical_name": "Liang Wenfeng",
                        "chinese_name": "梁文锋",
                        "aliases": [],
                        "category": "person",
                    }
                ],
                "technical_terms": [
                    {
                        "canonical_name": "haigui",
                        "chinese_name": "海归",
                        "aliases": ["sea turtles"],
                        "category": "term",
                    }
                ],
                ARTICLE_ANALYSIS_META_KEY: {
                    "cache_used": True,
                    "prompt_hash": article_text_hash(article),
                },
            }
            thread = SubtitleThread.__new__(SubtitleThread)
            thread.task = SubtitleTask(
                output_path=str(Path(temp_dir) / "output.srt"),
                article_reference_text=article,
                article_context_data=context,
                use_article_reference_assist=True,
            )

            resolved = thread._resolve_article_context(
                SubtitleConfig(),
                Path(temp_dir),
            )
            corrected = apply_article_asr_corrections(
                ASRData(
                    [
                        ASRDataSeg("Li", 100, 200),
                        ASRDataSeg("Yang", 200, 300),
                        ASRDataSeg("Wenfing", 300, 500),
                        ASRDataSeg("and", 500, 600),
                        ASRDataSeg("Higee", 600, 800),
                    ]
                ),
                resolved,
                output_dir=Path(temp_dir),
            )

            term = resolved["technical_terms"][0]
            self.assertTrue(term["canonical_in_article"])
            self.assertTrue(term["evidence"]["evidence_sentence"])
            self.assertEqual(
                [segment.text for segment in corrected.segments],
                ["Liang Wenfeng", "and", "haigui"],
            )
            self.assertEqual(
                [(segment.start_time, segment.end_time) for segment in corrected.segments],
                [(100, 500), (500, 600), (600, 800)],
            )
            translation_prompt = build_translation_context_prompt(resolved)
            self.assertIn("Liang Wenfeng -> 梁文锋", translation_prompt)
            self.assertIn("haigui -> 海归", translation_prompt)


if __name__ == "__main__":
    unittest.main()
