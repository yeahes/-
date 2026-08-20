import tempfile
import unittest
import json
from pathlib import Path

from app.core.article_context import (
    ARTICLE_ANALYSIS_META_KEY,
    ARTICLE_ANALYSIS_PROMPT_POLICY_VERSION,
    apply_article_asr_corrections,
    article_analysis_cache_key,
    article_analysis_prompt_hash,
    article_text_hash,
    build_translation_context_prompt,
)
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.entities import SubtitleConfig, SubtitleTask
from app.core.output_paths import (
    containing_media_result_dir,
    media_result_dir,
    media_result_manual_package_dir,
    media_result_quality_dir,
    media_result_subtitle_dir,
    media_result_video_dir,
)
from app.core.task_factory import TaskFactory
from app.core.subtitle_processor.manual_final_subtitle_editor import (
    ManualFinalSubtitleSession,
)
from app.core.subtitle_processor.stable_artifacts import (
    file_sha256,
    find_stable_manifest_for_artifact,
    stable_artifact_dir,
)


def _article_analysis_meta(article_text: str) -> dict:
    prompt_hash = article_analysis_prompt_hash()
    return {
        "article_text_hash": article_text_hash(article_text),
        "prompt_hash": prompt_hash,
        "analysis_prompt_hash": prompt_hash,
        "analysis_prompt_policy_version": ARTICLE_ANALYSIS_PROMPT_POLICY_VERSION,
        "analysis_cache_key": article_analysis_cache_key(article_text),
    }
from app.thread.subtitle_thread import SubtitleThread


class TaskContextContractTests(unittest.TestCase):
    def test_article_review_ids_are_bound_before_final_timing_shift(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            correction_log = root / "correction_log.json"
            correction_log.write_text(
                json.dumps(
                    [
                        {
                            "candidate_id": "candidate-1",
                            "original_text": "Felugia",
                            "candidate_text": "Fulujia",
                            "original_token_count": 1,
                            "candidate_token_count": 1,
                            "final_confidence": 0.8167,
                            "start_time": 100,
                            "end_time": 300,
                            "source_key": "companies",
                            "category": "company",
                            "entity_gate_passed": True,
                            "applied": False,
                            "result": "review_only",
                            "reason": "below_high_confidence_threshold",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            frozen = ASRDataSeg("Felugia expanded.", 0, 500)
            frozen.subtitle_id = "S0001"
            prepared = SubtitleThread._prepare_article_asr_review_artifact(
                root,
                ASRData([frozen]),
                correction_ran=True,
            )

            # Final alignment may move cue time. The already-frozen ID remains
            # authoritative and only the final ledger hash is rebound.
            frozen.start_time = 5000
            frozen.end_time = 6000
            report_path = root / "episode-coverage-report.txt"
            artifact_dir = stable_artifact_dir(report_path)
            artifact_dir.mkdir()
            (artifact_dir / "word-ledger.json").write_text(
                json.dumps({"hash": "final-ledger"}),
                encoding="utf-8",
            )
            SubtitleThread._write_article_asr_review_artifact(
                str(report_path),
                prepared,
            )

            published = json.loads(
                (artifact_dir / "article-asr-correction-review.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(published["word_ledger_hash"], "final-ledger")
            self.assertEqual(published["items"][0]["subtitle_ids"], ["S0001"])

    def test_media_result_dir_is_stable_for_source_and_owned_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "episode.m4a"
            expected = Path(temp_dir) / "episode-处理结果"

            self.assertEqual(media_result_dir(source), expected)
            self.assertEqual(media_result_dir(expected), expected)
            self.assertEqual(
                containing_media_result_dir(expected / "字幕文件" / "双语字幕.srt"),
                expected,
            )
            self.assertIsNone(containing_media_result_dir(source))
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
            self.assertEqual(
                media_result_dir(expected / "字幕文件" / "双语字幕.srt"),
                expected,
            )
            self.assertEqual(media_result_subtitle_dir(source), expected / "字幕文件")
            self.assertEqual(media_result_quality_dir(source), expected / "质检报告")
            self.assertEqual(media_result_video_dir(source), expected / "视频成片")
            self.assertEqual(
                media_result_manual_package_dir(source),
                expected / "人工终稿字幕包",
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

            expected = media_result_video_dir(source)
            self.assertEqual(Path(formal.output_path).parent, expected)
            self.assertEqual(Path(draft.output_path).parent, expected)

    def test_layout_v2_exports_and_manifest_lookup_are_scoped_to_one_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "episode.m4a"
            result_dir = media_result_dir(source)
            subtitle_dir = media_result_subtitle_dir(source)
            package_dir = media_result_manual_package_dir(source)
            subtitle_dir.mkdir(parents=True)
            package_dir.mkdir(parents=True)

            tracked = subtitle_dir / "episode-原文在上双语字幕.srt"
            tracked.write_text("tracked", encoding="utf-8")
            unrelated = subtitle_dir / "unrelated.srt"
            unrelated.write_text("unrelated", encoding="utf-8")
            manifest_path = package_dir / "stable-final-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 4,
                        "source_subtitle_paths": {
                            "named_bilingual_original_top_srt": str(tracked),
                        },
                        "source_subtitle_paths_sha256": {
                            "named_bilingual_original_top_srt": file_sha256(tracked),
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                find_stable_manifest_for_artifact(tracked),
                manifest_path.resolve(),
            )
            self.assertIsNone(find_stable_manifest_for_artifact(unrelated))
            self.assertEqual(
                ManualFinalSubtitleSession.find_manifest_for_subtitle(tracked),
                manifest_path.resolve(),
            )
            self.assertIsNone(
                ManualFinalSubtitleSession.find_manifest_for_subtitle(unrelated)
            )
            self.assertEqual(containing_media_result_dir(tracked), result_dir)

    def test_transcribe_task_owns_source_audio_and_article_state(self):
        context = {
            "summary": "Current article",
            ARTICLE_ANALYSIS_META_KEY: _article_analysis_meta("Article"),
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
                ARTICLE_ANALYSIS_META_KEY: _article_analysis_meta("Article A"),
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
                ARTICLE_ANALYSIS_META_KEY: _article_analysis_meta("Article A"),
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
            self.assertEqual(thread.task.article_context_data["summary"], "Analysis for A")

    def test_subtitle_retry_rebuild_inherits_context_only_for_same_input(self):
        previous = TaskFactory.create_subtitle_task(
            "episode.srt",
            video_path="episode.m4a",
            need_next_task=True,
            source_audio_path="source-episode.m4a",
            article_reference_text="Article A",
            article_context_data={"summary": "Analysis A"},
            use_article_reference_assist=True,
            use_article_translation_terms=True,
            require_manual_review_before_synthesis=True,
        )

        retry = TaskFactory.recreate_subtitle_task(
            previous,
            file_path="episode.srt",
        )

        self.assertEqual(retry.video_path, previous.video_path)
        self.assertEqual(retry.need_next_task, previous.need_next_task)
        self.assertEqual(retry.source_audio_path, previous.source_audio_path)
        self.assertEqual(retry.article_reference_text, previous.article_reference_text)
        self.assertIs(retry.article_context_data, previous.article_context_data)
        self.assertTrue(retry.use_article_reference_assist)
        self.assertTrue(retry.use_article_translation_terms)
        self.assertTrue(retry.require_manual_review_before_synthesis)

        unrelated = TaskFactory.recreate_subtitle_task(
            previous,
            file_path="another-episode.srt",
        )
        self.assertIsNone(unrelated.video_path)
        self.assertIsNone(unrelated.source_audio_path)
        self.assertEqual(unrelated.article_reference_text, "")
        self.assertIsNone(unrelated.article_context_data)
        self.assertFalse(unrelated.use_article_reference_assist)
        self.assertFalse(unrelated.use_article_translation_terms)
        self.assertFalse(unrelated.require_manual_review_before_synthesis)

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
                    **_article_analysis_meta(article),
                    "cache_used": True,
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

    def test_translation_context_injects_only_terms_hit_by_current_source(self):
        context = {
            "title": "AI competition",
            "summary": "A short article summary.",
            "technical_terms": [
                {
                    "canonical_name": "haigui",
                    "chinese_name": "海归",
                    "aliases": ["returnee"],
                    "category": "term",
                },
                {
                    "canonical_name": "Higee",
                    "chinese_name": "海归",
                    "aliases": [],
                    "category": "term",
                },
            ],
        }
        matched = build_translation_context_prompt(
            context,
            source_text="The haigui strategy.",
        )
        self.assertIn("haigui -> 海归", matched)
        self.assertNotIn("Higee -> 海归", matched)

        unmatched = build_translation_context_prompt(
            context,
            source_text="The domestic strategy.",
        )
        self.assertNotIn("Preferred glossary:", unmatched)
        self.assertIn("Article summary: A short article summary.", unmatched)


if __name__ == "__main__":
    unittest.main()
