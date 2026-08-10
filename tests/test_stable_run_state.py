"""Regression tests for durable subtitle-run state and safe resume planning."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.core.subtitle_processor.stable_run_state import (
    StableRunStateStore,
    build_stable_run_fingerprint,
    format_stage_progress,
)
from app.core.article_context import ARTICLE_ASR_CORRECTION_POLICY_VERSION
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.thread.subtitle_thread import SubtitleThread


class _Config:
    llm_model = "deepseek-v4-flash"
    translator_service = "openai"
    need_translate = True
    need_optimize = False
    need_reflect = False
    thread_num = 4
    batch_size = 10
    split_type = "sentence"
    subtitle_layout = "原文在上"
    max_word_count_cjk = 12
    max_word_count_english = 18
    need_split = True
    target_language = "简体中文"
    need_remove_punctuation = False
    need_screen_subtitle_edit = True
    screen_subtitle_stable_mode = True
    screen_subtitle_chinese_polish = False
    screen_subtitle_max_cjk = 24
    screen_subtitle_max_english = 16
    screen_subtitle_allocation_max_concurrency = 3
    screen_subtitle_allocation_batch_size = 16
    custom_prompt_text = ""


def _fingerprint(source: Path, **changes):
    values = {
        "article_reference_text": "Reference article.",
        "article_context_data": {"title": "Reference"},
        "use_article_reference_assist": True,
        "use_article_translation_terms": True,
        "alignment_backend": "whisperx-time-only",
        "custom_prompt_text": "",
    }
    values.update(changes)
    return build_stable_run_fingerprint(
        subtitle_path=source,
        subtitle_config=_Config(),
        **values,
    )


def _complete_safe_stages(store: StableRunStateStore, root: Path) -> None:
    context = root / "article_context.json"
    corrected = root / "asr_corrected.json"
    context.write_text('{"title":"Reference"}', encoding="utf-8")
    corrected.write_text('{"1":{"original_subtitle":"Hello"}}', encoding="utf-8")
    store.begin_stage("article_context")
    store.complete_stage("article_context", elapsed_seconds=1.2, artifact_paths=[context])
    store.begin_stage("article_asr_correction")
    store.complete_stage(
        "article_asr_correction", elapsed_seconds=2.4, artifact_paths=[corrected]
    )
    store.begin_stage("screen_subtitle_edit")


def test_matching_input_contract_reuses_only_verified_safe_stages():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "input.srt"
        source.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        fingerprint = _fingerprint(source)
        store = StableRunStateStore(root)
        store.start(fingerprint, store.plan_resume(fingerprint))
        _complete_safe_stages(store, root)

        plan = StableRunStateStore(root).plan_resume(fingerprint)

        assert plan.compatible is True
        assert plan.previous_status == "running"
        assert plan.reusable_stages == ("article_context", "article_asr_correction")


def test_contract_changes_reject_resume_for_article_model_prompt_and_alignment():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "input.srt"
        source.write_text("input", encoding="utf-8")
        fingerprint = _fingerprint(source)
        store = StableRunStateStore(root)
        store.start(fingerprint, store.plan_resume(fingerprint))
        _complete_safe_stages(store, root)

        changed_article = _fingerprint(source, article_reference_text="Different article.")
        assert not StableRunStateStore(root).plan_resume(changed_article).compatible

        changed_alignment = _fingerprint(source, alignment_backend="stable-ts")
        assert not StableRunStateStore(root).plan_resume(changed_alignment).compatible

        changed_prompt = _fingerprint(source, custom_prompt_text="different prompt")
        assert not StableRunStateStore(root).plan_resume(changed_prompt).compatible

        class ChangedModelConfig(_Config):
            llm_model = "different-model"

        changed_model = build_stable_run_fingerprint(
            subtitle_path=source,
            subtitle_config=ChangedModelConfig(),
            article_reference_text="Reference article.",
            article_context_data={"title": "Reference"},
            use_article_reference_assist=True,
            use_article_translation_terms=True,
            alignment_backend="whisperx-time-only",
        )
        assert not StableRunStateStore(root).plan_resume(changed_model).compatible


def test_tampered_or_missing_artifact_is_not_reused_and_state_stays_valid_json():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "input.srt"
        source.write_text("input", encoding="utf-8")
        fingerprint = _fingerprint(source)
        store = StableRunStateStore(root)
        store.start(fingerprint, store.plan_resume(fingerprint))
        _complete_safe_stages(store, root)

        (root / "asr_corrected.json").write_text("tampered", encoding="utf-8")
        plan = StableRunStateStore(root).plan_resume(fingerprint)

        assert plan.compatible is True
        assert plan.reusable_stages == ("article_context",)
        persisted = json.loads((root / "run-state.json").read_text(encoding="utf-8"))
        assert persisted["stages"]["screen_subtitle_edit"]["status"] == "running"


def test_progress_text_is_human_readable_and_signal_payload_remains_two_values():
    status = format_stage_progress(
        "中文分配",
        completed=8,
        total=20,
        cache_hits=6,
        retries=1,
        elapsed_seconds=194,
        eta_seconds=72,
    )

    assert status == "中文分配，第 8/20 批，缓存命中 6，重试 1，已用时 03:14，预计剩余 01:12"

    class _Progress:
        def __init__(self):
            self.events = []

        def emit(self, *args):
            self.events.append(args)

    thread = SubtitleThread.__new__(SubtitleThread)
    thread.progress = _Progress()
    thread.tr = lambda value: value
    thread._active_stage = "screen_subtitle_edit"
    thread._active_stage_started_at = 10.0
    with patch(
        "app.thread.subtitle_thread.time.perf_counter",
        side_effect=(100.0, 130.0, 400.0, 410.0),
    ):
        thread._handle_screen_editor_progress(
            {
                "phase": "full_translation",
                "completed": 1,
                "total": 4,
                "cache_hits": 1,
                "retries": 0,
            }
        )
        thread._handle_screen_editor_progress(
            {
                "phase": "allocation",
                "completed": 1,
                "total": 4,
                "cache_hits": 1,
                "retries": 0,
            }
        )
    assert all(len(event) == 2 for event in thread.progress.events)
    assert [event[0] for event in thread.progress.events] == sorted(
        event[0] for event in thread.progress.events
    )
    assert "缓存命中 1" in thread.progress.events[-1][1]
    assert "已用时 00:10" in thread.progress.events[-1][1]
    assert "预计剩余 00:30" in thread.progress.events[-1][1]


def test_resume_recomputes_only_stale_article_asr_correction_policy():
    class _ResumePlan:
        @staticmethod
        def can_reuse(stage):
            return stage in {"article_context", "article_asr_correction"}

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "article_context.json").write_text(
            '{"title":"Reference"}',
            encoding="utf-8",
        )
        corrected = ASRData([ASRDataSeg("Ms Hao", 100, 500)])
        (root / "asr_corrected.json").write_text(
            json.dumps(corrected.to_json(), ensure_ascii=False),
            encoding="utf-8",
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread._resume_plan = _ResumePlan()
        thread._resume_stage_records = {
            "article_context": {"details": {}},
            "article_asr_correction": {
                "details": {"policy_version": "article-asr-correction-v1"}
            },
        }

        assert thread._load_resume_article_context(root)["title"] == "Reference"
        assert thread._load_resume_asr_correction(root) is None

        thread._resume_stage_records["article_asr_correction"]["details"][
            "policy_version"
        ] = ARTICLE_ASR_CORRECTION_POLICY_VERSION
        resumed = thread._load_resume_asr_correction(root)

        assert resumed is not None
        assert [segment.text for segment in resumed.segments] == ["Ms Hao"]


if __name__ == "__main__":
    test_matching_input_contract_reuses_only_verified_safe_stages()
    test_contract_changes_reject_resume_for_article_model_prompt_and_alignment()
    test_tampered_or_missing_artifact_is_not_reused_and_state_stays_valid_json()
    test_progress_text_is_human_readable_and_signal_payload_remains_two_values()
    test_resume_recomputes_only_stale_article_asr_correction_policy()
    print("stable run state tests passed")
